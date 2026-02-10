#!/usr/bin/env python3
"""
Find gBattleSpritesDataPtr in Run & Bun ROM.

gBattleSpritesDataPtr is a pointer in EWRAM, referenced heavily by battle code.
It's separate from gBattleResources (0x02023A18).

Strategy: Look for EWRAM addresses near 0x02023A00-0x02023B00 that have
many ROM literal pool references (indicating they're heavily-used battle globals).
"""

import struct

ROM_PATH = "rom/Pokemon RunBun.gba"

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def main():
    rom = read_rom()
    print(f"ROM size: {len(rom)} bytes")

    # Count literal pool references for each EWRAM address in range
    ref_counts = {}

    for off in range(0, min(len(rom) - 4, 0x01000000), 4):
        word = struct.unpack_from("<I", rom, off)[0]
        # Look for EWRAM addresses near battle globals
        if 0x02023900 <= word < 0x02023C00:
            ref_counts[word] = ref_counts.get(word, 0) + 1

    # Sort by count
    sorted_refs = sorted(ref_counts.items(), key=lambda x: -x[1])

    print(f"\nTop EWRAM addresses (0x02023900-0x02023C00) by literal pool refs:")
    print(f"{'Address':>12} {'Refs':>6} {'Note':>30}")
    print("-" * 60)

    known = {
        0x02023A18: "gBattleResources",
        0x02023A98: "gPlayerParty",
        0x02023A95: "gPlayerPartyCount",
        0x02023CF0: "gEnemyParty",
        0x020233DC: "gActiveBattler",
        0x020233E0: "gBattleControllerExecFlags",
        0x020233E4: "gBattlersCount",
        0x02023364: "gBattleTypeFlags",
    }

    for addr, count in sorted_refs[:50]:
        note = known.get(addr, "")
        print(f"  0x{addr:08X}  {count:5d}  {note}")

if __name__ == "__main__":
    main()
