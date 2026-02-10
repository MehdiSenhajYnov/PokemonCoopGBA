#!/usr/bin/env python3
"""
Final targeted scanner for remaining Loadscript(37) addresses.

Key insight: gSendBuffer shifted +0x300 from vanilla. gLinkPlayers probably did too.
Vanilla gLinkPlayers = 0x020229E8 → R&B estimate = 0x02022CE8.

Targets:
1. Verify gLinkPlayers address
2. Find InitLocalLinkPlayer using correct gLinkPlayers
3. Determine if CB2_ReturnToField can be skipped (use CB2_Overworld directly)
4. Determine if Task_StartWiredCableClubBattle can be replaced with custom ASM
"""

import struct, os, sys, time

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

KNOWN = {
    'SetMainCallback2':      0x08000544,
    'GetMultiplayerId':      0x0800A4B1,
    'IsLinkTaskFinished':    0x0800A569,
    'CB2_InitBattle':        0x080363C1,
    'CB2_HandleStartBattle': 0x08037B45,
    'BattleMainCB2':         0x0803816D,
    'SetUpBattleVars':       0x0806F1D9,
    'CB2_Overworld':         0x080A89A5,
    'CreateTask':            0x080C1544,
    'gBattleTypeFlags':      0x02023364,
    'gBlockRecvBuffer':      0x020226C4,
    'gSendBuffer':           0x02022BC4,  # Found by v1 (vanilla+0x300)
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

def to_file(a): return (a & ~1) - 0x08000000

def main():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    rom_size = len(rom)

    t0 = time.time()
    print("Building indices...", end=" ", flush=True)
    lp_index = {}
    for pos in range(0, rom_size - 2, 2):
        hw = ru16(rom, pos)
        if (hw >> 11) == 0x09:
            imm8 = hw & 0xFF
            pc = ((pos + 4) & ~2)
            val = ru32(rom, pc + imm8 * 4)
            if val is not None:
                lp_index.setdefault(val, []).append(pos)

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
    print(f"done ({time.time()-t0:.1f}s)")

    def lp_refs(val):
        return len(lp_index.get(val, []))

    def find_push_lr(pos, max_back=4096):
        for p in range(pos, max(0, pos - max_back), -2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xB500:
                return p
        return None

    def get_literal_values(func_off, max_bytes=400):
        results = []
        for pos in range(func_off, min(func_off + max_bytes, rom_size - 2), 2):
            hw = ru16(rom, pos)
            if hw is not None and (hw >> 11) == 0x09:
                imm8 = hw & 0xFF
                pc = ((pos + 4) & ~2)
                val = ru32(rom, pc + imm8 * 4)
                if val is not None:
                    results.append((pos - func_off, val))
        return results

    # ================================================================
    # 1. FIND gLinkPlayers
    # ================================================================
    print("\n" + "="*60)
    print("1. Finding gLinkPlayers")
    print("="*60)

    # Vanilla: 0x020229E8. gSendBuffer shift = +0x300, so try +0x300
    vanilla_glp = 0x020229E8
    estimate_glp = vanilla_glp + 0x300  # = 0x02022CE8

    print(f"Vanilla gLinkPlayers:  0x{vanilla_glp:08X} — {lp_refs(vanilla_glp)} LP refs")
    print(f"Estimated (+0x300):    0x{estimate_glp:08X} — {lp_refs(estimate_glp)} LP refs")

    # Also check nearby addresses
    best_glp = None
    best_refs = 0
    print(f"\nSearching EWRAM range 0x02022800-0x02023400:")
    for addr in range(0x02022800, 0x02023400, 4):
        refs = lp_refs(addr)
        if refs >= 15:
            # gLinkPlayers should be referenced by link-related functions
            # Filter: must be referenced by at least one GetMultiplayerId caller
            gmid_callers = bl_index.get(KNOWN['GetMultiplayerId'] & ~1, [])
            in_gmid_func = False
            for caller_off in gmid_callers[:80]:
                func = find_push_lr(caller_off)
                if func is None: continue
                func_lits = get_literal_values(func, 400)
                if any(v == addr for _, v in func_lits):
                    in_gmid_func = True
                    break
            if in_gmid_func:
                print(f"  0x{addr:08X}: {refs} LP refs (in GetMultiplayerId caller)")
                if refs > best_refs:
                    best_refs = refs
                    best_glp = addr

    # The actual gLinkPlayers should also have gLinkPlayers+28 (sizeof LinkPlayer)
    # referenced as the second player entry
    if best_glp:
        for offset in [28, 56, 84]:  # Players 1, 2, 3
            r = lp_refs(best_glp + offset)
            print(f"    gLinkPlayers+{offset}: 0x{best_glp+offset:08X} — {r} LP refs")

    # Also specifically check 0x02022CE8
    print(f"\n  Checking 0x02022CE8 specifically:")
    test = 0x02022CE8
    refs = lp_refs(test)
    print(f"    LP refs: {refs}")
    # Check if in GetMultiplayerId callers
    gmid_callers = bl_index.get(KNOWN['GetMultiplayerId'] & ~1, [])
    in_gmid = 0
    for caller_off in gmid_callers:
        func = find_push_lr(caller_off)
        if func is None: continue
        func_lits = get_literal_values(func, 400)
        if any(v == test for _, v in func_lits):
            in_gmid += 1
    print(f"    In GetMultiplayerId callers: {in_gmid}")
    for offset in [28, 56, 84]:
        r = lp_refs(test + offset)
        print(f"    +{offset} (0x{test+offset:08X}): {r} LP refs")

    # Check vanilla gLinkPlayers with various offsets
    print(f"\n  Systematic search (vanilla + offset):")
    for delta in range(0, 0x600, 4):
        test = vanilla_glp + delta
        refs = lp_refs(test)
        if refs >= 5:
            # Quick check: is test+28 also referenced?
            refs2 = lp_refs(test + 28)
            if refs2 >= 1:
                print(f"    0x{test:08X} (+0x{delta:03X}): {refs} refs, +28: {refs2} refs")

    actual_glp = best_glp if best_glp else estimate_glp
    print(f"\n  Best candidate gLinkPlayers: 0x{actual_glp:08X} ({lp_refs(actual_glp)} refs)")

    # ================================================================
    # 2. FIND InitLocalLinkPlayer
    # ================================================================
    print("\n" + "="*60)
    print("2. Finding InitLocalLinkPlayer")
    print("="*60)

    # InitLocalLinkPlayer:
    # - Calls GetMultiplayerId
    # - References gLinkPlayers (uses result as index)
    # - References gSaveBlock2Ptr (IWRAM pointer)
    # - Calls StringCopy
    # - Many STRB/STRH stores (writing struct fields)
    # - Small-medium function (100-200 bytes)
    # - Has callers (called from other functions)

    # Find gSaveBlock2Ptr - in vanilla it's at 0x03005D90 (IWRAM)
    # In R&B, IWRAM addresses often match. Check.
    vanilla_sb2ptr = 0x03005D90
    print(f"\nVanilla gSaveBlock2Ptr: 0x{vanilla_sb2ptr:08X} — {lp_refs(vanilla_sb2ptr)} LP refs")

    # gSaveBlock2Ptr is heavily referenced. Search nearby if vanilla doesn't work.
    sb2ptr = None
    if lp_refs(vanilla_sb2ptr) >= 10:
        sb2ptr = vanilla_sb2ptr
    else:
        print("  Searching IWRAM for gSaveBlock2Ptr...")
        for delta in range(-0x200, 0x201, 4):
            test = vanilla_sb2ptr + delta
            if 0x03000000 <= test <= 0x03007FFF:
                refs = lp_refs(test)
                if refs >= 50:
                    print(f"    0x{test:08X}: {refs} refs")
                    if not sb2ptr or refs > lp_refs(sb2ptr):
                        sb2ptr = test

    if sb2ptr:
        print(f"  gSaveBlock2Ptr: 0x{sb2ptr:08X} ({lp_refs(sb2ptr)} refs)")

    # Now find InitLocalLinkPlayer:
    # Must BL GetMultiplayerId AND have gLinkPlayers OR gSaveBlock2Ptr in LP
    gmid_aligned = KNOWN['GetMultiplayerId'] & ~1
    gmid_callers = bl_index.get(gmid_aligned, [])
    print(f"\nGetMultiplayerId callers: {len(gmid_callers)}")

    candidates = []
    seen_funcs = set()
    for caller_off in gmid_callers:
        func = find_push_lr(caller_off)
        if func is None or func in seen_funcs:
            continue
        seen_funcs.add(func)

        func_lits = get_literal_values(func, 400)
        lit_vals = set(v for _, v in func_lits)

        # Must have EITHER gLinkPlayers or gSaveBlock2Ptr
        has_glp = actual_glp in lit_vals
        has_sb2 = sb2ptr and sb2ptr in lit_vals

        if not (has_glp or has_sb2):
            continue

        # Count stores (STRB, STRH, STR)
        str_count = 0
        func_size = 0
        for p in range(func, min(func + 400, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None:
                op = hw >> 11
                if op in (0x0C, 0x0E, 0x10):  # STR, STRB, STRH
                    str_count += 1
                if (hw & 0xFF00) == 0xBD00:
                    func_size = p - func + 2
                    break

        func_rom = 0x08000001 + func
        bl_count = len(bl_index.get(func, []))

        # Get all BL targets
        bls = []
        p = func
        while p < min(func + func_size if func_size else func + 400, rom_size - 4):
            h, l = ru16(rom, p), ru16(rom, p + 2)
            if is_bl(h, l):
                t = decode_bl(h, l, 0x08000000 + p + 4)
                bls.append(t & ~1)
                p += 4
            else:
                p += 2

        # StringCopy is called by InitLocalLinkPlayer
        # StringCopy in vanilla: 0x08008D58-ish. In R&B: unknown.
        # We can use the number of BL targets as a proxy

        candidates.append({
            'addr': func_rom,
            'size': func_size,
            'stores': str_count,
            'callers': bl_count,
            'has_glp': has_glp,
            'has_sb2': has_sb2,
            'both': has_glp and has_sb2,
            'bl_count': len(bls),
        })

    # Sort: prefer functions with BOTH gLinkPlayers and gSaveBlock2Ptr
    # Then by store count (more stores = more likely struct init)
    candidates.sort(key=lambda c: (-c['both'], -c['stores'], c['size']))

    print(f"\nCandidates (GetMultiplayerId callers with gLinkPlayers/gSaveBlock2Ptr):")
    for c in candidates[:20]:
        flags = []
        if c['has_glp']: flags.append("gLP")
        if c['has_sb2']: flags.append("gSB2")
        print(f"  0x{c['addr']:08X} size={c['size']:3d} stores={c['stores']:2d} callers={c['callers']:2d} BLs={c['bl_count']} [{','.join(flags)}]")

    # The best candidate should have BOTH, many stores, and reasonable size
    best_ilp = None
    for c in candidates:
        if c['both'] and c['stores'] >= 3 and 30 <= c['size'] <= 300:
            best_ilp = c['addr']
            print(f"\n  => InitLocalLinkPlayer = 0x{best_ilp:08X} (size={c['size']}, stores={c['stores']}, callers={c['callers']})")
            break

    if not best_ilp:
        # Try with just gSaveBlock2Ptr
        for c in candidates:
            if c['has_sb2'] and c['stores'] >= 4 and 30 <= c['size'] <= 300:
                best_ilp = c['addr']
                print(f"\n  => InitLocalLinkPlayer = 0x{best_ilp:08X} (size={c['size']}, stores={c['stores']}, only gSB2)")
                break

    if not best_ilp:
        # Try just gLinkPlayers with many stores
        for c in candidates:
            if c['stores'] >= 4 and 30 <= c['size'] <= 300:
                best_ilp = c['addr']
                print(f"\n  => InitLocalLinkPlayer = 0x{best_ilp:08X} (size={c['size']}, stores={c['stores']}, fallback)")
                break

    if not best_ilp:
        print("\n  => InitLocalLinkPlayer NOT FOUND")

    # ================================================================
    # 3. FIND DestroyTask
    # ================================================================
    print("\n" + "="*60)
    print("3. Finding DestroyTask")
    print("="*60)

    # DestroyTask is called by nearly all task functions after they complete.
    # It's the second most-called function after CreateTask.
    # CreateTask = 0x080C1544. DestroyTask should be nearby in ROM.
    ct = KNOWN['CreateTask'] & ~1
    print(f"CreateTask: 0x{ct | 1:08X}")

    # Check BL targets near CreateTask in ROM
    dt_candidates = []
    for addr in range(ct - 0x200, ct + 0x200, 2):
        callers = len(bl_index.get(addr, []))
        if callers >= 100:
            dt_candidates.append((addr, callers))

    dt_candidates.sort(key=lambda x: -x[1])
    print(f"High-caller functions near CreateTask:")
    for addr, callers in dt_candidates[:5]:
        print(f"  0x{addr|1:08X}: {callers} callers")

    # DestroyTask should be the one with many callers, NOT CreateTask itself
    destroy_task = None
    for addr, callers in dt_candidates:
        if addr != ct and callers >= 200:
            destroy_task = addr | 1
            print(f"  => DestroyTask = 0x{destroy_task:08X} ({callers} callers)")
            break

    # ================================================================
    # 4. ASSESSMENT: Can we write custom ASM?
    # ================================================================
    print("\n" + "="*60)
    print("4. Assessment")
    print("="*60)

    print(f"""
FOUND ADDRESSES (from all scanners):
  CreateTask                = 0x080C1544  (896 callers)
  gSpecialVar_8000          = 0x02036BB0
  gScriptLoad               = 0x03000E38  (IWRAM, 6 refs)
  gScriptData               = 0x096E0000  (safe cart0)
  gNativeData               = 0x096F0000  (safe cart0)
  gSendBuffer               = 0x02022BC4
  sBlockSend                = 0x03000D10  (IWRAM)
  gLinkCallback             = 0x03003140  (IWRAM)
  gLinkPlayers              = 0x{actual_glp:08X} ({lp_refs(actual_glp)} refs)
  gSaveBlock2Ptr            = 0x{sb2ptr:08X} ({lp_refs(sb2ptr)} refs) (if found)
  InitLocalLinkPlayer       = 0x{best_ilp:08X} (if found)
  DestroyTask               = 0x{destroy_task:08X} (if found)

STILL MISSING:
  Task_StartWiredCableClubBattle — Likely does not exist in R&B expansion.
  CB2_ReturnToField             — Cannot find (CB2_Overworld has 0 LP refs).

PROPOSED SOLUTION:
  Replace Task_StartWiredCableClubBattle with CUSTOM ASM in scriptASM that:
  1. Calls InitLocalLinkPlayer (sets up VS screen names)
  2. Does NOT use CreateTask (we handle timing ourselves)
  3. battle.lua still sets gBattleTypeFlags and calls SetMainCallback2 directly

  Replace CB2_ReturnToField usage with CB2_Overworld (0x080A89A5) directly.
  CB2_ReturnToField just wraps SetMainCallback2(CB2_Overworld).
  Writing CB2_Overworld to savedCallback achieves the same result.
""")

    # Verify InitLocalLinkPlayer by disassembling
    if best_ilp:
        print(f"\nDisassembly of InitLocalLinkPlayer candidate 0x{best_ilp:08X}:")
        off = to_file(best_ilp)
        for i in range(0, 120, 2):
            if off + i + 2 > rom_size: break
            hw = ru16(rom, off + i)
            addr = 0x08000000 + off + i

            if off + i + 4 <= rom_size:
                h, l = hw, ru16(rom, off + i + 2)
                if is_bl(h, l):
                    target = decode_bl(h, l, addr + 4)
                    # Name known targets
                    aligned = target & ~1
                    name = ""
                    if aligned == (KNOWN['GetMultiplayerId'] & ~1): name = " ; GetMultiplayerId"
                    elif aligned == (KNOWN['SetMainCallback2'] & ~1): name = " ; SetMainCallback2"
                    print(f"  0x{addr:08X}: BL 0x{target:08X}{name}")
                    # Skip next halfword
                    continue

            if (hw >> 11) == 0x09:
                imm8 = hw & 0xFF
                rd = (hw >> 8) & 7
                pc = ((addr + 4) & ~2)
                pool_off = (pc - 0x08000000) + imm8 * 4
                val = ru32(rom, pool_off)
                name = ""
                if val == actual_glp: name = " ; gLinkPlayers"
                elif val == sb2ptr: name = " ; gSaveBlock2Ptr"
                elif val == KNOWN['gBattleTypeFlags']: name = " ; gBattleTypeFlags"
                print(f"  0x{addr:08X}: LDR R{rd}, =0x{val:08X}{name}")
            elif (hw & 0xFF00) == 0xB500:
                print(f"  0x{addr:08X}: PUSH {{LR, ...}}")
            elif (hw & 0xFF00) == 0xBD00:
                print(f"  0x{addr:08X}: POP {{PC, ...}}")
                break
            elif (hw >> 11) == 0x0E:
                print(f"  0x{addr:08X}: STRB ...")
            elif (hw >> 11) == 0x10:
                print(f"  0x{addr:08X}: STRH ...")
            elif (hw >> 11) == 0x0C:
                print(f"  0x{addr:08X}: STR ...")
            else:
                print(f"  0x{addr:08X}: 0x{hw:04X}")

if __name__ == '__main__':
    main()
