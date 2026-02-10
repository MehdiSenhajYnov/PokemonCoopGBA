#!/usr/bin/env python3
"""Disassemble two THUMB functions from the Pokemon Run & Bun ROM."""
import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom_bytes(offset, length):
    with open(ROM_PATH, "rb") as f:
        f.seek(offset)
        return f.read(length)

def sign_extend(value, bits):
    if value & (1 << (bits - 1)):
        value -= (1 << bits)
    return value

def disasm_thumb(data, base_addr, max_instructions=40):
    """Simple THUMB disassembler - handles common instructions."""
    lines = []
    i = 0
    while i < len(data) and len(lines) < max_instructions:
        if i + 1 >= len(data):
            break
        hw = struct.unpack_from("<H", data, i)[0]
        addr = base_addr + i

        # 32-bit BL instruction
        if (hw >> 11) == 0x1E:  # F000-F7FF prefix
            if i + 3 < len(data):
                hw2 = struct.unpack_from("<H", data, i + 2)[0]
                if (hw2 >> 11) in (0x1F, 0x1D):  # BL or BLX suffix
                    offset_hi = sign_extend((hw & 0x7FF), 11) << 12
                    offset_lo = (hw2 & 0x7FF) << 1
                    target = (addr + 4 + offset_hi + offset_lo) & 0xFFFFFFFF
                    suffix = "BL" if (hw2 >> 11) == 0x1F else "BLX"
                    lines.append(f"  {addr:08X}: {hw:04X} {hw2:04X}  {suffix} 0x{target:08X}")
                    i += 4
                    continue

        # Decode common THUMB instructions
        decoded = decode_thumb(hw, addr, data, i)
        lines.append(f"  {addr:08X}: {hw:04X}        {decoded}")
        i += 2
    return lines

