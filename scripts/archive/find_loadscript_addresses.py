#!/usr/bin/env python3
"""
Find all ROM/RAM addresses needed for Loadscript(37) — GBA-PK style battle entry.
Scans Pokemon Run & Bun ROM using known addresses as anchors.

Targets:
  1A. CreateTask
  1B. Task_StartWiredCableClubBattle
  1C. InitLocalLinkPlayer
  1D. gSpecialVar_8000
  1E. gScriptLoad (sScriptContext1)
  1F. Safe cart0 areas (gScriptData / gNativeData)
  1G. CB2_ReturnToField, gSendBuffer, sBlockSend, gLinkCallback
"""

import struct, os, sys, time

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

# ========== Known R&B addresses ==========
KNOWN = {
    'SetUpBattleVars':       0x0806F1D9,
    'CB2_InitBattle':        0x080363C1,
    'CB2_HandleStartBattle': 0x08037B45,
    'SetMainCallback2':      0x08000544,
    'GetMultiplayerId':      0x0800A4B1,
    'IsLinkTaskFinished':    0x0800A569,
    'BattleMainCB2':         0x0803816D,
    'CB2_Overworld':         0x080A89A5,
    'gLinkPlayers':          0x020229E8,
    'gBattleTypeFlags':      0x02023364,
    'gBlockRecvBuffer':      0x020226C4,
    'gBlockReceivedStatus':  0x0300307C,
    'gReceivedRemoteLinkPlayers': 0x03003124,
    'gWirelessCommType':     0x030030FC,
    'gBattleMainFunc':       0x03005D04,
    'gMainAddr':             0x030022C0,
    'gPlayerParty':          0x02023A98,
}

# Vanilla BPEE reference (for addresses that may be identical in R&B)
VANILLA = {
    'CreateTask':          0x080A8FB0,
    'Task_StartWiredCableClubBattle': 0x080B32B4,
    'InitLocalLinkPlayer': 0x08009638,
    'gSpecialVar_8000':    0x020375D8,
    'gScriptLoad':         0x03000E38,
    'CB2_ReturnToField':   0x080860C8,
    'gSendBuffer':         0x020228C4,
    'sBlockSend':          0x03000D10,
    'gLinkCallback':       0x03003140,
    'CB2_WhiteOut':        0x08085F58,
}

# ========== Utility ==========

def ru16(d, o):
    if o < 0 or o + 2 > len(d): return None
    return struct.unpack_from('<H', d, o)[0]

def ru32(d, o):
    if o < 0 or o + 4 > len(d): return None
    return struct.unpack_from('<I', d, o)[0]

def is_bl(h, l):
    return h is not None and l is not None and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800

def decode_bl(h, l, pc4):
    """Decode THUMB BL. pc4 = address_of_first_halfword + 4."""
    full = ((h & 0x7FF) << 12) | ((l & 0x7FF) << 1)
    if full >= 0x400000: full -= 0x800000
    return pc4 + full

def to_file(rom_addr):
    return (rom_addr & ~1) - 0x08000000

def to_rom(file_off):
    return 0x08000001 + file_off  # THUMB bit

def find_push_lr(d, pos, max_back=4096):
    for p in range(pos, max(0, pos - max_back), -2):
        hw = ru16(d, p)
        if hw is not None and (hw & 0xFF00) == 0xB500:
            return p
    return None

def get_bl_targets(d, func_off, max_bytes=1024):
    results = []
    pos = func_off
    end = min(func_off + max_bytes, len(d) - 4)
    while pos < end:
        h, l = ru16(d, pos), ru16(d, pos + 2)
        if is_bl(h, l):
            pc4 = 0x08000000 + pos + 4
            results.append((pos - func_off, decode_bl(h, l, pc4)))
            pos += 4
        else:
            pos += 2
    return results

def get_literal_values(d, func_off, max_bytes=1024):
    results = []
    for pos in range(func_off, min(func_off + max_bytes, len(d) - 2), 2):
        hw = ru16(d, pos)
        if hw is not None and (hw >> 11) == 0x09:
            imm8 = hw & 0xFF
            pc = ((pos + 4) & ~2)
            val = ru32(d, pc + imm8 * 4)
            if val is not None:
                results.append((pos - func_off, val))
    return results

