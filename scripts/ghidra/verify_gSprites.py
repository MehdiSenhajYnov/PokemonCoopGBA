#!/usr/bin/env python3
"""
Verify gSprites candidate at 0x02020630 in Pokemon Run & Bun ROM.

Evidence:
- 1655 ROM literal pool refs (highest of ANY EWRAM address)
- 16 loop hits near ADD Rx, #0x44 (stride iteration pattern)
- AnimateSprites / BuildOamBuffer iterate gSprites[0..63] with stride 0x44

This script:
1. Analyzes ALL functions that reference 0x02020630
2. Checks for the CopyToSprites/CopyFromSprites pattern (addr + 0x1100)
3. Checks array end (0x02020630 + 0x1144 = 0x02021774) refs
4. Finds ResetSpriteData pattern
5. Validates that gSprites + 0x1144 doesn't overlap known vars
6. Checks the ADD #0x44 loops in detail
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

CANDIDATE = 0x02020630
SPRITE_SIZE = 0x44
MAX_SPRITES = 64
FULL_ARRAY_SIZE = (MAX_SPRITES + 1) * SPRITE_SIZE  # 0x1144
COPY_SIZE = MAX_SPRITES * SPRITE_SIZE               # 0x1100
ARRAY_END = CANDIDATE + FULL_ARRAY_SIZE              # 0x02021774

# Known addresses
KNOWN = {
    0x02024CBC: "playerX",
    0x02024CBE: "playerY",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x020233DC: "gActiveBattler",
    0x020233E0: "gBattleControllerExecFlags",
    0x02023364: "gBattleTypeFlags",
    0x02023A18: "gBattleResources",
    0x020233FC: "gBattleMons",
    0x0202370E: "gBattleCommunication",
    0x020233E4: "gBattlersCount",
    0x020226C4: "gBlockRecvBuffer",
    0x020229E8: "gLinkPlayers",
    0x02028848: "gPokemonStorage",
    0x020318A8: "sWarpDestination",
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

def find_function_start(rom_data, offset, max_back=4096):
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in (0xB400, 0xB500):
            return pos
    return None

def find_function_end(rom_data, start, max_size=8192):
    """Find POP {PC} or BX LR after function start."""
    for pos in range(start + 4, min(start + max_size, len(rom_data) - 1), 2):
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) == 0xBD00:
            return pos + 2
        if instr == 0x4770:
            return pos + 2
    return None

def decode_bl(rom_data, pos):
    """Decode a BL instruction pair at pos. Returns target address or None."""
    if pos + 3 >= len(rom_data):
        return None
    instr1 = read_u16_le(rom_data, pos)
    instr2 = read_u16_le(rom_data, pos + 2)
    if (instr1 & 0xF800) == 0xF000 and (instr2 & 0xF800) == 0xF800:
        off11hi = instr1 & 0x07FF
        off11lo = instr2 & 0x07FF
        full_off = (off11hi << 12) | (off11lo << 1)
        if full_off >= 0x400000:
            full_off -= 0x800000
        bl_pc = ROM_BASE + pos + 4
        return bl_pc + full_off
    return None

def disasm_function(rom_data, func_start, max_size=2048):
    """Disassemble a THUMB function and return info."""
    lines = []
    bl_targets = []
    ldr_literals = []  # (pos, reg, literal_offset, literal_value)

    pos = func_start
    end_limit = min(func_start + max_size, len(rom_data) - 1)
    func_end = None

    while pos < end_limit:
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos

        desc = f"0x{rom_addr:08X}: {instr:04X}"

        # LDR Rd, [PC, #imm]
        if (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            pc = (pos + 4) & ~3
            lit_off = pc + imm
            if lit_off < len(rom_data) - 3:
                lit_val = read_u32_le(rom_data, lit_off)
                desc += f"  LDR R{rd}, =0x{lit_val:08X}"
                ldr_literals.append((pos, rd, lit_off, lit_val))
            else:
                desc += f"  LDR R{rd}, [PC, #0x{imm:X}]"

        # ADD Rd, #imm8
        elif (instr & 0xF800) == 0x3000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  ADD R{rd}, #0x{imm:X}"
            if imm == SPRITE_SIZE:
                desc += " <<<< SPRITE STRIDE!"

        # SUB Rd, #imm8
        elif (instr & 0xF800) == 0x3800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  SUB R{rd}, #0x{imm:X}"

        # MOV Rd, #imm8
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  MOV R{rd}, #0x{imm:X}"

        # CMP Rd, #imm8
        elif (instr & 0xF800) == 0x2800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  CMP R{rd}, #0x{imm:X}"
            if imm == MAX_SPRITES:
                desc += " <<<< MAX_SPRITES!"

        # PUSH
        elif (instr & 0xFF00) in (0xB400, 0xB500):
            regs = []
            for bit in range(8):
                if instr & (1 << bit):
                    regs.append(f"R{bit}")
            if instr & 0x0100:
                regs.append("LR")
            desc += f"  PUSH {{{', '.join(regs)}}}"

        # POP
        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = []
            for bit in range(8):
                if instr & (1 << bit):
                    regs.append(f"R{bit}")
            if instr & 0x0100:
                regs.append("PC")
            desc += f"  POP {{{', '.join(regs)}}}"
            if instr & 0x0100:  # POP {PC}
                func_end = pos + 2
                lines.append(desc)
                break

        # BX LR
        elif instr == 0x4770:
            desc += "  BX LR"
            func_end = pos + 2
            lines.append(desc)
            break

        # BL pair
        elif pos + 2 < end_limit:
            target = decode_bl(rom_data, pos)
            if target is not None:
                desc += f"  BL 0x{target:08X}"
                bl_targets.append(target)
                lines.append(desc)
                pos += 4
                continue

        lines.append(desc)
        pos += 2

    return lines, bl_targets, ldr_literals, func_end


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print(f"Candidate: gSprites = 0x{CANDIDATE:08X}")
    print(f"Array end: 0x{ARRAY_END:08X} (0x{FULL_ARRAY_SIZE:04X} bytes)")
    print()

    # =========================================================================
    # CHECK 1: Overlap with known addresses
    # =========================================================================
    print("=" * 80)
    print("  CHECK 1: Overlap validation")
    print("=" * 80)
    print()

    overlaps = []
    for addr, name in sorted(KNOWN.items()):
        if CANDIDATE <= addr < ARRAY_END:
            overlaps.append((addr, name))

    if overlaps:
        print(f"  WARNING: Array would overlap with {len(overlaps)} known vars:")
        for addr, name in overlaps:
            print(f"    0x{addr:08X}: {name}")
    else:
        print(f"  PASS: No overlap with known addresses in range 0x{CANDIDATE:08X}-0x{ARRAY_END:08X}")
    print()

    # =========================================================================
    # CHECK 2: Reference count analysis
    # =========================================================================
    print("=" * 80)
    print("  CHECK 2: References to candidate and related addresses")
    print("=" * 80)
    print()

    main_refs = find_all_refs(rom_data, CANDIDATE)
    print(f"  0x{CANDIDATE:08X} (gSprites base): {len(main_refs)} refs")

    end_refs = find_all_refs(rom_data, ARRAY_END)
    print(f"  0x{ARRAY_END:08X} (array end):     {len(end_refs)} refs")

    # Check for size constant 0x1100 near our candidate
    size_1100_refs = find_all_refs(rom_data, COPY_SIZE)
    colocated = 0
    for sr in size_1100_refs:
        for mr in main_refs:
            if abs(sr - mr) < 256:
                colocated += 1
                break
    print(f"  0x{COPY_SIZE:04X} (copy size) co-located with candidate: {colocated} times")

    size_1144_refs = find_all_refs(rom_data, FULL_ARRAY_SIZE)
    colocated2 = 0
    for sr in size_1144_refs:
        for mr in main_refs:
            if abs(sr - mr) < 256:
                colocated2 += 1
                break
    print(f"  0x{FULL_ARRAY_SIZE:04X} (full size) co-located with candidate: {colocated2} times")
    print()

    # Check adjacent EWRAM variables that should follow gSprites
    # In expansion source order:
    # gSprites[65]   = 0x1144 bytes
    # sSpriteOrder[64] = 64 bytes = 0x40
    # sShouldProcessSpriteCopyRequests = 1 byte
    # sSpriteCopyRequestCount = 1 byte
    # sSpriteCopyRequests[64] = 64 * sizeof(SpriteCopyRequest) = 64 * 8 = 512 = 0x200
    # gOamLimit = 1 byte
    # sOamDummyIndex = 1 byte
    # gReservedSpriteTileCount = 2 bytes
    # sSpriteTileAllocBitmap[128] = 128 bytes = 0x80
    # gSpriteCoordOffsetX = 2 bytes
    # gSpriteCoordOffsetY = 2 bytes
    # gOamMatrices[32] = 32 * 8 = 256 = 0x100
    # gAffineAnimsDisabled = 1 byte

    print("  Adjacent variable analysis (after array end 0x{:08X}):".format(ARRAY_END))
    expected_offsets = [
        (0x0000, 0x40,  "sSpriteOrder[64]"),
        (0x0040, 0x01,  "sShouldProcessSpriteCopyRequests"),
        (0x0041, 0x01,  "sSpriteCopyRequestCount"),
        (0x0044, 0x200, "sSpriteCopyRequests[64]"),  # May have alignment padding
        (0x0244, 0x01,  "gOamLimit"),
        (0x0245, 0x01,  "sOamDummyIndex"),
        (0x0246, 0x02,  "gReservedSpriteTileCount"),
        (0x0248, 0x80,  "sSpriteTileAllocBitmap[128]"),
        (0x02C8, 0x02,  "gSpriteCoordOffsetX"),
        (0x02CA, 0x02,  "gSpriteCoordOffsetY"),
        (0x02CC, 0x100, "gOamMatrices[32]"),
        (0x03CC, 0x01,  "gAffineAnimsDisabled"),
    ]

    for off, size, name in expected_offsets:
        addr = ARRAY_END + off
        refs = find_all_refs(rom_data, addr)
        ref_str = f"{len(refs):3d} refs"
        check = ""
        # Check if gSpriteCoordOffsetX/Y match IWRAM addresses in config
        if "CoordOffsetX" in name:
            check = " (config says IWRAM 0x03005DFC)"
        elif "CoordOffsetY" in name:
            check = " (config says IWRAM 0x03005DF8)"
        print(f"    +0x{FULL_ARRAY_SIZE + off:04X}: 0x{addr:08X} ({ref_str}) -> {name}{check}")
    print()

    # =========================================================================
    # CHECK 3: Analyze functions with ADD #0x44 loops referencing candidate
    # =========================================================================
    print("=" * 80)
    print("  CHECK 3: Functions with ADD #0x44 loops near candidate reference")
    print("=" * 80)
    print()

    # Find ADD Rx, #0x44 instructions
    add_44_positions = []
    for pos in range(0, len(rom_data) - 1, 2):
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in range(0x3000, 0x3800, 0x100):
            imm = instr & 0xFF
            if imm == SPRITE_SIZE:
                add_44_positions.append(pos)

    # Find functions containing both a reference to candidate AND ADD #0x44
    loop_functions = set()
    for add_pos in add_44_positions:
        # Check if there's a literal pool ref to candidate within 256 bytes
        for ref_off in main_refs:
            # The literal pool entry should be within the function's range
            func_start = find_function_start(rom_data, add_pos)
            if func_start and abs(ref_off - add_pos) < 512:
                loop_functions.add(func_start)

    print(f"  Found {len(loop_functions)} functions with both gSprites ref AND ADD #0x44")
    print()

    for func_start in sorted(loop_functions)[:10]:
        func_addr = ROM_BASE + func_start + 1
        print(f"  Function 0x{func_addr:08X}:")
        lines, bl_targets, ldr_literals, func_end = disasm_function(rom_data, func_start, 512)

        # Only show relevant portions (near the candidate literal and ADD #0x44)
        relevant_lines = []
        for i, line in enumerate(lines):
            if f"0x{CANDIDATE:08X}" in line or "SPRITE STRIDE" in line or "MAX_SPRITES" in line:
                # Show context
                start_idx = max(0, i - 3)
                end_idx = min(len(lines), i + 4)
                for j in range(start_idx, end_idx):
                    if j not in [idx for idx, _ in relevant_lines]:
                        relevant_lines.append((j, lines[j]))

        for idx, line in sorted(set(relevant_lines)):
            print(f"    {line}")

        # Show all BL targets
        if bl_targets:
            print(f"    BL targets: {', '.join(f'0x{t:08X}' for t in bl_targets[:5])}")

        func_size = (func_end - func_start) if func_end else "?"
        print(f"    Size: {func_size} bytes")
        print()

    # =========================================================================
    # CHECK 4: Look for AnimateSprites specifically
    # =========================================================================
    print("=" * 80)
    print("  CHECK 4: Identify AnimateSprites / BuildOamBuffer / ResetSpriteData")
    print("=" * 80)
    print()

    # AnimateSprites: loops gSprites[0..63], calls sprite->callback (offset +0x1C in struct)
    # Pattern: LDR Rx, =gSprites; loop: LDR Ry, [Rx, #0x1C]; BLX Ry; ADD Rx, #0x44; CMP ..., #0x40

    # BuildOamBuffer: similar loop, but does AddSpriteToOamBuffer calls

    # ResetSpriteData: calls ResetOamRange, ResetAllSprites, etc.
    # Has LDR for gSpriteCoordOffsetX/Y and stores 0 to them

    # Let's look at the first few functions that reference candidate
    print("  First 15 functions referencing 0x{:08X}:".format(CANDIDATE))
    seen_funcs = {}
    for ref_off in main_refs:
        func_start = find_function_start(rom_data, ref_off)
        if func_start and func_start not in seen_funcs:
            func_end = find_function_end(rom_data, func_start)
            func_size = (func_end - func_start) if func_end else None
            seen_funcs[func_start] = func_size

    for func_start, func_size in sorted(seen_funcs.items())[:15]:
        func_addr = ROM_BASE + func_start + 1
        _, bl_targets, ldr_literals, _ = disasm_function(rom_data, func_start, min(func_size or 1024, 1024))

        # Check for key patterns
        has_add44 = False
        has_cmp40 = False
        has_callback_load = False
        loaded_vals = set()

        for _, _, _, lit_val in ldr_literals:
            loaded_vals.add(lit_val)

        for pos in range(func_start, func_start + (func_size or 512), 2):
            if pos >= len(rom_data) - 1:
                break
            instr = read_u16_le(rom_data, pos)
            if (instr & 0xFF00) in range(0x3000, 0x3800, 0x100) and (instr & 0xFF) == 0x44:
                has_add44 = True
            if (instr & 0xFF00) in range(0x2800, 0x3000, 0x100) and (instr & 0xFF) == 0x40:
                has_cmp40 = True

        tags = []
        if has_add44:
            tags.append("ADD#44")
        if has_cmp40:
            tags.append("CMP#40")
        if has_add44 and has_cmp40:
            tags.append("<<< SPRITE_LOOP")
        if ARRAY_END in loaded_vals:
            tags.append("LOADS_ARRAY_END")
        if COPY_SIZE in loaded_vals or FULL_ARRAY_SIZE in loaded_vals:
            tags.append("LOADS_SIZE")

        # Check for known addresses in literal pool
        known_in_lit = []
        for _, _, _, lit_val in ldr_literals:
            for kaddr, kname in KNOWN.items():
                if lit_val == kaddr:
                    known_in_lit.append(kname)

        tags_str = " ".join(f"[{t}]" for t in tags)
        known_str = f" (also refs: {', '.join(known_in_lit)})" if known_in_lit else ""
        print(f"    0x{func_addr:08X} ({func_size or '?':>4} bytes, {len(bl_targets):2d} BLs) {tags_str}{known_str}")
    print()

    # =========================================================================
    # CHECK 5: Full disassembly of the most likely AnimateSprites
    # =========================================================================
    print("=" * 80)
    print("  CHECK 5: Full disassembly of functions with SPRITE_LOOP pattern")
    print("=" * 80)
    print()

    for func_start, func_size in sorted(seen_funcs.items()):
        if func_size is None or func_size > 1024:
            continue

        has_add44 = False
        has_cmp40 = False
        for pos in range(func_start, func_start + func_size, 2):
            if pos >= len(rom_data) - 1:
                break
            instr = read_u16_le(rom_data, pos)
            if (instr & 0xFF00) in range(0x3000, 0x3800, 0x100) and (instr & 0xFF) == 0x44:
                has_add44 = True
            if (instr & 0xFF00) in range(0x2800, 0x3000, 0x100) and (instr & 0xFF) == 0x40:
                has_cmp40 = True

        if has_add44 and has_cmp40:
            func_addr = ROM_BASE + func_start + 1
            print(f"  === Function 0x{func_addr:08X} ({func_size} bytes) ===")
            lines, bl_targets, ldr_literals, _ = disasm_function(rom_data, func_start, func_size + 64)
            for line in lines:
                print(f"    {line}")
            print()


if __name__ == "__main__":
    main()
