#!/usr/bin/env python3
"""
Verify gSprites = 0x02020630 in Pokemon Run & Bun ROM (fast version).

Key evidence from initial scan:
- 1655 ROM literal pool refs (highest of ANY EWRAM address)
- 16 loop hits with ADD #0x44 stride pattern

This version only analyzes functions that reference 0x02020630 (no full ROM scan).
"""

import struct
import sys
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

CANDIDATE = 0x02020630
SPRITE_SIZE = 0x44    # 68 bytes
MAX_SPRITES = 64
FULL_ARRAY_SIZE = (MAX_SPRITES + 1) * SPRITE_SIZE  # 0x1144
COPY_SIZE = MAX_SPRITES * SPRITE_SIZE               # 0x1100
ARRAY_END = CANDIDATE + FULL_ARRAY_SIZE              # 0x02021774

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

def find_function_end(rom_data, start, max_size=4096):
    for pos in range(start + 4, min(start + max_size, len(rom_data) - 1), 2):
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) == 0xBD00:
            return pos + 2
        if instr == 0x4770:
            return pos + 2
    return None

def analyze_function_patterns(rom_data, func_start, func_size):
    """Check for sprite-related patterns in a function."""
    patterns = {
        "add_44": False,
        "cmp_40": False,
        "loads_array_end": False,
        "loads_size": False,
        "has_blx": False,
        "ldr_0x1C": False,   # LDR Rx, [Ry, #0x1C] = callback offset in Sprite struct
        "ldr_0x3E": False,   # offset of inUse/flags bitfield
    }
    loaded_vals = set()

    for pos in range(func_start, func_start + func_size, 2):
        if pos >= len(rom_data) - 1:
            break
        instr = read_u16_le(rom_data, pos)

        # ADD Rd, #0x44
        if (instr & 0xF800) == 0x3000 and (instr & 0xFF) == 0x44:
            patterns["add_44"] = True

        # CMP Rd, #0x40
        if (instr & 0xF800) == 0x2800 and (instr & 0xFF) == 0x40:
            patterns["cmp_40"] = True

        # LDR Rd, [Rn, #0x1C] (callback field)
        if (instr & 0xF800) == 0x6800:  # LDR Rd, [Rn, #imm5*4]
            imm5 = (instr >> 6) & 0x1F
            if imm5 * 4 == 0x1C:
                patterns["ldr_0x1C"] = True

        # LDRH/LDRB near offset 0x3E (flags)
        if (instr & 0xF800) == 0x8800:  # LDRH Rd, [Rn, #imm5*2]
            imm5 = (instr >> 6) & 0x1F
            if imm5 * 2 == 0x3E:
                patterns["ldr_0x3E"] = True

        # LDR Rd, [PC, #imm] — check literal pool values
        if (instr & 0xF800) == 0x4800:
            imm = (instr & 0xFF) * 4
            pc = (pos + 4) & ~3
            lit_off = pc + imm
            if lit_off < len(rom_data) - 3:
                lit_val = read_u32_le(rom_data, lit_off)
                loaded_vals.add(lit_val)

        # BLX Rx
        if (instr & 0xFF87) == 0x4780:
            patterns["has_blx"] = True

    if ARRAY_END in loaded_vals:
        patterns["loads_array_end"] = True
    if COPY_SIZE in loaded_vals or FULL_ARRAY_SIZE in loaded_vals:
        patterns["loads_size"] = True

    patterns["loaded_vals"] = loaded_vals
    return patterns


