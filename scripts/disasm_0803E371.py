#!/usr/bin/env python3
"""
Disassemble THUMB code at ROM address 0x0803E371 (cart0 offset 0x0003E370)
from the Pokemon Run & Bun ROM.

Context: This function is where the master player gets stuck after DoBattleIntro.
The slave goes to HTASS (0x0803BE39) correctly. We need to identify what this
function is and why it blocks.

Known addresses for reference:
  - DoBattleIntro:                    0x0803ACB1
  - HandleTurnActionSelectionState:   0x0803BE39 (HTASS)
  - Unknown stuck function:           0x0803E371
  - gBattleTypeFlags:                 0x02023364
  - gBattleControllerExecFlags:       0x020233E0
  - gBattleCommunication:             0x0202370E
  - gBattleMainFunc:                  (pointer stored somewhere)
  - CB2_BattleMain:                   0x08094815
  - GetBlockReceivedStatus:           (ROM function)
  - IsLinkTaskFinished:               (ROM function)
  - gReceivedRemoteLinkPlayers:       (EWRAM variable)
"""

import struct
import sys
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Key addresses
TARGET_ADDR = 0x0803E371  # The stuck function (ROM address with THUMB bit)
TARGET_OFFSET = 0x0003E370  # Cart0 offset (without THUMB bit)

# Known data addresses
KNOWN_ADDRS = {
    0x02023364: "gBattleTypeFlags",
    0x020233E0: "gBattleControllerExecFlags",
    0x020233FC: "gBattleMons",
    0x0202370E: "gBattleCommunication",
    0x02023A0C: "gBattleStruct_ptr",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x0202064C: "gMain.callback2",
    0x030022C0: "gMain",
    0x03005D70: "gBattlerControllerFuncs",
    0x03005D90: "gRngValue",

    # Known ROM function addresses
    0x0803ACB1: "DoBattleIntro",
    0x0803BE39: "HandleTurnActionSelectionState (HTASS)",
    0x0803E371: "TARGET_FUNCTION",
    0x08094815: "CB2_BattleMain",
    0x080363C1: "CB2_InitBattle",
    0x0803648D: "CB2_InitBattleInternal",
    0x08037B45: "CB2_HandleStartBattle",
    0x0803816D: "BattleMainCB2",
    0x08000544: "SetMainCallback2",
    0x08007441: "CB2_LoadMap",
}

# BATTLE_TYPE flags
BATTLE_TYPE_FLAGS = {
    0x00000001: "DOUBLE",
    0x00000002: "LINK",
    0x00000004: "IS_MASTER",
    0x00000008: "TRAINER",
    0x00000010: "FIRST_BATTLE",
    0x00000020: "LINK_IN_BATTLE",
    0x00000040: "MULTI",
    0x00000080: "SAFARI",
    0x00000100: "BATTLE_TOWER",
    0x00000200: "WALLY_TUTORIAL",
    0x00000400: "ROAMER",
    0x00000800: "EREADER_TRAINER",
    0x00001000: "KYOGRE_GROUDON",
    0x00002000: "LEGENDARY",
    0x00004000: "REGI",
    0x00010000: "ARENA",
    0x00020000: "FACTORY",
    0x00040000: "PIKE",
    0x00080000: "PYRAMID",
    0x00100000: "INGAME_PARTNER",
    0x00200000: "RECORDED",
    0x00400000: "RECORDED_LINK",
    0x00800000: "TRAINER_HILL",
    0x01000000: "SECRET_BASE",
    0x02000000: "GROUDON",
    0x04000000: "KYOGRE",
    0x08000000: "RAYQUAZA",
    0x10000000: "FRONTIER",
}


def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def sign_extend(val, bits):
    if val & (1 << (bits - 1)):
        val -= (1 << bits)
    return val

def addr_name(addr):
    """Look up a known address name."""
    if addr in KNOWN_ADDRS:
        return f" = {KNOWN_ADDRS[addr]}"
    # Check within 256 bytes of known addresses
    for ka, name in KNOWN_ADDRS.items():
        if 0 < addr - ka < 256:
            return f" = {name}+0x{addr-ka:X}"
    return ""

