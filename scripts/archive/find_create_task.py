#!/usr/bin/env python3
"""
Find CreateTask in the ROM. It references gTasks (0x03005E00) and is called from MANY places.
Then find HandleLinkBattleSetup which checks gBattleTypeFlags and calls CreateTask.
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

def count_callers_fast(rom, target_addr, max_search=0x400000):
    """Count BL callers in first max_search bytes of ROM."""
    count = 0
    i = 0
    target_clean = target_addr & ~1
    while i < min(len(rom), max_search) - 4:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        # Quick filter: BL first halfword starts with 0xF
        if (hw1 & 0xF800) == 0xF000:
            hw2 = struct.unpack_from("<H", rom, i + 2)[0]
            if (hw2 & 0xF800) in (0xF800, 0xE800):
                pc = 0x08000000 + i
                bl = decode_bl(hw1, hw2, pc)
                if bl is not None and (bl & ~1) == target_clean:
                    count += 1
                i += 4
                continue
        i += 2
    return count

def main():
    rom = read_rom()

    # Step 1: Find all potential CreateTask functions (reference gTasks 0x03005E00)
    print("=== Finding CreateTask ===")
    gtasks_bytes = struct.pack("<I", 0x03005E00)

    # Find all gTasks literal pool entries
    gtasks_locs = []
    pos = 0
    while True:
        idx = rom.find(gtasks_bytes, pos, 0x02000000)
        if idx == -1:
            break
        gtasks_locs.append(idx)
        pos = idx + 4

    print(f"  {len(gtasks_locs)} gTasks literal pool entries")

    # For each, find the containing function and count callers
    seen_funcs = set()
    candidates = []

    for pool_off in gtasks_locs:
        for back in range(4, 120, 2):
            if pool_off - back < 0:
                break
            hw = struct.unpack_from("<H", rom, pool_off - back)[0]
            if (hw & 0xFF00) == 0xB500 or (hw & 0xFE00) == 0xB400:
                func_start = pool_off - back
                if func_start in seen_funcs:
                    break
                seen_funcs.add(func_start)
                func_addr = 0x08000000 + func_start
                # Quick caller count
                count = count_callers_fast(rom, func_addr | 1)
                if count > 0:
                    candidates.append((func_start, func_addr, count))
                break

    candidates.sort(key=lambda x: -x[2])
    print(f"  {len(candidates)} unique functions referencing gTasks")
    print("  Top 10 by caller count:")
    for off, addr, count in candidates[:10]:
        print(f"    0x{addr:08X} (ROM 0x{off:06X}): {count} callers")

    # The one with most callers is likely CreateTask
    if not candidates:
        print("  ERROR: No candidates!")
        return

    create_task_addr = candidates[0][1]
    print(f"\n  CreateTask = 0x{create_task_addr:08X} ({candidates[0][2]} callers)")

    # Step 2: Search SetUpBattleVarsAndBirchZigzagoon for BL to CreateTask
    # We know this function is somewhere around 0x06F1D8
    print(f"\n=== Searching InitBattleControllers area for BL to CreateTask ===")
    func_start = 0x06F1D8
    func_end = 0x06F600  # generous
    i = func_start
    while i < func_end:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        if (hw1 & 0xF800) == 0xF000 and i + 2 < func_end:
            hw2 = struct.unpack_from("<H", rom, i + 2)[0]
            pc = 0x08000000 + i
            bl = decode_bl(hw1, hw2, pc)
            if bl is not None and (bl & ~1) == (create_task_addr & ~1):
                offset = i - func_start
                print(f"  +0x{offset:03X} (ROM 0x{i:06X}): BL CreateTask (0x{bl:08X})")
                i += 4
                continue
        i += 2

    # Step 3: Find HandleLinkBattleSetup
    # It's a small function that:
    # - loads gBattleTypeFlags, tests bit 1
    # - calls CreateTask once or more
    # - Is called from SetUpBattleVars area
    print(f"\n=== Finding HandleLinkBattleSetup ===")
    print(f"  Looking for small function with gBattleTypeFlags + CreateTask call\n")

    btf_bytes = struct.pack("<I", 0x02023364)
    btf_locs = []
    pos = 0
    while True:
        idx = rom.find(btf_bytes, pos, 0x02000000)
        if idx == -1:
            break
        btf_locs.append(idx)
        pos = idx + 4

    # For each gBattleTypeFlags pool entry, find containing function
    seen = set()
    hlbs_candidates = []

    for pool_off in btf_locs:
        for back in range(4, 300, 2):
            if pool_off - back < 0:
                break
            hw = struct.unpack_from("<H", rom, pool_off - back)[0]
            if (hw & 0xFF00) == 0xB500 or (hw & 0xFE00) == 0xB400:
                func_start = pool_off - back
                if func_start in seen:
                    break
                seen.add(func_start)

                func_size = pool_off - func_start + 20
                # Only consider small functions
                if func_size > 200:
                    break

                # Check for CreateTask call
                has_ct = False
                ct_calls = 0
                all_bls = []
                j = 0
                while j < func_size + 80:
                    if func_start + j + 4 > len(rom):
                        break
                    h1 = struct.unpack_from("<H", rom, func_start + j)[0]
                    h2 = struct.unpack_from("<H", rom, func_start + j + 2)[0]
                    fpc = 0x08000000 + func_start + j
                    fbl = decode_bl(h1, h2, fpc)
                    if fbl is not None:
                        all_bls.append((j, fbl))
                        if (fbl & ~1) == (create_task_addr & ~1):
                            has_ct = True
                            ct_calls += 1
                        j += 4
                    else:
                        # Check for POP {PC} or BX LR = end of function
                        if (h1 & 0xFF00) == 0xBD00 or h1 == 0x4770:
                            break
                        j += 2

                if has_ct:
                    func_addr = 0x08000000 + func_start
                    hlbs_candidates.append((func_start, func_addr, func_size, ct_calls, all_bls))
                break

    print(f"  Found {len(hlbs_candidates)} small functions with gBattleTypeFlags + CreateTask:\n")
    for fs, fa, fsize, ctc, bls in hlbs_candidates:
        # Check if called from InitBattleControllers area
        callers_in_ibc = []
        for ci in range(0x06F000, 0x06FA00, 2):
            if ci + 4 > len(rom):
                break
            ch1 = struct.unpack_from("<H", rom, ci)[0]
            ch2 = struct.unpack_from("<H", rom, ci + 2)[0]
            cpc = 0x08000000 + ci
            cbl = decode_bl(ch1, ch2, cpc)
            if cbl is not None and (cbl & ~1) == (fa & ~1):
                callers_in_ibc.append(ci)

        marker = " <-- CALLED FROM InitBattleControllers!" if callers_in_ibc else ""
        print(f"  ROM 0x{fs:06X} (0x{fa:08X}), ~{fsize} bytes, {ctc} CreateTask calls{marker}")
        for bi, bt in bls:
            ct_mark = " <-- CreateTask" if (bt & ~1) == (create_task_addr & ~1) else ""
            print(f"    +0x{bi:03X}: BL 0x{bt:08X}{ct_mark}")
        for ci in callers_in_ibc:
            offset_from_ibc = ci - 0x06F1D8
            print(f"    Called from InitBattleControllers+0x{offset_from_ibc:03X} (ROM 0x{ci:06X})")

if __name__ == "__main__":
    main()
