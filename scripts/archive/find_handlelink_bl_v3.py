#!/usr/bin/env python3
"""
Detailed analysis of HandleLinkBattleSetup at 0x0806F0D4
and its call from SetUpBattleVars at +0x248 (0x0806F420).
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
ROM_BASE = 0x08000000

def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def decode_bl(hw1, hw2, addr):
    if (hw1 & 0xF800) != 0xF000: return None
    if (hw2 & 0xF800) != 0xF800: return None
    offset_hi = hw1 & 0x7FF
    offset_lo = hw2 & 0x7FF
    if offset_hi & 0x400: offset_hi |= 0xFFFFF800
    combined = (offset_hi << 12) | (offset_lo << 1)
    return (addr + 4 + combined) & 0xFFFFFFFF

def disasm_thumb(rom_data, addr, hw):
    """Full disasm with literal pool resolution"""
    extra = ""
    if (hw & 0xF800) == 0x4800:
        rd = (hw >> 8) & 7; imm8 = hw & 0xFF
        pc_val = (addr + 4) & ~2; pool_addr = pc_val + imm8 * 4
        pool_off = pool_addr - ROM_BASE
        val_str = ""
        if 0 <= pool_off <= len(rom_data) - 4:
            val = read_u32(rom_data, pool_off)
            val_str = f"  ; =0x{val:08X}"
        return f"LDR r{rd}, [PC, #0x{imm8*4:X}]{val_str}"
    if (hw & 0xFE00) == 0xB400:
        regs = [f"r{i}" for i in range(8) if hw & (1 << i)]
        if hw & 0x100: regs.append("lr")
        return f"PUSH {{{', '.join(regs)}}}"
    if (hw & 0xFE00) == 0xBC00:
        regs = [f"r{i}" for i in range(8) if hw & (1 << i)]
        if hw & 0x100: regs.append("pc")
        return f"POP {{{', '.join(regs)}}}"
    if (hw & 0xFF00) == 0xBD00:
        regs = [f"r{i}" for i in range(8) if hw & (1 << i)]
        regs.append("pc")
        return f"POP {{{', '.join(regs)}}}"
    if (hw & 0xF800) == 0x2000:
        return f"MOV r{(hw>>8)&7}, #0x{hw&0xFF:02X}"
    if (hw & 0xF800) == 0x2800:
        return f"CMP r{(hw>>8)&7}, #0x{hw&0xFF:02X}"
    if (hw & 0xF800) == 0x3000:
        return f"ADD r{(hw>>8)&7}, #0x{hw&0xFF:02X}"
    if (hw & 0xF800) == 0x3800:
        return f"SUB r{(hw>>8)&7}, #0x{hw&0xFF:02X}"
    if (hw & 0xF800) == 0x6800:
        rd = hw&7; rn = (hw>>3)&7; imm = ((hw>>6)&0x1F)*4
        return f"LDR r{rd}, [r{rn}, #0x{imm:X}]"
    if (hw & 0xF800) == 0x6000:
        rd = hw&7; rn = (hw>>3)&7; imm = ((hw>>6)&0x1F)*4
        return f"STR r{rd}, [r{rn}, #0x{imm:X}]"
    if (hw & 0xF800) == 0x7800:
        rd = hw&7; rn = (hw>>3)&7; imm = (hw>>6)&0x1F
        return f"LDRB r{rd}, [r{rn}, #0x{imm:X}]"
    if (hw & 0xF800) == 0x7000:
        rd = hw&7; rn = (hw>>3)&7; imm = (hw>>6)&0x1F
        return f"STRB r{rd}, [r{rn}, #0x{imm:X}]"
    if (hw & 0xF800) == 0x8800:
        rd = hw&7; rn = (hw>>3)&7; imm = ((hw>>6)&0x1F)*2
        return f"LDRH r{rd}, [r{rn}, #0x{imm:X}]"
    if (hw & 0xF800) == 0x8000:
        rd = hw&7; rn = (hw>>3)&7; imm = ((hw>>6)&0x1F)*2
        return f"STRH r{rd}, [r{rn}, #0x{imm:X}]"
    if (hw & 0xFFC0) == 0x4000:
        return f"AND r{hw&7}, r{(hw>>3)&7}"
    if (hw & 0xFFC0) == 0x4040:
        return f"EOR r{hw&7}, r{(hw>>3)&7}"
    if (hw & 0xFFC0) == 0x4080:
        return f"LSL r{hw&7}, r{(hw>>3)&7}"
    if (hw & 0xFFC0) == 0x40C0:
        return f"LSR r{hw&7}, r{(hw>>3)&7}"
    if (hw & 0xFFC0) == 0x4200:
        return f"TST r{hw&7}, r{(hw>>3)&7}"
    if (hw & 0xFFC0) == 0x4300:
        return f"ORR r{hw&7}, r{(hw>>3)&7}"
    if (hw & 0xFFC0) == 0x4340:
        return f"MUL r{hw&7}, r{(hw>>3)&7}"
    if (hw & 0xFE00) == 0x1800:
        return f"ADD r{hw&7}, r{(hw>>3)&7}, r{(hw>>6)&7}"
    if (hw & 0xFE00) == 0x1A00:
        return f"SUB r{hw&7}, r{(hw>>3)&7}, r{(hw>>6)&7}"
    if (hw & 0xFE00) == 0x1C00:
        return f"ADD r{hw&7}, r{(hw>>3)&7}, #{(hw>>6)&7}"
    if (hw & 0xFE00) == 0x1E00:
        return f"SUB r{hw&7}, r{(hw>>3)&7}, #{(hw>>6)&7}"
    if (hw & 0xF800) == 0x0000:
        rd = hw&7; rm = (hw>>3)&7; imm5 = (hw>>6)&0x1F
        if imm5 == 0: return f"MOV r{rd}, r{rm}"
        return f"LSL r{rd}, r{rm}, #{imm5}"
    if (hw & 0xF800) == 0x0800:
        rd = hw&7; rm = (hw>>3)&7; imm5 = (hw>>6)&0x1F
        if imm5 == 0: imm5 = 32
        return f"LSR r{rd}, r{rm}, #{imm5}"
    if (hw & 0xFF00) == 0x4600:
        rd = (hw&7)|((hw>>4)&8); rm = (hw>>3)&0xF
        return f"MOV r{rd}, r{rm}"
    if (hw & 0xFF00) == 0x4500:
        rn = (hw&7)|((hw>>4)&8); rm = (hw>>3)&0xF
        return f"CMP r{rn}, r{rm}"
    if (hw & 0xFF80) == 0x4700:
        return f"BX r{(hw>>3)&0xF}"
    if (hw & 0xFF80) == 0x4780:
        return f"BLX r{(hw>>3)&0xF}"
    if (hw & 0xF000) == 0xD000:
        cond = (hw>>8)&0xF
        if cond < 0xE:
            names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                     "BHI","BLS","BGE","BLT","BGT","BLE"]
            imm8 = hw & 0xFF
            if imm8 & 0x80: imm8 -= 256
            tgt = addr + 4 + imm8 * 2
            return f"{names[cond]} 0x{tgt:08X}"
    if (hw & 0xF800) == 0xE000:
        imm11 = hw & 0x7FF
        if imm11 & 0x400: imm11 -= 0x800
        tgt = addr + 4 + imm11 * 2
        return f"B 0x{tgt:08X}"
    if hw == 0x46C0:
        return "NOP"
    if (hw & 0xFF80) == 0xB000:
        return f"ADD SP, #0x{(hw&0x7F)*4:X}"
    if (hw & 0xFF80) == 0xB080:
        return f"SUB SP, #0x{(hw&0x7F)*4:X}"
    if (hw & 0xF800) == 0x9800:
        return f"LDR r{(hw>>8)&7}, [SP, #0x{(hw&0xFF)*4:X}]"
    if (hw & 0xF800) == 0x9000:
        return f"STR r{(hw>>8)&7}, [SP, #0x{(hw&0xFF)*4:X}]"
    if (hw & 0xF800) == 0xA800:
        return f"ADD r{(hw>>8)&7}, SP, #0x{(hw&0xFF)*4:X}"
    if (hw & 0xFF00) == 0x4400:
        rd = (hw&7)|((hw>>4)&8); rm = (hw>>3)&0xF
        return f"ADD r{rd}, r{rm}"
    return f"??? 0x{hw:04X}"

def disasm_function(rom_data, func_addr, max_bytes=200):
    """Disassemble a THUMB function"""
    func_clean = func_addr & ~1
    func_off = func_clean - ROM_BASE
    lines = []
    i = 0
    while i < max_bytes:
        addr = func_clean + i
        hw = read_u16(rom_data, func_off + i)

        # Check BL
        if i + 2 < max_bytes:
            hw2 = read_u16(rom_data, func_off + i + 2)
            target = decode_bl(hw, hw2, addr)
            if target is not None:
                lines.append(f"  0x{addr:08X} (+0x{i:02X}): {hw:04X} {hw2:04X}  BL 0x{target:08X}")
                i += 4
                continue

        d = disasm_thumb(rom_data, addr, hw)
        lines.append(f"  0x{addr:08X} (+0x{i:02X}): {hw:04X}      {d}")

        # End at POP {pc} or BX LR
        if (hw & 0xFF00) == 0xBD00 or hw == 0x4770:
            # Print literal pool after function
            lines.append(f"  --- function end ---")
            # Align to 4 bytes
            pool_start = i + 2
            if pool_start & 2: pool_start += 2
            for j in range(pool_start, min(pool_start + 40, max_bytes - 4), 4):
                val = read_u32(rom_data, func_off + j)
                lines.append(f"  0x{func_clean+j:08X} (+0x{j:02X}): {val:08X}  .word 0x{val:08X}")
            break
        i += 2

    return lines

def main():
    with open(ROM_PATH, 'rb') as f:
        rom_data = f.read()

    SUBV_ADDR = 0x0806F1D8  # SetUpBattleVarsAndBirchZigzagoon
    HLBS_ADDR = 0x0806F0D4  # HandleLinkBattleSetup (found by v2 script)
    BL_OFFSET_IN_SUBV = 0x248  # Offset of BL within SetUpBattleVars

    print(f"{'='*80}")
    print(f"HandleLinkBattleSetup at 0x{HLBS_ADDR:08X}")
    print(f"{'='*80}\n")

    for line in disasm_function(rom_data, HLBS_ADDR, 200):
        print(line)

    print(f"\n{'='*80}")
    print(f"BL call site in SetUpBattleVars")
    print(f"{'='*80}\n")

    bl_addr = SUBV_ADDR + BL_OFFSET_IN_SUBV
    bl_rom_off = bl_addr - ROM_BASE
    hw1 = read_u16(rom_data, bl_rom_off)
    hw2 = read_u16(rom_data, bl_rom_off + 2)
    target = decode_bl(hw1, hw2, bl_addr)

    print(f"  BL instruction at:")
    print(f"    ROM address:    0x{bl_addr:08X}")
    print(f"    ROM file offset: 0x{bl_rom_off:06X}")
    print(f"    Bytes (hex):    {hw1:04X} {hw2:04X}")
    print(f"    Bytes (LE):     {hw1&0xFF:02X} {(hw1>>8)&0xFF:02X} {hw2&0xFF:02X} {(hw2>>8)&0xFF:02X}")
    print(f"    Target:         0x{target:08X}")
    print(f"    Target matches HandleLinkBattleSetup: {target == 0x0806F0D5 or (target & ~1) == HLBS_ADDR}")

    # Context around the BL
    print(f"\n  Context (SetUpBattleVars around +0x{BL_OFFSET_IN_SUBV:X}):")
    start = BL_OFFSET_IN_SUBV - 16
    func_off = SUBV_ADDR - ROM_BASE
    for i in range(start, BL_OFFSET_IN_SUBV + 8, 2):
        addr = SUBV_ADDR + i
        hw = read_u16(rom_data, func_off + i)

        if i + 2 <= BL_OFFSET_IN_SUBV + 8:
            hw2_check = read_u16(rom_data, func_off + i + 2)
            tgt = decode_bl(hw, hw2_check, addr)
            if tgt is not None:
                marker = " <--- BL to HandleLinkBattleSetup" if i == BL_OFFSET_IN_SUBV else ""
                print(f"    0x{addr:08X} (+0x{i:02X}): {hw:04X} {hw2_check:04X}  BL 0x{tgt:08X}{marker}")
                if i < BL_OFFSET_IN_SUBV:
                    # skip the second halfword in iteration
                    pass
                continue

        d = disasm_thumb(rom_data, addr, hw)
        print(f"    0x{addr:08X} (+0x{i:02X}): {hw:04X}      {d}")

    print(f"\n{'='*80}")
    print(f"SUMMARY: How to NOP the BL to HandleLinkBattleSetup")
    print(f"{'='*80}\n")
    print(f"  SetUpBattleVarsAndBirchZigzagoon: 0x{SUBV_ADDR:08X} (THUMB: 0x{SUBV_ADDR|1:08X})")
    print(f"  HandleLinkBattleSetup:            0x{HLBS_ADDR:08X} (THUMB: 0x{HLBS_ADDR|1:08X})")
    print(f"")
    print(f"  BL instruction offset in SetUpBattleVars: +0x{BL_OFFSET_IN_SUBV:X}")
    print(f"  BL ROM address:    0x{bl_addr:08X}")
    print(f"  BL ROM file offset: 0x{bl_rom_off:06X}")
    print(f"  BL bytes:          0x{hw1:04X} 0x{hw2:04X}")
    print(f"")
    print(f"  To NOP (2x MOV r8,r8 = 0x46C0):")
    print(f"    At ROM offset 0x{bl_rom_off:06X}: write bytes C0 46 (little-endian 0x46C0)")
    print(f"    At ROM offset 0x{bl_rom_off+2:06X}: write bytes C0 46 (little-endian 0x46C0)")
    print(f"")
    print(f"  For mGBA Lua (cart0 write):")
    print(f"    emu.memory.cart0:write16(0x{bl_rom_off:06X}, 0x46C0)")
    print(f"    emu.memory.cart0:write16(0x{bl_rom_off+2:06X}, 0x46C0)")
    print(f"  Or equivalently (ROM addresses):")
    print(f"    -- NOP the BL to HandleLinkBattleSetup at 0x{bl_addr:08X}")
    print(f"    emu.memory.cart0:write16(0x{bl_addr - ROM_BASE:06X}, 0x46C0)  -- first halfword")
    print(f"    emu.memory.cart0:write16(0x{bl_addr - ROM_BASE + 2:06X}, 0x46C0)  -- second halfword")

    # Verify: what does HandleLinkBattleSetup do?
    print(f"\n{'='*80}")
    print(f"HandleLinkBattleSetup analysis")
    print(f"{'='*80}\n")
    print(f"  This function at 0x{HLBS_ADDR:08X}:")
    print(f"  1. Loads gBattlerControllerFuncs (0x03005D70)")
    print(f"  2. Loads gBattlersCount (0x020233DC)")
    print(f"  3. Sets controller = PlayerBufferRunCommand (0x0806F151)")
    print(f"  4. Loads gBattleTypeFlags (0x02023364)")
    print(f"  5. Tests BATTLE_TYPE_LINK (bit 1, value 0x02)")
    print(f"  6. If LINK: calls further link setup functions")
    print(f"  7. If not LINK: skips to end")
    print(f"")
    print(f"  NOPing the BL prevents link battle hardware setup,")
    print(f"  which is exactly what we want for emulated PvP.")

    # Also check: is the function we identified at the LAST BL before function end?
    print(f"\n{'='*80}")
    print(f"Verification: SetUpBattleVars tail (last ~30 bytes)")
    print(f"{'='*80}")
    func_off = SUBV_ADDR - ROM_BASE
    for i in range(0x240, 0x260, 2):
        addr = SUBV_ADDR + i
        hw = read_u16(rom_data, func_off + i)
        if i + 2 < 0x260:
            hw2 = read_u16(rom_data, func_off + i + 2)
            tgt = decode_bl(hw, hw2, addr)
            if tgt is not None:
                print(f"  0x{addr:08X} (+0x{i:02X}): {hw:04X} {hw2:04X}  BL 0x{tgt:08X}")
                continue
        d = disasm_thumb(rom_data, addr, hw)
        print(f"  0x{addr:08X} (+0x{i:02X}): {hw:04X}      {d}")
        if (hw & 0xFF00) == 0xBD00 or hw == 0x4770:
            print(f"  --- function end ---")
            break

if __name__ == '__main__':
    main()
