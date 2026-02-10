#!/usr/bin/env python3
"""
ROM Literal Pool Scanner — Find battle variable addresses in Pokemon Run & Bun

Reads the ROM binary directly and scans for known EWRAM addresses in literal pools.
For each known anchor, finds nearby unknown EWRAM addresses (co-located in the same
function's literal pool = likely related variables).

Also identifies functions by walking backward from literal pool entries to PUSH {LR}.

No Ghidra needed — just reads the .gba file.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known anchors (verified addresses)
KNOWN = {
    "gPlayerParty":      0x02023A98,
    "gPlayerPartyCount": 0x02023A95,
    "gEnemyParty":       0x02023CF0,
    "gBattleTypeFlags":  0x020090E8,
    "gMainAddr":         0x02020648,
    "gMainCallback2":    0x0202064C,
    "gMainInBattle":     0x020206AE,
    "gPokemonStorage":   0x02028848,
    "sWarpDestination":  0x020318A8,
    "CB2_LoadMap":       0x08007441,
    "CB2_Overworld":     0x080A89A5,
    "CB2_BattleMain":    0x08094815,
    "GetMultiplayerId":  0x0833D67F,
    "SIO_MULTI_CNT":     0x04000120,
}

def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def find_all_refs(rom_data, target_value):
    """Find all 4-byte aligned positions where target_value appears."""
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs

def find_function_start(rom_data, offset):
    """Walk backward from offset to find PUSH {LR} or PUSH {Rx, LR}."""
    for back in range(2, 1024, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in (0xB400, 0xB500):
            return pos
    return None

def analyze_function(rom_data, func_offset):
    """Analyze function: measure size, count BL calls, extract BL targets."""
    size = None
    bl_targets = []
    pos = func_offset
    end = min(func_offset + 512, len(rom_data) - 1)

    while pos < end:
        instr = read_u16_le(rom_data, pos)

        # Function end: POP {PC} or BX LR (skip first instruction)
        if pos > func_offset + 2:
            if (instr & 0xFF00) == 0xBD00 or instr == 0x4770:
                size = pos + 2 - func_offset
                break

        # BL instruction pair
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

def get_litpool_ewram_addrs(rom_data, lit_offset, radius=256):
    """Get all EWRAM addresses in the literal pool near a given offset."""
    addrs = []
    start = max(0, lit_offset - radius)
    end = min(len(rom_data) - 3, lit_offset + radius)
    # Align to 4
    start = (start + 3) & ~3
    for pos in range(start, end, 4):
        val = read_u32_le(rom_data, pos)
        if 0x02000000 <= val < 0x02040000:
            addrs.append((pos, val))
    return addrs


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print()

    # =========================================================================
    # STEP 1: Find all literal pool references to known anchors
    # =========================================================================
    print("=" * 70)
    print("  STEP 1: Literal pool references to known anchors")
    print("=" * 70)
    print()

    anchor_refs = {}  # name -> [rom_offsets]
    for name, addr in sorted(KNOWN.items()):
        refs = find_all_refs(rom_data, addr)
        anchor_refs[name] = refs
        print(f"  {name} (0x{addr:08X}): {len(refs)} ROM refs")

    print()

    # =========================================================================
    # STEP 2: For each anchor with refs, scan nearby literal pool for EWRAM addrs
    # =========================================================================
    print("=" * 70)
    print("  STEP 2: Unknown EWRAM addresses near known anchors")
    print("=" * 70)
    print()

    known_values = set(KNOWN.values())
    nearby_map = defaultdict(set)  # ewram_addr -> set of anchor names

    for name, refs in sorted(anchor_refs.items()):
        for lit_offset in refs:
            nearby = get_litpool_ewram_addrs(rom_data, lit_offset, 512)
            for _, ewram_addr in nearby:
                if ewram_addr not in known_values:
                    nearby_map[ewram_addr].add(name)

    # Sort by number of co-references then by address
    sorted_addrs = sorted(nearby_map.items(), key=lambda x: (-len(x[1]), x[0]))

    # Print by region
    battle_region = [(a, n) for a, n in sorted_addrs if 0x02008000 <= a < 0x0200C000]
    main_region = [(a, n) for a, n in sorted_addrs if 0x02020000 <= a < 0x02025000]
    other_region = [(a, n) for a, n in sorted_addrs
                    if not (0x02008000 <= a < 0x0200C000) and not (0x02020000 <= a < 0x02025000)]

    def print_region(title, entries, limit=60):
        if not entries:
            return
        print(f"  [{title}] ({len(entries)} addresses)")
        for i, (addr, anchors) in enumerate(entries[:limit]):
            anchor_str = ", ".join(sorted(anchors))
            print(f"    0x{addr:08X}  ({len(anchors)} refs: {anchor_str})")
        if len(entries) > limit:
            print(f"    ... and {len(entries) - limit} more")
        print()

    print_region("BATTLE REGION 0x02008xxx-0x0200Bxxx", battle_region)
    print_region("MAIN/PARTY REGION 0x02020xxx-0x02024xxx", main_region)
    print_region("OTHER REGIONS", other_region, 30)

    # =========================================================================
    # STEP 3: Focus on battle-critical variables
    # =========================================================================
    print("=" * 70)
    print("  STEP 3: Battle-critical variable identification")
    print("=" * 70)
    print()

    # Find addresses referenced near BOTH gBattleTypeFlags AND gEnemyParty/gPlayerParty
    # These are most likely other battle globals
    battle_anchors = {"gBattleTypeFlags", "gEnemyParty", "gPlayerParty", "CB2_BattleMain"}
    multi_battle_refs = [(a, n) for a, n in sorted_addrs if len(n & battle_anchors) >= 2]
    print(f"  Addresses near 2+ battle anchors ({len(multi_battle_refs)}):")
    for addr, anchors in multi_battle_refs[:30]:
        print(f"    0x{addr:08X}  (near: {', '.join(sorted(anchors))})")
    print()

    # Find functions that reference gBattleTypeFlags
    print("  Functions referencing gBattleTypeFlags:")
    btf_refs = anchor_refs.get("gBattleTypeFlags", [])
    seen_funcs = set()
    for lit_off in btf_refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start and func_start not in seen_funcs:
            seen_funcs.add(func_start)
            size, bl_targets = analyze_function(rom_data, func_start)
            func_addr = ROM_BASE + func_start + 1  # +1 THUMB
            bl_str = ""
            for t in bl_targets[:3]:
                bl_str += f" BL->0x{t:08X}"
            print(f"    0x{func_addr:08X} ({size or '?'} bytes, {len(bl_targets)} BL){bl_str}")
    print()

    # Functions referencing gEnemyParty
    print("  Functions referencing gEnemyParty:")
    ep_refs = anchor_refs.get("gEnemyParty", [])
    seen_funcs = set()
    for lit_off in ep_refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start and func_start not in seen_funcs:
            seen_funcs.add(func_start)
            size, bl_targets = analyze_function(rom_data, func_start)
            func_addr = ROM_BASE + func_start + 1
            bl_str = ""
            for t in bl_targets[:3]:
                bl_str += f" BL->0x{t:08X}"
            print(f"    0x{func_addr:08X} ({size or '?'} bytes, {len(bl_targets)} BL){bl_str}")
    print()

    # =========================================================================
    # STEP 4: Direct scan for specific known patterns
    # =========================================================================
    print("=" * 70)
    print("  STEP 4: Direct scan for key variables")
    print("=" * 70)
    print()

    # Scan for ALL EWRAM addresses that appear in ROM literal pools
    # Then sort by frequency (most referenced = most important)
    print("  Scanning ALL EWRAM literal pool refs in ROM...")
    all_ewram_refs = defaultdict(int)
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if 0x02000000 <= val < 0x02040000:
            all_ewram_refs[val] += 1

    # Sort by frequency
    sorted_all = sorted(all_ewram_refs.items(), key=lambda x: -x[1])
    print(f"  {len(sorted_all)} unique EWRAM addresses found in ROM")
    print()

    # Print top 100 most referenced
    print("  TOP 100 most-referenced EWRAM addresses:")
    for i, (addr, count) in enumerate(sorted_all[:100]):
        known_name = ""
        for name, kaddr in KNOWN.items():
            if kaddr == addr:
                known_name = f" <-- {name}"
                break
        print(f"    {i+1:3d}. 0x{addr:08X}  ({count:3d} refs){known_name}")

    print()

    # =========================================================================
    # STEP 5: Cluster analysis — find variable groups
    # =========================================================================
    print("=" * 70)
    print("  STEP 5: EWRAM address clusters (likely struct/variable groups)")
    print("=" * 70)
    print()

    # Group nearby addresses (within 256 bytes of each other)
    all_addrs = sorted(all_ewram_refs.keys())
    clusters = []
    current_cluster = [all_addrs[0]] if all_addrs else []

    for addr in all_addrs[1:]:
        if addr - current_cluster[-1] <= 256:
            current_cluster.append(addr)
        else:
            if len(current_cluster) >= 3:
                clusters.append(current_cluster)
            current_cluster = [addr]
    if len(current_cluster) >= 3:
        clusters.append(current_cluster)

    # Print significant clusters
    for cluster in clusters:
        start = cluster[0]
        end = cluster[-1]
        span = end - start

        # Check if any known anchors are in this cluster
        known_in_cluster = []
        for name, addr in KNOWN.items():
            if start <= addr <= end:
                known_in_cluster.append(name)

        if known_in_cluster or len(cluster) >= 5:
            total_refs = sum(all_ewram_refs[a] for a in cluster)
            print(f"  Cluster 0x{start:08X}-0x{end:08X} ({len(cluster)} vars, {span} bytes span, {total_refs} total refs)")
            if known_in_cluster:
                print(f"    Known: {', '.join(known_in_cluster)}")
            for addr in cluster[:20]:
                refs = all_ewram_refs[addr]
                name = ""
                for n, a in KNOWN.items():
                    if a == addr:
                        name = f" <-- {n}"
                print(f"      0x{addr:08X} ({refs:3d} refs){name}")
            if len(cluster) > 20:
                print(f"      ... and {len(cluster) - 20} more")
            print()

    print("=" * 70)
    print("  SCAN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