def decode_thumb(hw, addr, data, offset):
    """Decode a single THUMB instruction."""

    # PUSH
    if (hw & 0xFE00) == 0xB400:
        regs = []
        for bit in range(8):
            if hw & (1 << bit):
                regs.append(f"r{bit}")
        if hw & 0x100:
            regs.append("lr")
        return f"PUSH {{{', '.join(regs)}}}"

    # POP
    if (hw & 0xFE00) == 0xBC00:
        regs = []
        for bit in range(8):
            if hw & (1 << bit):
                regs.append(f"r{bit}")
        if hw & 0x100:
            regs.append("pc")
        return f"POP {{{', '.join(regs)}}}"

    # ADD/SUB SP
    if (hw & 0xFF00) == 0xB000:
        imm = (hw & 0x7F) * 4
        if hw & 0x80:
            return f"SUB sp, #0x{imm:X}"
        else:
            return f"ADD sp, #0x{imm:X}"

    # MOV Rd, #imm
    if (hw >> 11) == 0x04:
        rd = (hw >> 8) & 7
        imm = hw & 0xFF
        return f"MOV r{rd}, #0x{imm:X}"

    # CMP Rd, #imm
    if (hw >> 11) == 0x05:
        rd = (hw >> 8) & 7
        imm = hw & 0xFF
        return f"CMP r{rd}, #0x{imm:X}"

    # ADD Rd, #imm
    if (hw >> 11) == 0x06:
        rd = (hw >> 8) & 7
        imm = hw & 0xFF
        return f"ADD r{rd}, #0x{imm:X}"

    # SUB Rd, #imm
    if (hw >> 11) == 0x07:
        rd = (hw >> 8) & 7
        imm = hw & 0xFF
        return f"SUB r{rd}, #0x{imm:X}"

    # LDR Rd, [PC, #imm] (literal pool load)
    if (hw >> 11) == 0x09:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        pc_val = (addr + 4) & ~2
        pool_addr = pc_val + imm
        # Try to read the pool value
        rom_offset = pool_addr - 0x08000000
        if 0 <= rom_offset < 0x02000000:
            try:
                pool_data = read_rom_bytes(rom_offset, 4)
                pool_val = struct.unpack_from("<I", pool_data, 0)[0]
                return f"LDR r{rd}, [pc, #0x{imm:X}]  ; =0x{pool_val:08X} (@0x{pool_addr:08X})"
            except:
                pass
        return f"LDR r{rd}, [pc, #0x{imm:X}]  ; @0x{pool_addr:08X}"

    # LDR Rd, [Rn, #imm5*4]
    if (hw >> 13) == 0x03:
        L = (hw >> 11) & 1
        B = (hw >> 12) & 1
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 7
        rd = hw & 7
        if B:
            off = imm5
            op = "LDRB" if L else "STRB"
        else:
            off = imm5 * 4
            op = "LDR" if L else "STR"
        return f"{op} r{rd}, [r{rn}, #0x{off:X}]"

    # LDRH/STRH with imm offset
    if (hw >> 13) == 0x04 and not ((hw >> 12) & 1):
        L = (hw >> 11) & 1
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 7
        rd = hw & 7
        off = imm5 * 2
        op = "LDRH" if L else "STRH"
        return f"{op} r{rd}, [r{rn}, #0x{off:X}]"

    # LDR/STR SP-relative
    if (hw >> 12) == 0x09:
        L = (hw >> 11) & 1
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        op = "LDR" if L else "STR"
        return f"{op} r{rd}, [sp, #0x{imm:X}]"

    # BX Rm
    if (hw & 0xFF80) == 0x4700:
        rm = (hw >> 3) & 0xF
        rnames = {13: "sp", 14: "lr", 15: "pc"}
        rn = rnames.get(rm, f"r{rm}")
        return f"BX {rn}"

    # MOV high register
    if (hw & 0xFF00) == 0x4600:
        D = (hw >> 7) & 1
        rd = (hw & 7) | (D << 3)
        rm = (hw >> 3) & 0xF
        rnames = {13: "sp", 14: "lr", 15: "pc"}
        rn_d = rnames.get(rd, f"r{rd}")
        rn_m = rnames.get(rm, f"r{rm}")
        return f"MOV {rn_d}, {rn_m}"

    # CMP high register
    if (hw & 0xFF00) == 0x4500:
        N = (hw >> 7) & 1
        rn = (hw & 7) | (N << 3)
        rm = (hw >> 3) & 0xF
        rnames = {13: "sp", 14: "lr", 15: "pc"}
        rn_n = rnames.get(rn, f"r{rn}")
        rn_m = rnames.get(rm, f"r{rm}")
        return f"CMP {rn_n}, {rn_m}"

    # ADD high register
    if (hw & 0xFF00) == 0x4400:
        D = (hw >> 7) & 1
        rd = (hw & 7) | (D << 3)
        rm = (hw >> 3) & 0xF
        rnames = {13: "sp", 14: "lr", 15: "pc"}
        rn_d = rnames.get(rd, f"r{rd}")
        rn_m = rnames.get(rm, f"r{rm}")
        return f"ADD {rn_d}, {rn_m}"

    # LSL Rd, Rm, #imm5
    if (hw >> 11) == 0x00:
        imm5 = (hw >> 6) & 0x1F
        rm = (hw >> 3) & 7
        rd = hw & 7
        if imm5 == 0 and rm == rd:
            return f"MOV r{rd}, r{rm}" if rd != rm else "NOP"  # LSL r0, r0, #0
        return f"LSL r{rd}, r{rm}, #{imm5}"

    # LSR Rd, Rm, #imm5
    if (hw >> 11) == 0x01:
        imm5 = (hw >> 6) & 0x1F
        if imm5 == 0:
            imm5 = 32
        rm = (hw >> 3) & 7
        rd = hw & 7
        return f"LSR r{rd}, r{rm}, #{imm5}"

    # ASR Rd, Rm, #imm5
    if (hw >> 11) == 0x02:
        imm5 = (hw >> 6) & 0x1F
        if imm5 == 0:
            imm5 = 32
        rm = (hw >> 3) & 7
        rd = hw & 7
        return f"ASR r{rd}, r{rm}, #{imm5}"

    # ADD/SUB 3-reg
    if (hw >> 9) == 0x06:  # ADD Rd, Rn, Rm
        rm = (hw >> 6) & 7
        rn = (hw >> 3) & 7
        rd = hw & 7
        return f"ADD r{rd}, r{rn}, r{rm}"
    if (hw >> 9) == 0x07:  # SUB Rd, Rn, Rm
        rm = (hw >> 6) & 7
        rn = (hw >> 3) & 7
        rd = hw & 7
        return f"SUB r{rd}, r{rn}, r{rm}"

    # ADD Rd, Rn, #imm3
    if (hw >> 9) == 0x0E:
        imm3 = (hw >> 6) & 7
        rn = (hw >> 3) & 7
        rd = hw & 7
        return f"ADD r{rd}, r{rn}, #{imm3}"

    # SUB Rd, Rn, #imm3
    if (hw >> 9) == 0x0F:
        imm3 = (hw >> 6) & 7
        rn = (hw >> 3) & 7
        rd = hw & 7
        return f"SUB r{rd}, r{rn}, #{imm3}"

    # ALU operations
    if (hw >> 10) == 0x10:
        op = (hw >> 6) & 0xF
        rm = (hw >> 3) & 7
        rd = hw & 7
        alu_ops = ["AND", "EOR", "LSL", "LSR", "ASR", "ADC", "SBC", "ROR",
                   "TST", "NEG", "CMP", "CMN", "ORR", "MUL", "BIC", "MVN"]
        return f"{alu_ops[op]} r{rd}, r{rm}"

    # Conditional branch
    if (hw >> 12) == 0xD:
        cond = (hw >> 8) & 0xF
        if cond < 0xE:
            offset8 = sign_extend(hw & 0xFF, 8)
            target = addr + 4 + offset8 * 2
            cond_names = ["BEQ", "BNE", "BCS", "BCC", "BMI", "BPL", "BVS", "BVC",
                          "BHI", "BLS", "BGE", "BLT", "BGT", "BLE"]
            return f"{cond_names[cond]} 0x{target:08X}"
        elif cond == 0xE:
            return f"UND #{hw & 0xFF}"
        else:
            return f"SWI #{hw & 0xFF}"

    # Unconditional branch
    if (hw >> 11) == 0x1C:
        offset11 = sign_extend(hw & 0x7FF, 11)
        target = addr + 4 + offset11 * 2
        return f"B 0x{target:08X}"

    # Register offset load/store (format 7/8)
    if (hw >> 12) == 0x5:
        opcode = (hw >> 9) & 0x7
        rm = (hw >> 6) & 7
        rn = (hw >> 3) & 7
        rd = hw & 7
        ops = ["STR", "STRH", "STRB", "LDRSB", "LDR", "LDRH", "LDRB", "LDRSH"]
        return f"{ops[opcode]} r{rd}, [r{rn}, r{rm}]"

    # ADD Rd, PC, #imm
    if (hw >> 11) == 0x14:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        return f"ADD r{rd}, pc, #0x{imm:X}"

    # ADD Rd, SP, #imm
    if (hw >> 11) == 0x15:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        return f"ADD r{rd}, sp, #0x{imm:X}"

    # LDMIA/STMIA
    if (hw >> 12) == 0xC:
        L = (hw >> 11) & 1
        rn = (hw >> 8) & 7
        regs = []
        for bit in range(8):
            if hw & (1 << bit):
                regs.append(f"r{bit}")
        op = "LDMIA" if L else "STMIA"
        return f"{op} r{rn}!, {{{', '.join(regs)}}}"

    return f".short 0x{hw:04X}"


