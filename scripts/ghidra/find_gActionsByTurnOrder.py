#!/usr/bin/env python3
"""
Find gActionsByTurnOrder in Pokemon Run & Bun ROM.

Known addresses (confirmed):
  gBattleControllerExecFlags = 0x020233E0  (u32)
  gBattlersCount             = 0x020233E4  (u8)
  gBattlerByTurnOrder        = 0x020233F6  (u8[4])
  gCurrentTurnActionNumber   = 0x020233FA  (u8) = gBattlerByTurnOrder + 4
  gCurrentActionFuncId       = 0x020233FB  (u8) = gBattlerByTurnOrder + 5
  gBattleMons                = 0x020233FC  (struct array)
  gActiveBattler             = 0x020233DC  (u8)

In pokeemerald-expansion source (battle_main.c lines 154-162):
  EWRAM_DATA u32 gBattleControllerExecFlags = 0;    // 4 bytes
  EWRAM_DATA u8  gBattlersCount = 0;                // 1 byte (aligned to 4 -> pad 3)
  EWRAM_DATA u16 gBattlerPartyIndexes[4] = {0};     // 8 bytes
  EWRAM_DATA u8  gBattlerPositions[4] = {0};         // 4 bytes
  EWRAM_DATA u8  gActionsByTurnOrder[4] = {0};       // 4 bytes  <-- TARGET
  EWRAM_DATA u8  gBattlerByTurnOrder[4] = {0};       // 4 bytes
  EWRAM_DATA u8  gCurrentTurnActionNumber = 0;       // 1 byte
  EWRAM_DATA u8  gCurrentActionFuncId = 0;           // 1 byte
  EWRAM_DATA struct BattlePokemon gBattleMons[4];   // large

If the linker respects source order, the layout MIGHT be:
  0x020233E0 = gBattleControllerExecFlags (4 bytes)
  0x020233E4 = gBattlersCount (1 byte, padded to 4)
  0x020233E8 = gBattlerPartyIndexes (8 bytes)
  0x020233F0 = gBattlerPositions (4 bytes)
  0x020233F4 = gActionsByTurnOrder (4 bytes)  <-- if this were true, but...
  ...but gBattlerByTurnOrder is at 0x020233F6, not 0x020233F8.

This means the linker DID NOT pad gBattlerPositions or the layout is different.
Let's look at 0x020233F2 (gBattlerByTurnOrder-4) or other offsets.

Strategy:
1. Scan ROM literal pools for ALL addresses in 0x020233E0-0x020233F8
2. Cross-reference with known addresses to identify unknown ones
3. For promising candidates, analyze the functions that reference them to confirm
4. Look for patterns specific to gActionsByTurnOrder usage (LDRB with battler index,
   compared against B_ACTION_USE_MOVE=0, B_ACTION_USE_ITEM=1, B_ACTION_SWITCH=2, etc.)

No Ghidra needed -- reads the .gba file directly.
"""

import struct
import sys
from pathlib import Path
from collections import defaultdict

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known confirmed R&B addresses
KNOWN = {
    "gActiveBattler":             0x020233DC,  # u8
    "gBattleControllerExecFlags": 0x020233E0,  # u32
    "gBattlersCount":             0x020233E4,  # u8
    "gBattlerByTurnOrder":        0x020233F6,  # u8[4]
    "gCurrentTurnActionNumber":   0x020233FA,  # u8
    "gCurrentActionFuncId":       0x020233FB,  # u8
    "gBattleMons":                0x020233FC,  # struct array
    "gBattleTypeFlags":           0x020090E8,  # u32
    "gBattleResources":           0x02023A18,  # ptr
    "gPlayerParty":               0x02023A98,  # array
    "gEnemyParty":                0x02023CF0,  # array
}

KNOWN_SET = set(KNOWN.values())

# Source code context: variables between gBattleControllerExecFlags and gBattlerByTurnOrder
# From battle_main.c:
#   gBattlersCount (u8, 1 byte)
#   gBattlerPartyIndexes (u16[4], 8 bytes)
#   gBattlerPositions (u8[4], 4 bytes)
#   gActionsByTurnOrder (u8[4], 4 bytes)  <-- TARGET
# Total: 1+8+4+4 = 17 bytes, but with alignment: probably 4+8+4+4 = 20 bytes
# 0x020233E4 + 20 = 0x020233F8... but gBattlerByTurnOrder is at 0x020233F6
# So the gap is 0x020233F6 - 0x020233E4 = 18 bytes for {gBattlersCount, gBattlerPartyIndexes, gBattlerPositions, gActionsByTurnOrder}
# 1(count) + 8(partyIdx) + 4(positions) + 4(actions) = 17 bytes, packed to 18 = 0x12
# That would mean: gBattlersCount=E4, gBattlerPartyIndexes=E5(??), no that's wrong with u16 alignment
# More likely with alignment: count=E4(1byte padded to 2), partyIdx=E6(8 bytes), positions=EE(4 bytes), actions=F2(4 bytes)
# E4+2=E6, E6+8=EE, EE+4=F2, F2+4=F6 = gBattlerByTurnOrder. PERFECT!
# So gActionsByTurnOrder = 0x020233F2 (the original estimate)
#
# But user says "that seems wrong". Let's verify by ROM literal pool scan.


