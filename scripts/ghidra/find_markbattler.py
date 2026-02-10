#!/usr/bin/env python3
"""
Find MarkBattlerForControllerExec in Pokemon Run & Bun ROM.

This function:
  - Loads gBattleTypeFlags (0x02023364)
  - Tests bit 1 (BATTLE_TYPE_LINK = 0x02)
  - If LINK: sets gBattleControllerExecFlags |= (1 << (battler + 28))
  - If LOCAL: sets gBattleControllerExecFlags |= (1 << battler)

Strategy:
  1. Find all literal pool refs for gBattleTypeFlags (0x02023364)
  2. Find all literal pool refs for gBattleControllerExecFlags (0x020233E0)
  3. Find functions that reference BOTH within 256 bytes (same literal pool)
  4. Score by function size (~20-40 bytes expected), instruction pattern, cross-refs

The inlined versions of MarkBattleControllerActiveOnLocal and
MarkBattleControllerMessageOutboundOverLink mean the full function body is:
  PUSH {LR}
  LDR Rx, =gBattleTypeFlags
  LDR Rx, [Rx]
  MOV Ry, #2         ; or TST Rx, #2
  TST Rx, Ry
  BEQ .local
  ; link path: MOV Ry, #28; ADD R0, Ry; (or ADD R0, #28)
  ...
  LDR Rx, =gBattleControllerExecFlags
  ...
  .local:
  LDR Rx, =gBattleControllerExecFlags
  MOV Ry, #1
  LSL Ry, R0
  LDR Rz, [Rx]
  ORR Rz, Ry
  STR Rz, [Rx]
  POP {PC}

No Ghidra needed -- reads the .gba file directly.
"""

import struct
import sys
from pathlib import Path
from collections import defaultdict

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Confirmed R&B addresses
gBattleTypeFlags_ADDR = 0x02023364
gBattleControllerExecFlags_ADDR = 0x020233E0


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


def find_function_start(rom_data, offset, max_back=1024):
    """Walk backward to find PUSH {..., LR} (0xB5xx)."""
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16(rom_data, pos)
        # PUSH {Rx..., LR} = 0xB5xx
        if (instr & 0xFF00) == 0xB500:
            return pos
        # Also check PUSH {Rx...} without LR = 0xB4xx (some leaf functions)
        # But MarkBattlerForControllerExec has BL calls, so it uses LR
    return None


def find_function_end(rom_data, func_start, max_size=256):
    """Find first POP {PC} or BX LR after func_start."""
    pos = func_start + 2
    limit = min(func_start + max_size, len(rom_data) - 2)
    while pos < limit:
        instr = read_u16(rom_data, pos)
        # POP {..., PC}
        if (instr & 0xFF00) == 0xBD00:
            return pos + 2
        # BX LR
        if instr == 0x4770:
            return pos + 2
        # Skip BL 32-bit pairs
        if (instr & 0xF800) == 0xF000 and pos + 2 < limit:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return None


def decode_bl_target(rom_data, pos):
    """Decode THUMB BL instruction pair at pos."""
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


def get_ldr_pc_values(rom_data, func_start, func_end):
    """Extract all literal pool values loaded via LDR Rd,[PC,#imm]."""
    results = []
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        if (instr & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_off)
                results.append((pos, rd, val))
        # Skip BL 32-bit pairs
        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return results


COND_NAMES = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
              "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]

