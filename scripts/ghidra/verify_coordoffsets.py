#!/usr/bin/env python3
"""
Quick verification: are 0x02021BBC/0x02021BBE the real gSpriteCoordOffsetX/Y?

Cross-reference with IWRAM 0x03005DFC/0x03005DF8 from config.
The sprite.c source has:
  sprite->oam.x = sprite->x + sprite->x2 + sprite->centerToCornerVecX + gSpriteCoordOffsetX;
  sprite->oam.y = sprite->y + sprite->y2 + sprite->centerToCornerVecY + gSpriteCoordOffsetY;

This is inside BuildOamBuffer. Find functions that load both gSprites (0x02020630)
AND either 0x02021BBC or IWRAM 0x03005DFC.
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

def main():
    rom_data = Path(ROM_PATH).read_bytes()
    print(f"ROM: {len(rom_data)} bytes")
    print()

    gSprites = 0x02020630

    # Candidate EWRAM coord offsets
    ewram_X = 0x02021BBC
    ewram_Y = 0x02021BBE

    # Config IWRAM coord offsets
    iwram_X = 0x03005DFC
    iwram_Y = 0x03005DF8

    print("=== Reference counts ===")
    for name, addr in [("EWRAM_X", ewram_X), ("EWRAM_Y", ewram_Y),
                       ("IWRAM_X", iwram_X), ("IWRAM_Y", iwram_Y)]:
        refs = find_all_refs(rom_data, addr)
        print(f"  {name} (0x{addr:08X}): {len(refs)} refs")
    print()

    # Find functions that reference gSprites
    gSprites_refs = find_all_refs(rom_data, gSprites)
    gSprites_funcs = set()
    for ref in gSprites_refs:
        f = find_function_start(rom_data, ref)
        if f:
            gSprites_funcs.add(f)

    # Find functions that reference each coord offset candidate
    for name, addr in [("EWRAM_X", ewram_X), ("EWRAM_Y", ewram_Y),
                       ("IWRAM_X", iwram_X), ("IWRAM_Y", iwram_Y)]:
        refs = find_all_refs(rom_data, addr)
        coord_funcs = set()
        for ref in refs:
            f = find_function_start(rom_data, ref)
            if f:
                coord_funcs.add(f)

        shared = coord_funcs & gSprites_funcs
        print(f"  {name}: {len(coord_funcs)} funcs, {len(shared)} shared with gSprites")
        if shared:
            for f in sorted(shared)[:5]:
                print(f"    0x{ROM_BASE + f + 1:08X}")
    print()

    # Now check if the EWRAM candidates are actually in functions that compute
    # sprite->oam.x = sprite->x + ... + gSpriteCoordOffsetX
    # This would be in BuildOamBuffer or AddSpriteToOamBuffer

    # Let's look at the function at the earliest address that references gSprites
    # and EWRAM_X/Y - this is likely BuildOamBuffer
    ewram_X_refs = find_all_refs(rom_data, ewram_X)
    ewram_X_funcs = set()
    for ref in ewram_X_refs:
        f = find_function_start(rom_data, ref)
        if f:
            ewram_X_funcs.add(f)

    shared_funcs = ewram_X_funcs & gSprites_funcs

    if shared_funcs:
        print("=== Functions loading BOTH gSprites AND EWRAM gSpriteCoordOffsetX ===")
        for func_start in sorted(shared_funcs):
            func_addr = ROM_BASE + func_start + 1

            # Disassemble relevant parts
            print(f"\n  Function 0x{func_addr:08X}:")

            # Find all LDR =literal in the function
            pos = func_start
            end = min(func_start + 2048, len(rom_data) - 1)
            interesting_loads = []

            while pos < end:
                instr = read_u16_le(rom_data, pos)

                # POP PC or BX LR
                if (instr & 0xFF00) == 0xBD00 or instr == 0x4770:
                    break

                if (instr & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
                    rd = (instr >> 8) & 7
                    imm = (instr & 0xFF) * 4
                    pc = (pos + 4) & ~3
                    lit_off = pc + imm
                    if lit_off < len(rom_data) - 3:
                        lit_val = read_u32_le(rom_data, lit_off)
                        if lit_val in (gSprites, ewram_X, ewram_Y, iwram_X, iwram_Y,
                                       0x02021774, 0x02021BC0):
                            addr_name = {
                                gSprites: "gSprites",
                                ewram_X: "gSpriteCoordOffsetX?",
                                ewram_Y: "gSpriteCoordOffsetY?",
                                iwram_X: "IWRAM_CoordOffsetX",
                                iwram_Y: "IWRAM_CoordOffsetY",
                                0x02021774: "gSprites_END",
                                0x02021BC0: "nearby_var",
                            }.get(lit_val, "?")
                            interesting_loads.append(
                                f"    0x{ROM_BASE+pos:08X}: LDR R{rd}, =0x{lit_val:08X} ({addr_name})")

                pos += 2

            for line in interesting_loads:
                print(line)

    # Also check: in the source, gSpriteCoordOffsetX/Y are written to 0 in ResetSpriteData
    # and read in BuildOamBuffer. Let's check if functions that write 0 to EWRAM_X also
    # reference gOamLimit (which is set in ResetSpriteData)

    # gOamLimit should be right after sSpriteCopyRequests
    # From the adjacent var analysis: gSprites+0x1508 = 0x02021B38 (6 refs)
    # That doesn't match expected offset. Let me just show all EWRAM refs in the
    # gSprites end zone to help identify the layout.

    print("\n=== All EWRAM refs near gSprites end ===")
    print(f"  Array end = 0x{gSprites + 0x1144:08X}")
    for offset in range(0x1144, 0x1600, 1):
        addr = gSprites + offset
        refs = find_all_refs(rom_data, addr)
        if refs:
            print(f"  +0x{offset:04X} = 0x{addr:08X}: {len(refs):3d} refs")


if __name__ == "__main__":
    main()