def decode_thumb(data, base_addr, offset, count=200):
    """Decode THUMB instructions from ROM data."""
    results = []
    pc = base_addr
    i = 0
    literal_pool_refs = []  # Track LDR literal pool references

    while i < count:
        if offset + i*2 + 1 >= len(data):
            break

        instr = read_u16(data, offset + i*2)
        addr = base_addr + i*2
        hex_str = f"{instr:04X}"

        # Decode instruction
        decoded = decode_single_thumb(instr, addr, data, offset + i*2, literal_pool_refs)

        results.append((addr, hex_str, decoded))
        i += 1

        # Check for BL (two-instruction sequence)
        if (instr >> 11) == 0x1E:  # BL prefix (high part)
            if offset + (i)*2 + 1 < len(data):
                instr2 = read_u16(data, offset + i*2)
                if (instr2 >> 11) == 0x1F:  # BL suffix (low part)
                    # Compute BL target
                    imm11_hi = instr & 0x7FF
                    imm11_lo = instr2 & 0x7FF
                    bl_offset = (sign_extend(imm11_hi, 11) << 12) | (imm11_lo << 1)
                    target = (addr + 4 + bl_offset) & 0xFFFFFFFF

                    hex_str2 = f"{instr2:04X}"
                    name = addr_name(target)
                    decoded2 = f"BL 0x{target:08X}{name}"

                    # Override the previous entry
                    results[-1] = (addr, f"{hex_str} {hex_str2}", decoded2)
                    i += 1
                    continue

    return results, literal_pool_refs


