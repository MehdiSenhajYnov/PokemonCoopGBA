#!/usr/bin/env python3
"""
Find Task_StartWiredCableClubBattle in Pokemon Run & Bun ROM.

Strategy: Triple literal pool intersection.
The function's literal pool should contain ALL THREE of:
- CB2_InitBattle = 0x080363C1
- DestroyTask = 0x080C1AA5
- SetMainCallback2 = 0x08000545

Also tries secondary approaches:
- BL->CreateTask with CB2_InitBattle in LP
- gSpecialVar_8004/8005 in LP + BL->CreateTask
"""

import struct
import sys
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known addresses (THUMB addresses with +1 bit)
CB2_INIT_BATTLE      = 0x080363C1
DESTROY_TASK         = 0x080C1AA5
SET_MAIN_CALLBACK2   = 0x08000545
CREATE_TASK          = 0x080C1545  # THUMB
IS_LINK_TASK_FINISHED = 0x0800A569
G_SPECIAL_VAR_8004   = 0x02036BB8
G_SPECIAL_VAR_8005   = 0x02036BBA

# Also try without THUMB bit variants
DESTROY_TASK_ALT     = 0x080C1AA4 | 1  # same as 0x080C1AA5
SET_MAIN_CB2_ALT     = 0x08000544 | 1  # same as 0x08000545
CREATE_TASK_ALT      = 0x080C1544 | 1  # same as 0x080C1545


def read_rom(path):
    with open(path, 'rb') as f:
        return f.read()


def find_lp_refs(rom, value):
    """Find all 4-byte aligned offsets in ROM where value appears as a 32-bit word."""
    refs = []
    for off in range(0, len(rom) - 3, 4):
        v = struct.unpack_from('<I', rom, off)[0]
        if v == value:
            refs.append(off)
    return refs


def find_function_start(rom, offset):
    """Scan backwards from offset looking for PUSH {LR} (0xB5xx) pattern.
    Returns (rom_offset, gba_address) of function start."""
    # Scan backwards in 2-byte steps (THUMB)
    for back in range(0, min(offset, 2048), 2):
        pos = offset - back
        if pos < 0:
            break
        hw = struct.unpack_from('<H', rom, pos)[0]
        # PUSH {... LR} = 0xB5xx (bit 8 set = LR pushed)
        if (hw & 0xFF00) == 0xB500:
            return pos, ROM_BASE + pos
    return None, None


def find_function_end(rom, func_start_off, max_size=1024):
    """Estimate function end by looking for POP {... PC} or next PUSH {LR}."""
    for off in range(func_start_off + 2, min(func_start_off + max_size, len(rom) - 1), 2):
        hw = struct.unpack_from('<H', rom, off)[0]
        # POP {... PC} = 0xBDxx
        if (hw & 0xFF00) == 0xBD00:
            return off + 2  # instruction after POP
        # Next PUSH {LR} = new function
        if off > func_start_off + 4 and (hw & 0xFF00) == 0xB500:
            return off
    return func_start_off + max_size


def decode_bl(rom, offset):
    """Decode a THUMB BL instruction at the given ROM offset.
    Returns target GBA address or None."""
    if offset + 3 >= len(rom):
        return None
    hi = struct.unpack_from('<H', rom, offset)[0]
    lo = struct.unpack_from('<H', rom, offset + 2)[0]

    if (hi & 0xF800) != 0xF000:
        return None
    if (lo & 0xF800) != 0xF800:
        return None

    offset_hi = hi & 0x7FF
    offset_lo = lo & 0x7FF
    combined = (offset_hi << 12) | (offset_lo << 1)

    # Sign extend from 23 bits
    if combined & 0x400000:
        combined -= 0x800000

    # Target = address_of_hi + 4 + offset
    addr_of_hi = ROM_BASE + offset
    target = addr_of_hi + 4 + combined
    return target


def find_bl_targets_in_range(rom, start_off, end_off):
    """Find all BL instructions in a range and return list of (offset, target_addr)."""
    results = []
    off = start_off
    while off < end_off - 3:
        target = decode_bl(rom, off)
        if target is not None:
            results.append((off, target))
            off += 4  # BL is 4 bytes
        else:
            off += 2
    return results


