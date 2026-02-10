#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v9: Disassemble HandleEndTurnOrder at 0x08054F34

Found via sEndTurnEffectHandlers table at 0x083AED78, entry [0] = 0x08054F35.
This is HandleEndTurnOrder in R&B (heavily modified from vanilla expansion).

The original source does:
    gBattleTurnCounter++;
    gBattleStruct->eventState.endTurn++;
    for (i < gBattlersCount) gBattlerByTurnOrder[i] = i;
    SortBattlersBySpeed(gBattlerByTurnOrder, FALSE);

R&B might have added code, but the gBattleTurnCounter++ should still be there.
Disassemble the FULL function and look for the increment pattern.
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
    0x020237C8: "?",
    0x02023958: "candidate_0x958",
    0x0202395A: "candidate_0x95A",
    0x02023960: "candidate_0x960",
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

def find_bl_target(rom_data, pos):
    instr = read_u16_le(rom_data, pos)
    ni = read_u16_le(rom_data, pos + 2)
    if (instr & 0xF800) != 0xF000 or (ni & 0xF800) != 0xF800:
        return None
    off11hi = instr & 0x07FF
    off11lo = ni & 0x07FF
    full_off = (off11hi << 12) | (off11lo << 1)
    if full_off >= 0x400000: full_off -= 0x800000
    return ROM_BASE + pos + 4 + full_off


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    # HandleEndTurnOrder starts at 0x08054F34 (THUMB: 0x08054F35)
    func_start = 0x00054F34

    # Find function end
    func_end = func_start
    pos = func_start + 4
    pop_count = 0
    while pos < func_start + 4000:
        ci = read_u16_le(rom_data, pos)
        if (ci & 0xFF00) == 0xBD00:
            pop_count += 1
            if pop_count >= 1:
                func_end = pos + 2
                break
        pos += 2

    func_size = func_end - func_start
    print(f"  HandleEndTurnOrder: 0x{ROM_BASE + func_start:08X} to 0x{ROM_BASE + func_end:08X} ({func_size} bytes)")
    print()

    # Full disassembly
    print("=" * 90)
    print("  FULL DISASSEMBLY of HandleEndTurnOrder (R&B modified)")
    print("=" * 90)
    print()

    pos = func_start
    instrs = []  # List of (file_off, rom_addr, raw_hex, desc, details)
    instr_count = 0
    while pos < func_end + 128 and pos + 1 < len(rom_data):
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        desc = f"0x{instr:04X}"
        extra = ""
        length = 2

        if (instr & 0xFF00) in (0xB400, 0xB500):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100: regs.append("LR" if (instr & 0xFF00) == 0xB500 else "R8")
            desc = f"PUSH {{{', '.join(regs)}}}"
        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100: regs.append("PC" if (instr & 0xFF00) == 0xBD00 else "R8")
            desc = f"POP {{{', '.join(regs)}}}"
            if "PC" in regs: extra = " <<<RETURN"
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7; imm8 = instr & 0xFF
            pa = ((rom_addr + 4) & ~3) + imm8 * 4
            pf = pa - ROM_BASE
            if 0 <= pf < len(rom_data) - 3:
                val = read_u32_le(rom_data, pf)
                name = KNOWN.get(val, "")
                if 0x02000000 <= val < 0x04000000:
                    desc = f"LDR R{rd}, =0x{val:08X}" + (f"  <{name}>" if name else "")
                else:
                    desc = f"LDR R{rd}, =0x{val:08X}"
        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rb}, #0x{off:X}]"
            extra = " ***LDRH"
        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"STRH R{rd}, [R{rb}, #0x{off:X}]"
            extra = " ***STRH"
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
        elif (instr & 0xFF00) == 0x3000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"ADD R{rd}, #0x{imm:X}"
            if imm == 1: extra = " <<<ADD_1"
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, #{imm}"
            if imm == 1: extra = " <<<ADDS_1"
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"MOV R{rd}, #0x{imm:X}"
            if imm == 0: extra = " <<<ZERO"
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"CMP R{rn}, #0x{imm:X}"
        elif (instr & 0xFFC0) == 0x4280:
            rn = instr & 7; rm = (instr >> 3) & 7
            desc = f"CMP R{rn}, R{rm}"
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF
            names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE","???","SWI"]
            off = instr & 0xFF
            if off >= 0x80: off -= 0x100
            desc = f"{names[cond]} 0x{rom_addr + 4 + off * 2:08X}"
        elif (instr & 0xF800) == 0xE000:
            off = instr & 0x7FF
            if off >= 0x400: off -= 0x800
            desc = f"B 0x{rom_addr + 4 + off * 2:08X}"
        elif instr == 0x4770:
            desc = "BX LR"
        elif (instr & 0xFF00) == 0x4600:
            rd = ((instr >> 4) & 8) | (instr & 7)
            rm = (instr >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"
        elif (instr & 0xFC00) == 0x4000:
            op = (instr >> 6) & 0xF; rs = (instr >> 3) & 7; rd = instr & 7
            alu = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR","TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            desc = f"{alu[op]} R{rd}, R{rs}"
        elif (instr & 0xFF80) == 0xB080:
            imm = (instr & 0x7F) * 4
            desc = f"SUB SP, #0x{imm:X}"
        elif (instr & 0xFF80) == 0xB000:
            imm = (instr & 0x7F) * 4
            desc = f"ADD SP, #0x{imm:X}"
        elif (instr & 0xF800) == 0x0000 and instr != 0:
            rd = instr & 7; rs = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            desc = f"LSL R{rd}, R{rs}, #{imm5}"
        elif (instr & 0xF800) == 0x0800:
            rd = instr & 7; rs = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            if imm5 == 0: imm5 = 32
            desc = f"LSR R{rd}, R{rs}, #{imm5}"
        elif (instr & 0xFF80) == 0x4700:
            rm = (instr >> 3) & 0xF
            desc = f"BX R{rm}"
        elif (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            ni = read_u16_le(rom_data, pos + 2)
            if (ni & 0xF800) == 0xF800:
                t = find_bl_target(rom_data, pos)
                if t == 0x0804B430:
                    extra = " <<<SortBattlersBySpeed"
                desc = f"BL 0x{t:08X}"
                raw = f"{instr:04X} {ni:04X}"
                instrs.append((pos, rom_addr, raw, desc + extra))
                pos += 4
                instr_count += 1
                continue
        elif (instr & 0xFE00) == 0x1800:
            rd = instr & 7; rs = (instr >> 3) & 7; rn = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, R{rn}"
        elif (instr & 0xFF00) == 0x3800:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"SUB R{rd}, #0x{imm:X}"

        raw = f"{instr:04X}     "
        instrs.append((pos, rom_addr, raw, desc + extra))
        pos += 2
        instr_count += 1

        if instr_count > 2000:
            break

    for foff, raddr, raw, desc in instrs:
        print(f"  {raddr:08X}: {raw}  {desc}")

    print()

    # =========================================================================
    # Analyze: Find ALL LDRH and STRH instructions in the function
    # =========================================================================
    print("=" * 90)
    print("  ANALYSIS: All LDRH/STRH instructions in the function")
    print("=" * 90)
    print()

    for i, (foff, raddr, raw, desc) in enumerate(instrs):
        if "***LDRH" in desc or "***STRH" in desc:
            # Show context (3 before, 3 after)
            for j in range(max(0, i-3), min(len(instrs), i+4)):
                marker = ">>>" if j == i else "   "
                _, ra, rw, de = instrs[j]
                print(f"  {marker} {ra:08X}: {rw}  {de}")
            print()

    # =========================================================================
    # Analyze: Find ALL ADD #1 / ADDS #1 instructions
    # =========================================================================
    print("=" * 90)
    print("  ANALYSIS: All ADD/ADDS #1 instructions in the function")
    print("=" * 90)
    print()

    for i, (foff, raddr, raw, desc) in enumerate(instrs):
        if "<<<ADD_1" in desc or "<<<ADDS_1" in desc:
            for j in range(max(0, i-5), min(len(instrs), i+5)):
                marker = ">>>" if j == i else "   "
                _, ra, rw, de = instrs[j]
                print(f"  {marker} {ra:08X}: {rw}  {de}")
            print()

    # =========================================================================
    # Collect ALL EWRAM addresses loaded by LDR from literal pool
    # =========================================================================
    print("=" * 90)
    print("  ALL EWRAM addresses loaded in HandleEndTurnOrder:")
    print("=" * 90)
    print()

    ewram_addrs = {}
    for foff, raddr, raw, desc in instrs:
        if "LDR R" in desc and "=0x02" in desc:
            # Extract the address
            idx = desc.index("=0x")
            addr_str = desc[idx+1:idx+11]
            try:
                val = int(addr_str, 16)
                if 0x02000000 <= val < 0x04000000:
                    if val not in ewram_addrs:
                        ewram_addrs[val] = []
                    ewram_addrs[val].append(raddr)
            except:
                pass

    for addr in sorted(ewram_addrs.keys()):
        refs_in_func = ewram_addrs[addr]
        total_refs = len(find_all_refs(rom_data, addr))
        name = KNOWN.get(addr, "")
        print(f"  0x{addr:08X}: {total_refs:4d} ROM refs, {len(refs_in_func)} in-func refs  {name}")
        for r in refs_in_func:
            print(f"    at 0x{r:08X}")

    print()

    # =========================================================================
    # Also disassemble the 2nd table entry to compare
    # =========================================================================
    print("=" * 90)
    print("  2nd table entry (HandleEndTurnVarious) for comparison")
    print("=" * 90)
    print()

    table_base = 0x003AED78
    entry1 = read_u32_le(rom_data, table_base + 4)
    func2_start = (entry1 & ~1) - ROM_BASE
    print(f"  Entry [1] = 0x{entry1:08X} -> function at 0x{ROM_BASE + func2_start:08X}")

    # Just first 30 instructions
    pos2 = func2_start
    for _ in range(30):
        if pos2 + 1 >= len(rom_data):
            break
        i2 = read_u16_le(rom_data, pos2)
        ra2 = ROM_BASE + pos2
        d2 = f"0x{i2:04X}"
        if (i2 & 0xF800) == 0x4800:
            rd = (i2 >> 8) & 7; imm8 = i2 & 0xFF
            pa = ((ra2 + 4) & ~3) + imm8 * 4
            pf = pa - ROM_BASE
            if 0 <= pf < len(rom_data) - 3:
                val = read_u32_le(rom_data, pf)
                name = KNOWN.get(val, "")
                d2 = f"LDR R{rd}, =0x{val:08X}" + (f" <{name}>" if name else "")
        elif (i2 & 0xFF00) in (0xB400, 0xB500):
            regs = [f"R{i}" for i in range(8) if i2 & (1 << i)]
            if i2 & 0x100: regs.append("LR")
            d2 = f"PUSH {{{', '.join(regs)}}}"
        elif (i2 & 0xFE00) == 0x8800:
            rd = i2 & 7; rb = (i2 >> 3) & 7; off = ((i2 >> 6) & 0x1F) * 2
            d2 = f"LDRH R{rd}, [R{rb}, #0x{off:X}] ***"
        elif (i2 & 0xFE00) == 0x8000:
            rd = i2 & 7; rb = (i2 >> 3) & 7; off = ((i2 >> 6) & 0x1F) * 2
            d2 = f"STRH R{rd}, [R{rb}, #0x{off:X}] ***"
        print(f"  {ra2:08X}: {i2:04X}  {d2}")
        pos2 += 2

    print()
    print("  DONE")


if __name__ == "__main__":
    main()