def decode_single_thumb(instr, addr, data, data_offset, literal_pool_refs):
    """Decode a single THUMB instruction."""

    # Format 1: Move shifted register (LSL/LSR/ASR)
    if (instr >> 13) == 0:
        op = (instr >> 11) & 3
        offset5 = (instr >> 6) & 0x1F
        rs = (instr >> 3) & 7
        rd = instr & 7
        ops = ["LSL", "LSR", "ASR"]
        if op < 3:
            return f"{ops[op]} r{rd}, r{rs}, #{offset5}"

    # Format 2: Add/subtract
    if (instr >> 11) == 0x3:  # 00011
        i_flag = (instr >> 10) & 1
        op = (instr >> 9) & 1
        rn_imm = (instr >> 6) & 7
        rs = (instr >> 3) & 7
        rd = instr & 7
        opname = "SUB" if op else "ADD"
        if i_flag:
            return f"{opname} r{rd}, r{rs}, #{rn_imm}"
        else:
            return f"{opname} r{rd}, r{rs}, r{rn_imm}"

    # Format 3: Move/compare/add/subtract immediate
    if (instr >> 13) == 1:
        op = (instr >> 11) & 3
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        ops = ["MOV", "CMP", "ADD", "SUB"]
        return f"{ops[op]} r{rd}, #0x{imm8:02X} (={imm8})"

    # Format 4: ALU operations
    if (instr >> 10) == 0x10:
        op = (instr >> 6) & 0xF
        rs = (instr >> 3) & 7
        rd = instr & 7
        ops = ["AND", "EOR", "LSL", "LSR", "ASR", "ADC", "SBC", "ROR",
               "TST", "NEG", "CMP", "CMN", "ORR", "MUL", "BIC", "MVN"]
        return f"{ops[op]} r{rd}, r{rs}"

    # Format 5: Hi register operations / BX
    if (instr >> 10) == 0x11:
        op = (instr >> 8) & 3
        h1 = (instr >> 7) & 1
        h2 = (instr >> 6) & 1
        rs = ((h2 << 3) | ((instr >> 3) & 7))
        rd = ((h1 << 3) | (instr & 7))
        if op == 0:
            return f"ADD r{rd}, r{rs}"
        elif op == 1:
            return f"CMP r{rd}, r{rs}"
        elif op == 2:
            return f"MOV r{rd}, r{rs}"
        elif op == 3:
            return f"BX r{rs}"

    # Format 6: PC-relative load (LDR Rd, [PC, #imm])
    if (instr >> 11) == 0x9:  # 01001
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        offset_val = imm8 * 4
        # PC is (addr + 4) aligned to 4
        pc_val = (addr + 4) & ~3
        pool_addr = pc_val + offset_val
        # Try to read the literal pool value
        pool_rom_offset = pool_addr - 0x08000000
        if 0 <= pool_rom_offset < len(data) - 3:
            pool_val = read_u32(data, pool_rom_offset)
            name = addr_name(pool_val)
            literal_pool_refs.append((addr, rd, pool_addr, pool_val))
            return f"LDR r{rd}, [PC, #0x{offset_val:X}] ; =0x{pool_val:08X}{name} (pool@0x{pool_addr:08X})"
        else:
            return f"LDR r{rd}, [PC, #0x{offset_val:X}] ; pool@0x{pool_addr:08X}"

    # Format 7: Load/store with register offset
    if (instr >> 12) == 0x5:
        op = (instr >> 9) & 7
        ro = (instr >> 6) & 7
        rb = (instr >> 3) & 7
        rd = instr & 7
        ops = {0: "STR", 1: "STRH", 2: "STRB", 3: "LDRSB",
               4: "LDR", 5: "LDRH", 6: "LDRB", 7: "LDRSH"}
        return f"{ops.get(op, '???')} r{rd}, [r{rb}, r{ro}]"

    # Format 8: Load/store halfword
    # (covered by format 7 with different op codes)

    # Format 9: Load/store with immediate offset
    if (instr >> 13) == 3:
        bl = (instr >> 11) & 1  # byte/word: 1=byte
        l = (instr >> 11) & 1
        # Actually format 9 is 011BL
        b_flag = (instr >> 12) & 1
        l_flag = (instr >> 11) & 1
        offset5 = (instr >> 6) & 0x1F
        rb = (instr >> 3) & 7
        rd = instr & 7
        if b_flag:
            opname = "LDRB" if l_flag else "STRB"
            return f"{opname} r{rd}, [r{rb}, #0x{offset5:X}]"
        else:
            opname = "LDR" if l_flag else "STR"
            return f"{opname} r{rd}, [r{rb}, #0x{offset5*4:X}]"

    # Format 10: Load/store halfword
    if (instr >> 12) == 8:
        l_flag = (instr >> 11) & 1
        offset5 = (instr >> 6) & 0x1F
        rb = (instr >> 3) & 7
        rd = instr & 7
        opname = "LDRH" if l_flag else "STRH"
        return f"{opname} r{rd}, [r{rb}, #0x{offset5*2:X}]"

    # Format 11: SP-relative load/store
    if (instr >> 12) == 9:
        l_flag = (instr >> 11) & 1
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        opname = "LDR" if l_flag else "STR"
        return f"{opname} r{rd}, [SP, #0x{imm8*4:X}]"

    # Format 12: Load address (ADD Rd, PC/SP, #imm)
    if (instr >> 12) == 0xA:
        sp = (instr >> 11) & 1
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        src = "SP" if sp else "PC"
        return f"ADD r{rd}, {src}, #0x{imm8*4:X}"

    # Format 13: Add offset to SP
    if (instr >> 8) == 0xB0:
        s = (instr >> 7) & 1
        imm7 = instr & 0x7F
        if s:
            return f"SUB SP, #0x{imm7*4:X}"
        else:
            return f"ADD SP, #0x{imm7*4:X}"

    # Format 14: Push/pop registers
    if (instr >> 12) == 0xB:
        if (instr >> 9) == 0x5A or (instr >> 9) == 0x5B:  # PUSH/POP
            l = (instr >> 11) & 1
            r = (instr >> 8) & 1
            rlist = instr & 0xFF
            regs = []
            for bit in range(8):
                if rlist & (1 << bit):
                    regs.append(f"r{bit}")
            if r:
                regs.append("LR" if not l else "PC")
            opname = "POP" if l else "PUSH"
            return f"{opname} {{{', '.join(regs)}}}"

    # Format 15: Multiple load/store
    if (instr >> 12) == 0xC:
        l = (instr >> 11) & 1
        rb = (instr >> 8) & 7
        rlist = instr & 0xFF
        regs = []
        for bit in range(8):
            if rlist & (1 << bit):
                regs.append(f"r{bit}")
        opname = "LDMIA" if l else "STMIA"
        return f"{opname} r{rb}!, {{{', '.join(regs)}}}"

    # Format 16: Conditional branch
    if (instr >> 12) == 0xD:
        cond = (instr >> 8) & 0xF
        if cond < 0xE:
            soffset8 = sign_extend(instr & 0xFF, 8)
            target = addr + 4 + soffset8 * 2
            conds = ["BEQ", "BNE", "BCS", "BCC", "BMI", "BPL", "BVS", "BVC",
                     "BHI", "BLS", "BGE", "BLT", "BGT", "BLE"]
            name = addr_name(target & 0xFFFFFFFF)
            return f"{conds[cond]} 0x{target & 0xFFFFFFFF:08X}{name}"
        elif cond == 0xE:
            return f"<undefined>"
        elif cond == 0xF:
            imm8 = instr & 0xFF
            return f"SWI 0x{imm8:02X}"

    # Format 17: Software interrupt (handled above)

    # Format 18: Unconditional branch
    if (instr >> 11) == 0x1C:
        soffset11 = sign_extend(instr & 0x7FF, 11)
        target = addr + 4 + soffset11 * 2
        name = addr_name(target & 0xFFFFFFFF)
        return f"B 0x{target & 0xFFFFFFFF:08X}{name}"

    # Format 19: Long branch with link (BL) - first half
    if (instr >> 11) == 0x1E:
        return f"BL_prefix (high=0x{instr & 0x7FF:03X})"

    # Format 19: Long branch with link (BL) - second half
    if (instr >> 11) == 0x1F:
        return f"BL_suffix (low=0x{instr & 0x7FF:03X})"

    return f"??? (0x{instr:04X})"


