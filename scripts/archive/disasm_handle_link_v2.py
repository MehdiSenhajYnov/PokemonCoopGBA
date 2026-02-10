#!/usr/bin/env python3
"""
Disassemble the function at ROM 0x0F6E92 area and find HandleLinkBattleSetup.
Also: find CreateTask by searching for gTasks (0x03005E00) reference.
Then find HandleLinkBattleSetup as a function that checks gBattleTypeFlags and calls CreateTask.
"""
import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_bl(hw1, hw2, pc):
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) in (0xF800, 0xE800):
        offset_hi = hw1 & 0x07FF
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800
        offset_lo = hw2 & 0x07FF
        target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
        return target & 0xFFFFFFFF
    return None

def find_all_bl_to(rom, target_addr, search_start=0, search_end=None):
    if search_end is None:
        search_end = min(len(rom), 0x02000000)
    results = []
    i = search_start
    while i < search_end - 4:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        hw2 = struct.unpack_from("<H", rom, i + 2)[0]
        pc = 0x08000000 + i
        bl_target = decode_bl(hw1, hw2, pc)
        if bl_target is not None:
            if (bl_target & ~1) == (target_addr & ~1):
                results.append((i, pc))
            i += 4
        else:
            i += 2
    return results

def main():
    rom = read_rom()

    # Step 1: Find CreateTask by searching for a function that references gTasks (0x03005E00)
    # and is small, takes 2 params (task func ptr, priority), returns task ID
    print("=== Step 1: Find CreateTask ===")
    gtasks_bytes = struct.pack("<I", 0x03005E00)

    # Find all literal pool entries for gTasks
    pos = 0
    gtasks_locations = []
    while True:
        idx = rom.find(gtasks_bytes, pos, 0x02000000)
        if idx == -1:
            break
        gtasks_locations.append(idx)
        pos = idx + 4

    print(f"  Found {len(gtasks_locations)} literal pool entries for gTasks")

    # Find functions that are SMALL and reference gTasks near start
    # CreateTask should be called from many places
    # Strategy: find all functions with gTasks in their literal pool within first 80 bytes
    create_task_candidates = []
    for pool_off in gtasks_locations:
        # Search backwards for PUSH instruction
        for back in range(4, 120, 2):
            if pool_off - back < 0:
                break
            hw = struct.unpack_from("<H", rom, pool_off - back)[0]
            if (hw & 0xFF00) == 0xB500 or (hw & 0xFE00) == 0xB400:
                func_start = pool_off - back
                func_addr = 0x08000000 + func_start
                # Count callers
                # Only check a few common callers
                test_callers = find_all_bl_to(rom, func_addr | 1, 0x030000, 0x100000)
                if len(test_callers) > 20:  # CreateTask is called VERY frequently
                    create_task_candidates.append((func_start, func_addr, len(test_callers)))
                break

    create_task_candidates.sort(key=lambda x: -x[2])
    print("  Top CreateTask candidates (by caller count):")
    for off, addr, count in create_task_candidates[:5]:
        print(f"    ROM 0x{off:06X} (0x{addr:08X}): {count} callers in battle region")

    if create_task_candidates:
        create_task_addr = create_task_candidates[0][1]
        print(f"\n  BEST CANDIDATE: CreateTask = 0x{create_task_addr:08X}")
    else:
        print("  No candidates found!")
        return

    # Step 2: Find HandleLinkBattleSetup - checks gBattleTypeFlags & 2, calls CreateTask
    print(f"\n=== Step 2: Find HandleLinkBattleSetup ===")
    print(f"  Looking for function that: loads gBattleTypeFlags (0x02023364), calls CreateTask (0x{create_task_addr:08X})")

    btf_bytes = struct.pack("<I", 0x02023364)
    btf_locations = []
    pos = 0
    while True:
        idx = rom.find(btf_bytes, pos, 0x02000000)
        if idx == -1:
            break
        btf_locations.append(idx)
        pos = idx + 4

    print(f"  Found {len(btf_locations)} literal pool entries for gBattleTypeFlags")

    # For each gBattleTypeFlags literal, find the containing function and check if it calls CreateTask
    found_hlbs = []
    for pool_off in btf_locations:
        # Find function start
        func_start = None
        for back in range(4, 300, 2):
            if pool_off - back < 0:
                break
            hw = struct.unpack_from("<H", rom, pool_off - back)[0]
            if (hw & 0xFF00) == 0xB500 or (hw & 0xFE00) == 0xB400:
                func_start = pool_off - back
                break

        if func_start is None:
            continue

        # Check if this function calls CreateTask
        func_size = pool_off - func_start + 20  # rough
        has_create_task = False
        bl_list = []
        i = 0
        while i < func_size + 50:
            if func_start + i + 4 > len(rom):
                break
            hw1 = struct.unpack_from("<H", rom, func_start + i)[0]
            hw2 = struct.unpack_from("<H", rom, func_start + i + 2)[0]
            pc = 0x08000000 + func_start + i
            bl = decode_bl(hw1, hw2, pc)
            if bl is not None:
                bl_list.append((i, bl))
                if (bl & ~1) == (create_task_addr & ~1):
                    has_create_task = True
                i += 4
            else:
                i += 2

        if has_create_task and func_size < 150:
            func_addr = 0x08000000 + func_start
            callers = find_all_bl_to(rom, func_addr | 1, 0x060000, 0x0A0000)
            found_hlbs.append((func_start, func_addr, func_size, bl_list, callers))

    print(f"\n  Found {len(found_hlbs)} functions loading gBattleTypeFlags AND calling CreateTask (size < 150):\n")
    for fs, fa, fsize, bls, callers in found_hlbs:
        print(f"  ROM 0x{fs:06X} (0x{fa:08X}), ~{fsize} bytes, {len(bls)} BLs, {len(callers)} callers in battle region")
        for bi, bt in bls:
            marker = " <-- CreateTask!" if (bt & ~1) == (create_task_addr & ~1) else ""
            print(f"    +0x{bi:03X}: BL 0x{bt:08X}{marker}")
        for co, cpc in callers:
            print(f"    Called from: ROM 0x{co:06X} (0x{cpc:08X})")

    # Step 3: Also try to find CreateTasksForSendRecvLinkBuffers
    # It calls CreateTask twice and references gTasks for task data setup
    print(f"\n=== Step 3: Find CreateTasksForSendRecvLinkBuffers ===")
    print(f"  Looking for function with TWO BL to CreateTask (0x{create_task_addr:08X})")

    # Search around battle controller code area
    i = 0x060000
    while i < 0x200000:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        if (hw1 & 0xFF00) == 0xB500 or (hw1 & 0xFE00) == 0xB400:
            # Potential function start. Scan next 100 bytes for CreateTask calls
            ct_count = 0
            bl_offsets = []
            j = 0
            while j < 100:
                if i + j + 4 > len(rom):
                    break
                h1 = struct.unpack_from("<H", rom, i + j)[0]
                h2 = struct.unpack_from("<H", rom, i + j + 2)[0]
                pc = 0x08000000 + i + j
                bl = decode_bl(h1, h2, pc)
                if bl is not None:
                    if (bl & ~1) == (create_task_addr & ~1):
                        ct_count += 1
                        bl_offsets.append(j)
                    j += 4
                else:
                    j += 2

            if ct_count >= 2:
                func_addr = 0x08000000 + i
                # Check if this small function also references gTasks in its literal pool
                has_gtasks = False
                for k in range(i, min(i + 200, len(rom) - 4), 4):
                    if struct.unpack_from("<I", rom, k)[0] == 0x03005E00:
                        has_gtasks = True
                        break

                if has_gtasks:
                    callers = find_all_bl_to(rom, func_addr | 1, 0x060000, 0x200000)
                    print(f"  ROM 0x{i:06X} (0x{func_addr:08X}): {ct_count} CreateTask calls at offsets {bl_offsets}")
                    print(f"    Has gTasks ref: {has_gtasks}, Callers: {len(callers)}")
                    for co, cpc in callers:
                        print(f"    Called from ROM 0x{co:06X} (0x{cpc:08X})")
        i += 2

if __name__ == "__main__":
    main()
