"""
Find InitLocalLinkPlayer in Pokemon Run & Bun ROM.

Strategy:
1. Narrow range scan near GetMultiplayerId (0x0800A4B1) for functions with gSaveBlock2Ptr in LP
2. Cross-reference with BL→StringCopy calls
3. Check for store-heavy functions (writing struct fields)
4. Also find gLocalLinkPlayer by looking at copy-to-gLinkPlayers functions

Known addresses:
- GetMultiplayerId = 0x0800A4B1
- gSaveBlock2Ptr = 0x03005D90 (IWRAM)
- gLinkPlayers = 0x02022CE8
- StringCopy vanilla = 0x08008C14
"""

import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses
GET_MULTIPLAYER_ID = 0x0800A4B1
SAVE_BLOCK2_PTR = 0x03005D90
G_LINK_PLAYERS = 0x02022CE8
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
    """Decode a THUMB BL instruction at offset. Returns target ROM address or None."""
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
    addr = (offset + ROM_BASE) + 4 + combined
    return addr

def find_function_start(rom, offset):
    """Walk backwards from offset to find PUSH {LR} (function start)."""
    for i in range(offset, max(offset - 0x400, 0), -2):
        hw = read16(rom, i)
        # PUSH {LR} or PUSH {..., LR}
        if (hw & 0xFF00) == 0xB500:
            return i
    return None

def find_function_end(rom, start, max_size=0x400):
    """Find POP {PC} or BX LR after start."""
    for i in range(start, min(start + max_size, len(rom)), 2):
        hw = read16(rom, i)
        # POP {PC} or POP {..., PC}
        if (hw & 0xFF00) == 0xBD00:
            return i + 2
        # BX LR
        if hw == 0x4770:
            return i + 2
    return start + max_size

def get_literal_pool_values(rom, func_start, func_end):
    """Get all literal pool values referenced by LDR Rd, [PC, #imm] in the function."""
    values = {}
    for off in range(func_start, func_end, 2):
        hw = read16(rom, off)
        # LDR Rd, [PC, #imm8*4]: 0x4800-0x4FFF
        if (hw >> 11) == 0x09:  # 0b01001 = LDR Rd, [PC, #imm]
            imm8 = hw & 0xFF
            # PC-relative load: (PC & ~3) + imm8*4, PC = current + 4
            pc = (off + ROM_BASE + 4) & ~3
            lp_addr = pc + imm8 * 4
            lp_offset = lp_addr - ROM_BASE
            if 0 <= lp_offset < len(rom) - 3:
                val = read32(rom, lp_offset)
                values[lp_offset] = val
    return values

def count_stores(rom, func_start, func_end):
    """Count STR, STRB, STRH instructions in the function."""
    count = 0
    for off in range(func_start, func_end, 2):
        hw = read16(rom, off)
        # STR Rd, [Rn, #imm]: 0x6000-0x63FF (opcode bits 15-11 = 01100)
        if (hw >> 11) == 0x0C:
            count += 1
        # STRB Rd, [Rn, #imm]: 0x7000-0x73FF (opcode bits 15-11 = 01110)
        elif (hw >> 11) == 0x0E:
            count += 1
        # STRH Rd, [Rn, #imm]: 0x8000-0x83FF (opcode bits 15-11 = 10000)
        elif (hw >> 11) == 0x10:
            count += 1
        # STR Rd, [Rn, Rm]: 0x5000-0x53FF
        elif (hw >> 9) == 0x28:
            count += 1
        # STRB Rd, [Rn, Rm]: 0x5400-0x57FF
        elif (hw >> 9) == 0x2A:
            count += 1
        # STRH Rd, [Rn, Rm]: 0x5200-0x55FF
        elif (hw >> 9) == 0x29:
            count += 1
    return count

def get_bl_targets(rom, func_start, func_end):
    """Get all BL targets in the function."""
    targets = []
    for off in range(func_start, func_end - 2, 2):
        target = decode_bl(rom, off)
        if target is not None:
            targets.append((off, target))
    return targets