def find_function_boundaries(data, start_offset, rom_base=0x08000000):
    """Try to find where the function starts (look for PUSH) and ends (POP PC or BX LR)."""
    # Search backwards for PUSH {... LR}
    func_start = start_offset
    for i in range(start_offset, max(start_offset - 200, 0), -2):
        instr = read_u16(data, i)
        # PUSH {... LR} pattern: 1011 0101 XXXX XXXX
        if (instr & 0xFF00) == 0xB500:
            func_start = i
            break

    # Search forward for POP {... PC} or BX LR
    func_end = start_offset + 400
    for i in range(start_offset, min(start_offset + 1000, len(data) - 1), 2):
        instr = read_u16(data, i)
        # POP {... PC}: 1011 1101 XXXX XXXX
        if (instr & 0xFF00) == 0xBD00:
            func_end = i + 2
            break
        # BX LR: 0x4770
        if instr == 0x4770:
            func_end = i + 2
            break

    return func_start, func_end


def scan_for_literal_pool(data, start_offset, end_offset, rom_base=0x08000000):
    """Scan for literal pool data after the function (32-bit aligned values)."""
    results = []
    # Literal pools are typically right after the function, word-aligned
    aligned_start = (end_offset + 3) & ~3
    for off in range(aligned_start, min(aligned_start + 128, len(data) - 3), 4):
        val = read_u32(data, off)
        addr = off + rom_base
        name = addr_name(val)
        if name or (0x02000000 <= val <= 0x0203FFFF) or (0x03000000 <= val <= 0x03007FFF) or (0x08000000 <= val <= 0x09FFFFFF):
            results.append((addr, val, name))
    return results


def check_for_link_patterns(data, start_offset, size):
    """Check for patterns that indicate link battle checks."""
    patterns = []

    for i in range(0, size - 3, 2):
        instr = read_u16(data, start_offset + i)

        # Look for TST or AND with immediate loaded via LDR
        # Also look for CMP with specific values
        if (instr >> 10) == 0x10:  # ALU op
            op = (instr >> 6) & 0xF
            if op == 8:  # TST
                patterns.append((start_offset + i, "TST found"))
            elif op == 0:  # AND
                patterns.append((start_offset + i, "AND found"))

    return patterns


