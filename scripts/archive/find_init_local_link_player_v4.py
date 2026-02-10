"""
Find InitLocalLinkPlayer v4 - via LocalLinkPlayerToBlock and gBlockSendBuffer.

Key insight: InitLocalLinkPlayer is STATIC and may be inlined by the compiler.
But LocalLinkPlayerToBlock is PUBLIC and calls InitLocalLinkPlayer.
LocalLinkPlayerToBlock writes to gBlockSendBuffer (0x02022BC4).

Strategy:
1. Find LocalLinkPlayerToBlock by looking for functions with gBlockSendBuffer in LP
   that also have gLocalLinkPlayer or gLocalLinkPlayerBlock in LP.
2. From LocalLinkPlayerToBlock, find the BL to InitLocalLinkPlayer.
3. If InitLocalLinkPlayer is inlined, the stores to gLocalLinkPlayer will be
   inside LocalLinkPlayerToBlock itself.

Also: directly scan for the characteristic constants:
- version = gGameVersion + 0x4000 (likely 0x4003 for Emerald)
- lp_field_2 = 0x8000
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

G_LOCAL_LINK_PLAYER = 0x02022D74
G_LINK_PLAYERS = 0x02022CE8
G_BLOCK_SEND_BUFFER = 0x02022BC4
SAVE_BLOCK2_PTR = 0x03005D90
ROM_BASE = 0x08000000

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def read16(rom, offset):
    if offset < 0 or offset + 2 > len(rom):
        return 0
    return struct.unpack_from("<H", rom, offset)[0]

def read32(rom, offset):
    if offset < 0 or offset + 4 > len(rom):
        return 0
    return struct.unpack_from("<I", rom, offset)[0]

def decode_bl(rom, offset):
    hw1 = read16(rom, offset)
    hw2 = read16(rom, offset + 2)
    if (hw1 & 0xF800) != 0xF000:
        return None
    if (hw2 & 0xF800) not in (0xF800, 0xE800):
        return None
    offset_hi = hw1 & 0x7FF
    offset_lo = hw2 & 0x7FF
    combined = (offset_hi << 12) | (offset_lo << 1)
    if combined & 0x400000:
        combined -= 0x800000
    return (offset + ROM_BASE) + 4 + combined

def find_function_start(rom, offset):
    for i in range(offset, max(offset - 0x400, 0), -2):
        hw = read16(rom, i)
        if (hw & 0xFF00) == 0xB500:
            return i
    return None

def find_function_end(rom, start, max_size=0x400):
    for i in range(start, min(start + max_size, len(rom)), 2):
        hw = read16(rom, i)
        if (hw & 0xFF00) == 0xBD00:
            return i + 2
        if hw == 0x4770:
            return i + 2
    return start + max_size

def get_literal_pool_values(rom, func_start, func_end):
    values = {}
    for off in range(func_start, func_end, 2):
        hw = read16(rom, off)
        if (hw >> 11) == 0x09:
            imm8 = hw & 0xFF
            pc = ((off + ROM_BASE + 4) & ~3)
            lp_addr = pc + imm8 * 4
            lp_offset = lp_addr - ROM_BASE
            if 0 <= lp_offset < len(rom) - 3:
                val = read32(rom, lp_offset)
                values[lp_offset] = val
    return values

def get_bl_targets(rom, func_start, func_end):
    targets = []
    for off in range(func_start, func_end - 2, 2):
        target = decode_bl(rom, off)
        if target is not None:
            targets.append((off, target))
    return targets

def disassemble_thumb(rom, start, end):
    lines = []
    off = start
    while off < end:
        hw = read16(rom, off)
        addr = off + ROM_BASE
        target = decode_bl(rom, off)
        if target is not None:
            lines.append(f"  0x{addr:08X}: BL 0x{target:08X}")
            off += 4
            continue
        if (hw & 0xFF00) == 0xB500:
            regs = []
            for i in range(8):
                if hw & (1 << i): regs.append(f"R{i}")
            if hw & 0x100: regs.append("LR")
            lines.append(f"  0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
        elif (hw & 0xFF00) == 0xBD00:
            regs = []
            for i in range(8):
                if hw & (1 << i): regs.append(f"R{i}")
            if hw & 0x100: regs.append("PC")
            lines.append(f"  0x{addr:08X}: POP {{{', '.join(regs)}}}")
        elif (hw >> 11) == 0x09:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            pc = (addr + 4) & ~3; lp_offset = (pc + imm8 * 4) - ROM_BASE
            val = read32(rom, lp_offset) if 0 <= lp_offset < len(rom) - 3 else 0
            label = ""
            if val == SAVE_BLOCK2_PTR: label = " ; gSaveBlock2Ptr"
            elif val == G_LOCAL_LINK_PLAYER: label = " ; gLocalLinkPlayer"
            elif val == G_LINK_PLAYERS: label = " ; gLinkPlayers"
            elif val == G_BLOCK_SEND_BUFFER: label = " ; gBlockSendBuffer"
            elif val == 0x03005D90: label = " ; gSaveBlock2Ptr"
            lines.append(f"  0x{addr:08X}: LDR R{rd}, [PC, #0x{imm8*4:X}]  ; =0x{val:08X}{label}")
        elif (hw >> 11) == 0x0C:
            rd = hw & 7; rn = (hw >> 3) & 7; imm5 = ((hw >> 6) & 0x1F) * 4
            lines.append(f"  0x{addr:08X}: STR R{rd}, [R{rn}, #0x{imm5:X}]")
        elif (hw >> 11) == 0x0E:
            rd = hw & 7; rn = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: STRB R{rd}, [R{rn}, #0x{imm5:X}]")
        elif (hw >> 11) == 0x10:
            rd = hw & 7; rn = (hw >> 3) & 7; imm5 = ((hw >> 6) & 0x1F) * 2
            lines.append(f"  0x{addr:08X}: STRH R{rd}, [R{rn}, #0x{imm5:X}]")
        elif (hw >> 11) == 0x0D:
            rd = hw & 7; rn = (hw >> 3) & 7; imm5 = ((hw >> 6) & 0x1F) * 4
            lines.append(f"  0x{addr:08X}: LDR R{rd}, [R{rn}, #0x{imm5:X}]")
        elif (hw >> 11) == 0x0F:
            rd = hw & 7; rn = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: LDRB R{rd}, [R{rn}, #0x{imm5:X}]")
        elif (hw >> 11) == 0x11:
            rd = hw & 7; rn = (hw >> 3) & 7; imm5 = ((hw >> 6) & 0x1F) * 2
            lines.append(f"  0x{addr:08X}: LDRH R{rd}, [R{rn}, #0x{imm5:X}]")
        elif (hw >> 11) == 0x04:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: MOV R{rd}, #0x{imm8:X}")
        elif (hw >> 11) == 0x06:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: ADD R{rd}, #0x{imm8:X}")
        elif (hw >> 11) == 0x07:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: SUB R{rd}, #0x{imm8:X}")
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            rname = f"R{rm}" if rm < 14 else ("LR" if rm == 14 else "PC")
            lines.append(f"  0x{addr:08X}: BX {rname}")
        elif (hw & 0xF800) == 0xD000:
            cond = (hw >> 8) & 0xF; imm8 = hw & 0xFF
            if imm8 & 0x80: imm8 -= 256
            target_addr = addr + 4 + imm8 * 2
            cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                          "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]
            if cond < 15:
                lines.append(f"  0x{addr:08X}: {cond_names[cond]} 0x{target_addr:08X}")
        elif (hw & 0xF800) == 0xE000:
            imm11 = hw & 0x7FF
            if imm11 & 0x400: imm11 -= 0x800
            target_addr = addr + 4 + imm11 * 2
            lines.append(f"  0x{addr:08X}: B 0x{target_addr:08X}")
        elif (hw & 0xFF00) == 0x4600:
            rd = (hw & 7) | ((hw >> 4) & 8); rm = (hw >> 3) & 0xF
            lines.append(f"  0x{addr:08X}: MOV R{rd}, R{rm}")
        elif (hw & 0xFF00) == 0x4400:
            rd = (hw & 7) | ((hw >> 4) & 8); rm = (hw >> 3) & 0xF
            lines.append(f"  0x{addr:08X}: ADD R{rd}, R{rm}")
        elif (hw & 0xFFC0) == 0x4280:
            rn = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: CMP R{rn}, R{rm}")
        elif (hw & 0xF800) == 0x2800:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: CMP R{rd}, #0x{imm8:X}")
        elif (hw >> 11) == 0x00:
            rd = hw & 7; rm = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: LSL R{rd}, R{rm}, #0x{imm5:X}")
        elif (hw >> 11) == 0x01:
            rd = hw & 7; rm = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: LSR R{rd}, R{rm}, #0x{imm5:X}")
        elif (hw & 0xFFC0) == 0x1800:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: ADD R{rd}, R{rn}, R{rm}")
        elif (hw & 0xFFC0) == 0x1A00:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: SUB R{rd}, R{rn}, R{rm}")
        elif (hw & 0xFFC0) == 0x4340:
            rd = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: MUL R{rd}, R{rm}")
        elif (hw & 0xFFC0) == 0x4000:
            rd = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: AND R{rd}, R{rm}")
        elif (hw & 0xFFC0) == 0x4300:
            rd = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: ORR R{rd}, R{rm}")
        elif (hw & 0xFFC0) == 0x4080:
            rd = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: LSL R{rd}, R{rm}")
        elif (hw & 0xFFC0) == 0x40C0:
            rd = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: LSR R{rd}, R{rm}")
        elif (hw & 0xFF00) == 0xB000:
            imm7 = hw & 0x7F
            if hw & 0x80:
                lines.append(f"  0x{addr:08X}: SUB SP, #0x{imm7*4:X}")
            else:
                lines.append(f"  0x{addr:08X}: ADD SP, #0x{imm7*4:X}")
        elif (hw >> 11) == 0x12:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: STR R{rd}, [SP, #0x{imm8*4:X}]")
        elif (hw >> 11) == 0x13:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: LDR R{rd}, [SP, #0x{imm8*4:X}]")
        else:
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")
        off += 2
    return lines

def main():
    print("=" * 80)
    print("FindInitLocalLinkPlayer v4 - via gBlockSendBuffer")
    print("=" * 80)

    rom = read_rom()

    # =========================================================================
    # STEP 1: Find LP refs to gBlockSendBuffer (0x02022BC4)
    # =========================================================================
    print("\nSTEP 1: Find LP refs to gBlockSendBuffer (0x02022BC4)")
    bsb_refs = []
    for off in range(0, min(len(rom) - 4, 0x2000000), 4):
        val = read32(rom, off)
        if val == G_BLOCK_SEND_BUFFER:
            bsb_refs.append(off)
    print(f"  Found {len(bsb_refs)} LP entries")

    # Find functions referencing gBlockSendBuffer
    seen = set()
    bsb_funcs = []
    for lp_off in bsb_refs:
        for instr_off in range(max(0, lp_off - 1024), lp_off, 2):
            hw = read16(rom, instr_off)
            if (hw >> 11) != 0x09:
                continue
            imm8 = hw & 0xFF
            pc = ((instr_off + ROM_BASE + 4) & ~3)
            target_lp = pc + imm8 * 4 - ROM_BASE
            if target_lp == lp_off:
                func_start = find_function_start(rom, instr_off)
                if func_start and func_start not in seen:
                    seen.add(func_start)
                    func_end = find_function_end(rom, func_start, 0x300)
                    lp_vals = get_literal_pool_values(rom, func_start, func_end)
                    bls = get_bl_targets(rom, func_start, func_end)
                    size = func_end - func_start

                    has_llp = G_LOCAL_LINK_PLAYER in lp_vals.values()
                    has_sb2 = SAVE_BLOCK2_PTR in lp_vals.values()

                    bsb_funcs.append({
                        'start': func_start,
                        'end': func_end,
                        'size': size,
                        'lp_vals': lp_vals,
                        'bls': bls,
                        'has_llp': has_llp,
                        'has_sb2': has_sb2,
                    })

    # Sort: functions with gLocalLinkPlayer first
    bsb_funcs.sort(key=lambda x: (-int(x['has_llp']), -int(x['has_sb2']), x['start']))

    print(f"  Found {len(bsb_funcs)} functions with gBlockSendBuffer:")
    for f in bsb_funcs:
        addr = f['start'] + ROM_BASE
        flags = ""
        if f['has_llp']: flags += " [gLocalLinkPlayer!]"
        if f['has_sb2']: flags += " [gSaveBlock2Ptr!]"
        lp_str = ', '.join(f'0x{v:08X}' for v in sorted(set(f['lp_vals'].values())))
        print(f"  0x{addr:08X} ({f['size']}b, {len(f['bls'])}bl){flags}")
        print(f"    LP: {lp_str}")

    # Disassemble the ones with gLocalLinkPlayer
    print("\n" + "=" * 80)
    print("STEP 2: Disassemble gBlockSendBuffer functions with gLocalLinkPlayer")
    print("=" * 80)

    for f in bsb_funcs:
        if not f['has_llp']:
            continue
        addr = f['start'] + ROM_BASE
        print(f"\n--- Function at 0x{addr:08X} ({f['size']} bytes) ---")
        print(f"  BL targets: {', '.join(f'0x{t:08X}' for _, t in f['bls'])}")
        lines = disassemble_thumb(rom, f['start'], f['end'])
        for line in lines:
            print(line)

        # For each BL target, check if it has gSaveBlock2Ptr
        print("\n  BL target analysis:")
        for bl_off, bl_target in f['bls']:
            t_off = bl_target - ROM_BASE
            if t_off < 0 or t_off >= len(rom):
                print(f"    0x{bl_target:08X}: outside ROM")
                continue
            t_start = find_function_start(rom, t_off)
            if not t_start:
                t_start = t_off
            t_end = find_function_end(rom, t_start, 0x200)
            t_lp = get_literal_pool_values(rom, t_start, t_end)
            t_size = t_end - t_start
            t_bls = get_bl_targets(rom, t_start, t_end)

            has_sb2 = SAVE_BLOCK2_PTR in t_lp.values()
            has_llp = G_LOCAL_LINK_PLAYER in t_lp.values()

            flags = ""
            if has_sb2: flags += " [SB2!]"
            if has_llp: flags += " [LLP!]"

            print(f"    0x{bl_target:08X}: {t_size}b, {len(t_bls)}bl{flags}")
            lp_str = ', '.join(f'0x{v:08X}' for v in sorted(set(t_lp.values())))
            print(f"      LP: {lp_str}")

            # If it has SB2 and is small, this could be InitLocalLinkPlayer!
            if has_sb2 and t_size < 300:
                print(f"\n    *** CANDIDATE InitLocalLinkPlayer: 0x{bl_target:08X} ***")
                t_lines = disassemble_thumb(rom, t_start, t_end)
                for line in t_lines:
                    print(f"    {line}")

            # If it CALLS something with SB2, check recursively one level
            if not has_sb2:
                for _, sub_target in t_bls:
                    s_off = sub_target - ROM_BASE
                    if s_off < 0 or s_off >= len(rom):
                        continue
                    s_start = find_function_start(rom, s_off)
                    if not s_start:
                        s_start = s_off
                    s_end = find_function_end(rom, s_start, 0x200)
                    s_lp = get_literal_pool_values(rom, s_start, s_end)
                    if SAVE_BLOCK2_PTR in s_lp.values() and (s_end - s_start) < 300:
                        print(f"      -> BL 0x{sub_target:08X} has SB2! ({s_end - s_start}b)")
                        print(f"         LP: {', '.join(f'0x{v:08X}' for v in sorted(set(s_lp.values())))}")
                        s_lines = disassemble_thumb(rom, s_start, s_end)
                        for line in s_lines:
                            print(f"      {line}")

    # =========================================================================
    # STEP 3: Also check gLocalLinkPlayerBlock
    # gLocalLinkPlayerBlock is a separate struct that contains a LinkPlayer copy.
    # In pokeemerald, it's declared as: static struct LinkPlayerBlock gLocalLinkPlayerBlock;
    # Its address should be near gLocalLinkPlayer (0x02022D74)
    # =========================================================================
    print("\n" + "=" * 80)
    print("STEP 3: Search for gLocalLinkPlayerBlock")
    print("=" * 80)

    # gLocalLinkPlayerBlock contains:
    # - LinkPlayer linkPlayer (28 bytes)
    # - char magic1[16]
    # - char magic2[16]
    # Total: 60 bytes (0x3C)
    # It should be close to gLocalLinkPlayer in BSS

    # Let's look at what addresses the bsb_funcs with gLocalLinkPlayer reference
    for f in bsb_funcs:
        if not f['has_llp']:
            continue
        addr = f['start'] + ROM_BASE
        print(f"\n  Function 0x{addr:08X} LP values:")
        for lp_off, val in sorted(f['lp_vals'].items()):
            label = ""
            if val == G_LOCAL_LINK_PLAYER: label = " gLocalLinkPlayer"
            elif val == G_BLOCK_SEND_BUFFER: label = " gBlockSendBuffer"
            elif 0x02022D00 <= val <= 0x02023000: label = " (near gLocalLinkPlayer!)"
            elif 0x02020000 <= val <= 0x0203FFFF: label = " (EWRAM)"
            elif 0x03000000 <= val <= 0x03007FFF: label = " (IWRAM)"
            elif 0x08000000 <= val <= 0x09FFFFFF: label = " (ROM)"
            print(f"    0x{val:08X}{label}")

    # =========================================================================
    # STEP 4: Direct search for 0x4003 (GAME_VERSION + 0x4000) or 0x8000 constants
    # used in InitLocalLinkPlayer near gLocalLinkPlayer stores
    # =========================================================================
    print("\n" + "=" * 80)
    print("STEP 4: Search for MOV Rx, #3 + STRH or LDR Rx, =0x4003 pattern")
    print("=" * 80)

    # 0x4003 won't fit in an immediate, so it would be in the LP
    for off in range(0, min(len(rom) - 4, 0x2000000), 4):
        val = read32(rom, off)
        if val == 0x4003:
            # Check if nearby (within 1024 bytes back) there's a function
            # with gLocalLinkPlayer or gSaveBlock2Ptr
            func_start = None
            for instr_off in range(max(0, off - 1024), off, 2):
                hw = read16(rom, instr_off)
                if (hw >> 11) == 0x09:
                    imm8 = hw & 0xFF
                    pc = ((instr_off + ROM_BASE + 4) & ~3)
                    target_lp = pc + imm8 * 4 - ROM_BASE
                    if target_lp == off:
                        func_start = find_function_start(rom, instr_off)
                        break
            if func_start:
                func_end = find_function_end(rom, func_start, 0x300)
                lp_vals = get_literal_pool_values(rom, func_start, func_end)
                addr = func_start + ROM_BASE
                has_sb2 = SAVE_BLOCK2_PTR in lp_vals.values()
                has_llp = G_LOCAL_LINK_PLAYER in lp_vals.values()
                flags = ""
                if has_sb2: flags += " [SB2!]"
                if has_llp: flags += " [LLP!]"
                if has_sb2 or has_llp:
                    print(f"  LP 0x4003 at ROM 0x{off:X} → function 0x{addr:08X}{flags}")

    # Also search for 0x00008000 in LP near SB2 functions
    print("\n  Searching for LP 0x8000 near SB2 functions...")
    for off in range(0, min(len(rom) - 4, 0x2000000), 4):
        val = read32(rom, off)
        if val == 0x8000:
            for instr_off in range(max(0, off - 1024), off, 2):
                hw = read16(rom, instr_off)
                if (hw >> 11) == 0x09:
                    imm8 = hw & 0xFF
                    pc = ((instr_off + ROM_BASE + 4) & ~3)
                    target_lp = pc + imm8 * 4 - ROM_BASE
                    if target_lp == off:
                        func_start = find_function_start(rom, instr_off)
                        if func_start:
                            func_end = find_function_end(rom, func_start, 0x300)
                            lp_vals = get_literal_pool_values(rom, func_start, func_end)
                            has_sb2 = SAVE_BLOCK2_PTR in lp_vals.values()
                            has_llp = G_LOCAL_LINK_PLAYER in lp_vals.values()
                            if has_sb2 or has_llp:
                                addr = func_start + ROM_BASE
                                flags = ""
                                if has_sb2: flags += " [SB2!]"
                                if has_llp: flags += " [LLP!]"
                                print(f"  LP 0x8000 at ROM 0x{off:X} → function 0x{addr:08X}{flags}")
                        break

if __name__ == "__main__":
    main()
