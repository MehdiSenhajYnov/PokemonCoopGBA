#!/usr/bin/env python3
"""
Find gBattleMons EWRAM address by scanning ROM literal pools.

gBattleMons is EWRAM_DATA struct BattlePokemon gBattleMons[MAX_BATTLERS_COUNT]
- 4 entries × 0x63 bytes each = 0x18C bytes total
- Has many ROM references (species, moves, stats are read constantly during battle)
- Should be near other battle globals like gBattleCommunication (0x0202370E)

Strategy: Scan ROM for EWRAM literal pool references in the 0x02023xxx range
that appear very frequently (gBattleMons is accessed hundreds of times).
Cross-reference with known addresses to narrow down.
"""

import struct
import sys
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "rom", "Pokemon RunBun.gba")

def read_rom(path):
    with open(path, "rb") as f:
        return f.read()

def scan_literal_pools(rom_data, target_range_start, target_range_end):
    """Scan ROM for 32-bit values in the target EWRAM range."""
    refs = {}  # addr -> count
    # Literal pool entries are 4-byte aligned
    for off in range(0, len(rom_data) - 4, 4):
        val = struct.unpack_from("<I", rom_data, off)[0]
        if target_range_start <= val <= target_range_end:
            if val not in refs:
                refs[val] = 0
            refs[val] += 1
    return refs

def main():
    print(f"Loading ROM: {ROM_PATH}")
    rom = read_rom(ROM_PATH)
    print(f"ROM size: {len(rom)} bytes")

    # Known addresses for reference
    known = {
        0x020233DC: "gBattleControllerExecFlags",
        0x020233E0: "gActiveBattler",
        0x020233E4: "gBattlersCount",
        0x020233F6: "gBattlerByTurnOrder",
        0x02023364: "gBattleTypeFlags",
        0x02023598: "gChosenActionByBattler",
        0x020235FA: "gChosenMoveByBattler",
        0x02023708: "gBattleTurnCounter",
        0x0202370E: "gBattleCommunication",
        0x02023716: "gBattleOutcome (estimated)",
        0x02023A18: "gBattleResources",
        0x02023A98: "gPlayerParty",
    }

    # Scan the range 0x02023300 - 0x02023A00 for highly-referenced addresses
    print("\n=== Scanning ROM literal pools for EWRAM refs (0x02023300-0x02023A00) ===")
    refs = scan_literal_pools(rom, 0x02023300, 0x02023A00)

    # Sort by reference count (most referenced first)
    sorted_refs = sorted(refs.items(), key=lambda x: -x[1])

    print(f"\nFound {len(sorted_refs)} unique EWRAM addresses in ROM literal pools")
    print("\nTop 50 most-referenced addresses:")
    print(f"{'Address':>12s}  {'Refs':>5s}  {'Known':>30s}  {'Notes'}")
    print("-" * 80)

    for addr, count in sorted_refs[:50]:
        label = known.get(addr, "")
        notes = ""
        # Check if it could be gBattleMons based on reference count
        # gBattleMons should have LOTS of refs (species, moves, stats, etc.)
        if count >= 100 and not label:
            # Check if it's in the expected range (near other battle globals)
            notes = "*** HIGH REF COUNT - CANDIDATE ***"
        print(f"  0x{addr:08X}  {count:5d}  {label:>30s}  {notes}")

    # Also check specifically for gBattleMons candidates
    # gBattleMons is 0x18C bytes (396 bytes) for 4 battlers
    # It should be near gBattleCommunication (0x0202370E) based on declaration order
    # In battle_main.c: gBattleMons is at line 162, gBattleCommunication at line 200
    # So gBattleMons should be BEFORE gBattleCommunication
    print("\n\n=== Candidate Analysis for gBattleMons ===")
    print("gBattleMons is declared BEFORE gBattleCommunication in battle_main.c")
    print("Size: 4 × 0x63 = 0x18C bytes")
    print("Expected range: before 0x0202370E (gBattleCommunication)")
    print()

    # Look for addresses with 50+ refs that are multiples of struct size apart
    # or that are in the expected range
    candidates = []
    for addr, count in sorted_refs:
        if count >= 30 and 0x02023400 <= addr <= 0x02023700:
            candidates.append((addr, count))

    if candidates:
        print("Candidates (30+ refs, range 0x02023400-0x02023700):")
        for addr, count in candidates:
            label = known.get(addr, "")
            # Check if addr + 0x18C lands near gBattleCommunication
            end_addr = addr + 0x18C
            dist_to_comm = 0x0202370E - end_addr
            print(f"  0x{addr:08X} ({count} refs) {label}")
            print(f"    end_addr = 0x{end_addr:08X}, gap to gBattleCommunication = {dist_to_comm} bytes")

    # Also scan wider range for very high ref count addresses
    print("\n\n=== Very High Ref Count (100+) in 0x02023000-0x02024000 ===")
    refs2 = scan_literal_pools(rom, 0x02023000, 0x02024000)
    sorted_refs2 = sorted(refs2.items(), key=lambda x: -x[1])
    for addr, count in sorted_refs2:
        if count >= 100:
            label = known.get(addr, "")
            print(f"  0x{addr:08X}  {count:5d}  {label}")

if __name__ == "__main__":
    main()
