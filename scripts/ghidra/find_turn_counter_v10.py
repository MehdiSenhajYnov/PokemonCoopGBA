#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v10: New strategy

HandleEndTurnOrder does:
    gBattleTurnCounter++;           // LDRH Rx, [Ry, #0]; ADD Rx, #1; STRH Rx, [Ry, #0]
    gBattleStruct->eventState.endTurn++;  // via gBattleStruct (0x020239D0)
    for (i=0; i<gBattlersCount; i++) gBattlerByTurnOrder[i] = i;  // loop with STRB
    SortBattlersBySpeed(gBattlerByTurnOrder, FALSE);

Approach:
1. Find ALL BL calls to SortBattlersBySpeed (0x0804B430)
2. For each call site, walk backwards to find the function PUSH
3. In that function, check for BOTH gBattlerByTurnOrder (0x020233F6) AND gBattlersCount (0x020233E4)
4. If found, scan the function for ANY LDRH+ADD/ADDS+STRH pattern on the SAME base register
5. Resolve which EWRAM address that register holds = gBattleTurnCounter

Also: Maybe the compiler doesn't use a literal pool for gBattleTurnCounter at all!
If gFieldStatuses is nearby, the compiler could load gFieldStatuses address and use
LDRH Rx, [Ry, #20] for gBattleTurnCounter (offset 20 = sizeof(u32) + sizeof(FieldTimer)).

Strategy B: For functions with gBattlerByTurnOrder+gBattlersCount+SortBattlersBySpeed,
scan for ALL LDRH with non-zero offsets and STRH back to same register+offset.
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
    0x020233E4: "gBattlersCount",
    0x020233FC: "gBattleMons",
    0x020233DC: "gActiveBattler",
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
    0x02023958: "gFieldStatuses?",
    0x02023960: "gFieldStatuses?",
}

SORT_BATTLERS = 0x0804B430
GBATTLER_BY_TURN_ORDER = 0x020233F6
GBATTLERS_COUNT = 0x020233E4
GBATTLE_STRUCT = 0x020239D0

def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

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

def get_ldr_pool_value(rom_data, pos):
    """For a THUMB LDR Rn, [PC, #imm] instruction, return (reg, value)"""
    instr = read_u16_le(rom_data, pos)
    if (instr & 0xF800) != 0x4800:
        return None, None
    rd = (instr >> 8) & 7
    imm8 = instr & 0xFF
    rom_addr = ROM_BASE + pos
    pa = ((rom_addr + 4) & ~3) + imm8 * 4
    pf = pa - ROM_BASE
    if 0 <= pf < len(rom_data) - 3:
        val = read_u32_le(rom_data, pf)
        return rd, val
    return rd, None

def find_push_backwards(rom_data, from_pos, max_dist=16000):
    """Walk backwards from from_pos to find a PUSH {.., LR} instruction."""
    pos = from_pos - 2
    while pos >= max(0, from_pos - max_dist):
        instr = read_u16_le(rom_data, pos)
        # PUSH with LR
        if (instr & 0xFF00) == 0xB500:
            return pos
        # If we hit a POP {.., PC} (return), the function boundary is before this
        if (instr & 0xFF00) == 0xBD00:
            # Function ends here, so the next PUSH after this is our function start
            # But we need to search FORWARD from here for a PUSH
            search = pos + 2
            while search < from_pos:
                si = read_u16_le(rom_data, search)
                if (si & 0xFF00) == 0xB500:
                    return search
                search += 2
            return None
        pos -= 2
    return None

def find_pop_forwards(rom_data, from_pos, max_dist=8000):
    """Find first POP {.., PC} after from_pos"""
    pos = from_pos + 2
    while pos < min(len(rom_data) - 1, from_pos + max_dist):
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) == 0xBD00:
            return pos + 2  # position AFTER the POP
        pos += 2
    return from_pos + max_dist


