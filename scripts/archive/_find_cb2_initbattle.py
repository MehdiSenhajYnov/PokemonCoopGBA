"""
Find CB2_InitBattle in Run & Bun ROM by scanning for:
1. Literal pool refs to CB2_InitBattleInternal (0x08036491)
2. BL instructions targeting CB2_InitBattleInternal (0x08036490) across ENTIRE ROM
3. Analyze containing functions for each match

Also verify CB2_InitBattleInternal by reading its first instructions.
"""
import struct
import sys
import json
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rom", "Pokemon RunBun.gba")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "_py_scan_results.json")

CB2_INIT_BATTLE_INTERNAL = 0x08036491
CB2_INIT_BATTLE_INTERNAL_PC = 0x08036490
CB2_HANDLE_START_BATTLE = 0x08037B45

def read_u16(data, offset):
    if offset + 2 > len(data):
        return None
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    if offset + 4 > len(data):
        return None
    return struct.unpack_from('<I', data, offset)[0]

def decode_bl(instr_h, instr_l, pc):
    """Decode THUMB BL (2 half-words)"""
    off11hi = instr_h & 0x07FF
    off11lo = instr_l & 0x07FF
    full_off = (off11hi << 12) | (off11lo << 1)
    if full_off >= 0x400000:
        full_off -= 0x800000
    return pc + full_off

def decode_b(instr, pc):
    """Decode THUMB B (unconditional)"""
    if (instr & 0xF800) != 0xE000:
        return None
    imm11 = instr & 0x07FF
    if imm11 >= 0x400:
        imm11 -= 0x800
    return pc + 4 + imm11 * 2

def find_func_start(data, offset, max_back=4096):
    """Walk backward from offset to find PUSH {... LR} prologue"""
    start = max(0, offset - max_back)
    for pos in range(offset - 2, start - 1, -2):
        instr = read_u16(data, pos)
        if instr is None:
            continue
        # PUSH {LR} variants: B5xx, B4xx with bit 8 set
        hi_byte = (instr >> 8) & 0xFF
        if hi_byte == 0xB5 or (hi_byte == 0xB4 and (instr & 0x100)):
            return pos
    return None

def analyze_function(data, func_offset, max_size=2048):
    """Analyze a THUMB function starting at func_offset"""
    end_off = min(func_offset + max_size, len(data))
    first_instr = read_u16(data, func_offset)
    if first_instr is None:
        return None
    hi = (first_instr >> 8) & 0xFF
    if hi != 0xB5 and not (hi == 0xB4 and (first_instr & 0x100)):
        return None

    func_end = None
    bl_targets = []
    b_targets = []
    ldr_literals = []

    pos = func_offset
    while pos < end_off - 1:
        instr = read_u16(data, pos)
        if instr is None:
            break
        rel = pos - func_offset

        # POP {PC} or BX LR
        if rel > 2 and ((instr & 0xFF00) == 0xBD00 or instr == 0x4770):
            func_end = pos + 2
            break

        # B (unconditional)
        if (instr & 0xF800) == 0xE000:
            pc = 0x08000000 + pos
            target = decode_b(instr, pc)
            if target:
                b_targets.append({'offset': rel, 'target': target})

        # LDR Rd, [PC, #imm]
        if (instr & 0xF800) == 0x4800:
            imm8 = (instr & 0xFF) * 4
            pc_aligned = ((pos + 4) & ~3) + 0x08000000
            lit_rom_off = (pc_aligned + imm8) - 0x08000000
            if 0 <= lit_rom_off < len(data) - 3:
                lit_val = read_u32(data, lit_rom_off)
                ldr_literals.append({'offset': rel, 'value': lit_val, 'lit_rom_off': lit_rom_off})

        # BL (two half-words)
        if pos + 3 < end_off:
            nxt = read_u16(data, pos + 2)
            if nxt and (instr & 0xF800) == 0xF000 and (nxt & 0xF800) == 0xF800:
                bl_pc = 0x08000000 + pos + 4
                target = decode_bl(instr, nxt, bl_pc)
                bl_targets.append({'offset': rel, 'target': target})
                pos += 4
                continue

        pos += 2

    size = (func_end - func_offset) if func_end else (end_off - func_offset)
    return {
        'rom_off': func_offset,
        'addr': 0x08000000 + func_offset + 1,
        'size': size,
        'has_end': func_end is not None,
        'bl_count': len(bl_targets),
        'bl_targets': bl_targets,
        'b_targets': b_targets,
        'ldr_literals': ldr_literals,
    }

