"""
Verify CB2_ReturnToField = 0x080A40D9 in Pokemon Run & Bun ROM.

From previous analysis:
  CB2_ReturnToField = 0x080A40D9 (stored 3x to gMain.savedCallback)
  CB2_ReturnToFieldLink = 0x080A4129
  CB2_ReturnToFieldLocal = 0x080A4105
  IsOverworldLinkActive = 0x080A3D9C
  FieldClearVBlankHBlankCallbacks = 0x080A432C

Let's verify by:
1. Disassembling 0x080A40D8 (function start = PUSH)
2. Checking CB2_ReturnToFieldLocal calls SetMainCallback2(CB2_Overworld) indirectly
3. Listing all callers of CB2_ReturnToField (who stores 0x080A40D9 to savedCallback)
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
ROM_BASE = 0x08000000
SET_MAIN_CB2 = 0x08000544
CB2_OVERWORLD = 0x080A89A5

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_thumb_bl(rom, offset):
    if offset + 4 > len(rom):
        return None
    hi = struct.unpack_from('<H', rom, offset)[0]
    lo = struct.unpack_from('<H', rom, offset + 2)[0]
    if (hi & 0xF800) != 0xF000 or (lo & 0xF800) != 0xF800:
        return None
    offset_hi = hi & 0x7FF
    offset_lo = lo & 0x7FF
    combined = (offset_hi << 12) | (offset_lo << 1)
    if combined & 0x400000:
        combined |= ~0x7FFFFF
        combined &= 0xFFFFFFFF
    pc = ROM_BASE + offset + 4
    target = (pc + combined) & 0xFFFFFFFF
    return target

def ldr_pc_value(rom, offset):
    if offset + 2 > len(rom):
        return None
    hw = struct.unpack_from('<H', rom, offset)[0]
    if (hw & 0xF800) != 0x4800:
        return None
    rd = (hw >> 8) & 0x7
    imm8 = hw & 0xFF
    addr = ROM_BASE + offset
    pc_val = ((addr + 4) & ~3) + imm8 * 4
    lit_off = pc_val - ROM_BASE
    if 0 <= lit_off < len(rom) - 3:
        val = struct.unpack_from('<I', rom, lit_off)[0]
        return (rd, val)
    return None

def disasm_thumb(rom, start_off, count=30):
    lines = []
    off = start_off
    for _ in range(count):
        if off + 2 > len(rom):
            break
        hw = struct.unpack_from('<H', rom, off)[0]
        addr = ROM_BASE + off
        desc = ""
        if (hw & 0xFE00) == 0xB400:
            rlist = hw & 0xFF; lr = (hw >> 8) & 1
            regs = [f"R{i}" for i in range(8) if rlist & (1 << i)]
            if lr: regs.append("LR")
            desc = f"PUSH {{{', '.join(regs)}}}"
        elif (hw & 0xFE00) == 0xBC00:
            rlist = hw & 0xFF; pc = (hw >> 8) & 1
            regs = [f"R{i}" for i in range(8) if rlist & (1 << i)]
            if pc: regs.append("PC")
            desc = f"POP {{{', '.join(regs)}}}"
        elif (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 0x7; imm8 = hw & 0xFF
            pc_val = ((addr + 4) & ~3) + imm8 * 4
            lit_off = pc_val - ROM_BASE
            if 0 <= lit_off < len(rom) - 3:
                lit_val = struct.unpack_from('<I', rom, lit_off)[0]
                desc = f"LDR R{rd}, [PC, #0x{imm8*4:X}] ; =0x{lit_val:08X}"
            else:
                desc = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"
        elif (hw & 0xF800) == 0xF000:
            if off + 4 <= len(rom):
                lo = struct.unpack_from('<H', rom, off + 2)[0]
                if (lo & 0xF800) == 0xF800:
                    target = decode_thumb_bl(rom, off)
                    desc = f"BL 0x{target:08X}"
                    lines.append(f"  0x{addr:08X}: {hw:04X} {lo:04X}  {desc}")
                    off += 4
                    continue
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF; desc = f"BX R{rm}"
        elif (hw & 0xF800) == 0x2000:
            desc = f"MOV R{(hw>>8)&7}, #0x{hw&0xFF:X}"
        elif (hw & 0xF800) == 0x2800:
            desc = f"CMP R{(hw>>8)&7}, #0x{hw&0xFF:X}"
        elif hw == 0x46C0: desc = "NOP"
        elif (hw & 0xF800) == 0xE000:
            imm11 = hw & 0x7FF
            if imm11 & 0x400: imm11 = imm11 - 0x800
            desc = f"B 0x{(addr+4+(imm11<<1))&0xFFFFFFFF:08X}"
        elif (hw & 0xFF00) == 0xD000 or (hw & 0xFF00) == 0xD100:
            imm8 = hw & 0xFF
            if imm8 & 0x80: imm8 = imm8 - 0x100
            cond = (hw >> 8) & 0xF
            conds = {0:"BEQ",1:"BNE",2:"BCS",3:"BCC",4:"BMI",5:"BPL",6:"BVS",7:"BVC",
                     8:"BHI",9:"BLS",10:"BGE",11:"BLT",12:"BGT",13:"BLE"}
            desc = f"{conds.get(cond,'B??')} 0x{(addr+4+(imm8<<1))&0xFFFFFFFF:08X}"
        elif (hw & 0xF000) == 0x6000:
            imm5=(hw>>6)&0x1F; rn=(hw>>3)&7; rd=hw&7
            op = "LDR" if (hw>>11)&1 else "STR"
            desc = f"{op} R{rd}, [R{rn}, #0x{imm5*4:X}]"
        elif (hw & 0xF000) == 0x7000:
            imm5=(hw>>6)&0x1F; rn=(hw>>3)&7; rd=hw&7
            op = "LDRB" if (hw>>11)&1 else "STRB"
            desc = f"{op} R{rd}, [R{rn}, #0x{imm5:X}]"
        elif (hw & 0xFF00) == 0x4600:
            rd = (hw & 7) | ((hw >> 4) & 8); rm = (hw >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"
        elif (hw & 0xFFC0) == 0x4280:
            desc = f"CMP R{hw&7}, R{(hw>>3)&7}"
        if not desc: desc = f".hword 0x{hw:04X}"
        lines.append(f"  0x{addr:08X}: {hw:04X}        {desc}")
        off += 2
    return "\n".join(lines)

def main():
    rom = read_rom()

    print("=" * 80)
    print("VERIFICATION: CB2_ReturnToField = 0x080A40D9")
    print("=" * 80)

    # 1. Disassemble CB2_ReturnToField (0x080A40D8 = function start)
    print("\n--- CB2_ReturnToField (0x080A40D8) ---")
    print(disasm_thumb(rom, 0x0A40D8, 20))

    # 2. Disassemble CB2_ReturnToFieldLocal (0x080A4104)
    print("\n--- CB2_ReturnToFieldLocal (0x080A4104) ---")
    print(disasm_thumb(rom, 0x0A4104, 20))

    # 3. Disassemble CB2_ReturnToFieldLink (0x080A4128)
    print("\n--- CB2_ReturnToFieldLink (0x080A4128) ---")
    print(disasm_thumb(rom, 0x0A4128, 20))

    # 4. Disassemble IsOverworldLinkActive (0x080A3D9C)
    print("\n--- IsOverworldLinkActive (0x080A3D9C) ---")
    print(disasm_thumb(rom, 0x0A3D9C, 15))

    # 5. Check if CB2_ReturnToFieldLocal eventually sets CB2_Overworld
    # It calls ReturnToFieldLocal(&gMain.state), and if that returns true,
    # calls SetFieldVBlankCallback() then SetMainCallback2(CB2_Overworld)
    print("\n--- Checking CB2_ReturnToFieldLocal for CB2_Overworld reference ---")
    # The func at 0x080A4104 calls some function, checks return, then calls SetMainCallback2
    # Let's check what the LDR R0 before the BL SetMainCallback2 loads
    for off in range(0x0A4104, 0x0A4128, 2):
        t = decode_thumb_bl(rom, off)
        if t == SET_MAIN_CB2:
            print(f"  BL SetMainCallback2 at 0x{ROM_BASE+off:08X}")
            # Check LDR R0 before
            for ldr_off in range(off - 2, max(off - 10, 0x0A4104), -2):
                r = ldr_pc_value(rom, ldr_off)
                if r and r[0] == 0:
                    print(f"  LDR R0, =0x{r[1]:08X} at 0x{ROM_BASE+ldr_off:08X}")
                    if r[1] == CB2_OVERWORLD:
                        print("  *** CONFIRMED: loads CB2_Overworld! ***")
                    break

    # 6. Verify by listing all callers (who stores this address to savedCallback)
    print("\n--- Callers storing 0x080A40D9 to gMain.savedCallback ---")
    target_val = 0x080A40D9
    # Find literal pool entries for this value
    for off in range(0, len(rom) - 3, 4):
        val = struct.unpack_from('<I', rom, off)[0]
        if val == target_val:
            # Find code that references this LP entry
            lp_addr = ROM_BASE + off
            for code_off in range(max(off - 1020, 0), off, 2):
                hw = struct.unpack_from('<H', rom, code_off)[0]
                if (hw & 0xF800) != 0x4800:
                    continue
                rd = (hw >> 8) & 0x7
                imm8 = hw & 0xFF
                code_addr = ROM_BASE + code_off
                pc_target = ((code_addr + 4) & ~3) + imm8 * 4
                if pc_target == lp_addr:
                    print(f"  LDR R{rd}, =0x{target_val:08X} at 0x{code_addr:08X}")

    # 7. Also check: does any function BL to CB2_ReturnToField directly?
    print("\n--- Direct callers of CB2_ReturnToField (BL 0x080A40D8) ---")
    for off in range(0, len(rom) - 4, 2):
        t = decode_thumb_bl(rom, off)
        if t == 0x080A40D9:
            print(f"  BL CB2_ReturnToField at 0x{ROM_BASE+off:08X}")
            # Show context
            context_start = max(off - 8, 0)
            print(disasm_thumb(rom, context_start, 10))

    # 8. Also verify CB2_ReturnToFieldContestHall nearby
    # In pokeemerald it's just before CB2_ReturnToField
    print("\n--- Checking functions just before CB2_ReturnToField ---")
    print("Previous function (likely CB2_ReturnToFieldContestHall):")
    # Walk back from 0x0A40D8
    prev_start = 0x0A40A8  # from approach 2, CB2_ReturnToFieldLocal alt
    print(disasm_thumb(rom, prev_start, 25))

    print("\n" + "=" * 80)
    print("FINAL RESULT")
    print("=" * 80)
    print(f"CB2_ReturnToField        = 0x080A40D9 (func at 0x080A40D8, THUMB addr 0x080A40D9)")
    print(f"CB2_ReturnToFieldLocal   = 0x080A4105 (func at 0x080A4104)")
    print(f"CB2_ReturnToFieldLink    = 0x080A4129 (func at 0x080A4128)")
    print(f"IsOverworldLinkActive    = 0x080A3D9D (func at 0x080A3D9C)")
    print(f"FieldClearVBlankHBlankCallbacks = 0x080A432D (func at 0x080A432C)")

if __name__ == "__main__":
    main()
