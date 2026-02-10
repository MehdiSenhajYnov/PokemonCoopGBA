#!/usr/bin/env python3
"""
Find the BL instruction to HandleLinkBattleSetup within SetUpBattleVarsAndBirchZigzagoon.

SetUpBattleVars is at ROM address 0x0806F1D9 (THUMB), code at 0x0806F1D8.
ROM offset = 0x0006F1D8.

HandleLinkBattleSetup references gBattleTypeFlags (0x02023364) early on.

ARM7TDMI THUMB BL encoding (ARMv4T):
  The BL is a two-instruction sequence:
    Instruction 1: 1111 0 offset_hi[10:0]    -> sets LR = PC + (sign_extend(offset_hi) << 12)
    Instruction 2: 1111 1 offset_lo[10:0]    -> BL: PC = LR + (offset_lo << 1), LR = old_PC | 1

  Combined offset = sign_extend(offset_hi << 12) + (offset_lo << 1)
  Target = (address_of_first_instruction + 4) + combined_offset
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
ROM_BASE = 0x08000000

FUNC_ROM_ADDR = 0x0806F1D8
FUNC_ROM_OFFSET = FUNC_ROM_ADDR - ROM_BASE  # 0x0006F1D8

GBATTLETYPEFLAGS = 0x02023364

def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def decode_bl_armv4t(hw1, hw2, addr_of_hw1):
    """
    Decode ARMv4T THUMB BL instruction pair.
    hw1 at addr_of_hw1, hw2 at addr_of_hw1+2.

    hw1: 1111 0xxx xxxx xxxx  (prefix, sets up upper offset in LR)
    hw2: 1111 1xxx xxxx xxxx  (BL, branches and links)

    Returns (target_address, "BL") or (None, None)
    """
    if (hw1 & 0xF800) != 0xF000:
        return None, None
    if (hw2 & 0xF800) != 0xF800:
        return None, None

    # Extract fields
    offset_hi = hw1 & 0x7FF  # 11 bits
    offset_lo = hw2 & 0x7FF  # 11 bits

    # Sign extend offset_hi from 11 bits and shift left by 12
    if offset_hi & 0x400:
        offset_hi |= 0xFFFFF800  # sign extend to 32 bits (negative)
    offset_upper = (offset_hi << 12) & 0xFFFFFFFF
    if offset_hi & 0x400:
        offset_upper = offset_hi << 12  # Python handles negative correctly

    # Lower offset shifted left by 1
    offset_lower = offset_lo << 1

    # Combined offset (sign-extended)
    if offset_hi & 0x400:
        # Negative: offset_hi is sign-extended
        combined = ((offset_hi << 12) | offset_lower)
        # Sign extend from bit 22
        if combined & 0x400000:
            combined |= ~0x7FFFFF  # extend sign
    else:
        combined = (offset_hi << 12) | offset_lower

    # Target = PC + 4 + combined_offset
    # PC = address of first BL instruction
    target = (addr_of_hw1 + 4 + combined) & 0xFFFFFFFF

    return target, "BL"

def check_function_references_btf(rom_data, func_addr):
    """Check if function at func_addr loads gBattleTypeFlags (0x02023364) via literal pool."""
    func_offset = (func_addr & ~1) - ROM_BASE
    if func_offset < 0 or func_offset + 80 > len(rom_data):
        return False

    for i in range(0, 80, 2):
        hw = read_u16(rom_data, func_offset + i)
        # LDR Rd, [PC, #imm8*4]
        if (hw & 0xF800) == 0x4800:
            imm8 = hw & 0xFF
            pc_val = ((func_addr & ~1) + i + 4) & ~2
            pool_addr = pc_val + imm8 * 4
            pool_offset = pool_addr - ROM_BASE
            if 0 <= pool_offset <= len(rom_data) - 4:
                val = read_u32(rom_data, pool_offset)
                if val == GBATTLETYPEFLAGS:
                    return True
    return False

def disasm_thumb(hw, addr):
    """Basic THUMB disassembly."""
    # PUSH
    if (hw & 0xFE00) == 0xB400:
        regs = []
        for i in range(8):
            if hw & (1 << i): regs.append(f"r{i}")
        if hw & 0x100: regs.append("lr")
        return f"PUSH {{{', '.join(regs)}}}"
    # POP
    if (hw & 0xFE00) == 0xBC00:
        regs = []
        for i in range(8):
            if hw & (1 << i): regs.append(f"r{i}")
        if hw & 0x100: regs.append("pc")
        return f"POP {{{', '.join(regs)}}}"
    # MOV Rd, #imm8
    if (hw & 0xF800) == 0x2000:
        rd = (hw >> 8) & 7; imm = hw & 0xFF
        return f"MOV r{rd}, #0x{imm:02X}"
    # CMP Rd, #imm8
    if (hw & 0xF800) == 0x2800:
        rd = (hw >> 8) & 7; imm = hw & 0xFF
        return f"CMP r{rd}, #0x{imm:02X}"
    # ADD Rd, #imm8
    if (hw & 0xF800) == 0x3000:
        rd = (hw >> 8) & 7; imm = hw & 0xFF
        return f"ADD r{rd}, #0x{imm:02X}"
    # SUB Rd, #imm8
    if (hw & 0xF800) == 0x3800:
        rd = (hw >> 8) & 7; imm = hw & 0xFF
        return f"SUB r{rd}, #0x{imm:02X}"
    # LDR Rd, [PC, #imm]
    if (hw & 0xF800) == 0x4800:
        rd = (hw >> 8) & 7; imm8 = hw & 0xFF
        pc_val = (addr + 4) & ~2; pool_addr = pc_val + imm8 * 4
        return f"LDR r{rd}, [PC, #0x{imm8*4:X}] ; @0x{pool_addr:08X}"
    # LDR Rd, [Rn, #imm]
    if (hw & 0xF800) == 0x6800:
        rd = hw & 7; rn = (hw >> 3) & 7; imm5 = ((hw >> 6) & 0x1F) * 4
        return f"LDR r{rd}, [r{rn}, #0x{imm5:X}]"
    # LDRB Rd, [Rn, #imm]
    if (hw & 0xF800) == 0x7800:
        rd = hw & 7; rn = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
        return f"LDRB r{rd}, [r{rn}, #0x{imm5:X}]"
    # LDRH Rd, [Rn, #imm]
    if (hw & 0xF800) == 0x8800:
        rd = hw & 7; rn = (hw >> 3) & 7; imm5 = ((hw >> 6) & 0x1F) * 2
        return f"LDRH r{rd}, [r{rn}, #0x{imm5:X}]"
    # STR Rd, [Rn, #imm]
    if (hw & 0xF800) == 0x6000:
        rd = hw & 7; rn = (hw >> 3) & 7; imm5 = ((hw >> 6) & 0x1F) * 4
        return f"STR r{rd}, [r{rn}, #0x{imm5:X}]"
    # STRB Rd, [Rn, #imm]
    if (hw & 0xF800) == 0x7000:
        rd = hw & 7; rn = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
        return f"STRB r{rd}, [r{rn}, #0x{imm5:X}]"
    # STRH
    if (hw & 0xF800) == 0x8000:
        rd = hw & 7; rn = (hw >> 3) & 7; imm5 = ((hw >> 6) & 0x1F) * 2
        return f"STRH r{rd}, [r{rn}, #0x{imm5:X}]"
    # LDRSH
    if (hw & 0xF800) == 0x8E00:
        # Actually this is LDRH with different offset range, but 0x8E01 is LDRH r1, [r0, #0x30]
        pass
    # B<cond>
    if (hw & 0xF000) == 0xD000:
        cond = (hw >> 8) & 0xF
        if cond < 0xE:
            cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                         "BHI","BLS","BGE","BLT","BGT","BLE"]
            imm8 = hw & 0xFF
            if imm8 & 0x80: imm8 -= 256
            target = addr + 4 + imm8 * 2
            return f"{cond_names[cond]} 0x{target:08X}"
    # Unconditional B
    if (hw & 0xF800) == 0xE000:
        imm11 = hw & 0x7FF
        if imm11 & 0x400: imm11 -= 0x800
        target = addr + 4 + imm11 * 2
        return f"B 0x{target:08X}"
    # LSL Rd, Rm, #imm5
    if (hw & 0xF800) == 0x0000:
        rd = hw & 7; rm = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
        if imm5 == 0: return f"MOV r{rd}, r{rm}"
        return f"LSL r{rd}, r{rm}, #{imm5}"
    # LSR Rd, Rm, #imm5
    if (hw & 0xF800) == 0x0800:
        rd = hw & 7; rm = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
        if imm5 == 0: imm5 = 32
        return f"LSR r{rd}, r{rm}, #{imm5}"
    # ADD reg
    if (hw & 0xFE00) == 0x1800:
        rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
        return f"ADD r{rd}, r{rn}, r{rm}"
    # SUB reg
    if (hw & 0xFE00) == 0x1A00:
        rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
        return f"SUB r{rd}, r{rn}, r{rm}"
    # ADD Rd, Rm, #imm3
    if (hw & 0xFE00) == 0x1C00:
        rd = hw & 7; rn = (hw >> 3) & 7; imm3 = (hw >> 6) & 7
        return f"ADD r{rd}, r{rn}, #{imm3}"
    # SUB Rd, Rm, #imm3
    if (hw & 0xFE00) == 0x1E00:
        rd = hw & 7; rn = (hw >> 3) & 7; imm3 = (hw >> 6) & 7
        return f"SUB r{rd}, r{rn}, #{imm3}"
    # TST
    if (hw & 0xFFC0) == 0x4200:
        rn = hw & 7; rm = (hw >> 3) & 7
        return f"TST r{rn}, r{rm}"
    # AND
    if (hw & 0xFFC0) == 0x4000:
        rd = hw & 7; rm = (hw >> 3) & 7
        return f"AND r{rd}, r{rm}"
    # ORR
    if (hw & 0xFFC0) == 0x4300:
        rd = hw & 7; rm = (hw >> 3) & 7
        return f"ORR r{rd}, r{rm}"
    # MOV high reg
    if (hw & 0xFF00) == 0x4600:
        rd = (hw & 7) | ((hw >> 4) & 8); rm = (hw >> 3) & 0xF
        return f"MOV r{rd}, r{rm}"
    # CMP high reg
    if (hw & 0xFF00) == 0x4500:
        rn = (hw & 7) | ((hw >> 4) & 8); rm = (hw >> 3) & 0xF
        return f"CMP r{rn}, r{rm}"
    # BX
    if (hw & 0xFF80) == 0x4700:
        rm = (hw >> 3) & 0xF
        return f"BX r{rm}"
    # BLX reg
    if (hw & 0xFF80) == 0x4780:
        rm = (hw >> 3) & 0xF
        return f"BLX r{rm}"
    # SP-relative LDR
    if (hw & 0xF800) == 0x9800:
        rd = (hw >> 8) & 7; imm8 = hw & 0xFF
        return f"LDR r{rd}, [SP, #0x{imm8*4:X}]"
    # SP-relative STR
    if (hw & 0xF800) == 0x9000:
        rd = (hw >> 8) & 7; imm8 = hw & 0xFF
        return f"STR r{rd}, [SP, #0x{imm8*4:X}]"
    # ADD SP, #imm
    if hw & 0xFF80 == 0xB000:
        imm7 = (hw & 0x7F) * 4
        return f"ADD SP, #{imm7}"
    # SUB SP, #imm
    if hw & 0xFF80 == 0xB080:
        imm7 = (hw & 0x7F) * 4
        return f"SUB SP, #{imm7}"
    # LDRH Rd, [Rn, Rm]
    if (hw & 0xFE00) == 0x5A00:
        rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
        return f"LDRH r{rd}, [r{rn}, r{rm}]"
    # NOP (MOV r8, r8)
    if hw == 0x46C0:
        return "NOP (MOV r8, r8)"

    return f"??? 0x{hw:04X}"

def main():
    with open(ROM_PATH, 'rb') as f:
        rom_data = f.read()

    print(f"ROM size: {len(rom_data)} bytes ({len(rom_data)/1024/1024:.1f} MB)")
    print(f"\n{'='*80}")
    print(f"SetUpBattleVarsAndBirchZigzagoon")
    print(f"  ROM addr: 0x{FUNC_ROM_ADDR:08X} (THUMB)")
    print(f"  ROM offset: 0x{FUNC_ROM_OFFSET:06X}")
    print(f"{'='*80}\n")

    # Read 300 bytes from function start (it's a big function)
    read_size = 300
    func_bytes = rom_data[FUNC_ROM_OFFSET:FUNC_ROM_OFFSET + read_size]

    print("Full disassembly:")
    print("-" * 80)

    bl_targets = []
    i = 0
    while i < read_size - 2:
        addr = FUNC_ROM_ADDR + i
        hw = read_u16(func_bytes, i)

        # Check for BL pair (ARMv4T: F000-F7FF followed by F800-FFFF)
        if i + 2 < read_size:
            hw2 = read_u16(func_bytes, i + 2)
            target, bl_type = decode_bl_armv4t(hw, hw2, addr)
            if target is not None:
                refs_btf = check_function_references_btf(rom_data, target)
                marker = " *** REFS gBattleTypeFlags! ***" if refs_btf else ""

                # Also resolve what's at the target
                tgt_clean = target & ~1
                tgt_off = tgt_clean - ROM_BASE
                tgt_hw = read_u16(rom_data, tgt_off) if 0 <= tgt_off < len(rom_data)-2 else 0

                print(f"  0x{addr:08X} (+0x{i:02X}): {hw:04X} {hw2:04X}  BL 0x{target:08X}{marker}")
                bl_targets.append((i, addr, target, refs_btf))
                i += 4
                continue

        # Resolve literal pool for LDR [PC, #imm]
        extra = ""
        if (hw & 0xF800) == 0x4800:
            imm8 = hw & 0xFF
            pc_val = (addr + 4) & ~2
            pool_addr = pc_val + imm8 * 4
            pool_offset = pool_addr - ROM_BASE
            if 0 <= pool_offset <= len(rom_data) - 4:
                val = read_u32(rom_data, pool_offset)
                extra = f"  ; =0x{val:08X}"

        disasm = disasm_thumb(hw, addr)
        print(f"  0x{addr:08X} (+0x{i:02X}): {hw:04X}      {disasm}{extra}")

        # Stop at POP {pc} — likely end of function
        if (hw & 0xFF00) == 0xBD00:
            print(f"  --- function end (POP {{..., pc}}) ---")
            # Continue a bit more for literal pool
            for j in range(i+2, min(i+32, read_size-2), 4):
                pool_val = read_u32(func_bytes, j)
                print(f"  0x{FUNC_ROM_ADDR+j:08X} (+0x{j:02X}): {pool_val:08X}  .word 0x{pool_val:08X}")
            break

        i += 2

    # Summary of BL instructions
    print(f"\n{'='*80}")
    print(f"BL instructions found:")
    print(f"{'='*80}")
    for offset, addr, target, refs_btf in bl_targets:
        target_clean = target & ~1
        print(f"\n  BL at +0x{offset:02X} (0x{addr:08X}) -> 0x{target:08X}")
        print(f"    Refs gBattleTypeFlags: {'YES' if refs_btf else 'no'}")

        # Brief disasm of target
        tgt_off = target_clean - ROM_BASE
        if 0 <= tgt_off < len(rom_data) - 40:
            print(f"    Target disasm (first 20 halfwords):")
            j = 0
            while j < 40:
                t_addr = target_clean + j
                t_hw = read_u16(rom_data, tgt_off + j)

                # Check BL at target
                if j + 2 < 40:
                    t_hw2 = read_u16(rom_data, tgt_off + j + 2)
                    t_target, t_bl_type = decode_bl_armv4t(t_hw, t_hw2, t_addr)
                    if t_target is not None:
                        print(f"      0x{t_addr:08X}: {t_hw:04X} {t_hw2:04X}  BL 0x{t_target:08X}")
                        j += 4
                        continue

                t_extra = ""
                if (t_hw & 0xF800) == 0x4800:
                    imm8 = t_hw & 0xFF
                    pc_val = (t_addr + 4) & ~2
                    pool_addr = pc_val + imm8 * 4
                    pool_off = pool_addr - ROM_BASE
                    if 0 <= pool_off <= len(rom_data) - 4:
                        val = read_u32(rom_data, pool_off)
                        t_extra = f"  ; =0x{val:08X}"

                t_disasm = disasm_thumb(t_hw, t_addr)
                print(f"      0x{t_addr:08X}: {t_hw:04X}      {t_disasm}{t_extra}")

                if (t_hw & 0xFF00) == 0xBD00 or t_hw == 0x4770:
                    print(f"      --- return ---")
                    break
                j += 2

    # Final answer
    print(f"\n{'='*80}")
    print("ANSWER")
    print(f"{'='*80}")
    found = [x for x in bl_targets if x[3]]
    if found:
        for offset, addr, target, _ in found:
            hw1 = read_u16(func_bytes, offset)
            hw2 = read_u16(func_bytes, offset + 2)
            print(f"HandleLinkBattleSetup BL found!")
            print(f"  Offset in SetUpBattleVars: +0x{offset:02X}")
            print(f"  ROM address:  0x{addr:08X} (hw1=0x{hw1:04X}) and 0x{addr+2:08X} (hw2=0x{hw2:04X})")
            print(f"  ROM file offset: 0x{FUNC_ROM_OFFSET + offset:06X}")
            print(f"  Target: HandleLinkBattleSetup at 0x{target:08X}")
            print(f"")
            print(f"  To NOP (replace with MOV r8,r8 = 0x46C0):")
            print(f"    Offset 0x{FUNC_ROM_OFFSET + offset:06X}: write 0xC046 (little-endian)")
            print(f"    Offset 0x{FUNC_ROM_OFFSET + offset + 2:06X}: write 0xC046 (little-endian)")
    else:
        print("No BL directly referencing gBattleTypeFlags found in SetUpBattleVars.")
        print("Checking ALL nearby BL targets more deeply...")

        # For each BL target, scan deeper (maybe it's an intermediary)
        for offset, addr, target, _ in bl_targets:
            target_clean = target & ~1
            tgt_off = target_clean - ROM_BASE
            if tgt_off < 0 or tgt_off >= len(rom_data) - 100:
                continue

            # Scan this function's BL targets for gBattleTypeFlags ref
            print(f"\n  Checking sub-calls of BL at +0x{offset:02X} -> 0x{target:08X}...")
            for j in range(0, 100, 2):
                sub_hw = read_u16(rom_data, tgt_off + j)
                if j + 2 < 100:
                    sub_hw2 = read_u16(rom_data, tgt_off + j + 2)
                    sub_target, _ = decode_bl_armv4t(sub_hw, sub_hw2, target_clean + j)
                    if sub_target is not None:
                        if check_function_references_btf(rom_data, sub_target):
                            print(f"    -> Sub-BL at target+0x{j:02X} calls 0x{sub_target:08X} which refs gBattleTypeFlags!")

    # Also: let's search around 0x0806F1D8 for the BL pattern that vanilla has at +0x42
    print(f"\n{'='*80}")
    print(f"Checking vanilla-equivalent offset +0x42 from function start:")
    check_off = 0x42
    if check_off + 4 <= read_size:
        hw1 = read_u16(func_bytes, check_off)
        hw2 = read_u16(func_bytes, check_off + 2)
        print(f"  +0x{check_off:02X}: 0x{hw1:04X} 0x{hw2:04X}")
        target, bl_type = decode_bl_armv4t(hw1, hw2, FUNC_ROM_ADDR + check_off)
        if target:
            print(f"  -> {bl_type} 0x{target:08X}")
            refs = check_function_references_btf(rom_data, target)
            print(f"  -> Refs gBattleTypeFlags: {refs}")
        else:
            print(f"  -> Not a BL instruction")

if __name__ == '__main__':
    main()
