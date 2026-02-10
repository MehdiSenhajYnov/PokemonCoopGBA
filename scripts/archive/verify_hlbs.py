#!/usr/bin/env python3
"""Verify HandleLinkBattleSetup and find the NOP patch location."""
import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_bl(hw1, hw2, pc):
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) in (0xF800, 0xE800):
        offset_hi = hw1 & 0x07FF
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800
        offset_lo = hw2 & 0x07FF
        target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
        return target & 0xFFFFFFFF
    return None

def find_all_bl_to(rom, target_addr, search_start=0, search_end=None):
    if search_end is None:
        search_end = min(len(rom), 0x02000000)
    results = []
    target_clean = target_addr & ~1
    i = search_start
    while i < search_end - 4:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        if (hw1 & 0xF800) == 0xF000:
            hw2 = struct.unpack_from("<H", rom, i + 2)[0]
            if (hw2 & 0xF800) in (0xF800, 0xE800):
                pc = 0x08000000 + i
                bl = decode_bl(hw1, hw2, pc)
                if bl is not None and (bl & ~1) == target_clean:
                    results.append((i, pc))
                i += 4
                continue
        i += 2
    return results

def main():
    rom = read_rom()

    print("=== HandleLinkBattleSetup at 0x0803240C (ROM 0x03240C) ===\n")

    # Find all callers of HandleLinkBattleSetup
    callers = find_all_bl_to(rom, 0x0803240C, 0, 0x02000000)
    print(f"All callers of 0x0803240C ({len(callers)}):")
    for off, pc in callers:
        print(f"  ROM 0x{off:06X} (0x{pc:08X})")

    # Also check callers of 0x0803240D (THUMB)
    callers2 = find_all_bl_to(rom, 0x0803240D, 0, 0x02000000)
    if callers2 and callers2 != callers:
        print(f"\nAlso callers of 0x0803240D ({len(callers2)}):")
        for off, pc in callers2:
            print(f"  ROM 0x{off:06X} (0x{pc:08X})")

    print()

    # Now: the BL at +0x088 in the second match region calls 0x0803240C
    # That means there's a function at approximately 0x032494 (0x03240C + 0x88) area
    # This function is SetUpBattleVarsAndBirchZigzagoon

    # Let's find SetUpBattleVarsAndBirchZigzagoon
    # From decomp, it calls HandleLinkBattleSetup. Any function that BL's to 0x0803240C
    # is likely SetUpBattleVarsAndBirchZigzagoon.

    for off, pc in callers:
        # Find function start (PUSH before the call)
        for back in range(0, 200, 2):
            if off - back < 0:
                break
            hw = struct.unpack_from("<H", rom, off - back)[0]
            if (hw & 0xFF00) == 0xB500 or (hw & 0xFE00) == 0xB400:
                func_start = off - back
                func_addr = 0x08000000 + func_start
                bl_offset = off - func_start
                print(f"Caller at ROM 0x{off:06X} is in function 0x{func_addr:08X} (ROM 0x{func_start:06X})")
                print(f"  BL HandleLinkBattleSetup at func+0x{bl_offset:03X}")

                # GBA-PK patches SetUpBattleVars+0x42. Let's see if this func+0x42 matches
                if bl_offset > 0x30 and bl_offset < 0x60:
                    print(f"  -> OFFSET MATCHES GBA-PK's +0x42 PATTERN! (actual: +0x{bl_offset:03X})")

                # Check who calls THIS function
                subcallers = find_all_bl_to(rom, func_addr | 1, 0, 0x02000000)
                print(f"  Callers of 0x{func_addr:08X} ({len(subcallers)}):")
                for so, spc in subcallers:
                    print(f"    ROM 0x{so:06X} (0x{spc:08X})")
                print()
                break

    # Now let's confirm: the NOP patch should be the BL halfwords at the caller offset
    print("=== NOP Patch Details ===\n")
    for off, pc in callers:
        hw1 = struct.unpack_from("<H", rom, off)[0]
        hw2 = struct.unpack_from("<H", rom, off + 2)[0]
        print(f"BL at ROM 0x{off:06X}: 0x{hw1:04X} 0x{hw2:04X}")
        print(f"  NOP patch: write 0x46C0 at ROM 0x{off:06X} and 0x{off+2:06X}")
        print(f"  This replaces BL HandleLinkBattleSetup with two NOPs")

if __name__ == "__main__":
    main()
