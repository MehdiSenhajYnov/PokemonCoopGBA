#!/usr/bin/env python3
"""Disassemble InitLocalLinkPlayer candidates at 0x081B6119 and verify."""

import struct, os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

def ru16(d, o):
    if o < 0 or o + 2 > len(d): return None
    return struct.unpack_from('<H', d, o)[0]

def ru32(d, o):
    if o < 0 or o + 4 > len(d): return None
    return struct.unpack_from('<I', d, o)[0]

def is_bl(h, l):
    return h is not None and l is not None and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800

def decode_bl(h, l, pc4):
    full = ((h & 0x7FF) << 12) | ((l & 0x7FF) << 1)
    if full >= 0x400000: full -= 0x800000
    return pc4 + full

# Known addresses for annotation
NAMES = {
    0x0800A4B0: "GetMultiplayerId",
    0x08000544: "SetMainCallback2",
    0x080C1544: "CreateTask",
    0x080C1AA4: "DestroyTask",
    0x02022CE8: "gLinkPlayers",
    0x03005D90: "gSaveBlock2Ptr",
    0x02036BB0: "gSpecialVar_8000",
    0x02023364: "gBattleTypeFlags",
    0x020226C4: "gBlockRecvBuffer",
    0x02022BC4: "gSendBuffer",
    0x080A89A5: "CB2_Overworld",
}

def name(val):
    if val in NAMES: return f" ; {NAMES[val]}"
    if val & ~1 in NAMES: return f" ; {NAMES[val & ~1]}"
    if 0x03000000 <= val <= 0x03007FFF: return " ; IWRAM"
    if 0x02020000 <= val <= 0x0203FFFF: return " ; EWRAM"
    if 0x08000000 <= val <= 0x09FFFFFF: return " ; ROM"
    return ""

