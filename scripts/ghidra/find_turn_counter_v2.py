#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v2

gBattleTurnCounter has only 3 source usages:
  1. EWRAM_DATA u16 gBattleTurnCounter = 0;  (declaration)
  2. gBattleTurnCounter = 0;  (in TryDoEventsBeforeFirstTurn, line 3809)
  3. gBattleTurnCounter++;    (in BattleTurnPassed, battle_end_turn.c:32)

So it should have very FEW ROM literal pool refs (maybe 3-6).
The ++ compiles to: LDR Rx, =addr; LDRH Ry, [Rx]; ADD Ry, #1; STRH Ry, [Rx]
The = 0 compiles to: LDR Rx, =addr; MOV Ry, #0; STRH Ry, [Rx]

Strategy: Search for u16 addresses with 3-10 refs in the expected range,
that show the increment pattern.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000


def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def find_all_refs(rom_data, target_value):
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs

def find_function_start(rom_data, offset):
    for back in range(2, 4096, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in (0xB400, 0xB500):
            return pos
    return None

def get_ewram_addrs_in_function(rom_data, func_start, max_size=8192):
    results = set()
    end = min(func_start + max_size, len(rom_data) - 3)
    pos = func_start
    pop_count = 0
    while pos < end:
        instr = read_u16_le(rom_data, pos)
        if pos > func_start + 4 and (instr & 0xFF00) == 0xBD00:
            pop_count += 1
            if pop_count >= 2:
                break
        if (instr & 0xF800) == 0x4800:
            imm8 = instr & 0xFF
            pc = ROM_BASE + pos
            pool_addr = ((pc + 4) & ~3) + imm8 * 4
            file_off = pool_addr - ROM_BASE
            if 0 <= file_off < len(rom_data) - 3:
                val = read_u32_le(rom_data, file_off)
                if 0x02000000 <= val < 0x02040000:
                    results.add(val)
        pos += 2
    return results


def check_increment_pattern(rom_data, target_addr):
    """Check if any reference to target_addr shows LDRH + ADD #1 + STRH pattern."""
    target_bytes = struct.pack('<I', target_addr)
    found = []

    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] != target_bytes:
            continue
        pool_rom_addr = ROM_BASE + i

        # Find LDR instructions that reference this pool entry
        for scan_off in range(max(0, i - 1024), i, 2):
            instr = read_u16_le(rom_data, scan_off)
            if (instr & 0xF800) != 0x4800:
                continue
            pc = ROM_BASE + scan_off
            pool_calc = ((pc + 4) & ~3) + (instr & 0xFF) * 4
            if pool_calc != pool_rom_addr:
                continue

            rd = (instr >> 8) & 7

            # Check next 6 instructions for LDRH+ADD#1+STRH pattern
            for ci in range(scan_off + 2, min(scan_off + 14, len(rom_data) - 5), 2):
                ci_instr = read_u16_le(rom_data, ci)
                # LDRH Rx, [Rd, #0]
                if (ci_instr & 0xFFC7) != (0x8800 | (rd << 3)):
                    continue
                rx = ci_instr & 7
                ni = read_u16_le(rom_data, ci + 2)
                # ADD Rx, #1
                if ni != (0x3000 | (rx << 8) | 1):
                    # Also check ADDS Rx, Rx, #1 (0x1C40 + rx encoding)
                    # ADDS Rd, Rs, #1: 0001 110 imm3 Rs Rd => 0x1C00 | (1<<6) | (rx<<3) | rx
                    expected_adds = 0x1C40 | (rx << 3) | rx
                    if ni != expected_adds:
                        continue
                si = read_u16_le(rom_data, ci + 4)
                # STRH Rx, [Rd, #0]
                if si == (0x8000 | (rd << 3) | rx):
                    found.append(ROM_BASE + scan_off)

    return found