def analyze_function(rom_data, func_start, func_end):
    """Analyze a function for:
    - References to known EWRAM addresses via literal pool
    - LDRH + ADD/ADDS #1 + STRH patterns (gBattleTurnCounter increment)
    - BL calls
    Returns dict of findings.
    """
    result = {
        'ewram_refs': {},  # addr -> [(reg, rom_addr)]
        'ldrh_addrs': [],  # list of (rom_addr, reg, base_reg, offset)
        'strh_addrs': [],  # list of (rom_addr, reg, base_reg, offset)
        'add1_addrs': [],  # list of (rom_addr, reg)
        'bl_targets': [],  # list of (rom_addr, target)
        'instructions': [], # list of (rom_addr, instr_raw, desc)
    }

    # First pass: collect literal pool loads
    reg_values = {}  # track what value each register holds (from LDR literal pool)

    pos = func_start
    while pos < func_end and pos + 1 < len(rom_data):
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos

        # LDR Rn, [PC, #imm] - literal pool load
        if (instr & 0xF800) == 0x4800:
            rd, val = get_ldr_pool_value(rom_data, pos)
            if val is not None:
                reg_values[rd] = val
                if 0x02000000 <= val < 0x04000000:
                    if val not in result['ewram_refs']:
                        result['ewram_refs'][val] = []
                    result['ewram_refs'][val].append((rd, rom_addr))

        # LDRH Rd, [Rb, #off]
        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7
            rb = (instr >> 3) & 7
            off = ((instr >> 6) & 0x1F) * 2
            result['ldrh_addrs'].append((rom_addr, rd, rb, off))

        # STRH Rd, [Rb, #off]
        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7
            rb = (instr >> 3) & 7
            off = ((instr >> 6) & 0x1F) * 2
            result['strh_addrs'].append((rom_addr, rd, rb, off))

        # ADD Rd, #imm
        elif (instr & 0xFF00) == 0x3000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            if imm == 1:
                result['add1_addrs'].append((rom_addr, rd))

        # ADDS Rd, Rs, #imm
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7
            imm = (instr >> 6) & 7
            if imm == 1:
                result['add1_addrs'].append((rom_addr, rd))

        # BL
        elif (instr & 0xF800) == 0xF000 and pos + 3 < len(rom_data):
            ni = read_u16_le(rom_data, pos + 2)
            if (ni & 0xF800) == 0xF800:
                target = find_bl_target(rom_data, pos)
                result['bl_targets'].append((rom_addr, target))
                pos += 4
                continue

        pos += 2

    return result


