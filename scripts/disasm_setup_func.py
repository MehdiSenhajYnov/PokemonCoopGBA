#!/usr/bin/env python3
"""Disassemble the function that sets up Function 2 as a controller."""
import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom(offset, length):
    with open(ROM_PATH, "rb") as f:
        f.seek(offset)
        return f.read(length)

def read_u32(rom_offset):
    data = read_rom(rom_offset, 4)
    return struct.unpack_from("<I", data, 0)[0]

def sign_ext(value, bits):
    if value & (1 << (bits - 1)):
        value -= (1 << bits)
    return value

def decode(hw, addr):
    if (hw & 0xFE00) == 0xB400:
        regs = [f"r{b}" for b in range(8) if hw & (1 << b)]
        if hw & 0x100: regs.append("lr")
        return f"PUSH {{{', '.join(regs)}}}"
    if (hw & 0xFE00) == 0xBC00:
        regs = [f"r{b}" for b in range(8) if hw & (1 << b)]
        if hw & 0x100: regs.append("pc")
        return f"POP {{{', '.join(regs)}}}"
    if (hw & 0xFF00) == 0xB000:
        imm = (hw & 0x7F) * 4
        return f"{'SUB' if hw & 0x80 else 'ADD'} sp, #0x{imm:X}"
    if (hw >> 11) == 0x04:
        return f"MOV r{(hw>>8)&7}, #0x{hw&0xFF:X}"
    if (hw >> 11) == 0x05:
        return f"CMP r{(hw>>8)&7}, #0x{hw&0xFF:X}"
    if (hw >> 11) == 0x06:
        return f"ADD r{(hw>>8)&7}, #0x{hw&0xFF:X}"
    if (hw >> 11) == 0x07:
        return f"SUB r{(hw>>8)&7}, #0x{hw&0xFF:X}"
    if (hw >> 11) == 0x09:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        pc = (addr + 4) & ~2
        pool = pc + imm
        try:
            val = read_u32(pool - 0x08000000)
            return f"LDR r{rd}, [pc, #0x{imm:X}]  ; =0x{val:08X}"
        except:
            return f"LDR r{rd}, [pc, #0x{imm:X}]"
    if (hw >> 13) == 0x03:
        L = (hw >> 11) & 1; B = (hw >> 12) & 1
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 7; rd = hw & 7
        if B: off = imm5; op = "LDRB" if L else "STRB"
        else: off = imm5 * 4; op = "LDR" if L else "STR"
        return f"{op} r{rd}, [r{rn}, #0x{off:X}]"
    if (hw >> 13) == 0x04 and not ((hw >> 12) & 1):
        L = (hw >> 11) & 1; imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 7; rd = hw & 7
        return f"{'LDRH' if L else 'STRH'} r{rd}, [r{rn}, #0x{imm5*2:X}]"
    if (hw >> 12) == 0x09:
        L = (hw >> 11) & 1; rd = (hw >> 8) & 7; imm = (hw & 0xFF) * 4
        return f"{'LDR' if L else 'STR'} r{rd}, [sp, #0x{imm:X}]"
    if (hw & 0xFF80) == 0x4700:
        rm = (hw >> 3) & 0xF
        n = {13:"sp",14:"lr",15:"pc"}.get(rm, f"r{rm}")
        return f"BX {n}"
    if (hw & 0xFF00) == 0x4600:
        D = (hw >> 7) & 1; rd = (hw & 7) | (D << 3); rm = (hw >> 3) & 0xF
        n_d = {13:"sp",14:"lr",15:"pc"}.get(rd, f"r{rd}")
        n_m = {13:"sp",14:"lr",15:"pc"}.get(rm, f"r{rm}")
        return f"MOV {n_d}, {n_m}"
    if (hw >> 12) == 0xD:
        cond = (hw >> 8) & 0xF
        if cond < 0xE:
            off = sign_ext(hw & 0xFF, 8)
            target = addr + 4 + off * 2
            cn = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE"][cond]
            return f"{cn} 0x{target:08X}"
    if (hw >> 11) == 0x1C:
        off = sign_ext(hw & 0x7FF, 11)
        target = addr + 4 + off * 2
        return f"B 0x{target:08X}"
    if (hw >> 10) == 0x10:
        op = (hw >> 6) & 0xF
        rm = (hw >> 3) & 7; rd = hw & 7
        ops = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
               "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
        return f"{ops[op]} r{rd}, r{rm}"
    if (hw >> 11) == 0x00:
        imm5 = (hw >> 6) & 0x1F; rm = (hw >> 3) & 7; rd = hw & 7
        if imm5 == 0: return f"MOV r{rd}, r{rm}"
        return f"LSL r{rd}, r{rm}, #{imm5}"
    if (hw >> 11) == 0x01:
        imm5 = (hw >> 6) & 0x1F; rm = (hw >> 3) & 7; rd = hw & 7
        if imm5 == 0: imm5 = 32
        return f"LSR r{rd}, r{rm}, #{imm5}"
    if (hw >> 9) == 0x0E:
        imm3 = (hw >> 6) & 7; rn = (hw >> 3) & 7; rd = hw & 7
        return f"ADD r{rd}, r{rn}, #{imm3}"
    if (hw >> 9) == 0x0F:
        imm3 = (hw >> 6) & 7; rn = (hw >> 3) & 7; rd = hw & 7
        return f"SUB r{rd}, r{rn}, #{imm3}"
    if (hw >> 12) == 0x5:
        opcode = (hw >> 9) & 7; rm = (hw >> 6) & 7; rn = (hw >> 3) & 7; rd = hw & 7
        ops = ["STR","STRH","STRB","LDRSB","LDR","LDRH","LDRB","LDRSH"]
        return f"{ops[opcode]} r{rd}, [r{rn}, r{rm}]"
    return f".short 0x{hw:04X}"