def check_store_zero_pattern(rom_data, target_addr):
    """Check if any reference shows MOV #0 + STRH pattern."""
    target_bytes = struct.pack('<I', target_addr)
    found = []

    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] != target_bytes:
            continue
        pool_rom_addr = ROM_BASE + i

        for scan_off in range(max(0, i - 1024), i, 2):
            instr = read_u16_le(rom_data, scan_off)
            if (instr & 0xF800) != 0x4800:
                continue
            pc = ROM_BASE + scan_off
            pool_calc = ((pc + 4) & ~3) + (instr & 0xFF) * 4
            if pool_calc != pool_rom_addr:
                continue

            rd = (instr >> 8) & 7

            # Check next 4 instructions for STRH with value 0
            for ci in range(scan_off + 2, min(scan_off + 10, len(rom_data) - 1), 2):
                ci_instr = read_u16_le(rom_data, ci)
                # STRH Rx, [Rd, #0] where we know a MOV Rx, #0 happened before
                if (ci_instr & 0xFE3F) == (0x8000 | (rd << 3)):
                    rx = ci_instr & 7
                    # Check if Rx was set to 0 before
                    for pi in range(scan_off, ci, 2):
                        pi_instr = read_u16_le(rom_data, pi)
                        if pi_instr == (0x2000 | (rx << 8)):  # MOV Rx, #0
                            found.append(ROM_BASE + scan_off)
                            break

    return found


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    # Known confirmed addresses
    confirmed = {
        "gBattlerByTurnOrder":    0x020233F6,
        "gChosenActionByBattler": 0x02023598,
        "gChosenMoveByBattler":   0x020235FA,
    }

    # =========================================================================
    # Scan range 0x02023900-0x02023A00 for addresses with 2-10 refs
    # that show increment pattern
    # =========================================================================
    print("=" * 78)
    print("  Scanning 0x02023900-0x02023A00 for u16 addresses with 2-10 refs")
    print("=" * 78)
    print()

    candidates = []
    for addr in range(0x02023900, 0x02023A00, 2):  # u16 = 2-aligned
        refs = find_all_refs(rom_data, addr)
        count = len(refs)
        if 2 <= count <= 10:
            candidates.append((addr, count))
            print(f"    0x{addr:08X}: {count} refs")

    print(f"\n  Total candidates: {len(candidates)}")
    print()

    # =========================================================================
    # Check each candidate for increment pattern
    # =========================================================================
    print("=" * 78)
    print("  Checking increment pattern (LDRH + ADD #1 + STRH)")
    print("=" * 78)
    print()

    for addr, count in candidates:
        inc_hits = check_increment_pattern(rom_data, addr)
        if inc_hits:
            print(f"  *** 0x{addr:08X} ({count} refs): INCREMENT pattern at {', '.join(f'0x{h:08X}' for h in inc_hits)}")

            # Also check store-zero pattern
            zero_hits = check_store_zero_pattern(rom_data, addr)
            if zero_hits:
                print(f"      Also has STORE ZERO pattern at {', '.join(f'0x{h:08X}' for h in zero_hits)}")

            # Check which confirmed vars are in the same functions
            for ref_off_file in find_all_refs(rom_data, addr):
                fs = find_function_start(rom_data, ref_off_file)
                if fs is None:
                    continue
                func_ewram = get_ewram_addrs_in_function(rom_data, fs, 8192)
                co_vars = []
                for name, va in confirmed.items():
                    if va in func_ewram:
                        co_vars.append(name)
                if co_vars:
                    print(f"      In func 0x{ROM_BASE+fs+1:08X}: also refs {', '.join(co_vars)}")
            print()

    # =========================================================================
    # Also broaden to 0x02023800-0x02023900
    # =========================================================================
    print("=" * 78)
    print("  Also scanning 0x02023800-0x02023900 for u16 with 2-10 refs + increment")
    print("=" * 78)
    print()

    for addr in range(0x02023800, 0x02023900, 2):
        refs = find_all_refs(rom_data, addr)
        count = len(refs)
        if 2 <= count <= 10:
            inc_hits = check_increment_pattern(rom_data, addr)
            if inc_hits:
                print(f"  *** 0x{addr:08X} ({count} refs): INCREMENT at {', '.join(f'0x{h:08X}' for h in inc_hits)}")

    print()

    # =========================================================================
    # Try wider search: 1-15 refs
    # =========================================================================
    print("=" * 78)
    print("  Wider search: 0x02023800-0x02023A18, 1-15 refs, increment pattern")
    print("=" * 78)
    print()

    for addr in range(0x02023800, 0x02023A18, 2):
        refs = find_all_refs(rom_data, addr)
        count = len(refs)
        if 1 <= count <= 15:
            inc_hits = check_increment_pattern(rom_data, addr)
            if inc_hits:
                zero_hits = check_store_zero_pattern(rom_data, addr)
                marker = " + STORE_ZERO" if zero_hits else ""
                print(f"  *** 0x{addr:08X} ({count} refs): INCREMENT{marker}")

    print()
    print("  Done.")


if __name__ == "__main__":
    main()
