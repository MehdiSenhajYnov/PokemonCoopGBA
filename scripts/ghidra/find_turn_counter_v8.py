#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v8: Find sEndTurnEffectHandlers table

Strategy: sEndTurnEffectHandlers is a ROM table of function pointers.
HandleEndTurnOrder is the FIRST entry (index 0 = ENDTURN_ORDER).

The table contains THUMB function addresses (odd = bit 0 set).
Each function is called with (u32 battler) and returns bool32.

To find the table:
1. The table must contain SortBattlersBySpeed callers (HandleEndTurnOrder calls it)
2. The table entries are 4-byte THUMB addresses (bit 0 set, in ROM range 0x08xxxxxx)
3. DoEndTurnEffects loads the table address and indexes into it
4. There should be ~40+ consecutive THUMB function pointers

Alternative: Since HandleEndTurnOrder calls SortBattlersBySpeed(gBattlerByTurnOrder, FALSE),
find ALL SortBattlersBySpeed callers and check which ones also access gBattleResources
(for gBattleStruct->eventState.endTurn++).
"""

import struct
import sys
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

KNOWN = {
    0x020233F6: "gBattlerByTurnOrder",
    0x020233E4: "gBattlersCount",
    0x020233FC: "gBattleMons",
    0x02023A18: "gBattleResources",
    0x020239D0: "gBattleStruct",
    0x02023594: "gBattlescriptCurrInstr",
    0x0202359C: "gBattlerAttacker",
}

def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def find_all_refs(rom_data, target_value):
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs

def find_bl_target(rom_data, pos):
    """Get the BL target at position pos (must be a BL instruction)."""
    instr = read_u16_le(rom_data, pos)
    next_instr = read_u16_le(rom_data, pos + 2)
    if (instr & 0xF800) != 0xF000 or (next_instr & 0xF800) != 0xF800:
        return None
    off11hi = instr & 0x07FF
    off11lo = next_instr & 0x07FF
    full_off = (off11hi << 12) | (off11lo << 1)
    if full_off >= 0x400000:
        full_off -= 0x800000
    return ROM_BASE + pos + 4 + full_off

def disasm_simple(rom_data, start, count, known):
    lines = []
    pos = start
    for _ in range(count):
        if pos + 1 >= len(rom_data):
            break
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        desc = f"0x{instr:04X}"
        extra = ""

        if (instr & 0xFF00) in (0xB400, 0xB500):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100: regs.append("LR" if (instr & 0xFF00) == 0xB500 else "R8")
            desc = f"PUSH {{{', '.join(regs)}}}"
        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100: regs.append("PC" if (instr & 0xFF00) == 0xBD00 else "R8")
            desc = f"POP {{{', '.join(regs)}}}"
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7; imm8 = instr & 0xFF
            pa = ((rom_addr + 4) & ~3) + imm8 * 4
            pf = pa - ROM_BASE
            if 0 <= pf < len(rom_data) - 3:
                val = read_u32_le(rom_data, pf)
                name = known.get(val, "")
                desc = f"LDR R{rd}, =0x{val:08X}" + (f"  <{name}>" if name else "")
        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rb}, #0x{off:X}]"
            extra = " ***LDRH"
        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"STRH R{rd}, [R{rb}, #0x{off:X}]"
            extra = " ***STRH"
        elif (instr & 0xFE00) == 0x6800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 4
            desc = f"LDR R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x6000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 4
            desc = f"STR R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x7800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = (instr >> 6) & 0x1F
            desc = f"LDRB R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x7000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = (instr >> 6) & 0x1F
            desc = f"STRB R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFF00) == 0x3000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"ADD R{rd}, #0x{imm:X}"
            if imm == 1: extra = " <<<+1"
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, #{imm}"
            if imm == 1: extra = " <<<+1"
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"MOV R{rd}, #0x{imm:X}"
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"CMP R{rn}, #0x{imm:X}"
        elif (instr & 0xFFC0) == 0x4280:
            rn = instr & 7; rm = (instr >> 3) & 7
            desc = f"CMP R{rn}, R{rm}"
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF
            names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE","???","SWI"]
            off = instr & 0xFF
            if off >= 0x80: off -= 0x100
            desc = f"{names[cond]} 0x{rom_addr + 4 + off * 2:08X}"
        elif (instr & 0xF800) == 0xE000:
            off = instr & 0x7FF
            if off >= 0x400: off -= 0x800
            desc = f"B 0x{rom_addr + 4 + off * 2:08X}"
        elif instr == 0x4770:
            desc = "BX LR"
        elif (instr & 0xFF00) == 0x4600:
            rd = ((instr >> 4) & 8) | (instr & 7)
            rm = (instr >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"
        elif (instr & 0xFC00) == 0x4000:
            op = (instr >> 6) & 0xF; rs = (instr >> 3) & 7; rd = instr & 7
            alu = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR","TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            desc = f"{alu[op]} R{rd}, R{rs}"
        elif (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            ni = read_u16_le(rom_data, pos + 2)
            if (ni & 0xF800) == 0xF800:
                t = find_bl_target(rom_data, pos)
                if t == 0x0804B430:
                    extra = " <<<SortBattlersBySpeed"
                lines.append(f"  {rom_addr:08X}: {instr:04X} {ni:04X}  BL 0x{t:08X}{extra}")
                pos += 4
                continue

        lines.append(f"  {rom_addr:08X}: {instr:04X}      {desc}{extra}")
        pos += 2
    return lines


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    SORT_BY_SPEED = 0x0804B430

    # =========================================================================
    # Step 1: Find all SortBattlersBySpeed callers that also access gBattleResources
    # =========================================================================
    print("=" * 80)
    print("  Step 1: Find SortBattlersBySpeed callers that also access gBattleResources")
    print("=" * 80)
    print()

    # Find all BL SortBattlersBySpeed
    bl_sites = []
    for pos in range(0, len(rom_data) - 3, 2):
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xF800) != 0xF000:
            continue
        ni = read_u16_le(rom_data, pos + 2)
        if (ni & 0xF800) != 0xF800:
            continue
        t = find_bl_target(rom_data, pos)
        if t == SORT_BY_SPEED:
            bl_sites.append(pos)

    print(f"  Total SortBattlersBySpeed call sites: {len(bl_sites)}")
    print()

    # For each call site, find the PUSH before it (function start)
    # Then check if the function also loads gBattleResources or gBattleStruct
    candidates = []
    for site_off in bl_sites:
        # Find nearest PUSH
        func_start = None
        for back in range(2, 2000, 2):
            check_pos = site_off - back
            if check_pos < 0:
                break
            ci = read_u16_le(rom_data, check_pos)
            if (ci & 0xFF00) in (0xB400, 0xB500):
                func_start = check_pos
                break

        if func_start is None:
            continue

        # Find function end
        func_end = func_start
        pop_seen = False
        for pos in range(func_start + 2, func_start + 2000, 2):
            ci = read_u16_le(rom_data, pos)
            if (ci & 0xFF00) == 0xBD00 or ci == 0x4770:
                func_end = pos + 2
                pop_seen = True
                break

        if not pop_seen:
            continue

        func_size = func_end - func_start

        # Scan for LDR pool refs in this function
        has_gBR = False
        has_gBS = False
        has_btto = False
        has_bc = False
        ewram_addrs = set()

        for scan in range(func_start, min(func_end + 128, len(rom_data) - 3), 2):
            ci = read_u16_le(rom_data, scan)
            if (ci & 0xF800) == 0x4800:
                pc = ROM_BASE + scan
                pa = ((pc + 4) & ~3) + (ci & 0xFF) * 4
                pf = pa - ROM_BASE
                if 0 <= pf < len(rom_data) - 3:
                    val = read_u32_le(rom_data, pf)
                    if val == 0x02023A18:
                        has_gBR = True
                    elif val == 0x020239D0:
                        has_gBS = True
                    elif val == 0x020233F6:
                        has_btto = True
                    elif val == 0x020233E4:
                        has_bc = True
                    if 0x02020000 <= val < 0x02040000:
                        ewram_addrs.add(val)

        if (has_gBR or has_gBS) and has_btto and has_bc:
            candidates.append((func_start, func_end, func_size, has_gBR, has_gBS, ewram_addrs))

    print(f"  Candidates with gBattleResources/gBattleStruct + gBattlerByTurnOrder + gBattlersCount: {len(candidates)}")
    print()

    for func_start, func_end, func_size, has_gBR, has_gBS, ewram_addrs in candidates:
        func_rom = ROM_BASE + func_start
        print(f"  Function 0x{func_rom:08X} ({func_size} bytes)")
        print(f"    gBattleResources={has_gBR}, gBattleStruct={has_gBS}")
        print(f"    EWRAM: {', '.join(f'0x{a:08X}' for a in sorted(ewram_addrs))}")
        print()

        # Full disassembly
        lines = disasm_simple(rom_data, func_start, func_size // 2 + 20, KNOWN)
        for line in lines:
            print(line)
        print()
        print()

    # =========================================================================
    # Step 2: Also try to find sEndTurnEffectHandlers table in ROM
    # The table is an array of THUMB function pointers (0x08xxxxxx | 1)
    # near the HandleEndTurn* functions.
    # Since HandleEndTurnOrder must be one of these small functions,
    # find groups of 20+ consecutive THUMB function pointers.
    # =========================================================================
    print("=" * 80)
    print("  Step 2: Find function pointer tables (20+ consecutive THUMB ptrs)")
    print("  Looking for sEndTurnEffectHandlers table")
    print("=" * 80)
    print()

    # Scan ROM for sequences of 20+ consecutive THUMB function pointers
    min_entries = 20
    pos = 0
    found_tables = []
    while pos < len(rom_data) - 4 * min_entries:
        count = 0
        start = pos
        while pos < len(rom_data) - 3:
            val = read_u32_le(rom_data, pos)
            # Check if it looks like a THUMB function pointer
            if (val & 0xFF000001) == 0x08000001 and val < ROM_BASE + len(rom_data):
                count += 1
                pos += 4
            else:
                break

        if count >= min_entries:
            found_tables.append((start, count))
            # Check if any entry points to a SortBattlersBySpeed caller
            has_sort_caller = False
            for i in range(count):
                entry = read_u32_le(rom_data, start + i * 4)
                func_off = (entry & ~1) - ROM_BASE
                # Check next 200 bytes for BL SortBattlersBySpeed
                for check in range(func_off, min(func_off + 300, len(rom_data) - 3), 2):
                    ci = read_u16_le(rom_data, check)
                    if (ci & 0xF800) == 0xF000 and check + 2 < len(rom_data):
                        ni = read_u16_le(rom_data, check + 2)
                        if (ni & 0xF800) == 0xF800:
                            t = find_bl_target(rom_data, check)
                            if t == SORT_BY_SPEED:
                                has_sort_caller = True
                                break
                if has_sort_caller:
                    break

            print(f"  Table at 0x{ROM_BASE + start:08X}: {count} entries, has SortBattlersBySpeed caller: {has_sort_caller}")

            if has_sort_caller:
                # Print first few entries
                for i in range(min(count, 5)):
                    entry = read_u32_le(rom_data, start + i * 4)
                    print(f"    [{i}] = 0x{entry:08X}")

                # Disassemble the first entry (should be HandleEndTurnOrder)
                first_entry = read_u32_le(rom_data, start)
                func_off = (first_entry & ~1) - ROM_BASE
                print(f"\n  Disassembly of first entry (0x{first_entry:08X}) = HandleEndTurnOrder:")
                print()
                lines = disasm_simple(rom_data, func_off, 80, KNOWN)
                for line in lines:
                    print(line)
                print()
        else:
            pos = start + 4  # Skip and try next

    if not found_tables:
        print("  No tables found with 20+ entries")

    print()
    print("  DONE")


if __name__ == "__main__":
    main()
