#!/usr/bin/env python3
"""
Verify gBattleTurnCounter address candidates by disassembling key functions.

The function at 0x08039CBB is a STRONG MATCH — it references all confirmed battle
variables AND the candidate 0x02023958. Let's disassemble it to find the
"gBattleTurnCounter = 0" pattern (LDR + MOV #0 + STRH).

Also check 0x0803BC21 which references candidate 0x02023960.
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


def disasm_thumb(rom_data, start_file_off, count=200, known_addrs=None):
    """Simple THUMB disassembler, annotating LDR pool values."""
    if known_addrs is None:
        known_addrs = {}

    pos = start_file_off
    lines = []
    for _ in range(count):
        if pos + 1 >= len(rom_data):
            break
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        decoded = f"0x{instr:04X}"

        # Decode common instructions
        if (instr & 0xFF00) in (0xB400, 0xB500):
            regs = []
            for i in range(8):
                if instr & (1 << i):
                    regs.append(f"R{i}")
            if instr & 0x100:
                regs.append("LR" if (instr & 0xFF00) == 0xB500 else "R8")
            decoded = f"PUSH {{{', '.join(regs)}}}"

        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = []
            for i in range(8):
                if instr & (1 << i):
                    regs.append(f"R{i}")
            if instr & 0x100:
                regs.append("PC" if (instr & 0xFF00) == 0xBD00 else "R8")
            decoded = f"POP {{{', '.join(regs)}}}"

        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            pool_addr = ((rom_addr + 4) & ~3) + imm8 * 4
            pool_file_off = pool_addr - ROM_BASE
            if 0 <= pool_file_off < len(rom_data) - 3:
                val = read_u32_le(rom_data, pool_file_off)
                name = known_addrs.get(val, "")
                if name:
                    name = f"  <-- {name}"
                decoded = f"LDR R{rd}, [PC, #0x{imm8*4:X}] (=0x{val:08X}){name}"
            else:
                decoded = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"

        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            decoded = f"MOV R{rd}, #0x{imm:X} ({imm})"

        elif instr == 0x4770:
            decoded = "BX LR"

        elif (instr & 0xFFC0) == 0x4680:
            rd = ((instr >> 4) & 8) | (instr & 7)
            rm = (instr >> 3) & 0xF
            decoded = f"MOV R{rd}, R{rm}"

        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7
            rb = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 2
            decoded = f"STRH R{rd}, [R{rb}, #0x{imm:X}]"

        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7
            rb = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 2
            decoded = f"LDRH R{rd}, [R{rb}, #0x{imm:X}]"

        elif (instr & 0xFE00) == 0x6000:
            rd = instr & 7
            rb = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 4
            decoded = f"STR R{rd}, [R{rb}, #0x{imm:X}]"

        elif (instr & 0xFE00) == 0x6800:
            rd = instr & 7
            rb = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 4
            decoded = f"LDR R{rd}, [R{rb}, #0x{imm:X}]"

        elif (instr & 0xFE00) == 0x7000:
            rd = instr & 7
            rb = (instr >> 3) & 7
            imm = (instr >> 6) & 0x1F
            decoded = f"STRB R{rd}, [R{rb}, #0x{imm:X}]"

        elif (instr & 0xFE00) == 0x7800:
            rd = instr & 7
            rb = (instr >> 3) & 7
            imm = (instr >> 6) & 0x1F
            decoded = f"LDRB R{rd}, [R{rb}, #0x{imm:X}]"

        elif (instr & 0xFF00) == 0x3000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            decoded = f"ADD R{rd}, #0x{imm:X}"

        elif (instr & 0xFF00) == 0x3800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            decoded = f"SUB R{rd}, #0x{imm:X}"

        elif (instr & 0xFFC0) == 0x1C00:
            rd = instr & 7
            rs = (instr >> 3) & 7
            imm = (instr >> 6) & 7
            decoded = f"ADD R{rd}, R{rs}, #0x{imm:X}"

        elif (instr & 0xF800) == 0xE000:
            off = instr & 0x7FF
            if off >= 0x400:
                off -= 0x800
            target = rom_addr + 4 + off * 2
            decoded = f"B 0x{target:08X}"

        elif (instr & 0xF000) == 0xD000:
            cond_code = (instr >> 8) & 0xF
            cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                          "BHI","BLS","BGE","BLT","BGT","BLE","???","SWI"]
            off = instr & 0xFF
            if off >= 0x80:
                off -= 0x100
            target = rom_addr + 4 + off * 2
            decoded = f"{cond_names[cond_code]} 0x{target:08X}"

        elif (instr & 0xFFC0) == 0x4280:
            rn = instr & 7
            rm = (instr >> 3) & 7
            decoded = f"CMP R{rn}, R{rm}"

        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7
            imm = instr & 0xFF
            decoded = f"CMP R{rn}, #0x{imm:X}"

        # BL pair
        elif (instr & 0xF800) == 0xF000:
            if pos + 2 < len(rom_data):
                next_instr = read_u16_le(rom_data, pos + 2)
                if (next_instr & 0xF800) == 0xF800:
                    off11hi = instr & 0x07FF
                    off11lo = next_instr & 0x07FF
                    full_off = (off11hi << 12) | (off11lo << 1)
                    if full_off >= 0x400000:
                        full_off -= 0x800000
                    target = rom_addr + 4 + full_off
                    decoded = f"BL 0x{target:08X}"
                    lines.append(f"  {rom_addr:08X}:  {instr:04X} {next_instr:04X}  {decoded}")
                    pos += 4
                    continue

        lines.append(f"  {rom_addr:08X}:  {instr:04X}        {decoded}")
        pos += 2

    return lines


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    known = {
        0x020233F6: "gBattlerByTurnOrder",
        0x02023598: "gChosenActionByBattler",
        0x020235FA: "gChosenMoveByBattler",
        0x0202370E: "gBattleCommunication",
        0x020233E4: "gBattlersCount",
        0x020233FC: "gBattleMons",
        0x020233DC: "gActiveBattler",
        0x02023364: "gBattleTypeFlags",
        0x020233E0: "gBattleControllerExecFlags",
        0x020233EE: "gBattlerPositions",
        0x020233F2: "gActionsByTurnOrder",
        0x020233E6: "gBattlerPartyIndexes",
        0x020233FA: "gCurrentTurnActionNumber",
        0x020233FB: "gCurrentActionFuncId",
        0x02023958: "gBattleTurnCounter?",
        0x02023960: "gBattleTurnCounter??",
        0x0202395A: "gBattlerAbility?",
        0x02023A18: "gBattleResources",
        0x02023A0C: "gBattleSpritesDataPtr?",
        0x020239D0: "gBattleStruct?",
        0x0202356C: "gBattlerSpriteIds",
        0x02023594: "gBattlescriptCurrInstr",
        0x0202359C: "gBattlerAttacker",
    }

    # =========================================================================
    # Disassemble the STRONG MATCH function at 0x08039CBB
    # (which references gBattlerByTurnOrder + gChosenActionByBattler + 0x02023958)
    # This is likely TryDoEventsBeforeFirstTurn or a related function
    # =========================================================================
    print("=" * 78)
    print("  Disassembly of function at 0x08039CBB (STRONG MATCH for 0x02023958)")
    print("  Looking for: LDR Rx, =gBattleTurnCounter; MOV Ry, #0; STRH Ry, [Rx]")
    print("=" * 78)
    print()

    # The function starts at file offset 0x39CBA (0x08039CBB - 0x08000001)
    func_start = 0x39CBA
    lines = disasm_thumb(rom_data, func_start, 300, known)
    for line in lines:
        print(line)

    print()
    print("  (showing first 300 instructions)")
    print()

    # =========================================================================
    # Also check 0x0803BC21 (STRONG MATCH for 0x02023960)
    # =========================================================================
    print("=" * 78)
    print("  Disassembly of function at 0x0803BC21 (STRONG MATCH for 0x02023960)")
    print("=" * 78)
    print()

    func_start2 = 0x3BC20
    lines2 = disasm_thumb(rom_data, func_start2, 300, known)
    for line in lines2:
        print(line)

    print()

    # =========================================================================
    # Check the 0x02023958 store pattern in all functions
    # =========================================================================
    print("=" * 78)
    print("  Searching ROM for 'store 0 to 0x02023958' pattern")
    print("=" * 78)
    print()

    # Find all LDR Rx, [PC, #nn] that load 0x02023958
    target_bytes = struct.pack('<I', 0x02023958)
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            # This is a literal pool entry at file offset i
            pool_rom_addr = ROM_BASE + i
            # Find which LDR instruction refers to this pool entry
            # Search backward for LDR Rx, [PC, #nn] instructions
            for scan_off in range(max(0, i - 1024), i, 2):
                instr = read_u16_le(rom_data, scan_off)
                if (instr & 0xF800) == 0x4800:
                    pc = ROM_BASE + scan_off
                    pool_calc = ((pc + 4) & ~3) + (instr & 0xFF) * 4
                    if pool_calc == pool_rom_addr:
                        # Found the LDR instruction. Check next few instructions for STRH with #0
                        rd = (instr >> 8) & 7
                        # Look at the 5 instructions after this LDR
                        context = disasm_thumb(rom_data, scan_off, 8, known)
                        has_store_zero = False
                        for ci in range(scan_off + 2, min(scan_off + 12, len(rom_data) - 1), 2):
                            ci_instr = read_u16_le(rom_data, ci)
                            # STRH Rx, [Ry, #0] where Ry is the register that was loaded
                            if (ci_instr & 0xFE00) == 0x8000:
                                rb = (ci_instr >> 3) & 7
                                imm = ((ci_instr >> 6) & 0x1F) * 2
                                if rb == rd and imm == 0:
                                    has_store_zero = True
                        if has_store_zero:
                            print(f"  ** FOUND store-to-0x02023958 pattern at 0x{ROM_BASE+scan_off:08X}:")
                            for line in context:
                                print(f"  {line}")
                            print()

    # Same for 0x02023960
    print()
    print("  Searching ROM for 'store 0 to 0x02023960' pattern")
    print()

    target_bytes2 = struct.pack('<I', 0x02023960)
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes2:
            pool_rom_addr = ROM_BASE + i
            for scan_off in range(max(0, i - 1024), i, 2):
                instr = read_u16_le(rom_data, scan_off)
                if (instr & 0xF800) == 0x4800:
                    pc = ROM_BASE + scan_off
                    pool_calc = ((pc + 4) & ~3) + (instr & 0xFF) * 4
                    if pool_calc == pool_rom_addr:
                        rd = (instr >> 8) & 7
                        context = disasm_thumb(rom_data, scan_off, 8, known)
                        has_store_zero = False
                        for ci in range(scan_off + 2, min(scan_off + 12, len(rom_data) - 1), 2):
                            ci_instr = read_u16_le(rom_data, ci)
                            if (ci_instr & 0xFE00) == 0x8000:
                                rb = (ci_instr >> 3) & 7
                                imm = ((ci_instr >> 6) & 0x1F) * 2
                                if rb == rd and imm == 0:
                                    has_store_zero = True
                        if has_store_zero:
                            print(f"  ** FOUND store-to-0x02023960 pattern at 0x{ROM_BASE+scan_off:08X}:")
                            for line in context:
                                print(f"  {line}")
                            print()

    # =========================================================================
    # Check increment pattern (gBattleTurnCounter++)
    # =========================================================================
    print()
    print("=" * 78)
    print("  Searching for increment pattern (LDRH + ADD #1 + STRH)")
    print("=" * 78)
    print()

    for candidate_addr, name in [(0x02023958, "candidate_0x958"), (0x02023960, "candidate_0x960")]:
        target_bytes_c = struct.pack('<I', candidate_addr)
        inc_count = 0
        for i in range(0, len(rom_data) - 3, 4):
            if rom_data[i:i+4] == target_bytes_c:
                pool_rom_addr = ROM_BASE + i
                for scan_off in range(max(0, i - 1024), i, 2):
                    instr = read_u16_le(rom_data, scan_off)
                    if (instr & 0xF800) == 0x4800:
                        pc = ROM_BASE + scan_off
                        pool_calc = ((pc + 4) & ~3) + (instr & 0xFF) * 4
                        if pool_calc == pool_rom_addr:
                            rd = (instr >> 8) & 7
                            # Check for LDRH [Rd, #0] + ADD #1 + STRH [Rd, #0]
                            for ci in range(scan_off + 2, min(scan_off + 16, len(rom_data) - 3), 2):
                                ci_instr = read_u16_le(rom_data, ci)
                                # LDRH Rx, [Rd, #0]
                                if (ci_instr & 0xFFC7) == (0x8800 | (rd << 3)):
                                    rx = ci_instr & 7
                                    # Check next for ADD Rx, #1
                                    if ci + 2 < len(rom_data):
                                        ni = read_u16_le(rom_data, ci + 2)
                                        if ni == (0x3000 | (rx << 8) | 1):
                                            # Check for STRH Rx, [Rd, #0]
                                            if ci + 4 < len(rom_data):
                                                si = read_u16_le(rom_data, ci + 4)
                                                if si == (0x8000 | (rd << 3) | rx):
                                                    inc_count += 1
                                                    context = disasm_thumb(rom_data, scan_off, 8, known)
                                                    print(f"  ** {name}: increment pattern at 0x{ROM_BASE+scan_off:08X}")
                                                    for line in context:
                                                        print(f"    {line}")
                                                    print()

        if inc_count == 0:
            print(f"  {name}: no increment pattern found")
            print()


if __name__ == "__main__":
    main()
