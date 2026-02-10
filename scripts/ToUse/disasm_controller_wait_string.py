"""
Disassemble THUMB code at ROM offset 0x071B64 (Controller_WaitForString @ 0x08071B64)
and also 0x071B30 (preceding function context).

Reads raw bytes from the ROM and decodes ARM THUMB (16-bit) instructions.
"""

import struct
import sys
import os

ROM_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "rom", "Pokemon RunBun.gba")

def read_rom_bytes(rom_path, offset, length):
    """Read `length` bytes from ROM at `offset`."""
    with open(rom_path, "rb") as f:
        f.seek(offset)
        data = f.read(length)
    return data

def decode_thumb_reg(r):
    """Return register name."""
    names = ["r0","r1","r2","r3","r4","r5","r6","r7",
             "r8","r9","r10","r11","r12","sp","lr","pc"]
    if 0 <= r <= 15:
        return names[r]
    return f"r{r}"

def sign_extend(value, bits):
    """Sign-extend a `bits`-wide value."""
    if value & (1 << (bits - 1)):
        value -= (1 << bits)
    return value

def decode_thumb_instruction(hw, addr):
    """
    Decode a single 16-bit THUMB instruction.
    Returns (mnemonic, description) string.
    """
    # --- Format 1: Move shifted register ---
    if (hw >> 13) == 0b000:
        op = (hw >> 11) & 0x3
        offset5 = (hw >> 6) & 0x1F
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        ops = ["LSL", "LSR", "ASR"]
        if op < 3:
            return f"{ops[op]} {decode_thumb_reg(rd)}, {decode_thumb_reg(rs)}, #{offset5}"

    # --- Format 2: Add/subtract ---
    if (hw >> 11) == 0b00011:
        i = (hw >> 10) & 1
        op = (hw >> 9) & 1
        rn_or_imm = (hw >> 6) & 0x7
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        opname = "SUB" if op else "ADD"
        if i:
            return f"{opname} {decode_thumb_reg(rd)}, {decode_thumb_reg(rs)}, #{rn_or_imm}"
        else:
            return f"{opname} {decode_thumb_reg(rd)}, {decode_thumb_reg(rs)}, {decode_thumb_reg(rn_or_imm)}"

    # --- Format 3: Move/compare/add/subtract immediate ---
    if (hw >> 13) == 0b001:
        op = (hw >> 11) & 0x3
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        ops = ["MOV", "CMP", "ADD", "SUB"]
        return f"{ops[op]} {decode_thumb_reg(rd)}, #0x{imm8:02X} (={imm8})"

    # --- Format 4: ALU operations ---
    if (hw >> 10) == 0b010000:
        op = (hw >> 6) & 0xF
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        ops = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
               "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
        return f"{ops[op]} {decode_thumb_reg(rd)}, {decode_thumb_reg(rs)}"

    # --- Format 5: Hi register operations / BX ---
    if (hw >> 10) == 0b010001:
        op = (hw >> 8) & 0x3
        h1 = (hw >> 7) & 1
        h2 = (hw >> 6) & 1
        rs = ((h2 << 3) | ((hw >> 3) & 0x7))
        rd = ((h1 << 3) | (hw & 0x7))
        if op == 0:
            return f"ADD {decode_thumb_reg(rd)}, {decode_thumb_reg(rs)}"
        elif op == 1:
            return f"CMP {decode_thumb_reg(rd)}, {decode_thumb_reg(rs)}"
        elif op == 2:
            return f"MOV {decode_thumb_reg(rd)}, {decode_thumb_reg(rs)}"
        elif op == 3:
            return f"BX {decode_thumb_reg(rs)}"

    # --- Format 6: PC-relative load (LDR Rd, [PC, #imm]) ---
    if (hw >> 11) == 0b01001:
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        offset = imm8 * 4
        # PC is (current_addr + 4) & ~2
        pc_val = (addr + 4) & ~2
        target = pc_val + offset
        return f"LDR {decode_thumb_reg(rd)}, [PC, #0x{offset:X}]  ; =0x{target:08X}"

    # --- Format 7/8: Load/store with register offset ---
    if (hw >> 12) == 0b0101:
        opcode = (hw >> 9) & 0x7
        ro = (hw >> 6) & 0x7
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        ops = ["STR","STRH","STRB","LDRSB","LDR","LDRH","LDRB","LDRSH"]
        return f"{ops[opcode]} {decode_thumb_reg(rd)}, [{decode_thumb_reg(rb)}, {decode_thumb_reg(ro)}]"

    # --- Format 9: Load/store with immediate offset ---
    if (hw >> 13) == 0b011:
        b = (hw >> 12) & 1
        l = (hw >> 11) & 1
        offset5 = (hw >> 6) & 0x1F
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        if b:
            off = offset5
            op = "LDRB" if l else "STRB"
        else:
            off = offset5 * 4
            op = "LDR" if l else "STR"
        return f"{op} {decode_thumb_reg(rd)}, [{decode_thumb_reg(rb)}, #0x{off:X}]"

    # --- Format 10: Load/store halfword ---
    if (hw >> 12) == 0b1000:
        l = (hw >> 11) & 1
        offset5 = (hw >> 6) & 0x1F
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        off = offset5 * 2
        op = "LDRH" if l else "STRH"
        return f"{op} {decode_thumb_reg(rd)}, [{decode_thumb_reg(rb)}, #0x{off:X}]"

    # --- Format 11: SP-relative load/store ---
    if (hw >> 12) == 0b1001:
        l = (hw >> 11) & 1
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        off = imm8 * 4
        op = "LDR" if l else "STR"
        return f"{op} {decode_thumb_reg(rd)}, [SP, #0x{off:X}]"

    # --- Format 12: Load address (ADD Rd, PC/SP, #imm) ---
    if (hw >> 12) == 0b1010:
        sp = (hw >> 11) & 1
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        off = imm8 * 4
        src = "SP" if sp else "PC"
        return f"ADD {decode_thumb_reg(rd)}, {src}, #0x{off:X}"

    # --- Format 13: Add offset to SP ---
    if (hw >> 8) == 0b10110000:
        s = (hw >> 7) & 1
        imm7 = hw & 0x7F
        off = imm7 * 4
        if s:
            return f"ADD SP, #-0x{off:X}"
        else:
            return f"ADD SP, #0x{off:X}"

    # --- Format 14: Push/pop ---
    if (hw >> 12) == 0b1011:
        if ((hw >> 9) & 0x3) == 0b10:
            l = (hw >> 11) & 1
            r = (hw >> 8) & 1
            rlist = hw & 0xFF
            regs = []
            for i in range(8):
                if rlist & (1 << i):
                    regs.append(decode_thumb_reg(i))
            if l:
                if r: regs.append("pc")
                return f"POP {{{', '.join(regs)}}}"
            else:
                if r: regs.append("lr")
                return f"PUSH {{{', '.join(regs)}}}"

    # --- Format 15: Multiple load/store ---
    if (hw >> 12) == 0b1100:
        l = (hw >> 11) & 1
        rb = (hw >> 8) & 0x7
        rlist = hw & 0xFF
        regs = []
        for i in range(8):
            if rlist & (1 << i):
                regs.append(decode_thumb_reg(i))
        op = "LDMIA" if l else "STMIA"
        return f"{op} {decode_thumb_reg(rb)}!, {{{', '.join(regs)}}}"

    # --- Format 16: Conditional branch ---
    if (hw >> 12) == 0b1101:
        cond = (hw >> 8) & 0xF
        if cond == 0xF:
            # SWI
            imm8 = hw & 0xFF
            return f"SWI #0x{imm8:02X}"
        if cond < 0xE:
            offset8 = hw & 0xFF
            offset = sign_extend(offset8, 8) * 2
            target = addr + 4 + offset
            conds = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                     "BHI","BLS","BGE","BLT","BGT","BLE"]
            return f"{conds[cond]} 0x{target:08X}  ; offset={offset:+d}"

    # --- Format 17: SWI ---
    if (hw >> 8) == 0b11011111:
        imm8 = hw & 0xFF
        return f"SWI #0x{imm8:02X}"

    # --- Format 18: Unconditional branch ---
    if (hw >> 11) == 0b11100:
        offset11 = hw & 0x7FF
        offset = sign_extend(offset11, 11) * 2
        target = addr + 4 + offset
        return f"B 0x{target:08X}  ; offset={offset:+d}"

    # --- Format 19: Long branch with link (BL) ---
    # Note: BL is a 32-bit instruction (two 16-bit halfwords).
    # We only decode the first half here; the caller handles pairing.
    if (hw >> 11) == 0b11110:
        offset11 = hw & 0x7FF
        return f"BL_PREFIX (high offset=0x{offset11:03X})"
    if (hw >> 11) == 0b11111:
        offset11 = hw & 0x7FF
        return f"BL_SUFFIX (low offset=0x{offset11:03X})"

    # --- NOP (MOV r8, r8) ---
    if hw == 0x46C0:
        return "NOP  ; MOV r8, r8"

    return f"??? (0x{hw:04X})"


