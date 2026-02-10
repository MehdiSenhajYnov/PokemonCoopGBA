#!/usr/bin/env python3
"""
ROM Scanner — Find gSprites array address in Pokemon Run & Bun

gSprites is an array of MAX_SPRITES+1 (65) Sprite structs.
Each Sprite is 0x44 (68) bytes.
Total array size: 65 * 68 = 4420 bytes = 0x1144.

Strategy:
1. Scan ALL EWRAM literal pool references, rank by frequency
   (gSprites is one of the most-referenced symbols in pokeemerald)
2. Look for addresses near size constants 0x1100 or 0x1144 in literal pools
3. Validate candidates by checking:
   - Size makes sense for EWRAM (fits within 0x02000000-0x0203FFFF)
   - Not already known as another variable
   - High reference count (gSprites should have 100+ refs)
   - Nearby literal pool entries include ROM function pointers (callbacks)
4. Cross-reference with CopyToSprites/CopyFromSprites pattern:
   These functions load gSprites address + 0x1100 size constant

Based on pokeemerald-expansion source (refs/pokeemerald-expansion/):
- Sprite struct: 0x44 bytes (same as vanilla)
- gSprites[MAX_SPRITES + 1] = 65 entries
- EWRAM_DATA declaration in sprite.c
- Adjacent EWRAM vars: sSpriteOrder (64 bytes), sShouldProcessSpriteCopyRequests, etc.
- gSpriteCoordOffsetX/Y declared later in same file

Vanilla Emerald reference: gSprites = 0x020200B0
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known addresses from config/run_and_bun.lua (to exclude from candidates)
KNOWN_ADDRS = {
    0x02024CBC: "playerX",
    0x02024CBE: "playerY",
    0x02024CC0: "mapGroup",
    0x02024CC1: "mapId",
    0x02036934: "facing",
    0x02023A98: "gPlayerParty",
    0x02023A95: "gPlayerPartyCount",
    0x02023CF0: "gEnemyParty",
    0x02023A96: "gEnemyPartyCount",
    0x02028848: "gPokemonStorage",
    0x02023364: "gBattleTypeFlags",
    0x02023A18: "gBattleResources",
    0x020233DC: "gActiveBattler",
    0x020233E0: "gBattleControllerExecFlags",
    0x0202370E: "gBattleCommunication",
    0x020229E8: "gLinkPlayers",
    0x020233E4: "gBattlersCount",
    0x020233EE: "gBattlerPositions",
    0x020233FC: "gBattleMons",
    0x020226C4: "gBlockRecvBuffer",
    0x020318A8: "sWarpDestination",
    0x020200B0: "gSprites_VANILLA",
}

# Important size constants
SPRITE_SIZE = 0x44           # sizeof(struct Sprite)
MAX_SPRITES = 64
FULL_ARRAY_SIZE = 0x1144     # (MAX_SPRITES + 1) * SPRITE_SIZE = 65 * 68
COPY_SIZE = 0x1100           # MAX_SPRITES * SPRITE_SIZE = 64 * 68

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
    for back in range(2, 2048, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        # PUSH {Rx, LR} or PUSH {LR}
        if (instr & 0xFF00) in (0xB400, 0xB500):
            return pos
    return None

def get_nearby_literals(rom_data, offset, radius=256):
    """Get all 32-bit literal pool values near a given offset."""
    results = []
    start = max(0, (offset - radius) & ~3)
    end = min(len(rom_data) - 3, offset + radius)
    for pos in range(start, end, 4):
        val = read_u32_le(rom_data, pos)
        results.append((pos, val))
    return results

def disasm_thumb_around(rom_data, addr_rom_offset, context=16):
    """Print a few THUMB instructions around an address for context."""
    lines = []
    start = max(0, addr_rom_offset - context)
    start = start & ~1  # Align to 2
    end = min(len(rom_data) - 1, addr_rom_offset + context)
    for pos in range(start, end, 2):
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        marker = " <<" if pos == addr_rom_offset or pos == addr_rom_offset - 2 else ""
        # Decode some common instructions
        desc = ""
        if (instr & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            # PC is aligned to 4 and is current + 4
            pc = (pos + 4) & ~3
            target_off = pc + imm
            if target_off < len(rom_data) - 3:
                lit_val = read_u32_le(rom_data, target_off)
                desc = f"  ; LDR R{rd}, =0x{lit_val:08X}"
        elif (instr & 0xFF00) == 0xB500:
            desc = f"  ; PUSH {{..., LR}}"
        elif (instr & 0xFF00) == 0xBD00:
            desc = f"  ; POP {{..., PC}}"
        elif instr == 0x4770:
            desc = f"  ; BX LR"
        elif (instr & 0xFFC0) == 0x0000 and instr != 0:
            desc = f"  ; LSL/MOV"
        elif (instr & 0xFF00) == 0x2000 or (instr & 0xFF00) == 0x2100:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc = f"  ; MOV R{rd}, #0x{imm:X}"

        lines.append(f"  0x{rom_addr:08X}: {instr:04X}{desc}{marker}")
    return "\n".join(lines)


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print()

    # =========================================================================
    # STEP 1: Scan ALL EWRAM literal pool references, rank by frequency
    # =========================================================================
    print("=" * 80)
    print("  STEP 1: ALL EWRAM literal pool references ranked by frequency")
    print("=" * 80)
    print()

    all_ewram_refs = defaultdict(list)  # addr -> [rom_offsets]
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if 0x02000000 <= val < 0x02040000:
            all_ewram_refs[val].append(i)

    # Sort by reference count descending
    sorted_by_freq = sorted(all_ewram_refs.items(), key=lambda x: -len(x[1]))

    print(f"  Found {len(sorted_by_freq)} unique EWRAM addresses in ROM literal pools")
    print()
    print("  TOP 50 most-referenced EWRAM addresses:")
    print(f"  {'Rank':>4}  {'Address':>12}  {'Refs':>5}  {'Known As'}")
    print(f"  {'----':>4}  {'-------':>12}  {'----':>5}  {'--------'}")
    for i, (addr, refs) in enumerate(sorted_by_freq[:50]):
        known = KNOWN_ADDRS.get(addr, "")
        flag = ""
        # Check if this could be gSprites based on size
        array_end = addr + FULL_ARRAY_SIZE
        if 0x02000000 <= array_end < 0x02040000:
            # Check if addr+SPRITE_SIZE or similar offsets also appear
            nearby_refs = 0
            for delta in [SPRITE_SIZE, SPRITE_SIZE*2, SPRITE_SIZE*3]:
                if (addr + delta) in all_ewram_refs:
                    nearby_refs += 1
            if nearby_refs >= 2:
                flag = " [SPRITE_STRIDE_MATCH]"
        print(f"  {i+1:4d}  0x{addr:08X}  {len(refs):5d}  {known}{flag}")
    print()

    # =========================================================================
    # STEP 2: Look for size constants 0x1100 and 0x1144 in literal pools
    # =========================================================================
    print("=" * 80)
    print("  STEP 2: Find EWRAM addresses co-located with sprite size constants")
    print("=" * 80)
    print()

    # In CopyToSprites/CopyFromSprites, the compiler loads:
    #   LDR R0, =gSprites     (EWRAM address)
    #   LDR R1, =0x1100        (or inlined as MOV + LSL)
    # Let's find all places where 0x1100 or 0x1144 appear as 32-bit literals
    for size_const in [COPY_SIZE, FULL_ARRAY_SIZE, SPRITE_SIZE]:
        size_refs = find_all_refs(rom_data, size_const)
        # Also check as 16-bit immediate in MOV instructions won't work for >255,
        # so check for the actual 32-bit literal pool value
        print(f"  Size constant 0x{size_const:04X} ({size_const}): {len(size_refs)} literal pool refs")

        for ref_off in size_refs:
            # Look for EWRAM addresses in the same literal pool neighborhood
            nearby = get_nearby_literals(rom_data, ref_off, 128)
            ewram_nearby = [(pos, val) for pos, val in nearby
                           if 0x02000000 <= val < 0x02040000 and len(all_ewram_refs.get(val, [])) >= 5]

            if ewram_nearby:
                func_start = find_function_start(rom_data, ref_off)
                func_addr = f"0x{ROM_BASE + func_start + 1:08X}" if func_start else "?"
                print(f"    At ROM+0x{ref_off:06X} (func ~{func_addr}):")
                for pos, val in ewram_nearby:
                    count = len(all_ewram_refs.get(val, []))
                    known = KNOWN_ADDRS.get(val, "")
                    print(f"      0x{val:08X} ({count} refs) {known}")
    print()

    # =========================================================================
    # STEP 3: Search for the specific CopyToSprites / CopyFromSprites pattern
    # =========================================================================
    print("=" * 80)
    print("  STEP 3: Find CopyToSprites/CopyFromSprites pattern")
    print("  (LDR Rx, =gSprites near LDR Ry, =0x1100)")
    print("=" * 80)
    print()

    # Find all occurrences of 0x00001100 in literal pools
    size_1100_refs = find_all_refs(rom_data, 0x1100)
    print(f"  Found {len(size_1100_refs)} literal pool refs to 0x1100")

    candidates = {}  # addr -> score

    for size_ref in size_1100_refs:
        # Search within 128 bytes for an EWRAM address
        for delta in range(-128, 128, 4):
            pos = size_ref + delta
            if 0 <= pos < len(rom_data) - 3:
                val = read_u32_le(rom_data, pos)
                if 0x02000000 <= val < 0x02040000:
                    ref_count = len(all_ewram_refs.get(val, []))
                    if ref_count >= 20:  # gSprites should be heavily referenced
                        if val not in KNOWN_ADDRS:
                            if val not in candidates or candidates[val] < ref_count:
                                candidates[val] = ref_count
                                print(f"    Candidate: 0x{val:08X} ({ref_count} total refs, near 0x1100 at ROM+0x{size_ref:06X})")

    print()

    # =========================================================================
    # STEP 4: Validate top candidates using stride pattern
    # =========================================================================
    print("=" * 80)
    print("  STEP 4: Validate candidates with stride pattern analysis")
    print("  (Check if addr + n*0x44 also appears as literals)")
    print("=" * 80)
    print()

    # Consider all high-frequency EWRAM addresses as candidates
    all_candidates = {}
    for addr, refs in sorted_by_freq[:200]:  # Top 200 by frequency
        if addr in KNOWN_ADDRS:
            continue
        # Skip addresses in IWRAM-like range or very low EWRAM
        if addr < 0x02010000:
            continue  # Too low, likely BSS/heap area
        if addr > 0x02030000:
            continue  # Too high

        ref_count = len(refs)

        # Check stride pattern: do addr+0x44, addr+0x88, addr+0xCC also appear?
        stride_matches = 0
        stride_total_refs = 0
        for n in range(1, 10):
            check_addr = addr + n * SPRITE_SIZE
            if check_addr in all_ewram_refs:
                stride_matches += 1
                stride_total_refs += len(all_ewram_refs[check_addr])

        # Also check negative strides (maybe we found a later element)
        neg_stride_matches = 0
        for n in range(1, 10):
            check_addr = addr - n * SPRITE_SIZE
            if check_addr in all_ewram_refs:
                neg_stride_matches += 1

        score = ref_count * 10 + stride_matches * 50 + stride_total_refs * 5

        if stride_matches >= 2 or ref_count >= 50:
            all_candidates[addr] = {
                "refs": ref_count,
                "stride_fwd": stride_matches,
                "stride_rev": neg_stride_matches,
                "stride_refs": stride_total_refs,
                "score": score,
            }

    # Sort by score
    sorted_candidates = sorted(all_candidates.items(), key=lambda x: -x[1]["score"])

    print(f"  {len(sorted_candidates)} candidates found")
    print()
    print(f"  {'Rank':>4}  {'Address':>12}  {'Refs':>5}  {'Fwd':>4}  {'Rev':>4}  {'Score':>6}  Notes")
    print(f"  {'----':>4}  {'-------':>12}  {'----':>5}  {'---':>4}  {'---':>4}  {'-----':>6}  -----")

    for i, (addr, info) in enumerate(sorted_candidates[:30]):
        notes = []
        # Check if the full array fits
        end = addr + FULL_ARRAY_SIZE
        if end < 0x02040000:
            notes.append(f"ends@0x{end:08X}")

        # Check if near the vanilla address
        diff = addr - 0x020200B0
        if abs(diff) < 0x10000:
            notes.append(f"vanilla+0x{diff:04X}" if diff >= 0 else f"vanilla-0x{-diff:04X}")

        # Check if co-located with 0x1100
        if addr in candidates:
            notes.append("NEAR_0x1100")

        note_str = ", ".join(notes) if notes else ""
        print(f"  {i+1:4d}  0x{addr:08X}  {info['refs']:5d}  {info['stride_fwd']:4d}  {info['stride_rev']:4d}  {info['score']:6d}  {note_str}")
    print()

    # =========================================================================
    # STEP 5: Deep analysis of top 5 candidates
    # =========================================================================
    print("=" * 80)
    print("  STEP 5: Deep analysis of top candidates")
    print("=" * 80)
    print()

    for i, (addr, info) in enumerate(sorted_candidates[:5]):
        print(f"  --- Candidate #{i+1}: 0x{addr:08X} ({info['refs']} refs, score={info['score']}) ---")
        print()

        # Show stride analysis
        print(f"    Stride +0x44 pattern:")
        for n in range(0, 12):
            check = addr + n * SPRITE_SIZE
            r = len(all_ewram_refs.get(check, []))
            known = KNOWN_ADDRS.get(check, "")
            bar = "#" * min(r, 40)
            if r > 0 or n == 0:
                print(f"      [{n:2d}] 0x{check:08X}: {r:3d} refs {bar} {known}")

        # Show what variables are at addr + FULL_ARRAY_SIZE (should be sSpriteOrder etc.)
        end = addr + FULL_ARRAY_SIZE
        print(f"    After array end (0x{end:08X}):")
        for delta in range(0, 256, 4):
            check = end + delta
            if check in all_ewram_refs:
                r = len(all_ewram_refs[check])
                known = KNOWN_ADDRS.get(check, "")
                print(f"      +0x{FULL_ARRAY_SIZE + delta:04X}: 0x{check:08X} ({r} refs) {known}")

        # Show some LDR instructions that reference this address
        refs = all_ewram_refs.get(addr, [])
        print(f"    First 5 ROM references:")
        for ref_off in refs[:5]:
            func_start = find_function_start(rom_data, ref_off)
            func_str = f"func@0x{ROM_BASE + func_start + 1:08X}" if func_start else "?"
            print(f"      ROM+0x{ref_off:06X} ({func_str})")
            # Show surrounding literals
            nearby_ewram = []
            for delta in range(-32, 36, 4):
                pos = ref_off + delta
                if 0 <= pos < len(rom_data) - 3:
                    val = read_u32_le(rom_data, pos)
                    if 0x02000000 <= val < 0x02040000 and val != addr:
                        known = KNOWN_ADDRS.get(val, "")
                        nearby_ewram.append(f"0x{val:08X}{' ('+known+')' if known else ''}")
                    elif val == COPY_SIZE or val == FULL_ARRAY_SIZE:
                        nearby_ewram.append(f"0x{val:04X} (SIZE!)")
            if nearby_ewram:
                print(f"        Nearby literals: {', '.join(nearby_ewram[:8])}")
        print()

    # =========================================================================
    # STEP 6: Look for AnimateSprites pattern
    # =========================================================================
    print("=" * 80)
    print("  STEP 6: AnimateSprites / BuildOamBuffer pattern search")
    print("  (These functions iterate gSprites[0..63] with stride 0x44)")
    print("=" * 80)
    print()

    # AnimateSprites loops through gSprites calling sprite->callback
    # The compiler typically generates:
    #   LDR Rx, =gSprites
    #   loop: LDR Ry, [Rx, #0x1C]  (callback offset)
    #         BLX Ry
    #         ADDS Rx, #0x44
    #         CMP ...
    # Look for ADD #0x44 instructions near EWRAM literal pool refs

    # In THUMB, ADD Rd, #imm8 is 0x30xx-0x37xx where xx = imm8
    # 0x44 = 68, so ADD R0, #0x44 = 0x3044, ADD R1, #0x44 = 0x3144, etc.
    # Also ADDS Rd, Rd, #0x44 won't exist (too big for 3-bit imm)
    # The compiler may use ADD Rd, #0x44 (THUMB encoding)

    add_44_positions = []
    for pos in range(0, len(rom_data) - 1, 2):
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in (0x3000, 0x3100, 0x3200, 0x3300, 0x3400, 0x3500, 0x3600, 0x3700):
            imm = instr & 0xFF
            if imm == SPRITE_SIZE:
                add_44_positions.append(pos)

    print(f"  Found {len(add_44_positions)} ADD Rx, #0x44 instructions in ROM")
    print()

    # For each ADD #0x44, look backward for an LDR =EWRAM_addr
    sprite_loop_candidates = defaultdict(int)

    for add_pos in add_44_positions:
        # Search backward for LDR Rx, [PC, #imm] that loads an EWRAM address
        for back in range(2, 128, 2):
            ldr_pos = add_pos - back
            if ldr_pos < 0:
                break
            instr = read_u16_le(rom_data, ldr_pos)
            if (instr & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
                imm = (instr & 0xFF) * 4
                pc = (ldr_pos + 4) & ~3
                lit_off = pc + imm
                if lit_off < len(rom_data) - 3:
                    lit_val = read_u32_le(rom_data, lit_off)
                    if 0x02010000 <= lit_val < 0x02030000:
                        ref_count = len(all_ewram_refs.get(lit_val, []))
                        if ref_count >= 10:
                            sprite_loop_candidates[lit_val] += 1

    # Sort and show
    sorted_loop = sorted(sprite_loop_candidates.items(), key=lambda x: -x[1])
    print(f"  EWRAM addresses found near ADD #0x44 loops:")
    print(f"  {'Address':>12}  {'Loop Hits':>9}  {'Total Refs':>10}  {'Known'}")
    for addr, hits in sorted_loop[:20]:
        ref_count = len(all_ewram_refs.get(addr, []))
        known = KNOWN_ADDRS.get(addr, "")
        print(f"  0x{addr:08X}  {hits:9d}  {ref_count:10d}  {known}")
    print()

    # =========================================================================
    # STEP 7: Cross-reference — best candidate summary
    # =========================================================================
    print("=" * 80)
    print("  STEP 7: FINAL VERDICT — Best gSprites candidates")
    print("=" * 80)
    print()

    # Combine all evidence
    final_scores = defaultdict(lambda: {"freq": 0, "stride": 0, "loop": 0, "size": 0, "total": 0})

    # Frequency score
    for addr, refs in all_ewram_refs.items():
        if 0x02010000 <= addr < 0x02030000:
            count = len(refs)
            if count >= 30:
                final_scores[addr]["freq"] = count

    # Stride score
    for addr in list(final_scores.keys()):
        stride_count = 0
        for n in range(1, 20):
            if (addr + n * SPRITE_SIZE) in all_ewram_refs:
                stride_count += 1
        final_scores[addr]["stride"] = stride_count

    # Loop pattern score
    for addr, hits in sprite_loop_candidates.items():
        if addr in final_scores:
            final_scores[addr]["loop"] = hits

    # Size constant proximity score
    for addr in candidates:
        if addr in final_scores:
            final_scores[addr]["size"] = 1

    # Calculate total score
    for addr in final_scores:
        s = final_scores[addr]
        s["total"] = s["freq"] * 2 + s["stride"] * 100 + s["loop"] * 200 + s["size"] * 500

    # Sort and show top results
    final_sorted = sorted(final_scores.items(), key=lambda x: -x[1]["total"])

    # Filter to only show real candidates
    final_filtered = [(a, s) for a, s in final_sorted
                      if s["total"] > 500 and a not in KNOWN_ADDRS and s["stride"] >= 3]

    print(f"  {'Rank':>4}  {'Address':>12}  {'FreqRefs':>8}  {'Stride+44':>9}  {'LoopHits':>8}  {'NearSize':>8}  {'Score':>7}  {'Known'}")
    print(f"  {'----':>4}  {'-------':>12}  {'--------':>8}  {'---------':>9}  {'--------':>8}  {'--------':>8}  {'-----':>7}  {'-----'}")

    for i, (addr, s) in enumerate(final_filtered[:15]):
        known = KNOWN_ADDRS.get(addr, "")
        end = addr + FULL_ARRAY_SIZE
        print(f"  {i+1:4d}  0x{addr:08X}  {s['freq']:8d}  {s['stride']:9d}  {s['loop']:8d}  {s['size']:8d}  {s['total']:7d}  {known}")
        if i == 0:
            print(f"        ^^ BEST CANDIDATE: array from 0x{addr:08X} to 0x{end:08X}")
            # Verify it doesn't overlap with known addresses
            overlaps = []
            for kaddr, kname in KNOWN_ADDRS.items():
                if addr <= kaddr < end:
                    overlaps.append(f"{kname}@0x{kaddr:08X}")
            if overlaps:
                print(f"        WARNING: Overlaps with: {', '.join(overlaps)}")
            else:
                print(f"        No overlap with known addresses - GOOD")

    print()

    if final_filtered:
        best = final_filtered[0][0]
        print(f"  *** CONCLUSION: gSprites is most likely at 0x{best:08X} ***")
        print(f"      Array size: 0x{FULL_ARRAY_SIZE:04X} ({FULL_ARRAY_SIZE} bytes)")
        print(f"      Array end:  0x{best + FULL_ARRAY_SIZE:08X}")
        print(f"      Entry size: 0x{SPRITE_SIZE:02X} ({SPRITE_SIZE} bytes)")
        print(f"      Entries:    {MAX_SPRITES + 1} (MAX_SPRITES + 1)")
        diff = best - 0x020200B0
        if diff >= 0:
            print(f"      Offset from vanilla: +0x{diff:04X}")
        else:
            print(f"      Offset from vanilla: -0x{-diff:04X}")
    else:
        print("  No strong candidates found. Manual investigation needed.")

    print()
    print("=" * 80)
    print("  SCAN COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