def disassemble_thumb(rom_data, start, end):
    """Simple THUMB disassembler. Returns list of (rom_offset, addr, mnemonic)."""
    lines = []
    pos = start
    while pos < end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        addr = ROM_BASE + pos
        mnem = ""

        # PUSH
        if (instr & 0xFE00) == 0xB400:
            lr = (instr >> 8) & 1
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if lr: regs.append("LR")
            mnem = f"PUSH {{{', '.join(regs)}}}"
        # POP
        elif (instr & 0xFE00) == 0xBC00:
            pc = (instr >> 8) & 1
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if pc: regs.append("PC")
            mnem = f"POP {{{', '.join(regs)}}}"
        # MOV Rd, #imm
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            mnem = f"MOV R{rd}, #{imm}"
        # CMP Rn, #imm
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7; imm = instr & 0xFF
            mnem = f"CMP R{rn}, #{imm}"
        # ADD Rd, #imm
        elif (instr & 0xF800) == 0x3000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            mnem = f"ADD R{rd}, #{imm}"
        # LDR Rd, [PC, #imm]
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7; imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_off)
                mnem = f"LDR R{rd}, =0x{val:08X}"
            else:
                mnem = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"
        # LDR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            mnem = f"LDR R{rd}, [R{rn}, #{imm}]"
        # STR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            mnem = f"STR R{rd}, [R{rn}, #{imm}]"
        # LDRB Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x7800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            mnem = f"LDRB R{rd}, [R{rn}, #{imm}]"
        # STRB Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x7000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            mnem = f"STRB R{rd}, [R{rn}, #{imm}]"
        # ALU format 4
        elif (instr & 0xFC00) == 0x4000:
            op = (instr >> 6) & 0xF; rd = instr & 7; rm = (instr >> 3) & 7
            names = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                     "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            mnem = f"{names[op]} R{rd}, R{rm}"
        # High register ops (format 5)
        elif (instr & 0xFC00) == 0x4400:
            op = (instr >> 8) & 3; h1 = (instr >> 7) & 1; h2 = (instr >> 6) & 1
            rd = (instr & 7) | (h1 << 3); rm = ((instr >> 3) & 7) | (h2 << 3)
            ops = ["ADD","CMP","MOV","BX"]
            mnem = f"{ops[op]} R{rd}, R{rm}"
        # Shifts
        elif (instr & 0xF800) == 0x0000 and instr != 0:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            mnem = f"LSL R{rd}, R{rm}, #{imm5}"
        elif (instr & 0xF800) == 0x0800:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            if imm5 == 0: imm5 = 32
            mnem = f"LSR R{rd}, R{rm}, #{imm5}"
        # ADD 3-reg
        elif (instr & 0xFE00) == 0x1800:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"ADD R{rd}, R{rn}, R{rm}"
        # Conditional branch
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF; soff = instr & 0xFF
            if soff >= 0x80: soff -= 0x100
            target = addr + 4 + soff * 2
            if cond < 0xF:
                mnem = f"{COND_NAMES[cond]} 0x{target:08X}"
            else:
                mnem = f"SVC #{instr & 0xFF}"
        # Unconditional branch
        elif (instr & 0xF800) == 0xE000:
            soff = instr & 0x7FF
            if soff >= 0x400: soff -= 0x800
            target = addr + 4 + soff * 2
            mnem = f"B 0x{target:08X}"
        # BL (32-bit)
        elif (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                target = decode_bl_target(rom_data, pos)
                mnem = f"BL 0x{target:08X}" if target else "BL ???"
                lines.append((pos, addr, mnem))
                pos += 4
                continue
        # SP-relative LDR/STR
        elif (instr & 0xF800) == 0x9800:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            mnem = f"LDR R{rd}, [SP, #0x{imm:X}]"
        elif (instr & 0xF800) == 0x9000:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            mnem = f"STR R{rd}, [SP, #0x{imm:X}]"
        # NOP
        elif instr == 0x46C0:
            mnem = "NOP"
        elif instr == 0x0000:
            mnem = "DATA 0x0000"
        else:
            mnem = f"??? 0x{instr:04X}"

        lines.append((pos, addr, mnem))
        pos += 2

    return lines


def count_callers(rom_data, target_thumb_addr, max_rom_offset=None):
    """Count how many BL instructions in the ROM call the given THUMB address.
    target_thumb_addr should include the +1 THUMB bit (e.g., 0x0806F0D5).
    Returns list of (caller_rom_offset, caller_func_start) tuples."""
    # The BL target is computed without the THUMB bit
    target_no_thumb = target_thumb_addr & ~1
    limit = max_rom_offset if max_rom_offset else len(rom_data) - 4
    callers = []
    for pos in range(0, limit, 2):
        t = decode_bl_target(rom_data, pos)
        if t is not None and (t == target_thumb_addr or t == target_no_thumb):
            callers.append(pos)
    return callers


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size:,} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print(f"ROM path: {ROM_PATH.resolve()}")
    print()

    # =========================================================================
    # STEP 1: Find literal pool refs for both addresses
    # =========================================================================
    print("=" * 80)
    print("  STEP 1: Finding literal pool references")
    print("=" * 80)
    print()

    btf_refs = find_all_literal_refs(rom_data, gBattleTypeFlags_ADDR)
    bcef_refs = find_all_literal_refs(rom_data, gBattleControllerExecFlags_ADDR)

    print(f"  gBattleTypeFlags (0x{gBattleTypeFlags_ADDR:08X}):           {len(btf_refs)} literal pool refs")
    print(f"  gBattleControllerExecFlags (0x{gBattleControllerExecFlags_ADDR:08X}): {len(bcef_refs)} literal pool refs")
    print()

    if len(btf_refs) == 0:
        print("  WARNING: gBattleTypeFlags has 0 literal pool refs!")
        print("  The compiler may access it via base register + offset.")
        print("  Trying alternate strategy: scan for gBattleControllerExecFlags refs")
        print("  and look for nearby TST #2 or MOV #2 + TST patterns.")
        print()

    if len(bcef_refs) == 0:
        print("  WARNING: gBattleControllerExecFlags has 0 literal pool refs!")
        print("  Cannot proceed with literal pool strategy.")
        sys.exit(1)

    # =========================================================================
    # STEP 2: Find functions containing both refs in literal pool
    # =========================================================================
    print("=" * 80)
    print("  STEP 2: Finding functions with BOTH addresses in literal pool")
    print("=" * 80)
    print()

    # Build sets of functions referencing each address
    btf_funcs = {}  # func_start -> [lit_offsets]
    for lit_off in btf_refs:
        fs = find_function_start(rom_data, lit_off)
        if fs is not None:
            if fs not in btf_funcs:
                btf_funcs[fs] = []
            btf_funcs[fs].append(lit_off)

    bcef_funcs = {}
    for lit_off in bcef_refs:
        fs = find_function_start(rom_data, lit_off)
        if fs is not None:
            if fs not in bcef_funcs:
                bcef_funcs[fs] = []
            bcef_funcs[fs].append(lit_off)

    # Functions referencing BOTH
    both_funcs = set(btf_funcs.keys()) & set(bcef_funcs.keys())
    print(f"  Functions referencing gBattleTypeFlags:           {len(btf_funcs)}")
    print(f"  Functions referencing gBattleControllerExecFlags: {len(bcef_funcs)}")
    print(f"  Functions referencing BOTH:                       {len(both_funcs)}")
    print()

    # =========================================================================
    # STEP 2B: Proximity-based matching (literal pool entries within 256 bytes)
    # =========================================================================
    print("=" * 80)
    print("  STEP 2B: Proximity-based matching (within 256 bytes)")
    print("=" * 80)
    print()

    proximity_matches = set()
    PROXIMITY = 256
    for btf_off in btf_refs:
        for bcef_off in bcef_refs:
            if abs(btf_off - bcef_off) <= PROXIMITY:
                # Both literal pool entries are close -- find containing function
                earliest = min(btf_off, bcef_off)
                fs = find_function_start(rom_data, earliest)
                if fs is not None:
                    proximity_matches.add(fs)

    print(f"  Proximity matches (lit pool entries within {PROXIMITY} bytes): {len(proximity_matches)}")
    print()

    # Merge all candidate function starts
    all_candidates = both_funcs | proximity_matches

    # =========================================================================
    # STEP 3: Analyze and score candidate functions
    # =========================================================================
    print("=" * 80)
    print("  STEP 3: Analyzing candidate functions")
    print("=" * 80)
    print()

    scored = []

    for fs in sorted(all_candidates):
        fe = find_function_end(rom_data, fs, max_size=256)
        if fe is None:
            fe = fs + 100  # fallback

        size = fe - fs
        func_addr = ROM_BASE + fs + 1  # +1 for THUMB

        # Get literal pool values
        ldr_vals = get_ldr_pc_values(rom_data, fs, fe)
        lit_set = set(v for _, _, v in ldr_vals)

        has_btf = gBattleTypeFlags_ADDR in lit_set
        has_bcef = gBattleControllerExecFlags_ADDR in lit_set

        # Disassemble
        disasm = disassemble_thumb(rom_data, fs, fe)

        # Score
        score = 0
        reasons = []

        # Must reference gBattleControllerExecFlags
        if has_bcef:
            score += 20
            reasons.append("refs gBattleControllerExecFlags")
        else:
            continue  # skip

        # Should reference gBattleTypeFlags
        if has_btf:
            score += 20
            reasons.append("refs gBattleTypeFlags")

        # Size: 20-60 bytes is ideal for this function
        if 16 <= size <= 60:
            score += 30
            reasons.append(f"ideal size ({size} bytes)")
        elif 60 < size <= 100:
            score += 10
            reasons.append(f"acceptable size ({size} bytes)")
        elif size > 100:
            score -= 10
            reasons.append(f"too large ({size} bytes)")
        else:
            score += 5
            reasons.append(f"tiny ({size} bytes)")

        # Check for TST instruction (testing BATTLE_TYPE_LINK bit)
        has_tst = False
        has_mov_2 = False
        has_lsl = False
        has_orr = False
        has_add_28 = False
        has_mov_1 = False
        bl_count = 0

        for _, _, mnem in disasm:
            if "TST" in mnem:
                has_tst = True
            if "MOV" in mnem and "#2" in mnem.split(",")[-1].strip():
                has_mov_2 = True
            if "MOV" in mnem and "#1" in mnem.split(",")[-1].strip():
                has_mov_1 = True
            if "LSL" in mnem:
                has_lsl = True
            if "ORR" in mnem:
                has_orr = True
            if "ADD" in mnem and "#28" in mnem:
                has_add_28 = True
            if "BL " in mnem:
                bl_count += 1

        if has_tst:
            score += 15
            reasons.append("has TST (bit test)")
        if has_mov_2:
            score += 10
            reasons.append("has MOV Rx, #2 (BATTLE_TYPE_LINK)")
        if has_lsl:
            score += 10
            reasons.append("has LSL (1 << battler)")
        if has_orr:
            score += 15
            reasons.append("has ORR (flags |= mask)")
        if has_add_28:
            score += 15
            reasons.append("has ADD Rx, #28 (battler + 28 for link path)")
        if has_mov_1:
            score += 5
            reasons.append("has MOV Rx, #1 (bit mask)")
        if bl_count == 0:
            score += 10
            reasons.append("no BL calls (pure inline logic)")
        elif bl_count <= 2:
            score += 5
            reasons.append(f"{bl_count} BL call(s)")
        else:
            score -= 10
            reasons.append(f"too many BL calls ({bl_count})")

        # Check for conditional branch (BEQ/BNE after TST)
        has_cond_branch = False
        for _, _, mnem in disasm:
            if mnem.startswith("BEQ") or mnem.startswith("BNE"):
                has_cond_branch = True
                break
        if has_cond_branch:
            score += 10
            reasons.append("has conditional branch (link vs local path)")

        scored.append((score, fs, fe, func_addr, size, reasons, disasm, lit_set))

    scored.sort(key=lambda x: -x[0])

    print(f"  {len(scored)} candidate functions scored")
    print()

    # Print all candidates
    for rank, (score, fs, fe, func_addr, size, reasons, disasm, lit_set) in enumerate(scored[:15]):
        marker = "  <<<< BEST" if rank == 0 else ""
        print(f"  #{rank+1} Score={score} | 0x{func_addr:08X} ({size} bytes) ROM offset 0x{fs:06X}{marker}")
        for r in reasons:
            print(f"       - {r}")

        # Print disassembly
        print(f"    Disassembly:")
        for rom_off, addr, mnem in disasm:
            func_off = rom_off - fs
            annotation = ""
            if f"0x{gBattleTypeFlags_ADDR:08X}" in mnem:
                annotation = "  ; gBattleTypeFlags"
            elif f"0x{gBattleControllerExecFlags_ADDR:08X}" in mnem:
                annotation = "  ; gBattleControllerExecFlags"
            print(f"      +0x{func_off:02X} | 0x{addr:08X}: {mnem}{annotation}")

        # Print literal pool contents
        ldr_vals = get_ldr_pc_values(rom_data, fs, fe)
        if ldr_vals:
            print(f"    Literal pool:")
            for ldr_pos, rd, val in ldr_vals:
                label = ""
                if val == gBattleTypeFlags_ADDR:
                    label = " = gBattleTypeFlags"
                elif val == gBattleControllerExecFlags_ADDR:
                    label = " = gBattleControllerExecFlags"
                elif 0x02000000 <= val < 0x02040000:
                    label = " (EWRAM)"
                elif 0x03000000 <= val < 0x03008000:
                    label = " (IWRAM)"
                elif 0x08000000 <= val < 0x0A000000:
                    label = " (ROM)"
                print(f"      R{rd} <- 0x{val:08X}{label}")
        print()

    # =========================================================================
    # STEP 3B: Fallback -- if gBattleTypeFlags has 0 refs, search via
    # gBattleControllerExecFlags functions that have TST pattern
    # =========================================================================
    if not btf_refs:
        print("=" * 80)
        print("  STEP 3B: FALLBACK -- gBattleTypeFlags not in literal pools")
        print("  Searching gBattleControllerExecFlags functions with TST + ORR pattern")
        print("=" * 80)
        print()

        fallback_scored = []
        for fs in sorted(bcef_funcs.keys()):
            fe = find_function_end(rom_data, fs, max_size=256)
            if fe is None:
                fe = fs + 100

            size = fe - fs
            func_addr = ROM_BASE + fs + 1

            disasm = disassemble_thumb(rom_data, fs, fe)
            ldr_vals = get_ldr_pc_values(rom_data, fs, fe)
            lit_set = set(v for _, _, v in ldr_vals)

            score = 0
            reasons = []

            # Size check: ideal 16-80 bytes
            if 16 <= size <= 80:
                score += 25
                reasons.append(f"ideal size ({size} bytes)")
            elif 80 < size <= 150:
                score += 5
                reasons.append(f"acceptable size ({size} bytes)")
            else:
                continue

            has_tst = False
            has_orr = False
            has_lsl = False
            has_add_28 = False
            has_cond = False
            bl_count = 0

            for _, _, mnem in disasm:
                if "TST" in mnem: has_tst = True
                if "ORR" in mnem: has_orr = True
                if "LSL" in mnem: has_lsl = True
                if "ADD" in mnem and "#28" in mnem: has_add_28 = True
                if mnem.startswith("BEQ") or mnem.startswith("BNE"): has_cond = True
                if "BL " in mnem: bl_count += 1

            if has_tst: score += 15; reasons.append("has TST")
            if has_orr: score += 15; reasons.append("has ORR")
            if has_lsl: score += 10; reasons.append("has LSL")
            if has_add_28: score += 15; reasons.append("has ADD #28")
            if has_cond: score += 10; reasons.append("has conditional branch")
            if bl_count == 0: score += 10; reasons.append("no BL calls")

            # Check if any EWRAM address near gBattleTypeFlags is loaded
            for _, _, v in ldr_vals:
                if 0x02023350 <= v <= 0x02023380:
                    score += 20
                    reasons.append(f"refs EWRAM near gBattleTypeFlags (0x{v:08X})")
                    break

            if score >= 30:
                fallback_scored.append((score, fs, fe, func_addr, size, reasons, disasm, lit_set))

        fallback_scored.sort(key=lambda x: -x[0])

        print(f"  {len(fallback_scored)} fallback candidates")
        print()

        for rank, (score, fs, fe, func_addr, size, reasons, disasm, lit_set) in enumerate(fallback_scored[:10]):
            marker = "  <<<< BEST" if rank == 0 else ""
            print(f"  #{rank+1} Score={score} | 0x{func_addr:08X} ({size} bytes){marker}")
            for r in reasons:
                print(f"       - {r}")
            print(f"    Disassembly:")
            for rom_off, addr, mnem in disasm:
                func_off = rom_off - fs
                annotation = ""
                if f"0x{gBattleControllerExecFlags_ADDR:08X}" in mnem:
                    annotation = "  ; gBattleControllerExecFlags"
                print(f"      +0x{func_off:02X} | 0x{addr:08X}: {mnem}{annotation}")
            print()

    # =========================================================================
    # STEP 4: Cross-reference count (how many callers does the best candidate have?)
    # =========================================================================
    if scored:
        best_addr = scored[0][3]
        print("=" * 80)
        print(f"  STEP 4: Cross-reference count for best candidate 0x{best_addr:08X}")
        print("=" * 80)
        print()

        print(f"  Scanning ROM for BL calls to 0x{best_addr:08X}...")
        # Limit scan to first 2MB of ROM for speed
        callers = count_callers(rom_data, best_addr, max_rom_offset=min(len(rom_data), 0x200000))
        print(f"  Found {len(callers)} BL callers (in first 2MB)")
        print()

        if len(callers) > 0:
            # Show first 20 callers
            print(f"  First {min(20, len(callers))} callers:")
            for i, bl_pos in enumerate(callers[:20]):
                caller_fs = find_function_start(rom_data, bl_pos)
                caller_addr = ROM_BASE + caller_fs + 1 if caller_fs else "???"
                print(f"    BL at ROM 0x{bl_pos:06X} (0x{ROM_BASE + bl_pos:08X}), in function at {f'0x{caller_addr:08X}' if isinstance(caller_addr, int) else caller_addr}")
            if len(callers) > 20:
                print(f"    ... and {len(callers) - 20} more")
            print()

        # Also check top 3 candidates
        if len(scored) > 1:
            print("  Cross-ref counts for top candidates:")
            for rank in range(min(5, len(scored))):
                cand_addr = scored[rank][3]
                cand_callers = count_callers(rom_data, cand_addr, max_rom_offset=min(len(rom_data), 0x200000))
                marker = " <<<< highest" if rank == 0 and len(cand_callers) >= len(count_callers(rom_data, scored[1][3] if len(scored) > 1 else 0, max_rom_offset=min(len(rom_data), 0x200000))) else ""
                print(f"    0x{cand_addr:08X}: {len(cand_callers)} callers{marker}")
            print()

    # =========================================================================
    # STEP 5: Also check gBattleControllerExecFlags-ONLY functions as
    # MarkBattlerForControllerExec might access gBattleTypeFlags via a
    # base register loaded earlier (not in its own literal pool)
    # =========================================================================
    print("=" * 80)
    print("  STEP 5: gBattleControllerExecFlags-only small functions with TST+ORR+LSL")
    print("  (in case gBattleTypeFlags is loaded via base+offset)")
    print("=" * 80)
    print()

    # Find all small functions (~20-80 bytes) referencing gBattleControllerExecFlags
    # that have TST + ORR + LSL + conditional branch pattern
    alt_candidates = []
    for fs in sorted(bcef_funcs.keys()):
        fe = find_function_end(rom_data, fs, max_size=200)
        if fe is None:
            continue
        size = fe - fs
        if size > 100 or size < 14:
            continue

        func_addr = ROM_BASE + fs + 1
        disasm = disassemble_thumb(rom_data, fs, fe)

        has_tst = False
        has_orr = False
        has_lsl = False
        has_cond = False
        has_add_28 = False
        has_mov_1 = False
        bl_count = 0

        for _, _, mnem in disasm:
            if "TST" in mnem: has_tst = True
            if "ORR" in mnem: has_orr = True
            if "LSL" in mnem: has_lsl = True
            if mnem.startswith("BEQ") or mnem.startswith("BNE"): has_cond = True
            if "ADD" in mnem and "#28" in mnem: has_add_28 = True
            if "MOV" in mnem and ", #1" in mnem: has_mov_1 = True
            if "BL " in mnem: bl_count += 1

        # Must have: ORR + LSL + conditional branch (the core pattern)
        if has_orr and has_lsl and has_cond:
            score = 0
            reasons = []
            score += 20; reasons.append("has ORR + LSL + conditional branch")
            if has_tst: score += 10; reasons.append("has TST")
            if has_add_28: score += 20; reasons.append("has ADD #28 (link path)")
            if has_mov_1: score += 5; reasons.append("has MOV #1")
            if bl_count == 0: score += 10; reasons.append("no BL calls")
            if 20 <= size <= 60: score += 15; reasons.append(f"ideal size ({size} bytes)")
            elif size <= 80: score += 5; reasons.append(f"ok size ({size} bytes)")

            alt_candidates.append((score, fs, fe, func_addr, size, reasons, disasm))

    alt_candidates.sort(key=lambda x: -x[0])

    print(f"  {len(alt_candidates)} alternative candidates (ORR+LSL+cond in small func)")
    print()

    for rank, (score, fs, fe, func_addr, size, reasons, disasm) in enumerate(alt_candidates[:10]):
        print(f"  #{rank+1} Score={score} | 0x{func_addr:08X} ({size} bytes)")
        for r in reasons:
            print(f"       - {r}")
        print(f"    Disassembly:")
        for rom_off, addr, mnem in disasm:
            func_off = rom_off - fs
            annotation = ""
            if f"0x{gBattleControllerExecFlags_ADDR:08X}" in mnem:
                annotation = "  ; gBattleControllerExecFlags"
            elif f"0x{gBattleTypeFlags_ADDR:08X}" in mnem:
                annotation = "  ; gBattleTypeFlags"
            print(f"      +0x{func_off:02X} | 0x{addr:08X}: {mnem}{annotation}")

        # Count cross-refs for this candidate
        callers = count_callers(rom_data, func_addr, max_rom_offset=min(len(rom_data), 0x200000))
        print(f"    Cross-refs: {len(callers)} BL callers (first 2MB)")
        print()

    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    print("=" * 80)
    print("  FINAL SUMMARY")
    print("=" * 80)
    print()

    # Combine all candidates from all approaches
    all_results = []
    for score, fs, fe, func_addr, size, reasons, disasm, lit_set in scored:
        callers = count_callers(rom_data, func_addr, max_rom_offset=min(len(rom_data), 0x200000))
        all_results.append((score, func_addr, size, len(callers), reasons, "literal pool match"))

    for score, fs, fe, func_addr, size, reasons, disasm in alt_candidates:
        callers = count_callers(rom_data, func_addr, max_rom_offset=min(len(rom_data), 0x200000))
        all_results.append((score, func_addr, size, len(callers), reasons, "pattern match"))

    # Re-sort by combined score (original score + caller bonus)
    # MarkBattlerForControllerExec is called VERY frequently (dozens or hundreds of times)
    for i, (score, addr, size, ncallers, reasons, method) in enumerate(all_results):
        caller_bonus = min(ncallers * 2, 100)  # up to +100 for many callers
        all_results[i] = (score + caller_bonus, addr, size, ncallers, reasons, method)

    all_results.sort(key=lambda x: -x[0])

    print("  Top candidates by combined score (pattern + cross-refs):")
    print()
    for rank, (final_score, addr, size, ncallers, reasons, method) in enumerate(all_results[:10]):
        marker = " <<<< BEST MATCH" if rank == 0 else ""
        print(f"  #{rank+1} FinalScore={final_score} | 0x{addr:08X} | {size} bytes | {ncallers} callers | [{method}]{marker}")
        for r in reasons:
            print(f"       - {r}")
        print()

    if all_results:
        best = all_results[0]
        print(f"  >>> RESULT: MarkBattlerForControllerExec = 0x{best[1]:08X}")
        print(f"  >>> Size: {best[2]} bytes")
        print(f"  >>> Cross-references (BL callers): {best[3]}")
        print(f"  >>> ROM offset: 0x{(best[1] - ROM_BASE - 1):06X}")
    else:
        print("  >>> NO CANDIDATES FOUND")

    print()
    print("=" * 80)
    print("  SCAN COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
