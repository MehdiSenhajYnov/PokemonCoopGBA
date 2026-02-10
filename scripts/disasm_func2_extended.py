#!/usr/bin/env python3
"""Extended disassembly of Function 2 with more context."""
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

def disasm(data, base, max_inst=80):
    lines = []
    i = 0
    while i < len(data) and len(lines) < max_inst:
        if i + 1 >= len(data):
            break
        hw = struct.unpack_from("<H", data, i)[0]
        addr = base + i

        # BL 32-bit
        if (hw >> 11) == 0x1E and i + 3 < len(data):
            hw2 = struct.unpack_from("<H", data, i + 2)[0]
            if (hw2 >> 11) in (0x1F, 0x1D):
                off_hi = sign_ext(hw & 0x7FF, 11) << 12
                off_lo = (hw2 & 0x7FF) << 1
                target = (addr + 4 + off_hi + off_lo) & 0xFFFFFFFF
                sfx = "BL" if (hw2 >> 11) == 0x1F else "BLX"
                lines.append((addr, f"{hw:04X} {hw2:04X}", f"{sfx} 0x{target:08X}"))
                i += 4
                continue

        txt = decode(hw, addr)
        lines.append((addr, f"{hw:04X}    ", txt))
        i += 2
    return lines

def decode(hw, addr):
    # PUSH
    if (hw & 0xFE00) == 0xB400:
        regs = [f"r{b}" for b in range(8) if hw & (1 << b)]
        if hw & 0x100: regs.append("lr")
        return f"PUSH {{{', '.join(regs)}}}"
    # POP
    if (hw & 0xFE00) == 0xBC00:
        regs = [f"r{b}" for b in range(8) if hw & (1 << b)]
        if hw & 0x100: regs.append("pc")
        return f"POP {{{', '.join(regs)}}}"
    # SP adjust
    if (hw & 0xFF00) == 0xB000:
        imm = (hw & 0x7F) * 4
        return f"{'SUB' if hw & 0x80 else 'ADD'} sp, #0x{imm:X}"
    # MOV imm
    if (hw >> 11) == 0x04:
        return f"MOV r{(hw>>8)&7}, #0x{hw&0xFF:X}"
    # CMP imm
    if (hw >> 11) == 0x05:
        return f"CMP r{(hw>>8)&7}, #0x{hw&0xFF:X}"
    # ADD imm
    if (hw >> 11) == 0x06:
        return f"ADD r{(hw>>8)&7}, #0x{hw&0xFF:X}"
    # SUB imm
    if (hw >> 11) == 0x07:
        return f"SUB r{(hw>>8)&7}, #0x{hw&0xFF:X}"
    # LDR PC-relative
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
    # LDR/STR imm offset
    if (hw >> 13) == 0x03:
        L = (hw >> 11) & 1; B = (hw >> 12) & 1
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 7; rd = hw & 7
        if B: off = imm5; op = "LDRB" if L else "STRB"
        else: off = imm5 * 4; op = "LDR" if L else "STR"
        return f"{op} r{rd}, [r{rn}, #0x{off:X}]"
    # LDRH/STRH imm
    if (hw >> 13) == 0x04 and not ((hw >> 12) & 1):
        L = (hw >> 11) & 1; imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 7; rd = hw & 7
        return f"{'LDRH' if L else 'STRH'} r{rd}, [r{rn}, #0x{imm5*2:X}]"
    # STR/LDR SP-relative
    if (hw >> 12) == 0x09:
        L = (hw >> 11) & 1; rd = (hw >> 8) & 7; imm = (hw & 0xFF) * 4
        return f"{'LDR' if L else 'STR'} r{rd}, [sp, #0x{imm:X}]"
    # BX
    if (hw & 0xFF80) == 0x4700:
        rm = (hw >> 3) & 0xF
        n = {13:"sp",14:"lr",15:"pc"}.get(rm, f"r{rm}")
        return f"BX {n}"
    # MOV high
    if (hw & 0xFF00) == 0x4600:
        D = (hw >> 7) & 1; rd = (hw & 7) | (D << 3); rm = (hw >> 3) & 0xF
        n_d = {13:"sp",14:"lr",15:"pc"}.get(rd, f"r{rd}")
        n_m = {13:"sp",14:"lr",15:"pc"}.get(rm, f"r{rm}")
        return f"MOV {n_d}, {n_m}"
    # CMP high
    if (hw & 0xFF00) == 0x4500:
        N = (hw >> 7) & 1; rn = (hw & 7) | (N << 3); rm = (hw >> 3) & 0xF
        n_n = {13:"sp",14:"lr",15:"pc"}.get(rn, f"r{rn}")
        n_m = {13:"sp",14:"lr",15:"pc"}.get(rm, f"r{rm}")
        return f"CMP {n_n}, {n_m}"
    # ADD high
    if (hw & 0xFF00) == 0x4400:
        D = (hw >> 7) & 1; rd = (hw & 7) | (D << 3); rm = (hw >> 3) & 0xF
        n_d = {13:"sp",14:"lr",15:"pc"}.get(rd, f"r{rd}")
        n_m = {13:"sp",14:"lr",15:"pc"}.get(rm, f"r{rm}")
        return f"ADD {n_d}, {n_m}"
    # Cond branch
    if (hw >> 12) == 0xD:
        cond = (hw >> 8) & 0xF
        if cond < 0xE:
            off = sign_ext(hw & 0xFF, 8)
            target = addr + 4 + off * 2
            cn = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE"][cond]
            return f"{cn} 0x{target:08X}"
        elif cond == 0xF:
            return f"SWI #{hw & 0xFF}"
    # Unconditional branch
    if (hw >> 11) == 0x1C:
        off = sign_ext(hw & 0x7FF, 11)
        target = addr + 4 + off * 2
        return f"B 0x{target:08X}"
    # ALU
    if (hw >> 10) == 0x10:
        op = (hw >> 6) & 0xF
        rm = (hw >> 3) & 7; rd = hw & 7
        ops = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
               "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
        return f"{ops[op]} r{rd}, r{rm}"
    # LSL imm
    if (hw >> 11) == 0x00:
        imm5 = (hw >> 6) & 0x1F; rm = (hw >> 3) & 7; rd = hw & 7
        if imm5 == 0: return f"MOV r{rd}, r{rm}"
        return f"LSL r{rd}, r{rm}, #{imm5}"
    # LSR imm
    if (hw >> 11) == 0x01:
        imm5 = (hw >> 6) & 0x1F; rm = (hw >> 3) & 7; rd = hw & 7
        if imm5 == 0: imm5 = 32
        return f"LSR r{rd}, r{rm}, #{imm5}"
    # ASR imm
    if (hw >> 11) == 0x02:
        imm5 = (hw >> 6) & 0x1F; rm = (hw >> 3) & 7; rd = hw & 7
        if imm5 == 0: imm5 = 32
        return f"ASR r{rd}, r{rm}, #{imm5}"
    # ADD 3-reg / imm3
    if (hw >> 9) == 0x06:
        rm = (hw >> 6) & 7; rn = (hw >> 3) & 7; rd = hw & 7
        return f"ADD r{rd}, r{rn}, r{rm}"
    if (hw >> 9) == 0x07:
        rm = (hw >> 6) & 7; rn = (hw >> 3) & 7; rd = hw & 7
        return f"SUB r{rd}, r{rn}, r{rm}"
    if (hw >> 9) == 0x0E:
        imm3 = (hw >> 6) & 7; rn = (hw >> 3) & 7; rd = hw & 7
        return f"ADD r{rd}, r{rn}, #{imm3}"
    if (hw >> 9) == 0x0F:
        imm3 = (hw >> 6) & 7; rn = (hw >> 3) & 7; rd = hw & 7
        return f"SUB r{rd}, r{rn}, #{imm3}"
    # Register load/store
    if (hw >> 12) == 0x5:
        opcode = (hw >> 9) & 7; rm = (hw >> 6) & 7; rn = (hw >> 3) & 7; rd = hw & 7
        ops = ["STR","STRH","STRB","LDRSB","LDR","LDRH","LDRB","LDRSH"]
        return f"{ops[opcode]} r{rd}, [r{rn}, r{rm}]"
    # ADD PC/SP
    if (hw >> 11) == 0x14:
        return f"ADD r{(hw>>8)&7}, pc, #0x{(hw&0xFF)*4:X}"
    if (hw >> 11) == 0x15:
        return f"ADD r{(hw>>8)&7}, sp, #0x{(hw&0xFF)*4:X}"
    # LDMIA/STMIA
    if (hw >> 12) == 0xC:
        L = (hw >> 11) & 1; rn = (hw >> 8) & 7
        regs = [f"r{b}" for b in range(8) if hw & (1 << b)]
        return f"{'LDMIA' if L else 'STMIA'} r{rn}!, {{{', '.join(regs)}}}"

    return f".short 0x{hw:04X}"


