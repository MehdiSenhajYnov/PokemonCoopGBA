#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v4: Direct disassembly of HandleEndTurnOrder

HandleEndTurnOrder (battle_end_turn.c:28) does:
    gBattleTurnCounter++;
    gBattleStruct->eventState.endTurn++;
    for (u32 i = 0; i < gBattlersCount; i++)
        gBattlerByTurnOrder[i] = i;
    SortBattlersBySpeed(gBattlerByTurnOrder, FALSE);

It must reference gBattlerByTurnOrder (0x020233F6).
Find functions with gBattlerByTurnOrder + gBattlersCount that are NOT
the big SetActionsAndBattlersTurnOrder or TryDoEventsBeforeFirstTurn.
The function should be relatively small (~100-200 bytes).

Then disassemble the function to find what EWRAM address is loaded
just before the STRH (increment pattern).
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

def find_function_start(rom_data, offset):
    for back in range(2, 4096, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in (0xB400, 0xB500):
            return pos
    return None

def get_ewram_addrs_in_function(rom_data, func_start, max_size=2048):
    results = {}
    end = min(func_start + max_size, len(rom_data) - 3)
    pos = func_start
    pop_count = 0
    while pos < end:
        instr = read_u16_le(rom_data, pos)
        if pos > func_start + 4 and (instr & 0xFF00) == 0xBD00:
            pop_count += 1
            if pop_count >= 1:
                # Continue just a bit for the literal pool
                end = min(pos + 256, end)
        if (instr & 0xF800) == 0x4800:
            imm8 = instr & 0xFF
            pc = ROM_BASE + pos
            pool_addr = ((pc + 4) & ~3) + imm8 * 4
            file_off = pool_addr - ROM_BASE
            if 0 <= file_off < len(rom_data) - 3:
                val = read_u32_le(rom_data, file_off)
                if 0x02000000 <= val < 0x04000000:
                    results[val] = results.get(val, [])
                    results[val].append(pos)
        pos += 2
    return results

def analyze_function(rom_data, func_offset, max_size=2048):
    size = None
    bl_targets = []
    pos = func_offset
    end = min(func_offset + max_size, len(rom_data) - 1)
    while pos < end:
        instr = read_u16_le(rom_data, pos)
        if pos > func_offset + 2:
            if (instr & 0xFF00) == 0xBD00 or instr == 0x4770:
                size = pos + 2 - func_offset
                break
        if pos + 2 < end:
            next_instr = read_u16_le(rom_data, pos + 2)
            if (instr & 0xF800) == 0xF000 and (next_instr & 0xF800) == 0xF800:
                off11hi = instr & 0x07FF
                off11lo = next_instr & 0x07FF
                full_off = (off11hi << 12) | (off11lo << 1)
                if full_off >= 0x400000:
                    full_off -= 0x800000
                bl_pc = ROM_BASE + pos + 4
                target = bl_pc + full_off
                bl_targets.append(target)
                pos += 4
                continue
        pos += 2
    return size, bl_targets


def disasm_function(rom_data, func_start, max_instrs=200, known=None):
    if known is None:
        known = {}
    lines = []
    pos = func_start
    pop_seen = False
    for _ in range(max_instrs):
        if pos + 1 >= len(rom_data):
            break
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        desc = f"0x{instr:04X}"

        if (instr & 0xFF00) in (0xB400, 0xB500):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100:
                regs.append("LR" if (instr & 0xFF00) == 0xB500 else "R8")
            desc = f"PUSH {{{', '.join(regs)}}}"
        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100:
                regs.append("PC" if (instr & 0xFF00) == 0xBD00 else "R8")
            desc = f"POP {{{', '.join(regs)}}}"
            pop_seen = True
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            pool_addr = ((rom_addr + 4) & ~3) + imm8 * 4
            pf = pool_addr - ROM_BASE
            if 0 <= pf < len(rom_data) - 3:
                val = read_u32_le(rom_data, pf)
                name = known.get(val, "")
                if name:
                    name = f"  <-- {name}"
                desc = f"LDR R{rd}, =0x{val:08X}{name}"
        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7; rb = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rb}, #0x{imm:X}]"
        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7; rb = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            desc = f"STRH R{rd}, [R{rb}, #0x{imm:X}]"
        elif (instr & 0xFE00) == 0x6800:
            rd = instr & 7; rb = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            desc = f"LDR R{rd}, [R{rb}, #0x{imm:X}]"
        elif (instr & 0xFE00) == 0x6000:
            rd = instr & 7; rb = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            desc = f"STR R{rd}, [R{rb}, #0x{imm:X}]"
        elif (instr & 0xFE00) == 0x7800:
            rd = instr & 7; rb = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            desc = f"LDRB R{rd}, [R{rb}, #0x{imm:X}]"
        elif (instr & 0xFE00) == 0x7000:
            rd = instr & 7; rb = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            desc = f"STRB R{rd}, [R{rb}, #0x{imm:X}]"
        elif (instr & 0xFF00) == 0x3000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"ADD R{rd}, #0x{imm:X}"
        elif (instr & 0xFF00) == 0x3800:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"SUB R{rd}, #0x{imm:X}"
        elif (instr & 0xFF00) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"MOV R{rd}, #0x{imm:X}"
        elif (instr & 0xFFC0) == 0x1C00:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, #{imm}"
        elif instr == 0x4770:
            desc = "BX LR"
        elif (instr & 0xFF00) == 0x4600:
            rd = ((instr >> 4) & 8) | (instr & 7)
            rm = (instr >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"
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
            target = rom_addr + 4 + off * 2
            desc = f"{names[cond]} 0x{target:08X}"
        elif (instr & 0xF800) == 0xE000:
            off = instr & 0x7FF
            if off >= 0x400: off -= 0x800
            target = rom_addr + 4 + off * 2
            desc = f"B 0x{target:08X}"
        elif (instr & 0xF800) == 0xF000:
            if pos + 2 < len(rom_data):
                next_instr = read_u16_le(rom_data, pos + 2)
                if (next_instr & 0xF800) == 0xF800:
                    off11hi = instr & 0x07FF
                    off11lo = next_instr & 0x07FF
                    full_off = (off11hi << 12) | (off11lo << 1)
                    if full_off >= 0x400000: full_off -= 0x800000
                    target = rom_addr + 4 + full_off
                    lines.append(f"  {rom_addr:08X}: {instr:04X} {next_instr:04X}  BL 0x{target:08X}")
                    pos += 4
                    continue

        lines.append(f"  {rom_addr:08X}: {instr:04X}       {desc}")

        if pop_seen and (instr & 0xFF00) in (0xBC00, 0xBD00, 0x4700):
            # Stop shortly after POP {PC} or BX
            break
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
        0x020239D0: "?",
        0x02023A0C: "gBattleSpritesDataPtr?",
    }

    # Find functions that reference gBattlerByTurnOrder (0x020233F6)
    # and gBattlersCount (0x020233E4) and are small (~100-400 bytes)
    btto_refs = find_all_refs(rom_data, 0x020233F6)
    bc_refs_set = set(find_all_refs(rom_data, 0x020233E4))

    print("=" * 78)
    print("  Small functions with gBattlerByTurnOrder + gBattlersCount")
    print("  (HandleEndTurnOrder candidates)")
    print("=" * 78)
    print()

    for ref_off in btto_refs:
        fs = find_function_start(rom_data, ref_off)
        if fs is None:
            continue

        # Check if function also references gBattlersCount
        func_addrs = get_ewram_addrs_in_function(rom_data, fs, 2048)
        if 0x020233E4 not in func_addrs:
            continue

        size, bl_targets = analyze_function(rom_data, fs, 2048)
        if size is None or size > 500:
            continue

        func_rom = ROM_BASE + fs + 1
        all_ewram = sorted(a for a in func_addrs if 0x02023000 <= a < 0x02024000)

        # Check if it references any address in 0x02023900-0x02023A00 range
        near_tc = [a for a in all_ewram if 0x02023700 <= a < 0x02023A00]

        print(f"  Function 0x{func_rom:08X} ({size} bytes, {len(bl_targets)} BLs)")
        print(f"    EWRAM refs: {', '.join(f'0x{a:08X}' for a in all_ewram)}")
        if near_tc:
            print(f"    ** Candidate TC addresses: {', '.join(f'0x{a:08X}' for a in near_tc)}")

        # Disassemble if it has a TC candidate
        if near_tc or len(all_ewram) <= 8:
            lines = disasm_function(rom_data, fs, 100, known)
            for line in lines:
                print(f"  {line}")
        print()

    # =========================================================================
    # Also check: TryDoEventsBeforeFirstTurn (line 3809 gBattleTurnCounter=0)
    # This is a CASE within a switch function. Find it via gBattlerByTurnOrder +
    # gBattlersCount + nearby call to GetBattlerAbility + GetWhichBattlerFaster
    # =========================================================================
    print("=" * 78)
    print("  All EWRAM addresses that appear ONLY in functions with gBattlerByTurnOrder")
    print("  in the 0x02023800-0x02023A18 range")
    print("=" * 78)
    print()

    # Collect all functions referencing gBattlerByTurnOrder
    btto_funcs = set()
    for ref_off in btto_refs:
        fs = find_function_start(rom_data, ref_off)
        if fs is not None:
            btto_funcs.add(fs)

    # For each function, collect EWRAM addresses in the TC range
    tc_all = {}
    for fs in btto_funcs:
        func_addrs = get_ewram_addrs_in_function(rom_data, fs, 8192)
        for addr in func_addrs:
            if 0x02023800 <= addr < 0x02023A18:
                if addr not in tc_all:
                    tc_all[addr] = []
                tc_all[addr].append(fs)

    for addr in sorted(tc_all.keys()):
        funcs = tc_all[addr]
        total_refs = len(find_all_refs(rom_data, addr))
        print(f"    0x{addr:08X}: {total_refs} total refs, in {len(funcs)} gBattlerByTurnOrder-funcs")

    print()


if __name__ == "__main__":
    main()
