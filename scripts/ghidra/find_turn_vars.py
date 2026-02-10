#!/usr/bin/env python3
"""
ROM Literal Pool Scanner — Find turn-order battle variables in Pokemon Run & Bun

Target variables (all EWRAM_DATA in pokeemerald-expansion/src/battle_main.c):
  1. gBattlerByTurnOrder     — u8[4]  (line 159, after gActionsByTurnOrder[4])
  2. gChosenActionByBattler  — u8[4]  (line 180, after gBattlescriptCurrInstr)
  3. gChosenMoveByBattler    — u16[4] (line 192, after gLastHitBy[4])
  4. gBattleTurnCounter      — u16    (line 236, after gFieldTimers)

Strategy:
  - These variables are in the EWRAM BSS section, near other known battle vars.
  - The compiler lays out EWRAM_DATA in declaration order within each translation unit.
  - We know several anchors in the same file (gBattleTypeFlags, gBattleControllerExecFlags,
    gActiveBattler, gBattlersCount, gBattlerPositions, gBattleMons, gBattleCommunication).
  - Scan ROM literal pools for EWRAM addresses co-located with these anchors.
  - Use source declaration order + type sizes to predict relative positions.

Known anchors (VERIFIED in R&B):
  gBattleTypeFlags          = 0x02023364 (line 148)
  gBattleControllerExecFlags = 0x020233E0 (line 154)
  gActiveBattler            = 0x020233DC (line ??)  -- NOTE: layout is SWAPPED vs vanilla
  gBattlersCount            = 0x020233E4 (line 155)
  gBattlerPositions         = 0x020233EE (line 157)
  gBattleMons               = 0x020233FC (line 162)
  gBattleCommunication      = 0x0202370E (line 200)
  gBattleResources          = 0x02023A18 (line 221)

No Ghidra needed -- just reads the .gba file.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# ============================================================================
# Known anchors — VERIFIED R&B addresses
# ============================================================================
KNOWN = {
    # Battle state (from config/run_and_bun.lua, verified)
    "gBattleTypeFlags":          0x02023364,
    "gBattleControllerExecFlags": 0x020233E0,
    "gActiveBattler":            0x020233DC,
    "gBattlersCount":            0x020233E4,
    "gBattlerPositions":         0x020233EE,  # u8[4]
    "gBattleMons":               0x020233FC,  # struct BattlePokemon[4], ~0x5C per entry
    "gBattleCommunication":      0x0202370E,  # u8[8]
    "gBattleResources":          0x02023A18,

    # Party
    "gPlayerParty":              0x02023A98,
    "gEnemyParty":               0x02023CF0,

    # Other known battle EWRAM
    "gLinkPlayers":              0x020229E8,
    "gBlockRecvBuffer":          0x020226C4,
}

# Source-order layout from battle_main.c (lines 132-246)
# Each entry: (name, type, size_bytes, line_number)
# size = actual memory footprint including alignment
SOURCE_ORDER = [
    # --- Lines 132-143: BG vars (u16 each = 2 bytes, 12 of them = 24 bytes)
    ("gBattle_BG0_X",               "u16",   2,  132),
    ("gBattle_BG0_Y",               "u16",   2,  133),
    ("gBattle_BG1_X",               "u16",   2,  134),
    ("gBattle_BG1_Y",               "u16",   2,  135),
    ("gBattle_BG2_X",               "u16",   2,  136),
    ("gBattle_BG2_Y",               "u16",   2,  137),
    ("gBattle_BG3_X",               "u16",   2,  138),
    ("gBattle_BG3_Y",               "u16",   2,  139),
    ("gBattle_WIN0H",               "u16",   2,  140),
    ("gBattle_WIN0V",               "u16",   2,  141),
    ("gBattle_WIN1H",               "u16",   2,  142),
    ("gBattle_WIN1V",               "u16",   2,  143),
    # line 144: gDisplayedStringBattle[425] => 425 bytes, aligned to 4 => 428
    ("gDisplayedStringBattle",      "u8[425]", 425, 144),
    # line 145: gBattleTextBuff1[18] (TEXT_BUFF_ARRAY_COUNT = max(16, max(18, max(13, 17))) = 18)
    ("gBattleTextBuff1",            "u8[18]",  18,  145),
    # line 146: gBattleTextBuff2[18]
    ("gBattleTextBuff2",            "u8[18]",  18,  146),
    # line 147: gBattleTextBuff3[31] (18+13)
    ("gBattleTextBuff3",            "u8[31]",  31,  147),
    # line 148: gBattleTypeFlags (u32, 4 bytes) -- ANCHOR
    ("gBattleTypeFlags",            "u32",   4,  148),
    # line 149: gBattleEnvironment (u8, 1 byte)
    ("gBattleEnvironment",          "u8",    1,  149),
    # line 150: gMultiPartnerParty[3] -- struct is 3*sizeof(MultiPartnerMenuPokemon)
    #   MultiPartnerMenuPokemon = { species(u16), heldItem(u16), moves[4](u16*4), level(u8), EVs[6](u8*6), IVs(u32), OT_ID(u32), personality(u32), abilityNum(u8), gender(u8), nickname[12+1](u8*13) }
    #   rough size ~56 bytes per entry, 3 entries = 168 bytes (estimate)
    ("gMultiPartnerParty",          "struct[3]", 168, 150),
    # line 151: sMultiPartnerPartyBuffer (ptr, 4 bytes)
    ("sMultiPartnerPartyBuffer",    "ptr",   4,  151),
    # line 152: gBattleAnimBgTileBuffer (ptr, 4 bytes)
    ("gBattleAnimBgTileBuffer",     "ptr",   4,  152),
    # line 153: gBattleAnimBgTilemapBuffer (ptr, 4 bytes)
    ("gBattleAnimBgTilemapBuffer",  "ptr",   4,  153),
    # line 154: gBattleControllerExecFlags (u32, 4 bytes) -- ANCHOR
    ("gBattleControllerExecFlags",  "u32",   4,  154),
    # line 155: gBattlersCount (u8, 1 byte) -- ANCHOR
    ("gBattlersCount",              "u8",    1,  155),
    # line 156: gBattlerPartyIndexes[4] (u16*4 = 8 bytes)
    ("gBattlerPartyIndexes",        "u16[4]", 8, 156),
    # line 157: gBattlerPositions[4] (u8*4 = 4 bytes) -- ANCHOR
    ("gBattlerPositions",           "u8[4]", 4,  157),
    # line 158: gActionsByTurnOrder[4] (u8*4 = 4 bytes)
    ("gActionsByTurnOrder",         "u8[4]", 4,  158),
    # line 159: *** TARGET 1 *** gBattlerByTurnOrder[4] (u8*4 = 4 bytes)
    ("gBattlerByTurnOrder",         "u8[4]", 4,  159),
    # line 160: gCurrentTurnActionNumber (u8, 1 byte)
    ("gCurrentTurnActionNumber",    "u8",    1,  160),
    # line 161: gCurrentActionFuncId (u8, 1 byte)
    ("gCurrentActionFuncId",        "u8",    1,  161),
    # line 162: gBattleMons[4] (struct BattlePokemon * 4) -- ANCHOR
    #   BattlePokemon: offset 0x00 to 0x62+1 = 0x63 bytes, but expansion has Volatiles at 0x51..0x5C
    #   The R&B confirmed size is 0x5C per entry (from gBattleMons config, fits 4 entries between 0x020233FC and gBattleCommunication area)
    ("gBattleMons",                 "struct[4]", 0x170, 162),  # 4 * 0x5C = 0x170
    # line 163: gBattlerSpriteIds[4] (u8*4 = 4 bytes)
    ("gBattlerSpriteIds",           "u8[4]", 4,  163),
    # line 164: gCurrMovePos (u8, 1)
    ("gCurrMovePos",                "u8",    1,  164),
    # line 165: gChosenMovePos (u8, 1)
    ("gChosenMovePos",              "u8",    1,  165),
    # line 166: gCurrentMove (u16, 2)
    ("gCurrentMove",                "u16",   2,  166),
    # line 167: gChosenMove (u16, 2)
    ("gChosenMove",                 "u16",   2,  167),
    # line 168: gCalledMove (u16, 2)
    ("gCalledMove",                 "u16",   2,  168),
    # line 169: gBideDmg[4] (s32*4 = 16 bytes)
    ("gBideDmg",                    "s32[4]", 16, 169),
    # line 170: gLastUsedItem (u16, 2)
    ("gLastUsedItem",               "u16",   2,  170),
    # line 171: gLastUsedAbility (enum = u16 in expansion, 2 bytes)
    ("gLastUsedAbility",            "u16",   2,  171),
    # line 172: gBattlerAttacker (u8, 1)
    ("gBattlerAttacker",            "u8",    1,  172),
    # line 173: gBattlerTarget (u8, 1)
    ("gBattlerTarget",              "u8",    1,  173),
    # line 174: gBattlerFainted (u8, 1)
    ("gBattlerFainted",             "u8",    1,  174),
    # line 175: gEffectBattler (u8, 1)
    ("gEffectBattler",              "u8",    1,  175),
    # line 176: gPotentialItemEffectBattler (u8, 1)
    ("gPotentialItemEffectBattler", "u8",    1,  176),
    # line 177: gAbsentBattlerFlags (u8, 1)
    ("gAbsentBattlerFlags",         "u8",    1,  177),
    # line 178: gMultiHitCounter (u8, 1)
    ("gMultiHitCounter",            "u8",    1,  178),
    # line 179: gBattlescriptCurrInstr (ptr, 4)
    ("gBattlescriptCurrInstr",      "ptr",   4,  179),
    # line 180: *** TARGET 2 *** gChosenActionByBattler[4] (u8*4 = 4 bytes)
    ("gChosenActionByBattler",      "u8[4]", 4,  180),
    # line 181: gSelectionBattleScripts[4] (ptr*4 = 16)
    ("gSelectionBattleScripts",     "ptr[4]", 16, 181),
    # line 182: gPalaceSelectionBattleScripts[4] (ptr*4 = 16)
    ("gPalaceSelectionBattleScripts", "ptr[4]", 16, 182),
    # line 183: gLastPrintedMoves[4] (u16*4 = 8)
    ("gLastPrintedMoves",           "u16[4]", 8, 183),
    # line 184: gLastMoves[4] (u16*4 = 8)
    ("gLastMoves",                  "u16[4]", 8, 184),
    # line 185: gLastLandedMoves[4] (u16*4 = 8)
    ("gLastLandedMoves",            "u16[4]", 8, 185),
    # line 186: gLastHitByType[4] (u16*4 = 8)
    ("gLastHitByType",              "u16[4]", 8, 186),
    # line 187: gLastUsedMoveType[4] (u16*4 = 8)
    ("gLastUsedMoveType",           "u16[4]", 8, 187),
    # line 188: gLastResultingMoves[4] (u16*4 = 8)
    ("gLastResultingMoves",         "u16[4]", 8, 188),
    # line 189: gLockedMoves[4] (u16*4 = 8)
    ("gLockedMoves",                "u16[4]", 8, 189),
    # line 190: gLastUsedMove (u16, 2)
    ("gLastUsedMove",               "u16",   2,  190),
    # line 191: gLastHitBy[4] (u8*4 = 4)
    ("gLastHitBy",                  "u8[4]", 4,  191),
    # line 192: *** TARGET 3 *** gChosenMoveByBattler[4] (u16*4 = 8 bytes)
    ("gChosenMoveByBattler",        "u16[4]", 8, 192),
    # line 193: gHitMarker (u32, 4)
    ("gHitMarker",                  "u32",   4,  193),
    # line 194: gBideTarget[4] (u8*4 = 4)
    ("gBideTarget",                 "u8[4]", 4,  194),
    # line 195: gSideStatuses[2] (u32*2 = 8)
    ("gSideStatuses",               "u32[2]", 8, 195),
    # line 196: gSideTimers[2] (struct, varies)
    # SideTimer: (futureSight[4]*u16=8, futureSightBI[4]*u8=4, futureSightPI[4]*u8=4,
    #   futureSightMove[4]*u16=8, wish[4]*u16=8, wishPI[4]*u8=4, knockedOff[2]*u8=2, ...)
    #   ~60 bytes per side * 2 = 120 (rough estimate, depends on R&B modifications)
    ("gSideTimers",                 "struct[2]", 120, 196),
    # line 197: gDisableStructs[4] (struct, ~40 bytes per entry * 4 = 160)
    ("gDisableStructs",             "struct[4]", 160, 197),
    # line 198: gPauseCounterBattle (u16, 2)
    ("gPauseCounterBattle",         "u16",   2,  198),
    # line 199: gPaydayMoney (u16, 2)
    ("gPaydayMoney",                "u16",   2,  199),
    # line 200: gBattleCommunication[8] (u8*8 = 8 bytes) -- ANCHOR
    ("gBattleCommunication",        "u8[8]", 8,  200),
    # line 201: gBattleOutcome (u8, 1)
    ("gBattleOutcome",              "u8",    1,  201),
    # ... continues through line 236
    # line 236: *** TARGET 4 *** gBattleTurnCounter (u16, 2 bytes)
    ("gBattleTurnCounter",          "u16",   2,  236),
]

TARGETS = {
    "gBattlerByTurnOrder",
    "gChosenActionByBattler",
    "gChosenMoveByBattler",
    "gBattleTurnCounter",
}


def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def find_all_refs(rom_data, target_value):
    """Find all 4-byte aligned positions where target_value appears as a literal."""
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs

def find_function_start(rom_data, offset):
    """Walk backward from offset to find PUSH {LR} or PUSH {Rx, LR}."""
    for back in range(2, 2048, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in (0xB400, 0xB500):
            return pos
    return None

def is_ldr_pc_relative(instr):
    """Check if instruction is LDR Rx, [PC, #imm8*4]."""
    return (instr & 0xF800) == 0x4800

def get_ldr_pool_offset(instr, pc):
    """For LDR Rx, [PC, #imm], compute the literal pool address."""
    if not is_ldr_pc_relative(instr):
        return None
    imm8 = instr & 0xFF
    # PC is instruction address + 4, then aligned down to 4
    pool_addr = ((pc + 4) & ~3) + imm8 * 4
    return pool_addr

def scan_function_ldr_targets(rom_data, func_start, max_size=2048):
    """Scan a function starting at func_start and collect all LDR literal pool targets.
    Returns list of (rom_file_offset, loaded_value)."""
    results = []
    end = min(func_start + max_size, len(rom_data) - 3)
    pos = func_start
    found_pop = False
    while pos < end:
        instr = read_u16_le(rom_data, pos)
        # Track function end
        if pos > func_start + 4:
            if (instr & 0xFF00) == 0xBD00:  # POP {PC}
                found_pop = True
            # Continue a bit past POP to pick up literal pool
            if found_pop and (pos - func_start > max_size // 2):
                break
        if is_ldr_pc_relative(instr):
            pool_off = get_ldr_pool_offset(instr, ROM_BASE + pos)
            file_off = pool_off - ROM_BASE
            if 0 <= file_off < len(rom_data) - 3:
                val = read_u32_le(rom_data, file_off)
                results.append((file_off, val))
        pos += 2
    return results

def get_ewram_addrs_in_function(rom_data, func_start, max_size=2048):
    """Get all EWRAM addresses loaded via LDR in a function."""
    targets = scan_function_ldr_targets(rom_data, func_start, max_size)
    ewram = []
    for file_off, val in targets:
        if 0x02000000 <= val < 0x02040000:
            ewram.append(val)
    return sorted(set(ewram))


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print()

    # =========================================================================
    # STEP 1: Compute expected layout from source order
    # =========================================================================
    print("=" * 78)
    print("  STEP 1: Expected EWRAM layout (source declaration order)")
    print("=" * 78)
    print()

    # We know gBattleTypeFlags = 0x02023364 at line 148.
    # Walk forward from there using source order and type sizes.
    # NOTE: The compiler aligns vars to their natural alignment:
    #   u8 = 1-byte aligned, u16 = 2-byte aligned, u32/ptr = 4-byte aligned
    # Actual R&B layout may differ due to different struct sizes or compiler flags.

    anchor_name = "gBattleTypeFlags"
    anchor_addr = KNOWN[anchor_name]
    anchor_line = 148

    # Find anchor in source order
    anchor_idx = None
    for i, (name, _, _, line) in enumerate(SOURCE_ORDER):
        if name == anchor_name:
            anchor_idx = i
            break

    if anchor_idx is None:
        print("ERROR: anchor not found in SOURCE_ORDER")
        sys.exit(1)

    # Compute addresses forward from anchor
    def align_up(addr, alignment):
        return (addr + alignment - 1) & ~(alignment - 1)

    def get_alignment(type_str):
        if type_str.startswith("u32") or type_str.startswith("s32") or type_str.startswith("ptr"):
            return 4
        elif type_str.startswith("u16") or type_str.startswith("s16"):
            return 2
        elif type_str.startswith("struct"):
            return 4  # structs are typically 4-aligned
        return 1

    expected = {}
    current_addr = anchor_addr
    for i in range(anchor_idx, len(SOURCE_ORDER)):
        name, type_str, size, line = SOURCE_ORDER[i]
        alignment = get_alignment(type_str)
        current_addr = align_up(current_addr, alignment)
        expected[name] = current_addr
        if name in TARGETS or name in KNOWN:
            marker = " *** TARGET ***" if name in TARGETS else " (KNOWN)"
            known_real = KNOWN.get(name)
            if known_real:
                delta = known_real - current_addr
                marker += f"  actual=0x{known_real:08X} delta={delta:+d}"
            print(f"  0x{current_addr:08X}  {name:40s}  [{type_str:12s} {size:4d}B]{marker}")
        current_addr += size

    print()
    print("  NOTE: Expected layout assumes vanilla alignment and struct sizes.")
    print("  R&B may have different struct sizes. Use ROM literal pool scan to confirm.")
    print()

    # =========================================================================
    # STEP 2: Scan ALL EWRAM literal pool refs in battle address range
    # =========================================================================
    print("=" * 78)
    print("  STEP 2: ALL EWRAM addresses in ROM literal pools (0x02023300-0x02023C00)")
    print("=" * 78)
    print()

    # Scan full ROM for EWRAM addresses in the battle var range
    ewram_refs = defaultdict(int)
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if 0x02023300 <= val < 0x02023C00:
            ewram_refs[val] += 1

    sorted_refs = sorted(ewram_refs.items(), key=lambda x: x[0])
    print(f"  {len(sorted_refs)} unique EWRAM addresses in range 0x02023300-0x02023C00")
    print()

    for addr, count in sorted_refs:
        known_name = ""
        for n, a in KNOWN.items():
            if a == addr:
                known_name = f" <-- {n}"
                break
        expected_name = ""
        for n, a in expected.items():
            if a == addr and n not in KNOWN:
                expected_name = f" (expected: {n})"
                break
        target_mark = ""
        for n, a in expected.items():
            if a == addr and n in TARGETS:
                target_mark = " *** MATCH ***"
                break
        print(f"    0x{addr:08X}  ({count:4d} refs){known_name}{expected_name}{target_mark}")

    print()

    # =========================================================================
    # STEP 3: Find functions referencing nearby known anchors and extract
    #         ALL EWRAM addresses they load — these reveal the target vars
    # =========================================================================
    print("=" * 78)
    print("  STEP 3: Co-located EWRAM addresses in functions with known anchors")
    print("=" * 78)
    print()

    # For each known anchor, find functions that reference it,
    # then extract all EWRAM addresses those functions also reference
    colocated = defaultdict(set)  # ewram_addr -> set of anchor names

    for anchor_name, anchor_addr in KNOWN.items():
        if not (0x02023000 <= anchor_addr < 0x02024000):
            continue  # Only battle-range anchors

        refs = find_all_refs(rom_data, anchor_addr)
        for ref_off in refs:
            func_start = find_function_start(rom_data, ref_off)
            if func_start is None:
                continue
            func_ewram = get_ewram_addrs_in_function(rom_data, func_start, 4096)
            for ea in func_ewram:
                if 0x02023300 <= ea < 0x02023C00:
                    colocated[ea].add(anchor_name)

    # Sort by address
    sorted_coloc = sorted(colocated.items(), key=lambda x: x[0])
    print(f"  {len(sorted_coloc)} EWRAM addresses found co-located with battle anchors")
    print()

    for addr, anchors in sorted_coloc:
        known_name = ""
        for n, a in KNOWN.items():
            if a == addr:
                known_name = f" <-- {n}"
                break
        exp_name = ""
        for n, a in expected.items():
            if a == addr and n in TARGETS:
                exp_name = f" *** EXPECTED TARGET: {n} ***"
                break
            elif a == addr:
                exp_name = f" (expected: {n})"
                break
        print(f"    0x{addr:08X}  (in {len(anchors):2d} funcs: {', '.join(sorted(anchors)[:5])}){known_name}{exp_name}")

    print()

    # =========================================================================
    # STEP 4: Focused search — find gBattlerByTurnOrder and gActionsByTurnOrder
    #         They are accessed together in SetActionsAndBattlersTurnOrder
    # =========================================================================
    print("=" * 78)
    print("  STEP 4: Focused search for target variables")
    print("=" * 78)
    print()

    # Strategy: gBattlerByTurnOrder and gActionsByTurnOrder are written together
    # in SetActionsAndBattlersTurnOrder (line ~5021):
    #   gActionsByTurnOrder[turnOrderId] = gChosenActionByBattler[battler];
    #   gBattlerByTurnOrder[turnOrderId] = battler;
    # These two are 4-byte u8[4] arrays declared consecutively.
    # The function also references gChosenActionByBattler and gBattlersCount.

    # Find functions that reference gBattlersCount AND addresses near gBattlerPositions
    battlers_count_addr = KNOWN["gBattlersCount"]
    battlers_count_refs = find_all_refs(rom_data, battlers_count_addr)

    print(f"  gBattlersCount (0x{battlers_count_addr:08X}): {len(battlers_count_refs)} literal pool refs")
    print()

    # For each function referencing gBattlersCount, look for addresses in range
    # gBattlerPositions (0x020233EE) to gBattlerPositions+16
    # That's where gActionsByTurnOrder and gBattlerByTurnOrder should be
    pos_base = KNOWN["gBattlerPositions"]  # 0x020233EE
    nearby_range = (pos_base, pos_base + 0x20)  # should be within 32 bytes

    print(f"  Looking for EWRAM addresses in range 0x{nearby_range[0]:08X}-0x{nearby_range[1]:08X}")
    print(f"  (near gBattlerPositions, where gActionsByTurnOrder + gBattlerByTurnOrder should be)")
    print()

    found_near = defaultdict(list)
    for ref_off in battlers_count_refs:
        func_start = find_function_start(rom_data, ref_off)
        if func_start is None:
            continue
        func_addrs = get_ewram_addrs_in_function(rom_data, func_start, 4096)
        for ea in func_addrs:
            if nearby_range[0] <= ea < nearby_range[1]:
                func_rom = ROM_BASE + func_start + 1
                found_near[ea].append(func_rom)

    for addr in sorted(found_near.keys()):
        funcs = found_near[addr]
        print(f"    0x{addr:08X}  (in {len(funcs)} funcs: {', '.join(f'0x{f:08X}' for f in funcs[:5])})")

    print()

    # =========================================================================
    # STEP 5: Search for gChosenActionByBattler via B_ACTION_NONE pattern
    #         The code does: gChosenActionByBattler[i] = B_ACTION_NONE (0xFF)
    #         This appears as: MOV Rx, #0xFF; STRB Rx, [Ry, Rz]
    #         The function also references gBattlersCount
    # =========================================================================
    print("=" * 78)
    print("  STEP 5: Narrow search for gChosenActionByBattler and gChosenMoveByBattler")
    print("=" * 78)
    print()

    # gChosenActionByBattler should be between gBattleMons end and gBattleCommunication
    # gBattleMons = 0x020233FC, size ~4*0x5C = 0x170
    # So gBattleMons end ~= 0x0202356C
    # gBattleCommunication = 0x0202370E
    # Search range: 0x02023500-0x02023710

    search_range = (0x02023500, 0x02023720)
    print(f"  Searching EWRAM literal pool refs in 0x{search_range[0]:08X}-0x{search_range[1]:08X}")
    print(f"  (between gBattleMons end and gBattleCommunication)")
    print()

    mid_refs = defaultdict(int)
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if search_range[0] <= val < search_range[1]:
            mid_refs[val] += 1

    sorted_mid = sorted(mid_refs.items(), key=lambda x: x[0])
    print(f"  {len(sorted_mid)} unique addresses found:")
    for addr, count in sorted_mid:
        known_name = ""
        for n, a in KNOWN.items():
            if a == addr:
                known_name = f" <-- {n}"
                break
        print(f"    0x{addr:08X}  ({count:4d} refs){known_name}")

    print()

    # =========================================================================
    # STEP 6: Find gBattleTurnCounter — it's set to 0 in TryDoEventsBeforeFirstTurn
    #         which also references gBattlerByTurnOrder.
    #         Search range: past gBattleCommunication+8 through gBattleResources
    # =========================================================================
    print("=" * 78)
    print("  STEP 6: Search for gBattleTurnCounter (after gBattleCommunication)")
    print("=" * 78)
    print()

    # gBattleCommunication = 0x0202370E, size 8 => ends at 0x02023716
    # gBattleResources = 0x02023A18
    # gBattleTurnCounter is between these (line 236 vs line 200/221)
    tc_range = (0x02023716, 0x02023A20)
    print(f"  Searching EWRAM literal pool refs in 0x{tc_range[0]:08X}-0x{tc_range[1]:08X}")
    print()

    tc_refs = defaultdict(int)
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if tc_range[0] <= val < tc_range[1]:
            tc_refs[val] += 1

    sorted_tc = sorted(tc_refs.items(), key=lambda x: x[0])
    print(f"  {len(sorted_tc)} unique addresses found:")
    for addr, count in sorted_tc:
        known_name = ""
        for n, a in KNOWN.items():
            if a == addr:
                known_name = f" <-- {n}"
                break
        print(f"    0x{addr:08X}  ({count:4d} refs){known_name}")

    print()

    # =========================================================================
    # STEP 7: Cross-reference with TryDoEventsBeforeFirstTurn pattern
    #         This function sets:
    #           gBattleTurnCounter = 0
    #           gBattlerByTurnOrder[i] = i
    #           gChosenActionByBattler[i] = B_ACTION_NONE
    #           gChosenMoveByBattler[i] = MOVE_NONE
    #         So find functions that reference 3+ addresses from our candidates
    # =========================================================================
    print("=" * 78)
    print("  STEP 7: Cross-reference — find functions referencing multiple candidates")
    print("=" * 78)
    print()

    # Collect ALL candidate addresses from steps 4-6
    all_candidates = set()
    for addr in found_near:
        all_candidates.add(addr)
    for addr, _ in sorted_mid:
        all_candidates.add(addr)
    for addr, _ in sorted_tc:
        all_candidates.add(addr)

    # Add known anchors in battle range
    for n, a in KNOWN.items():
        if 0x02023300 <= a < 0x02023C00:
            all_candidates.add(a)

    print(f"  Total candidate addresses: {len(all_candidates)}")
    print()

    # For each candidate, find all ROM functions that reference it
    candidate_funcs = defaultdict(set)  # func_start -> set of addresses
    for addr in all_candidates:
        refs = find_all_refs(rom_data, addr)
        for ref_off in refs:
            fs = find_function_start(rom_data, ref_off)
            if fs is not None:
                candidate_funcs[fs].add(addr)

    # Find functions that reference 4+ candidates (likely TryDoEventsBeforeFirstTurn
    # or SetActionsAndBattlersTurnOrder)
    multi_ref_funcs = [(fs, addrs) for fs, addrs in candidate_funcs.items() if len(addrs) >= 4]
    multi_ref_funcs.sort(key=lambda x: -len(x[1]))

    print(f"  Functions referencing 4+ candidate addresses: {len(multi_ref_funcs)}")
    print()

    for func_start, addrs in multi_ref_funcs[:20]:
        func_rom = ROM_BASE + func_start + 1
        sorted_addrs = sorted(addrs)
        addr_strs = []
        for a in sorted_addrs:
            name = ""
            for n, ka in KNOWN.items():
                if ka == a:
                    name = n
                    break
            if name:
                addr_strs.append(f"0x{a:08X}({name})")
            else:
                addr_strs.append(f"0x{a:08X}")
        print(f"    0x{func_rom:08X} ({len(addrs)} addrs): {', '.join(addr_strs)}")

    print()

    # =========================================================================
    # STEP 8: Definitive identification using address proximity patterns
    # =========================================================================
    print("=" * 78)
    print("  STEP 8: Definitive identification")
    print("=" * 78)
    print()

    # From the source order:
    # gBattlerPositions[4] = 0x020233EE (KNOWN, u8[4] = 4 bytes)
    # gActionsByTurnOrder[4] should be at 0x020233F2 (or aligned)
    # gBattlerByTurnOrder[4] should be at 0x020233F6 (or aligned)
    #
    # But also:
    # gBattlersCount = 0x020233E4 (KNOWN, u8)
    # gBattlerPartyIndexes[4] = after gBattlersCount (+1, aligned to 2) = 0x020233E6 (u16[4]=8)
    # gBattlerPositions[4] = 0x020233EE (KNOWN) = 0x020233E6+8 -- MATCHES!
    # gActionsByTurnOrder = 0x020233F2
    # gBattlerByTurnOrder = 0x020233F6
    # gCurrentTurnActionNumber = 0x020233FA (u8)
    # gCurrentActionFuncId = 0x020233FB (u8)
    # gBattleMons = 0x020233FC (KNOWN) -- MATCHES with 4-align!

    # Check: gBattlerPositions(0x020233EE) + 4 = 0x020233F2
    # gBattlerByTurnOrder would be 0x020233F2 + 4 = 0x020233F6
    # Then: 0x020233F6 + 4 + 1 + 1 = 0x020233FC = gBattleMons! PERFECT!

    predicted_gActionsByTurnOrder = KNOWN["gBattlerPositions"] + 4  # 0x020233F2
    predicted_gBattlerByTurnOrder = predicted_gActionsByTurnOrder + 4  # 0x020233F6
    predicted_gCurrentTurnActionNumber = predicted_gBattlerByTurnOrder + 4  # 0x020233FA
    predicted_gCurrentActionFuncId = predicted_gCurrentTurnActionNumber + 1  # 0x020233FB
    # Then gBattleMons at 0x020233FC (known) -- needs 4-alignment from 0x020233FC. MATCH!

    print(f"  Layout verification (gBattlerPositions to gBattleMons):")
    print(f"    gBattlersCount           = 0x{KNOWN['gBattlersCount']:08X} (KNOWN)")
    print(f"    gBattlerPartyIndexes[4]  = 0x{KNOWN['gBattlersCount']+2:08X} (predicted: gBattlersCount+2, u16[4]=8)")
    print(f"    gBattlerPositions[4]     = 0x{KNOWN['gBattlerPositions']:08X} (KNOWN) == predicted 0x{KNOWN['gBattlersCount']+2+8:08X} {'MATCH' if KNOWN['gBattlerPositions'] == KNOWN['gBattlersCount']+2+8 else 'MISMATCH!'}")
    print(f"    gActionsByTurnOrder[4]   = 0x{predicted_gActionsByTurnOrder:08X} (predicted)")
    print(f"    gBattlerByTurnOrder[4]   = 0x{predicted_gBattlerByTurnOrder:08X} (predicted) *** TARGET 1 ***")
    print(f"    gCurrentTurnActionNumber = 0x{predicted_gCurrentTurnActionNumber:08X} (predicted)")
    print(f"    gCurrentActionFuncId     = 0x{predicted_gCurrentActionFuncId:08X} (predicted)")
    print(f"    gBattleMons[4]           = 0x{KNOWN['gBattleMons']:08X} (KNOWN) == predicted 0x{predicted_gCurrentActionFuncId+1:08X} (align4=0x{(predicted_gCurrentActionFuncId+1+3)&~3:08X}) {'MATCH' if KNOWN['gBattleMons'] == ((predicted_gCurrentActionFuncId+1+3)&~3) else 'MISMATCH!'}")
    print()

    # Check if predicted addresses have literal pool refs
    for name, addr in [
        ("gActionsByTurnOrder", predicted_gActionsByTurnOrder),
        ("gBattlerByTurnOrder", predicted_gBattlerByTurnOrder),
        ("gCurrentTurnActionNumber", predicted_gCurrentTurnActionNumber),
    ]:
        refs = find_all_refs(rom_data, addr)
        print(f"    {name} (0x{addr:08X}): {len(refs)} ROM literal pool refs")

    print()

    # Now for gChosenActionByBattler:
    # gBattleMons[4] = 0x020233FC, each entry ~0x5C (92 bytes), 4 entries = 0x170
    # gBattleMons end = 0x0202356C
    # Then: gBattlerSpriteIds[4] (4 bytes) = 0x0202356C
    # gCurrMovePos (u8) = 0x02023570
    # gChosenMovePos (u8) = 0x02023571
    # gCurrentMove (u16) = 0x02023572
    # gChosenMove (u16) = 0x02023574
    # gCalledMove (u16) = 0x02023576
    # gBideDmg[4] (s32*4=16, align4) = 0x02023578
    # gLastUsedItem (u16) = 0x02023588
    # gLastUsedAbility (enum=u16) = 0x0202358A
    # gBattlerAttacker (u8) = 0x0202358C
    # gBattlerTarget (u8) = 0x0202358D
    # gBattlerFainted (u8) = 0x0202358E
    # gEffectBattler (u8) = 0x0202358F
    # gPotentialItemEffectBattler (u8) = 0x02023590
    # gAbsentBattlerFlags (u8) = 0x02023591
    # gMultiHitCounter (u8) = 0x02023592
    # gBattlescriptCurrInstr (ptr, align4) = 0x02023594
    # gChosenActionByBattler[4] (u8*4) = 0x02023598  *** TARGET 2 ***

    predicted_gBattlerSpriteIds = KNOWN["gBattleMons"] + 4 * 0x5C  # 0x0202356C
    predicted_gBattlescriptCurrInstr = predicted_gBattlerSpriteIds + 4 + 1 + 1 + 2 + 2 + 2 + 16 + 2 + 2 + 1 + 1 + 1 + 1 + 1 + 1 + 1
    predicted_gBattlescriptCurrInstr = (predicted_gBattlescriptCurrInstr + 3) & ~3  # align4
    predicted_gChosenActionByBattler = predicted_gBattlescriptCurrInstr + 4

    print(f"  Layout verification (gBattleMons to gChosenActionByBattler):")
    print(f"    gBattleMons[4] end       = 0x{KNOWN['gBattleMons'] + 4 * 0x5C:08X}")
    print(f"    gBattlerSpriteIds        = 0x{predicted_gBattlerSpriteIds:08X}")
    print(f"    gBattlescriptCurrInstr   = 0x{predicted_gBattlescriptCurrInstr:08X}")
    print(f"    gChosenActionByBattler   = 0x{predicted_gChosenActionByBattler:08X} *** TARGET 2 ***")

    refs_bsci = find_all_refs(rom_data, predicted_gBattlescriptCurrInstr)
    refs_cab = find_all_refs(rom_data, predicted_gChosenActionByBattler)
    print(f"    gBattlescriptCurrInstr refs: {len(refs_bsci)}")
    print(f"    gChosenActionByBattler refs: {len(refs_cab)}")
    print()

    # gChosenMoveByBattler:
    # After gChosenActionByBattler[4], there are:
    # gSelectionBattleScripts[4] (ptr*4=16)
    # gPalaceSelectionBattleScripts[4] (ptr*4=16)
    # gLastPrintedMoves[4] (u16*4=8)
    # gLastMoves[4] (u16*4=8)
    # gLastLandedMoves[4] (u16*4=8)
    # gLastHitByType[4] (u16*4=8)
    # gLastUsedMoveType[4] (u16*4=8)
    # gLastResultingMoves[4] (u16*4=8)
    # gLockedMoves[4] (u16*4=8)
    # gLastUsedMove (u16=2)
    # gLastHitBy[4] (u8*4=4)
    # gChosenMoveByBattler[4] (u16*4=8) *** TARGET 3 ***

    skip_after_cab = 4 + 16 + 16 + 8 + 8 + 8 + 8 + 8 + 8 + 8 + 2 + 4
    predicted_gChosenMoveByBattler = predicted_gChosenActionByBattler + skip_after_cab
    # Check alignment (u16 = 2-aligned)
    predicted_gChosenMoveByBattler = (predicted_gChosenMoveByBattler + 1) & ~1  # align to 2

    print(f"  Layout verification (gChosenActionByBattler to gChosenMoveByBattler):")
    print(f"    gChosenActionByBattler   = 0x{predicted_gChosenActionByBattler:08X}")
    print(f"    + SelectionScripts(16) + PalaceScripts(16) + PrintedMoves(8) + LastMoves(8)")
    print(f"    + LandedMoves(8) + HitByType(8) + UsedMoveType(8) + ResultingMoves(8)")
    print(f"    + LockedMoves(8) + LastUsedMove(2) + LastHitBy(4)")
    print(f"    gChosenMoveByBattler     = 0x{predicted_gChosenMoveByBattler:08X} *** TARGET 3 ***")

    refs_cmbb = find_all_refs(rom_data, predicted_gChosenMoveByBattler)
    print(f"    gChosenMoveByBattler refs: {len(refs_cmbb)}")
    print()

    # gBattleTurnCounter search:
    # It's at line 236, many variables after gBattleCommunication (line 200)
    # gBattleCommunication = 0x0202370E, followed by many structs
    # Too many unknowns. Better approach: scan functions referencing gBattlerByTurnOrder
    # that also reference a u16 in the gBattleCommunication+0x100-0x400 range

    print(f"  Looking for gBattleTurnCounter:")
    print(f"    gBattleCommunication = 0x{KNOWN['gBattleCommunication']:08X}")
    print(f"    gBattleResources     = 0x{KNOWN['gBattleResources']:08X}")
    print(f"    Expected range: 0x02023700-0x02023A18")
    print()

    # Find functions referencing predicted_gBattlerByTurnOrder (or nearby confirmed addresses)
    # that also reference something in the 0x02023700-0x02023A00 range
    search_addrs = set()
    # Use confirmed gBattlerByTurnOrder address (check from Step 4 results)
    btto_refs = find_all_refs(rom_data, predicted_gBattlerByTurnOrder)
    tc_candidates = defaultdict(int)

    for ref_off in btto_refs:
        func_start = find_function_start(rom_data, ref_off)
        if func_start is None:
            continue
        func_ewram = get_ewram_addrs_in_function(rom_data, func_start, 4096)
        for ea in func_ewram:
            if 0x02023800 <= ea < 0x02023A18:
                tc_candidates[ea] += 1

    print(f"    EWRAM addresses in functions also referencing gBattlerByTurnOrder:")
    for addr in sorted(tc_candidates.keys()):
        count = tc_candidates[addr]
        print(f"      0x{addr:08X}  ({count} co-occurrences)")

    print()

    # Also search via gChosenActionByBattler (they're in the same function)
    cab_refs = find_all_refs(rom_data, predicted_gChosenActionByBattler)
    tc_candidates2 = defaultdict(int)
    for ref_off in cab_refs:
        func_start = find_function_start(rom_data, ref_off)
        if func_start is None:
            continue
        func_ewram = get_ewram_addrs_in_function(rom_data, func_start, 4096)
        for ea in func_ewram:
            if 0x02023800 <= ea < 0x02023A18:
                tc_candidates2[ea] += 1

    print(f"    EWRAM addresses in functions also referencing gChosenActionByBattler:")
    for addr in sorted(tc_candidates2.keys()):
        count = tc_candidates2[addr]
        print(f"      0x{addr:08X}  ({count} co-occurrences)")

    print()

    # gBattleTurnCounter (u16) appears as a literal in functions that also access
    # gBattlerByTurnOrder, gChosenActionByBattler, gChosenMoveByBattler
    # Intersect the two candidate sets for high-confidence
    common_tc = set(tc_candidates.keys()) & set(tc_candidates2.keys())
    print(f"    Addresses in BOTH gBattlerByTurnOrder AND gChosenActionByBattler functions:")
    for addr in sorted(common_tc):
        total = tc_candidates[addr] + tc_candidates2[addr]
        print(f"      0x{addr:08X}  ({total} total co-occurrences)")

    print()

    # =========================================================================
    # STEP 9: Alternative approach for BattleMons size verification
    # =========================================================================
    print("=" * 78)
    print("  STEP 9: BattlePokemon struct size verification")
    print("=" * 78)
    print()

    # The R&B config says gBattleMons = 0x020233FC
    # If BattlePokemon is 0x5C (92) bytes, 4 entries = 0x170, end = 0x0202356C
    # If it's 0x63 (99) bytes (+alignment), it could be 0x64 (100) per entry, 4 = 0x190, end = 0x0202358C
    # Check which end-point leads to more literal pool refs for the variables after it

    for bp_size in [0x58, 0x5C, 0x60, 0x63, 0x64, 0x68]:
        end_addr = KNOWN["gBattleMons"] + 4 * bp_size
        # gBattlerSpriteIds should be right after
        sprite_ids_addr = end_addr
        refs = find_all_refs(rom_data, sprite_ids_addr)
        if refs:
            print(f"    BattlePokemon size=0x{bp_size:02X}: gBattlerSpriteIds=0x{sprite_ids_addr:08X} -> {len(refs)} refs")

    print()

    # Also try to find gBattlerAttacker/gBattlerTarget which have many refs
    # They should be at gBattleMons_end + 4 + 1 + 1 + 2 + 2 + 2 + 16 + 2 + 2 = +32
    for bp_size in [0x58, 0x5C, 0x60, 0x63, 0x64, 0x68]:
        end_addr = KNOWN["gBattleMons"] + 4 * bp_size
        attacker_addr = end_addr + 4 + 1 + 1 + 2 + 2 + 2 + 16 + 2 + 2  # 32 bytes after end
        refs_atk = find_all_refs(rom_data, attacker_addr)
        target_addr = attacker_addr + 1
        refs_tgt = find_all_refs(rom_data, target_addr)
        if refs_atk or refs_tgt:
            print(f"    BattlePokemon size=0x{bp_size:02X}: gBattlerAttacker=0x{attacker_addr:08X}({len(refs_atk)} refs), gBattlerTarget=0x{target_addr:08X}({len(refs_tgt)} refs)")

    print()

    # Try gBattlescriptCurrInstr (heavily referenced, ptr = 4-aligned)
    for bp_size in [0x58, 0x5C, 0x60, 0x63, 0x64, 0x68]:
        end_addr = KNOWN["gBattleMons"] + 4 * bp_size
        # Path: spriteIds(4) + currMovePos(1) + chosenMovePos(1) + currentMove(2) + chosenMove(2) + calledMove(2) + bideDmg(align4+16) + lastUsedItem(2) + lastUsedAbility(2) + attacker(1) + target(1) + fainted(1) + effect(1) + potential(1) + absent(1) + multiHit(1)
        # => 4+1+1+2+2+2 = 12, then align4 for bideDmg = pad to 4 = 12+16=28, then 2+2+1+1+1+1+1+1+1 = 11
        # total from end = 12 (possibly +padding) + 16 + 11 = 39, then align4 = 40
        bsci_addr = end_addr + 4 + 2 + 2 + 2 + 2  # spriteids + currMovePos(pad) + currentMove + chosenMove + calledMove
        bsci_addr = (bsci_addr + 3) & ~3  # align for bideDmg
        bsci_addr += 16  # bideDmg
        bsci_addr += 2 + 2 + 1 + 1 + 1 + 1 + 1 + 1 + 1  # lastUsedItem through multiHitCounter
        bsci_addr = (bsci_addr + 3) & ~3  # align for ptr
        refs = find_all_refs(rom_data, bsci_addr)
        if refs:
            print(f"    BattlePokemon size=0x{bp_size:02X}: gBattlescriptCurrInstr=0x{bsci_addr:08X} -> {len(refs)} refs")

    print()

    # =========================================================================
    # STEP 10: Brute force - scan for gBattlescriptCurrInstr
    # =========================================================================
    print("=" * 78)
    print("  STEP 10: Brute-force scan for high-ref-count addresses")
    print("=" * 78)
    print()

    # gBattlescriptCurrInstr is one of the most heavily referenced battle vars
    # (pointer to current battle script instruction, used in every script command)
    # It should be in range 0x02023560-0x020235C0

    print("  Scanning 0x02023560-0x020235C0 for high-ref-count addresses:")
    brute_refs = {}
    for addr in range(0x02023560, 0x020235C0, 4):  # 4-aligned (it's a pointer)
        count = len(find_all_refs(rom_data, addr))
        if count >= 5:
            brute_refs[addr] = count

    for addr in sorted(brute_refs.keys()):
        print(f"    0x{addr:08X}: {brute_refs[addr]} refs")

    print()

    # Similarly scan for gBattlerAttacker (very heavily referenced, u8 but loaded via LDR)
    print("  Scanning 0x0202356C-0x020235A0 for addresses with 20+ refs:")
    for addr in range(0x0202356C, 0x020235A0):
        count = len(find_all_refs(rom_data, addr))
        if count >= 20:
            print(f"    0x{addr:08X}: {count} refs")

    print()

    # Scan wider range for gChosenActionByBattler (should have ~30+ refs based on source usage)
    print("  Scanning 0x020235A0-0x02023620 for addresses with 10+ refs:")
    for addr in range(0x020235A0, 0x02023620):
        count = len(find_all_refs(rom_data, addr))
        if count >= 10:
            print(f"    0x{addr:08X}: {count} refs")

    print()

    # Scan for gChosenMoveByBattler (u16[4], should be 2-aligned, ~20+ refs)
    print("  Scanning 0x02023620-0x020236C0 for addresses with 5+ refs:")
    for addr in range(0x02023620, 0x020236C0, 2):
        count = len(find_all_refs(rom_data, addr))
        if count >= 5:
            print(f"    0x{addr:08X}: {count} refs")

    print()

    # Scan for gBattleTurnCounter (u16, near gBattleCommunication region)
    print("  Scanning 0x020238C0-0x020239C0 for addresses with 3+ refs:")
    for addr in range(0x020238C0, 0x020239C0, 2):
        count = len(find_all_refs(rom_data, addr))
        if count >= 3:
            print(f"    0x{addr:08X}: {count} refs")

    print()

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("=" * 78)
    print("  SUMMARY — Predicted addresses")
    print("=" * 78)
    print()
    print(f"  TARGET 1: gBattlerByTurnOrder[4]    = 0x{predicted_gBattlerByTurnOrder:08X}  (u8[4], {len(find_all_refs(rom_data, predicted_gBattlerByTurnOrder))} ROM refs)")
    print(f"  TARGET 2: gChosenActionByBattler[4]  = 0x{predicted_gChosenActionByBattler:08X}  (u8[4], {len(find_all_refs(rom_data, predicted_gChosenActionByBattler))} ROM refs)")
    print(f"  TARGET 3: gChosenMoveByBattler[4]    = 0x{predicted_gChosenMoveByBattler:08X}  (u16[4], {len(find_all_refs(rom_data, predicted_gChosenMoveByBattler))} ROM refs)")
    print(f"  TARGET 4: gBattleTurnCounter         = (see Step 6/7 candidates)")
    print()
    print("  NOTE: These predictions assume:")
    print("    - BattlePokemon struct size = 0x5C (92 bytes) per entry")
    print("    - Source declaration order = BSS layout order")
    print("    - No additional padding between variables")
    print("  If ref counts are 0, the compiler may use base+offset addressing instead of")
    print("  literal pool entries for small arrays. Verify at runtime with a Lua scanner.")
    print()


if __name__ == "__main__":
    main()
