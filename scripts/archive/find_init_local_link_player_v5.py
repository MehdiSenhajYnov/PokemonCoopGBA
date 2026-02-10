"""
Find InitLocalLinkPlayer v5 - Check 0x0811B4E8 and callers of copy function.

Key findings so far:
- gLocalLinkPlayer = 0x02022D74 (confirmed)
- Copy function (gLocalLinkPlayer → gLinkPlayers) = 0x0800AA4C
- ResetLinkPlayers (memset gLocalLinkPlayer) = 0x0800AB3C
- 0x0811B4E8 has BOTH gSaveBlock2Ptr AND gBlockSendBuffer
- Callers 0x080D0BB0 and 0x080D0CA0 have gBlockSendBuffer

The function at 0x0811B4E8 might contain inlined InitLocalLinkPlayer.
Also: the callers might call a function that calls InitLocalLinkPlayer.

Strategy: Deep disassembly of 0x0811B4E8 and of callers 0x080D0BB0/0x080D0CA0,
focusing on their BL targets that lead to gSaveBlock2Ptr access.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
ROM_BASE = 0x08000000
SAVE_BLOCK2_PTR = 0x03005D90
G_LOCAL_LINK_PLAYER = 0x02022D74
G_LINK_PLAYERS = 0x02022CE8
G_BLOCK_SEND_BUFFER = 0x02022BC4

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
    for i in range(offset, max(offset - 0x800, 0), -2):
        hw = read16(rom, i)
        if (hw & 0xFF00) == 0xB500:
            return i
    return None

def find_function_end_multi(rom, start, max_size=0x800):
    """Find the LAST POP {PC}/BX LR (to handle large functions with multiple returns)."""
    last_end = start + max_size
    for i in range(start, min(start + max_size, len(rom)), 2):
        hw = read16(rom, i)
        if (hw & 0xFF00) == 0xBD00:
            last_end = i + 2
        if hw == 0x4770:
            last_end = i + 2
        # If we hit another PUSH {LR}, that's the next function
        if i > start + 2 and (hw & 0xFF00) == 0xB500:
            return i
    return last_end

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

def label_val(val):
    if val == SAVE_BLOCK2_PTR: return " ; gSaveBlock2Ptr"
    if val == G_LOCAL_LINK_PLAYER: return " ; gLocalLinkPlayer"
    if val == G_LINK_PLAYERS: return " ; gLinkPlayers"
    if val == G_BLOCK_SEND_BUFFER: return " ; gBlockSendBuffer"
    if val == 0x030022C0: return " ; gMain"
    if val == 0x08000544: return " ; SetMainCallback2"
    return ""

def disasm(rom, start, end):
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
            regs = [f"R{i}" for i in range(8) if hw & (1 << i)]
            if hw & 0x100: regs.append("LR")
            lines.append(f"  0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
        elif (hw & 0xFF00) == 0xBD00:
            regs = [f"R{i}" for i in range(8) if hw & (1 << i)]
            if hw & 0x100: regs.append("PC")
            lines.append(f"  0x{addr:08X}: POP {{{', '.join(regs)}}}")
        elif (hw >> 11) == 0x09:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            pc = (addr + 4) & ~3; lp_offset = (pc + imm8 * 4) - ROM_BASE
            val = read32(rom, lp_offset) if 0 <= lp_offset < len(rom) - 3 else 0
            lines.append(f"  0x{addr:08X}: LDR R{rd}, =0x{val:08X}{label_val(val)}")
        elif (hw >> 11) == 0x0C:
            rd = hw & 7; rn = (hw >> 3) & 7; imm = ((hw >> 6) & 0x1F) * 4
            lines.append(f"  0x{addr:08X}: STR R{rd}, [R{rn}, #0x{imm:X}]")
        elif (hw >> 11) == 0x0E:
            rd = hw & 7; rn = (hw >> 3) & 7; imm = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: STRB R{rd}, [R{rn}, #0x{imm:X}]")
        elif (hw >> 11) == 0x10:
            rd = hw & 7; rn = (hw >> 3) & 7; imm = ((hw >> 6) & 0x1F) * 2
            lines.append(f"  0x{addr:08X}: STRH R{rd}, [R{rn}, #0x{imm:X}]")
        elif (hw >> 11) == 0x0D:
            rd = hw & 7; rn = (hw >> 3) & 7; imm = ((hw >> 6) & 0x1F) * 4
            lines.append(f"  0x{addr:08X}: LDR R{rd}, [R{rn}, #0x{imm:X}]")
        elif (hw >> 11) == 0x0F:
            rd = hw & 7; rn = (hw >> 3) & 7; imm = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: LDRB R{rd}, [R{rn}, #0x{imm:X}]")
        elif (hw >> 11) == 0x11:
            rd = hw & 7; rn = (hw >> 3) & 7; imm = ((hw >> 6) & 0x1F) * 2
            lines.append(f"  0x{addr:08X}: LDRH R{rd}, [R{rn}, #0x{imm:X}]")
        elif (hw >> 11) == 0x04:
            rd = (hw >> 8) & 7; imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: MOV R{rd}, #0x{imm:X}")
        elif (hw >> 11) == 0x06:
            rd = (hw >> 8) & 7; imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: ADD R{rd}, #0x{imm:X}")
        elif (hw >> 11) == 0x07:
            rd = (hw >> 8) & 7; imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: SUB R{rd}, #0x{imm:X}")
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
        elif (hw >> 11) == 0x00:
            rd = hw & 7; rm = (hw >> 3) & 7; imm = (hw >> 6) & 0x1F
            if imm == 0 and rd == rm:
                lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")
            else:
                lines.append(f"  0x{addr:08X}: LSL R{rd}, R{rm}, #0x{imm:X}")
        elif (hw >> 11) == 0x01:
            rd = hw & 7; rm = (hw >> 3) & 7; imm = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: LSR R{rd}, R{rm}, #0x{imm:X}")
        elif (hw & 0xF800) == 0x2800:
            rd = (hw >> 8) & 7; imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: CMP R{rd}, #0x{imm:X}")
        elif (hw & 0xFFC0) == 0x4280:
            rn = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: CMP R{rn}, R{rm}")
        elif (hw & 0xFFC0) == 0x4300:
            rd = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: ORR R{rd}, R{rm}")
        elif (hw & 0xFFC0) == 0x1800:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: ADD R{rd}, R{rn}, R{rm}")
        elif (hw & 0xFFC0) == 0x1A00:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: SUB R{rd}, R{rn}, R{rm}")
        elif (hw & 0xFF00) == 0xB000:
            imm = (hw & 0x7F) * 4
            if hw & 0x80:
                lines.append(f"  0x{addr:08X}: SUB SP, #0x{imm:X}")
            else:
                lines.append(f"  0x{addr:08X}: ADD SP, #0x{imm:X}")
        else:
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")
        off += 2
    return lines


def main():
    rom = read_rom()

    print("=" * 80)
    print("Disassembly of 0x0811B4E8 (has gSaveBlock2Ptr + gBlockSendBuffer)")
    print("=" * 80)

    # This is a large function. Let's disassemble up to next PUSH
    start = 0x11B4E8
    end = find_function_end_multi(rom, start, 0x400)
    lp_vals = get_literal_pool_values(rom, start, end)
    bls = get_bl_targets(rom, start, end)

    print(f"Function 0x{start + ROM_BASE:08X} to 0x{end + ROM_BASE:08X} ({end - start} bytes)")
    print(f"LP values: {', '.join(f'0x{v:08X}' for v in sorted(set(lp_vals.values())))}")
    print(f"BL targets: {', '.join(f'0x{t:08X}' for _, t in bls)}")

    lines = disasm(rom, start, end)
    for line in lines:
        print(line)

    # Check each BL target for gSaveBlock2Ptr
    print(f"\nBL target analysis for 0x{start + ROM_BASE:08X}:")
    for bl_off, bl_target in bls:
        t_off = bl_target - ROM_BASE
        if t_off < 0 or t_off >= len(rom):
            continue
        t_start = find_function_start(rom, t_off)
        if not t_start:
            t_start = t_off
        t_end = find_function_end_multi(rom, t_start, 0x200)
        t_lp = get_literal_pool_values(rom, t_start, t_end)
        t_size = t_end - t_start

        has_sb2 = SAVE_BLOCK2_PTR in t_lp.values()
        has_llp = G_LOCAL_LINK_PLAYER in t_lp.values()
        flags = ""
        if has_sb2: flags += " [SB2!]"
        if has_llp: flags += " [LLP!]"
        if flags:
            print(f"  BL at 0x{bl_off + ROM_BASE:08X} → 0x{bl_target:08X} ({t_size}b){flags}")
            print(f"    LP: {', '.join(f'0x{v:08X}' for v in sorted(set(t_lp.values())))}")
            if t_size < 200:
                t_lines = disasm(rom, t_start, t_end)
                for line in t_lines:
                    print(f"  {line}")

    # =========================================================================
    # Check 0x080D0BB0 and 0x080D0CA0 BL targets for SB2
    # =========================================================================
    for caller_off in [0x0D0BB0, 0x0D0CA0]:
        print(f"\n{'='*80}")
        print(f"BL targets of caller 0x{caller_off + ROM_BASE:08X} with SB2")
        print(f"{'='*80}")

        c_end = find_function_end_multi(rom, caller_off, 0x400)
        c_bls = get_bl_targets(rom, caller_off, c_end)

        for bl_off, bl_target in c_bls:
            t_off = bl_target - ROM_BASE
            if t_off < 0 or t_off >= len(rom):
                continue
            t_start = find_function_start(rom, t_off)
            if not t_start:
                t_start = t_off
            t_end = find_function_end_multi(rom, t_start, 0x200)
            t_lp = get_literal_pool_values(rom, t_start, t_end)

            has_sb2 = SAVE_BLOCK2_PTR in t_lp.values()
            has_llp = G_LOCAL_LINK_PLAYER in t_lp.values()
            if has_sb2 or has_llp:
                t_size = t_end - t_start
                flags = ""
                if has_sb2: flags += " [SB2!]"
                if has_llp: flags += " [LLP!]"
                print(f"  BL 0x{bl_target:08X} ({t_size}b){flags}")
                print(f"    LP: {', '.join(f'0x{v:08X}' for v in sorted(set(t_lp.values())))}")
                # Check ITS BL targets too
                t_bls = get_bl_targets(rom, t_start, t_end)
                for _, sub_t in t_bls:
                    s_off = sub_t - ROM_BASE
                    if s_off < 0 or s_off >= len(rom):
                        continue
                    s_start = find_function_start(rom, s_off)
                    if not s_start:
                        s_start = s_off
                    s_end = find_function_end_multi(rom, s_start, 0x200)
                    s_lp = get_literal_pool_values(rom, s_start, s_end)
                    s_has_sb2 = SAVE_BLOCK2_PTR in s_lp.values()
                    s_has_llp = G_LOCAL_LINK_PLAYER in s_lp.values()
                    if s_has_sb2 or s_has_llp:
                        s_size = s_end - s_start
                        sf = ""
                        if s_has_sb2: sf += " [SB2!]"
                        if s_has_llp: sf += " [LLP!]"
                        print(f"      -> sub BL 0x{sub_t:08X} ({s_size}b){sf}")

    # =========================================================================
    # Alternative approach: find all functions that have BOTH gSaveBlock2Ptr
    # AND any EWRAM address in 0x02022D00-0x02023000 range in their LP
    # =========================================================================
    print(f"\n{'='*80}")
    print("FINAL: All functions with gSaveBlock2Ptr + EWRAM near gLocalLinkPlayer")
    print(f"{'='*80}")

    sb2_lp_refs = []
    for off in range(0, min(len(rom) - 4, 0x2000000), 4):
        val = read32(rom, off)
        if val == SAVE_BLOCK2_PTR:
            sb2_lp_refs.append(off)

    seen = set()
    for lp_off in sb2_lp_refs:
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
                    func_end = find_function_end_multi(rom, func_start, 0x400)
                    lp_vals = get_literal_pool_values(rom, func_start, func_end)

                    near_llp = [v for v in lp_vals.values() if 0x02022D00 <= v <= 0x02023000]
                    if near_llp:
                        size = func_end - func_start
                        addr = func_start + ROM_BASE
                        print(f"\n  0x{addr:08X} ({size}b)")
                        print(f"    Near-LLP addresses: {', '.join(f'0x{v:08X}' for v in near_llp)}")
                        print(f"    All LP: {', '.join(f'0x{v:08X}' for v in sorted(set(lp_vals.values())))}")

                        if size <= 300:
                            lines = disasm(rom, func_start, func_end)
                            for line in lines:
                                print(line)

if __name__ == "__main__":
    main()