def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]


def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def find_all_literal_refs(rom_data, target_value):
    """Find all 4-byte aligned positions where target_value appears in ROM."""
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs


def find_function_start(rom_data, offset, max_back=2048):
    """Walk backward to find PUSH {..., LR} = 0xB5xx."""
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16(rom_data, pos)
        if (instr & 0xFF00) == 0xB500:
            return pos
    return None


def find_function_end(rom_data, func_start, max_size=2048):
    """Find function end: first POP {PC} or BX LR."""
    pos = func_start + 2
    limit = min(func_start + max_size, len(rom_data) - 2)
    while pos < limit:
        instr = read_u16(rom_data, pos)
        if (instr & 0xFF00) == 0xBD00:  # POP {..., PC}
            return pos + 2
        if instr == 0x4770:  # BX LR
            return pos + 2
        if (instr & 0xFE00) == 0xBC00 and not (instr & 0x100):
            if pos + 2 < limit:
                nxt = read_u16(rom_data, pos + 2)
                if (nxt & 0xFF80) == 0x4700:
                    return pos + 4
        if (instr & 0xF800) == 0xF000 and pos + 2 < limit:
            nxt = read_u16(rom_data, pos + 2)
            if (nxt & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return None


def decode_bl_target(rom_data, pos):
    """Decode THUMB BL at pos."""
    if pos + 4 > len(rom_data):
        return None
    hi = read_u16(rom_data, pos)
    lo = read_u16(rom_data, pos + 2)
    if (hi & 0xF800) != 0xF000 or (lo & 0xF800) != 0xF800:
        return None
    full = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    if full >= 0x400000:
        full -= 0x800000
    return ROM_BASE + pos + 4 + full


def get_ldr_pc_literals(rom_data, func_start, func_end):
    """Extract LDR Rd,[PC,#imm] literal pool values."""
    results = []
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        if (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_off)
                results.append((pos, rd, val, lit_off))
        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            nxt = read_u16(rom_data, pos + 2)
            if (nxt & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return results


COND_NAMES = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
              "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]

def disassemble_range(rom_data, start, end, max_instrs=200):
    """Disassemble THUMB code."""
    lines = []
    pos = start
    while pos < end and pos + 2 <= len(rom_data):
        if max_instrs is not None and len(lines) >= max_instrs:
            break
        instr = read_u16(rom_data, pos)
        addr = ROM_BASE + pos
        raw = f"{instr:04X}"
        mnem = ""

        if (instr & 0xFE00) == 0xB400:
            lr = (instr >> 8) & 1
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if lr: regs.append("LR")
            mnem = f"PUSH {{{', '.join(regs)}}}"
        elif (instr & 0xFE00) == 0xBC00:
            pc = (instr >> 8) & 1
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if pc: regs.append("PC")
            mnem = f"POP {{{', '.join(regs)}}}"
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            mnem = f"MOV R{rd}, #{imm} (0x{imm:02X})"
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7; imm = instr & 0xFF
            mnem = f"CMP R{rn}, #{imm} (0x{imm:02X})"
        elif (instr & 0xF800) == 0x3000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            mnem = f"ADD R{rd}, #{imm} (0x{imm:02X})"
        elif (instr & 0xF800) == 0x3800:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            mnem = f"SUB R{rd}, #{imm} (0x{imm:02X})"
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7; imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_off)
                mnem = f"LDR R{rd}, =0x{val:08X}"
            else:
                mnem = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            mnem = f"LDR R{rd}, [R{rn}, #{imm}]"
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            mnem = f"STR R{rd}, [R{rn}, #{imm}]"
        elif (instr & 0xF800) == 0x7800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            mnem = f"LDRB R{rd}, [R{rn}, #{imm}]"
        elif (instr & 0xF800) == 0x7000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            mnem = f"STRB R{rd}, [R{rn}, #{imm}]"
        elif (instr & 0xF800) == 0x8800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            mnem = f"LDRH R{rd}, [R{rn}, #{imm}]"
        elif (instr & 0xF800) == 0x8000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            mnem = f"STRH R{rd}, [R{rn}, #{imm}]"
        elif (instr & 0xFE00) == 0x5800:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"LDR R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5C00:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"LDRB R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5A00:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"LDRH R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5000:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"STR R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5400:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"STRB R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x1800:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"ADD R{rd}, R{rn}, R{rm}"
        elif (instr & 0xFE00) == 0x1A00:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"SUB R{rd}, R{rn}, R{rm}"
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7; rn = (instr >> 3) & 7; imm3 = (instr >> 6) & 7
            mnem = f"ADD R{rd}, R{rn}, #{imm3}"
        elif (instr & 0xFE00) == 0x1E00:
            rd = instr & 7; rn = (instr >> 3) & 7; imm3 = (instr >> 6) & 7
            mnem = f"SUB R{rd}, R{rn}, #{imm3}"
        elif (instr & 0xF800) == 0x0000 and instr != 0:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            mnem = f"LSL R{rd}, R{rm}, #{imm5}"
        elif (instr & 0xF800) == 0x0800:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            if imm5 == 0: imm5 = 32
            mnem = f"LSR R{rd}, R{rm}, #{imm5}"
        elif (instr & 0xF800) == 0x1000:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            if imm5 == 0: imm5 = 32
            mnem = f"ASR R{rd}, R{rm}, #{imm5}"
        elif (instr & 0xFC00) == 0x4000:
            op = (instr >> 6) & 0xF; rd = instr & 7; rm = (instr >> 3) & 7
            names = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                     "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            mnem = f"{names[op]} R{rd}, R{rm}"
        elif (instr & 0xFC00) == 0x4400:
            op = (instr >> 8) & 3; h1 = (instr >> 7) & 1; h2 = (instr >> 6) & 1
            rd = (instr & 7) | (h1 << 3); rm = ((instr >> 3) & 7) | (h2 << 3)
            ops = ["ADD","CMP","MOV","BX"]
            mnem = f"{ops[op]} R{rd}, R{rm}"
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF; soff = instr & 0xFF
            if soff >= 0x80: soff -= 0x100
            target = addr + 4 + soff * 2
            if cond < 0xF:
                mnem = f"{COND_NAMES[cond]} 0x{target:08X}"
            else:
                mnem = f"SVC #{instr & 0xFF}"
        elif (instr & 0xF800) == 0xE000:
            soff = instr & 0x7FF
            if soff >= 0x400: soff -= 0x800
            target = addr + 4 + soff * 2
            mnem = f"B 0x{target:08X}"
        elif (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            nxt = read_u16(rom_data, pos + 2)
            if (nxt & 0xF800) == 0xF800:
                target = decode_bl_target(rom_data, pos)
                raw = f"{instr:04X} {nxt:04X}"
                mnem = f"BL 0x{target:08X}"
                lines.append((pos, addr, raw, mnem))
                pos += 4
                continue
        elif (instr & 0xF800) == 0x9800:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            mnem = f"LDR R{rd}, [SP, #0x{imm:X}]"
        elif (instr & 0xF800) == 0x9000:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            mnem = f"STR R{rd}, [SP, #0x{imm:X}]"
        elif (instr & 0xFF00) == 0xB000:
            imm = (instr & 0x7F) * 4
            if instr & 0x80:
                mnem = f"SUB SP, #{imm}"
            else:
                mnem = f"ADD SP, #{imm}"
        elif instr == 0x46C0:
            mnem = "NOP"
        elif instr == 0x0000:
            mnem = "DATA 0x0000"
        else:
            mnem = f"??? 0x{instr:04X}"

        lines.append((pos, addr, raw, mnem))
        pos += 2
    return lines


def annotate_addr(val):
    """Return annotation for known addresses."""
    for name, addr in KNOWN.items():
        if val == addr:
            return f" <-- {name}"
    return ""


# =============================================================================
# APPROACH 1: Direct literal pool scan for addresses in the gap
# =============================================================================

def scan_gap_addresses(rom_data):
    """Scan ROM literal pools for ALL EWRAM addresses between
    gBattlersCount (0x020233E4) and gBattlerByTurnOrder (0x020233F6)."""

    print("=" * 78)
    print("  APPROACH 1: Literal pool scan for addresses in the gap")
    print("  Range: 0x020233E4 - 0x020233F6 (18 bytes)")
    print("=" * 78)
    print()

    # Scan for every possible address in the gap
    gap_start = 0x020233E4
    gap_end = 0x020233F6

    results = {}  # addr -> ref_count

    for target in range(gap_start, gap_end + 1):
        refs = find_all_literal_refs(rom_data, target)
        if refs:
            results[target] = len(refs)

    print(f"  Addresses found in gap 0x{gap_start:08X}-0x{gap_end:08X}:")
    print()
    for addr in sorted(results.keys()):
        count = results[addr]
        known = annotate_addr(addr)
        print(f"    0x{addr:08X}: {count:3d} ROM literal pool refs{known}")

    print()
    return results


# =============================================================================
# APPROACH 2: Wider scan around the battle variables cluster
# =============================================================================

def scan_wider_cluster(rom_data):
    """Scan a wider range for context: 0x02023380 - 0x02023440."""

    print("=" * 78)
    print("  APPROACH 2: Wider cluster scan")
    print("  Range: 0x02023380 - 0x02023440")
    print("=" * 78)
    print()

    results = {}
    for target in range(0x02023380, 0x02023440):
        refs = find_all_literal_refs(rom_data, target)
        if refs:
            results[target] = len(refs)

    # Group by known/unknown
    print(f"  {len(results)} addresses found with ROM literal pool refs:")
    print()
    for addr in sorted(results.keys()):
        count = results[addr]
        known = annotate_addr(addr)
        star = " ***" if addr not in KNOWN_SET and count >= 5 else ""
        print(f"    0x{addr:08X}: {count:3d} refs{known}{star}")

    print()
    return results


# =============================================================================
# APPROACH 3: Analyze functions that reference candidate addresses
# =============================================================================

def analyze_candidate(rom_data, candidate_addr, ref_count):
    """Analyze all functions that reference a candidate address to determine
    what variable it is."""

    refs = find_all_literal_refs(rom_data, candidate_addr)

    print(f"  Analyzing 0x{candidate_addr:08X} ({ref_count} refs):")
    print()

    # For each ref, find the containing function and analyze
    seen_funcs = set()
    func_infos = []

    for lit_off in refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start is None or func_start in seen_funcs:
            continue
        seen_funcs.add(func_start)

        func_end = find_function_end(rom_data, func_start)
        if func_end is None:
            func_end = func_start + 300

        func_addr = ROM_BASE + func_start + 1
        func_size = func_end - func_start

        # Get all literal pool values in this function
        lits = get_ldr_pc_literals(rom_data, func_start, func_end)
        lit_vals = set(v for _, _, v, _ in lits)

        # Check which known addresses this function also references
        also_refs = []
        for name, kaddr in sorted(KNOWN.items()):
            if kaddr in lit_vals and kaddr != candidate_addr:
                also_refs.append(name)

        func_infos.append({
            'start': func_start,
            'end': func_end,
            'addr': func_addr,
            'size': func_size,
            'lits': lits,
            'lit_vals': lit_vals,
            'also_refs': also_refs,
        })

    # Print summary of all referencing functions
    print(f"    {len(func_infos)} unique functions reference this address:")
    print()
    for info in sorted(func_infos, key=lambda x: x['addr']):
        also = f"  also refs: {', '.join(info['also_refs'])}" if info['also_refs'] else ""
        print(f"      0x{info['addr']:08X} ({info['size']:3d} bytes){also}")

    print()
    return func_infos


def analyze_access_pattern(rom_data, candidate_addr, func_infos):
    """Look at HOW the candidate address is accessed in each function.
    gActionsByTurnOrder is u8[4], so it should be accessed via LDRB/STRB with
    a register offset (base+index)."""

    print(f"    Access patterns for 0x{candidate_addr:08X}:")
    print()

    access_patterns = defaultdict(int)

    for info in func_infos[:20]:  # Limit to first 20 functions
        disasm = disassemble_range(rom_data, info['start'], info['end'], max_instrs=150)

        # Find instructions that load this address
        for i, (pos, addr, raw, mnem) in enumerate(disasm):
            if f"0x{candidate_addr:08X}" in mnem and "LDR" in mnem:
                # This instruction loads the address into a register
                # Parse "LDR Rn, =0x..." to get register number
                import re
                rd_match = re.search(r'LDR R(\d)', mnem)
                if not rd_match:
                    continue
                rd = int(rd_match.group(1))

                # Look at next 5 instructions for how this register is used
                for j in range(i+1, min(i+6, len(disasm))):
                    _, _, _, next_mnem = disasm[j]
                    if f"R{rd}" in next_mnem:
                        # What operation?
                        if "LDRB" in next_mnem and f"[R{rd}" in next_mnem:
                            access_patterns["LDRB [base, ...]"] += 1
                        elif "STRB" in next_mnem and f"[R{rd}" in next_mnem:
                            access_patterns["STRB [base, ...]"] += 1
                        elif "LDRH" in next_mnem and f"[R{rd}" in next_mnem:
                            access_patterns["LDRH [base, ...]"] += 1
                        elif "STRH" in next_mnem and f"[R{rd}" in next_mnem:
                            access_patterns["STRH [base, ...]"] += 1
                        elif "LDR " in next_mnem and f"[R{rd}" in next_mnem:
                            access_patterns["LDR [base, ...]"] += 1
                        elif "STR " in next_mnem and f"[R{rd}" in next_mnem:
                            access_patterns["STR [base, ...]"] += 1
                        elif "ADD" in next_mnem:
                            access_patterns["ADD (base+offset calc)"] += 1
                        break

    if access_patterns:
        for pattern, count in sorted(access_patterns.items(), key=lambda x: -x[1]):
            print(f"      {pattern}: {count}x")
    else:
        print(f"      (no clear patterns found)")
    print()
    return access_patterns


# =============================================================================
# APPROACH 4: Look for base+offset access patterns
# (compiler may use gBattlerByTurnOrder or nearby known address as base)
# =============================================================================

def scan_base_offset_access(rom_data):
    """gActionsByTurnOrder might not have its OWN literal pool entry.
    The compiler could access it via a known nearby address + offset.

    For example, if gBattlerByTurnOrder = 0x020233F6, the compiler might do:
      LDR R0, =0x020233F6  ; gBattlerByTurnOrder
      SUB R0, #4            ; gActionsByTurnOrder = gBattlerByTurnOrder - 4

    Or more commonly for co-located arrays:
      LDR R0, =0x020233F2  ; gActionsByTurnOrder (if it has its own literal)

    Or via the battle vars cluster base:
      LDR R0, =0x020233E0  ; gBattleControllerExecFlags (base)
      ADD R0, #0x12         ; offset to gActionsByTurnOrder
      LDRB R1, [R0, R2]    ; read gActionsByTurnOrder[battlerIndex]

    Let's check if gBattlerByTurnOrder refs ever access at negative offsets.
    """

    print("=" * 78)
    print("  APPROACH 4: Check base+offset access from gBattlerByTurnOrder")
    print("  (compiler might access gActionsByTurnOrder as gBattlerByTurnOrder-N)")
    print("=" * 78)
    print()

    bto_addr = KNOWN["gBattlerByTurnOrder"]
    refs = find_all_literal_refs(rom_data, bto_addr)

    print(f"  gBattlerByTurnOrder (0x{bto_addr:08X}): {len(refs)} literal pool refs")
    print()

    # For each function that references gBattlerByTurnOrder, check the disassembly
    # for patterns that also access gActionsByTurnOrder (base-4)
    seen_funcs = set()
    colocated_funcs = []

    for lit_off in refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start is None or func_start in seen_funcs:
            continue
        seen_funcs.add(func_start)

        func_end = find_function_end(rom_data, func_start)
        if func_end is None:
            func_end = func_start + 400

        func_addr = ROM_BASE + func_start + 1
        lits = get_ldr_pc_literals(rom_data, func_start, func_end)
        lit_vals = set(v for _, _, v, _ in lits)

        # Check if this function ALSO references any address in the gap
        gap_refs = [v for v in lit_vals if 0x020233E5 <= v <= 0x020233F5]

        if gap_refs:
            colocated_funcs.append({
                'addr': func_addr,
                'start': func_start,
                'end': func_end,
                'gap_refs': gap_refs,
                'all_lits': lit_vals,
            })

    if colocated_funcs:
        print(f"  Found {len(colocated_funcs)} functions that ref gBattlerByTurnOrder AND gap addresses:")
        print()
        for info in colocated_funcs:
            gap_str = ", ".join(f"0x{v:08X}" for v in sorted(info['gap_refs']))
            print(f"    0x{info['addr']:08X}: gap refs = [{gap_str}]")
    else:
        print("  No functions found that reference both gBattlerByTurnOrder and gap addresses.")

    print()

    # Now let's also look for SUB instructions right after loading gBattlerByTurnOrder
    print("  Checking for SUB/ADD offset patterns near gBattlerByTurnOrder loads:")
    print()

    seen_funcs2 = set()
    offset_patterns = []

    for lit_off in refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start is None or func_start in seen_funcs2:
            continue
        seen_funcs2.add(func_start)

        func_end = find_function_end(rom_data, func_start)
        if func_end is None:
            func_end = func_start + 400

        disasm = disassemble_range(rom_data, func_start, func_end, max_instrs=200)

        for i, (pos, addr, raw, mnem) in enumerate(disasm):
            if f"0x{bto_addr:08X}" in mnem and "LDR" in mnem:
                # Found a load of gBattlerByTurnOrder, check next instructions
                context = disasm[max(0,i-2):min(len(disasm),i+8)]
                has_sub = any("SUB" in m for _, _, _, m in context[2:])  # after the LDR
                has_neg_offset = any(("LDRB" in m and "#" in m) for _, _, _, m in context[2:])

                if has_sub or has_neg_offset:
                    func_addr = ROM_BASE + func_start + 1
                    context_str = " | ".join(m for _, _, _, m in context)
                    offset_patterns.append((func_addr, context_str))

    if offset_patterns:
        for fa, ctx in offset_patterns[:10]:
            print(f"    0x{fa:08X}: {ctx}")
    else:
        print("    No SUB/ADD offset patterns found near gBattlerByTurnOrder loads.")

    print()
    return colocated_funcs


# =============================================================================
# APPROACH 5: Shared function analysis
# Look for functions that reference BOTH a gap address AND gBattlerByTurnOrder
# (gActionsByTurnOrder is almost always used in the same functions as gBattlerByTurnOrder)
# =============================================================================

def find_shared_function_refs(rom_data, gap_results):
    """For each gap address, find which functions reference it AND also
    reference gBattlerByTurnOrder or gCurrentTurnActionNumber."""

    print("=" * 78)
    print("  APPROACH 5: Shared function analysis")
    print("  Find gap addresses co-referenced with gBattlerByTurnOrder")
    print("=" * 78)
    print()

    bto_addr = KNOWN["gBattlerByTurnOrder"]
    ctun_addr = KNOWN["gCurrentTurnActionNumber"]

    # Build function->lit_vals map for gBattlerByTurnOrder functions
    bto_refs = find_all_literal_refs(rom_data, bto_addr)
    bto_funcs = set()
    for lit_off in bto_refs:
        fs = find_function_start(rom_data, lit_off)
        if fs is not None:
            bto_funcs.add(fs)

    ctun_refs = find_all_literal_refs(rom_data, ctun_addr)
    ctun_funcs = set()
    for lit_off in ctun_refs:
        fs = find_function_start(rom_data, lit_off)
        if fs is not None:
            ctun_funcs.add(fs)

    print(f"  gBattlerByTurnOrder functions: {len(bto_funcs)}")
    print(f"  gCurrentTurnActionNumber functions: {len(ctun_funcs)}")
    print()

    # For each unknown gap address, check overlap with bto_funcs
    for addr in sorted(gap_results.keys()):
        if addr in KNOWN_SET:
            continue

        refs = find_all_literal_refs(rom_data, addr)
        addr_funcs = set()
        for lit_off in refs:
            fs = find_function_start(rom_data, lit_off)
            if fs is not None:
                addr_funcs.add(fs)

        overlap_bto = addr_funcs & bto_funcs
        overlap_ctun = addr_funcs & ctun_funcs

        if overlap_bto or overlap_ctun:
            print(f"  0x{addr:08X} ({len(refs)} refs):")
            print(f"    Shared with gBattlerByTurnOrder: {len(overlap_bto)} functions")
            print(f"    Shared with gCurrentTurnActionNumber: {len(overlap_ctun)} functions")

            # These shared functions are strong indicators
            if overlap_bto:
                print(f"    Shared function addrs (gBattlerByTurnOrder): ", end="")
                for fs in sorted(list(overlap_bto)[:10]):
                    print(f"0x{ROM_BASE + fs + 1:08X} ", end="")
                print()
            print()

    return bto_funcs, ctun_funcs


# =============================================================================
# APPROACH 6: Deep disassembly of top candidate
# =============================================================================

def deep_analyze_candidate(rom_data, candidate_addr):
    """Full disassembly of all functions referencing the candidate,
    looking for gActionsByTurnOrder usage patterns."""

    print("=" * 78)
    print(f"  APPROACH 6: Deep disassembly analysis for 0x{candidate_addr:08X}")
    print("=" * 78)
    print()

    refs = find_all_literal_refs(rom_data, candidate_addr)

    seen = set()
    shown = 0
    for lit_off in refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start is None or func_start in seen:
            continue
        seen.add(func_start)

        func_end = find_function_end(rom_data, func_start)
        if func_end is None:
            func_end = func_start + 300

        func_addr = ROM_BASE + func_start + 1
        func_size = func_end - func_start

        # Get co-referenced known addresses
        lits = get_ldr_pc_literals(rom_data, func_start, func_end)
        lit_vals = set(v for _, _, v, _ in lits)
        co_refs = []
        for name, kaddr in sorted(KNOWN.items()):
            if kaddr in lit_vals:
                co_refs.append(name)

        print(f"  --- Function 0x{func_addr:08X} ({func_size} bytes) ---")
        if co_refs:
            print(f"      Also references: {', '.join(co_refs)}")
        print()

        disasm = disassemble_range(rom_data, func_start, func_end, max_instrs=80)
        for pos, addr, raw, mnem in disasm:
            annotation = ""
            for name, kaddr in KNOWN.items():
                if f"0x{kaddr:08X}" in mnem:
                    annotation = f"  ; {name}"
                    break
            if f"0x{candidate_addr:08X}" in mnem:
                annotation = f"  ; <<< CANDIDATE"
            off = pos - func_start
            print(f"      +0x{off:04X} | 0x{addr:08X}: {raw:<12s} {mnem}{annotation}")

        print()
        shown += 1
        if shown >= 10:
            remaining = len(refs) - shown
            if remaining > 0:
                print(f"  ... ({remaining} more functions omitted)")
            break

    print()


# =============================================================================
# APPROACH 7: Look for gActionsByTurnOrder as non-aligned address
# The address 0x020233F2 might not appear in literal pools because it's
# accessed via base+offset. Check for patterns like:
#   LDR Rn, =0x020233E0  ; or similar base
#   ADD Rn, #18           ; offset 0x12
#   LDRB Rd, [Rn, Rm]    ; indexed byte access
# =============================================================================

def scan_base_plus_offset(rom_data):
    """Check if gActionsByTurnOrder is accessed via base+offset from known addresses."""

    print("=" * 78)
    print("  APPROACH 7: Base+offset access pattern scan")
    print("  Check if gActionsByTurnOrder at gap is accessed via known_base+offset")
    print("=" * 78)
    print()

    # For each known base address near the gap, check what offsets would reach
    # the candidate gActionsByTurnOrder locations
    candidates = {
        0x020233E0: "gBattleControllerExecFlags",
        0x020233E4: "gBattlersCount",
        0x020233F6: "gBattlerByTurnOrder",
        0x020233DC: "gActiveBattler",
    }

    for base_addr, base_name in candidates.items():
        for target in range(0x020233E5, 0x020233F6):
            offset = target - base_addr
            if offset < 0 or offset > 31:  # LDRB immediate max is 31
                continue
            # This combination is plausible -- check if there are functions
            # that load base_addr and then do LDRB Rd, [Rn, #offset]

    # More targeted: look for functions referencing gBattleControllerExecFlags (0x020233E0)
    # and check for LDRB/STRB with offsets 0x12-0x16
    print("  Checking gBattleControllerExecFlags (0x020233E0) + offset patterns:")
    print()

    base = 0x020233E0
    base_refs = find_all_literal_refs(rom_data, base)

    offset_usage = defaultdict(int)
    seen = set()

    for lit_off in base_refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start is None or func_start in seen:
            continue
        seen.add(func_start)

        func_end = find_function_end(rom_data, func_start)
        if func_end is None:
            func_end = func_start + 300

        disasm = disassemble_range(rom_data, func_start, func_end, max_instrs=200)

        for i, (pos, addr, raw, mnem) in enumerate(disasm):
            if f"0x{base:08X}" in mnem and "LDR" in mnem:
                # Found base load, check subsequent byte accesses
                import re
                rd_match = re.search(r'LDR R(\d)', mnem)
                if not rd_match:
                    continue
                rd = int(rd_match.group(1))

                for j in range(i+1, min(i+15, len(disasm))):
                    _, _, _, nm = disasm[j]
                    if f"[R{rd}, #" in nm:
                        try:
                            off_str = nm.split("#")[1].rstrip("])")
                            off_val = int(off_str)
                            actual_addr = base + off_val
                            if 0x020233E5 <= actual_addr <= 0x020233FB:
                                offset_usage[(off_val, actual_addr)] += 1
                        except:
                            pass

    if offset_usage:
        print(f"    Offsets from 0x{base:08X} leading to gap addresses:")
        for (off, actual), count in sorted(offset_usage.items(), key=lambda x: -x[1]):
            known = annotate_addr(actual)
            print(f"      +{off} -> 0x{actual:08X} ({count}x){known}")
    else:
        print("    No relevant base+offset patterns found from gBattleControllerExecFlags.")

    # Also check gActiveBattler (0x020233DC) as base
    print()
    print("  Checking gActiveBattler (0x020233DC) + offset patterns:")
    print()

    base2 = 0x020233DC
    base2_refs = find_all_literal_refs(rom_data, base2)

    offset_usage2 = defaultdict(int)
    seen2 = set()

    for lit_off in base2_refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start is None or func_start in seen2:
            continue
        seen2.add(func_start)

        func_end = find_function_end(rom_data, func_start)
        if func_end is None:
            func_end = func_start + 300

        disasm = disassemble_range(rom_data, func_start, func_end, max_instrs=200)

        for i, (pos, addr, raw, mnem) in enumerate(disasm):
            if f"0x{base2:08X}" in mnem and "LDR" in mnem:
                import re
                rd_match = re.search(r'LDR R(\d)', mnem)
                if not rd_match:
                    continue
                rd = int(rd_match.group(1))

                for j in range(i+1, min(i+15, len(disasm))):
                    _, _, _, nm = disasm[j]
                    if f"[R{rd}, #" in nm:
                        try:
                            off_str = nm.split("#")[1].rstrip("])")
                            off_val = int(off_str)
                            actual_addr = base2 + off_val
                            if 0x020233E5 <= actual_addr <= 0x020233FB:
                                offset_usage2[(off_val, actual_addr)] += 1
                        except:
                            pass

    if offset_usage2:
        print(f"    Offsets from 0x{base2:08X} leading to gap addresses:")
        for (off, actual), count in sorted(offset_usage2.items(), key=lambda x: -x[1]):
            known = annotate_addr(actual)
            print(f"      +{off} -> 0x{actual:08X} ({count}x){known}")
    else:
        print("    No relevant base+offset patterns found from gActiveBattler.")

    print()


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        print(f"  Expected: {ROM_PATH.resolve()}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size:,} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print()

    # Print known addresses for reference
    print("Known battle variable addresses:")
    for name, addr in sorted(KNOWN.items(), key=lambda x: x[1]):
        print(f"  {name:<30s} = 0x{addr:08X}")
    print()

    print("Source code variable order (battle_main.c lines 154-162):")
    print("  gBattleControllerExecFlags  u32       4 bytes")
    print("  gBattlersCount              u8        1 byte (aligned?)")
    print("  gBattlerPartyIndexes        u16[4]    8 bytes")
    print("  gBattlerPositions           u8[4]     4 bytes")
    print("  gActionsByTurnOrder         u8[4]     4 bytes  <-- TARGET")
    print("  gBattlerByTurnOrder         u8[4]     4 bytes")
    print("  gCurrentTurnActionNumber    u8        1 byte")
    print("  gCurrentActionFuncId        u8        1 byte")
    print("  gBattleMons                 struct[]  large")
    print()
    print("Estimated layout if linker respects source order:")
    print("  0x020233E0 = gBattleControllerExecFlags (4)")
    print("  0x020233E4 = gBattlersCount (1, padded to 2 for u16 alignment)")
    print("  0x020233E6 = gBattlerPartyIndexes (8)")
    print("  0x020233EE = gBattlerPositions (4)")
    print("  0x020233F2 = gActionsByTurnOrder (4)  <-- ESTIMATED")
    print("  0x020233F6 = gBattlerByTurnOrder (4)  <-- CONFIRMED")
    print("  0x020233FA = gCurrentTurnActionNumber (1) <-- CONFIRMED")
    print("  0x020233FB = gCurrentActionFuncId (1) <-- CONFIRMED")
    print("  0x020233FC = gBattleMons <-- CONFIRMED")
    print()

    # Run all approaches
    gap_results = scan_gap_addresses(rom_data)
    wider_results = scan_wider_cluster(rom_data)

    # Merge results
    all_unknown = {}
    for addr, count in {**gap_results, **wider_results}.items():
        if addr not in KNOWN_SET:
            all_unknown[addr] = count

    # Analyze top candidates from the gap
    print("=" * 78)
    print("  APPROACH 3: Function analysis for top gap candidates")
    print("=" * 78)
    print()

    gap_unknowns = {a: c for a, c in gap_results.items() if a not in KNOWN_SET and c >= 2}

    for addr in sorted(gap_unknowns.keys()):
        count = gap_unknowns[addr]
        func_infos = analyze_candidate(rom_data, addr, count)
        access_patterns = analyze_access_pattern(rom_data, addr, func_infos)

    # Approach 4: base+offset from gBattlerByTurnOrder
    scan_base_offset_access(rom_data)

    # Approach 5: shared function analysis
    find_shared_function_refs(rom_data, {**gap_results, **wider_results})

    # Approach 7: base+offset from other known addresses
    scan_base_plus_offset(rom_data)

    # Determine the best candidate
    print("=" * 78)
    print("  DETERMINATION: Identifying gActionsByTurnOrder")
    print("=" * 78)
    print()

    # Score each unknown address in the gap
    scored_candidates = []

    for addr in sorted(gap_unknowns.keys()):
        count = gap_unknowns[addr]
        score = 0
        reasons = []

        # High ref count is good (gActionsByTurnOrder should have many refs)
        if count >= 20:
            score += 30
            reasons.append(f"high ref count ({count})")
        elif count >= 10:
            score += 20
            reasons.append(f"moderate ref count ({count})")
        elif count >= 5:
            score += 10
            reasons.append(f"some refs ({count})")
        else:
            reasons.append(f"low ref count ({count})")

        # Address should be 4 bytes before gBattlerByTurnOrder if layout is packed
        # gBattlerByTurnOrder = 0x020233F6
        delta = KNOWN["gBattlerByTurnOrder"] - addr
        if delta == 4:
            score += 40
            reasons.append("exactly 4 bytes before gBattlerByTurnOrder (expected for u8[4])")
        elif 1 <= delta <= 8:
            score += 15
            reasons.append(f"{delta} bytes before gBattlerByTurnOrder")

        # It should be u8[4], so at an address that makes sense for byte alignment
        # (any alignment is fine for u8)

        # Check if address is consistent with source code ordering
        if addr > KNOWN["gBattlersCount"] and addr < KNOWN["gBattlerByTurnOrder"]:
            score += 10
            reasons.append("between gBattlersCount and gBattlerByTurnOrder (source order)")

        scored_candidates.append((score, addr, count, reasons))

    scored_candidates.sort(key=lambda x: -x[0])

    if scored_candidates:
        print("  Ranked candidates:")
        print()
        for rank, (score, addr, count, reasons) in enumerate(scored_candidates):
            marker = " <<<< BEST" if rank == 0 else ""
            print(f"    #{rank+1} 0x{addr:08X} (score={score}, {count} refs){marker}")
            for r in reasons:
                print(f"        - {r}")
            print()

        best_score, best_addr, best_count, best_reasons = scored_candidates[0]

        # Deep analyze the best candidate
        deep_analyze_candidate(rom_data, best_addr)

        print("=" * 78)
        print("  FINAL RESULT")
        print("=" * 78)
        print()
        print(f"  gActionsByTurnOrder = 0x{best_addr:08X}")
        print(f"  Confidence: {'HIGH' if best_score >= 50 else 'MODERATE' if best_score >= 30 else 'LOW'} (score={best_score})")
        print(f"  ROM literal pool refs: {best_count}")
        print(f"  Size: u8[4] = 4 bytes")
        print()
        print("  Complete battle variable layout:")
        all_vars = dict(KNOWN)
        all_vars["gActionsByTurnOrder (FOUND)"] = best_addr
        for name, addr in sorted(all_vars.items(), key=lambda x: x[1]):
            if 0x020233D0 <= addr <= 0x02023400:
                marker = " ***" if "FOUND" in name else ""
                print(f"    0x{addr:08X} = {name}{marker}")
    else:
        print("  NO CANDIDATES FOUND in the gap!")
        print()
        print("  gActionsByTurnOrder may not have its own literal pool entry.")
        print("  It might be accessed purely via base+offset from a nearby known address.")
        print("  Check Approach 7 output above for base+offset patterns.")

    print()
    print("=" * 78)
    print("  SCAN COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
