"""
Part 2: Find where HandleLinkBattleSetup (0x0803240C) is called from,
and verify the existing NOP patch at 0x06F420.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

HANDLE_LINK_BATTLE_SETUP = 0x0803240C


def read_rom(path):
    with open(path, "rb") as f:
        return f.read()


def decode_bl(rom, offset):
    if offset + 4 > len(rom):
        return None
    hi = struct.unpack_from("<H", rom, offset)[0]
    lo = struct.unpack_from("<H", rom, offset + 2)[0]
    if (hi >> 11) != 0x1E:
        return None
    if (lo >> 11) == 0x1F:
        s = (hi >> 10) & 1
        imm10 = hi & 0x3FF
        j1 = (lo >> 13) & 1
        j2 = (lo >> 11) & 1
        imm11 = lo & 0x7FF
        i1 = 1 - (j1 ^ s)
        i2 = 1 - (j2 ^ s)
        imm32 = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
        if s:
            imm32 |= 0xFE000000
            imm32 -= 0x100000000
        pc = 0x08000000 + offset + 4
        return pc + imm32
    return None


def disasm_thumb(rom, start_offset, length):
    end = min(start_offset + length, len(rom))
    off = start_offset
    while off < end:
        hw = struct.unpack_from("<H", rom, off)[0]
        if (hw >> 11) == 0x1E and off + 2 < end:
            target = decode_bl(rom, off)
            if target is not None:
                print(f"  0x{0x08000000+off:08X}: BL 0x{target:08X}")
                off += 4
                continue
        if (hw >> 11) == 0x09:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc_aligned = ((0x08000000 + off + 4) & ~3)
            lit_addr = pc_aligned + imm
            lit_off = lit_addr - 0x08000000
            if 0 <= lit_off < len(rom):
                lit_val = struct.unpack_from("<I", rom, lit_off)[0]
                print(f"  0x{0x08000000+off:08X}: LDR R{rd}, =0x{lit_val:08X}")
            else:
                print(f"  0x{0x08000000+off:08X}: LDR R{rd}, [PC, ...]")
        elif (hw >> 8) in (0xB5, 0xB4):
            regs = hw & 0xFF
            lr = (hw >> 8) & 1
            rlist = [f"R{i}" for i in range(8) if regs & (1 << i)]
            if lr: rlist.append("LR")
            print(f"  0x{0x08000000+off:08X}: PUSH {{{', '.join(rlist)}}}")
        elif (hw >> 8) in (0xBD, 0xBC):
            regs = hw & 0xFF
            pc = (hw >> 8) & 1
            rlist = [f"R{i}" for i in range(8) if regs & (1 << i)]
            if pc: rlist.append("PC")
            print(f"  0x{0x08000000+off:08X}: POP {{{', '.join(rlist)}}}")
        elif hw == 0x4770:
            print(f"  0x{0x08000000+off:08X}: BX LR")
        elif hw == 0x46C0:
            print(f"  0x{0x08000000+off:08X}: NOP")
        else:
            print(f"  0x{0x08000000+off:08X}: 0x{hw:04X}")
        off += 2


def main():
    rom = read_rom(ROM_PATH)
    print(f"ROM loaded: {len(rom)} bytes")

    # Search entire ROM for BL to HandleLinkBattleSetup
    print(f"\nSearching ENTIRE ROM for BL calls to HandleLinkBattleSetup (0x{HANDLE_LINK_BATTLE_SETUP:08X})...")
    callers = []
    for off in range(0, min(len(rom) - 4, 0x02000000), 2):
        hi = struct.unpack_from("<H", rom, off)[0]
        if (hi >> 11) == 0x1E:
            target = decode_bl(rom, off)
            if target and (target & ~1) == (HANDLE_LINK_BATTLE_SETUP & ~1):
                callers.append(off)
                print(f"  BL at 0x{0x08000000+off:08X} -> 0x{target:08X}")

    print(f"\nTotal callers: {len(callers)}")

    # Disassemble context around each caller
    for caller_off in callers:
        print(f"\n--- Context around 0x{0x08000000+caller_off:08X} ---")
        # Find function start (search backward for PUSH)
        func_start = caller_off
        for search_off in range(caller_off - 2, max(0, caller_off - 200), -2):
            hw = struct.unpack_from("<H", rom, search_off)[0]
            if (hw >> 8) in (0xB5, 0xB4):
                func_start = search_off
                break

        print(f"Function starts at ~0x{0x08000000+func_start:08X}")
        disasm_thumb(rom, func_start, caller_off - func_start + 20)

    # Also check what the NOP patch at 0x06F420 actually patches
    print("\n" + "=" * 70)
    print("Verifying NOP patch at 0x06F420")
    print("=" * 70)
    bl_target = decode_bl(rom, 0x06F420)
    if bl_target:
        print(f"BL at 0x06F420 targets: 0x{bl_target:08X}")
        # What function is this?
        # 0x0806F0D4 is right before PlayerBufferRunCommand (0x0806F151)
        # Let's disassemble it
        tgt_off = (bl_target & ~1) - 0x08000000
        print(f"\nDisassembly of target function at 0x{bl_target & ~1:08X}:")
        disasm_thumb(rom, tgt_off, 80)
    else:
        print("No valid BL at 0x06F420")


if __name__ == "__main__":
    main()
