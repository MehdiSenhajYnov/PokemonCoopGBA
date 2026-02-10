#!/usr/bin/env python3
"""
Find the 3 missing addresses for Loadscript(37):
  - Task_StartWiredCableClubBattle
  - InitLocalLinkPlayer
  - CB2_ReturnToField

Uses improved heuristics based on why the v1 scanner failed.
"""

import struct, os, sys, time

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

# Known R&B addresses
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
    'CreateTask':            0x080C1544,  # Found by v1 scanner
    'gSpecialVar_8000':      0x02036BB0,  # Found by v1 scanner
}

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

def to_file(rom_addr):
    return (rom_addr & ~1) - 0x08000000

def to_rom(file_off):
    return 0x08000001 + file_off

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

def main():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    rom_size = len(rom)
    print(f"ROM: {rom_size} bytes")

    # Build indices
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
    print(f"done ({time.time()-t0:.1f}s)")

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
    print(f"done ({time.time()-t1:.1f}s)")

    def lp_refs(val):
        return len(lp_index.get(val, []))

    results = {}

    # ================================================================
    # 1. CB2_ReturnToField
    # ================================================================
    # CB2_ReturnToField(void) { SetMainCallback2(CB2_Overworld); }
    # It has CB2_Overworld in literal pool AND BLs to SetMainCallback2.
    # Very small function (8-16 bytes).
    print("\n" + "="*60)
    print("CB2_ReturnToField")
    print("="*60)

    cb2_ow = KNOWN['CB2_Overworld']
    smc2 = KNOWN['SetMainCallback2'] & ~1

    # Find all LDR instructions that load CB2_Overworld (with or without THUMB bit)
    ow_refs = []
    for addr_variant in [cb2_ow, cb2_ow & ~1, cb2_ow | 1]:
        for ref_pos in lp_index.get(addr_variant, []):
            ow_refs.append(ref_pos)
    ow_refs = sorted(set(ow_refs))
    print(f"CB2_Overworld literal pool refs: {len(ow_refs)}")

    # For each ref, find the containing function and check if it BLs to SetMainCallback2
    cb2_rtf_candidates = []
    for ref_pos in ow_refs:
        func = find_push_lr(rom, ref_pos, max_back=64)
        if func is None:
            continue
        func_size = ref_pos - func + 20  # approximate
        if func_size > 100:
            continue  # Too far from PUSH LR

        func_bls = get_bl_targets(rom, func, min(func_size + 20, 100))
        has_smc2 = any((t & ~1) == smc2 for _, t in func_bls)
        if not has_smc2:
            continue

        # Find actual function size (POP PC)
        actual_size = 0
        for p in range(func, min(func + 80, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xBD00:
                actual_size = p - func + 2
                break

        func_rom = to_rom(func)
        # Check how many functions reference this function in their literal pool
        lp_count = lp_refs(func_rom) + lp_refs(func_rom & ~1)

        cb2_rtf_candidates.append((func_rom, actual_size, lp_count))
        print(f"  Candidate: 0x{func_rom:08X} size={actual_size} lp_refs={lp_count}")

    # Also look for B (branch) tail call pattern instead of BL
    # Pattern: LDR R0, =CB2_Overworld; B SetMainCallback2 (no PUSH/POP)
    # This is a 2-instruction function with no stack frame
    for ref_pos in ow_refs:
        # Check if next instruction is a B (unconditional branch) to SetMainCallback2 area
        # Or check if there's a BL nearby without PUSH LR
        # Actually in THUMB, tail call is done via: LDR R1, =target; BX R1
        # Or via: B <offset> but B only reaches ±2KB
        pass

    if cb2_rtf_candidates:
        # Prefer small functions with literal pool refs
        cb2_rtf_candidates.sort(key=lambda x: (-x[2], x[1]))
        best = cb2_rtf_candidates[0]
        results['CB2_ReturnToField'] = best[0]
        print(f"  => CB2_ReturnToField = 0x{best[0]:08X} (size={best[1]}, refs={best[2]})")
    else:
        # Fallback: look for CB2_ReturnToFieldContinueScriptPlayback which is similar
        # but calls CB2_Overworld differently
        print("  Direct approach failed, trying broader search...")
        # Search ALL SetMainCallback2 callers for those loading CB2_Overworld-ish args
        smc2_callers = bl_index.get(smc2, [])
        for caller_off in smc2_callers:
            func = find_push_lr(rom, caller_off, max_back=32)
            if func is None:
                continue
            dist = caller_off - func
            if dist > 20:
                continue  # Too far from function start for a simple wrapper
            func_lits = get_literal_values(rom, func, 40)
            has_ow = any(v in [cb2_ow, cb2_ow & ~1, cb2_ow | 1] for _, v in func_lits)
            if has_ow:
                func_rom = to_rom(func)
                func_size = 0
                for p in range(func, min(func + 40, rom_size - 2), 2):
                    hw = ru16(rom, p)
                    if hw is not None and (hw & 0xFF00) == 0xBD00:
                        func_size = p - func + 2
                        break
                lp_count = lp_refs(func_rom) + lp_refs(func_rom & ~1)
                print(f"  Fallback candidate: 0x{func_rom:08X} size={func_size} refs={lp_count}")
                if not results.get('CB2_ReturnToField'):
                    results['CB2_ReturnToField'] = func_rom

    # ================================================================
    # 2. Task_StartWiredCableClubBattle
    # ================================================================
    # From decomp:
    # static void Task_StartWiredCableClubBattle(u8 taskId) {
    #     if (IsLinkTaskFinished()) {
    #         gLinkPlayers[0].linkType = gSpecialVar_8005;
    #         SetMainCallback2(CB2_InitBattle);
    #         gBattleTypeFlags = BATTLE_TYPE_LINK | BATTLE_TYPE_TRAINER;
    #         gTrainerBattleOpponent_A = TRAINER_LINK_OPPONENT;
    #         DestroyTask(taskId);
    #     }
    # }
    #
    # Key signatures:
    # - BL to IsLinkTaskFinished (0x0800A568 aligned)
    # - Literal pool contains CB2_InitBattle (0x080363C1)
    # - BL to SetMainCallback2 (0x08000544)
    # - Literal pool contains gBattleTypeFlags (0x02023364)
    # - BL to CreateTask not present (it IS the task function, it calls DestroyTask)
    #
    # It's CALLED by CreateTask as argument, so it appears in literal pools of OTHER functions.
    print("\n" + "="*60)
    print("Task_StartWiredCableClubBattle")
    print("="*60)

    ilf_aligned = KNOWN['IsLinkTaskFinished'] & ~1
    cb2_init = KNOWN['CB2_InitBattle']
    btf = KNOWN['gBattleTypeFlags']

    # Step 1: Find functions that BL to IsLinkTaskFinished
    ilf_callers = bl_index.get(ilf_aligned, [])
    print(f"IsLinkTaskFinished callers (BL): {len(ilf_callers)}")

    # Step 2: Among those, find ones with CB2_InitBattle in literal pool
    task_candidates = []
    for caller_off in ilf_callers:
        func = find_push_lr(rom, caller_off, max_back=200)
        if func is None:
            continue

        func_lits = get_literal_values(rom, func, 300)
        lit_vals = set(v for _, v in func_lits)

        has_cb2 = cb2_init in lit_vals or (cb2_init & ~1) in lit_vals or (cb2_init | 1) in lit_vals
        has_btf = btf in lit_vals

        if not has_cb2:
            continue

        # Also check for BL to SetMainCallback2
        func_bls = get_bl_targets(rom, func, 300)
        has_smc2 = any((t & ~1) == smc2 for _, t in func_bls)

        func_rom = to_rom(func)
        func_size = 0
        for p in range(func, min(func + 300, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xBD00:
                func_size = p - func + 2
                break

        # Check if this function pointer appears in literal pools (= used as CreateTask arg)
        lp_count = lp_refs(func_rom) + lp_refs(func_rom & ~1)

        score = (1 if has_cb2 else 0) + (1 if has_btf else 0) + (1 if has_smc2 else 0)
        task_candidates.append((func_rom, func_size, score, has_btf, has_smc2, lp_count))
        print(f"  Candidate: 0x{func_rom:08X} size={func_size} score={score} btf={has_btf} smc2={has_smc2} lp_refs={lp_count}")

    if task_candidates:
        # Sort by score (descending), then by lp_refs
        task_candidates.sort(key=lambda x: (-x[2], -x[5], x[1]))
        best = task_candidates[0]
        results['Task_StartWiredCableClubBattle'] = best[0]
        print(f"  => Task_StartWiredCableClubBattle = 0x{best[0]:08X}")
    else:
        print("  Direct approach failed.")
        # Fallback: search for functions that have BOTH CB2_InitBattle AND gBattleTypeFlags in LP
        print("  Trying LP-only approach (CB2_InitBattle + gBattleTypeFlags)...")
        cb2_init_refs = set()
        for v in [cb2_init, cb2_init & ~1, cb2_init | 1]:
            for p in lp_index.get(v, []):
                f = find_push_lr(rom, p)
                if f is not None:
                    cb2_init_refs.add(f)

        btf_refs = set()
        for p in lp_index.get(btf, []):
            f = find_push_lr(rom, p)
            if f is not None:
                btf_refs.add(f)

        both = cb2_init_refs & btf_refs
        print(f"  CB2_InitBattle LP funcs: {len(cb2_init_refs)}")
        print(f"  gBattleTypeFlags LP funcs: {len(btf_refs)}")
        print(f"  Intersection: {len(both)}")

        for func_off in sorted(both):
            func_rom = to_rom(func_off)
            func_size = 0
            for p in range(func_off, min(func_off + 300, rom_size - 2), 2):
                hw = ru16(rom, p)
                if hw is not None and (hw & 0xFF00) == 0xBD00:
                    func_size = p - func_off + 2
                    break
            func_bls = get_bl_targets(rom, func_off, 300)
            bl_targets = [(t & ~1) for _, t in func_bls]
            has_ilf = ilf_aligned in bl_targets
            has_smc2 = smc2 in bl_targets
            lp_count = lp_refs(func_rom) + lp_refs(func_rom & ~1)
            print(f"    0x{func_rom:08X} size={func_size} ILF={has_ilf} SMC2={has_smc2} lp_refs={lp_count}")
            if has_ilf and has_smc2 and func_size <= 200 and not results.get('Task_StartWiredCableClubBattle'):
                results['Task_StartWiredCableClubBattle'] = func_rom
                print(f"    => Task_StartWiredCableClubBattle = 0x{func_rom:08X}")

    # ================================================================
    # 3. InitLocalLinkPlayer
    # ================================================================
    # From decomp:
    # void InitLocalLinkPlayer(void) {
    #     gLocalLinkPlayer.id = gSaveBlock2Ptr->playerTrainerId[0] | (sb2->playerTrainerId[1] << 8);
    #     StringCopy(gLocalLinkPlayer.name, gSaveBlock2Ptr->playerName);
    #     gLocalLinkPlayer.gender = gSaveBlock2Ptr->playerGender;
    #     ...
    # }
    # gLocalLinkPlayer = gLinkPlayers[GetMultiplayerId()]
    #
    # Key signatures:
    # - BL to GetMultiplayerId
    # - Literal pool contains gLinkPlayers (possibly shifted in R&B)
    # - BL to StringCopy
    # - Multiple STRB/STRH to struct fields
    # - References gSaveBlock2Ptr
    #
    # v1 scanner failed because gLinkPlayers address may be shifted.
    # Let's first find the actual gLinkPlayers address in R&B.
    print("\n" + "="*60)
    print("InitLocalLinkPlayer")
    print("="*60)

    gmid_aligned = KNOWN['GetMultiplayerId'] & ~1
    gmid_callers = bl_index.get(gmid_aligned, [])
    print(f"GetMultiplayerId callers: {len(gmid_callers)}")

    # First: find the actual gLinkPlayers address in R&B
    # In vanilla: 0x020229E8. Check if it has refs.
    known_glp = KNOWN['gLinkPlayers']
    glp_refs = lp_refs(known_glp)
    print(f"Known gLinkPlayers 0x{known_glp:08X}: {glp_refs} LP refs")

    # If gLinkPlayers has shifted, search nearby
    actual_glp = None
    if glp_refs >= 5:
        actual_glp = known_glp
    else:
        # Search EWRAM for heavily-referenced addresses near known gLinkPlayers
        # gSendBuffer shifted +0x300, so try same offset
        candidates_glp = []
        for delta in range(-0x1000, 0x1001, 4):
            test = known_glp + delta
            if 0x02020000 <= test <= 0x0203FFFF:
                r = lp_refs(test)
                if r >= 10:
                    candidates_glp.append((test, r))

        candidates_glp.sort(key=lambda x: -x[1])
        print(f"  gLinkPlayers candidates (>= 10 refs):")
        for addr, refs in candidates_glp[:10]:
            print(f"    0x{addr:08X}: {refs} refs")

        if candidates_glp:
            # The real gLinkPlayers should be the one that appears in functions
            # calling GetMultiplayerId
            for addr, refs in candidates_glp:
                # Check if any GetMultiplayerId callers reference this address
                for caller_off in gmid_callers[:50]:  # Check first 50
                    func = find_push_lr(rom, caller_off)
                    if func is None:
                        continue
                    func_lits = get_literal_values(rom, func, 400)
                    if any(v == addr for _, v in func_lits):
                        actual_glp = addr
                        print(f"  => gLinkPlayers confirmed: 0x{addr:08X} (found in GetMultiplayerId caller)")
                        break
                if actual_glp:
                    break

    if not actual_glp:
        print("  Could not confirm gLinkPlayers address. Trying broader search...")
        # Search ALL GetMultiplayerId callers for EWRAM addresses in their literal pools
        # that look like gLinkPlayers (0x0202xxxx range, heavily referenced)
        ewram_in_gmid_callers = {}
        for caller_off in gmid_callers:
            func = find_push_lr(rom, caller_off)
            if func is None:
                continue
            func_lits = get_literal_values(rom, func, 400)
            for _, v in func_lits:
                if 0x02022000 <= v <= 0x02024000:
                    ewram_in_gmid_callers[v] = ewram_in_gmid_callers.get(v, 0) + 1

        sorted_ewram = sorted(ewram_in_gmid_callers.items(), key=lambda x: -x[1])
        print(f"  EWRAM addresses in GetMultiplayerId caller literal pools:")
        for addr, count in sorted_ewram[:15]:
            refs = lp_refs(addr)
            print(f"    0x{addr:08X}: in {count} callers, {refs} total LP refs")

        # gLinkPlayers should appear in many GetMultiplayerId callers
        for addr, count in sorted_ewram:
            if count >= 3 and lp_refs(addr) >= 10:
                actual_glp = addr
                print(f"  => gLinkPlayers = 0x{addr:08X} (in {count} callers, {lp_refs(addr)} total refs)")
                break

    if actual_glp:
        print(f"\n  Using gLinkPlayers = 0x{actual_glp:08X}")

        # Now find InitLocalLinkPlayer: caller of GetMultiplayerId with gLinkPlayers in LP,
        # that also has many STRB/STRH (writing struct fields)
        init_candidates = []
        for caller_off in gmid_callers:
            func = find_push_lr(rom, caller_off)
            if func is None:
                continue
            func_lits = get_literal_values(rom, func, 300)
            has_glp = any(v == actual_glp for _, v in func_lits)
            if not has_glp:
                continue

            # Count store instructions
            str_count = 0
            func_size = 0
            for p in range(func, min(func + 300, rom_size - 2), 2):
                hw = ru16(rom, p)
                if hw is not None:
                    if (hw >> 11) in (0x0E, 0x10):  # STRB, STRH
                        str_count += 1
                    if (hw & 0xFF00) == 0xBD00:
                        func_size = p - func + 2
                        break

            func_rom = to_rom(func)
            # Check if function is called by other link functions
            bl_count = len(bl_index.get(func & ~1, []))  # How many places call this func

            init_candidates.append((func_rom, func_size, str_count, bl_count))
            print(f"  Candidate: 0x{func_rom:08X} size={func_size} stores={str_count} callers={bl_count}")

        if init_candidates:
            # InitLocalLinkPlayer should have many stores (writing struct fields)
            # and be relatively small (100-200 bytes)
            init_candidates.sort(key=lambda x: (-x[2], x[1]))
            for c in init_candidates:
                if 30 <= c[1] <= 300:
                    results['InitLocalLinkPlayer'] = c[0]
                    print(f"  => InitLocalLinkPlayer = 0x{c[0]:08X} (size={c[1]}, stores={c[2]})")
                    break
    else:
        print("  Cannot find gLinkPlayers — cannot find InitLocalLinkPlayer")

    # ================================================================
    # SUMMARY
    # ================================================================
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    # Include v1 results
    v1_found = {
        'CreateTask':       0x080C1544,
        'gSpecialVar_8000': 0x02036BB0,
        'gScriptLoad':      0x03000E38,
        'gScriptData':      0x096E0000,
        'gNativeData':      0x096F0000,
        'gSendBuffer':      0x02022BC4,
        'sBlockSend':       0x03000D10,
        'gLinkCallback':    0x03003140,
    }

    all_results = {**v1_found, **results}

    targets = [
        'CreateTask', 'Task_StartWiredCableClubBattle', 'InitLocalLinkPlayer',
        'gSpecialVar_8000', 'gScriptLoad', 'gScriptData', 'gNativeData',
        'CB2_ReturnToField', 'gSendBuffer', 'sBlockSend', 'gLinkCallback'
    ]

    found = 0
    missing = []
    for name in targets:
        val = all_results.get(name)
        if val:
            print(f"  {name:40s} = 0x{val:08X}")
            found += 1
        else:
            print(f"  {name:40s} = *** MISSING ***")
            missing.append(name)

    print(f"\nFound: {found}/{len(targets)}")
    if missing:
        print(f"Missing: {', '.join(missing)}")
        print("\n*** GATE FAILED ***")
    else:
        print("\n*** ALL ADDRESSES FOUND — Ready for implementation ***")
        print("\n-- Lua config snippet:")
        for name in targets:
            val = all_results[name]
            print(f"    {name} = 0x{val:08X},")

if __name__ == '__main__':
    main()