def main():
    if not os.path.exists(ROM_PATH):
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    with open(ROM_PATH, 'rb') as f:
        rom_data = f.read()

    print(f"ROM size: {len(rom_data)} bytes ({len(rom_data)/1024/1024:.1f} MB)")
    print(f"Target address: 0x{TARGET_ADDR:08X} (cart0 offset 0x{TARGET_OFFSET:08X})")
    print()

    # ====== STEP 1: Find function boundaries ======
    print("=" * 80)
    print("STEP 1: Finding function boundaries around 0x0803E370")
    print("=" * 80)

    func_start, func_end = find_function_boundaries(rom_data, TARGET_OFFSET)
    func_size = func_end - func_start
    print(f"Function start: 0x{func_start + 0x08000000:08X} (cart0: 0x{func_start:08X})")
    print(f"Function end:   0x{func_end + 0x08000000:08X} (cart0: 0x{func_end:08X})")
    print(f"Function size:  {func_size} bytes")
    print()

    # ====== STEP 2: Disassemble the function ======
    print("=" * 80)
    print(f"STEP 2: Disassembling from 0x{func_start + 0x08000000:08X}")
    print("=" * 80)

    num_instrs = min(func_size // 2 + 20, 300)  # disassemble a bit past the end too
    results, lit_refs = decode_thumb(rom_data, func_start + 0x08000000, func_start, num_instrs)

    for addr, hex_str, decoded in results:
        marker = " <-- TARGET (bmf stuck here)" if addr == TARGET_ADDR or addr == TARGET_ADDR - 1 else ""
        # Highlight LINK-related checks
        if "BATTLE_TYPE" in decoded or "gBattleTypeFlags" in decoded:
            marker += " *** LINK CHECK ***"
        if "GetBlockReceivedStatus" in decoded or "IsLinkTaskFinished" in decoded:
            marker += " *** LINK WAIT ***"
        if "gBattleCommunication" in decoded:
            marker += " *** COMM ***"
        if "gBattleControllerExecFlags" in decoded:
            marker += " *** EXEC FLAGS ***"
        if "HandleTurnActionSelectionState" in decoded or "HTASS" in decoded:
            marker += " *** -> HTASS ***"
        print(f"  0x{addr:08X}: {hex_str:12s}  {decoded}{marker}")

    print()

    # ====== STEP 3: Check literal pool ======
    print("=" * 80)
    print("STEP 3: Literal pool scan")
    print("=" * 80)

    pool_entries = scan_for_literal_pool(rom_data, func_start, func_end)
    for addr, val, name in pool_entries:
        flag_info = ""
        if name and "gBattleTypeFlags" in name:
            flag_info = " ** THIS IS THE BATTLE TYPE FLAGS ADDRESS **"
        # Check if val matches a battle type flag
        if val in BATTLE_TYPE_FLAGS:
            flag_info += f" BATTLE_TYPE_{BATTLE_TYPE_FLAGS[val]}"
        print(f"  0x{addr:08X}: 0x{val:08X}{name}{flag_info}")

    print()

    # ====== STEP 4: Analyze specific patterns ======
    print("=" * 80)
    print("STEP 4: Analysis — Key questions")
    print("=" * 80)

    # Check if gBattleTypeFlags is referenced
    has_btf = False
    has_link_check = False
    has_getblock = False
    has_comm = False
    has_exec_flags = False
    has_htass_ref = False
    bl_targets = []
    branch_targets = []

    for addr, hex_str, decoded in results:
        if "gBattleTypeFlags" in decoded:
            has_btf = True
        if "0x00000002" in decoded or "BATTLE_TYPE_LINK" in decoded:
            has_link_check = True
        if "GetBlockReceivedStatus" in decoded:
            has_getblock = True
        if "gBattleCommunication" in decoded:
            has_comm = True
        if "gBattleControllerExecFlags" in decoded:
            has_exec_flags = True
        if "0x0803BE39" in decoded or "HTASS" in decoded:
            has_htass_ref = True
        if decoded.startswith("BL "):
            target = decoded.split()[1]
            bl_targets.append((addr, target, decoded))
        if decoded.startswith("B ") and not decoded.startswith("BL") and not decoded.startswith("BX") and not decoded.startswith("BEQ") and not decoded.startswith("BNE") and not decoded.startswith("BCS") and not decoded.startswith("BCC") and not decoded.startswith("BMI") and not decoded.startswith("BPL") and not decoded.startswith("BVS") and not decoded.startswith("BVC") and not decoded.startswith("BHI") and not decoded.startswith("BLS") and not decoded.startswith("BGE") and not decoded.startswith("BLT") and not decoded.startswith("BGT") and not decoded.startswith("BLE"):
            branch_targets.append((addr, decoded))

    print(f"1. References gBattleTypeFlags?           {'YES' if has_btf else 'NO'}")
    print(f"2. Checks BATTLE_TYPE_LINK (0x02)?        {'YES' if has_link_check else 'NO'}")
    print(f"3. Calls GetBlockReceivedStatus?           {'YES' if has_getblock else 'NO'}")
    print(f"4. References gBattleCommunication?        {'YES' if has_comm else 'NO'}")
    print(f"5. References gBattleControllerExecFlags?  {'YES' if has_exec_flags else 'NO'}")
    print(f"6. References HTASS (0x0803BE39)?           {'YES' if has_htass_ref else 'NO'}")

    print()
    print("BL (function call) targets:")
    for addr, target, decoded in bl_targets:
        print(f"  0x{addr:08X}: {decoded}")

    print()
    print("Unconditional branch targets:")
    for addr, decoded in branch_targets:
        print(f"  0x{addr:08X}: {decoded}")

    # ====== STEP 5: Look for loops ======
    print()
    print("=" * 80)
    print("STEP 5: Loop detection (backward branches)")
    print("=" * 80)

    for addr, hex_str, decoded in results:
        # Look for conditional branches that go backward (loop)
        if decoded.startswith("B") and "0x" in decoded:
            parts = decoded.split()
            if len(parts) >= 2:
                try:
                    target_str = parts[1].rstrip(';').split('=')[0]
                    if target_str.startswith("0x"):
                        target_val = int(target_str, 16)
                        if target_val < addr:
                            print(f"  BACKWARD BRANCH at 0x{addr:08X}: {decoded}")
                            # Check if this creates a tight loop
                            loop_size = addr - target_val
                            if loop_size <= 20:
                                print(f"    ** TIGHT LOOP (only {loop_size} bytes)! **")
                except ValueError:
                    pass

    # ====== STEP 6: Wider context — what's before and after ======
    print()
    print("=" * 80)
    print("STEP 6: Context — functions before and after")
    print("=" * 80)

    # Check HTASS end -> target function
    htass_offset = 0x0003BE38  # HTASS at 0x0803BE39 minus THUMB bit
    print(f"HTASS (HandleTurnActionSelectionState) at 0x0803BE39 (offset 0x{htass_offset:08X})")
    print(f"Gap from HTASS start to target: {TARGET_OFFSET - htass_offset} bytes ({(TARGET_OFFSET - htass_offset)//2} instructions)")

    # Find what functions are between HTASS and our target
    print()
    print("Scanning for PUSH instructions (function starts) between HTASS and target:")
    for off in range(htass_offset, TARGET_OFFSET + 2, 2):
        instr = read_u16(rom_data, off)
        if (instr & 0xFF00) == 0xB500 or (instr & 0xFF00) == 0xB510 or (instr & 0xFF00) == 0xB530 or (instr & 0xFF00) == 0xB570 or (instr & 0xFF00) == 0xB5F0 or (instr & 0xFF80) == 0xB500:
            rom_addr = off + 0x08000000
            name = addr_name(rom_addr) or addr_name(rom_addr + 1)
            print(f"  0x{rom_addr:08X}: PUSH {instr:04X}{name}")

    # ====== STEP 7: Scan the literal pool values referenced by the function ======
    print()
    print("=" * 80)
    print("STEP 7: All literal pool values loaded by the function")
    print("=" * 80)

    for pc_addr, rd, pool_addr, pool_val in lit_refs:
        name = addr_name(pool_val)
        flag_match = ""
        for fv, fn in BATTLE_TYPE_FLAGS.items():
            if pool_val == fv:
                flag_match = f" = BATTLE_TYPE_{fn}"
        print(f"  At 0x{pc_addr:08X}: r{rd} = [0x{pool_addr:08X}] = 0x{pool_val:08X}{name}{flag_match}")

    # ====== STEP 8: Wider disassembly — 200 bytes before target ======
    print()
    print("=" * 80)
    print("STEP 8: Disassembly 100 bytes BEFORE target (context)")
    print("=" * 80)

    pre_start = max(TARGET_OFFSET - 100, 0)
    # Align to 2
    pre_start &= ~1
    pre_results, pre_lit_refs = decode_thumb(rom_data, pre_start + 0x08000000, pre_start, 50)
    for addr, hex_str, decoded in pre_results:
        marker = ""
        if addr == TARGET_ADDR or addr == TARGET_ADDR - 1:
            marker = " <-- TARGET"
        print(f"  0x{addr:08X}: {hex_str:12s}  {decoded}{marker}")

    # ====== STEP 9: Raw bytes around target for manual inspection ======
    print()
    print("=" * 80)
    print("STEP 9: Raw bytes at target offset (hex dump)")
    print("=" * 80)

    dump_start = TARGET_OFFSET
    dump_size = 256
    for row in range(0, dump_size, 16):
        off = dump_start + row
        hex_bytes = ' '.join(f'{rom_data[off+j]:02X}' for j in range(min(16, dump_size - row)))
        ascii_chars = ''.join(chr(rom_data[off+j]) if 32 <= rom_data[off+j] < 127 else '.' for j in range(min(16, dump_size - row)))
        print(f"  0x{off + 0x08000000:08X}: {hex_bytes}  {ascii_chars}")

    # ====== STEP 10: Search for HTASS address in literal pools near target ======
    print()
    print("=" * 80)
    print("STEP 10: Search for HTASS (0x0803BE39) reference near target")
    print("=" * 80)

    htass_bytes = struct.pack('<I', 0x0803BE39)
    # Search in the range around target
    search_start = max(TARGET_OFFSET - 2000, 0)
    search_end = min(TARGET_OFFSET + 2000, len(rom_data) - 3)
    found_any = False
    for off in range(search_start, search_end):
        if rom_data[off:off+4] == htass_bytes:
            print(f"  Found 0x0803BE39 at ROM offset 0x{off:08X} (addr 0x{off + 0x08000000:08X})")
            found_any = True
    if not found_any:
        print("  NOT FOUND in +-2000 bytes range")
        # Also search wider
        for off in range(0, len(rom_data) - 3, 4):
            if rom_data[off:off+4] == htass_bytes:
                print(f"  Found at ROM offset 0x{off:08X} (addr 0x{off + 0x08000000:08X}) [wider search]")
                found_any = True
                if found_any and off > search_end + 10000:
                    break  # Don't search forever

    # ====== STEP 11: Check what calls gBattleMainFunc = target ======
    print()
    print("=" * 80)
    print("STEP 11: Search for 0x0803E371 in literal pools (who sets bmf to this?)")
    print("=" * 80)

    target_bytes = struct.pack('<I', 0x0803E371)
    for off in range(0, len(rom_data) - 3, 4):
        if rom_data[off:off+4] == target_bytes:
            rom_addr = off + 0x08000000
            print(f"  Found at 0x{rom_addr:08X} (cart0 offset 0x{off:08X})")
            # Try to find the LDR that references this
            for check_off in range(max(off - 200, 0), off, 2):
                check_instr = read_u16(rom_data, check_off)
                if (check_instr >> 11) == 0x9:  # LDR Rd, [PC, #imm]
                    rd = (check_instr >> 8) & 7
                    imm8 = check_instr & 0xFF
                    pc_val = (check_off + 0x08000000 + 4) & ~3
                    pool = pc_val + imm8 * 4
                    if pool == rom_addr:
                        print(f"    Referenced by LDR r{rd} at 0x{check_off + 0x08000000:08X}")


if __name__ == "__main__":
    main()