def disassemble_thumb(rom, start, end):
    """Simple THUMB disassembler for key instructions."""
    lines = []
    off = start
    while off < end:
        hw = read16(rom, off)
        addr = off + ROM_BASE

        # Check for BL (two halfwords)
        target = decode_bl(rom, off)
        if target is not None:
            lines.append(f"  0x{addr:08X}: BL 0x{target:08X}")
            off += 4
            continue

        # PUSH
        if (hw & 0xFF00) == 0xB500:
            regs = []
            for i in range(8):
                if hw & (1 << i):
                    regs.append(f"R{i}")
            if hw & 0x100:
                regs.append("LR")
            lines.append(f"  0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
        # POP
        elif (hw & 0xFF00) == 0xBD00:
            regs = []
            for i in range(8):
                if hw & (1 << i):
                    regs.append(f"R{i}")
            if hw & 0x100:
                regs.append("PC")
            lines.append(f"  0x{addr:08X}: POP {{{', '.join(regs)}}}")
        # LDR Rd, [PC, #imm]
        elif (hw >> 11) == 0x09:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            pc = (addr + 4) & ~3
            lp_addr = pc + imm8 * 4
            lp_offset = lp_addr - ROM_BASE
            val = read32(rom, lp_offset) if 0 <= lp_offset < len(rom) - 3 else 0
            lines.append(f"  0x{addr:08X}: LDR R{rd}, [PC, #0x{imm8*4:X}]  ; =0x{val:08X}")
        # STR Rd, [Rn, #imm]
        elif (hw >> 11) == 0x0C:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = ((hw >> 6) & 0x1F) * 4
            lines.append(f"  0x{addr:08X}: STR R{rd}, [R{rn}, #0x{imm5:X}]")
        # STRB
        elif (hw >> 11) == 0x0E:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: STRB R{rd}, [R{rn}, #0x{imm5:X}]")
        # STRH
        elif (hw >> 11) == 0x10:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = ((hw >> 6) & 0x1F) * 2
            lines.append(f"  0x{addr:08X}: STRH R{rd}, [R{rn}, #0x{imm5:X}]")
        # LDR Rd, [Rn, #imm]
        elif (hw >> 11) == 0x0D:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = ((hw >> 6) & 0x1F) * 4
            lines.append(f"  0x{addr:08X}: LDR R{rd}, [R{rn}, #0x{imm5:X}]")
        # LDRB
        elif (hw >> 11) == 0x0F:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: LDRB R{rd}, [R{rn}, #0x{imm5:X}]")
        # LDRH
        elif (hw >> 11) == 0x11:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm5 = ((hw >> 6) & 0x1F) * 2
            lines.append(f"  0x{addr:08X}: LDRH R{rd}, [R{rn}, #0x{imm5:X}]")
        # MOV Rd, #imm
        elif (hw >> 11) == 0x04:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: MOV R{rd}, #0x{imm8:X}")
        # ADD Rd, #imm
        elif (hw >> 11) == 0x06:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: ADD R{rd}, #0x{imm8:X}")
        # BX Rm
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            lines.append(f"  0x{addr:08X}: BX R{rm}")
        else:
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")

        off += 2
    return lines

def find_string_copy(rom):
    """Find StringCopy - a small function that copies bytes until 0xFF terminator.
    In pokeemerald, signature: while (*src != EOS) *dst++ = *src++; *dst = EOS;
    EOS = 0xFF in GBA pokemon. Very short function, typically 20-40 bytes."""
    # Look near vanilla address first (0x08008C14 -> ROM offset 0x8C14)
    # In R&B it may be slightly shifted
    candidates = []

    # Scan a reasonable range for StringCopy pattern
    # It's a leaf function (no BL calls), has LDRB/CMP #0xFF/STRB loop
    for start in range(0x8000, 0xC000, 2):
        hw = read16(rom, start)
        if (hw & 0xFF00) != 0xB500:  # Must start with PUSH {LR}
            continue

        func_end = find_function_end(rom, start, 0x60)
        size = func_end - start
        if size < 10 or size > 60:
            continue

        # Check for CMP Rx, #0xFF pattern and LDRB/STRB
        has_cmp_ff = False
        has_ldrb = False
        has_strb = False
        has_bl = False

        for off in range(start, func_end, 2):
            hw2 = read16(rom, off)
            # CMP Rd, #0xFF
            if (hw2 & 0xF800) == 0x2800 and (hw2 & 0xFF) == 0xFF:
                has_cmp_ff = True
            # LDRB
            if (hw2 >> 11) in (0x0F,):  # LDRB Rd, [Rn, #imm]
                has_ldrb = True
            if (hw2 >> 9) == 0x2E:  # LDRB Rd, [Rn, Rm]
                has_ldrb = True
            # STRB
            if (hw2 >> 11) == 0x0E:
                has_strb = True
            if (hw2 >> 9) == 0x2A:
                has_strb = True
            # BL (not a leaf)
            if decode_bl(rom, off):
                has_bl = True

        if has_cmp_ff and has_ldrb and has_strb and not has_bl:
            candidates.append((start, size))

    return candidates

def main():
    print("=" * 80)
    print("FindInitLocalLinkPlayer - Pokemon Run & Bun ROM Scanner")
    print("=" * 80)

    rom = read_rom()
    print(f"ROM size: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)")

    # =========================================================================
    # PHASE 1: Find StringCopy
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 1: Finding StringCopy")
    print("=" * 80)

    sc_candidates = find_string_copy(rom)
    print(f"Found {len(sc_candidates)} StringCopy candidates:")
    string_copy_addr = None
    for (sc_off, sc_size) in sc_candidates:
        addr = sc_off + ROM_BASE
        print(f"  0x{addr:08X} ({sc_size} bytes)")
        if string_copy_addr is None:
            string_copy_addr = addr  # Take first (closest to vanilla)

    if string_copy_addr:
        print(f"\nUsing StringCopy = 0x{string_copy_addr:08X}")

    # =========================================================================
    # PHASE 2: Narrow range scan for functions with gSaveBlock2Ptr in LP
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 2: Scanning 0x08009000-0x0800B000 for functions with gSaveBlock2Ptr")
    print("=" * 80)

    SCAN_START = 0x9000
    SCAN_END = 0xB000

    # Find all literal pool references to gSaveBlock2Ptr in this range
    lp_refs = []
    for off in range(SCAN_START, SCAN_END, 4):
        val = read32(rom, off)
        if val == SAVE_BLOCK2_PTR:
            lp_refs.append(off)

    print(f"Found {len(lp_refs)} literal pool entries with gSaveBlock2Ptr (0x{SAVE_BLOCK2_PTR:08X}):")
    for lp_off in lp_refs:
        print(f"  LP at ROM offset 0x{lp_off:X} (0x{lp_off + ROM_BASE:08X})")

    # For each LP ref, find which function uses it
    seen_funcs = set()
    candidates = []

    for lp_off in lp_refs:
        # The LDR instruction must be before the LP entry, within range
        # LDR Rd, [PC, #imm8*4] can reach up to 1020 bytes forward
        for instr_off in range(max(SCAN_START, lp_off - 1024), lp_off, 2):
            hw = read16(rom, instr_off)
            if (hw >> 11) != 0x09:  # Not LDR Rd, [PC, #imm]
                continue
            imm8 = hw & 0xFF
            pc = ((instr_off + ROM_BASE + 4) & ~3)
            target_lp = pc + imm8 * 4 - ROM_BASE
            if target_lp == lp_off:
                # Found instruction referencing this LP
                func_start = find_function_start(rom, instr_off)
                if func_start and func_start not in seen_funcs:
                    seen_funcs.add(func_start)
                    func_end = find_function_end(rom, func_start, 0x200)
                    size = func_end - func_start
                    stores = count_stores(rom, func_start, func_end)
                    bls = get_bl_targets(rom, func_start, func_end)
                    lp_vals = get_literal_pool_values(rom, func_start, func_end)

                    # Check if any BL targets StringCopy
                    calls_stringcopy = False
                    if string_copy_addr:
                        for (bl_off, bl_target) in bls:
                            if bl_target == string_copy_addr or bl_target == (string_copy_addr | 1):
                                calls_stringcopy = True

                    candidates.append({
                        'start': func_start,
                        'end': func_end,
                        'size': size,
                        'stores': stores,
                        'bls': bls,
                        'lp_vals': lp_vals,
                        'calls_stringcopy': calls_stringcopy,
                    })

    print(f"\nFound {len(candidates)} candidate functions:")
    for c in sorted(candidates, key=lambda x: x['start']):
        addr = c['start'] + ROM_BASE
        sc_marker = " *** CALLS StringCopy ***" if c['calls_stringcopy'] else ""
        print(f"\n  Function at 0x{addr:08X} ({c['size']} bytes, {c['stores']} stores, {len(c['bls'])} BLs){sc_marker}")

        # Show LP values
        print(f"    LP values:")
        for lp_off, val in sorted(c['lp_vals'].items()):
            label = ""
            if val == SAVE_BLOCK2_PTR:
                label = " (gSaveBlock2Ptr)"
            elif val == G_LINK_PLAYERS:
                label = " (gLinkPlayers)"
            elif 0x02000000 <= val <= 0x0203FFFF:
                label = " (EWRAM)"
            elif 0x03000000 <= val <= 0x03007FFF:
                label = " (IWRAM)"
            elif 0x08000000 <= val <= 0x09FFFFFF:
                label = " (ROM)"
            print(f"      0x{val:08X}{label}")

        # Show BL targets
        if c['bls']:
            print(f"    BL targets:")
            for (bl_off, bl_target) in c['bls']:
                sc_label = " (StringCopy!)" if string_copy_addr and (bl_target == string_copy_addr or bl_target == (string_copy_addr | 1)) else ""
                print(f"      0x{bl_target:08X}{sc_label}")

    # =========================================================================
    # PHASE 3: Score and rank candidates
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 3: Ranking candidates for InitLocalLinkPlayer")
    print("=" * 80)

    # InitLocalLinkPlayer characteristics:
    # 1. Has gSaveBlock2Ptr in LP (reads player name, trainer ID, gender)
    # 2. Has many stores (writes struct fields: version, language, id, name, gender)
    # 3. Calls StringCopy (copies player name)
    # 4. Size ~80-200 bytes
    # 5. Has an EWRAM address in LP (gLocalLinkPlayer destination)
    # 6. Close to GetMultiplayerId (0x0800A4B1)

    scored = []
    for c in candidates:
        score = 0
        reasons = []

        # Stores
        if c['stores'] >= 5:
            score += 3
            reasons.append(f"{c['stores']} stores (writes struct fields)")
        elif c['stores'] >= 3:
            score += 1
            reasons.append(f"{c['stores']} stores")

        # StringCopy call
        if c['calls_stringcopy']:
            score += 5
            reasons.append("calls StringCopy (copies player name)")

        # Size
        if 60 <= c['size'] <= 200:
            score += 2
            reasons.append(f"size {c['size']} bytes (ideal range)")
        elif 40 <= c['size'] <= 300:
            score += 1
            reasons.append(f"size {c['size']} bytes (acceptable)")

        # EWRAM address in LP (gLocalLinkPlayer)
        ewram_addrs = [v for v in c['lp_vals'].values() if 0x02000000 <= v <= 0x0203FFFF and v != G_LINK_PLAYERS]
        if ewram_addrs:
            score += 3
            reasons.append(f"EWRAM addr in LP: {', '.join(f'0x{a:08X}' for a in ewram_addrs)} (likely gLocalLinkPlayer)")

        # Proximity to GetMultiplayerId
        dist = abs((c['start'] + ROM_BASE) - GET_MULTIPLAYER_ID)
        if dist < 0x2000:
            score += 2
            reasons.append(f"close to GetMultiplayerId ({dist:#x} bytes)")
        elif dist < 0x4000:
            score += 1
            reasons.append(f"near GetMultiplayerId ({dist:#x} bytes)")

        scored.append((score, c, reasons))

    scored.sort(key=lambda x: -x[0])

    for rank, (score, c, reasons) in enumerate(scored):
        addr = c['start'] + ROM_BASE
        print(f"\n#{rank+1} [Score: {score}] 0x{addr:08X} ({c['size']} bytes)")
        for r in reasons:
            print(f"    + {r}")

    # =========================================================================
    # PHASE 4: Disassemble top candidates
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 4: Disassembly of top candidates")
    print("=" * 80)

    for rank, (score, c, reasons) in enumerate(scored[:5]):
        addr = c['start'] + ROM_BASE
        print(f"\n--- Function at 0x{addr:08X} (Score: {score}, {c['size']} bytes) ---")
        lines = disassemble_thumb(rom, c['start'], c['end'])
        for line in lines:
            print(line)

    # =========================================================================
    # PHASE 5: Wider scan — ALL functions with gSaveBlock2Ptr + many stores
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 5: Wider ROM scan for gSaveBlock2Ptr + 5+ stores + <200 bytes")
    print("=" * 80)

    # Find ALL literal pool references to gSaveBlock2Ptr in the ROM
    all_lp_refs = []
    for off in range(0, min(len(rom) - 4, 0x1000000), 4):
        val = read32(rom, off)
        if val == SAVE_BLOCK2_PTR:
            all_lp_refs.append(off)

    print(f"Total LP entries with gSaveBlock2Ptr: {len(all_lp_refs)}")

    # Find functions referencing these
    all_seen = set()
    all_candidates = []

    for lp_off in all_lp_refs:
        for instr_off in range(max(0, lp_off - 1024), lp_off, 2):
            hw = read16(rom, instr_off)
            if (hw >> 11) != 0x09:
                continue
            imm8 = hw & 0xFF
            pc = ((instr_off + ROM_BASE + 4) & ~3)
            target_lp = pc + imm8 * 4 - ROM_BASE
            if target_lp == lp_off:
                func_start = find_function_start(rom, instr_off)
                if func_start and func_start not in all_seen:
                    all_seen.add(func_start)
                    func_end = find_function_end(rom, func_start, 0x200)
                    size = func_end - func_start
                    if size > 200:
                        continue
                    stores = count_stores(rom, func_start, func_end)
                    if stores < 5:
                        continue
                    bls = get_bl_targets(rom, func_start, func_end)
                    lp_vals = get_literal_pool_values(rom, func_start, func_end)

                    calls_sc = False
                    if string_copy_addr:
                        for (bl_off, bl_target) in bls:
                            if bl_target == string_copy_addr or bl_target == (string_copy_addr | 1):
                                calls_sc = True

                    ewram_addrs = [v for v in lp_vals.values() if 0x02000000 <= v <= 0x0203FFFF]

                    all_candidates.append({
                        'start': func_start,
                        'end': func_end,
                        'size': size,
                        'stores': stores,
                        'bls': bls,
                        'lp_vals': lp_vals,
                        'calls_stringcopy': calls_sc,
                        'ewram_addrs': ewram_addrs,
                        'dist_to_gmp': abs((func_start + ROM_BASE) - GET_MULTIPLAYER_ID),
                    })

    # Sort by: calls StringCopy first, then stores descending, then proximity
    all_candidates.sort(key=lambda x: (-int(x['calls_stringcopy']), -x['stores'], x['dist_to_gmp']))

    print(f"Found {len(all_candidates)} functions with gSaveBlock2Ptr + 5+ stores + <200 bytes:")
    for c in all_candidates[:20]:
        addr = c['start'] + ROM_BASE
        sc_flag = " [StringCopy!]" if c['calls_stringcopy'] else ""
        ewram_str = f" EWRAM:[{', '.join(f'0x{a:08X}' for a in c['ewram_addrs'])}]" if c['ewram_addrs'] else ""
        print(f"  0x{addr:08X} ({c['size']}b, {c['stores']} stores, dist={c['dist_to_gmp']:#x}){sc_flag}{ewram_str}")

    # Disassemble the best wider candidate that calls StringCopy
    best_sc = [c for c in all_candidates if c['calls_stringcopy']]
    if best_sc:
        print(f"\n--- Best candidates calling StringCopy ---")
        for c in best_sc[:3]:
            addr = c['start'] + ROM_BASE
            print(f"\n  Function at 0x{addr:08X} ({c['size']} bytes, {c['stores']} stores)")
            print(f"  LP values: {', '.join(f'0x{v:08X}' for v in sorted(c['lp_vals'].values()))}")
            lines = disassemble_thumb(rom, c['start'], c['end'])
            for line in lines:
                print(line)

    # =========================================================================
    # PHASE 6: Strategy 4 — Find gLocalLinkPlayer via copy-to-gLinkPlayers
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 6: Find gLocalLinkPlayer via copy to gLinkPlayers")
    print("=" * 80)

    # Find functions that have gLinkPlayers (0x02022CE8) in their LP
    # AND are small (copy function that copies gLocalLinkPlayer → gLinkPlayers[id])
    glp_lp_refs = []
    for off in range(0, min(len(rom) - 4, 0x1000000), 4):
        val = read32(rom, off)
        if val == G_LINK_PLAYERS:
            glp_lp_refs.append(off)

    print(f"LP entries with gLinkPlayers (0x{G_LINK_PLAYERS:08X}): {len(glp_lp_refs)}")

    glp_seen = set()
    glp_funcs = []

    for lp_off in glp_lp_refs:
        for instr_off in range(max(0, lp_off - 1024), lp_off, 2):
            hw = read16(rom, instr_off)
            if (hw >> 11) != 0x09:
                continue
            imm8 = hw & 0xFF
            pc = ((instr_off + ROM_BASE + 4) & ~3)
            target_lp = pc + imm8 * 4 - ROM_BASE
            if target_lp == lp_off:
                func_start = find_function_start(rom, instr_off)
                if func_start and func_start not in glp_seen:
                    glp_seen.add(func_start)
                    func_end = find_function_end(rom, func_start, 0x200)
                    size = func_end - func_start
                    if size > 300:
                        continue
                    lp_vals = get_literal_pool_values(rom, func_start, func_end)
                    bls = get_bl_targets(rom, func_start, func_end)

                    # Check if it has another EWRAM address (could be gLocalLinkPlayer)
                    other_ewram = [v for v in lp_vals.values() if 0x02000000 <= v <= 0x0203FFFF and v != G_LINK_PLAYERS]

                    # Check if BL targets include memcpy-like or GetMultiplayerId
                    calls_gmp = any(bt == GET_MULTIPLAYER_ID or bt == (GET_MULTIPLAYER_ID & ~1) for _, bt in bls)

                    glp_funcs.append({
                        'start': func_start,
                        'end': func_end,
                        'size': size,
                        'lp_vals': lp_vals,
                        'bls': bls,
                        'other_ewram': other_ewram,
                        'calls_gmp': calls_gmp,
                    })

    # Sort: those calling GetMultiplayerId first, then by other EWRAM, then size
    glp_funcs.sort(key=lambda x: (-int(x['calls_gmp']), -len(x['other_ewram']), x['size']))

    print(f"Found {len(glp_funcs)} functions referencing gLinkPlayers (<300 bytes):")
    for c in glp_funcs[:15]:
        addr = c['start'] + ROM_BASE
        gmp_flag = " [calls GetMultiplayerId!]" if c['calls_gmp'] else ""
        ewram_str = f" OtherEWRAM:[{', '.join(f'0x{a:08X}' for a in c['other_ewram'])}]" if c['other_ewram'] else ""
        print(f"  0x{addr:08X} ({c['size']}b, {len(c['bls'])} BLs){gmp_flag}{ewram_str}")

    # Disassemble top candidates that call GetMultiplayerId
    gmp_callers = [c for c in glp_funcs if c['calls_gmp']]
    if gmp_callers:
        print(f"\n--- Functions with gLinkPlayers + GetMultiplayerId (copy functions) ---")
        for c in gmp_callers[:5]:
            addr = c['start'] + ROM_BASE
            print(f"\n  Function at 0x{addr:08X} ({c['size']} bytes)")
            print(f"  LP values: {', '.join(f'0x{v:08X}' for v in sorted(c['lp_vals'].values()))}")
            lines = disassemble_thumb(rom, c['start'], c['end'])
            for line in lines:
                print(line)

            # If we found gLocalLinkPlayer address, report it
            if c['other_ewram']:
                for ew in c['other_ewram']:
                    print(f"\n  *** Possible gLocalLinkPlayer = 0x{ew:08X} ***")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    # Report best InitLocalLinkPlayer candidate
    if scored:
        best_score, best_c, best_reasons = scored[0]
        best_addr = best_c['start'] + ROM_BASE
        print(f"\nBest InitLocalLinkPlayer candidate (narrow range):")
        print(f"  Address: 0x{best_addr:08X} | 0x{best_addr | 1:08X} (THUMB)")
        print(f"  Size: {best_c['size']} bytes")
        print(f"  Score: {best_score}")
        for r in best_reasons:
            print(f"    + {r}")

    if best_sc:
        addr = best_sc[0]['start'] + ROM_BASE
        print(f"\nBest InitLocalLinkPlayer candidate (wide scan, calls StringCopy):")
        print(f"  Address: 0x{addr:08X} | 0x{addr | 1:08X} (THUMB)")
        print(f"  Size: {best_sc[0]['size']} bytes, {best_sc[0]['stores']} stores")

    if gmp_callers:
        for c in gmp_callers[:3]:
            addr = c['start'] + ROM_BASE
            if c['other_ewram']:
                for ew in c['other_ewram']:
                    print(f"\nPossible gLocalLinkPlayer = 0x{ew:08X}")
                    print(f"  Found in copy function at 0x{addr:08X}")

if __name__ == "__main__":
    main()