def disassemble_thumb(data, base_addr):
    """Disassemble a block of THUMB code."""
    results = []
    i = 0
    while i < len(data) - 1:
        hw = struct.unpack_from("<H", data, i)[0]
        addr = base_addr + i
        mnemonic = decode_thumb_instruction(hw, addr)

        # Check for BL (32-bit: prefix + suffix)
        if (hw >> 11) == 0b11110 and i + 2 < len(data):
            hw2 = struct.unpack_from("<H", data, i + 2)[0]
            if (hw2 >> 11) == 0b11111:
                # Full BL instruction
                offset_high = sign_extend(hw & 0x7FF, 11) << 12
                offset_low = (hw2 & 0x7FF) << 1
                target = addr + 4 + offset_high + offset_low
                mnemonic = f"BL 0x{target:08X}"
                results.append((addr, hw, hw2, mnemonic, True))
                i += 4
                continue

        results.append((addr, hw, None, mnemonic, False))
        i += 2

    return results


def main():
    rom_path = ROM_PATH
    if not os.path.exists(rom_path):
        print(f"ERROR: ROM not found at {rom_path}")
        sys.exit(1)

    print(f"ROM: {rom_path}")
    print(f"File size: {os.path.getsize(rom_path):,} bytes")
    print()

    # --- Region 1: Before Controller_WaitForString (0x071B30) ---
    print("=" * 80)
    print("REGION 1: ROM offset 0x071B30 (addr 0x08071B30) — preceding context")
    print("=" * 80)
    data1 = read_rom_bytes(rom_path, 0x071B30, 52)  # Read 52 bytes (up to 0x071B64)
    print(f"Raw bytes ({len(data1)} bytes):")
    for j in range(0, len(data1), 16):
        chunk = data1[j:j+16]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        print(f"  0x{0x08071B30 + j:08X}: {hex_str}")
    print()

    results1 = disassemble_thumb(data1, 0x08071B30)
    print("Disassembly:")
    for addr, hw, hw2, mnem, is_bl in results1:
        if is_bl:
            print(f"  0x{addr:08X}:  {hw:04X} {hw2:04X}    {mnem}")
        else:
            print(f"  0x{addr:08X}:  {hw:04X}          {mnem}")
    print()

    # --- Region 2: Controller_WaitForString (0x071B64) ---
    print("=" * 80)
    print("REGION 2: ROM offset 0x071B64 (addr 0x08071B64) — Controller_WaitForString")
    print("=" * 80)
    data2 = read_rom_bytes(rom_path, 0x071B64, 48)  # Read 48 bytes for good context
    print(f"Raw bytes ({len(data2)} bytes):")
    for j in range(0, len(data2), 16):
        chunk = data2[j:j+16]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        print(f"  0x{0x08071B64 + j:08X}: {hex_str}")
    print()

    results2 = disassemble_thumb(data2, 0x08071B64)
    print("Disassembly:")
    for addr, hw, hw2, mnem, is_bl in results2:
        if is_bl:
            print(f"  0x{addr:08X}:  {hw:04X} {hw2:04X}    {mnem}")
        else:
            print(f"  0x{addr:08X}:  {hw:04X}          {mnem}")
    print()

    # --- Analysis: Find BNE instructions ---
    print("=" * 80)
    print("ANALYSIS: BNE instructions in Controller_WaitForString")
    print("=" * 80)
    bne_found = []
    for addr, hw, hw2, mnem, is_bl in results2:
        if "BNE" in mnem:
            rom_offset = addr - 0x08000000
            bne_found.append((addr, hw, rom_offset, mnem))
            print(f"  FOUND BNE at 0x{addr:08X} (ROM offset 0x{rom_offset:06X})")
            print(f"    Instruction value: 0x{hw:04X}")
            print(f"    Little-endian bytes: {hw & 0xFF:02X} {(hw >> 8) & 0xFF:02X}")
            print(f"    Mnemonic: {mnem}")
            print()

    if not bne_found:
        print("  No BNE found in this region.")
    print()

    # --- NOP analysis ---
    print("=" * 80)
    print("NOP REPLACEMENT ANALYSIS")
    print("=" * 80)
    print(f"  NOP = 0x46C0 (MOV r8, r8)")
    print(f"  Little-endian bytes: C0 46")
    print()
    for addr, hw, rom_offset, mnem in bne_found:
        print(f"  Replacing BNE at 0x{addr:08X} with NOP:")
        print(f"    Original: 0x{hw:04X} — {mnem}")
        print(f"    Patched:  0x46C0 — NOP (MOV r8, r8)")
        print(f"    Effect: The branch is removed. Instead of skipping the code after")
        print(f"            the BNE (which skips BtlController_Complete when the text")
        print(f"            printer is still active), execution FALLS THROUGH immediately.")
        print(f"            This means BtlController_Complete will ALWAYS be called,")
        print(f"            regardless of whether the text printer is still active.")
        print(f"            The battle controller won't wait for text to finish —")
        print(f"            it will immediately mark itself as complete/idle.")
        print()

    # --- Also check for BEQ ---
    print("=" * 80)
    print("ANALYSIS: BEQ instructions in Controller_WaitForString")
    print("=" * 80)
    for addr, hw, hw2, mnem, is_bl in results2:
        if "BEQ" in mnem:
            rom_offset = addr - 0x08000000
            print(f"  FOUND BEQ at 0x{addr:08X} (ROM offset 0x{rom_offset:06X})")
            print(f"    Instruction value: 0x{hw:04X}")
            print(f"    Mnemonic: {mnem}")
            print()

    # --- Literal pool values ---
    print("=" * 80)
    print("LITERAL POOL VALUES (32-bit words after function code)")
    print("=" * 80)
    # Check for LDR Rd, [PC, #imm] targets
    for addr, hw, hw2, mnem, is_bl in results2:
        if "LDR" in mnem and "[PC," in mnem and "=0x" in mnem:
            # Extract the target address from the mnemonic
            target_str = mnem.split("=0x")[1].split("]")[0]
            target_addr = int(target_str, 16)
            target_rom_offset = target_addr - 0x08000000
            if target_rom_offset < os.path.getsize(rom_path):
                pool_data = read_rom_bytes(rom_path, target_rom_offset, 4)
                pool_val = struct.unpack_from("<I", pool_data, 0)[0]
                print(f"  LDR at 0x{addr:08X} -> literal pool at 0x{target_addr:08X}")
                print(f"    Value: 0x{pool_val:08X}")
                print()


if __name__ == "__main__":
    main()
