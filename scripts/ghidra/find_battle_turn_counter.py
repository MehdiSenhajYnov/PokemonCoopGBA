#!/usr/bin/env python3
"""
Focused scanner to find gBattleTurnCounter in Pokemon Run & Bun ROM.

Strategy: TryDoEventsBeforeFirstTurn references ALL of:
  - gBattlerByTurnOrder (0x020233F6, confirmed)
  - gChosenActionByBattler (0x02023598, confirmed)
  - gChosenMoveByBattler (0x020235FA, confirmed)
  - gBattleTurnCounter (UNKNOWN, u16)

Find function(s) that reference the first 3, then check what other
addresses in the 0x02023800-0x02023A18 range they also reference.
The most likely candidate is gBattleTurnCounter.

Also: gBattleTurnCounter is incremented each turn in BattleTurnPassed:
    gBattleTurnCounter++;
This means it's referenced in multiple battle functions.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Confirmed addresses from find_turn_vars.py
CONFIRMED = {
    "gBattlerByTurnOrder":    0x020233F6,
    "gChosenActionByBattler": 0x02023598,
    "gChosenMoveByBattler":   0x020235FA,
    "gBattleCommunication":   0x0202370E,
    "gBattlersCount":         0x020233E4,
    "gBattleMons":            0x020233FC,
    "gActiveBattler":         0x020233DC,
    "gBattleTypeFlags":       0x02023364,
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

def find_function_start(rom_data, offset):
    for back in range(2, 4096, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in (0xB400, 0xB500):
            return pos
    return None

def is_ldr_pc_relative(instr):
    return (instr & 0xF800) == 0x4800

def get_ldr_pool_offset(instr, pc):
    if not is_ldr_pc_relative(instr):
        return None
    imm8 = instr & 0xFF
    pool_addr = ((pc + 4) & ~3) + imm8 * 4
    return pool_addr

def get_ewram_addrs_in_function(rom_data, func_start, max_size=4096):
    """Get all EWRAM addresses loaded via LDR in a function."""
    results = set()
    end = min(func_start + max_size, len(rom_data) - 3)
    pos = func_start
    pop_count = 0
    while pos < end:
        instr = read_u16_le(rom_data, pos)
        if pos > func_start + 4 and (instr & 0xFF00) == 0xBD00:
            pop_count += 1
            if pop_count >= 2:
                break
        if is_ldr_pc_relative(instr):
            pool_off = get_ldr_pool_offset(instr, ROM_BASE + pos)
            file_off = pool_off - ROM_BASE
            if 0 <= file_off < len(rom_data) - 3:
                val = read_u32_le(rom_data, file_off)
                if 0x02000000 <= val < 0x02040000:
                    results.add(val)
        pos += 2
    return results

def analyze_function(rom_data, func_offset, max_size=8192):
    """Analyze function: size, BL targets, all LDR literals."""
    size = None
    bl_targets = []
    pos = func_offset
    end = min(func_offset + max_size, len(rom_data) - 1)

    while pos < end:
        instr = read_u16_le(rom_data, pos)
        if pos > func_offset + 2:
            if (instr & 0xFF00) == 0xBD00 or instr == 0x4770:
                size = pos + 2 - func_offset
                break
        if pos + 2 < end:
            next_instr = read_u16_le(rom_data, pos + 2)
            if (instr & 0xF800) == 0xF000 and (next_instr & 0xF800) == 0xF800:
                off11hi = instr & 0x07FF
                off11lo = next_instr & 0x07FF
                full_off = (off11hi << 12) | (off11lo << 1)
                if full_off >= 0x400000:
                    full_off -= 0x800000
                bl_pc = ROM_BASE + pos + 4
                target = bl_pc + full_off
                bl_targets.append(target)
                pos += 4
                continue
        pos += 2
    return size, bl_targets


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    # =========================================================================
    # STEP 1: Find functions referencing ALL THREE confirmed variables
    # =========================================================================
    print("=" * 78)
    print("  STEP 1: Functions referencing gBattlerByTurnOrder + gChosenActionByBattler")
    print("          + gChosenMoveByBattler (= TryDoEventsBeforeFirstTurn candidates)")
    print("=" * 78)
    print()

    # Build function -> set of referenced addresses
    func_addrs = defaultdict(set)

    for name in ["gBattlerByTurnOrder", "gChosenActionByBattler", "gChosenMoveByBattler"]:
        addr = CONFIRMED[name]
        refs = find_all_refs(rom_data, addr)
        print(f"  {name} (0x{addr:08X}): {len(refs)} literal pool refs")
        for ref_off in refs:
            fs = find_function_start(rom_data, ref_off)
            if fs is not None:
                func_addrs[fs].add(name)

    print()

    # Functions that reference all 3
    all_three = [fs for fs, names in func_addrs.items()
                 if len(names) == 3]
    all_three.sort()

    print(f"  Functions referencing all 3: {len(all_three)}")
    print()

    for fs in all_three:
        func_rom = ROM_BASE + fs + 1
        ewram = get_ewram_addrs_in_function(rom_data, fs, 8192)
        size, bl_targets = analyze_function(rom_data, fs, 8192)

        # Look for addresses in 0x02023800-0x02023A18 range (where gBattleTurnCounter should be)
        tc_candidates = sorted(a for a in ewram if 0x02023800 <= a < 0x02023A18)

        print(f"  Function 0x{func_rom:08X} ({size or '?'} bytes, {len(bl_targets)} BLs)")
        print(f"    All EWRAM: {', '.join(f'0x{a:08X}' for a in sorted(ewram)[:30])}")
        if tc_candidates:
            print(f"    ** TC candidates (0x02023800-0x02023A18): {', '.join(f'0x{a:08X}' for a in tc_candidates)}")
        print()

    # =========================================================================
    # STEP 2: Also find functions with gBattlerByTurnOrder + gChosenActionByBattler
    #         (HandleTurnActionSelectionState also references both)
    # =========================================================================
    print("=" * 78)
    print("  STEP 2: Functions referencing gBattlerByTurnOrder + gChosenActionByBattler")
    print("=" * 78)
    print()

    two_of_three = [fs for fs, names in func_addrs.items()
                    if "gBattlerByTurnOrder" in names and "gChosenActionByBattler" in names]
    two_of_three.sort()

    print(f"  Functions referencing both: {len(two_of_three)}")
    print()

    # Collect all addresses that appear in these functions
    tc_tallies = defaultdict(int)
    for fs in two_of_three:
        ewram = get_ewram_addrs_in_function(rom_data, fs, 8192)
        for a in ewram:
            if 0x02023800 <= a < 0x02023A18:
                tc_tallies[a] += 1

    print("  Addresses in 0x02023800-0x02023A18 referenced by these functions:")
    for addr in sorted(tc_tallies.keys()):
        count = tc_tallies[addr]
        total_refs = len(find_all_refs(rom_data, addr))
        print(f"    0x{addr:08X}: in {count}/{len(two_of_three)} functions, {total_refs} total ROM refs")

    print()

    # =========================================================================
    # STEP 3: TryDoEventsBeforeFirstTurn pattern matching
    #         This function does: gBattleTurnCounter = 0;
    #         Which compiles to: LDR Rx, =gBattleTurnCounter; MOV Ry, #0; STRH Ry, [Rx]
    #         Find functions that do STR #0 to an address in range
    # =========================================================================
    print("=" * 78)
    print("  STEP 3: Pattern match — functions setting u16 to 0 near target vars")
    print("=" * 78)
    print()

    # TryDoEventsBeforeFirstTurn is a large function with a switch statement
    # (gBattleStruct->switchInBattlerCounter as state variable)
    # The gBattleTurnCounter=0 is in the first case (FIRST_TURN_EVENTS_END or similar)

    # For each of the "all three" functions, disassemble and look for:
    # LDR Rx, [PC, #nn] where pool value is a candidate,
    # followed within a few instructions by STRH or STR with value 0

    print("  Detailed analysis of functions referencing all 3 confirmed variables:")
    print()

    for fs in all_three:
        func_rom = ROM_BASE + fs + 1
        ewram = get_ewram_addrs_in_function(rom_data, fs, 8192)
        size, _ = analyze_function(rom_data, fs, 8192)

        # Get ALL LDR targets with their instruction positions
        pos = fs
        end_pos = min(fs + (size or 4096), len(rom_data) - 3)
        ldr_entries = []  # (instr_pos, pool_value)

        while pos < end_pos:
            instr = read_u16_le(rom_data, pos)
            if is_ldr_pc_relative(instr):
                pool_off = get_ldr_pool_offset(instr, ROM_BASE + pos)
                file_off = pool_off - ROM_BASE
                if 0 <= file_off < len(rom_data) - 3:
                    val = read_u32_le(rom_data, file_off)
                    if 0x02023800 <= val < 0x02023A18:
                        # Check the register (bits 10-8)
                        reg = (instr >> 8) & 7
                        ldr_entries.append((pos, val, reg))
            pos += 2

        if ldr_entries:
            print(f"  Function 0x{func_rom:08X} ({size or '?'} bytes):")
            for ipos, val, reg in ldr_entries:
                # Check next few instructions for MOV #0 + STRH/STR pattern
                context_instrs = []
                for ci in range(max(fs, ipos - 6), min(end_pos, ipos + 12), 2):
                    cinstr = read_u16_le(rom_data, ci)
                    context_instrs.append((ci, cinstr))

                # Decode context
                context_str = ""
                for ci, cinstr in context_instrs:
                    marker = " >>>" if ci == ipos else "    "
                    # Try to decode
                    if (cinstr & 0xF800) == 0x4800:
                        lr = (cinstr >> 8) & 7
                        context_str += f"\n{marker} 0x{ROM_BASE+ci:08X}: LDR R{lr}, [PC, #0x{(cinstr&0xFF)*4:X}]"
                    elif (cinstr & 0xFF00) == 0x2000:
                        rr = (cinstr >> 8) & 7
                        imm = cinstr & 0xFF
                        context_str += f"\n{marker} 0x{ROM_BASE+ci:08X}: MOV R{rr}, #0x{imm:X}"
                    elif (cinstr & 0xFE00) == 0x8000:
                        # STRH Rd, [Rb, #nn]
                        context_str += f"\n{marker} 0x{ROM_BASE+ci:08X}: STRH (store halfword)"
                    elif (cinstr & 0xFE00) == 0x6000:
                        context_str += f"\n{marker} 0x{ROM_BASE+ci:08X}: STR (store word)"
                    elif (cinstr & 0xFE00) == 0x7000:
                        context_str += f"\n{marker} 0x{ROM_BASE+ci:08X}: STRB (store byte)"
                    else:
                        context_str += f"\n{marker} 0x{ROM_BASE+ci:08X}: 0x{cinstr:04X}"

                print(f"    LDR R{reg}, =0x{val:08X} at 0x{ROM_BASE+ipos:08X}{context_str}")
                print()

    # =========================================================================
    # STEP 4: Direct approach — expected layout from gBattleCommunication
    # =========================================================================
    print("=" * 78)
    print("  STEP 4: Layout analysis from gBattleCommunication to gBattleTurnCounter")
    print("=" * 78)
    print()

    # From source (battle_main.c lines 200-236):
    # 200: gBattleCommunication[8]         = 0x0202370E (KNOWN, 8 bytes)
    # 201: gBattleOutcome (u8)
    # 202: gProtectStructs[4] (struct ProtectStruct, ~24-32 bytes each)
    # 203: gSpecialStatuses[4] (struct SpecialStatus, ~12-16 bytes each)
    # 204: gBattleWeather (u16)
    # 205: gWishFutureKnock (struct, ~60 bytes)
    # 206: gIntroSlideFlags (u16)
    # 207: gSentPokesToOpponent[2] (u8*2)
    # 208: gEnigmaBerries[4] (struct BattleEnigmaBerry, ~22 bytes each)
    # 209: gBattleScripting (struct BattleScripting, ~40 bytes)
    # 210: gBattleStruct (ptr, 4 bytes)
    # ... AI pointers ...
    # 221: gBattleResources (ptr) = 0x02023A18 (KNOWN)
    # 222-235: more small vars
    # 236: gBattleTurnCounter (u16)

    # Let's check key landmarks:
    # gBattleOutcome should be at 0x02023716 (gBattleCommunication + 8)
    gBattleOutcome_pred = 0x0202370E + 8  # 0x02023716
    refs_bo = find_all_refs(rom_data, gBattleOutcome_pred)
    print(f"  gBattleOutcome (predicted 0x{gBattleOutcome_pred:08X}): {len(refs_bo)} refs")

    # gBattleWeather should be a u16 with many refs
    # It's after gProtectStructs + gSpecialStatuses
    # Let's look for it in the Step 6 candidates that had high ref counts
    # 0x02023718 (119 refs) and 0x02023768 (172 refs) are strong candidates

    print(f"  Candidates after gBattleOutcome:")
    for addr, expected_name in [
        (0x02023718, "gProtectStructs?"),
        (0x02023768, "gSpecialStatuses? or gBattleWeather?"),
        (0x020237C8, "gWishFutureKnock? or gBattleScripting?"),
        (0x020237CC, "gBattleStruct?"),
        (0x02023958, "?"),
        (0x0202395A, "?"),
        (0x02023960, "gBattleTurnCounter candidate?"),
        (0x020239D0, "gBattleStruct or gBattleSpritesDataPtr?"),
        (0x02023A0C, "gBattleSpritesDataPtr or gBattleMovePower?"),
    ]:
        refs = find_all_refs(rom_data, addr)
        print(f"    0x{addr:08X}: {len(refs):4d} refs  ({expected_name})")

    print()

    # =========================================================================
    # STEP 5: Narrow down via BattleTurnPassed (increments gBattleTurnCounter)
    # =========================================================================
    print("=" * 78)
    print("  STEP 5: Find gBattleTurnCounter via BattleTurnPassed pattern")
    print("=" * 78)
    print()

    # BattleTurnPassed does: gBattleTurnCounter++
    # Which compiles to: LDR Rx, =gBattleTurnCounter; LDRH Ry, [Rx]; ADD Ry, #1; STRH Ry, [Rx]
    # This function also references gBattlerByTurnOrder, gChosenActionByBattler, gBattlersCount

    # From Step 7 data, addresses in both gBattlerByTurnOrder AND gChosenActionByBattler functions:
    # 0x0202394C (4), 0x02023960 (15), 0x020239D0 (52), 0x02023A0C (53)

    # 0x020239D0 (299 refs) is way too many for gBattleTurnCounter (a simple u16 counter)
    # 0x02023A0C (579 refs) is also too many
    # 0x02023960 (16 refs) is more reasonable for a turn counter
    # 0x0202394C (1 ref total) is too few

    # Let's check: 0x02023958 has 19 refs, 0x02023960 has 16 refs
    # In expansion, gBattleTurnCounter has ~30 usages in source

    # Check both candidates
    for candidate in [0x02023958, 0x0202395A, 0x02023960]:
        refs = find_all_refs(rom_data, candidate)
        print(f"  Candidate 0x{candidate:08X}: {len(refs)} refs")

        # For each ref, find the function and check if it also references our confirmed vars
        func_hits = defaultdict(set)
        for ref_off in refs:
            fs = find_function_start(rom_data, ref_off)
            if fs is None:
                continue
            func_ewram = get_ewram_addrs_in_function(rom_data, fs, 8192)
            for name, addr in CONFIRMED.items():
                if addr in func_ewram:
                    func_hits[fs].add(name)

        for fs in sorted(func_hits.keys()):
            names = func_hits[fs]
            func_rom = ROM_BASE + fs + 1
            size, bls = analyze_function(rom_data, fs, 8192)
            names_str = ", ".join(sorted(names))
            interesting = ""
            if "gBattlerByTurnOrder" in names and "gChosenActionByBattler" in names:
                interesting = " *** STRONG MATCH ***"
            elif "gBattlerByTurnOrder" in names:
                interesting = " * has gBattlerByTurnOrder"
            print(f"    In 0x{func_rom:08X} ({size or '?'}B, {len(bls)} BLs) also refs: {names_str}{interesting}")
        print()

    # =========================================================================
    # STEP 6: Alternative — check gBattleMovePower pattern
    # =========================================================================
    print("=" * 78)
    print("  STEP 6: Verify via adjacent variable pattern")
    print("=" * 78)
    print()

    # gBattleTurnCounter (line 236) is right after gFieldTimers (line 235)
    # and before gBattlerAbility (line 237)
    # gBattlerAbility should have moderate refs (~20-50)
    # gBattleMovePower (line 232) should also have moderate refs

    # gBattleTurnCounter is a u16. If it's at 0x02023960:
    # gBattlerAbility (u8) would be at 0x02023962
    refs_962 = find_all_refs(rom_data, 0x02023962)
    print(f"  If gBattleTurnCounter=0x02023960, gBattlerAbility(0x02023962): {len(refs_962)} refs")

    # If at 0x02023958:
    refs_95A = find_all_refs(rom_data, 0x0202395A)
    print(f"  If gBattleTurnCounter=0x02023958, gBattlerAbility(0x0202395A): {len(refs_95A)} refs")

    # gBattleMovePower (u16, line 232) should be a few bytes before gBattleTurnCounter
    # Between gBattleMovePower and gBattleTurnCounter:
    # line 232: gBattleMovePower (u16)
    # line 233: gMoveToLearn (u16)
    # line 234: gFieldStatuses (u32)
    # line 235: gFieldTimers (struct FieldTimer - check size)
    # line 236: gBattleTurnCounter

    print()
    print("  Check FieldTimer struct size...")

    # The answer depends on FieldTimer struct. Let me search for it.
    # In the expansion: struct FieldTimer has terrain, weather, trick_room, etc.
    # Typical size: 8-16 bytes. Let's check both scenarios.

    # If gBattleMovePower is at some address X, then:
    # X+2 = gMoveToLearn (u16)
    # X+4 = gFieldStatuses (u32)
    # X+8 = gFieldTimers (struct)
    # X+8+sizeof(FieldTimer) = gBattleTurnCounter

    # Let's search for gBattleMovePower - it's heavily used
    # Check addresses with ~30-100 refs just before 0x02023960
    print("  Scanning 0x02023940-0x02023970 for moderate-ref addresses:")
    for addr in range(0x02023940, 0x02023970, 2):
        count = len(find_all_refs(rom_data, addr))
        if count >= 2:
            print(f"    0x{addr:08X}: {count} refs")

    print()

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("=" * 78)
    print("  FINAL ASSESSMENT")
    print("=" * 78)
    print()

    print("  gBattlerByTurnOrder[4]    = 0x020233F6  (39 refs, CONFIRMED via layout)")
    print("  gChosenActionByBattler[4] = 0x02023598  (31 refs, CONFIRMED via layout)")
    print("  gChosenMoveByBattler[4]   = 0x020235FA  (22 refs, CONFIRMED via layout)")
    print()
    print("  gBattleTurnCounter candidates:")
    for addr in [0x02023958, 0x0202395A, 0x02023960]:
        count = len(find_all_refs(rom_data, addr))
        print(f"    0x{addr:08X}: {count} refs")
    print()
    print("  Best candidate: 0x02023958 or 0x02023960")
    print("  (Verify at runtime: value should be 0 at battle start, increment each turn)")


if __name__ == "__main__":
    main()