def disassemble_thumb(rom, start_off, end_off):
    """Basic THUMB disassembly for display purposes."""
    lines = []
    off = start_off
    while off < end_off:
        addr = ROM_BASE + off
        hw = struct.unpack_from('<H', rom, off)[0]

        # Check if it's a BL
        bl_target = decode_bl(rom, off)
        if bl_target is not None:
            lo = struct.unpack_from('<H', rom, off + 2)[0]
            lines.append(f"  0x{addr:08X}: {hw:04X} {lo:04X}  BL 0x{bl_target:08X}")
            off += 4
            continue

        # Check for PUSH
        if (hw & 0xFF00) == 0xB500:
            regs = []
            for i in range(8):
                if hw & (1 << i):
                    regs.append(f"R{i}")
            if hw & 0x100:
                regs.append("LR")
            lines.append(f"  0x{addr:08X}: {hw:04X}       PUSH {{{', '.join(regs)}}}")
        # POP
        elif (hw & 0xFF00) == 0xBD00:
            regs = []
            for i in range(8):
                if hw & (1 << i):
                    regs.append(f"R{i}")
            if hw & 0x100:
                regs.append("PC")
            lines.append(f"  0x{addr:08X}: {hw:04X}       POP {{{', '.join(regs)}}}")
        # LDR Rd, [PC, #imm]
        elif (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc_val = (addr + 4) & ~3  # PC is aligned
            lp_addr = pc_val + imm
            lp_off = lp_addr - ROM_BASE
            val = "????????"
            if 0 <= lp_off < len(rom) - 3:
                val = f"0x{struct.unpack_from('<I', rom, lp_off)[0]:08X}"
            lines.append(f"  0x{addr:08X}: {hw:04X}       LDR R{rd}, [PC, #0x{imm:X}]  ; ={val} @0x{lp_addr:08X}")
        # MOV Rd, #imm
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: {hw:04X}       MOV R{rd}, #0x{imm:X}")
        # CMP Rd, #imm
        elif (hw & 0xF800) == 0x2800:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: {hw:04X}       CMP R{rd}, #0x{imm:X}")
        # B<cond>
        elif (hw & 0xF000) == 0xD000:
            cond = (hw >> 8) & 0xF
            soff = hw & 0xFF
            if soff & 0x80:
                soff -= 0x100
            target = addr + 4 + soff * 2
            cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                         "BHI","BLS","BGE","BLT","BGT","BLE","(undef)","SWI"]
            lines.append(f"  0x{addr:08X}: {hw:04X}       {cond_names[cond]} 0x{target:08X}")
        # B (unconditional)
        elif (hw & 0xF800) == 0xE000:
            soff = hw & 0x7FF
            if soff & 0x400:
                soff -= 0x800
            target = addr + 4 + soff * 2
            lines.append(f"  0x{addr:08X}: {hw:04X}       B 0x{target:08X}")
        # BX / BLX register
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            lines.append(f"  0x{addr:08X}: {hw:04X}       BX R{rm}")
        else:
            lines.append(f"  0x{addr:08X}: {hw:04X}       .hword 0x{hw:04X}")

        off += 2

    return "\n".join(lines)


