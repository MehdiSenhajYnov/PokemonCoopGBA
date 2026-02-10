#!/usr/bin/env python3
"""
Disassemble the 3 functions that directly access gBlockReceivedStatus.
Try to understand their purpose and when they're called.
"""

import struct
from pathlib import Path

ROM_PATH = Path(r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba")

# Functions found by scan_gbrs_refs.py
FUNCTIONS = [
    ("SetBlockReceivedFlag", 0x0800A5D1),
    ("ResetBlockReceivedFlags", 0x0800A5FD),
    ("ClearReceivedBlockStatus", 0x0800A635),
]

def read_rom():
    return ROM_PATH.read_bytes()

def find_function_end(rom, start_offset, max_bytes=512):
    """
    Find function end by looking for POP+BX or B (unconditional branch).
    Returns rom_offset of end.
    """
    for i in range(start_offset, min(start_offset + max_bytes, len(rom) - 1), 2):
        instr = struct.unpack('<H', rom[i:i+2])[0]
        # POP {..., pc} or BX LR
        if (instr & 0xFE00) == 0xBD00 or instr == 0x4770:
            return i + 2
    return start_offset + max_bytes

def disasm_thumb_simple(rom, func_addr, func_name):
    """
    Simple Thumb disassembly to identify patterns.
    Focus on LDR (literal pool), LDRB, STRB, CMP, BEQ, B, BL.
    """
    print(f"\n{'='*80}")
    print(f"Function: {func_name}")
    print(f"Address: 0x{func_addr:08X}")
    print(f"{'='*80}\n")

    rom_offset = (func_addr & 0x01FFFFFF) - 1  # Strip Thumb bit
    end_offset = find_function_end(rom, rom_offset)

    pc = func_addr & ~1
    for offset in range(rom_offset, end_offset, 2):
        instr = struct.unpack('<H', rom[offset:offset+2])[0]
        disasm = f"  {pc:08X}:  {instr:04X}  "

        # Decode common patterns
        if (instr & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm] — literal pool
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            target_pc = (pc + 4) & ~3  # Align PC to 4
            target_addr = target_pc + imm
            target_rom = (target_addr & 0x01FFFFFF)
            if target_rom < len(rom) - 3:
                value = struct.unpack('<I', rom[target_rom:target_rom+4])[0]
                disasm += f"LDR R{rd}, [PC, #{imm}]  ; R{rd} = 0x{value:08X} from [0x{target_addr:08X}]"
            else:
                disasm += f"LDR R{rd}, [PC, #{imm}]"

        elif (instr & 0xFE00) == 0x7800:  # LDRB Rd, [Rn, #imm]
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = (instr >> 6) & 0x1F
            disasm += f"LDRB R{rd}, [R{rn}, #{imm}]"

        elif (instr & 0xFE00) == 0x7000:  # STRB Rd, [Rn, #imm]
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = (instr >> 6) & 0x1F
            disasm += f"STRB R{rd}, [R{rn}, #{imm}]"

        elif (instr & 0xFFC0) == 0x4280:  # CMP Rn, Rm
            rn = instr & 7
            rm = (instr >> 3) & 7
            disasm += f"CMP R{rn}, R{rm}"

        elif (instr & 0xFF00) == 0x2800:  # CMP Rn, #imm
            rn = (instr >> 8) & 7
            imm = instr & 0xFF
            disasm += f"CMP R{rn}, #{imm}"

        elif (instr & 0xF000) == 0xD000:  # Bcc (conditional branch)
            cond = (instr >> 8) & 0xF
            simm = instr & 0xFF
            if simm & 0x80:
                simm |= 0xFFFFFF00  # Sign extend
            target = pc + 4 + (simm * 2)
            cond_str = ["BEQ", "BNE", "BCS", "BCC", "BMI", "BPL", "BVS", "BVC",
                        "BHI", "BLS", "BGE", "BLT", "BGT", "BLE", "BAL", "BNV"][cond]
            disasm += f"{cond_str} 0x{target:08X}"

        elif (instr & 0xF800) == 0xE000:  # B (unconditional)
            simm = instr & 0x7FF
            if simm & 0x400:
                simm |= 0xFFFFF800
            target = pc + 4 + (simm * 2)
            disasm += f"B 0x{target:08X}"

        elif instr == 0x4770:  # BX LR
            disasm += "BX LR"

        elif (instr & 0xFE00) == 0xB400:  # PUSH
            rlist = instr & 0x1FF
            disasm += f"PUSH {{...}}  ; rlist=0x{rlist:03X}"

        elif (instr & 0xFE00) == 0xBC00:  # POP
            rlist = instr & 0x1FF
            disasm += f"POP {{...}}  ; rlist=0x{rlist:03X}"

        elif (instr & 0xF800) == 0xF000:  # BL prefix (first half)
            # BL is a 32-bit instruction in Thumb
            if offset + 2 < end_offset:
                instr2 = struct.unpack('<H', rom[offset+2:offset+4])[0]
                if (instr2 & 0xF800) == 0xF800:
                    # Full BL
                    imm11_1 = instr & 0x7FF
                    imm11_2 = instr2 & 0x7FF
                    if imm11_1 & 0x400:
                        imm11_1 |= 0xFFFFF800
                    offset_val = (imm11_1 << 12) | (imm11_2 << 1)
                    target = pc + 4 + offset_val
                    disasm += f"BL 0x{target:08X}"
                    # Skip next instruction (already processed)
                    pc += 2
                    offset += 2
                    print(disasm)
                    continue

        else:
            disasm += f"???"

        print(disasm)
        pc += 2

    print()

def search_xrefs(rom, target_addr):
    """
    Search for BL calls to target_addr.
    """
    print(f"\nSearching for calls to 0x{target_addr:08X}...")
    xrefs = []

    # BL in Thumb is 32-bit: 0xF000 xxxx followed by 0xF800 xxxx
    for i in range(0, len(rom) - 3, 2):
        instr1 = struct.unpack('<H', rom[i:i+2])[0]
        instr2 = struct.unpack('<H', rom[i+2:i+4])[0]

        if (instr1 & 0xF800) == 0xF000 and (instr2 & 0xF800) == 0xF800:
            # Calculate target
            imm11_1 = instr1 & 0x7FF
            imm11_2 = instr2 & 0x7FF
            if imm11_1 & 0x400:
                imm11_1 |= 0xFFFFF800
            offset_val = (imm11_1 << 12) | (imm11_2 << 1)
            pc = 0x08000000 + i + 4
            bl_target = pc + offset_val

            if bl_target == target_addr:
                caller_addr = 0x08000000 + i + 1  # Thumb bit
                xrefs.append(caller_addr)

    if xrefs:
        print(f"  Found {len(xrefs)} call sites:")
        for addr in xrefs:
            print(f"    0x{addr:08X}")
    else:
        print(f"  No direct BL calls found")

    return xrefs

def main():
    print("[*] Reading ROM...")
    rom = read_rom()

    for func_name, func_addr in FUNCTIONS:
        disasm_thumb_simple(rom, func_addr, func_name)
        search_xrefs(rom, func_addr)

    print("\n" + "="*80)
    print("ANALYSIS SUMMARY")
    print("="*80)
    print("\nThese functions directly read/write gBlockReceivedStatus memory.")
    print("If they're called during battle init (CB2_HandleStartBattle),")
    print("they will see our 0x0F value instead of GBA-PK's 0x0/0x03.")
    print("\nCheck if any xrefs are in CB2_HandleStartBattle (0x08037B45)")
    print("or CB2_InitBattleInternal (0x0803648D).")

if __name__ == '__main__':
    main()