def disassemble_range(rom_data, start, end):
    """Full disassembly of a ROM range, returns list of (rom_addr, raw, desc)"""
    instrs = []
    pos = start
    while pos < end and pos + 1 < len(rom_data):
        instr = read_u16_le(rom_data, pos)
        rom_addr = ROM_BASE + pos
        desc = f"0x{instr:04X}"
        length = 2

        if (instr & 0xFF00) in (0xB400, 0xB500):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100: regs.append("LR" if (instr & 0xFF00) == 0xB500 else "R8")
            desc = f"PUSH {{{', '.join(regs)}}}"
        elif (instr & 0xFF00) in (0xBC00, 0xBD00):
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if instr & 0x100: regs.append("PC" if (instr & 0xFF00) == 0xBD00 else "R8")
            desc = f"POP {{{', '.join(regs)}}}"
        elif (instr & 0xF800) == 0x4800:
            rd, val = get_ldr_pool_value(rom_data, pos)
            if val is not None:
                name = KNOWN.get(val, "")
                desc = f"LDR R{rd}, =0x{val:08X}" + (f"  <{name}>" if name else "")
            else:
                desc = f"LDR R{(instr >> 8) & 7}, [PC, ...]"
        elif (instr & 0xFE00) == 0x8800:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rb}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x8000:
            rd = instr & 7; rb = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            desc = f"STRH R{rd}, [R{rb}, #0x{off:X}]"
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
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7; rs = (instr >> 3) & 7; imm = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, #{imm}"
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"MOV R{rd}, #0x{imm:X}"
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
        elif (instr & 0xF800) == 0xF000 and pos + 3 < len(rom_data):
            ni = read_u16_le(rom_data, pos + 2)
            if (ni & 0xF800) == 0xF800:
                target = find_bl_target(rom_data, pos)
                tname = ""
                if target == SORT_BATTLERS: tname = " <SortBattlersBySpeed>"
                desc = f"BL 0x{target:08X}{tname}"
                instrs.append((rom_addr, f"{instr:04X} {ni:04X}", desc))
                pos += 4
                continue
        elif (instr & 0xFE00) == 0x1800:
            rd = instr & 7; rs = (instr >> 3) & 7; rn = (instr >> 6) & 7
            desc = f"ADDS R{rd}, R{rs}, R{rn}"
        elif (instr & 0xFF00) == 0x3800:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f"SUB R{rd}, #0x{imm:X}"

        instrs.append((rom_addr, f"{instr:04X}    ", desc))
        pos += 2

    return instrs


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    # =========================================================================
    # PHASE 1: Find ALL BL calls to SortBattlersBySpeed
    # =========================================================================
    print("=" * 90)
    print("  PHASE 1: Find all BL calls to SortBattlersBySpeed (0x0804B430)")
    print("=" * 90)
    print()

    bl_sites = []
    for pos in range(0, min(len(rom_data) - 4, 0x01000000), 2):
        target = find_bl_target(rom_data, pos)
        if target == SORT_BATTLERS:
            bl_sites.append(pos)

    print(f"  Found {len(bl_sites)} call sites")
    print()

    # =========================================================================
    # PHASE 2: For each call site, find enclosing function and check for
    #          gBattlerByTurnOrder + gBattlersCount + increment pattern
    # =========================================================================
    print("=" * 90)
    print("  PHASE 2: Find functions with gBattlerByTurnOrder + gBattlersCount + increment")
    print("=" * 90)
    print()

    candidates = []

    for site_off in bl_sites:
        site_addr = ROM_BASE + site_off

        # Find function boundaries
        func_start = find_push_backwards(rom_data, site_off)
        if func_start is None:
            continue
        func_end = find_pop_forwards(rom_data, site_off)

        # Analyze the function
        analysis = analyze_function(rom_data, func_start, func_end)

        has_turn_order = GBATTLER_BY_TURN_ORDER in analysis['ewram_refs']
        has_battlers_count = GBATTLERS_COUNT in analysis['ewram_refs']
        has_battle_struct = GBATTLE_STRUCT in analysis['ewram_refs']
        has_add1 = len(analysis['add1_addrs']) > 0
        has_ldrh = len(analysis['ldrh_addrs']) > 0
        has_strh = len(analysis['strh_addrs']) > 0

        # We want functions that have gBattlerByTurnOrder AND gBattlersCount
        # AND some LDRH+ADD/ADDS+STRH pattern (the increment)
        if has_turn_order and has_battlers_count:
            func_size = func_end - func_start
            bl_count = len(analysis['bl_targets'])

            # Check for LDRH+ADD+STRH on same register (increment pattern)
            increment_candidates = []
            for ldrh_addr, ldrh_rd, ldrh_rb, ldrh_off in analysis['ldrh_addrs']:
                for add_addr, add_rd in analysis['add1_addrs']:
                    if add_rd == ldrh_rd and abs(add_addr - ldrh_addr) <= 8:
                        for strh_addr, strh_rd, strh_rb, strh_off in analysis['strh_addrs']:
                            if strh_rd == ldrh_rd and strh_rb == ldrh_rb and strh_off == ldrh_off:
                                if abs(strh_addr - add_addr) <= 8:
                                    increment_candidates.append({
                                        'ldrh_addr': ldrh_addr,
                                        'add_addr': add_addr,
                                        'strh_addr': strh_addr,
                                        'base_reg': ldrh_rb,
                                        'offset': ldrh_off,
                                        'data_reg': ldrh_rd,
                                    })

            candidates.append({
                'site_addr': site_addr,
                'func_start': ROM_BASE + func_start,
                'func_end': ROM_BASE + func_end,
                'func_size': func_size,
                'bl_count': bl_count,
                'ewram_addrs': sorted(analysis['ewram_refs'].keys()),
                'has_add1': has_add1,
                'has_ldrh_strh': has_ldrh and has_strh,
                'has_battle_struct': has_battle_struct,
                'increment_candidates': increment_candidates,
                'n_ldrh': len(analysis['ldrh_addrs']),
                'n_strh': len(analysis['strh_addrs']),
                'n_add1': len(analysis['add1_addrs']),
                'analysis': analysis,
            })

    print(f"  Found {len(candidates)} functions with gBattlerByTurnOrder + gBattlersCount")
    print()

    for i, c in enumerate(candidates):
        marker = ""
        if c['increment_candidates']:
            marker = " *** HAS INCREMENT PATTERN ***"
        elif c['has_add1'] and c['has_ldrh_strh']:
            marker = " (has add1 + ldrh/strh but no exact match)"

        print(f"  [{i}] Function 0x{c['func_start']:08X}-0x{c['func_end']:08X} "
              f"({c['func_size']}B, {c['bl_count']} BLs){marker}")
        print(f"      Call site: 0x{c['site_addr']:08X}")
        print(f"      LDRH: {c['n_ldrh']}, STRH: {c['n_strh']}, ADD#1: {c['n_add1']}")
        print(f"      EWRAM addresses:")
        for addr in c['ewram_addrs']:
            name = KNOWN.get(addr, "")
            print(f"        0x{addr:08X} {name}")

        if c['increment_candidates']:
            print(f"      INCREMENT CANDIDATES:")
            for ic in c['increment_candidates']:
                print(f"        LDRH @0x{ic['ldrh_addr']:08X}, ADD#1 @0x{ic['add_addr']:08X}, "
                      f"STRH @0x{ic['strh_addr']:08X}")
                print(f"        base_reg=R{ic['base_reg']}, offset=#0x{ic['offset']:X}, data_reg=R{ic['data_reg']}")
                # Try to resolve what EWRAM address the base register holds
                for ewram_addr, refs in c['analysis']['ewram_refs'].items():
                    for ref_reg, ref_addr in refs:
                        if ref_reg == ic['base_reg'] and ref_addr < ic['ldrh_addr']:
                            computed = ewram_addr + ic['offset']
                            print(f"        -> Base R{ic['base_reg']} loaded with 0x{ewram_addr:08X} at 0x{ref_addr:08X}")
                            print(f"        -> gBattleTurnCounter = 0x{ewram_addr:08X} + 0x{ic['offset']:X} = 0x{computed:08X}")
        print()

    # =========================================================================
    # PHASE 3: For small functions (< 300 bytes) with the right refs,
    #          do full disassembly
    # =========================================================================
    print("=" * 90)
    print("  PHASE 3: Full disassembly of SMALL candidate functions (< 300 bytes)")
    print("=" * 90)
    print()

    for i, c in enumerate(candidates):
        if c['func_size'] < 300:
            print(f"  --- Function [{i}]: 0x{c['func_start']:08X} ({c['func_size']} bytes) ---")
            print()
            func_off = c['func_start'] - ROM_BASE
            func_end_off = c['func_end'] - ROM_BASE
            instrs = disassemble_range(rom_data, func_off, func_end_off + 64)
            for raddr, raw, desc in instrs:
                print(f"    {raddr:08X}: {raw}  {desc}")
            print()

    # =========================================================================
    # PHASE 4: Alternative — scan for gBattleTurnCounter via offset from
    #          gBattleStruct->eventState.endTurn increment
    # HandleEndTurnOrder also does: gBattleStruct->eventState.endTurn++
    # If we find a function doing BOTH increments (one via gBattleStruct pointer,
    # one via halfword), that's HandleEndTurnOrder.
    # =========================================================================
    print("=" * 90)
    print("  PHASE 4: Functions with gBattleStruct + gBattlerByTurnOrder + SortBattlersBySpeed")
    print("=" * 90)
    print()

    for i, c in enumerate(candidates):
        if c['has_battle_struct']:
            print(f"  [{i}] Function 0x{c['func_start']:08X} ({c['func_size']}B) "
                  f"- has gBattleStruct + gBattlerByTurnOrder + gBattlersCount")
            if c['has_add1']:
                print(f"       Also has {c['n_add1']} ADD#1 instructions")

            # Full disassembly for small functions
            if c['func_size'] < 500:
                func_off = c['func_start'] - ROM_BASE
                func_end_off = c['func_end'] - ROM_BASE
                instrs = disassemble_range(rom_data, func_off, func_end_off + 64)
                print(f"       Full disassembly:")
                for raddr, raw, desc in instrs:
                    print(f"         {raddr:08X}: {raw}  {desc}")
            print()

    # =========================================================================
    # PHASE 5: Brute force — for ALL functions with SortBattlersBySpeed calls,
    #          look for LDRH [Rn, #0] + ADD/ADDS #1 + STRH [Rn, #0] pattern
    #          where Rn was loaded from literal pool pointing to EWRAM
    #          This catches gBattleTurnCounter even if its own literal pool
    #          address is the ONLY reference.
    # =========================================================================
    print("=" * 90)
    print("  PHASE 5: Brute-force — ALL SortBattlersBySpeed callers with LDRH-increment-STRH")
    print("=" * 90)
    print()

    all_inc_functions = []

    for site_off in bl_sites:
        func_start = find_push_backwards(rom_data, site_off)
        if func_start is None:
            continue
        func_end = find_pop_forwards(rom_data, site_off)

        # Quick scan for LDRH + ADD#1/ADDS#1 + STRH pattern
        pos = func_start
        ldrh_regs = {}  # pos -> (rd, rb, off)
        add1_regs = {}  # pos -> rd
        increments_found = []

        while pos < func_end and pos + 1 < len(rom_data):
            instr = read_u16_le(rom_data, pos)

            # LDRH
            if (instr & 0xFE00) == 0x8800:
                rd = instr & 7
                rb = (instr >> 3) & 7
                off = ((instr >> 6) & 0x1F) * 2
                ldrh_regs[pos] = (rd, rb, off)

            # ADD Rd, #1
            elif (instr & 0xFF00) == 0x3000 and (instr & 0xFF) == 1:
                rd = (instr >> 8) & 7
                add1_regs[pos] = rd
                # Check if recent LDRH loaded this register
                for lp in sorted(ldrh_regs.keys(), reverse=True):
                    if pos - lp > 12: break
                    lr, lb, lo = ldrh_regs[lp]
                    if lr == rd:
                        # Found LDRH Rx + ADD Rx, #1 — now look for STRH Rx, [same base, same off]
                        sp = pos + 2
                        while sp < min(func_end, pos + 12) and sp + 1 < len(rom_data):
                            si = read_u16_le(rom_data, sp)
                            if (si & 0xFE00) == 0x8000:
                                sd = si & 7
                                sb = (si >> 3) & 7
                                so = ((si >> 6) & 0x1F) * 2
                                if sd == rd and sb == lb and so == lo:
                                    # MATCH! Now resolve base register
                                    increments_found.append({
                                        'ldrh_pos': lp,
                                        'add_pos': pos,
                                        'strh_pos': sp,
                                        'base_reg': lb,
                                        'offset': lo,
                                        'data_reg': rd,
                                        'func_start': func_start,
                                        'func_end': func_end,
                                    })
                            sp += 2
                        break

            # ADDS Rd, Rs, #1
            elif (instr & 0xFE00) == 0x1C00 and ((instr >> 6) & 7) == 1:
                rd = instr & 7
                rs = (instr >> 3) & 7
                add1_regs[pos] = rd
                # Check if recent LDRH loaded rs or rd
                for lp in sorted(ldrh_regs.keys(), reverse=True):
                    if pos - lp > 12: break
                    lr, lb, lo = ldrh_regs[lp]
                    if lr == rs:
                        # ADDS Rd, Rs, #1 where Rs was loaded by LDRH
                        sp = pos + 2
                        while sp < min(func_end, pos + 12) and sp + 1 < len(rom_data):
                            si = read_u16_le(rom_data, sp)
                            if (si & 0xFE00) == 0x8000:
                                sd = si & 7
                                sb = (si >> 3) & 7
                                so = ((si >> 6) & 0x1F) * 2
                                if sd == rd and sb == lb and so == lo:
                                    increments_found.append({
                                        'ldrh_pos': lp,
                                        'add_pos': pos,
                                        'strh_pos': sp,
                                        'base_reg': lb,
                                        'offset': lo,
                                        'data_reg': rd,
                                        'func_start': func_start,
                                        'func_end': func_end,
                                    })
                            sp += 2
                        break

            pos += 2

        if increments_found:
            all_inc_functions.append({
                'site_off': site_off,
                'increments': increments_found,
            })

    print(f"  Found {len(all_inc_functions)} SortBattlersBySpeed-calling functions with increment patterns")
    print()

    for item in all_inc_functions:
        site_addr = ROM_BASE + item['site_off']
        print(f"  Call site: 0x{site_addr:08X}")
        for inc in item['increments']:
            func_addr = ROM_BASE + inc['func_start']
            func_size = inc['func_end'] - inc['func_start']
            print(f"    Function: 0x{func_addr:08X} ({func_size} bytes)")
            print(f"    Pattern: LDRH @0x{ROM_BASE + inc['ldrh_pos']:08X}, "
                  f"ADD#1 @0x{ROM_BASE + inc['add_pos']:08X}, "
                  f"STRH @0x{ROM_BASE + inc['strh_pos']:08X}")
            print(f"    base_reg=R{inc['base_reg']}, offset=#0x{inc['offset']:X}")

            # Resolve base register from literal pool loads
            func_start = inc['func_start']
            ldrh_pos = inc['ldrh_pos']
            base_reg = inc['base_reg']

            # Scan backwards from LDRH to find LDR of base_reg
            scan = ldrh_pos - 2
            while scan >= max(func_start, ldrh_pos - 64):
                ci = read_u16_le(rom_data, scan)
                if (ci & 0xF800) == 0x4800:
                    rd, val = get_ldr_pool_value(rom_data, scan)
                    if rd == base_reg and val is not None:
                        computed = val + inc['offset']
                        name = KNOWN.get(val, "")
                        cname = KNOWN.get(computed, "")
                        print(f"    -> R{base_reg} loaded with 0x{val:08X} {name} at 0x{ROM_BASE + scan:08X}")
                        print(f"    -> Incremented address = 0x{val:08X} + 0x{inc['offset']:X} = 0x{computed:08X} {cname}")
                        if 0x02000000 <= computed < 0x04000000 and not cname:
                            print(f"    *** CANDIDATE gBattleTurnCounter = 0x{computed:08X} ***")
                        break
                scan -= 2

            # Also show context disassembly (20 instructions around the LDRH)
            print(f"    Context disassembly:")
            ctx_start = max(func_start, inc['ldrh_pos'] - 20)
            ctx_end = min(inc['func_end'], inc['strh_pos'] + 20)
            instrs = disassemble_range(rom_data, ctx_start, ctx_end)
            for raddr, raw, desc in instrs:
                marker = "  "
                foff = raddr - ROM_BASE
                if foff == inc['ldrh_pos']:
                    marker = ">>"
                elif foff == inc['add_pos']:
                    marker = "++"
                elif foff == inc['strh_pos']:
                    marker = "<<"
                print(f"      {marker} {raddr:08X}: {raw}  {desc}")
            print()

    # =========================================================================
    # PHASE 6: Final verification — search ALL EWRAM addresses near known
    #          battle vars for anything with exactly the right ref count
    # gBattleTurnCounter in vanilla has ~10-20 references (used in a few places)
    # =========================================================================
    print("=" * 90)
    print("  PHASE 6: Scan EWRAM range near known battle vars for 5-30 ref addresses")
    print("=" * 90)
    print()

    # Known addresses in battle_main.c EWRAM section are around 0x02023500-0x02023A20
    # gBattleTurnCounter should be near gFieldStatuses/gFieldTimers
    # Let's scan 0x02023900-0x020239D0 (where gBattleStruct is at 0x020239D0)
    target_bytes = bytearray(4)
    for addr in range(0x02023900, 0x020239D0, 2):
        struct.pack_into('<I', target_bytes, 0, addr)
        count = 0
        for i in range(0, min(len(rom_data) - 3, 0x01000000), 4):
            if rom_data[i:i+4] == bytes(target_bytes):
                count += 1
        if 3 <= count <= 40:
            name = KNOWN.get(addr, "")
            print(f"  0x{addr:08X}: {count:3d} refs  {name}")

    print()
    print("  DONE")


if __name__ == "__main__":
    main()