# ========== MAIN ==========

def main():
    if not os.path.exists(ROM_PATH):
        print(f"ERROR: ROM not found: {ROM_PATH}")
        sys.exit(1)

    with open(ROM_PATH, 'rb') as f:
        rom = f.read()

    rom_size = len(rom)
    print(f"ROM: {rom_size} bytes ({rom_size/1048576:.1f} MB)")

    # Build literal pool index: value → [file_offset, ...]
    t0 = time.time()
    print("Building literal pool index...", end=" ", flush=True)
    lp_index = {}
    for pos in range(0, rom_size - 2, 2):
        hw = ru16(rom, pos)
        if (hw >> 11) == 0x09:
            imm8 = hw & 0xFF
            pc = ((pos + 4) & ~2)
            val = ru32(rom, pc + imm8 * 4)
            if val is not None:
                lp_index.setdefault(val, []).append(pos)
    print(f"done ({len(lp_index)} values, {time.time()-t0:.1f}s)")

    # Build BL caller index: aligned_target → [caller_file_offset, ...]
    t1 = time.time()
    print("Building BL caller index...", end=" ", flush=True)
    bl_index = {}
    pos = 0
    while pos < rom_size - 4:
        h, l = ru16(rom, pos), ru16(rom, pos + 2)
        if is_bl(h, l):
            pc4 = 0x08000000 + pos + 4
            target = decode_bl(h, l, pc4) & ~1
            bl_index.setdefault(target, []).append(pos)
            pos += 4
        else:
            pos += 2
    print(f"done ({len(bl_index)} targets, {time.time()-t1:.1f}s)")

    def lp_refs(val):
        return len(lp_index.get(val, []))

    def bl_callers(rom_addr):
        return len(bl_index.get(rom_addr & ~1, []))

    results = {}

    # ==========================================
    # 1A. CreateTask — BL from SetUpBattleVars with most callers
    # ==========================================
    print("\n" + "="*60)
    print("1A. CreateTask")
    print("="*60)

    sub_off = to_file(KNOWN['SetUpBattleVars'])
    bls = get_bl_targets(rom, sub_off, 300)
    print(f"SetUpBattleVars BLs (first 300 bytes):")

    best, best_n = None, 0
    for rel, target in bls:
        n = bl_callers(target)
        print(f"  +0x{rel:03X}: BL 0x{target:08X} ({n} callers)")
        if n > best_n:
            best_n = n
            best = target

    if best and best_n > 50:
        results['CreateTask'] = best
        print(f"  => CreateTask = 0x{best:08X} ({best_n} callers)")
    else:
        print(f"  => NOT FOUND (best had {best_n} callers)")

    # ==========================================
    # 1B. Task_StartWiredCableClubBattle
    # ==========================================
    print("\n" + "="*60)
    print("1B. Task_StartWiredCableClubBattle")
    print("="*60)

    # Functions with CB2_InitBattle in literal pool
    cb2_funcs = set()
    for p in lp_index.get(KNOWN['CB2_InitBattle'], []):
        f = find_push_lr(rom, p)
        if f is not None: cb2_funcs.add(f)

    # Functions with IsLinkTaskFinished in literal pool (try both aligned and +1)
    ilf_funcs = set()
    for addr in [KNOWN['IsLinkTaskFinished'], KNOWN['IsLinkTaskFinished'] & ~1]:
        for p in lp_index.get(addr, []):
            f = find_push_lr(rom, p)
            if f is not None: ilf_funcs.add(f)

    candidates = cb2_funcs & ilf_funcs
    print(f"CB2_InitBattle literal refs: {len(cb2_funcs)} funcs")
    print(f"IsLinkTaskFinished literal refs: {len(ilf_funcs)} funcs")
    print(f"Intersection: {len(candidates)} funcs")

    task_swcb = None
    for func_off in sorted(candidates):
        func_rom = to_rom(func_off)
        # Must also call SetMainCallback2 via BL
        func_bls = get_bl_targets(rom, func_off, 200)
        has_smc2 = any((t & ~1) == (KNOWN['SetMainCallback2'] & ~1) for _, t in func_bls)
        # Function size (find POP PC)
        func_size = 0
        for p in range(func_off, min(func_off + 200, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xBD00:
                func_size = p - func_off + 2
                break
        print(f"  0x{func_rom:08X} size={func_size} SetMainCallback2={has_smc2}")
        if has_smc2 and 20 <= func_size <= 200:
            task_swcb = func_rom
            break

    if task_swcb:
        results['Task_StartWiredCableClubBattle'] = task_swcb
        print(f"  => Task_StartWiredCableClubBattle = 0x{task_swcb:08X}")
    else:
        print(f"  => NOT FOUND")

    # ==========================================
    # 1C. InitLocalLinkPlayer
    # ==========================================
    print("\n" + "="*60)
    print("1C. InitLocalLinkPlayer")
    print("="*60)

    # Find callers of GetMultiplayerId that also reference gLinkPlayers
    gmid_aligned = KNOWN['GetMultiplayerId'] & ~1
    gmid_callers = bl_index.get(gmid_aligned, [])
    print(f"GetMultiplayerId callers: {len(gmid_callers)}")

    init_llp = None
    best_score = 0
    for caller_pos in gmid_callers:
        func = find_push_lr(rom, caller_pos)
        if func is None: continue
        func_lits = get_literal_values(rom, func, 300)
        has_lp = any(v == KNOWN['gLinkPlayers'] for _, v in func_lits)
        if not has_lp: continue
        # Count STRB/STRH (writing to struct)
        str_count = 0
        for p in range(func, min(func + 300, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw >> 11) in (0x0E, 0x10):  # STRB/STRH
                str_count += 1
        func_rom = to_rom(func)
        print(f"  Candidate: 0x{func_rom:08X} ({str_count} stores)")
        if str_count > best_score:
            best_score = str_count
            init_llp = func_rom

    if init_llp:
        results['InitLocalLinkPlayer'] = init_llp
        print(f"  => InitLocalLinkPlayer = 0x{init_llp:08X} ({best_score} stores)")
    else:
        print(f"  => NOT FOUND")

    # ==========================================
    # 1D. gSpecialVar_8000
    # ==========================================
    print("\n" + "="*60)
    print("1D. gSpecialVar_8000")
    print("="*60)

    # Scan CB2_HandleStartBattle literal pool for consecutive EWRAM u16 vars
    hsb_off = to_file(KNOWN['CB2_HandleStartBattle'])
    hsb_lits = get_literal_values(rom, hsb_off, 2000)
    ewram_lits = sorted(set(v for _, v in hsb_lits if 0x02030000 <= v <= 0x0203FFFF))
    print(f"CB2_HandleStartBattle EWRAM literals: {len(ewram_lits)}")

    # Find consecutive sequences of EWRAM addresses spaced 2 bytes apart
    spec_var = None
    for v in ewram_lits:
        # Check if v is part of a consecutive u16 sequence
        start = v
        while (start - 2) in ewram_lits or lp_refs(start - 2) > 0:
            start -= 2
            if start < 0x02000000: break
        end = v
        while (end + 2) in ewram_lits or lp_refs(end + 2) > 0:
            end += 2
            if end > 0x0203FFFF: break
        seq_len = (end - start) // 2 + 1
        if seq_len >= 5:
            print(f"  Consecutive seq: 0x{start:08X}..0x{end:08X} ({seq_len} vars)")
            spec_var = start
            break

    # Fallback: check vanilla address
    if not spec_var:
        van = VANILLA['gSpecialVar_8000']
        refs = lp_refs(van)
        print(f"  Vanilla 0x{van:08X}: {refs} refs")
        if refs >= 3:
            spec_var = van
        else:
            # Search nearby vanilla
            for delta in range(-0x2000, 0x2001, 2):
                test = van + delta
                if lp_refs(test) >= 10 and lp_refs(test + 2) >= 3 and lp_refs(test + 4) >= 3:
                    spec_var = test
                    print(f"  Found near vanilla: 0x{test:08X} ({lp_refs(test)} refs)")
                    break

    if spec_var:
        results['gSpecialVar_8000'] = spec_var
        print(f"  => gSpecialVar_8000 = 0x{spec_var:08X}")
    else:
        print(f"  => NOT FOUND")

    # ==========================================
    # 1E. gScriptLoad
    # ==========================================
    print("\n" + "="*60)
    print("1E. gScriptLoad")
    print("="*60)

    # Try vanilla address first (many IWRAM vars are identical)
    script_load = None
    van_sl = VANILLA['gScriptLoad']
    refs = lp_refs(van_sl)
    print(f"Vanilla gScriptLoad 0x{van_sl:08X}: {refs} refs in R&B ROM")
    if refs >= 3:
        script_load = van_sl
    else:
        # Search nearby IWRAM addresses
        print("  Searching nearby IWRAM addresses...")
        for delta in range(-0x400, 0x401, 4):
            test = van_sl + delta
            if 0x03000000 <= test <= 0x03007FFF:
                r = lp_refs(test)
                if r >= 5:
                    print(f"  Candidate: 0x{test:08X} ({r} refs)")
                    if not script_load or r > lp_refs(script_load):
                        script_load = test

    if script_load:
        results['gScriptLoad'] = script_load
        print(f"  => gScriptLoad = 0x{script_load:08X}")
    else:
        print(f"  => NOT FOUND")

    # ==========================================
    # 1F. Safe cart0 areas
    # ==========================================
    print("\n" + "="*60)
    print("1F. Safe cart0 areas")
    print("="*60)

    # Find last non-padding byte
    data_end = rom_size
    while data_end > 0 and rom[data_end - 1] in (0x00, 0xFF):
        data_end -= 1

    safe_start = ((data_end + 0xFFFF) // 0x10000) * 0x10000
    print(f"ROM data ends at: 0x{data_end:X}")
    print(f"Safe area starts: 0x{safe_start:X} (file) = 0x{0x08000000 + safe_start:08X} (ROM)")

    if safe_start + 0x20000 <= rom_size:
        results['gScriptData'] = 0x08000000 + safe_start
        results['gNativeData'] = 0x08000000 + safe_start + 0x10000
        print(f"  => gScriptData = 0x{results['gScriptData']:08X}")
        print(f"  => gNativeData = 0x{results['gNativeData']:08X}")
    elif safe_start + 0x20000 <= 0x02000000:  # Within 32MB address space
        results['gScriptData'] = 0x08000000 + safe_start
        results['gNativeData'] = 0x08000000 + safe_start + 0x10000
        print(f"  => gScriptData = 0x{results['gScriptData']:08X} (past ROM file, mGBA maps as RAM)")
        print(f"  => gNativeData = 0x{results['gNativeData']:08X}")
    else:
        print(f"  => NOT ENOUGH SPACE")

    # ==========================================
    # 1G. CB2_ReturnToField
    # ==========================================
    print("\n" + "="*60)
    print("1G. CB2_ReturnToField")
    print("="*60)

    # CB2_ReturnToField is a small function that calls SetMainCallback2.
    # It's referenced by CB2_EndLinkBattle and SetBattleEndCallbacks.
    # Search for it via: literal pool value referenced by battle end functions,
    # pointing to a small function that calls SetMainCallback2.

    # Approach: Find functions that have CB2_Overworld in literal pool AND call SetMainCallback2
    # CB2_ReturnToField itself doesn't reference CB2_Overworld directly,
    # but it calls SetMainCallback2(CB2_ReturnToFieldLocal) which eventually calls CB2_Overworld.
    #
    # Better: CB2_ReturnToField is in the literal pool of battle end functions.
    # The battle end code writes it to gMain.savedCallback.
    # We can find it by: searching for ROM function pointers in literal pools of
    # functions near CB2_HandleStartBattle.

    cb2_rtf = None
    # Try vanilla address first
    van_rtf = VANILLA['CB2_ReturnToField']
    van_rtf_file = to_file(van_rtf)
    refs = lp_refs(van_rtf)
    refs_even = lp_refs(van_rtf & ~1)
    print(f"Vanilla CB2_ReturnToField 0x{van_rtf:08X}: {refs}/{refs_even} refs")

    # Search: functions whose literal pool is referenced by battle-related code
    # CB2_ReturnToField calls SetMainCallback2 as its first action
    # It's a 2-instruction function: LDR R0, [=CB2_ReturnToFieldLocal]; B SetMainCallback2
    # Or: PUSH LR; BL SetMainCallback2; POP PC with LDR for argument

    smc2_aligned = KNOWN['SetMainCallback2'] & ~1
    smc2_callers = bl_index.get(smc2_aligned, [])
    print(f"SetMainCallback2 has {len(smc2_callers)} callers")

    # CB2_ReturnToField should be near the battle functions in ROM address space
    # It's around 0x08085000-0x08090000 in vanilla
    # In R&B, battle functions are around 0x08030000-0x08070000, so ReturnToField
    # might be around 0x08080000-0x080B0000

    # Find small functions (< 30 bytes) that call SetMainCallback2 and are referenced
    # as literal pool values by other functions
    rtf_candidates = []
    for caller_off in smc2_callers:
        func = find_push_lr(rom, caller_off)
        if func is None: continue
        # Check size
        func_size = 0
        for p in range(func, min(func + 40, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xBD00:
                func_size = p - func + 2
                break
        if func_size == 0 or func_size > 30: continue
        func_rom = to_rom(func)
        # Check if this function pointer is referenced in literal pools
        refs_odd = lp_refs(func_rom)
        refs_even = lp_refs(func_rom & ~1)
        total_refs = refs_odd + refs_even
        if total_refs >= 2:
            rtf_candidates.append((func_rom, func_size, total_refs))

    rtf_candidates.sort(key=lambda x: -x[2])
    print(f"Small SetMainCallback2 callers with LP refs: {len(rtf_candidates)}")
    for rom_addr, size, refs in rtf_candidates[:10]:
        # Check what this function loads from literal pool (its argument to SetMainCallback2)
        func_lits = get_literal_values(rom, to_file(rom_addr), size + 20)
        rom_lits = [v for _, v in func_lits if 0x08000000 <= v <= 0x09FFFFFF]
        print(f"  0x{rom_addr:08X} size={size} refs={refs} lits={[f'0x{v:08X}' for v in rom_lits]}")

    # Pick the one in the right ROM range (near battle functions)
    for rom_addr, size, refs in rtf_candidates:
        file_off = to_file(rom_addr)
        if 0x050000 <= file_off <= 0x0C0000:  # Reasonable range for battle-adjacent code
            cb2_rtf = rom_addr
            break

    if cb2_rtf:
        results['CB2_ReturnToField'] = cb2_rtf
        print(f"  => CB2_ReturnToField = 0x{cb2_rtf:08X}")
    else:
        print(f"  => NOT FOUND")

    # ==========================================
    # 1G. gSendBuffer
    # ==========================================
    print("\n" + "="*60)
    print("1G. gSendBuffer")
    print("="*60)

    # In vanilla: gSendBuffer = 0x020228C4 (EWRAM)
    # gBlockRecvBuffer (R&B) = 0x020226C4
    # In vanilla: gBlockRecvBuffer = 0x020223C4, gSendBuffer = 0x020228C4
    # Offset from gBlockRecvBuffer: vanilla diff = 0x500
    # Try R&B: gBlockRecvBuffer + 0x500 = 0x020226C4 + 0x500 = 0x02022BC4

    send_buf = None
    # Try vanilla address
    van_sb = VANILLA['gSendBuffer']
    refs = lp_refs(van_sb)
    print(f"Vanilla gSendBuffer 0x{van_sb:08X}: {refs} refs")
    if refs >= 3:
        send_buf = van_sb

    if not send_buf:
        # Try offset from gBlockRecvBuffer
        estimate = KNOWN['gBlockRecvBuffer'] + 0x500
        refs = lp_refs(estimate)
        print(f"Estimated 0x{estimate:08X}: {refs} refs")
        if refs >= 3:
            send_buf = estimate

    if not send_buf:
        # Search EWRAM range near gBlockRecvBuffer for heavily-referenced address
        print("  Searching EWRAM near gBlockRecvBuffer...")
        best_addr, best_refs = None, 0
        for delta in range(0x200, 0x800, 4):
            test = KNOWN['gBlockRecvBuffer'] + delta
            r = lp_refs(test)
            if r > best_refs:
                best_refs = r
                best_addr = test
        if best_addr and best_refs >= 5:
            send_buf = best_addr
            print(f"  Best: 0x{best_addr:08X} ({best_refs} refs)")

    if send_buf:
        results['gSendBuffer'] = send_buf
        print(f"  => gSendBuffer = 0x{send_buf:08X}")
    else:
        print(f"  => NOT FOUND")

    # ==========================================
    # 1G. sBlockSend
    # ==========================================
    print("\n" + "="*60)
    print("1G. sBlockSend")
    print("="*60)

    sblock = None
    van_sbs = VANILLA['sBlockSend']
    refs = lp_refs(van_sbs)
    print(f"Vanilla sBlockSend 0x{van_sbs:08X}: {refs} refs")
    if refs >= 2:
        sblock = van_sbs
    else:
        print("  Searching nearby IWRAM...")
        for delta in range(-0x200, 0x201, 4):
            test = van_sbs + delta
            if 0x03000000 <= test <= 0x03007FFF:
                r = lp_refs(test)
                if r >= 3:
                    print(f"  Candidate: 0x{test:08X} ({r} refs)")
                    if not sblock or r > lp_refs(sblock):
                        sblock = test

    if sblock:
        results['sBlockSend'] = sblock
        print(f"  => sBlockSend = 0x{sblock:08X}")
    else:
        print(f"  => NOT FOUND")

    # ==========================================
    # 1G. gLinkCallback
    # ==========================================
    print("\n" + "="*60)
    print("1G. gLinkCallback")
    print("="*60)

    link_cb = None
    van_lc = VANILLA['gLinkCallback']
    refs = lp_refs(van_lc)
    print(f"Vanilla gLinkCallback 0x{van_lc:08X}: {refs} refs")
    if refs >= 2:
        link_cb = van_lc
    else:
        print("  Searching nearby IWRAM...")
        for delta in range(-0x200, 0x201, 4):
            test = van_lc + delta
            if 0x03000000 <= test <= 0x03007FFF:
                r = lp_refs(test)
                if r >= 3:
                    print(f"  Candidate: 0x{test:08X} ({r} refs)")
                    if not link_cb or r > lp_refs(link_cb):
                        link_cb = test

    if link_cb:
        results['gLinkCallback'] = link_cb
        print(f"  => gLinkCallback = 0x{link_cb:08X}")
    else:
        print(f"  => NOT FOUND")

    # ==========================================
    # SUMMARY
    # ==========================================
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    targets = [
        'CreateTask', 'Task_StartWiredCableClubBattle', 'InitLocalLinkPlayer',
        'gSpecialVar_8000', 'gScriptLoad', 'gScriptData', 'gNativeData',
        'CB2_ReturnToField', 'gSendBuffer', 'sBlockSend', 'gLinkCallback'
    ]

    found = 0
    missing = []
    for name in targets:
        val = results.get(name)
        if val:
            print(f"  {name:40s} = 0x{val:08X}")
            found += 1
        else:
            print(f"  {name:40s} = *** MISSING ***")
            missing.append(name)

    print(f"\nFound: {found}/{len(targets)}")
    if missing:
        print(f"Missing: {', '.join(missing)}")
        print("\n*** GATE FAILED: Cannot proceed with implementation ***")
    else:
        print("\n*** ALL ADDRESSES FOUND — Ready for implementation ***")

    # Output as Lua config snippet
    if found == len(targets):
        print("\n-- Lua config snippet for run_and_bun.lua battle_link section:")
        print("-- Script system (Loadscript 37)")
        for name in targets:
            val = results[name]
            print(f"    {name} = 0x{val:08X},")

    return results, missing

if __name__ == '__main__':
    main()
