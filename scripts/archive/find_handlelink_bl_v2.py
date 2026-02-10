#!/usr/bin/env python3
"""
Find HandleLinkBattleSetup in the ROM.

Strategy:
1. HandleLinkBattleSetup is a function that:
   - Loads gBattleTypeFlags (0x02023364)
   - Tests BATTLE_TYPE_LINK (bit 1)
   - If link: checks gWirelessCommType, calls CreateTask, CreateTasksForSendRecvLinkBuffers
   - If not link: returns quickly

2. In pokeemerald-expansion source (battle_controllers.c:89-121):
   static void HandleLinkBattleSetup(void)
   {
       if (gBattleTypeFlags & BATTLE_TYPE_LINK)
       {
           if (gWirelessCommType)
               ...
           else
               ...
       }
   }

3. Search for ALL functions that reference gBattleTypeFlags in their literal pool
   and are small functions (< 120 bytes) with PUSH {lr} at start.
   Then check which ones are called from our SetUpBattleVars area.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
ROM_BASE = 0x08000000
ROM_SIZE = 32 * 1024 * 1024

GBATTLETYPEFLAGS = 0x02023364
FUNC_ADDR = 0x0806F1D8
FUNC_OFFSET = FUNC_ADDR - ROM_BASE

def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def decode_bl(hw1, hw2, addr):
    """ARMv4T THUMB BL decode"""
    if (hw1 & 0xF800) != 0xF000:
        return None
    if (hw2 & 0xF800) != 0xF800:
        return None
    offset_hi = hw1 & 0x7FF
    offset_lo = hw2 & 0x7FF
    if offset_hi & 0x400:
        offset_hi |= 0xFFFFF800
    combined = (offset_hi << 12) | (offset_lo << 1)
    target = (addr + 4 + combined) & 0xFFFFFFFF
    return target

def main():
    with open(ROM_PATH, 'rb') as f:
        rom_data = f.read()

    print(f"ROM size: {len(rom_data)} bytes")

    # Step 1: Find ALL literal pool entries that contain gBattleTypeFlags (0x02023364)
    print(f"\n{'='*80}")
    print(f"Step 1: Find all literal pool refs to gBattleTypeFlags (0x{GBATTLETYPEFLAGS:08X})")
    print(f"{'='*80}")

    btf_refs = []
    for off in range(0, min(len(rom_data) - 4, ROM_SIZE), 4):
        val = read_u32(rom_data, off)
        if val == GBATTLETYPEFLAGS:
            rom_addr = ROM_BASE + off
            btf_refs.append((off, rom_addr))

    print(f"Found {len(btf_refs)} literal pool entries with gBattleTypeFlags:")
    for off, addr in btf_refs:
        print(f"  0x{addr:08X} (file offset 0x{off:06X})")

    # Step 2: For each literal pool ref, find which LDR instructions reference it
    # LDR Rd, [PC, #imm] can reach +1020 bytes from (PC+4)&~2
    # So the LDR must be within 1020 bytes BEFORE the literal pool entry
    print(f"\n{'='*80}")
    print(f"Step 2: Find functions that load gBattleTypeFlags")
    print(f"{'='*80}")

    func_candidates = set()  # (function start address)
    ldr_hits = []

    for pool_off, pool_addr in btf_refs:
        # Search backwards up to 1020 bytes for LDR Rd, [PC, #imm]
        for delta in range(0, 1024, 2):
            ldr_off = pool_off - delta
            if ldr_off < 0:
                break
            hw = read_u16(rom_data, ldr_off)
            if (hw & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
                imm8 = hw & 0xFF
                ldr_addr = ROM_BASE + ldr_off
                pc_val = (ldr_addr + 4) & ~2
                target_pool = pc_val + imm8 * 4
                if target_pool == pool_addr:
                    rd = (hw >> 8) & 7
                    ldr_hits.append((ldr_off, ldr_addr, rd))

    print(f"Found {len(ldr_hits)} LDR instructions that load gBattleTypeFlags:")
    for off, addr, rd in ldr_hits:
        print(f"  0x{addr:08X}: LDR r{rd}, =gBattleTypeFlags")

    # Step 3: For each LDR hit, find the enclosing function (scan back for PUSH)
    # and check if it's a small function that tests BATTLE_TYPE_LINK
    print(f"\n{'='*80}")
    print(f"Step 3: Identify HandleLinkBattleSetup candidates")
    print(f"{'='*80}")

    candidates = []
    for ldr_off, ldr_addr, rd in ldr_hits:
        # Scan backwards for PUSH {lr} or PUSH {rN..., lr}
        func_start = None
        for back in range(0, 200, 2):
            check_off = ldr_off - back
            if check_off < 0:
                break
            hw = read_u16(rom_data, check_off)
            # PUSH with LR bit set
            if (hw & 0xFE00) == 0xB400 and (hw & 0x100):
                func_start = check_off
                break

        if func_start is None:
            continue

        func_addr = ROM_BASE + func_start
        func_thumb = func_addr | 1

        # Check function size (find POP {pc} or BX LR)
        func_size = 0
        for j in range(0, 200, 2):
            hw = read_u16(rom_data, func_start + j)
            if (hw & 0xFF00) == 0xBD00:  # POP {pc}
                func_size = j + 2
                break
            if hw == 0x4770:  # BX LR
                func_size = j + 2
                break

        if func_size == 0 or func_size > 150:
            continue  # Too big or no end found

        # This is a small function that loads gBattleTypeFlags
        # Check if it tests bit 1 (BATTLE_TYPE_LINK) - look for TST or AND with #1
        has_link_test = False
        for j in range(0, func_size, 2):
            hw = read_u16(rom_data, func_start + j)
            # TST Rn, Rm
            if (hw & 0xFFC0) == 0x4200:
                has_link_test = True
            # AND Rd, Rm
            if (hw & 0xFFC0) == 0x4000:
                has_link_test = True
            # LDR followed by TST/AND with immediate pattern
            # Actually just check if there's a MOV Rd, #1 near the LDR
            if (hw & 0xF800) == 0x2000 and (hw & 0xFF) == 0x01:
                has_link_test = True

        # Check if function contains BL (calls CreateTask etc)
        has_bl = False
        bl_targets = []
        for j in range(0, func_size - 2, 2):
            hw1 = read_u16(rom_data, func_start + j)
            hw2 = read_u16(rom_data, func_start + j + 2)
            target = decode_bl(hw1, hw2, func_addr + j)
            if target is not None:
                has_bl = True
                bl_targets.append(target)

        candidates.append({
            'addr': func_addr,
            'thumb': func_thumb,
            'offset': func_start,
            'size': func_size,
            'has_link_test': has_link_test,
            'has_bl': has_bl,
            'bl_targets': bl_targets,
            'ldr_dist': ldr_off - func_start,
        })

    # Sort by likelihood (small, has link test, has BL calls)
    candidates.sort(key=lambda c: (not c['has_link_test'], not c['has_bl'], c['size']))

    print(f"\nFound {len(candidates)} candidate functions:")
    for c in candidates:
        score = ""
        if c['has_link_test'] and c['has_bl']:
            score = " *** STRONG CANDIDATE ***"
        elif c['has_link_test']:
            score = " (has link test)"
        elif c['has_bl']:
            score = " (has BL calls)"

        print(f"\n  0x{c['addr']:08X} (THUMB: 0x{c['thumb']:08X}), size={c['size']} bytes{score}")
        print(f"    LDR at +0x{c['ldr_dist']:02X} from func start")
        if c['bl_targets']:
            for bt in c['bl_targets']:
                print(f"    BL -> 0x{bt:08X}")

    # Step 4: Check which of these candidates is called from SetUpBattleVars
    print(f"\n{'='*80}")
    print(f"Step 4: Check which candidate is called from SetUpBattleVars (0x{FUNC_ADDR:08X})")
    print(f"{'='*80}")

    # Read SetUpBattleVars (larger range this time, up to 600 bytes)
    read_size = 600
    func_bytes = rom_data[FUNC_OFFSET:FUNC_OFFSET + read_size]

    subv_bls = []
    for i in range(0, read_size - 4, 2):
        hw1 = read_u16(func_bytes, i)
        hw2 = read_u16(func_bytes, i + 2)
        target = decode_bl(hw1, hw2, FUNC_ADDR + i)
        if target is not None:
            subv_bls.append((i, FUNC_ADDR + i, target))

    print(f"\nAll BL instructions in SetUpBattleVars ({len(subv_bls)} total):")
    candidate_addrs = {c['thumb'] for c in candidates}
    candidate_addrs_nothumb = {c['addr'] for c in candidates}

    for offset, addr, target in subv_bls:
        match = ""
        if target in candidate_addrs or (target & ~1) in candidate_addrs_nothumb:
            match = " *** MATCHES HandleLinkBattleSetup CANDIDATE! ***"
        print(f"  +0x{offset:02X} (0x{addr:08X}): BL 0x{target:08X}{match}")

    # Step 5: Alternative approach - look for the function that:
    # 1. Is called from SetUpBattleVars
    # 2. First loads a value, tests bit 1
    # 3. If set, does more work
    # HandleLinkBattleSetup pattern: PUSH{lr}, LDR r0,[=gBattleTypeFlags], LDR r0,[r0], MOV r1,#1, TST r0,r1, BEQ <skip>
    print(f"\n{'='*80}")
    print(f"Step 5: Check ALL BL targets from SetUpBattleVars for HandleLinkBattleSetup pattern")
    print(f"{'='*80}")

    for offset, addr, target in subv_bls:
        tgt_clean = target & ~1
        tgt_off = tgt_clean - ROM_BASE
        if tgt_off < 0 or tgt_off + 80 > len(rom_data):
            continue

        # Read first 40 bytes of target
        snippet = rom_data[tgt_off:tgt_off+80]

        # Check if this function loads gBattleTypeFlags
        loads_btf = False
        for j in range(0, min(40, len(snippet)-2), 2):
            hw = read_u16(snippet, j)
            if (hw & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
                imm8 = hw & 0xFF
                pc_val = (tgt_clean + j + 4) & ~2
                pool_addr = pc_val + imm8 * 4
                pool_off = pool_addr - ROM_BASE
                if 0 <= pool_off <= len(rom_data) - 4:
                    val = read_u32(rom_data, pool_off)
                    if val == GBATTLETYPEFLAGS:
                        loads_btf = True
                        break

        if loads_btf:
            print(f"\n  *** BL at +0x{offset:02X} -> 0x{target:08X} LOADS gBattleTypeFlags! ***")
            # Disassemble first 40 bytes
            j = 0
            while j < 60:
                t_addr = tgt_clean + j
                t_hw = read_u16(rom_data, tgt_off + j)

                if j + 2 < 60:
                    t_hw2 = read_u16(rom_data, tgt_off + j + 2)
                    bl_tgt = decode_bl(t_hw, t_hw2, t_addr)
                    if bl_tgt is not None:
                        print(f"    0x{t_addr:08X}: {t_hw:04X} {t_hw2:04X}  BL 0x{bl_tgt:08X}")
                        j += 4
                        continue

                extra = ""
                if (t_hw & 0xF800) == 0x4800:
                    imm8 = t_hw & 0xFF
                    pc_val = (t_addr + 4) & ~2
                    pool_addr = pc_val + imm8 * 4
                    pool_off = pool_addr - ROM_BASE
                    if 0 <= pool_off <= len(rom_data) - 4:
                        val = read_u32(rom_data, pool_off)
                        extra = f"  ; =0x{val:08X}"

                # Simple disasm
                if (t_hw & 0xFE00) == 0xB400:
                    regs = []
                    for b in range(8):
                        if t_hw & (1 << b): regs.append(f"r{b}")
                    if t_hw & 0x100: regs.append("lr")
                    disasm = f"PUSH {{{', '.join(regs)}}}"
                elif (t_hw & 0xFF00) == 0xBD00:
                    regs = []
                    for b in range(8):
                        if t_hw & (1 << b): regs.append(f"r{b}")
                    if t_hw & 0x100: regs.append("pc")
                    disasm = f"POP {{{', '.join(regs)}}}"
                elif (t_hw & 0xF800) == 0x4800:
                    rd = (t_hw >> 8) & 7
                    imm8 = t_hw & 0xFF
                    pc_val = (t_addr + 4) & ~2
                    disasm = f"LDR r{rd}, [PC, #0x{imm8*4:X}]"
                elif (t_hw & 0xF800) == 0x6800:
                    rd = t_hw & 7; rn = (t_hw >> 3) & 7; imm = ((t_hw >> 6) & 0x1F)*4
                    disasm = f"LDR r{rd}, [r{rn}, #0x{imm:X}]"
                elif (t_hw & 0xF800) == 0x2000:
                    rd = (t_hw >> 8) & 7; imm = t_hw & 0xFF
                    disasm = f"MOV r{rd}, #0x{imm:02X}"
                elif (t_hw & 0xFFC0) == 0x4200:
                    rn = t_hw & 7; rm = (t_hw >> 3) & 7
                    disasm = f"TST r{rn}, r{rm}"
                elif (t_hw & 0xFFC0) == 0x4000:
                    rd = t_hw & 7; rm = (t_hw >> 3) & 7
                    disasm = f"AND r{rd}, r{rm}"
                elif (t_hw & 0xF000) == 0xD000:
                    cond = (t_hw >> 8) & 0xF
                    cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                                 "BHI","BLS","BGE","BLT","BGT","BLE","B","SVC"]
                    imm8 = t_hw & 0xFF
                    if imm8 & 0x80: imm8 -= 256
                    btarget = t_addr + 4 + imm8 * 2
                    disasm = f"{cond_names[cond]} 0x{btarget:08X}"
                elif t_hw == 0x4770:
                    disasm = "BX LR"
                else:
                    disasm = f"0x{t_hw:04X}"

                print(f"    0x{t_addr:08X}: {t_hw:04X}      {disasm}{extra}")

                if (t_hw & 0xFF00) == 0xBD00 or t_hw == 0x4770:
                    break
                j += 2

    # Step 6: Also look more broadly - maybe HandleLinkBattleSetup was INLINED
    # In pokeemerald-expansion, it's "static void HandleLinkBattleSetup(void)"
    # Being static, the compiler may have inlined it!
    print(f"\n{'='*80}")
    print(f"Step 6: Check if HandleLinkBattleSetup is INLINED in SetUpBattleVars")
    print(f"{'='*80}")

    # Look for loading gBattleTypeFlags within SetUpBattleVars itself
    for i in range(0, min(600, len(func_bytes) - 2), 2):
        hw = read_u16(func_bytes, i)
        if (hw & 0xF800) == 0x4800:
            imm8 = hw & 0xFF
            pc_val = (FUNC_ADDR + i + 4) & ~2
            pool_addr = pc_val + imm8 * 4
            pool_off = pool_addr - ROM_BASE
            if 0 <= pool_off <= len(rom_data) - 4:
                val = read_u32(rom_data, pool_off)
                if val == GBATTLETYPEFLAGS:
                    rd = (hw >> 8) & 7
                    print(f"  gBattleTypeFlags loaded at +0x{i:02X} (0x{FUNC_ADDR+i:08X}): LDR r{rd}, =0x{val:08X}")
                    # Show context: prev 4 and next 10 instructions
                    start = max(0, i - 8)
                    end = min(len(func_bytes) - 2, i + 20)
                    for j in range(start, end, 2):
                        hw2 = read_u16(func_bytes, j)
                        marker = " <---" if j == i else ""
                        extra2 = ""
                        if (hw2 & 0xF800) == 0x4800:
                            imm8b = hw2 & 0xFF
                            pc2 = (FUNC_ADDR + j + 4) & ~2
                            pa2 = pc2 + imm8b * 4
                            po2 = pa2 - ROM_BASE
                            if 0 <= po2 <= len(rom_data) - 4:
                                extra2 = f"  ; =0x{read_u32(rom_data, po2):08X}"
                        print(f"    +0x{j:02X}: {hw2:04X}{extra2}{marker}")

if __name__ == '__main__':
    main()