def disasm_print(rom_offset, base, size=128, max_inst=50):
    data = read_rom(rom_offset, size)
    i = 0
    count = 0
    while i < len(data) and count < max_inst:
        hw = struct.unpack_from("<H", data, i)[0]
        addr = base + i
        if (hw >> 11) == 0x1E and i + 3 < len(data):
            hw2 = struct.unpack_from("<H", data, i + 2)[0]
            if (hw2 >> 11) in (0x1F, 0x1D):
                off_hi = sign_ext(hw & 0x7FF, 11) << 12
                off_lo = (hw2 & 0x7FF) << 1
                target = (addr + 4 + off_hi + off_lo) & 0xFFFFFFFF
                sfx = "BL" if (hw2 >> 11) == 0x1F else "BLX"
                print(f"  {addr:08X}: {hw:04X} {hw2:04X}  {sfx} 0x{target:08X}")
                i += 4; count += 1; continue
        txt = decode(hw, addr)
        print(f"  {addr:08X}: {hw:04X}      {txt}")
        i += 2; count += 1


# Find the start of the setup function that stores 0x0806FBF5 into gBattlerControllerFuncs
# Look backwards from 0x0806FB70 for PUSH
print("=" * 74)
print("Setup function (stores 0x0806FBF5 into gBattlerControllerFuncs)")
print("Looking back from 0x0806FB50")
print("=" * 74)
disasm_print(0x06FB20, 0x0806FB20, 160, 50)

print()
print("=" * 74)
print("BL target 0x0806F924 (called at start of setup func)")
print("=" * 74)
disasm_print(0x06F924, 0x0806F924, 64, 20)

# What function is at 0x08039974? (DoBounceEffect)
print()
print("=" * 74)
print("0x08039974 (DoBounceEffect)")
print("=" * 74)
disasm_print(0x039974, 0x08039974, 64, 16)

# Also, look at what's at 0x080C1544 (called from Function 2 with arg 5)
# This is PlaySE with sound 5
print()
print("=" * 74)
print("BL 0x080C1544 - PlaySE wrapper? (called with 0x5)")
print("=" * 74)
disasm_print(0x0C1544, 0x080C1544, 32, 8)

# Check what 0xAE is at 0x0806FC6E: CMP r0, #0xAE (174 decimal)
print()
print("Check: 0xAE = 174 decimal")
print("MOVE_STRUGGLE = 165 in vanilla, but R&B expansion has different IDs")
print()

# What about the gBattleStruct at 0x03005DA0? Check offset 0x13
print("gBattleStruct ptr at 0x03005DA0, [ptr+0x13] compared to 2")
print("Offset 0x13 in BattleStruct could be related to turnEffectsTracker")