# Function 2 - extended dump (512 bytes to find all the code)
print("=" * 74)
print("Function 2: 0x0806FBF5 (offset 0x06FBF4) - FULL")
print("=" * 74)
data = read_rom(0x06FBF4, 1024)
for addr, enc, txt in disasm(data, 0x0806FBF4, 80):
    print(f"  {addr:08X}: {enc}  {txt}")

# Also identify the function at the previous POP/BX boundary
# The function before 0x06FBF4 ends at 0x06FBE4 (POP {r4,r5} + POP {r0} + BX r0)
print()
print("=" * 74)
print("Key literal pool values for Function 2:")
print("=" * 74)
# Pool values between instructions
addrs = [0x0806FC30, 0x0806FC34, 0x0806FC38, 0x0806FC3C, 0x0806FC40,
         0x0806FC98, 0x0806FC9C, 0x0806FCA0]
for a in addrs:
    val = read_u32(a - 0x08000000)
    print(f"  0x{a:08X}: 0x{val:08X}")

# Check what the function at 0x0806FBE6 is (right before Function 2)
print()
print("=" * 74)
print("Function BEFORE: ending at 0x0806FBE4 (context)")
print("=" * 74)
pre_data = read_rom(0x06FB70, 132)
for addr, enc, txt in disasm(pre_data, 0x0806FB70, 30):
    print(f"  {addr:08X}: {enc}  {txt}")

# BL targets
print()
print("=" * 74)
print("BL target 0x080C1544 (from Function 2)")
print("=" * 74)
bl_data = read_rom(0x0C1544, 32)
for addr, enc, txt in disasm(bl_data, 0x080C1544, 8):
    print(f"  {addr:08X}: {enc}  {txt}")
