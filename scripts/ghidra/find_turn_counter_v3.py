#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v3

Broader increment pattern search. The compiler might generate:
  LDR R2, =addr
  LDRH R0, [R2]      or  LDRH R0, [R2, #0]
  ADDS R0, R0, #1    or  ADD R0, #1  or  ADDS R0, #1
  STRH R0, [R2]      or  STRH R0, [R2, #0]

Or even:
  LDR R2, =addr
  LDRH R1, [R2]
  ADD R0, R1, #1
  STRH R0, [R2]

Check ALL EWRAM addresses with 1-20 refs in the expected range.
"""

import struct
import sys
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


def check_all_increment_patterns(rom_data, target_addr):
    """
    Exhaustively check for any halfword increment pattern:
    LDR Rd, =addr; ... LDRH Rx, [Rd, #0]; ... (add 1 somehow) ...; STRH Ry, [Rd, #0]
    within 12 instructions of the LDR.
    """
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

            rd = (instr >> 8) & 7  # Register holding the address

            # Collect next 12 instructions
            instrs = []
            for ci in range(scan_off + 2, min(scan_off + 26, len(rom_data) - 1), 2):
                instrs.append((ci, read_u16_le(rom_data, ci)))

            # Look for LDRH Rx, [Rd, #0] followed later by STRH Ry, [Rd, #0]
            for j, (ci, ci_instr) in enumerate(instrs):
                # LDRH Rx, [Rd, #0] = 0x8800 | (Rd << 3) | Rx
                if (ci_instr & 0xFFC7) != (0x8800 | (rd << 3)):
                    continue
                rx = ci_instr & 7

                # Look for ADD to rx (or any reg) then STRH back
                for k in range(j + 1, min(j + 5, len(instrs))):
                    ki, ki_instr = instrs[k]

                    # Check if this is an add-by-1 in any form
                    is_add1 = False
                    add_dest = -1

                    # ADD Rx, #1: 0x3000 | (Rx << 8) | 1
                    if ki_instr == (0x3000 | (rx << 8) | 1):
                        is_add1 = True
                        add_dest = rx

                    # ADDS Rd, Rs, #1: 0001 110 001 Rs Rd = 0x1C40 | (Rs << 3) | Rd
                    for dst in range(8):
                        if ki_instr == (0x1C40 | (rx << 3) | dst):
                            is_add1 = True
                            add_dest = dst
                            break

                    if not is_add1:
                        continue

                    # Now look for STRH add_dest, [Rd, #0]
                    for m in range(k + 1, min(k + 3, len(instrs))):
                        mi, mi_instr = instrs[m]
                        if mi_instr == (0x8000 | (rd << 3) | add_dest):
                            found.append(ROM_BASE + scan_off)

    return found


def check_store_zero(rom_data, target_addr):
    """Check for MOV #0 + STRH pattern."""
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

            # Check next 6 instructions
            instrs = []
            for ci in range(scan_off + 2, min(scan_off + 14, len(rom_data) - 1), 2):
                instrs.append((ci, read_u16_le(rom_data, ci)))

            # Look for STRH Rx, [Rd, #0] where Rx was set to 0
            zero_regs = set()
            for ci, ci_instr in instrs:
                # MOV Rx, #0
                if (ci_instr & 0xFF00) == 0x2000 and (ci_instr & 0xFF) == 0:
                    zero_regs.add((ci_instr >> 8) & 7)
                # STRH Rx, [Rd, #0]
                if (ci_instr & 0xFFC7) == (0x8000 | (rd << 3)):
                    rx = ci_instr & 7
                    if rx in zero_regs:
                        found.append(ROM_BASE + scan_off)

    return found


def disasm_around(rom_data, file_off, before=4, after=8):
    """Disassemble a few instructions around a file offset."""
    lines = []
    start = max(0, file_off - before * 2)
    for pos in range(start, min(file_off + after * 2, len(rom_data) - 1), 2):
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        marker = " >>>" if pos == file_off else "    "
        desc = f"0x{instr:04X}"

        if (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            pool_addr = ((rom_addr + 4) & ~3) + imm8 * 4
            pf = pool_addr - ROM_BASE
            if 0 <= pf < len(rom_data) - 3:
                val = read_u32_le(rom_data, pf)
                desc = f"LDR R{rd}, [PC, #0x{imm8*4:X}] (=0x{val:08X})"
        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7; rb = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rb}, #0x{imm:X}]"
        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7; rb = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            desc = f"STRH R{rd}, [R{rb}, #0x{imm:X}]"
        elif (instr & 0xFF00) == 0x3000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"ADD R{rd}, #0x{imm:X}"
        elif (instr & 0xFF00) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"MOV R{rd}, #0x{imm:X}"
        elif (instr & 0xFFC0) == 0x1C40:
            rd = instr & 7; rs = (instr >> 3) & 7
            desc = f"ADDS R{rd}, R{rs}, #1"

        lines.append(f"{marker} {rom_addr:08X}: {instr:04X}  {desc}")
    return "\n".join(lines)


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    # =========================================================================
    # Scan 0x02023700-0x02023A18 for addresses with ANY increment pattern
    # =========================================================================
    print("=" * 78)
    print("  Scanning for u16 EWRAM addresses with LDRH+ADD1+STRH pattern")
    print("  Range: 0x02023700-0x02023A18")
    print("=" * 78)
    print()

    for addr in range(0x02023700, 0x02023A18, 2):
        refs = find_all_refs(rom_data, addr)
        count = len(refs)
        if count == 0:
            continue

        inc_hits = check_all_increment_patterns(rom_data, addr)
        if inc_hits:
            zero_hits = check_store_zero(rom_data, addr)
            zero_marker = " + STORE_ZERO" if zero_hits else ""
            print(f"  *** 0x{addr:08X} ({count} refs): INCREMENT pattern found{zero_marker}")
            for hit in inc_hits:
                file_off = hit - ROM_BASE
                print(disasm_around(rom_data, file_off))
                print()

    # =========================================================================
    # Also check wider range including before gBattleCommunication
    # =========================================================================
    print("=" * 78)
    print("  Also scanning 0x02023600-0x02023700")
    print("=" * 78)
    print()

    for addr in range(0x02023600, 0x02023700, 2):
        refs = find_all_refs(rom_data, addr)
        count = len(refs)
        if count == 0:
            continue

        inc_hits = check_all_increment_patterns(rom_data, addr)
        if inc_hits:
            print(f"  *** 0x{addr:08X} ({count} refs): INCREMENT pattern found")
            for hit in inc_hits:
                file_off = hit - ROM_BASE
                print(disasm_around(rom_data, file_off))
                print()


if __name__ == "__main__":
    main()
