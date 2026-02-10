#!/usr/bin/env python3
"""
Final scanner: Find InitLocalLinkPlayer using CONFIRMED gLinkPlayers = 0x02022CE8.
Also verify the address and find DestroyTask.
"""

import struct, os, sys, time

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

KNOWN = {
    'SetMainCallback2':      0x08000544,
    'GetMultiplayerId':      0x0800A4B1,
    'CB2_InitBattle':        0x080363C1,
    'CB2_Overworld':         0x080A89A5,
    'CreateTask':            0x080C1544,
    'gLinkPlayers':          0x02022CE8,   # Confirmed: vanilla+0x300, 132 LP refs
    'gSaveBlock2Ptr':        0x03005D90,   # Confirmed: 13 LP refs
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

    def get_literal_values(func_off, max_bytes=600):
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

    glp = KNOWN['gLinkPlayers']
    sb2 = KNOWN['gSaveBlock2Ptr']
    gmid = KNOWN['GetMultiplayerId'] & ~1

    # ================================================================
    # 1. Find InitLocalLinkPlayer
    # ================================================================
    print("\n" + "="*60)
    print("Finding InitLocalLinkPlayer")
    print("="*60)
    print(f"  gLinkPlayers = 0x{glp:08X} ({lp_refs(glp)} LP refs)")
    print(f"  gSaveBlock2Ptr = 0x{sb2:08X} ({lp_refs(sb2)} LP refs)")

    # Find all places where gLinkPlayers is loaded from literal pool
    glp_positions = lp_index.get(glp, [])
    print(f"\n  gLinkPlayers loaded at {len(glp_positions)} positions in ROM")

    # Find functions that reference gLinkPlayers
    glp_funcs = set()
    for p in glp_positions:
        func = find_push_lr(p)
        if func is not None:
            glp_funcs.add(func)
    print(f"  gLinkPlayers in {len(glp_funcs)} unique functions")

    # Find functions that BL GetMultiplayerId
    gmid_callers = set(bl_index.get(gmid, []))
    gmid_funcs = set()
    for p in gmid_callers:
        func = find_push_lr(p)
        if func is not None:
            gmid_funcs.add(func)
    print(f"  GetMultiplayerId called from {len(gmid_funcs)} unique functions")

    # Intersection: functions that BL GetMultiplayerId AND reference gLinkPlayers
    both_funcs = glp_funcs & gmid_funcs
    print(f"  Intersection: {len(both_funcs)} functions")

    # Among these, find ones that also reference gSaveBlock2Ptr
    candidates = []
    for func_off in sorted(both_funcs):
        func_lits = get_literal_values(func_off, 600)
        lit_vals = set(v for _, v in func_lits)

        has_sb2 = sb2 in lit_vals

        # Count different store types
        str_count = 0
        strb_count = 0
        strh_count = 0
        func_size = 0
        for p in range(func_off, min(func_off + 600, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is None: break
            op = hw >> 11
            if op == 0x0C: str_count += 1     # STR
            elif op == 0x0E: strb_count += 1  # STRB
            elif op == 0x10: strh_count += 1  # STRH
            if (hw & 0xFF00) == 0xBD00:
                func_size = p - func_off + 2
                break

        total_stores = str_count + strb_count + strh_count

        # Get BL targets
        bls = []
        p = func_off
        end = min(func_off + (func_size if func_size else 600), rom_size - 4)
        while p < end:
            h, l = ru16(rom, p), ru16(rom, p + 2)
            if is_bl(h, l):
                t = decode_bl(h, l, 0x08000000 + p + 4) & ~1
                bls.append(t)
                p += 4
            else:
                p += 2

        func_rom = 0x08000001 + func_off
        bl_callers = len(bl_index.get(func_off, []))

        candidates.append({
            'addr': func_rom,
            'off': func_off,
            'size': func_size,
            'stores': total_stores,
            'strb': strb_count,
            'strh': strh_count,
            'has_sb2': has_sb2,
            'callers': bl_callers,
            'bls': bls,
        })

    # InitLocalLinkPlayer should:
    # 1. Reference gSaveBlock2Ptr (reads player data from save)
    # 2. Have multiple STRB/STRH (writing to LinkPlayer struct fields)
    # 3. Be relatively small (50-200 bytes)
    # 4. Call StringCopy (for player name)
    # 5. Be called by other functions

    # Sort: has_sb2 first, then by (strb+strh), then by size (prefer smaller)
    candidates.sort(key=lambda c: (-c['has_sb2'], -(c['strb'] + c['strh']), c['size'] if c['size'] > 0 else 9999))

    print(f"\nTop candidates (BL GetMultiplayerId + LP gLinkPlayers):")
    for c in candidates[:25]:
        flags = []
        if c['has_sb2']: flags.append("gSB2")
        sz = c['size'] if c['size'] > 0 else "?"
        print(f"  0x{c['addr']:08X} size={sz:>4} stores={c['stores']:2d} strb={c['strb']} strh={c['strh']} callers={c['callers']} [{','.join(flags)}]")

    # Best match
    best = None
    for c in candidates:
        if c['has_sb2'] and (c['strb'] + c['strh']) >= 3 and 20 <= c['size'] <= 300:
            best = c
            break

    if not best:
        for c in candidates:
            if c['has_sb2'] and c['stores'] >= 3:
                best = c
                break

    if not best:
        for c in candidates:
            if (c['strb'] + c['strh']) >= 3 and 20 <= c['size'] <= 300:
                best = c
                break

    if best:
        print(f"\n  => InitLocalLinkPlayer = 0x{best['addr']:08X}")
        print(f"     (size={best['size']}, stores={best['stores']}, strb={best['strb']}, strh={best['strh']}, callers={best['callers']})")
    else:
        print(f"\n  => InitLocalLinkPlayer NOT FOUND in strict search")
        # Show ALL candidates for manual inspection
        print(f"\n  All {len(candidates)} candidates for manual inspection:")
        for c in candidates:
            sz = c['size'] if c['size'] > 0 else "?"
            flags = "gSB2" if c['has_sb2'] else ""
            print(f"    0x{c['addr']:08X} size={sz:>4} st={c['stores']} strb={c['strb']} strh={c['strh']} callers={c['callers']} {flags}")

    # Disassemble best candidate
    if best:
        print(f"\n  Disassembly of 0x{best['addr']:08X}:")
        off = best['off']
        p = off
        while p < min(off + 200, rom_size - 2):
            hw = ru16(rom, p)
            addr = 0x08000000 + p

            # Check BL
            if p + 4 <= rom_size:
                h, l = hw, ru16(rom, p + 2)
                if is_bl(h, l):
                    target = decode_bl(h, l, addr + 4)
                    t_aligned = target & ~1
                    name = ""
                    if t_aligned == gmid: name = " ; GetMultiplayerId"
                    elif t_aligned == (KNOWN['SetMainCallback2'] & ~1): name = " ; SetMainCallback2"
                    elif t_aligned == (KNOWN['CreateTask'] & ~1): name = " ; CreateTask"
                    callers = len(bl_index.get(t_aligned, []))
                    print(f"    0x{addr:08X}: BL 0x{target:08X} ({callers} callers){name}")
                    p += 4
                    continue

            if (hw >> 11) == 0x09:
                rd = (hw >> 8) & 7
                imm8 = hw & 0xFF
                pc_val = ((addr + 4) & ~2) + imm8 * 4
                pool_off = (pc_val - 0x08000000)
                val = ru32(rom, pool_off)
                name = ""
                if val == glp: name = " ; gLinkPlayers"
                elif val == sb2: name = " ; gSaveBlock2Ptr"
                elif val == KNOWN['gLinkPlayers']: name = " ; gLinkPlayers"
                elif val and 0x03000000 <= val <= 0x03007FFF: name = f" ; IWRAM"
                elif val and 0x02020000 <= val <= 0x0203FFFF: name = f" ; EWRAM"
                elif val and 0x08000000 <= val <= 0x09FFFFFF: name = f" ; ROM func?"
                print(f"    0x{addr:08X}: LDR R{rd}, =0x{val:08X}{name}")
            elif (hw & 0xFF00) == 0xB500:
                regs = []
                for i in range(8):
                    if hw & (1 << i): regs.append(f"R{i}")
                if hw & 0x100: regs.append("LR")
                print(f"    0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
            elif (hw & 0xFF00) == 0xBD00:
                regs = []
                for i in range(8):
                    if hw & (1 << i): regs.append(f"R{i}")
                if hw & 0x100: regs.append("PC")
                print(f"    0x{addr:08X}: POP {{{', '.join(regs)}}}")
                break
            elif (hw >> 11) == 0x0E:
                print(f"    0x{addr:08X}: STRB (0x{hw:04X})")
            elif (hw >> 11) == 0x10:
                print(f"    0x{addr:08X}: STRH (0x{hw:04X})")
            elif (hw >> 11) == 0x0C:
                print(f"    0x{addr:08X}: STR (0x{hw:04X})")
            elif (hw >> 11) == 0x04:
                rd = (hw >> 8) & 7
                imm = hw & 0xFF
                print(f"    0x{addr:08X}: MOV R{rd}, #{imm}")
            elif (hw >> 12) == 0xD:
                cond = (hw >> 8) & 0xF
                offset_val = hw & 0xFF
                if offset_val >= 0x80: offset_val -= 0x100
                target = addr + 4 + offset_val * 2
                cond_names = ['BEQ','BNE','BCS','BCC','BMI','BPL','BVS','BVC','BHI','BLS','BGE','BLT','BGT','BLE']
                cname = cond_names[cond] if cond < 14 else f"B{cond}"
                print(f"    0x{addr:08X}: {cname} 0x{target:08X}")
            elif (hw >> 11) == 0x0D:
                print(f"    0x{addr:08X}: LDR Rd,[Rn,#] (0x{hw:04X})")
            elif (hw >> 11) == 0x0F:
                print(f"    0x{addr:08X}: LDRB (0x{hw:04X})")
            elif (hw >> 11) == 0x11:
                print(f"    0x{addr:08X}: LDRH (0x{hw:04X})")
            else:
                print(f"    0x{addr:08X}: 0x{hw:04X}")

            p += 2

    # ================================================================
    # 2. Find DestroyTask (near CreateTask)
    # ================================================================
    print("\n" + "="*60)
    print("Finding DestroyTask")
    print("="*60)

    ct = KNOWN['CreateTask'] & ~1
    # DestroyTask is usually right after CreateTask in the ROM
    # Or close by. It has many callers (>400)
    print(f"CreateTask at 0x{ct|1:08X} ({len(bl_index.get(ct, []))} callers)")

    # Scan from CreateTask-0x400 to CreateTask+0x400
    high_caller_funcs = []
    for test in range(ct - 0x400, ct + 0x800, 2):
        if test == ct: continue
        callers = len(bl_index.get(test, []))
        if callers >= 200:
            high_caller_funcs.append((test, callers))

    high_caller_funcs.sort(key=lambda x: -x[1])
    for addr, callers in high_caller_funcs[:5]:
        print(f"  0x{addr|1:08X}: {callers} callers")
        # Disassemble first few instructions
        off = addr - 0x08000000
        print(f"    First 4 instructions:")
        p = off
        for _ in range(6):
            hw = ru16(rom, p)
            a = 0x08000000 + p
            if hw is not None and (hw & 0xFF00) == 0xB500:
                print(f"      0x{a:08X}: PUSH {{LR, ...}}")
            elif hw is not None and (hw >> 11) == 0x09:
                imm8 = hw & 0xFF
                rd = (hw >> 8) & 7
                pc_val = ((a + 4) & ~2) + imm8 * 4
                pool_off = pc_val - 0x08000000
                val = ru32(rom, pool_off)
                print(f"      0x{a:08X}: LDR R{rd}, =0x{val:08X}")
            else:
                print(f"      0x{a:08X}: 0x{hw:04X}")
            p += 2

    if high_caller_funcs:
        dt = high_caller_funcs[0][0] | 1
        print(f"\n  => DestroyTask = 0x{dt:08X} ({high_caller_funcs[0][1]} callers)")
    else:
        print(f"\n  => DestroyTask NOT FOUND")

    # ================================================================
    # 3. Summary
    # ================================================================
    print("\n" + "="*60)
    print("COMPLETE LOADSCRIPT(37) ADDRESS TABLE")
    print("="*60)

    all_addrs = {
        'CreateTask':            0x080C1544,
        'gSpecialVar_8000':      0x02036BB0,
        'gScriptLoad':           0x03000E38,
        'gScriptData':           0x096E0000,
        'gNativeData':           0x096F0000,
        'gSendBuffer':           0x02022BC4,
        'sBlockSend':            0x03000D10,
        'gLinkCallback':         0x03003140,
        'gLinkPlayers':          0x02022CE8,
        'gSaveBlock2Ptr':        0x03005D90,
        'CB2_Overworld':         0x080A89A5,
    }
    if best:
        all_addrs['InitLocalLinkPlayer'] = best['addr']
    if high_caller_funcs:
        all_addrs['DestroyTask'] = high_caller_funcs[0][0] | 1

    for name, val in sorted(all_addrs.items()):
        print(f"  {name:40s} = 0x{val:08X}")

    missing = []
    needed = ['CreateTask', 'InitLocalLinkPlayer', 'gSpecialVar_8000', 'gScriptLoad',
              'gScriptData', 'gNativeData', 'gLinkPlayers', 'CB2_Overworld',
              'gSendBuffer', 'sBlockSend', 'gLinkCallback', 'DestroyTask']
    for n in needed:
        if n not in all_addrs:
            missing.append(n)

    if missing:
        print(f"\nStill missing: {', '.join(missing)}")
    else:
        print(f"\nAll needed addresses found!")
        print("\nNOTE: Task_StartWiredCableClubBattle and CB2_ReturnToField are NOT needed:")
        print("  - Custom ASM replaces Task_StartWiredCableClubBattle")
        print("  - CB2_Overworld replaces CB2_ReturnToField (direct savedCallback write)")

if __name__ == '__main__':
    main()