def disasm_func(rom, file_off, max_bytes=200):
    p = file_off
    end = min(file_off + max_bytes, len(rom) - 2)
    while p < end:
        hw = ru16(rom, p)
        addr = 0x08000000 + p

        # BL (32-bit)
        if p + 4 <= len(rom):
            h, l = hw, ru16(rom, p + 2)
            if is_bl(h, l):
                target = decode_bl(h, l, addr + 4)
                callers_name = name(target & ~1)
                print(f"  0x{addr:08X}: BL 0x{target:08X}{callers_name}")
                p += 4
                continue

        if (hw & 0xFE00) == 0xB400:
            regs = []
            for i in range(8):
                if hw & (1 << i): regs.append(f"R{i}")
            if hw & 0x100: regs.append("LR")
            print(f"  0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
        elif (hw & 0xFF00) == 0xBC00 or (hw & 0xFF00) == 0xBD00:
            regs = []
            for i in range(8):
                if hw & (1 << i): regs.append(f"R{i}")
            if hw & 0x100: regs.append("PC")
            print(f"  0x{addr:08X}: POP {{{', '.join(regs)}}}")
            if hw & 0x100:  # POP {PC} = return
                return p - file_off + 2
        elif (hw >> 11) == 0x09:  # LDR Rd, [PC, #imm]
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            pc_val = ((addr + 4) & ~2) + imm8 * 4
            pool_off = pc_val - 0x08000000
            val = ru32(rom, pool_off)
            n = name(val) if val else ""
            print(f"  0x{addr:08X}: LDR R{rd}, =0x{val:08X}{n}")
        elif (hw >> 11) == 0x04:  # MOV Rd, #imm
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            print(f"  0x{addr:08X}: MOV R{rd}, #{imm}  (0x{imm:02X})")
        elif (hw >> 11) == 0x0E:  # STRB
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            print(f"  0x{addr:08X}: STRB R{rd}, [R{rn}, #{imm5}]")
        elif (hw >> 11) == 0x10:  # STRH
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            print(f"  0x{addr:08X}: STRH R{rd}, [R{rn}, #{imm5*2}]")
        elif (hw >> 11) == 0x0C:  # STR
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            print(f"  0x{addr:08X}: STR R{rd}, [R{rn}, #{imm5*4}]")
        elif (hw >> 11) == 0x0D:  # LDR Rd, [Rn, #imm]
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            print(f"  0x{addr:08X}: LDR R{rd}, [R{rn}, #{imm5*4}]")
        elif (hw >> 11) == 0x0F:  # LDRB
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            print(f"  0x{addr:08X}: LDRB R{rd}, [R{rn}, #{imm5}]")
        elif (hw >> 11) == 0x11:  # LDRH
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            print(f"  0x{addr:08X}: LDRH R{rd}, [R{rn}, #{imm5*2}]")
        elif (hw >> 12) == 0xD:  # Bcc
            cond = (hw >> 8) & 0xF
            offset_val = hw & 0xFF
            if offset_val >= 0x80: offset_val -= 0x100
            target = addr + 4 + offset_val * 2
            cond_names = ['BEQ','BNE','BCS','BCC','BMI','BPL','BVS','BVC','BHI','BLS','BGE','BLT','BGT','BLE']
            cname = cond_names[cond] if cond < 14 else f"B{cond}"
            print(f"  0x{addr:08X}: {cname} 0x{target:08X}")
        elif (hw >> 11) == 0x1C:  # B (unconditional)
            offset_val = hw & 0x7FF
            if offset_val >= 0x400: offset_val -= 0x800
            target = addr + 4 + offset_val * 2
            print(f"  0x{addr:08X}: B 0x{target:08X}")
        elif (hw & 0xFF00) == 0x4600 or (hw & 0xFC00) == 0x4400:
            # MOV/ADD high regs
            rd = hw & 7
            rm = (hw >> 3) & 0xF
            if (hw & 0xFF00) == 0x4600:
                rd_full = (hw & 0x80) >> 4 | (hw & 7)
                rm_full = (hw >> 3) & 0xF
                print(f"  0x{addr:08X}: MOV R{rd_full}, R{rm_full}")
            else:
                rd_full = (hw & 0x80) >> 4 | (hw & 7)
                rm_full = (hw >> 3) & 0xF
                print(f"  0x{addr:08X}: ADD R{rd_full}, R{rm_full}")
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            print(f"  0x{addr:08X}: BX R{rm}")
        elif (hw & 0xFE00) == 0x1800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            rm = (hw >> 6) & 7
            print(f"  0x{addr:08X}: ADD R{rd}, R{rn}, R{rm}")
        elif (hw & 0xFE00) == 0x1A00:
            rd = hw & 7
            rn = (hw >> 3) & 7
            rm = (hw >> 6) & 7
            print(f"  0x{addr:08X}: SUB R{rd}, R{rn}, R{rm}")
        elif (hw & 0xFE00) == 0x1C00:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm3 = (hw >> 6) & 7
            print(f"  0x{addr:08X}: ADD R{rd}, R{rn}, #{imm3}")
        elif (hw & 0xF800) == 0x3000:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            print(f"  0x{addr:08X}: ADD R{rd}, #{imm8}")
        elif (hw & 0xF800) == 0x3800:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            print(f"  0x{addr:08X}: SUB R{rd}, #{imm8}")
        elif (hw & 0xFFC0) == 0x4340:
            rd = hw & 7
            rm = (hw >> 3) & 7
            print(f"  0x{addr:08X}: MUL R{rd}, R{rm}")
        elif (hw & 0xF800) == 0x0000:
            rd = hw & 7
            rm = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            print(f"  0x{addr:08X}: LSL R{rd}, R{rm}, #{imm5}")
        elif (hw & 0xF800) == 0x0800:
            rd = hw & 7
            rm = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            print(f"  0x{addr:08X}: LSR R{rd}, R{rm}, #{imm5}")
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            print(f"  0x{addr:08X}: MOV R{rd}, #{imm}  (0x{imm:02X})")
        elif (hw & 0xF800) == 0x2800:
            rn = (hw >> 8) & 7
            imm = hw & 0xFF
            print(f"  0x{addr:08X}: CMP R{rn}, #{imm}")
        elif (hw & 0xFFC0) == 0x4280:
            rn = hw & 7
            rm = (hw >> 3) & 7
            print(f"  0x{addr:08X}: CMP R{rn}, R{rm}")
        else:
            print(f"  0x{addr:08X}: 0x{hw:04X}")

        p += 2

    return p - file_off

def main():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()

    # Candidate 1: 0x081B6119 (size=50)
    print("="*60)
    print("Candidate 0x081B6119 (v2 result, size=50)")
    print("="*60)
    off1 = 0x1B6118  # file offset (0x081B6119 - 0x08000001)
    size1 = disasm_func(rom, off1, 100)
    print(f"\nFunction size: {size1} bytes\n")

    # Also check: what functions CALL 0x081B6118?
    print("Who calls this function?")
    target = 0x081B6118
    count = 0
    for pos in range(0, len(rom) - 4, 2):
        h = ru16(rom, pos)
        l = ru16(rom, pos + 2)
        if is_bl(h, l):
            t = decode_bl(h, l, 0x08000000 + pos + 4) & ~1
            if t == target:
                print(f"  Called from 0x{0x08000000 + pos:08X}")
                count += 1
                if count > 20: break
    if count == 0:
        print("  (no callers found)")

    # Also check the other candidate from final scanner: 0x0811B4E9
    print("\n" + "="*60)
    print("Candidate 0x0811B4E9 (final scanner, large function)")
    print("="*60)
    off2 = 0x11B4E8
    # Only show first 80 bytes
    disasm_func(rom, off2, 80)

    # Let's also search more broadly: functions with gSaveBlock2Ptr in LP that are small
    print("\n" + "="*60)
    print("Small functions (< 150 bytes) referencing gSaveBlock2Ptr (0x03005D90)")
    print("="*60)

    sb2 = 0x03005D90
    # Build quick LP index for sb2
    sb2_positions = []
    for pos in range(0, len(rom) - 2, 2):
        hw = ru16(rom, pos)
        if (hw >> 11) == 0x09:
            imm8 = hw & 0xFF
            pc = ((pos + 4) & ~2)
            val = ru32(rom, pc + imm8 * 4)
            if val == sb2:
                sb2_positions.append(pos)

    print(f"gSaveBlock2Ptr loaded at {len(sb2_positions)} positions\n")

    # For each, find the containing function and check if it's small
    seen = set()
    for p in sb2_positions:
        # Find PUSH {LR} backwards
        func = None
        for bp in range(p, max(0, p - 300), -2):
            hw = ru16(rom, bp)
            if hw is not None and (hw & 0xFE00) == 0xB400 and (hw & 0x100):  # PUSH {.., LR}
                func = bp
                break
        if func is None or func in seen:
            continue
        seen.add(func)

        # Check function size
        func_size = 0
        store_count = 0
        strb_count = 0
        strh_count = 0
        for sp in range(func, min(func + 200, len(rom) - 2), 2):
            hw = ru16(rom, sp)
            if hw is None: break
            if (hw >> 11) == 0x0E: strb_count += 1
            elif (hw >> 11) == 0x10: strh_count += 1
            elif (hw >> 11) == 0x0C: store_count += 1
            if (hw & 0xFF00) == 0xBD00 or (hw & 0xFF00) == 0xBC00 and ru16(rom, sp+2) is not None and (ru16(rom, sp+2) & 0xFF80) == 0x4700:
                func_size = sp - func + 2
                break

        if 30 <= func_size <= 150 and (strb_count + strh_count) >= 3:
            total = store_count + strb_count + strh_count
            func_rom = 0x08000001 + func
            # Check if it references gLinkPlayers
            has_glp = False
            for sp in range(func, min(func + func_size + 30, len(rom) - 2), 2):
                hw = ru16(rom, sp)
                if hw is not None and (hw >> 11) == 0x09:
                    imm8 = hw & 0xFF
                    pc = ((sp + 4 + 0x08000000) & ~2)
                    pool_off = (pc - 0x08000000) + imm8 * 4
                    val = ru32(rom, pool_off)
                    if val == 0x02022CE8:
                        has_glp = True
            # Check for GetMultiplayerId BL
            has_gmid = False
            sp = func
            while sp < min(func + func_size, len(rom) - 4):
                h, l = ru16(rom, sp), ru16(rom, sp + 2)
                if is_bl(h, l):
                    t = decode_bl(h, l, 0x08000000 + sp + 4) & ~1
                    if t == 0x0800A4B0:
                        has_gmid = True
                    sp += 4
                else:
                    sp += 2

            flags = []
            if has_glp: flags.append("gLP")
            if has_gmid: flags.append("GMID")
            print(f"  0x{func_rom:08X} size={func_size:3d} stores={total} strb={strb_count} strh={strh_count} {' '.join(flags)}")

            # If this looks like InitLocalLinkPlayer, disassemble it
            if has_glp and (strb_count + strh_count) >= 4:
                print(f"    *** PROMISING — Disassembly:")
                disasm_func(rom, func, func_size + 30)
                print()

if __name__ == '__main__':
    main()
