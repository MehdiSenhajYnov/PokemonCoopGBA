#!/usr/bin/env python3
"""
Targeted investigation for the 2 remaining missing addresses:
  - Task_StartWiredCableClubBattle (or equivalent)
  - CB2_ReturnToField

Also verifies CB2_Overworld and examines candidates from v2 scanner.
"""

import struct, os, sys, time

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

KNOWN = {
    'SetUpBattleVars':       0x0806F1D9,
    'CB2_InitBattle':        0x080363C1,
    'CB2_HandleStartBattle': 0x08037B45,
    'SetMainCallback2':      0x08000544,
    'GetMultiplayerId':      0x0800A4B1,
    'IsLinkTaskFinished':    0x0800A569,
    'BattleMainCB2':         0x0803816D,
    'CB2_Overworld':         0x080A89A5,
    'gBattleTypeFlags':      0x02023364,
    'CreateTask':            0x080C1544,
    'gSpecialVar_8000':      0x02036BB0,
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
def to_rom(o): return 0x08000001 + o

def disasm_thumb(rom, file_off, count=40):
    """Simple THUMB disassembler for analysis."""
    lines = []
    pos = file_off
    for _ in range(count):
        if pos + 2 > len(rom): break
        hw = ru16(rom, pos)
        addr = 0x08000000 + pos

        # Check for BL (32-bit)
        if pos + 4 <= len(rom):
            h, l = hw, ru16(rom, pos + 2)
            if is_bl(h, l):
                target = decode_bl(h, l, addr + 4)
                lines.append(f"  0x{addr:08X}: BL 0x{target:08X}")
                pos += 4
                continue

        # PUSH
        if (hw & 0xFF00) == 0xB500:
            regs = []
            if hw & 0x100: regs.append("LR")
            for i in range(8):
                if hw & (1 << i): regs.append(f"R{i}")
            lines.append(f"  0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
        # POP
        elif (hw & 0xFF00) == 0xBD00:
            regs = []
            if hw & 0x100: regs.append("PC")
            for i in range(8):
                if hw & (1 << i): regs.append(f"R{i}")
            lines.append(f"  0x{addr:08X}: POP {{{', '.join(regs)}}}")
        # LDR Rd, [PC, #imm]
        elif (hw >> 11) == 0x09:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            pool_addr = ((addr + 4) & ~2) + imm8 * 4
            pool_file = pool_addr - 0x08000000
            val = ru32(rom, pool_file) if pool_file + 4 <= len(rom) else None
            val_str = f"0x{val:08X}" if val is not None else "???"
            lines.append(f"  0x{addr:08X}: LDR R{rd}, [PC, #{imm8*4}]  ; ={val_str}")
        # MOV Rd, #imm
        elif (hw >> 11) == 0x04:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: MOV R{rd}, #{imm}  ; 0x{imm:02X}")
        # CMP Rn, #imm
        elif (hw >> 11) == 0x05:
            rn = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: CMP R{rn}, #{imm}")
        # BEQ/BNE/etc
        elif (hw >> 12) == 0xD:
            cond = (hw >> 8) & 0xF
            offset = hw & 0xFF
            if offset >= 0x80: offset -= 0x100
            target = addr + 4 + offset * 2
            cond_names = ['BEQ','BNE','BCS','BCC','BMI','BPL','BVS','BVC','BHI','BLS','BGE','BLT','BGT','BLE','BAL','SWI']
            cname = cond_names[cond] if cond < 16 else f"B{cond}"
            lines.append(f"  0x{addr:08X}: {cname} 0x{target:08X}")
        # STR/STRH/STRB
        elif (hw >> 11) == 0x0C:
            lines.append(f"  0x{addr:08X}: STR ... (0x{hw:04X})")
        elif (hw >> 11) == 0x10:
            lines.append(f"  0x{addr:08X}: STRH ... (0x{hw:04X})")
        elif (hw >> 11) == 0x0E:
            lines.append(f"  0x{addr:08X}: STRB ... (0x{hw:04X})")
        # LDR Rd, [Rn, #imm]
        elif (hw >> 11) == 0x0D:
            lines.append(f"  0x{addr:08X}: LDR Rd, [Rn, #imm] (0x{hw:04X})")
        # LDRH
        elif (hw >> 11) == 0x11:
            lines.append(f"  0x{addr:08X}: LDRH ... (0x{hw:04X})")
        # LDRB
        elif (hw >> 11) == 0x0F:
            lines.append(f"  0x{addr:08X}: LDRB ... (0x{hw:04X})")
        # BX Rm
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            lines.append(f"  0x{addr:08X}: BX R{rm}")
        # ADD/SUB low reg
        elif (hw >> 9) == 0x0E:
            lines.append(f"  0x{addr:08X}: ADD/SUB (0x{hw:04X})")
        else:
            lines.append(f"  0x{addr:08X}: 0x{hw:04X}")

        pos += 2
    return lines

def main():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    rom_size = len(rom)

    # Build indices
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

    # ================================================================
    # VERIFY CB2_Overworld
    # ================================================================
    print("\n" + "="*60)
    print("Verifying CB2_Overworld = 0x{:08X}".format(KNOWN['CB2_Overworld']))
    print("="*60)

    cb2_ow = KNOWN['CB2_Overworld']
    print(f"  LP refs (odd):  {lp_refs(cb2_ow)}")
    print(f"  LP refs (even): {lp_refs(cb2_ow & ~1)}")
    print(f"  BL callers:     {len(bl_index.get(cb2_ow & ~1, []))}")

    # Disassemble function at CB2_Overworld
    print(f"\n  Disassembly at 0x{cb2_ow:08X}:")
    for line in disasm_thumb(rom, to_file(cb2_ow), 30):
        print(f"    {line}")

    # Search for the REAL CB2_Overworld if needed
    # CB2_Overworld/CB2_OverworldBasic is a large function that's the main overworld loop
    # It should be referenced as the saved callback written to gMain.savedCallback
    # by many functions (warp, battle end, etc.)
    #
    # gMain.callback2 offset = gMain+4 = 0x030022C4
    # gMain.savedCallback = gMain+8 = 0x030022C8
    # Any function writing to savedCallback should load a ROM callback value

    # Let's check: maybe the address stored is slightly different
    # Search for 0x080A89xx values in literal pools
    print("\n  Searching for 0x080A89xx values in literal pools:")
    for delta in range(-0x100, 0x101, 2):
        test = cb2_ow + delta
        refs = lp_refs(test) + lp_refs(test & ~1)
        if refs > 0:
            print(f"    0x{test:08X}: {refs} refs")

    # Wider search: check all ROM addresses with many LP refs near CB2_Overworld
    print("\n  High-ref ROM addresses near CB2_Overworld (0x080A8xxx-0x080Axxxx):")
    for base in range(0x080A0000, 0x080B0000, 2):
        refs = lp_refs(base)
        if refs >= 5:
            print(f"    0x{base:08X}: {refs} refs")

    # ================================================================
    # CB2_ReturnToField — Alternative approach
    # ================================================================
    print("\n" + "="*60)
    print("CB2_ReturnToField — Alternative: Find via gMain.savedCallback")
    print("="*60)

    # gMain.savedCallback = 0x030022C8
    # Many functions write: gMain.savedCallback = CB2_ReturnToField
    # So CB2_ReturnToField should appear as a literal pool value that is
    # stored to 0x030022C8 (or gMain+8)
    #
    # Also: CB2_ReturnToField is in the literal pool of CB2_EndLinkBattle/CB2_SetBattleEndCallbacks
    # which are near BattleMainCB2 in ROM

    # Search near BattleMainCB2 for literal pool values that are ROM function pointers
    bmcb2_off = to_file(KNOWN['BattleMainCB2'])
    print(f"  BattleMainCB2 at 0x{KNOWN['BattleMainCB2']:08X}")
    print(f"  Scanning 50KB neighborhood for function-pointer literal pool values...")

    # Find all distinct ROM addresses loaded from literal pools in the
    # 0x08037000-0x08045000 range (near battle main functions)
    rom_func_ptrs = {}
    for start in range(0x037000, min(0x045000, rom_size)):
        hw = ru16(rom, start)
        if hw is not None and (hw >> 11) == 0x09:
            imm8 = hw & 0xFF
            pc = ((start + 4 + 0x08000000) & ~2)
            pool_file = (pc - 0x08000000) + imm8 * 4
            val = ru32(rom, pool_file)
            if val is not None and 0x08060000 <= val <= 0x080C0000:
                # Check if this is a function (PUSH LR at target)
                target_off = to_file(val)
                target_hw = ru16(rom, target_off)
                if target_hw is not None and (target_hw & 0xFF00) == 0xB500:
                    rom_func_ptrs.setdefault(val, []).append(start)

    # Find which of these function pointers are small wrappers calling SetMainCallback2
    smc2_aligned = KNOWN['SetMainCallback2'] & ~1
    print(f"\n  Small wrapper functions that call SetMainCallback2:")
    for ptr, ref_positions in sorted(rom_func_ptrs.items()):
        ptr_off = to_file(ptr)
        # Check size
        size = 0
        for p in range(ptr_off, min(ptr_off + 40, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xBD00:
                size = p - ptr_off + 2
                break
        if size == 0 or size > 30:
            continue

        # Check for BL to SetMainCallback2
        bls = []
        p = ptr_off
        while p < ptr_off + size:
            h, l = ru16(rom, p), ru16(rom, p + 2)
            if is_bl(h, l):
                target = decode_bl(h, l, 0x08000000 + p + 4)
                bls.append(target & ~1)
                p += 4
            else:
                p += 2

        if smc2_aligned not in bls:
            continue

        # Get literal pool value (the argument to SetMainCallback2)
        lits = []
        for p in range(ptr_off, min(ptr_off + size + 20, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw >> 11) == 0x09:
                imm8 = hw & 0xFF
                pc = ((0x08000000 + p + 4) & ~2)
                pool_off = (pc - 0x08000000) + imm8 * 4
                val = ru32(rom, pool_off)
                if val is not None:
                    lits.append(val)

        total_refs = lp_refs(ptr) + lp_refs(ptr & ~1)
        # Filter: the argument should be a ROM callback (0x08xxxxxx)
        rom_args = [v for v in lits if 0x08000000 <= v <= 0x09FFFFFF and v != ptr]

        print(f"    0x{ptr:08X} size={size} lp_refs={total_refs} arg={[f'0x{v:08X}' for v in rom_args]} refs_from_battle={len(ref_positions)}")
        print(f"      Disasm:")
        for line in disasm_thumb(rom, ptr_off, 10):
            print(f"        {line}")

    # ================================================================
    # Task_StartWiredCableClubBattle — Deep investigation
    # ================================================================
    print("\n" + "="*60)
    print("Task_StartWiredCableClubBattle — Investigation")
    print("="*60)

    # Examine the candidate from v2: 0x080CF3ED
    candidate_off = to_file(0x080CF3ED)
    print(f"\n  Candidate 0x080CF3ED disassembly:")
    for line in disasm_thumb(rom, candidate_off, 60):
        print(f"    {line}")

    # Find what literal values this function loads
    lits = []
    for p in range(candidate_off, min(candidate_off + 300, rom_size - 2), 2):
        hw = ru16(rom, p)
        if hw is not None and (hw >> 11) == 0x09:
            imm8 = hw & 0xFF
            pc = ((0x08000000 + p + 4) & ~2)
            pool_off = (pc - 0x08000000) + imm8 * 4
            val = ru32(rom, pool_off)
            if val is not None:
                lits.append(val)
    print(f"\n  Literal pool values: {[f'0x{v:08X}' for v in lits]}")

    # Better approach: Among the 131 IsLinkTaskFinished callers,
    # find ones that also call SetMainCallback2 AND load a BATTLE_TYPE value
    print(f"\n  ILF callers that also call SetMainCallback2:")
    ilf_aligned = KNOWN['IsLinkTaskFinished'] & ~1
    ilf_callers = bl_index.get(ilf_aligned, [])

    for caller_off in ilf_callers:
        # Find function start
        func = None
        for p in range(caller_off, max(0, caller_off - 4096), -2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xB500:
                func = p
                break
        if func is None:
            continue

        # Check BLs from this function
        func_bls = []
        p = func
        end = min(func + 500, rom_size - 4)
        while p < end:
            h, l = ru16(rom, p), ru16(rom, p + 2)
            if is_bl(h, l):
                target = decode_bl(h, l, 0x08000000 + p + 4)
                func_bls.append((p - func, target & ~1))
                p += 4
            else:
                p += 2

        has_smc2 = any(t == smc2_aligned for _, t in func_bls)
        if not has_smc2:
            continue

        func_rom = to_rom(func)
        # Get literal values
        func_lits = []
        for p in range(func, min(func + 500, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw >> 11) == 0x09:
                imm8 = hw & 0xFF
                pc = ((0x08000000 + p + 4) & ~2)
                pool_off = (pc - 0x08000000) + imm8 * 4
                val = ru32(rom, pool_off)
                if val is not None:
                    func_lits.append(val)

        # Check for interesting values
        has_cb2_init = any(v in [0x080363C0, 0x080363C1] for v in func_lits)
        has_btf = any(v == 0x02023364 for v in func_lits)

        # Function size
        func_size = 0
        for p in range(func, min(func + 500, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xBD00:
                func_size = p - func + 2
                break

        # List all BL targets
        bl_names = []
        for _, t in func_bls:
            if t == smc2_aligned:
                bl_names.append("SetMainCallback2")
            elif t == ilf_aligned:
                bl_names.append("IsLinkTaskFinished")
            elif t == (KNOWN['CreateTask'] & ~1):
                bl_names.append("CreateTask")
            else:
                bl_names.append(f"0x{t|1:08X}")

        # LP refs for this function (is it used as a task func?)
        lp_count = lp_refs(func_rom) + lp_refs(func_rom & ~1)

        print(f"    0x{func_rom:08X} size={func_size} cb2Init={has_cb2_init} btf={has_btf} lp_refs={lp_count}")
        print(f"      BLs: {', '.join(bl_names)}")

        # Show interesting literal values
        interesting = [v for v in func_lits if 0x08000000 <= v <= 0x09FFFFFF or 0x02020000 <= v <= 0x0203FFFF]
        if interesting:
            print(f"      Key literals: {[f'0x{v:08X}' for v in interesting[:8]]}")

    # ================================================================
    # Alternative: Check what functions reference CreateTask via BL
    # and load CB2_InitBattle from literal pool (the parent function
    # that CALLS CreateTask with Task_StartWiredCableClubBattle)
    # ================================================================
    print(f"\n  Functions that BL CreateTask AND have CB2_InitBattle in LP:")
    ct_aligned = KNOWN['CreateTask'] & ~1
    ct_callers = bl_index.get(ct_aligned, [])
    print(f"  CreateTask callers: {len(ct_callers)}")

    for caller_off in ct_callers:
        func = None
        for p in range(caller_off, max(0, caller_off - 4096), -2):
            hw = ru16(rom, p)
            if hw is not None and (hw & 0xFF00) == 0xB500:
                func = p
                break
        if func is None: continue

        func_lits = []
        for p in range(func, min(func + 500, rom_size - 2), 2):
            hw = ru16(rom, p)
            if hw is not None and (hw >> 11) == 0x09:
                imm8 = hw & 0xFF
                pc = ((0x08000000 + p + 4) & ~2)
                pool_off = (pc - 0x08000000) + imm8 * 4
                val = ru32(rom, pool_off)
                if val is not None:
                    func_lits.append(val)

        # Look for CB2_InitBattle in literal pool
        has_cb2 = any(v in [0x080363C0, 0x080363C1] for v in func_lits)
        if not has_cb2: continue

        func_rom = to_rom(func)
        # What ROM pointer is loaded before the CreateTask BL? That's the task func
        # In THUMB: LDR R0, =TaskFunc; MOV R1, #priority; BL CreateTask
        # R0 is loaded 2-6 instructions before the BL
        task_func_addr = None
        for p in range(max(func, caller_off - 12), caller_off, 2):
            hw = ru16(rom, p)
            if hw is not None and (hw >> 11) == 0x09:
                rd = (hw >> 8) & 7
                if rd == 0:  # LDR R0, ...
                    imm8 = hw & 0xFF
                    pc = ((0x08000000 + p + 4) & ~2)
                    pool_off = (pc - 0x08000000) + imm8 * 4
                    val = ru32(rom, pool_off)
                    if val is not None and 0x08000000 <= val <= 0x09FFFFFF:
                        task_func_addr = val

        if task_func_addr:
            task_lp_refs = lp_refs(task_func_addr) + lp_refs(task_func_addr & ~1)
            # Check what the task function does
            task_off = to_file(task_func_addr)
            task_bls = []
            p = task_off
            while p < min(task_off + 200, rom_size - 4):
                h, l = ru16(rom, p), ru16(rom, p + 2)
                if is_bl(h, l):
                    t = decode_bl(h, l, 0x08000000 + p + 4) & ~1
                    task_bls.append(t)
                    p += 4
                else:
                    p += 2

            has_ilf = ilf_aligned in task_bls
            has_smc2 = smc2_aligned in task_bls

            print(f"    Caller: 0x{func_rom:08X} → CreateTask(0x{task_func_addr:08X}, ...)")
            print(f"      Task func ILF={has_ilf} SMC2={has_smc2} lp_refs={task_lp_refs}")
            if has_ilf and has_smc2:
                print(f"      *** MATCH: Task_StartWiredCableClubBattle = 0x{task_func_addr:08X} ***")

if __name__ == '__main__':
    main()
