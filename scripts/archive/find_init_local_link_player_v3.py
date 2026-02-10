"""
Find InitLocalLinkPlayer v3 - broader approach.

Key finding from v2: gLocalLinkPlayer = 0x02022D74 (confirmed).
But InitLocalLinkPlayer doesn't reference gLocalLinkPlayer in its LP.

New hypothesis: InitLocalLinkPlayer might:
1. Use gSaveBlock2 directly (not via pointer — R&B might inline the address)
2. Be INLINED into another function
3. Have been REMOVED or CHANGED in R&B expansion

Let's try:
A. Find all functions in 0x08009000-0x0800E000 that have BOTH many stores AND call StringCopy-like functions
B. Look at what functions call into the 0x0800AA00-0x0800AC00 region (link.c area)
C. Scan for functions that write the game version constant (GAME_VERSION = 3 for Emerald)
D. Look at callers of the copy function 0x0800AA4C more deeply
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

G_LOCAL_LINK_PLAYER = 0x02022D74
SAVE_BLOCK2_PTR = 0x03005D90
G_LINK_PLAYERS = 0x02022CE8
GET_MULTIPLAYER_ID = 0x0800A4B1
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

def count_stores(rom, func_start, func_end):
    count = 0
    for off in range(func_start, func_end, 2):
        hw = read16(rom, off)
        op = hw >> 11
        if op in (0x0C, 0x0E, 0x10):
            count += 1
        elif (hw >> 9) in (0x28, 0x29, 0x2A):
            count += 1
    return count

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
            pc = (addr + 4) & ~3; lp_addr = pc + imm8 * 4; lp_offset = lp_addr - ROM_BASE
            val = read32(rom, lp_offset) if 0 <= lp_offset < len(rom) - 3 else 0
            label = ""
            if val == SAVE_BLOCK2_PTR: label = " ; gSaveBlock2Ptr"
            elif val == G_LOCAL_LINK_PLAYER: label = " ; gLocalLinkPlayer"
            elif val == G_LINK_PLAYERS: label = " ; gLinkPlayers"
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
        else:
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")
        off += 2
    return lines


def main():
    print("=" * 80)
    print("FindInitLocalLinkPlayer v3")
    print("=" * 80)

    rom = read_rom()

    # =========================================================================
    # APPROACH A: Look at callers of 0x0800AA4C (the copy fn) deeply
    # The callers are at 0x080D09F4, 0x080D0BB0, 0x080D0CA0
    # These are in the link setup code. One of them should CALL InitLocalLinkPlayer
    # before calling the copy function.
    # =========================================================================
    print("\n" + "=" * 80)
    print("APPROACH A: Analyze callers of copy function 0x0800AA4C")
    print("=" * 80)

    callers = [0x0D09F4, 0x0D0BB0, 0x0D0CA0]
    for caller_off in callers:
        func_end = find_function_end(rom, caller_off, 0x300)
        size = func_end - caller_off
        bls = get_bl_targets(rom, caller_off, func_end)
        lp_vals = get_literal_pool_values(rom, caller_off, func_end)

        addr = caller_off + ROM_BASE
        print(f"\n--- Caller at 0x{addr:08X} ({size} bytes) ---")
        print(f"  LP: {', '.join(f'0x{v:08X}' for v in sorted(set(lp_vals.values())))}")
        print(f"  BL targets: {', '.join(f'0x{t:08X}' for _, t in bls)}")

        lines = disassemble_thumb(rom, caller_off, func_end)
        for line in lines:
            print(line)

    # =========================================================================
    # APPROACH B: Look for the vanilla InitLocalLinkPlayer pattern
    # In pokeemerald vanilla:
    #   void InitLocalLinkPlayer(void) {
    #       gLocalLinkPlayer.version = GAME_VERSION;
    #       gLocalLinkPlayer.lp_field_2 = GAME_LANGUAGE;
    #       gLocalLinkPlayer.trainerId = gSaveBlock2Ptr->playerTrainerId[0]
    #                                  | (gSaveBlock2Ptr->playerTrainerId[1] << 8)
    #                                  | (gSaveBlock2Ptr->playerTrainerId[2] << 16)
    #                                  | (gSaveBlock2Ptr->playerTrainerId[3] << 24);
    #       StringCopy(gLocalLinkPlayer.name, gSaveBlock2Ptr->playerName);
    #       gLocalLinkPlayer.gender = gSaveBlock2Ptr->playerGender;
    #       gLocalLinkPlayer.linkType = gLinkType;
    #       gLocalLinkPlayer.language = gGameLanguage;
    #   }
    #
    # This writes GAME_VERSION (3 for Emerald) as first STRH.
    # In R&B/expansion, GAME_VERSION = VERSION_EMERALD = 3.
    # Let's look for: MOV Rx, #3 followed by STRH Rx, [Ry, #0] near gLocalLinkPlayer
    # =========================================================================

    # =========================================================================
    # APPROACH C: Exhaustive scan near link.c
    # Let me scan ALL functions in 0x08009000-0x0800E000 and for each, check
    # if its BL targets include any of the known link.c functions.
    # Then disassemble the most interesting ones.
    # =========================================================================
    print("\n" + "=" * 80)
    print("APPROACH C: Find ALL BL sites calling into 0x0800A000-0x0800AC00 range")
    print("=" * 80)

    # The link.c functions are in 0x0800A000-0x0800AC00.
    # Find all BL calls TO this range from anywhere in the ROM.
    # Group by target to see which link.c functions are called and from where.

    link_range_start = 0x0800A000
    link_range_end = 0x0800AC00

    # Let's specifically find calls to the range near InitLocalLinkPlayer
    # In vanilla emerald, InitLocalLinkPlayer is at 0x08009638
    # In R&B, the link.c area seems to be around 0x0800A000-0x0800AC00

    # Let's enumerate ALL functions in 0x08009000-0x0800AC00
    print("\nAll functions (PUSH {LR}) in 0x08009000-0x0800AC00:")
    func_list = []
    for off in range(0x9000, 0xAC00, 2):
        hw = read16(rom, off)
        if (hw & 0xFF00) == 0xB500:
            func_end = find_function_end(rom, off, 0x300)
            size = func_end - off
            stores = count_stores(rom, off, func_end)
            bls = get_bl_targets(rom, off, func_end)
            lp_vals = get_literal_pool_values(rom, off, func_end)
            func_list.append({
                'start': off,
                'end': func_end,
                'size': size,
                'stores': stores,
                'bls': bls,
                'lp_vals': lp_vals,
            })

    print(f"Found {len(func_list)} functions")
    for f in func_list:
        addr = f['start'] + ROM_BASE
        lp_str = ', '.join(f'0x{v:08X}' for v in sorted(set(f['lp_vals'].values())))
        print(f"  0x{addr:08X} ({f['size']}b, {f['stores']}s, {len(f['bls'])}bl) LP:[{lp_str}]")

    # =========================================================================
    # APPROACH D: Direct scan for functions writing to 0x02022D74 region
    # Maybe the function doesn't use LP for gLocalLinkPlayer — maybe it
    # computes the address. But more likely, let's check if there are functions
    # that have 0x02022D74 or nearby addresses but through different LP alignment.
    # =========================================================================
    print("\n" + "=" * 80)
    print("APPROACH D: Look for LP refs near gLocalLinkPlayer (0x02022D60-0x02022DA0)")
    print("=" * 80)

    for target_val in range(0x02022D60, 0x02022DA0, 4):
        refs = []
        for off in range(0, min(len(rom) - 4, 0x2000000), 4):
            val = read32(rom, off)
            if val == target_val:
                refs.append(off)
        if refs:
            print(f"  0x{target_val:08X}: {len(refs)} LP refs at {', '.join(f'0x{r+ROM_BASE:08X}' for r in refs[:10])}")

    # =========================================================================
    # APPROACH E: In pokeemerald-expansion, check if InitLocalLinkPlayer
    # was modified to use a different pattern.
    # In expansion, the function might store MORE fields.
    # Also check: maybe gSaveBlock2 is accessed differently in R&B.
    # Let's look at what 0x03005D90 actually contains — it's a POINTER.
    # The function dereferences it: LDR Rx, =gSaveBlock2Ptr; LDR Ry, [Rx]
    # Then reads playerTrainerId at offset +0x0A, playerName at +0x00, gender at +0x08
    # In expansion: SaveBlock2 has playerName at +0, playerGender at +8, trainerId at +0xA
    # =========================================================================
    print("\n" + "=" * 80)
    print("APPROACH E: Check callers of 0x0800AA4C more carefully")
    print("= These callers SET UP the link, and one of them must call InitLocalLinkPlayer")
    print("=" * 80)

    # The caller at 0x080D09F4 etc. — let's trace what they call BEFORE 0x0800AA4C
    for caller_off in callers:
        func_end = find_function_end(rom, caller_off, 0x300)
        bls = get_bl_targets(rom, caller_off, func_end)
        addr = caller_off + ROM_BASE
        print(f"\n  Caller 0x{addr:08X} calls:")
        for bl_off, bl_target in bls:
            # For each BL target, check if IT references gSaveBlock2Ptr or gLocalLinkPlayer
            target_off = bl_target - ROM_BASE
            if target_off < 0 or target_off >= len(rom):
                print(f"    0x{bl_target:08X} (outside ROM)")
                continue
            t_start = find_function_start(rom, target_off)
            if not t_start:
                t_start = target_off
            t_end = find_function_end(rom, t_start, 0x300)
            t_lp = get_literal_pool_values(rom, t_start, t_end)
            t_size = t_end - t_start
            t_stores = count_stores(rom, t_start, t_end)
            t_bls = get_bl_targets(rom, t_start, t_end)

            has_sb2 = SAVE_BLOCK2_PTR in t_lp.values()
            has_llp = G_LOCAL_LINK_PLAYER in t_lp.values()
            has_glp = G_LINK_PLAYERS in t_lp.values()

            flags = ""
            if has_sb2: flags += " [SB2!]"
            if has_llp: flags += " [LLP!]"
            if has_glp: flags += " [GLP]"

            print(f"    0x{bl_target:08X} ({t_size}b, {t_stores}s, {len(t_bls)}bl){flags}")

            # If it has gSaveBlock2Ptr, show its LP and disassembly
            if has_sb2 or has_llp:
                print(f"      LP: {', '.join(f'0x{v:08X}' for v in sorted(set(t_lp.values())))}")
                t_lines = disassemble_thumb(rom, t_start, t_end)
                for line in t_lines:
                    print(f"    {line}")

    # =========================================================================
    # APPROACH F: Direct brute search for InitLocalLinkPlayer signature
    # The function writes: STRH version, [ptr, #0]; STRH language, [ptr, #2];
    # STR trainerId, [ptr, #4]; then BL StringCopy for name; STRB gender, [ptr, #0x10]
    # Key: sequence of STRH offset#0, STRH offset#2, STR offset#4 in close proximity
    # =========================================================================
    print("\n" + "=" * 80)
    print("APPROACH F: Scan for STRH Rx,[Ry,#0] + STRH Rx,[Ry,#2] + STR Rx,[Ry,#4] pattern")
    print("=" * 80)

    # Look for the specific store pattern
    candidates = []
    for off in range(0, min(len(rom) - 20, 0x2000000), 2):
        # Look for STRH Rd, [Rn, #0] (writes .version)
        hw = read16(rom, off)
        if (hw >> 11) == 0x10:  # STRH imm
            imm5 = ((hw >> 6) & 0x1F) * 2
            rn = (hw >> 3) & 7
            if imm5 == 0:
                # Check next few instructions for STRH [same_rn, #2] and STR [same_rn, #4]
                found_strh2 = False
                found_str4 = False
                for off2 in range(off + 2, min(off + 20, len(rom)), 2):
                    hw2 = read16(rom, off2)
                    if (hw2 >> 11) == 0x10:  # STRH
                        imm5_2 = ((hw2 >> 6) & 0x1F) * 2
                        rn2 = (hw2 >> 3) & 7
                        if imm5_2 == 2 and rn2 == rn:
                            found_strh2 = True
                    if (hw2 >> 11) == 0x0C:  # STR
                        imm5_2 = ((hw2 >> 6) & 0x1F) * 4
                        rn2 = (hw2 >> 3) & 7
                        if imm5_2 == 4 and rn2 == rn:
                            found_str4 = True

                if found_strh2 and found_str4:
                    func_start = find_function_start(rom, off)
                    if func_start:
                        candidates.append(func_start)

    # Deduplicate
    candidates = sorted(set(candidates))
    print(f"Found {len(candidates)} functions with STRH#0 + STRH#2 + STR#4 pattern:")
    for c in candidates[:30]:
        addr = c + ROM_BASE
        func_end = find_function_end(rom, c, 0x200)
        size = func_end - c
        stores = count_stores(rom, c, func_end)
        lp_vals = get_literal_pool_values(rom, c, func_end)
        bls = get_bl_targets(rom, c, func_end)

        has_sb2 = SAVE_BLOCK2_PTR in lp_vals.values()
        has_llp = G_LOCAL_LINK_PLAYER in lp_vals.values()

        flags = ""
        if has_sb2: flags += " [SB2!]"
        if has_llp: flags += " [LLP!]"

        lp_str = ', '.join(f'0x{v:08X}' for v in sorted(set(lp_vals.values())))
        print(f"  0x{addr:08X} ({size}b, {stores}s, {len(bls)}bl){flags} LP:[{lp_str}]")

        # Disassemble the most interesting ones (near link.c, has sb2, has llp, or small with stores)
        if has_sb2 or has_llp or (0x08009000 <= addr <= 0x0800E000 and stores >= 3):
            lines = disassemble_thumb(rom, c, func_end)
            for line in lines:
                print(line)
            print()

if __name__ == "__main__":
    main()