def main():
    print(f"Loading ROM: {ROM_PATH}")
    rom = read_rom(ROM_PATH)
    print(f"ROM size: {len(rom)} bytes (0x{len(rom):X})")

    # ==========================================
    # APPROACH 1: Triple LP intersection
    # ==========================================
    print("\n" + "="*70)
    print("APPROACH 1: Triple Literal Pool Intersection")
    print("="*70)

    targets = {
        "CB2_InitBattle": [CB2_INIT_BATTLE],
        "DestroyTask": [DESTROY_TASK, DESTROY_TASK_ALT],
        "SetMainCallback2": [SET_MAIN_CALLBACK2, SET_MAIN_CB2_ALT],
    }

    # For each target, find all LP refs and their containing functions
    func_sets = {}
    for name, values in targets.items():
        refs = []
        for v in values:
            refs.extend(find_lp_refs(rom, v))
        refs = sorted(set(refs))
        print(f"\n  {name}: {len(refs)} LP refs found")

        funcs = set()
        for ref_off in refs:
            fstart, faddr = find_function_start(rom, ref_off)
            if fstart is not None:
                funcs.add(fstart)
        func_sets[name] = funcs
        print(f"  {name}: maps to {len(funcs)} unique functions")

    # Intersect: functions that have ALL 3
    intersection = func_sets["CB2_InitBattle"] & func_sets["DestroyTask"] & func_sets["SetMainCallback2"]
    print(f"\n  Triple intersection: {len(intersection)} functions")

    for fstart in sorted(intersection):
        faddr = ROM_BASE + fstart
        fend_off = find_function_end(rom, fstart)
        fsize = fend_off - fstart
        print(f"\n  CANDIDATE: 0x{faddr:08X} (THUMB: 0x{faddr|1:08X}), size ~{fsize} bytes")

        # Find BL targets
        bls = find_bl_targets_in_range(rom, fstart, fend_off)
        print(f"  BL calls:")
        for bl_off, bl_target in bls:
            bl_addr = ROM_BASE + bl_off
            label = ""
            if bl_target == CB2_INIT_BATTLE or bl_target == (CB2_INIT_BATTLE & ~1):
                label = " (CB2_InitBattle)"
            elif bl_target == DESTROY_TASK or bl_target == (DESTROY_TASK & ~1):
                label = " (DestroyTask)"
            elif bl_target == SET_MAIN_CALLBACK2 or bl_target == (SET_MAIN_CALLBACK2 & ~1):
                label = " (SetMainCallback2)"
            elif bl_target == CREATE_TASK or bl_target == (CREATE_TASK & ~1):
                label = " (CreateTask)"
            elif bl_target == IS_LINK_TASK_FINISHED or bl_target == (IS_LINK_TASK_FINISHED & ~1):
                label = " (IsLinkTaskFinished)"
            print(f"    0x{bl_addr:08X} -> 0x{bl_target:08X}{label}")

        print(f"\n  Disassembly:")
        # Include literal pool area (extend a bit past function end)
        disasm_end = min(fend_off + 64, len(rom))
        print(disassemble_thumb(rom, fstart, disasm_end))

    # ==========================================
    # APPROACH 2: BL->CreateTask with CB2_InitBattle in LP
    # ==========================================
    print("\n" + "="*70)
    print("APPROACH 2: Find callers of CreateTask that have CB2_InitBattle in LP")
    print("="*70)

    # Find all BL->CreateTask sites
    create_task_addr_no_thumb = CREATE_TASK & ~1  # 0x080C1544
    bl_create_task_sites = []
    for off in range(0, len(rom) - 3, 2):
        target = decode_bl(rom, off)
        if target is not None and (target == CREATE_TASK or target == create_task_addr_no_thumb):
            bl_create_task_sites.append(off)

    print(f"\n  Found {len(bl_create_task_sites)} BL->CreateTask call sites")

    # For each, find containing function, check if CB2_InitBattle is in its LP
    cb2_lp_refs = set(find_lp_refs(rom, CB2_INIT_BATTLE))

    matches = []
    for site_off in bl_create_task_sites:
        fstart, faddr = find_function_start(rom, site_off)
        if fstart is None:
            continue
        fend = find_function_end(rom, fstart, max_size=2048)

        # Check if any CB2_InitBattle LP ref falls within this function's range (including LP area)
        for lp_off in cb2_lp_refs:
            if fstart <= lp_off <= fend + 128:
                matches.append((fstart, site_off))
                break

    print(f"  Matches (CreateTask + CB2_InitBattle in LP): {len(matches)}")
    for fstart, site_off in matches:
        faddr = ROM_BASE + fstart
        fend = find_function_end(rom, fstart, max_size=2048)
        print(f"\n  CANDIDATE: func=0x{faddr:08X}, CreateTask call at 0x{ROM_BASE+site_off:08X}")

        # Look at what R0 is loaded with before the BL CreateTask
        # R0 = function pointer for the task callback
        # Scan backwards from the BL for an LDR R0, [PC, #imm]
        for back in range(0, min(site_off - fstart, 32), 2):
            pos = site_off - back - 2
            if pos < fstart:
                break
            hw = struct.unpack_from('<H', rom, pos)[0]
            if (hw & 0xF800) == 0x4800:  # LDR R0, [PC, #imm]
                rd = (hw >> 8) & 7
                if rd == 0:
                    imm = (hw & 0xFF) * 4
                    pc_val = (ROM_BASE + pos + 4) & ~3
                    lp_addr = pc_val + imm
                    lp_off = lp_addr - ROM_BASE
                    if 0 <= lp_off < len(rom) - 3:
                        val = struct.unpack_from('<I', rom, lp_off)[0]
                        print(f"    R0 loaded from LP: 0x{val:08X} (LDR at 0x{ROM_BASE+pos:08X})")
                        if val & 0x08000000:
                            print(f"    ==> Task_StartWiredCableClubBattle candidate: 0x{val:08X}")
                    break

        print(f"  Disassembly:")
        disasm_end = min(fend + 64, len(rom))
        print(disassemble_thumb(rom, fstart, disasm_end))

    # ==========================================
    # APPROACH 3: gSpecialVar_8004/8005 in LP + BL->CreateTask
    # ==========================================
    print("\n" + "="*70)
    print("APPROACH 3: gSpecialVar_8004/8005 in LP + BL->CreateTask")
    print("="*70)

    var8004_refs = set(find_lp_refs(rom, G_SPECIAL_VAR_8004))
    var8005_refs = set(find_lp_refs(rom, G_SPECIAL_VAR_8005))
    print(f"\n  gSpecialVar_8004 LP refs: {len(var8004_refs)}")
    print(f"  gSpecialVar_8005 LP refs: {len(var8005_refs)}")

    # Find functions containing both gSpecialVar refs + CreateTask
    for site_off in bl_create_task_sites:
        fstart, faddr = find_function_start(rom, site_off)
        if fstart is None:
            continue
        fend = find_function_end(rom, fstart, max_size=2048)

        has_8004 = any(fstart <= r <= fend + 128 for r in var8004_refs)
        has_8005 = any(fstart <= r <= fend + 128 for r in var8005_refs)

        if has_8004 and has_8005:
            print(f"\n  CANDIDATE: func=0x{faddr:08X}, has gSpecialVar_8004+8005 + CreateTask")

            # Look for R0 before CreateTask BL
            for back in range(0, min(site_off - fstart, 32), 2):
                pos = site_off - back - 2
                if pos < fstart:
                    break
                hw = struct.unpack_from('<H', rom, pos)[0]
                if (hw & 0xF800) == 0x4800 and ((hw >> 8) & 7) == 0:
                    imm = (hw & 0xFF) * 4
                    pc_val = (ROM_BASE + pos + 4) & ~3
                    lp_addr = pc_val + imm
                    lp_off = lp_addr - ROM_BASE
                    if 0 <= lp_off < len(rom) - 3:
                        val = struct.unpack_from('<I', rom, lp_off)[0]
                        print(f"    R0 loaded from LP: 0x{val:08X} => Task_StartWiredCableClubBattle candidate")
                    break

            fend_disasm = min(fend + 128, len(rom))
            print(f"  Disassembly:")
            print(disassemble_thumb(rom, fstart, fend_disasm))

    # ==========================================
    # APPROACH 4: Direct search - functions with CB2_InitBattle + IsLinkTaskFinished
    # ==========================================
    print("\n" + "="*70)
    print("APPROACH 4: Functions with BL->IsLinkTaskFinished + CB2_InitBattle in LP")
    print("="*70)

    is_link_finished_no_thumb = IS_LINK_TASK_FINISHED & ~1
    bl_islink_sites = []
    for off in range(0, len(rom) - 3, 2):
        target = decode_bl(rom, off)
        if target is not None and (target == IS_LINK_TASK_FINISHED or target == is_link_finished_no_thumb):
            bl_islink_sites.append(off)

    print(f"\n  Found {len(bl_islink_sites)} BL->IsLinkTaskFinished call sites")

    for site_off in bl_islink_sites:
        fstart, faddr = find_function_start(rom, site_off)
        if fstart is None:
            continue
        fend = find_function_end(rom, fstart, max_size=512)

        # Check for CB2_InitBattle in LP
        has_cb2 = any(fstart <= r <= fend + 128 for r in cb2_lp_refs)
        if has_cb2:
            print(f"\n  MATCH: func=0x{faddr:08X} (THUMB: 0x{faddr|1:08X})")
            print(f"    Has BL->IsLinkTaskFinished at 0x{ROM_BASE+site_off:08X}")
            print(f"    Has CB2_InitBattle in LP")

            # Also check for DestroyTask and SetMainCallback2
            bls = find_bl_targets_in_range(rom, fstart, fend)
            for bl_off, bl_target in bls:
                label = ""
                t_nothumb = bl_target & ~1
                if t_nothumb == (DESTROY_TASK & ~1):
                    label = " (DestroyTask)"
                elif t_nothumb == (SET_MAIN_CALLBACK2 & ~1):
                    label = " (SetMainCallback2)"
                elif t_nothumb == (CREATE_TASK & ~1):
                    label = " (CreateTask)"
                elif t_nothumb == (IS_LINK_TASK_FINISHED & ~1):
                    label = " (IsLinkTaskFinished)"
                elif t_nothumb == (CB2_INIT_BATTLE & ~1):
                    label = " (CB2_InitBattle)"
                if label:
                    print(f"    BL at 0x{ROM_BASE+bl_off:08X} -> 0x{bl_target:08X}{label}")

            fend_disasm = min(fend + 128, len(rom))
            print(f"\n  Disassembly:")
            print(disassemble_thumb(rom, fstart, fend_disasm))

    print("\n" + "="*70)
    print("DONE")
    print("="*70)


if __name__ == "__main__":
    main()