def main():
    print("=" * 70)
    print("Function 1: 0x08071BD9 (offset 0x071BD8)")
    print("Near Controller_WaitForString at 0x08071B64")
    print("=" * 70)
    data1 = read_rom_bytes(0x071BD8, 128)
    print(f"Raw hex: {data1[:64].hex()}")
    print()
    for line in disasm_thumb(data1, 0x08071BD8, 40):
        print(line)

    print()
    print("=" * 70)
    print("Function 2: 0x0806FBF5 (offset 0x06FBF4)")
    print("In the player controller area")
    print("=" * 70)
    data2 = read_rom_bytes(0x06FBF4, 128)
    print(f"Raw hex: {data2[:64].hex()}")
    print()
    for line in disasm_thumb(data2, 0x0806FBF4, 40):
        print(line)

    # Also look at what's before each function for context
    print()
    print("=" * 70)
    print("Context: 32 bytes BEFORE 0x071BD8 (end of previous function)")
    print("=" * 70)
    pre1 = read_rom_bytes(0x071BA0, 56)
    for line in disasm_thumb(pre1, 0x08071BA0, 20):
        print(line)

    print()
    print("=" * 70)
    print("Context: 32 bytes BEFORE 0x06FBF4 (end of previous function)")
    print("=" * 70)
    pre2 = read_rom_bytes(0x06FBC0, 52)
    for line in disasm_thumb(pre2, 0x0806FBC0, 20):
        print(line)

    # Read literal pool values referenced by the functions
    print()
    print("=" * 70)
    print("Literal pool scan around 0x071BD8")
    print("=" * 70)
    # Scan for literal pools after the function
    pool_data = read_rom_bytes(0x071C00, 64)
    for j in range(0, 64, 4):
        val = struct.unpack_from("<I", pool_data, j)[0]
        pool_addr = 0x08071C00 + j
        print(f"  0x{pool_addr:08X}: 0x{val:08X}")


if __name__ == "__main__":
    main()