def main():
    if not os.path.exists(ROM_PATH):
        print(f"ROM not found: {ROM_PATH}")
        sys.exit(1)

    print(f"Reading ROM: {ROM_PATH}")
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    print(f"ROM size: {len(rom)} bytes ({len(rom)/(1024*1024):.1f} MB)")

    results = {
        'rom_size_mb': len(rom) / (1024*1024),
        'CB2_InitBattleInternal': f'0x{CB2_INIT_BATTLE_INTERNAL:08X}',
    }

    # Step 0: Verify CB2_InitBattleInternal
    print("\n=== Step 0: Verify CB2_InitBattleInternal (0x08036491) ===")
    int_rom_off = CB2_INIT_BATTLE_INTERNAL_PC - 0x08000000
    int_info = analyze_function(rom, int_rom_off, max_size=8192)
    if int_info:
        print(f"  Function at 0x{int_info['addr']:08X}: {int_info['size']} bytes, {int_info['bl_count']} BLs, {len(int_info['b_targets'])} Bs, end={int_info['has_end']}")
        print(f"  First 5 BL targets:")
        for i, bl in enumerate(int_info['bl_targets'][:5]):
            print(f"    BL{i+1} -> 0x{bl['target']:08X} at +0x{bl['offset']:X}")
        print(f"  First 5 LDR literals:")
        for i, ldr in enumerate(int_info['ldr_literals'][:5]):
            print(f"    LDR =0x{ldr['value']:08X} at +0x{ldr['offset']:X}")
    else:
        print("  WARNING: Could not analyze function!")

    # Step 1: Find literal pool refs to CB2_InitBattleInternal
    print("\n=== Step 1: Literal pool refs to CB2_InitBattleInternal ===")
    target_bytes = struct.pack('<I', CB2_INIT_BATTLE_INTERNAL)
    target_bytes_pc = struct.pack('<I', CB2_INIT_BATTLE_INTERNAL_PC)

    lit_refs = []
    for offset in range(0, len(rom) - 3, 4):
        chunk = rom[offset:offset+4]
        if chunk == target_bytes or chunk == target_bytes_pc:
            lit_refs.append(offset)

    print(f"  Found {len(lit_refs)} literal pool refs")
    results['literal_refs_to_internal'] = len(lit_refs)

    lit_ref_funcs = []
    for lit_off in lit_refs:
        func_start = find_func_start(rom, lit_off)
        if func_start is not None:
            info = analyze_function(rom, func_start, max_size=1024)
            if info and info['has_end']:
                # Check it's not CB2_InitBattleInternal itself
                if info['addr'] != CB2_INIT_BATTLE_INTERNAL:
                    dup = any(f['addr'] == info['addr'] for f in lit_ref_funcs)
                    if not dup:
                        lit_ref_funcs.append(info)
                        print(f"  Func: 0x{info['addr']:08X} ({info['size']} bytes, {info['bl_count']} BLs, {len(info['b_targets'])} Bs)")
                        for bl in info['bl_targets'][:5]:
                            print(f"    BL -> 0x{bl['target']:08X}")
                        for bt in info['b_targets']:
                            print(f"    B -> 0x{bt['target']:08X}")

    # Step 2: Find BL instructions targeting CB2_InitBattleInternal (ENTIRE ROM)
    print("\n=== Step 2: BL scan (entire ROM) ===")
    bl_callers = []
    target_pc = CB2_INIT_BATTLE_INTERNAL_PC

    for pos in range(0, len(rom) - 3, 2):
        h = read_u16(rom, pos)
        l = read_u16(rom, pos + 2)
        if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800:
            bl_pc = 0x08000000 + pos + 4
            bl_target = decode_bl(h, l, bl_pc)
            if bl_target == target_pc or bl_target == CB2_INIT_BATTLE_INTERNAL:
                bl_callers.append(pos)

    print(f"  Found {len(bl_callers)} BL instructions to CB2_InitBattleInternal")
    results['bl_calls_to_internal'] = len(bl_callers)

    bl_caller_funcs = []
    for bl_off in bl_callers:
        func_start = find_func_start(rom, bl_off)
        if func_start is not None:
            info = analyze_function(rom, func_start, max_size=1024)
            if info and info['has_end'] and info['addr'] != CB2_INIT_BATTLE_INTERNAL:
                dup = any(f['addr'] == info['addr'] for f in bl_caller_funcs)
                if not dup:
                    bl_caller_funcs.append(info)
                    print(f"  Func: 0x{info['addr']:08X} ({info['size']} bytes, {info['bl_count']} BLs)")
                    for bl in info['bl_targets'][:8]:
                        print(f"    BL -> 0x{bl['target']:08X}")
                    for bt in info['b_targets']:
                        print(f"    B -> 0x{bt['target']:08X}")

    # Step 3: Find B instructions targeting CB2_InitBattleInternal (wider scan)
    print("\n=== Step 3: B scan (wider: entire ROM) ===")
    b_callers = []
    for pos in range(0, len(rom) - 1, 2):
        instr = read_u16(rom, pos)
        if instr and (instr & 0xF800) == 0xE000:
            pc = 0x08000000 + pos
            target = decode_b(instr, pc)
            if target and (target == target_pc or target == CB2_INIT_BATTLE_INTERNAL):
                b_callers.append(pos)

    print(f"  Found {len(b_callers)} B instructions to CB2_InitBattleInternal")
    results['b_jumps_to_internal'] = len(b_callers)

    b_caller_funcs = []
    for b_off in b_callers:
        func_start = find_func_start(rom, b_off)
        if func_start is not None:
            info = analyze_function(rom, func_start, max_size=512)
            if info and info['addr'] != CB2_INIT_BATTLE_INTERNAL:
                dup = any(f['addr'] == info['addr'] for f in b_caller_funcs)
                if not dup:
                    b_caller_funcs.append(info)
                    print(f"  Func: 0x{info['addr']:08X} ({info['size']} bytes, {info['bl_count']} BLs, end={info['has_end']})")
                    for bl in info['bl_targets'][:5]:
                        print(f"    BL -> 0x{bl['target']:08X}")
                    for bt in info['b_targets']:
                        print(f"    B -> 0x{bt['target']:08X}")

    # Step 4: Combine all candidates
    print("\n=== Step 4: All CB2_InitBattle candidates ===")
    all_candidates = {}
    for info in lit_ref_funcs + bl_caller_funcs + b_caller_funcs:
        addr = info['addr']
        if addr not in all_candidates:
            all_candidates[addr] = info

    # Score candidates: CB2_InitBattle should have 4-8 BLs and be 50-300 bytes
    scored = []
    for addr, info in all_candidates.items():
        score = 0
        if 4 <= info['bl_count'] <= 10:
            score += 20
        if 40 <= info['size'] <= 300:
            score += 20
        # Check if it references CB2_InitBattleInternal in a B or literal pool
        for bt in info['b_targets']:
            if bt['target'] in (target_pc, CB2_INIT_BATTLE_INTERNAL):
                score += 30
        for ldr in info['ldr_literals']:
            if ldr['value'] in (target_pc, CB2_INIT_BATTLE_INTERNAL):
                score += 25
        for bl in info['bl_targets']:
            if bl['target'] in (target_pc, CB2_INIT_BATTLE_INTERNAL):
                score += 15
        scored.append((score, addr, info))

    scored.sort(reverse=True)

    candidates_json = []
    for score, addr, info in scored[:10]:
        print(f"\n  Score {score}: 0x{addr:08X} ({info['size']} bytes, {info['bl_count']} BLs, {len(info['b_targets'])} Bs, end={info['has_end']})")
        bl_strs = [f"0x{bl['target']:08X}" for bl in info['bl_targets']]
        b_strs = [f"0x{bt['target']:08X}" for bt in info['b_targets']]
        ldr_strs = [f"0x{ldr['value']:08X}" for ldr in info['ldr_literals']]
        for s in bl_strs[:8]:
            print(f"    BL -> {s}")
        for s in b_strs:
            print(f"    B  -> {s}")
        for s in ldr_strs[:5]:
            print(f"    LDR = {s}")

        candidates_json.append({
            'addr': f"0x{addr:08X}",
            'size': info['size'],
            'bl_count': info['bl_count'],
            'b_count': len(info['b_targets']),
            'score': score,
            'bl_targets': bl_strs[:10],
            'b_targets': b_strs,
            'ldr_literals': ldr_strs[:10],
        })

    results['candidates'] = candidates_json
    results['best_CB2_InitBattle'] = candidates_json[0]['addr'] if candidates_json else None

    # Step 5: Also scan for literal pool refs to CB2_HandleStartBattle for cross-reference
    print("\n=== Step 5: Verify - literal pool refs to CB2_HandleStartBattle ===")
    hsb_bytes = struct.pack('<I', CB2_HANDLE_START_BATTLE)
    hsb_refs = []
    for offset in range(0, len(rom) - 3, 4):
        if rom[offset:offset+4] == hsb_bytes:
            hsb_refs.append(offset)
    print(f"  Found {len(hsb_refs)} literal pool refs: {['0x{:06X}'.format(r) for r in hsb_refs]}")
    results['hsb_literal_refs'] = [f"0x{r:06X}" for r in hsb_refs]

    # Write results
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to: {OUTPUT_PATH}")

if __name__ == '__main__':
    main()
