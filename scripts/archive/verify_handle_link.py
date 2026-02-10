#!/usr/bin/env python3
"""
Verify that 0x080721DC is HandleLinkBattleSetup by disassembling it.
Also find the exact BL bytes at SetUpBattleVars+0x100 to confirm patch offset.
"""
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

def main():
    rom = read_rom()

    # Verify the BL at SetUpBattleVars+0x100
    setup_offset = 0x06F1D8
    bl_offset = setup_offset + 0x100  # = 0x06F2D8

    hw1 = struct.unpack_from("<H", rom, bl_offset)[0]
    hw2 = struct.unpack_from("<H", rom, bl_offset + 2)[0]
    pc = 0x08000000 + bl_offset
    target = decode_bl(hw1, hw2, pc)

    print(f"=== BL at SetUpBattleVars+0x100 (ROM 0x{bl_offset:06X}) ===")
    print(f"  Bytes: 0x{hw1:04X} 0x{hw2:04X}")
    print(f"  PC: 0x{pc:08X}")
    print(f"  Target: 0x{target:08X}")
    print(f"  To NOP this BL: write 0x46C0 at ROM 0x{bl_offset:06X} and 0x{bl_offset+2:06X}")
    print()

    # Disassemble HandleLinkBattleSetup at 0x080721DC (ROM 0x0721DC)
    func_offset = 0x0721DC
    print(f"=== HandleLinkBattleSetup at ROM 0x{func_offset:06X} ===")
    print()

    # Read and print raw bytes first
    raw = rom[func_offset:func_offset+200]
    print("Raw bytes (first 200):")
    for i in range(0, min(200, len(raw)), 16):
        hex_str = " ".join(f"{b:02X}" for b in raw[i:i+16])
        print(f"  +0x{i:03X}: {hex_str}")
    print()

    # Decode THUMB instructions
    print("THUMB disassembly:")
    i = 0
    while i < 200:
        hw = struct.unpack_from("<H", rom, func_offset + i)[0]
        addr = 0x08000000 + func_offset + i

        # Check for BL
        if i + 2 < 200:
            hw2 = struct.unpack_from("<H", rom, func_offset + i + 2)[0]
            bl_target = decode_bl(hw, hw2, addr)
            if bl_target is not None:
                print(f"  +0x{i:03X} [{addr:08X}]: BL 0x{bl_target:08X}  (0x{hw:04X} 0x{hw2:04X})")
                i += 4
                continue

        # Decode common THUMB instructions
        desc = ""
        if (hw & 0xFF00) == 0xB500:
            desc = f"PUSH {{LR, ...}}"
        elif (hw & 0xFF00) == 0xBD00:
            desc = f"POP {{PC, ...}}"
        elif (hw & 0xFF80) == 0xB080:
            desc = f"SUB SP, #{(hw & 0x7F) * 4}"
        elif (hw & 0xFF80) == 0xB000:
            desc = f"ADD SP, #{(hw & 0x7F) * 4}"
        elif (hw & 0xF800) == 0x4800:
            rn = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pool_addr = ((addr + 4) & ~3) + imm
            pool_offset = pool_addr - 0x08000000
            if 0 <= pool_offset < len(rom) - 4:
                pool_val = struct.unpack_from("<I", rom, pool_offset)[0]
                desc = f"LDR R{rn}, [PC, #0x{imm:X}] = [0x{pool_addr:08X}] -> 0x{pool_val:08X}"
            else:
                desc = f"LDR R{rn}, [PC, #0x{imm:X}]"
        elif (hw & 0xF800) == 0x6800:
            rn = (hw >> 3) & 7
            rd = hw & 7
            imm = ((hw >> 6) & 0x1F) * 4
            desc = f"LDR R{rd}, [R{rn}, #0x{imm:X}]"
        elif (hw & 0xF800) == 0x6000:
            rn = (hw >> 3) & 7
            rd = hw & 7
            imm = ((hw >> 6) & 0x1F) * 4
            desc = f"STR R{rd}, [R{rn}, #0x{imm:X}]"
        elif (hw & 0xFF00) == 0x2000 or (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"MOVS R{rd}, #0x{imm:X} ({imm})"
        elif (hw & 0xFFC0) == 0x4200:
            rn = (hw >> 3) & 7
            rm = hw & 7
            desc = f"TST R{rm}, R{rn}"
        elif (hw & 0xFF00) == 0xD000:
            cond = (hw >> 8) & 0xF
            offset = hw & 0xFF
            if offset & 0x80: offset -= 256
            cond_names = {0:"BEQ",1:"BNE",2:"BCS",3:"BCC",4:"BMI",5:"BPL",
                         6:"BVS",7:"BVC",8:"BHI",9:"BLS",10:"BGE",11:"BLT",
                         12:"BGT",13:"BLE"}
            cname = cond_names.get(cond, f"B{cond}")
            target_addr = addr + 4 + offset * 2
            desc = f"{cname} 0x{target_addr:08X}"
        elif hw == 0x46C0:
            desc = "NOP (MOV R8, R8)"
        elif (hw & 0xFE00) == 0x1C00:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = (hw >> 6) & 7
            desc = f"ADDS R{rd}, R{rn}, #{imm}"
        elif hw == 0x4770:
            desc = "BX LR (return)"
        elif (hw & 0xFFC0) == 0x0000 and hw != 0:
            rd = hw & 7
            rm = (hw >> 3) & 7
            desc = f"MOVS R{rd}, R{rm}"

        print(f"  +0x{i:03X} [{addr:08X}]: 0x{hw:04X}  {desc}")

        # Stop at BX LR or POP {PC}
        if hw == 0x4770 or (hw & 0xFF00) == 0xBD00:
            print("  --- function end ---")
            break

        i += 2

    print()
    print("=== Summary ===")
    print(f"  HandleLinkBattleSetup = 0x080721DC (ROM 0x0721DC)")
    print(f"  Called from SetUpBattleVars at +0x100 (ROM 0x06F2D8)")
    print(f"  NOP patch: write 0x46C0 at ROM 0x06F2D8 and 0x06F2DA")
    print(f"  (replaces BL 0x080721DC with two NOPs)")

if __name__ == "__main__":
    main()
