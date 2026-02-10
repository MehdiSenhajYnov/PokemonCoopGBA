#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v6: Find ALL callers of SortBattlersBySpeed

HandleEndTurnOrder (battle_end_turn.c:28) calls SortBattlersBySpeed(gBattlerByTurnOrder, FALSE).
SortBattlersBySpeed = 0x0804B430 (confirmed from v4/v5 BL target).

Strategy:
1. Find ALL BL 0x0804B430 in the ROM
2. For each call site, check if R0 = gBattlerByTurnOrder (0x020233F6) nearby
3. For matching call sites, disassemble backward to find the small function
4. Look for LDRH+ADD+STRH (gBattleTurnCounter++) in those functions
"""

import struct
import sys
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

KNOWN = {
    0x020233F6: "gBattlerByTurnOrder",
    0x020233F2: "gActionsByTurnOrder",
    0x02023598: "gChosenActionByBattler",
    0x020235FA: "gChosenMoveByBattler",
    0x0202370E: "gBattleCommunication",
    0x020233E4: "gBattlersCount",
    0x020233FC: "gBattleMons",
    0x020233DC: "gActiveBattler",
    0x02023364: "gBattleTypeFlags",
    0x020233E0: "gBattleControllerExecFlags",
    0x020233EE: "gBattlerPositions",
    0x020233E6: "gBattlerPartyIndexes",
    0x020233FA: "gCurrentTurnActionNumber",
    0x020233FB: "gCurrentActionFuncId",
    0x02023A18: "gBattleResources",
    0x0202356C: "gBattlerSpriteIds",
    0x02023594: "gBattlescriptCurrInstr",
    0x0202359C: "gBattlerAttacker",
    0x020239D0: "gBattleStruct",
    0x02023A0C: "gBattleSpritesDataPtr",
}


def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def find_all_bl_targets(rom_data, target_addr):
    """Find all BL instructions that call target_addr."""
    results = []
    for pos in range(0, len(rom_data) - 3, 2):
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xF800) != 0xF000:
            continue
        if pos + 2 >= len(rom_data):
            continue
        next_instr = read_u16_le(rom_data, pos + 2)
        if (next_instr & 0xF800) != 0xF800:
            continue

        off11hi = instr & 0x07FF
        off11lo = next_instr & 0x07FF
        full_off = (off11hi << 12) | (off11lo << 1)
        if full_off >= 0x400000:
            full_off -= 0x800000
        rom_addr = ROM_BASE + pos
        bl_target = rom_addr + 4 + full_off

        if bl_target == target_addr:
            results.append(pos)

    return results


def find_all_refs(rom_data, target_value):
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs


def disasm_simple(rom_data, start, count, known):
    """Simple disassembler returning text lines."""
    lines = []
    pos = start
    for _ in range(count):
        if pos + 1 >= len(rom_data):
            break
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        desc = f"0x{instr:04X}"

        if (instr & 0xFF00) in (0xB400, 0xB500):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100:
                regs.append("LR" if (instr & 0xFF00) == 0xB500 else "R8")
            desc = f"PUSH {{{', '.join(regs)}}}"
        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100:
                regs.append("PC" if (instr & 0xFF00) == 0xBD00 else "R8")
            desc = f"POP {{{', '.join(regs)}}}"
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            pool_addr = ((rom_addr + 4) & ~3) + imm8 * 4
            pf = pool_addr - ROM_BASE
            if 0 <= pf < len(rom_data) - 3:
                val = read_u32_le(rom_data, pf)
                name = known.get(val, "")
                if name:
                    desc = f"LDR R{rd}, =0x{val:08X}  <{name}>"
                else:
                    desc = f"LDR R{rd}, =0x{val:08X}"
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"MOV R{rd}, #0x{imm:X}"
        elif (instr & 0xFF00) == 0x3000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"ADD R{rd}, #0x{imm:X}"
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, #{imm}"
        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"STRH R{rd}, [R{rb}, #0x{off:X}]"
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
        elif (instr & 0xFFC0) == 0x4280:
            rn = instr & 7; rm = (instr >> 3) & 7
            desc = f"CMP R{rn}, R{rm}"
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"CMP R{rn}, #0x{imm:X}"
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF
            names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE","???","SWI"]
            off = instr & 0xFF
            if off >= 0x80: off -= 0x100
            target = rom_addr + 4 + off * 2
            desc = f"{names[cond]} 0x{target:08X}"
        elif (instr & 0xF800) == 0xE000:
            off = instr & 0x7FF
            if off >= 0x400: off -= 0x800
            target = rom_addr + 4 + off * 2
            desc = f"B 0x{target:08X}"
        elif instr == 0x4770:
            desc = "BX LR"
        elif (instr & 0xFF00) == 0x4600:
            rd = ((instr >> 4) & 8) | (instr & 7)
            rm = (instr >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"
        elif (instr & 0xFC00) == 0x4000:
            op = (instr >> 6) & 0xF
            rs = (instr >> 3) & 7; rd = instr & 7
            alu = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                   "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            desc = f"{alu[op]} R{rd}, R{rs}"
        elif (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16_le(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                off11hi = instr & 0x07FF
                off11lo = next_instr & 0x07FF
                full_off = (off11hi << 12) | (off11lo << 1)
                if full_off >= 0x400000: full_off -= 0x800000
                target = rom_addr + 4 + full_off
                lines.append(f"  {rom_addr:08X}:  {instr:04X} {next_instr:04X}  BL 0x{target:08X}")
                pos += 4
                continue

        lines.append(f"  {rom_addr:08X}:  {instr:04X}       {desc}")
        pos += 2

    return lines


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    SORT_BATTLERS_BY_SPEED = 0x0804B430

    # =========================================================================
    # Step 1: Find ALL BL calls to SortBattlersBySpeed
    # =========================================================================
    print("=" * 80)
    print(f"  Step 1: Find ALL BL 0x{SORT_BATTLERS_BY_SPEED:08X} (SortBattlersBySpeed)")
    print("=" * 80)
    print()

    bl_sites = find_all_bl_targets(rom_data, SORT_BATTLERS_BY_SPEED)
    print(f"  Found {len(bl_sites)} call sites:")
    for site in bl_sites:
        print(f"    0x{ROM_BASE + site:08X}")
    print()

    # =========================================================================
    # Step 2: For each call site, check context
    # =========================================================================
    print("=" * 80)
    print("  Step 2: Analyze each call site")
    print("=" * 80)
    print()

    for site_off in bl_sites:
        site_rom = ROM_BASE + site_off

        # Check 20 instructions before the BL for LDR =gBattlerByTurnOrder
        has_btto = False
        for back in range(2, 42, 2):
            check_pos = site_off - back
            if check_pos < 0:
                break
            ci = read_u16_le(rom_data, check_pos)
            if (ci & 0xF800) == 0x4800:
                pc = ROM_BASE + check_pos
                pool_addr = ((pc + 4) & ~3) + (ci & 0xFF) * 4
                pf = pool_addr - ROM_BASE
                if 0 <= pf < len(rom_data) - 3:
                    val = read_u32_le(rom_data, pf)
                    if val == 0x020233F6:
                        has_btto = True
                        break

        # Find function start (PUSH)
        func_start = None
        for back in range(2, 8192, 2):
            check_pos = site_off - back
            if check_pos < 0:
                break
            ci = read_u16_le(rom_data, check_pos)
            if (ci & 0xFF00) in (0xB400, 0xB500):
                func_start = check_pos
                break

        func_size = "unknown"
        if func_start:
            func_size = f"{site_off - func_start}+ bytes"

        print(f"  Call site: 0x{site_rom:08X}")
        print(f"    Has gBattlerByTurnOrder in context: {has_btto}")
        if func_start:
            print(f"    Function start: 0x{ROM_BASE + func_start:08X} ({func_size})")

        # Find the nearest PUSH before the BL (could be a different function if
        # HandleEndTurnOrder is small and close to the BL)
        nearest_push = None
        for back in range(2, 200, 2):
            check_pos = site_off - back
            if check_pos < 0:
                break
            ci = read_u16_le(rom_data, check_pos)
            if (ci & 0xFF00) in (0xB400, 0xB500):
                nearest_push = check_pos
                break

        if nearest_push and nearest_push != func_start:
            dist = site_off - nearest_push
            print(f"    ** Nearest PUSH (within 200 bytes): 0x{ROM_BASE + nearest_push:08X} ({dist} bytes before BL)")
        print()

    # =========================================================================
    # Step 3: Disassemble ALL call sites with gBattlerByTurnOrder
    # =========================================================================
    print("=" * 80)
    print("  Step 3: Full disassembly around gBattlerByTurnOrder + SortBattlersBySpeed calls")
    print("=" * 80)
    print()

    for site_off in bl_sites:
        site_rom = ROM_BASE + site_off

        # Check if gBattlerByTurnOrder is nearby
        has_btto = False
        for back in range(2, 42, 2):
            check_pos = site_off - back
            if check_pos < 0:
                break
            ci = read_u16_le(rom_data, check_pos)
            if (ci & 0xF800) == 0x4800:
                pc = ROM_BASE + check_pos
                pool_addr = ((pc + 4) & ~3) + (ci & 0xFF) * 4
                pf = pool_addr - ROM_BASE
                if 0 <= pf < len(rom_data) - 3:
                    val = read_u32_le(rom_data, pf)
                    if val == 0x020233F6:
                        has_btto = True
                        break

        if not has_btto:
            continue

        print(f"  === Call site 0x{site_rom:08X} (has gBattlerByTurnOrder) ===")
        print()

        # Disassemble 80 instructions before and 20 after
        start = max(0, site_off - 160)
        lines = disasm_simple(rom_data, start, 120, KNOWN)
        for line in lines:
            # Mark the BL instruction
            if f"{site_rom:08X}" in line:
                print(f">>>{line}  <<< SortBattlersBySpeed")
            elif "gBattlerByTurnOrder" in line:
                print(f">>>{line}")
            elif "LDRH" in line or "STRH" in line:
                print(f"  *{line}")
            else:
                print(f"   {line}")
        print()

    # =========================================================================
    # Step 4: Alternative — search for HandleEndTurnOrder by its unique pattern
    #         It must reference gBattleStruct (0x020239D0) AND gBattlerByTurnOrder
    #         AND gBattlersCount in close proximity
    # =========================================================================
    print("=" * 80)
    print("  Step 4: Find HandleEndTurnOrder via gBattleStruct + gBattlerByTurnOrder pattern")
    print("  HandleEndTurnOrder does:")
    print("    gBattleTurnCounter++")
    print("    gBattleStruct->eventState.endTurn++")
    print("    for(i<gBattlersCount) gBattlerByTurnOrder[i]=i")
    print("    SortBattlersBySpeed(gBattlerByTurnOrder, FALSE)")
    print("=" * 80)
    print()

    # gBattleStruct is accessed via: gBattleResources->battleStruct
    # gBattleResources = 0x02023A18, first field ptr = gBattleStruct
    # OR gBattleStruct might be stored separately

    # Find call sites to SortBattlersBySpeed that also have gBattlersCount nearby
    for site_off in bl_sites:
        site_rom = ROM_BASE + site_off

        # Scan 60 instructions before for both gBattlerByTurnOrder AND gBattlersCount
        has_btto = False
        has_bc = False
        has_struct = False
        ewram_addrs = set()

        for back in range(2, 120, 2):
            check_pos = site_off - back
            if check_pos < 0:
                break
            ci = read_u16_le(rom_data, check_pos)
            if (ci & 0xF800) == 0x4800:
                pc = ROM_BASE + check_pos
                pool_addr = ((pc + 4) & ~3) + (ci & 0xFF) * 4
                pf = pool_addr - ROM_BASE
                if 0 <= pf < len(rom_data) - 3:
                    val = read_u32_le(rom_data, pf)
                    if val == 0x020233F6:
                        has_btto = True
                    elif val == 0x020233E4:
                        has_bc = True
                    elif val == 0x020239D0 or val == 0x02023A18:
                        has_struct = True
                    if 0x02020000 <= val < 0x02040000:
                        ewram_addrs.add(val)

        if has_btto and has_bc:
            print(f"  Call site 0x{site_rom:08X}: gBattlerByTurnOrder=YES, gBattlersCount=YES, gBattleStruct={has_struct}")
            print(f"    EWRAM refs in context: {', '.join(f'0x{a:08X}' for a in sorted(ewram_addrs))}")

            # Look for LDRH+ADD+STRH pattern in this vicinity
            found_inc = False
            for back in range(2, 120, 2):
                check_pos = site_off - back
                if check_pos < 0:
                    break
                ci = read_u16_le(rom_data, check_pos)
                # LDRH
                if (ci & 0xFE00) != 0x8800:
                    continue
                rd = ci & 7
                rb = (ci >> 3) & 7
                ldrh_off = ((ci >> 6) & 0x1F) * 2

                # Check next instructions
                for delta in range(2, 8, 2):
                    if check_pos + delta + 1 >= len(rom_data):
                        break
                    ni = read_u16_le(rom_data, check_pos + delta)
                    added = -1

                    # ADD Rx, #1
                    if (ni & 0xFF00) == 0x3000 and (ni & 0xFF) == 1:
                        added = (ni >> 8) & 7
                    # ADDS Rd, Rs, #1
                    elif (ni & 0xFE00) == 0x1C00 and ((ni >> 6) & 7) == 1:
                        added = ni & 7

                    if added < 0:
                        continue

                    # Check for STRH
                    for delta2 in range(delta + 2, delta + 6, 2):
                        if check_pos + delta2 + 1 >= len(rom_data):
                            break
                        si = read_u16_le(rom_data, check_pos + delta2)
                        # STRH with same base and offset
                        expected = 0x8000 | (rb << 3) | added | ((ldrh_off // 2) << 6)
                        if si == expected:
                            # Trace rb back to find what address it holds
                            for trace_back in range(2, 20, 2):
                                tp = check_pos - trace_back
                                if tp < 0:
                                    break
                                ti = read_u16_le(rom_data, tp)
                                if (ti & 0xF800) == 0x4800 and ((ti >> 8) & 7) == rb:
                                    pc = ROM_BASE + tp
                                    pa = ((pc + 4) & ~3) + (ti & 0xFF) * 4
                                    pf = pa - ROM_BASE
                                    if 0 <= pf < len(rom_data) - 3:
                                        val = read_u32_le(rom_data, pf)
                                        eff = val + ldrh_off
                                        name = KNOWN.get(eff, KNOWN.get(val, ""))
                                        total = len(find_all_refs(rom_data, val))
                                        print(f"    ** INCREMENT: base=0x{val:08X}+0x{ldrh_off:X} = 0x{eff:08X} ({total} refs) {name}")
                                        found_inc = True
                                    break

            if not found_inc:
                # Maybe the increment uses a register that was loaded much earlier
                # or uses gBattleStruct-relative access
                print(f"    No direct LDRH+ADD+STRH pattern found in 120 bytes before BL")

                # Check for LDR [Rx, #offset] + LDRH/STRH chain (struct access)
                print(f"    Checking for struct-relative halfword increment...")
                for back in range(2, 120, 2):
                    check_pos = site_off - back
                    if check_pos < 0:
                        break
                    ci = read_u16_le(rom_data, check_pos)
                    # LDR Rd, [Rb, #offset] -- load struct pointer field
                    if (ci & 0xFE00) == 0x6800:
                        load_rd = ci & 7
                        load_rb = (ci >> 3) & 7
                        load_off = ((ci >> 6) & 0x1F) * 4

                        # Check if next is LDRH from load_rd
                        if check_pos + 2 < len(rom_data):
                            ni = read_u16_le(rom_data, check_pos + 2)
                            if (ni & 0xFE00) == 0x8800 and ((ni >> 3) & 7) == load_rd:
                                h_rd = ni & 7
                                h_off = ((ni >> 6) & 0x1F) * 2
                                # Check for ADD +1
                                if check_pos + 4 < len(rom_data):
                                    ai = read_u16_le(rom_data, check_pos + 4)
                                    is_add1 = False
                                    if (ai & 0xFF00) == 0x3000 and (ai & 0xFF) == 1 and ((ai >> 8) & 7) == h_rd:
                                        is_add1 = True
                                    elif (ai & 0xFE00) == 0x1C00 and ((ai >> 6) & 7) == 1 and ((ai >> 3) & 7) == h_rd:
                                        is_add1 = True
                                    if is_add1 and check_pos + 6 < len(rom_data):
                                        si = read_u16_le(rom_data, check_pos + 6)
                                        if (si & 0xFE00) == 0x8000 and ((si >> 3) & 7) == load_rd:
                                            print(f"    ** STRUCT INCREMENT: [R{load_rb}+0x{load_off:X}]→R{load_rd}, LDRH [R{load_rd}+0x{h_off:X}], +1, STRH")
                                            # Show context
                                            lines = disasm_simple(rom_data, check_pos - 6, 10, KNOWN)
                                            for line in lines:
                                                print(f"      {line}")
                                            print()

            print()

    # =========================================================================
    # Step 5: HandleEndTurnOrder is in battle_end_turn.c — different translation unit
    #         It might be very small. Search for small functions (PUSH...POP) near
    #         SortBattlersBySpeed call sites.
    # =========================================================================
    print("=" * 80)
    print("  Step 5: Search for small functions near SortBattlersBySpeed calls")
    print("  HandleEndTurnOrder is ~40-60 instructions, in battle_end_turn.c")
    print("=" * 80)
    print()

    for site_off in bl_sites:
        site_rom = ROM_BASE + site_off

        # Find the nearest PUSH before the BL (within 200 bytes)
        nearest_push = None
        for back in range(2, 400, 2):
            check_pos = site_off - back
            if check_pos < 0:
                break
            ci = read_u16_le(rom_data, check_pos)
            if (ci & 0xFF00) in (0xB400, 0xB500):
                nearest_push = check_pos
                break

        if nearest_push is None:
            continue

        dist_to_bl = site_off - nearest_push

        # Find the next POP {PC} or BX LR after the BL
        next_pop = None
        for fwd in range(4, 200, 2):
            check_pos = site_off + fwd
            if check_pos + 1 >= len(rom_data):
                break
            ci = read_u16_le(rom_data, check_pos)
            if (ci & 0xFF00) == 0xBD00 or ci == 0x4770:
                next_pop = check_pos
                break

        if next_pop is None:
            continue

        func_size = next_pop + 2 - nearest_push
        if func_size > 300:
            continue  # Too large

        # Check if this small function contains gBattlerByTurnOrder
        has_btto = False
        for scan in range(nearest_push, next_pop + 2, 2):
            ci = read_u16_le(rom_data, scan)
            if (ci & 0xF800) == 0x4800:
                pc = ROM_BASE + scan
                pool_addr = ((pc + 4) & ~3) + (ci & 0xFF) * 4
                pf = pool_addr - ROM_BASE
                if 0 <= pf < len(rom_data) - 3:
                    val = read_u32_le(rom_data, pf)
                    if val == 0x020233F6:
                        has_btto = True
                        break

        if not has_btto:
            continue

        print(f"  Small function: 0x{ROM_BASE + nearest_push:08X} - 0x{ROM_BASE + next_pop:08X} ({func_size} bytes)")
        print(f"    BL SortBattlersBySpeed at 0x{site_rom:08X}")
        print()

        # Full disassembly
        lines = disasm_simple(rom_data, nearest_push, func_size // 2 + 20, KNOWN)
        for line in lines:
            if "LDRH" in line or "STRH" in line:
                print(f"  *{line}")
            elif "SortBattlers" in line or "0804B430" in line:
                print(f">>>{line}")
            elif "gBattlerByTurnOrder" in line or "gBattlersCount" in line:
                print(f">>>{line}")
            elif "PUSH" in line or "POP" in line:
                print(f"==={line}")
            else:
                print(f"   {line}")
        print()

        # Collect all EWRAM addresses loaded in this function
        ewram = {}
        for scan in range(nearest_push, next_pop + 64, 2):
            if scan + 1 >= len(rom_data):
                break
            ci = read_u16_le(rom_data, scan)
            if (ci & 0xF800) == 0x4800:
                pc = ROM_BASE + scan
                pool_addr = ((pc + 4) & ~3) + (ci & 0xFF) * 4
                pf = pool_addr - ROM_BASE
                if 0 <= pf < len(rom_data) - 3:
                    val = read_u32_le(rom_data, pf)
                    if 0x02020000 <= val < 0x02040000:
                        name = KNOWN.get(val, "")
                        total = len(find_all_refs(rom_data, val))
                        ewram[val] = (total, name)

        print(f"  EWRAM addresses loaded in function:")
        for addr in sorted(ewram.keys()):
            total, name = ewram[addr]
            print(f"    0x{addr:08X}: {total:4d} refs  {name}")
        print()
        print()

    print("  DONE")
    print()


if __name__ == "__main__":
    main()