def disasm_function_str(rom_data, func_start, max_size=512):
    """Return disassembly as string."""
    lines = []
    pos = func_start
    end = min(func_start + max_size, len(rom_data) - 1)

    while pos < end:
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        desc = f"  0x{rom_addr:08X}: {instr:04X}"

        # LDR Rd, [PC, #imm]
        if (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            pc = (pos + 4) & ~3
            lit_off = pc + imm
            if lit_off < len(rom_data) - 3:
                lit_val = read_u32_le(rom_data, lit_off)
                known_name = KNOWN.get(lit_val, "")
                extra = ""
                if lit_val == CANDIDATE:
                    extra = " *** gSprites ***"
                elif lit_val == ARRAY_END:
                    extra = " *** ARRAY_END ***"
                elif lit_val == COPY_SIZE:
                    extra = " *** COPY_SIZE ***"
                elif lit_val == FULL_ARRAY_SIZE:
                    extra = " *** FULL_SIZE ***"
                elif known_name:
                    extra = f" ({known_name})"
                desc += f"  LDR R{rd}, =0x{lit_val:08X}{extra}"

        elif (instr & 0xF800) == 0x3000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  ADD R{rd}, #0x{imm:X}"
            if imm == 0x44:
                desc += " *** +SPRITE_SIZE ***"

        elif (instr & 0xF800) == 0x3800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  SUB R{rd}, #0x{imm:X}"

        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  MOV R{rd}, #0x{imm:X}"

        elif (instr & 0xF800) == 0x2800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  CMP R{rd}, #0x{imm:X}"
            if imm == 0x40:
                desc += " *** MAX_SPRITES ***"

        elif (instr & 0xFF00) in (0xB400, 0xB500):
            regs = [f"R{b}" for b in range(8) if instr & (1 << b)]
            if instr & 0x0100:
                regs.append("LR")
            desc += f"  PUSH {{{', '.join(regs)}}}"

        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = [f"R{b}" for b in range(8) if instr & (1 << b)]
            if instr & 0x0100:
                regs.append("PC")
            desc += f"  POP {{{', '.join(regs)}}}"
            if instr & 0x0100:
                lines.append(desc)
                break

        elif instr == 0x4770:
            desc += "  BX LR"
            lines.append(desc)
            break

        elif (instr & 0xFF87) == 0x4780:
            rd = (instr >> 3) & 0xF
            desc += f"  BLX R{rd}"

        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm5 = (instr >> 6) & 0x1F
            desc += f"  LDR R{rd}, [R{rn}, #0x{imm5*4:X}]"
            if imm5 * 4 == 0x1C:
                desc += " *** callback ***"

        elif (instr & 0xF800) == 0x8800:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm5 = (instr >> 6) & 0x1F
            desc += f"  LDRH R{rd}, [R{rn}, #0x{imm5*2:X}]"
            if imm5 * 2 == 0x3E:
                desc += " *** inUse/flags ***"

        # BL pair
        if pos + 2 < end:
            next_instr = read_u16_le(rom_data, pos + 2)
            if (instr & 0xF800) == 0xF000 and (next_instr & 0xF800) == 0xF800:
                off11hi = instr & 0x07FF
                off11lo = next_instr & 0x07FF
                full_off = (off11hi << 12) | (off11lo << 1)
                if full_off >= 0x400000:
                    full_off -= 0x800000
                target = ROM_BASE + pos + 4 + full_off
                desc = f"  0x{rom_addr:08X}: {instr:04X} {next_instr:04X}  BL 0x{target:08X}"
                lines.append(desc)
                pos += 4
                continue

        lines.append(desc)
        pos += 2

    return "\n".join(lines)


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
    # CHECK 1: Overlap validation
    # =========================================================================
    print("=" * 80)
    print("  CHECK 1: Overlap validation")
    print("=" * 80)
    overlaps = [(a, n) for a, n in KNOWN.items() if CANDIDATE <= a < ARRAY_END]
    if overlaps:
        print(f"  FAIL: Overlaps {len(overlaps)} known variables")
        for a, n in overlaps:
            print(f"    0x{a:08X}: {n}")
    else:
        print(f"  PASS: No overlap in 0x{CANDIDATE:08X}-0x{ARRAY_END:08X}")
    print()

    # =========================================================================
    # CHECK 2: Reference counts
    # =========================================================================
    print("=" * 80)
    print("  CHECK 2: Reference counts")
    print("=" * 80)
    main_refs = find_all_refs(rom_data, CANDIDATE)
    end_refs = find_all_refs(rom_data, ARRAY_END)
    print(f"  gSprites base (0x{CANDIDATE:08X}): {len(main_refs)} refs")
    print(f"  Array end     (0x{ARRAY_END:08X}): {len(end_refs)} refs")

    # Check related size constants
    size_1100_refs = find_all_refs(rom_data, COPY_SIZE)
    size_1144_refs = find_all_refs(rom_data, FULL_ARRAY_SIZE)
    print(f"  0x{COPY_SIZE:04X} literal refs: {len(size_1100_refs)}")
    print(f"  0x{FULL_ARRAY_SIZE:04X} literal refs: {len(size_1144_refs)}")

    # Check co-location
    for sr in size_1100_refs:
        func = find_function_start(rom_data, sr)
        for mr in main_refs:
            if func and abs(mr - sr) < 512:
                print(f"  ** 0x{COPY_SIZE:04X} co-located with gSprites at ROM+0x{sr:06X} (func 0x{ROM_BASE+func+1:08X})")
                break
    print()

    # =========================================================================
    # CHECK 3: Adjacent variable analysis
    # =========================================================================
    print("=" * 80)
    print("  CHECK 3: Adjacent EWRAM variables after array end")
    print("=" * 80)
    print()

    # In the expansion source, after gSprites:
    # sSpriteOrder[64], sShouldProcessSpriteCopyRequests, sSpriteCopyRequestCount,
    # sSpriteCopyRequests[64], gOamLimit, sOamDummyIndex, gReservedSpriteTileCount,
    # sSpriteTileAllocBitmap[128], gSpriteCoordOffsetX, gSpriteCoordOffsetY,
    # gOamMatrices[32], gAffineAnimsDisabled

    # Scan all EWRAM refs in the range right after the array
    for offset in range(0, 0x500, 2):
        addr = ARRAY_END + offset
        refs = find_all_refs(rom_data, addr)
        if len(refs) >= 2:
            print(f"    gSprites+0x{FULL_ARRAY_SIZE+offset:04X} = 0x{addr:08X}: {len(refs):3d} refs")
    print()

    # =========================================================================
    # CHECK 4: Function analysis — find sprite loop functions
    # =========================================================================
    print("=" * 80)
    print("  CHECK 4: Classify functions referencing gSprites")
    print("=" * 80)
    print()

    # Group refs by function
    func_refs = {}
    for ref_off in main_refs:
        func = find_function_start(rom_data, ref_off)
        if func:
            if func not in func_refs:
                func_refs[func] = []
            func_refs[func].append(ref_off)

    print(f"  {len(func_refs)} unique functions reference gSprites")
    print()

    # Analyze each function for patterns
    sprite_loop_funcs = []
    callback_funcs = []
    all_func_info = []

    for func_start in sorted(func_refs.keys()):
        func_end = find_function_end(rom_data, func_start)
        func_size = (func_end - func_start) if func_end else 512
        func_size = min(func_size, 4096)

        pat = analyze_function_patterns(rom_data, func_start, func_size)
        func_addr = ROM_BASE + func_start + 1

        tags = []
        if pat["add_44"] and pat["cmp_40"]:
            tags.append("SPRITE_LOOP")
            sprite_loop_funcs.append(func_start)
        elif pat["add_44"]:
            tags.append("ADD#44")
        if pat["ldr_0x1C"] and pat["has_blx"]:
            tags.append("CALLBACK_CALL")
            callback_funcs.append(func_start)
        if pat["loads_array_end"]:
            tags.append("LOADS_END")
        if pat["loads_size"]:
            tags.append("LOADS_SIZE")
        if pat["ldr_0x3E"]:
            tags.append("CHECKS_FLAGS")

        known_refs = [KNOWN[v] for v in pat["loaded_vals"] if v in KNOWN]

        info = {
            "addr": func_addr,
            "size": func_size,
            "tags": tags,
            "known_refs": known_refs,
            "start": func_start,
        }
        all_func_info.append(info)

        tag_str = " ".join(f"[{t}]" for t in tags)
        known_str = f" refs: {','.join(known_refs)}" if known_refs else ""
        if tags:
            print(f"    0x{func_addr:08X} ({func_size:4d}B) {tag_str}{known_str}")

    print()

    # =========================================================================
    # CHECK 5: Disassemble key functions
    # =========================================================================
    print("=" * 80)
    print("  CHECK 5: Disassemble SPRITE_LOOP and CALLBACK_CALL functions")
    print("=" * 80)
    print()

    key_funcs = sorted(set(sprite_loop_funcs + callback_funcs))

    for func_start in key_funcs[:6]:
        func_end = find_function_end(rom_data, func_start)
        func_size = min((func_end - func_start) if func_end else 512, 512)
        func_addr = ROM_BASE + func_start + 1
        print(f"  === Function 0x{func_addr:08X} ({func_size} bytes) ===")
        print(disasm_function_str(rom_data, func_start, func_size))
        print()

    # =========================================================================
    # CHECK 6: Cross-reference with gSpriteCoordOffsetX/Y
    # =========================================================================
    print("=" * 80)
    print("  CHECK 6: gSpriteCoordOffsetX/Y cross-reference")
    print("=" * 80)
    print()

    # Config says these are at IWRAM 0x03005DFC and 0x03005DF8
    # But in expansion source, they're EWRAM_DATA, declared right after gSprites-related vars
    # If gSprites = 0x02020630, then after the sprite system vars we'd expect to find
    # gSpriteCoordOffsetX/Y

    # Expected layout from source:
    # gSprites:        0x02020630 (0x1144 bytes)
    # sSpriteOrder:    +0x1144 = 0x02021774 (0x40 bytes)
    # sShouldProc:     +0x1184 = 0x020217B4 (1 byte + padding)
    # sSpriteCopyReqCount: +0x1185 (1 byte)
    # sSpriteCopyRequests: +0x1188 (0x200 bytes, aligned)  (each is src(4)+dest(4)+size(2)+pad(2) = 12? No, src*+dest*+size(2) = 10, padded to 8 = src(4)+dest(4) =8? )
    # Actually SpriteCopyRequest is { const u8 *src; u8 *dest; u16 size; } = 4+4+2 = 10 bytes, padded to 12
    # 64 * 12 = 768 = 0x300
    # Wait, let me recalculate. On ARM, struct padding: ptr(4) + ptr(4) + u16(2) = 10, but aligned to 4 = 12
    # Actually no, with ARM EABI, the struct would be: ptr(4) + ptr(4) + u16(2) + pad(2) = 12 bytes
    # 64 * 12 = 768 = 0x300

    # Actually: { const u8 *src; u8 *dest; u16 size; } -> 4 + 4 + 2 = 10, struct size = 12 (align to 4)
    # Hmm, actually struct packing on GBA (ARM7TDMI) with -mthumb: might be 10 or 12.
    # Let's check both possibilities.

    # gOamLimit at some offset
    # gReservedSpriteTileCount
    # sSpriteTileAllocBitmap[128]
    # gSpriteCoordOffsetX (s16)
    # gSpriteCoordOffsetY (s16)

    # The total offset from gSprites to gSpriteCoordOffsetX depends on exact struct packing
    # But we can try to find it by looking at what addresses are loaded by functions that
    # also load gSprites AND have the pattern of storing 0 (ResetSpriteData stores 0 to both)

    # Let's find functions that load gSprites AND store 0 to nearby EWRAM addresses
    print("  Looking for ResetSpriteData pattern (loads gSprites + stores 0 to coord offsets)...")
    print()

    for fi in all_func_info:
        if "SPRITE_LOOP" in fi["tags"] or "LOADS_END" in fi["tags"] or "LOADS_SIZE" in fi["tags"]:
            continue  # Skip, looking for init/reset functions

    # Actually, let's just search for references to addresses at expected CoordOffset positions
    # Expected: gSprites base + ~0x1400 to +0x1500 range for gSpriteCoordOffsetX/Y
    print("  Scanning for potential gSpriteCoordOffsetX/Y (EWRAM, near gSprites end):")
    for offset in range(0x1144, 0x1600, 2):
        addr = CANDIDATE + offset
        refs = find_all_refs(rom_data, addr)
        if len(refs) >= 10:
            # Check if any function also references gSprites
            shared_funcs = 0
            for ref in refs[:20]:
                func = find_function_start(rom_data, ref)
                if func and func in func_refs:
                    shared_funcs += 1
            if shared_funcs > 0:
                print(f"    gSprites+0x{offset:04X} = 0x{addr:08X}: {len(refs)} refs, {shared_funcs} shared funcs with gSprites")
    print()

    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    print("=" * 80)
    print("  FINAL SUMMARY")
    print("=" * 80)
    print()
    print(f"  Candidate: gSprites = 0x{CANDIDATE:08X}")
    print(f"  Total ROM refs: {len(main_refs)}")
    print(f"  Array end refs: {len(end_refs)}")
    print(f"  Overlap with known: {'YES' if overlaps else 'NO'}")
    print(f"  SPRITE_LOOP functions: {len(sprite_loop_funcs)}")
    print(f"  CALLBACK_CALL functions: {len(callback_funcs)}")
    print()

    # Identify AnimateSprites: has SPRITE_LOOP + CALLBACK_CALL + CMP #0x40
    for func_start in sprite_loop_funcs:
        if func_start in callback_funcs:
            func_addr = ROM_BASE + func_start + 1
            print(f"  *** LIKELY AnimateSprites: 0x{func_addr:08X} ***")

    print()


if __name__ == "__main__":
    main()
