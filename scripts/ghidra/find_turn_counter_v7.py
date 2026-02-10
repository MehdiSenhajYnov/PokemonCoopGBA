#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v7: Disassemble around 0x08057980 call site

The call at 0x08057980 (BL SortBattlersBySpeed) has BOTH gBattlerByTurnOrder AND
gBattlersCount nearby, making it the likely inlined HandleEndTurnOrder.

HandleEndTurnOrder does (in order):
  1. gBattleTurnCounter++
  2. gBattleStruct->eventState.endTurn++
  3. for (i = 0; i < gBattlersCount; i++) gBattlerByTurnOrder[i] = i;
  4. SortBattlersBySpeed(gBattlerByTurnOrder, FALSE);

The increment should be 30-100 bytes BEFORE the BL SortBattlersBySpeed.
The compiler may use:
  - Direct literal pool: LDR Rx, =addr; LDRH Ry, [Rx]; ADD Ry,#1; STRH Ry,[Rx]
  - gBattleStruct relative: LDR Rx, =gBattleResources; LDR Rx,[Rx]; LDR Rx,[Rx];
    LDRH Ry,[Rx,#off]; ADD Ry,#1; STRH Ry,[Rx,#off]

Also search ALL 189 SortBattlersBySpeed call sites for ANY LDRH+ADD+STRH pattern
within 200 bytes before the call.
"""

import struct
import sys
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

KNOWN = {
    0x020233F6: "gBattlerByTurnOrder",
    0x020233F2: "gActionsByTurnOrder",
    0x02023598: "gChosenActionByBattler",
    0x020235FA: "gChosenMoveByBattler",
    0x0202370E: "gBattleCommunication",
    0x020233E4: "gBattlersCount",
    0x020233FC: "gBattleMons",
    0x020233DC: "gActiveBattler",
    0x02023364: "gBattleTypeFlags",
    0x020233E0: "gBattleControllerExecFlags",
    0x020233EE: "gBattlerPositions",
    0x020233E6: "gBattlerPartyIndexes",
    0x020233FA: "gCurrentTurnActionNumber",
    0x020233FB: "gCurrentActionFuncId",
    0x02023A18: "gBattleResources",
    0x0202356C: "gBattlerSpriteIds",
    0x02023594: "gBattlescriptCurrInstr",
    0x0202359C: "gBattlerAttacker",
    0x020239D0: "gBattleStruct",
    0x02023A0C: "gBattleSpritesDataPtr",
    0x02023708: "gPauseCounterBattle?",
}


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


def disasm(rom_data, start, count, known):
    lines = []
    pos = start
    for _ in range(count):
        if pos + 1 >= len(rom_data):
            break
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        desc = f"0x{instr:04X}"
        extra = ""

        if (instr & 0xFF00) in (0xB400, 0xB500):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100: regs.append("LR" if (instr & 0xFF00) == 0xB500 else "R8")
            desc = f"PUSH {{{', '.join(regs)}}}"
            extra = " <<<FUNC_START"
        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100: regs.append("PC" if (instr & 0xFF00) == 0xBD00 else "R8")
            desc = f"POP {{{', '.join(regs)}}}"
            if "PC" in regs: extra = " <<<FUNC_RETURN"
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            pool_addr = ((rom_addr + 4) & ~3) + imm8 * 4
            pf = pool_addr - ROM_BASE
            if 0 <= pf < len(rom_data) - 3:
                val = read_u32_le(rom_data, pf)
                name = known.get(val, "")
                if name:
                    desc = f"LDR R{rd}, =0x{val:08X}  <{name}>"
                elif 0x02000000 <= val < 0x04000000:
                    desc = f"LDR R{rd}, =0x{val:08X}"
                else:
                    desc = f"LDR R{rd}, =0x{val:08X}"
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"MOV R{rd}, #0x{imm:X}"
        elif (instr & 0xFF00) == 0x3000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"ADD R{rd}, #0x{imm:X}"
            if imm == 1: extra = " <<<+1"
        elif (instr & 0xFF00) == 0x3800:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"SUB R{rd}, #0x{imm:X}"
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, #{imm}"
            if imm == 1: extra = " <<<+1"
        elif (instr & 0xFE00) == 0x1E00:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 7
            desc = f"SUBS R{rd}, R{rs}, #{imm}"
        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rb}, #0x{off:X}]"
            extra = " <<<LDRH"
        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"STRH R{rd}, [R{rb}, #0x{off:X}]"
            extra = " <<<STRH"
        elif (instr & 0xFE00) == 0x6800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 4
            desc = f"LDR R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x6000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 4
            desc = f"STR R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x7800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = (instr >> 6) & 0x1F
            desc = f"LDRB R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x7000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = (instr >> 6) & 0x1F
            desc = f"STRB R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFFC0) == 0x4280:
            rn = instr & 7; rm = (instr >> 3) & 7
            desc = f"CMP R{rn}, R{rm}"
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"CMP R{rn}, #0x{imm:X}"
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF
            names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE","???","SWI"]
            off = instr & 0xFF
            if off >= 0x80: off -= 0x100
            target = rom_addr + 4 + off * 2
            desc = f"{names[cond]} 0x{target:08X}"
        elif (instr & 0xF800) == 0xE000:
            off = instr & 0x7FF
            if off >= 0x400: off -= 0x800
            target = rom_addr + 4 + off * 2
            desc = f"B 0x{target:08X}"
        elif instr == 0x4770:
            desc = "BX LR"
        elif (instr & 0xFF00) == 0x4600:
            rd = ((instr >> 4) & 8) | (instr & 7)
            rm = (instr >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"
        elif (instr & 0xFC00) == 0x4000:
            op = (instr >> 6) & 0xF
            rs = (instr >> 3) & 7; rd = instr & 7
            alu = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                   "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            desc = f"{alu[op]} R{rd}, R{rs}"
        elif (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16_le(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                off11hi = instr & 0x07FF
                off11lo = next_instr & 0x07FF
                full_off = (off11hi << 12) | (off11lo << 1)
                if full_off >= 0x400000: full_off -= 0x800000
                target = rom_addr + 4 + full_off
                if target == 0x0804B430:
                    extra = " <<<SortBattlersBySpeed"
                lines.append(f"  {rom_addr:08X}:  {instr:04X} {next_instr:04X}  BL 0x{target:08X}{extra}")
                pos += 4
                continue
        elif (instr & 0xFE00) == 0x1800:
            rd = instr & 7; rs = (instr >> 3) & 7; rn = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, R{rn}"
        elif (instr & 0xF800) == 0x0000 and instr != 0:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            desc = f"LSL R{rd}, R{rs}, #{imm}"
        elif (instr & 0xF800) == 0x0800:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            if imm == 0: imm = 32
            desc = f"LSR R{rd}, R{rs}, #{imm}"
        elif (instr & 0xFF80) == 0xB000:
            imm = (instr & 0x7F) * 4
            desc = f"ADD SP, #0x{imm:X}"
        elif (instr & 0xFF80) == 0xB080:
            imm = (instr & 0x7F) * 4
            desc = f"SUB SP, #0x{imm:X}"

        lines.append(f"  {rom_addr:08X}:  {instr:04X}       {desc}{extra}")
        pos += 2

    return lines


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    # =========================================================================
    # Disassemble 300 bytes BEFORE 0x08057980 (the BL SortBattlersBySpeed call)
    # This is where HandleEndTurnOrder's gBattleTurnCounter++ should be
    # =========================================================================
    bl_site = 0x00057980  # file offset of BL

    print("=" * 90)
    print(f"  Disassembly around BL SortBattlersBySpeed at 0x{ROM_BASE + bl_site:08X}")
    print(f"  (300 bytes before through 60 bytes after)")
    print("=" * 90)
    print()

    start = bl_site - 300
    lines = disasm(rom_data, start, 200, KNOWN)
    for line in lines:
        print(line)

    print()

    # =========================================================================
    # Now check 0x0803FAEC too with more context (500 bytes before)
    # =========================================================================
    bl_site2 = 0x0003FAEC  # file offset

    print("=" * 90)
    print(f"  Disassembly around BL SortBattlersBySpeed at 0x{ROM_BASE + bl_site2:08X}")
    print(f"  (500 bytes before through 60 bytes after)")
    print(f"  This is inside the LARGE battle function (PUSH at 0x0803F460)")
    print("=" * 90)
    print()

    start2 = bl_site2 - 500
    lines2 = disasm(rom_data, start2, 300, KNOWN)
    for line in lines2:
        print(line)

    print()

    # =========================================================================
    # Brute force: For EVERY SortBattlersBySpeed call site, scan backward
    # for LDRH to ANY EWRAM addr in 0x02023700-0x02023A18 range
    # =========================================================================
    print("=" * 90)
    print("  Scanning ALL 189 call sites for nearby LDRH of EWRAM 0x02023700-0x02023A18")
    print("=" * 90)
    print()

    # Find all BL 0x0804B430
    bl_sites_all = []
    for pos in range(0, len(rom_data) - 3, 2):
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xF800) != 0xF000:
            continue
        next_instr = read_u16_le(rom_data, pos + 2)
        if (next_instr & 0xF800) != 0xF800:
            continue
        off11hi = instr & 0x07FF
        off11lo = next_instr & 0x07FF
        full_off = (off11hi << 12) | (off11lo << 1)
        if full_off >= 0x400000: full_off -= 0x800000
        target = ROM_BASE + pos + 4 + full_off
        if target == 0x0804B430:
            bl_sites_all.append(pos)

    found_addresses = {}
    for site_off in bl_sites_all:
        # Scan backward up to 200 bytes
        for back in range(2, 200, 2):
            check_pos = site_off - back
            if check_pos < 0:
                break
            ci = read_u16_le(rom_data, check_pos)

            # LDR Rx, [PC, #imm]
            if (ci & 0xF800) != 0x4800:
                continue

            rd = (ci >> 8) & 7
            pc = ROM_BASE + check_pos
            pool_addr = ((pc + 4) & ~3) + (ci & 0xFF) * 4
            pf = pool_addr - ROM_BASE
            if pf < 0 or pf + 3 >= len(rom_data):
                continue
            val = read_u32_le(rom_data, pf)

            if not (0x02023700 <= val < 0x02023A18):
                continue

            # Check if there's a LDRH from this register in the next 6 instructions
            for fwd in range(2, 14, 2):
                fi = check_pos + fwd
                if fi + 1 >= len(rom_data):
                    break
                fi_instr = read_u16_le(rom_data, fi)
                if (fi_instr & 0xFE00) == 0x8800 and ((fi_instr >> 3) & 7) == rd:
                    h_rd = fi_instr & 7
                    h_off = ((fi_instr >> 6) & 0x1F) * 2
                    eff_addr = val + h_off
                    if eff_addr not in found_addresses:
                        found_addresses[eff_addr] = []
                    found_addresses[eff_addr].append((ROM_BASE + site_off, ROM_BASE + check_pos, val, h_off))
                    break

    for addr in sorted(found_addresses.keys()):
        sites = found_addresses[addr]
        name = KNOWN.get(addr, "")
        total_refs = len(find_all_refs(rom_data, addr)) if addr == (addr & ~1) else 0
        print(f"  0x{addr:08X}: LDRH'd near {len(sites)} SortBattlersBySpeed calls ({total_refs} direct refs) {name}")
        for bl_rom, ldr_rom, base, offset in sites[:3]:
            print(f"    BL at 0x{bl_rom:08X}, LDR at 0x{ldr_rom:08X} (base=0x{base:08X}+0x{offset:X})")

    print()

    # Now check which of these addresses has LDRH + ADD#1 + STRH pattern
    print("  Checking which of these have increment pattern...")
    print()

    for addr in sorted(found_addresses.keys()):
        name = KNOWN.get(addr, "")
        # For each occurrence, check if there's an ADD+1 then STRH nearby
        for bl_rom, ldr_rom, base, offset in found_addresses[addr]:
            ldr_off = ldr_rom - ROM_BASE
            # Find the LDRH instruction
            for fwd in range(2, 14, 2):
                fi = ldr_off + fwd
                fi_instr = read_u16_le(rom_data, fi)
                if (fi_instr & 0xFE00) != 0x8800:
                    continue
                rb = (fi_instr >> 3) & 7
                if rb != ((read_u16_le(rom_data, ldr_off) >> 8) & 7):
                    continue
                h_rd = fi_instr & 7
                h_off = ((fi_instr >> 6) & 0x1F) * 2

                # Check next 4 instructions for ADD/ADDS +1
                for ai in range(fi + 2, fi + 10, 2):
                    if ai + 1 >= len(rom_data):
                        break
                    ai_instr = read_u16_le(rom_data, ai)
                    add_dest = -1

                    if (ai_instr & 0xFF00) == 0x3000 and (ai_instr & 0xFF) == 1:
                        add_dest = (ai_instr >> 8) & 7
                    elif (ai_instr & 0xFE00) == 0x1C00 and ((ai_instr >> 6) & 7) == 1:
                        src = (ai_instr >> 3) & 7
                        if src == h_rd:
                            add_dest = ai_instr & 7

                    if add_dest < 0:
                        continue

                    # Check for STRH
                    for si in range(ai + 2, ai + 8, 2):
                        if si + 1 >= len(rom_data):
                            break
                        si_instr = read_u16_le(rom_data, si)
                        expected = 0x8000 | (rb << 3) | add_dest | ((h_off // 2) << 6)
                        if si_instr == expected:
                            total_refs = len(find_all_refs(rom_data, base))
                            print(f"  ** 0x{addr:08X} (base=0x{base:08X}+0x{h_off:X}, {total_refs} base refs): "
                                  f"INCREMENT near BL at 0x{bl_rom:08X} {name}")
                            # Show context
                            ctx_lines = disasm(rom_data, ldr_off - 4, 12, KNOWN)
                            for cl in ctx_lines:
                                print(f"    {cl}")
                            print()
                break

    print()
    print("  DONE")


if __name__ == "__main__":
    main()
