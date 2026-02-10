"""
Find InitLocalLinkPlayer in Pokemon Run & Bun ROM - Phase 2.

We found gLocalLinkPlayer = 0x02022D74 from the copy function at 0x0800AA4C.
Now find InitLocalLinkPlayer = the function that WRITES TO 0x02022D74.

Strategy:
1. Find ALL LP references to 0x02022D74 in ROM
2. Disassemble each function
3. InitLocalLinkPlayer is the one that STORES to the struct (many STR/STRB/STRH)
   AND has gSaveBlock2Ptr (0x03005D90) in LP (reads player data)

Also:
- EOS in pokeemerald = 0xFF. StringCopy uses CMP #0xFF.
  But maybe R&B uses a different terminator? Let's also try 0x00.
- Try finding StringCopy with both EOS values.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known
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
        if op in (0x0C, 0x0E, 0x10):  # STR, STRB, STRH imm
            count += 1
        elif (hw >> 9) in (0x28, 0x29, 0x2A):  # STR, STRH, STRB reg
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
            label = ""
            if target == GET_MULTIPLAYER_ID or target == (GET_MULTIPLAYER_ID & ~1):
                label = " ; GetMultiplayerId"
            lines.append(f"  0x{addr:08X}: BL 0x{target:08X}{label}")
            off += 4
            continue
        if (hw & 0xFF00) == 0xB500:
            regs = []
            for i in range(8):
                if hw & (1 << i):
                    regs.append(f"R{i}")
            if hw & 0x100:
                regs.append("LR")
            lines.append(f"  0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
        elif (hw & 0xFF00) == 0xBD00:
            regs = []
            for i in range(8):
                if hw & (1 << i):
                    regs.append(f"R{i}")
            if hw & 0x100:
                regs.append("PC")
            lines.append(f"  0x{addr:08X}: POP {{{', '.join(regs)}}}")
        elif (hw >> 11) == 0x09:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            pc = (addr + 4) & ~3
            lp_addr = pc + imm8 * 4
            lp_offset = lp_addr - ROM_BASE
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
        elif (hw & 0xFFC0) == 0x4280:
            rn = hw & 7; rm = (hw >> 3) & 7
            lines.append(f"  0x{addr:08X}: CMP R{rn}, R{rm}")
        elif (hw & 0xF800) == 0x2800:
            rd = (hw >> 8) & 7; imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: CMP R{rd}, #0x{imm8:X}")
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            rname = f"R{rm}" if rm < 14 else ("LR" if rm == 14 else "PC")
            lines.append(f"  0x{addr:08X}: BX {rname}")
        elif (hw & 0xFFC0) == 0x1800:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: ADD R{rd}, R{rn}, R{rm}")
        elif (hw & 0xFFC0) == 0x1A00:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: SUB R{rd}, R{rn}, R{rm}")
        elif (hw & 0xFF00) == 0x4600:
            rd = (hw & 7) | ((hw >> 4) & 8)
            rm = (hw >> 3) & 0xF
            rname_d = f"R{rd}" if rd < 13 else ("SP" if rd == 13 else ("LR" if rd == 14 else "PC"))
            rname_m = f"R{rm}" if rm < 13 else ("SP" if rm == 13 else ("LR" if rm == 14 else "PC"))
            lines.append(f"  0x{addr:08X}: MOV {rname_d}, {rname_m}")
        elif (hw & 0xFF00) == 0x4400:
            rd = (hw & 7) | ((hw >> 4) & 8)
            rm = (hw >> 3) & 0xF
            lines.append(f"  0x{addr:08X}: ADD R{rd}, R{rm}")
        elif (hw & 0xFE00) == 0x5600:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: LDRSB R{rd}, [R{rn}, R{rm}]")
        elif (hw & 0xFE00) == 0x5C00:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: LDRB R{rd}, [R{rn}, R{rm}]")
        elif (hw & 0xFE00) == 0x5800:
            rd = hw & 7; rn = (hw >> 3) & 7; rm = (hw >> 6) & 7
            lines.append(f"  0x{addr:08X}: LDR R{rd}, [R{rn}, R{rm}]")
        elif (hw & 0xF800) == 0xD000:
            cond = (hw >> 8) & 0xF
            imm8 = hw & 0xFF
            if imm8 & 0x80: imm8 -= 256
            target_addr = addr + 4 + imm8 * 2
            cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                          "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]
            if cond < 15:
                lines.append(f"  0x{addr:08X}: {cond_names[cond]} 0x{target_addr:08X}")
            else:
                lines.append(f"  0x{addr:08X}: SVC #0x{hw & 0xFF:X}")
        elif (hw & 0xF800) == 0xE000:
            imm11 = hw & 0x7FF
            if imm11 & 0x400: imm11 -= 0x800
            target_addr = addr + 4 + imm11 * 2
            lines.append(f"  0x{addr:08X}: B 0x{target_addr:08X}")
        elif (hw >> 11) == 0x00:
            rd = hw & 7; rm = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: LSL R{rd}, R{rm}, #0x{imm5:X}")
        elif (hw >> 11) == 0x01:
            rd = hw & 7; rm = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: LSR R{rd}, R{rm}, #0x{imm5:X}")
        elif (hw >> 11) == 0x02:
            rd = hw & 7; rm = (hw >> 3) & 7; imm5 = (hw >> 6) & 0x1F
            lines.append(f"  0x{addr:08X}: ASR R{rd}, R{rm}, #0x{imm5:X}")
        else:
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")
        off += 2
    return lines

def main():
    print("=" * 80)
    print("FindInitLocalLinkPlayer v2 - Using gLocalLinkPlayer = 0x02022D74")
    print("=" * 80)

    rom = read_rom()
    print(f"ROM size: {len(rom)} bytes")

    # =========================================================================
    # STEP 1: Find ALL LP references to gLocalLinkPlayer (0x02022D74)
    # =========================================================================
    print("\n" + "=" * 80)
    print("STEP 1: Find ALL LP references to gLocalLinkPlayer (0x02022D74)")
    print("=" * 80)

    lp_refs = []
    for off in range(0, min(len(rom) - 4, 0x2000000), 4):
        val = read32(rom, off)
        if val == G_LOCAL_LINK_PLAYER:
            lp_refs.append(off)

    print(f"Found {len(lp_refs)} LP entries with gLocalLinkPlayer:")
    for lp_off in lp_refs:
        print(f"  ROM offset 0x{lp_off:X} (0x{lp_off + ROM_BASE:08X})")

    # =========================================================================
    # STEP 2: Find functions that reference gLocalLinkPlayer
    # =========================================================================
    print("\n" + "=" * 80)
    print("STEP 2: Find functions referencing gLocalLinkPlayer")
    print("=" * 80)

    seen_funcs = set()
    candidates = []

    for lp_off in lp_refs:
        for instr_off in range(max(0, lp_off - 1024), lp_off, 2):
            hw = read16(rom, instr_off)
            if (hw >> 11) != 0x09:
                continue
            imm8 = hw & 0xFF
            pc = ((instr_off + ROM_BASE + 4) & ~3)
            target_lp = pc + imm8 * 4 - ROM_BASE
            if target_lp == lp_off:
                func_start = find_function_start(rom, instr_off)
                if func_start and func_start not in seen_funcs:
                    seen_funcs.add(func_start)
                    func_end = find_function_end(rom, func_start, 0x300)
                    size = func_end - func_start
                    stores = count_stores(rom, func_start, func_end)
                    bls = get_bl_targets(rom, func_start, func_end)
                    lp_vals = get_literal_pool_values(rom, func_start, func_end)

                    has_sb2 = SAVE_BLOCK2_PTR in lp_vals.values()
                    has_glp = G_LINK_PLAYERS in lp_vals.values()

                    candidates.append({
                        'start': func_start,
                        'end': func_end,
                        'size': size,
                        'stores': stores,
                        'bls': bls,
                        'lp_vals': lp_vals,
                        'has_sb2': has_sb2,
                        'has_glp': has_glp,
                    })

    print(f"\nFound {len(candidates)} functions referencing gLocalLinkPlayer:")
    for c in sorted(candidates, key=lambda x: x['start']):
        addr = c['start'] + ROM_BASE
        sb2_flag = " [gSaveBlock2Ptr!]" if c['has_sb2'] else ""
        glp_flag = " [gLinkPlayers]" if c['has_glp'] else ""
        print(f"  0x{addr:08X} ({c['size']}b, {c['stores']} stores, {len(c['bls'])} BLs){sb2_flag}{glp_flag}")

    # =========================================================================
    # STEP 3: Disassemble ALL candidates (they should be few)
    # =========================================================================
    print("\n" + "=" * 80)
    print("STEP 3: Disassembly of ALL candidates")
    print("=" * 80)

    # Sort: has_sb2 first (InitLocalLinkPlayer reads SaveBlock2), then by stores
    candidates.sort(key=lambda x: (-int(x['has_sb2']), -x['stores']))

    for c in candidates:
        addr = c['start'] + ROM_BASE
        sb2_flag = " [HAS gSaveBlock2Ptr]" if c['has_sb2'] else ""
        glp_flag = " [HAS gLinkPlayers]" if c['has_glp'] else ""
        print(f"\n--- Function at 0x{addr:08X} ({c['size']} bytes, {c['stores']} stores){sb2_flag}{glp_flag} ---")
        print(f"  LP values: {', '.join(f'0x{v:08X}' for v in sorted(set(c['lp_vals'].values())))}")
        print(f"  BL targets: {', '.join(f'0x{t:08X}' for _, t in c['bls'])}")

        lines = disassemble_thumb(rom, c['start'], c['end'])
        for line in lines:
            print(line)

    # =========================================================================
    # STEP 4: Analyze the copy function at 0x0800AA4C more deeply
    # =========================================================================
    print("\n" + "=" * 80)
    print("STEP 4: Deep analysis of copy function at 0x0800AA4C")
    print("=" * 80)

    # This function: called with arg in R0, stores to IWRAM vars,
    # calls GetMultiplayerId, then copies gLinkPlayers ↔ gLocalLinkPlayer
    # The function that INITIALIZES gLocalLinkPlayer is the one we want.
    # It should call StringCopy and read from SaveBlock2.

    # Let's also find who CALLS the gLocalLinkPlayer-writing functions
    # by scanning for BL targets matching our candidate addresses
    print("\nSearching for callers of candidate functions...")

    for c in candidates:
        func_addr = c['start'] + ROM_BASE + 1  # THUMB bit
        func_addr_even = c['start'] + ROM_BASE
        callers = []
        # Scan ROM for BL to this function
        for off in range(0, min(len(rom) - 4, 0x1000000), 2):
            target = decode_bl(rom, off)
            if target is not None and (target == func_addr or target == func_addr_even):
                caller_start = find_function_start(rom, off)
                if caller_start:
                    callers.append((off, caller_start))
        print(f"\n  Function 0x{func_addr_even:08X} is called by {len(callers)} sites:")
        for call_off, caller_start in callers[:10]:
            print(f"    BL at 0x{call_off + ROM_BASE:08X}, in function 0x{caller_start + ROM_BASE:08X}")

    # =========================================================================
    # STEP 5: Look for InitLocalLinkPlayer pattern more broadly
    # =========================================================================
    print("\n" + "=" * 80)
    print("STEP 5: Search for functions with gSaveBlock2Ptr that write to gLocalLinkPlayer-range")
    print("=" * 80)

    # gLocalLinkPlayer is at 0x02022D74, struct is 28 bytes (0x1C)
    # So the struct spans 0x02022D74 - 0x02022D8F
    # InitLocalLinkPlayer may not have 0x02022D74 in its LP directly —
    # it might receive the address as a parameter or compute it.
    # Let's check: in vanilla pokeemerald, InitLocalLinkPlayer stores to gLocalLinkPlayer
    # which is a file-scope static. The compiler would put &gLocalLinkPlayer in the LP.

    # But wait — maybe the function's LP stores are to a DIFFERENT gLocalLinkPlayer address?
    # Let's check all 13 gSaveBlock2Ptr LP refs and see what other EWRAM addresses are nearby
    print("\nAll functions with gSaveBlock2Ptr:")
    sb2_lp_refs = []
    for off in range(0, min(len(rom) - 4, 0x2000000), 4):
        val = read32(rom, off)
        if val == SAVE_BLOCK2_PTR:
            sb2_lp_refs.append(off)

    sb2_seen = set()
    sb2_funcs = []
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
                if func_start and func_start not in sb2_seen:
                    sb2_seen.add(func_start)
                    func_end = find_function_end(rom, func_start, 0x300)
                    size = func_end - func_start
                    stores = count_stores(rom, func_start, func_end)
                    bls = get_bl_targets(rom, func_start, func_end)
                    lp_vals = get_literal_pool_values(rom, func_start, func_end)
                    sb2_funcs.append({
                        'start': func_start,
                        'end': func_end,
                        'size': size,
                        'stores': stores,
                        'bls': bls,
                        'lp_vals': lp_vals,
                    })

    sb2_funcs.sort(key=lambda x: x['start'])
    print(f"Found {len(sb2_funcs)} functions with gSaveBlock2Ptr in LP:")
    for c in sb2_funcs:
        addr = c['start'] + ROM_BASE
        lp_str = ', '.join(f'0x{v:08X}' for v in sorted(set(c['lp_vals'].values())))
        print(f"\n  0x{addr:08X} ({c['size']}b, {c['stores']} stores, {len(c['bls'])} BLs)")
        print(f"    LP: {lp_str}")
        # Disassemble short ones
        if c['size'] <= 200:
            lines = disassemble_thumb(rom, c['start'], c['end'])
            for line in lines:
                print(line)

    # =========================================================================
    # STEP 6: Check the exact struct at 0x02022D74
    # =========================================================================
    print("\n" + "=" * 80)
    print("STEP 6: LinkPlayerInfo struct layout")
    print("=" * 80)

    # In pokeemerald, struct LinkPlayer is:
    # u16 version;      // +0x00
    # u16 lp_field_2;   // +0x02 (neverRead)
    # u32 trainerId;    // +0x04
    # u8 name[PLAYER_NAME_LENGTH + 1]; // +0x08 (8 bytes in expansion)
    # u8 gender;        // +0x10
    # u8 linkType;      // +0x11
    # u8 language;      // +0x12
    # u8 progressFlags; // +0x13 (or badge count in some versions)
    # u16 neverRead5;   // +0x14
    # u16 progressFlagsCopy; // +0x16
    # u8 name_Pokemon[8]; // +0x18
    # Total: 0x1C (28) bytes? Actually varies by expansion.

    # In pokeemerald-expansion (RHH):
    # sizeof(struct LinkPlayer) = 28 bytes (0x1C)
    # This matches the +0x1C stride in the copy function at 0x0800AA4C

    print("struct LinkPlayer (from pokeemerald-expansion):")
    print("  +0x00: u16 version")
    print("  +0x02: u16 lp_field_2")
    print("  +0x04: u32 trainerId")
    print("  +0x08: u8 name[8]  (PLAYER_NAME_LENGTH + 1)")
    print("  +0x10: u8 gender")
    print("  +0x11: u8 linkType")
    print("  +0x12: u8 language")
    print("  +0x13: u8 progressFlags")
    print("  +0x14-0x1B: padding/extra")
    print("  Total: 0x1C (28) bytes")

    print(f"\ngLocalLinkPlayer = 0x{G_LOCAL_LINK_PLAYER:08X}")
    print(f"  .version  = 0x{G_LOCAL_LINK_PLAYER + 0:08X}")
    print(f"  .trainerId = 0x{G_LOCAL_LINK_PLAYER + 4:08X}")
    print(f"  .name     = 0x{G_LOCAL_LINK_PLAYER + 8:08X}")
    print(f"  .gender   = 0x{G_LOCAL_LINK_PLAYER + 0x10:08X}")
    print(f"  .language = 0x{G_LOCAL_LINK_PLAYER + 0x12:08X}")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    print(f"gLocalLinkPlayer = 0x{G_LOCAL_LINK_PLAYER:08X} (28 bytes)")
    print(f"gLinkPlayers = 0x{G_LINK_PLAYERS:08X} (4 * 28 = 112 bytes)")
    print(f"Copy function (SendLocalLinkPlayer?) = 0x0800AA4C")

    # Best InitLocalLinkPlayer candidate = function with gSaveBlock2Ptr + stores to gLocalLinkPlayer
    best = None
    for c in candidates:
        if c['has_sb2']:
            best = c
            break

    if best:
        addr = best['start'] + ROM_BASE
        print(f"\nBest InitLocalLinkPlayer candidate: 0x{addr:08X} (0x{addr|1:08X} THUMB)")
        print(f"  Size: {best['size']} bytes, Stores: {best['stores']}")
    else:
        print("\nNo function with BOTH gSaveBlock2Ptr and gLocalLinkPlayer found directly.")
        print("InitLocalLinkPlayer may receive gLocalLinkPlayer as a parameter.")
        print("Check callers of the copy function or check gSaveBlock2Ptr functions above.")

        # If none has both, the best candidate is the one with most stores
        if candidates:
            best2 = max(candidates, key=lambda x: x['stores'])
            addr = best2['start'] + ROM_BASE
            print(f"\nAlternative: function with most stores: 0x{addr:08X} ({best2['stores']} stores)")

if __name__ == "__main__":
    main()
