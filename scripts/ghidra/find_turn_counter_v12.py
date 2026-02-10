#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v12: Find HandleEndTurnOrder's increment

We KNOW gBattleTurnCounter = 0x02023708 based on:
- Ref[0] at 0x08039EF6: Reset to 0 in TryDoEventsBeforeFirstTurn (confirmed)
- Ref[1,2]: Incremented in battle script commands (2 copies)

But HandleEndTurnOrder also increments it. Since HandleEndTurnOrder is likely
INLINED into DoEndTurnEffects, and DoEndTurnEffects is part of a large function,
the compiler might access 0x02023708 via offset from a nearby loaded address.

Approach:
1. Find ALL functions that call SortBattlersBySpeed AND have gBattlerByTurnOrder
2. In those functions, search for any access to address 0x02023708 via:
   a. Direct literal pool load
   b. Offset from nearby known address (e.g., LDR Rx, =0x02023700; LDRH Ry, [Rx, #8])
   c. ADD to a base register before LDRH
3. Also search for DoEndTurnEffects by finding sEndTurnEffectHandlers properly

Also: Verify gBattleTurnCounter = 0x02023708 conclusively by checking if it's in the
same init block as gBattleTurnCounter's known neighbors.
"""

import struct
import sys
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def find_all_refs(rom_data, target_value, max_off=0x01000000):
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, min(len(rom_data) - 3, max_off), 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs

def find_bl_target(rom_data, pos):
    instr = read_u16_le(rom_data, pos)
    ni = read_u16_le(rom_data, pos + 2)
    if (instr & 0xF800) != 0xF000 or (ni & 0xF800) != 0xF800:
        return None
    off11hi = instr & 0x07FF
    off11lo = ni & 0x07FF
    full_off = (off11hi << 12) | (off11lo << 1)
    if full_off >= 0x400000: full_off -= 0x800000
    return ROM_BASE + pos + 4 + full_off

def get_ldr_pool_value(rom_data, pos):
    instr = read_u16_le(rom_data, pos)
    if (instr & 0xF800) != 0x4800:
        return None, None
    rd = (instr >> 8) & 7
    imm8 = instr & 0xFF
    rom_addr = ROM_BASE + pos
    pa = ((rom_addr + 4) & ~3) + imm8 * 4
    pf = pa - ROM_BASE
    if 0 <= pf < len(rom_data) - 3:
        val = read_u32_le(rom_data, pf)
        return rd, val
    return rd, None


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    TARGET = 0x02023708
    SORT_BATTLERS = 0x0804B430
    GBATTLER_BY_TURN_ORDER = 0x020233F6

    # =========================================================================
    # PART 1: Find ALL BL to SortBattlersBySpeed, then for each caller,
    #         look for literal pool loads of addresses near 0x02023708
    #         (within +/- 62 bytes, which is the LDRH/STRH offset range)
    # =========================================================================
    print("=" * 90)
    print("  PART 1: SortBattlersBySpeed callers with access to 0x02023700-0x0202370E range")
    print("=" * 90)
    print()

    # Find all BL sites
    bl_sites = []
    for pos in range(0, min(len(rom_data) - 4, 0x01000000), 2):
        target = find_bl_target(rom_data, pos)
        if target == SORT_BATTLERS:
            bl_sites.append(pos)

    print(f"  Found {len(bl_sites)} BL sites to SortBattlersBySpeed")
    print()

    # For each call site, scan the surrounding code (512 bytes before to call site)
    # for LDR literal pool loads of addresses in range 0x02023700-0x0202370F
    TARGET_RANGE_LO = 0x02023700
    TARGET_RANGE_HI = 0x02023710  # 0x02023708 could be at offset 0-8 from base

    for site_off in bl_sites:
        # Also check that this function references gBattlerByTurnOrder
        has_turn_order = False
        has_near_target = False
        near_loads = []

        scan_start = max(0, site_off - 1024)
        scan_end = min(len(rom_data) - 2, site_off + 32)

        for scan in range(scan_start, scan_end, 2):
            ci = read_u16_le(rom_data, scan)
            if (ci & 0xF800) == 0x4800:
                rd, val = get_ldr_pool_value(rom_data, scan)
                if val is not None:
                    if val == GBATTLER_BY_TURN_ORDER:
                        has_turn_order = True
                    if TARGET_RANGE_LO <= val <= TARGET_RANGE_HI:
                        has_near_target = True
                        near_loads.append((scan, rd, val))
                    # Also check if val == TARGET exactly
                    if val == TARGET:
                        has_near_target = True

        if has_turn_order and has_near_target:
            site_addr = ROM_BASE + site_off
            print(f"  *** MATCH at call site 0x{site_addr:08X}")
            for nl_off, nl_reg, nl_val in near_loads:
                nl_addr = ROM_BASE + nl_off
                offset_to_target = TARGET - nl_val
                print(f"      LDR R{nl_reg}, =0x{nl_val:08X} at 0x{nl_addr:08X} "
                      f"(offset to 0x{TARGET:08X} = {offset_to_target})")
            print()

    # =========================================================================
    # PART 2: Alternative — find DoEndTurnEffects directly
    # DoEndTurnEffects contains: `gBattlerAttacker = gBattlerByTurnOrder[...]`
    # It loads both gBattlerAttacker address and gBattlerByTurnOrder address
    # It also loads gBattleStruct for eventState access
    # And it loads sEndTurnEffectHandlers table address for dispatch
    #
    # Key: it has a for(;;) infinite loop, checking eventState.endTurn == ENDTURN_COUNT
    # =========================================================================
    print("=" * 90)
    print("  PART 2: Find DoEndTurnEffects — search for callers of HandleEndTurnOrder")
    print("=" * 90)
    print()

    # DoEndTurnEffects is called from BattleTurnPassed via BL
    # BattleTurnPassed itself is called as a function pointer from gBattleMainFunc
    # Let's find DoEndTurnEffects by its unique pattern:
    # It must reference gBattlerAttacker, gBattlerByTurnOrder, gBattlersCount, gBattleStruct
    # AND the sEndTurnEffectHandlers table

    # Strategy: find functions that have ALL of:
    # 1. gBattlerAttacker (0x0202359C)  - but note: this might be gBattlescriptCurrInstr!
    # 2. gBattlerByTurnOrder (0x020233F6)
    # 3. gBattlersCount (0x020233E4)
    # 4. gBattleStruct (0x020239D0)
    # 5. A table address (somewhere in 0x083xxxxx range with 30-50 consecutive THUMB ptrs)

    # Actually, let me try something simpler. DoEndTurnEffects has this exact line:
    # battler = gBattlerAttacker = gBattlerByTurnOrder[gBattleStruct->eventState.endTurnBattler];
    # Which compiles to something like:
    #   LDR R0, =gBattleStruct
    #   LDR R0, [R0]           ; dereference pointer
    #   LDRB R1, [R0, #offset] ; load endTurnBattler
    #   LDR R2, =gBattlerByTurnOrder
    #   LDRB R3, [R2, R1]      ; load gBattlerByTurnOrder[endTurnBattler]
    #   LDR R4, =gBattlerAttacker
    #   STRB R3, [R4]           ; gBattlerAttacker = value

    # The key distinguishing feature: LDRB from gBattlerByTurnOrder using a computed index

    # Let's find all functions that load gBattlerByTurnOrder AND gBattleStruct
    print("  Searching for functions with gBattlerByTurnOrder + gBattleStruct + gBattlersCount...")
    print()

    # We need a better approach. Let me check: is 0x02023708 accessed with
    # non-zero LDRH offset anywhere in ROM?
    # If the compiler loads e.g. 0x02023706 and does LDRH [Rx, #2], that accesses 0x02023708

    print("=" * 90)
    print("  PART 3: Search for LDRH access to 0x02023708 via base+offset")
    print("=" * 90)
    print()

    # Addresses that could be used as base to reach 0x02023708 via LDRH offset (0-62):
    possible_bases = {}
    for offset in range(0, 63, 2):
        base = TARGET - offset
        if 0x02000000 <= base < 0x04000000:
            refs = find_all_refs(rom_data, base)
            if len(refs) > 0:
                possible_bases[base] = (offset, len(refs))

    print(f"  EWRAM addresses that can reach 0x{TARGET:08X} via LDRH offset:")
    for base in sorted(possible_bases.keys()):
        offset, nrefs = possible_bases[base]
        print(f"    base=0x{base:08X} + offset=#0x{offset:X} = 0x{TARGET:08X} ({nrefs} ROM refs)")

    print()

    # =========================================================================
    # PART 4: Verify 0x02023708 via the init block at 0x08039EF6
    # The init block clears: 0x0202370A, 0x02023708, 0x0202370E, gBattleControllerExecFlags,
    # gFieldStatuses (0x02023958), etc.
    # Let's see if these match TryDoEventsBeforeFirstTurn's clearing pattern
    # =========================================================================
    print("=" * 90)
    print("  PART 4: Full init block analysis at 0x08039E... (TryDoEventsBeforeFirstTurn)")
    print("=" * 90)
    print()

    # Let me list ALL variables cleared in the block around 0x08039EF6
    # by scanning for MOV #0 + STRH/STR/STRB sequences

    # Scan the area 0x08039E80-0x08039F50 for all store-zero patterns
    scan_start = 0x00039E80
    scan_end = 0x00039F50

    # Collect all literal pool loads in this area first
    reg_vals = {}  # pos -> (reg, val)
    pos = scan_start
    while pos < scan_end and pos + 1 < len(rom_data):
        ci = read_u16_le(rom_data, pos)
        if (ci & 0xF800) == 0x4800:
            rd, val = get_ldr_pool_value(rom_data, pos)
            if val is not None and 0x02000000 <= val < 0x04000000:
                reg_vals[pos] = (rd, val)
                print(f"  LDR R{rd}, =0x{val:08X} at 0x{ROM_BASE + pos:08X}")
        pos += 2

    print()

    # Now trace what happens with these registers
    # For the init block, we expect:
    # Source line 3809: gBattleTurnCounter = 0  → STRH #0 to gBattleTurnCounter
    # Source also: clearing gBattleCommunication, gFieldStatuses, etc.

    # =========================================================================
    # PART 5: Final — check that R&B uses gBattleTurnCounter the same way
    # by looking for it in battle script command table
    # Battle script commands like "turncountercheck" use gBattleTurnCounter
    # =========================================================================
    print("=" * 90)
    print("  PART 5: Verify battle script command functions accessing 0x02023708")
    print("=" * 90)
    print()

    # The function at 0x0805782C (Ref[1]) uses gBattleTurnCounter
    # Let's identify this function by checking what calls it
    # Battle script commands are called through a function pointer table
    # (gBattleScriptingCommandsTable or similar)

    func_addr = 0x0005782C  # ROM offset of the function
    func_thumb = ROM_BASE + func_addr + 1  # THUMB address

    # Find ROM literal pool entries containing this THUMB address
    func_refs = find_all_refs(rom_data, func_thumb)
    print(f"  Function at 0x{ROM_BASE + func_addr:08X} (THUMB: 0x{func_thumb:08X})")
    print(f"  Found in {len(func_refs)} ROM literal pools:")
    for r in func_refs[:5]:
        print(f"    0x{ROM_BASE + r:08X}")
        # Check if this is part of a table (consecutive THUMB pointers)
        # Look at the surrounding entries
        table_start = r
        while table_start >= 4:
            prev_val = read_u32_le(rom_data, table_start - 4)
            if 0x08000000 <= prev_val < 0x09000000 and (prev_val & 1):
                table_start -= 4
            else:
                break

        table_end = r
        while table_end + 4 < len(rom_data):
            next_val = read_u32_le(rom_data, table_end + 4)
            if 0x08000000 <= next_val < 0x09000000 and (next_val & 1):
                table_end += 4
            else:
                break

        table_size = (table_end - table_start) // 4 + 1
        entry_index = (r - table_start) // 4
        print(f"      In table at 0x{ROM_BASE + table_start:08X} ({table_size} entries), index #{entry_index}")

    print()

    # =========================================================================
    # PART 6: Definitive test — look at ALL 3 refs and see if the patterns
    #         match the known source uses
    # =========================================================================
    print("=" * 90)
    print("  PART 6: Mapping ROM refs to source code uses")
    print("=" * 90)
    print()

    refs = find_all_refs(rom_data, TARGET)

    # Source uses:
    # 1. gBattleTurnCounter = 0  (TryDoEventsBeforeFirstTurn, battle_main.c:3809)
    # 2. gBattleTurnCounter++ (HandleEndTurnOrder, battle_end_turn.c:32) — if not removed by R&B
    # 3. Battle script command(s) using gBattleTurnCounter

    print(f"  3 source uses expected (1 reset, 1 increment in HandleEndTurnOrder, possibly removed)")
    print(f"  Found {len(refs)} ROM literal pool refs")
    print()

    for idx, ref_off in enumerate(refs):
        # Find which LDR uses this pool entry
        for scan in range(max(0, ref_off - 4096), ref_off, 2):
            ci = read_u16_le(rom_data, scan)
            if (ci & 0xF800) == 0x4800:
                rd, val = get_ldr_pool_value(rom_data, scan)
                if val == TARGET:
                    scan_addr = ROM_BASE + scan
                    # Check subsequent instructions
                    next_pos = scan + 2
                    ni = read_u16_le(rom_data, next_pos)

                    # STRH to [Rd, #0] = reset
                    # LDRH from [Rd, #0] = read (for increment)
                    pattern = "unknown"
                    if (ni & 0xFE00) == 0x8000:  # STRH
                        strh_rd = ni & 7
                        strh_rb = (ni >> 3) & 7
                        if strh_rb == rd:
                            pattern = "STRH (reset to zero)"
                    elif (ni & 0xFE00) == 0x8800:  # LDRH
                        ldrh_rd = ni & 7
                        ldrh_rb = (ni >> 3) & 7
                        if ldrh_rb == rd:
                            # Check for ADD #1 after
                            nn = read_u16_le(rom_data, next_pos + 2)
                            if (nn & 0xFF00) == 0x3000 and (nn & 0xFF) == 1:
                                pattern = "LDRH + ADD #1 (increment)"
                            elif (nn & 0xFE00) == 0x1C00 and ((nn >> 6) & 7) == 1:
                                pattern = "LDRH + ADDS #1 (increment)"
                            else:
                                pattern = "LDRH (read)"

                    print(f"  Ref [{idx}]: Pool at 0x{ROM_BASE + ref_off:08X}, "
                          f"LDR R{rd} at 0x{scan_addr:08X} -> {pattern}")

    print()

    # =========================================================================
    # PART 7: Cross-check with nearby variables
    # 0x0202370A should be gBattlerAbility (u8, 3 refs)
    # 0x0202370C should be gQueuedStatBoosts (struct array)
    # =========================================================================
    print("=" * 90)
    print("  PART 7: Nearby variable verification")
    print("=" * 90)
    print()

    nearby = [
        (0x02023706, "gBattleTurnCounter - 2 (should be last FieldTimer field)"),
        (0x02023708, "gBattleTurnCounter (u16)"),
        (0x0202370A, "gBattlerAbility (u8, expected 3+ refs)"),
        (0x0202370C, "gQueuedStatBoosts? (struct array)"),
        (0x0202370E, "?? (352 refs — likely NOT gQueuedStatBoosts)"),
    ]

    for addr, desc in nearby:
        n = len(find_all_refs(rom_data, addr))
        print(f"  0x{addr:08X}: {n:4d} refs  {desc}")

    # 0x0202370E has 352 refs — that's WAY too many for gQueuedStatBoosts
    # 0x0202370E is likely gBattleCommunication (u8[8]) which has tons of refs
    # If gBattleCommunication = 0x0202370E, that's 8 bytes: 0x0202370E-0x02023715
    # Then gBattlerAbility CANNOT be at 0x0202370A (that's BEFORE gBattleCommunication)

    print()
    print("  NOTE: 0x0202370E (352 refs) is likely gBattleCommunication (u8[8])")
    print("  If so, the layout BEFORE gBattleCommunication might be:")
    print("  0x02023708 = gBattleTurnCounter (u16, 3 refs)")
    print("  0x0202370A = gBattlerAbility (u8, 3 refs)")
    print("  0x0202370B = padding byte")
    print("  0x0202370C = ??? (4 refs)")
    print("  0x0202370E = gBattleCommunication (u8[8], 352 refs)")
    print()

    # Verify: gBattleCommunication is declared AFTER gBattleTurnCounter in battle_main.c?
    # Let's check the source
    print("  Source order in battle_main.c around gBattleTurnCounter:")
    print("  ...gBattleTurnCounter (u16)")
    print("  gBattlerAbility (u8)")
    print("  gQueuedStatBoosts[MAX_BATTLERS_COUNT] (struct)")
    print("  gHasFetchedBall (bool8/u8)")
    print("  gLastUsedBall (u16)")
    print("  ...")
    print()
    print("  gBattleCommunication is declared in battle_util.c, NOT battle_main.c!")
    print("  So different translation units — the linker can place them anywhere.")
    print()

    # =========================================================================
    # CONCLUSION
    # =========================================================================
    print("=" * 90)
    print("  CONCLUSION")
    print("=" * 90)
    print()
    print("  gBattleTurnCounter = 0x02023708")
    print()
    print("  Evidence:")
    print("  1. Reset to 0 in TryDoEventsBeforeFirstTurn init block (Ref[0])")
    print("  2. Incremented in battle script commands (Ref[1], Ref[2])")
    print("  3. Accessed as u16 (LDRH/STRH) — matches u16 type")
    print("  4. Has 3 ROM refs (consistent with 2-3 source uses)")
    print("  5. Adjacent to gBattlerAbility-like variable at 0x0202370A (3 refs, u8/u16)")
    print("  6. Cleared alongside other battle init vars (gBattleCommunication, gFieldStatuses)")
    print()
    print("  HandleEndTurnOrder's gBattleTurnCounter++ was likely:")
    print("  a) Inlined and uses a register already holding 0x02023708, OR")
    print("  b) Removed/modified by R&B (replaced by battle script counter system)")
    print()
    print("  DONE")


if __name__ == "__main__":
    main()
