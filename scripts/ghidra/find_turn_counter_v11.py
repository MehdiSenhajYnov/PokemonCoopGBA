#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v11: Verify 0x02023708 candidate

gBattleTurnCounter has ONLY 3 source references:
1. Declaration (EWRAM_DATA u16 gBattleTurnCounter = 0) — no ROM ref
2. gBattleTurnCounter = 0 in TryDoEventsBeforeFirstTurn (battle_main.c:3809)
3. gBattleTurnCounter++ in HandleEndTurnOrder (battle_end_turn.c:32)

So we expect exactly 2 literal pool refs in ROM. 0x02023708 has 2 refs — matches!

This script:
1. Finds ALL 2 ROM literal pool refs for 0x02023708
2. Disassembles the context around each to verify:
   - One should be "MOV R0, #0; STRH R0, [Rn, #0]" (reset to 0)
   - Other should be "LDRH R0, [Rn, #0]; ADD R0, #1; STRH R0, [Rn, #0]" (increment)
3. Cross-checks with structural layout:
   - gFieldStatuses (u32) should be 20 bytes before gBattleTurnCounter
   - gBattleMovePower (u16) + gMoveToLearn (u16) should be 24 bytes before gFieldStatuses
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
    0x02023594: "gBattlescriptCurrInstr",
    0x0202359C: "gBattlerAttacker",
    0x020239D0: "gBattleStruct",
    0x02023A0C: "gBattleSpritesDataPtr",
    0x02023A18: "gBattleResources",
    0x02023958: "gFieldStatuses_candidate_A",
    0x02023960: "gFieldStatuses_candidate_B",
    0x02023708: "gBattleTurnCounter_CANDIDATE",
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

def get_ldr_pool_value(rom_data, pos):
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


def disasm_thumb(rom_data, pos):
    """Simple THUMB disassembly of one instruction, returns (desc, length)"""
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
            desc = f"BL 0x{target:08X}"
            length = 4
    elif (instr & 0xFE00) == 0x1800:
        rd = instr & 7; rs = (instr >> 3) & 7; rn = (instr >> 6) & 7
        desc = f"ADDS R{rd}, R{rs}, R{rn}"
    elif (instr & 0xFF00) == 0x3800:
        rd = (instr >> 8) & 7; imm = instr & 0xFF
        desc = f"SUB R{rd}, #0x{imm:X}"

    return desc, length


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    TARGET = 0x02023708
    target_bytes = struct.pack('<I', TARGET)

    # =========================================================================
    # PART 1: Find ALL literal pool refs for 0x02023708
    # =========================================================================
    print("=" * 90)
    print(f"  PART 1: ALL ROM literal pool refs for 0x{TARGET:08X}")
    print("=" * 90)
    print()

    refs = find_all_refs(rom_data, TARGET)
    print(f"  Found {len(refs)} literal pool entries")
    print()

    for ref_off in refs:
        ref_addr = ROM_BASE + ref_off
        print(f"  Literal pool entry at ROM offset 0x{ref_off:06X} (0x{ref_addr:08X})")

        # Find which LDR instruction uses this pool entry
        # LDR Rn, [PC, #imm] where PC-relative address = pool entry
        found_users = []
        # Search backwards from pool entry for LDR instructions that reference it
        for scan in range(max(0, ref_off - 4096), ref_off, 2):
            ci = read_u16_le(rom_data, scan)
            if (ci & 0xF800) == 0x4800:
                rd = (ci >> 8) & 7
                imm8 = ci & 0xFF
                scan_addr = ROM_BASE + scan
                pa = ((scan_addr + 4) & ~3) + imm8 * 4
                if pa == ref_addr:
                    found_users.append((scan, rd))

        for user_off, reg in found_users:
            user_addr = ROM_BASE + user_off
            print(f"    Used by LDR R{reg}, =0x{TARGET:08X} at 0x{user_addr:08X}")
            print()

            # Disassemble context: 30 instructions before and 30 after
            ctx_start = max(0, user_off - 60)
            ctx_end = min(len(rom_data) - 1, user_off + 80)

            pos = ctx_start
            while pos < ctx_end:
                desc, length = disasm_thumb(rom_data, pos)
                addr = ROM_BASE + pos
                marker = ">>>" if pos == user_off else "   "
                print(f"    {marker} {addr:08X}: {desc}")
                pos += length

            print()

    # =========================================================================
    # PART 2: Structural layout verification
    # If gBattleTurnCounter = 0x02023708, then:
    #   gFieldTimers = 0x02023708 - 2 - 16 = 0x020236F6 (16 bytes)
    #   gFieldStatuses = 0x020236F6 - 4 = 0x020236F2 (u32)
    #   gMoveToLearn = 0x020236F2 - 2 = 0x020236F0
    #   gBattleMovePower = 0x020236F0 - 2 = 0x020236EE
    #   gBattlerAbility = 0x02023708 + 2 = 0x0202370A (u8)
    # =========================================================================
    print("=" * 90)
    print(f"  PART 2: Structural layout if gBattleTurnCounter = 0x{TARGET:08X}")
    print("=" * 90)
    print()

    layout = [
        ("gBattleMovePower", TARGET - 2 - 16 - 4 - 2 - 2, "u16"),  # -26
        ("gMoveToLearn", TARGET - 2 - 16 - 4 - 2, "u16"),           # -24
        ("gFieldStatuses", TARGET - 2 - 16 - 4, "u32"),             # -22
        ("gFieldTimers", TARGET - 2 - 16, "16B struct"),             # -18
        ("gBattleTurnCounter", TARGET, "u16"),
        ("gBattlerAbility", TARGET + 2, "u8"),
        ("gQueuedStatBoosts", TARGET + 3, "struct array"),
    ]

    # Wait, let me recalculate. Source order:
    # gBattleMovePower (u16) = 2 bytes
    # gMoveToLearn (u16) = 2 bytes
    # gFieldStatuses (u32) = 4 bytes
    # gFieldTimers (struct FieldTimer) = 16 bytes (8 x u16)
    # gBattleTurnCounter (u16) = 2 bytes
    # gBattlerAbility (u8) = 1 byte
    #
    # Cumulative: BMP(2) + MTL(2) + FS(4) + FT(16) + BTC(2) = 26 bytes
    # gBattleTurnCounter offset from gBattleMovePower = 2+2+4+16 = 24

    # But we also need to account for alignment. u32 needs 4-byte alignment.
    # After gMoveToLearn (u16), the next u32 needs to be 4-byte aligned.
    # gBattleMovePower: addr
    # gMoveToLearn: addr + 2
    # gFieldStatuses: addr + 4 (naturally aligned because 2+2=4)
    # gFieldTimers: addr + 8 (naturally aligned)
    # gBattleTurnCounter: addr + 24
    # So gBattleMovePower = gBattleTurnCounter - 24 = 0x020236F0

    field_statuses_addr = TARGET - 2 - 16  # -18 = FieldTimers(16) + BTC alignment padding? No...
    # Let me be more careful:
    # gFieldStatuses (u32) ends at gFieldStatuses + 4
    # gFieldTimers starts at gFieldStatuses + 4, is 16 bytes -> ends at gFieldStatuses + 20
    # gBattleTurnCounter = gFieldStatuses + 20
    # So gFieldStatuses = gBattleTurnCounter - 20 = 0x02023708 - 20 = 0x020236F4

    computed_layout = {
        "gBattleMovePower (u16)": TARGET - 24,      # 0x020236F0
        "gMoveToLearn (u16)": TARGET - 22,           # 0x020236F2
        "gFieldStatuses (u32)": TARGET - 20,         # 0x020236F4
        "gFieldTimers.mudSportTimer": TARGET - 16,   # 0x020236F8
        "gFieldTimers.waterSportTimer": TARGET - 14,
        "gFieldTimers.wonderRoomTimer": TARGET - 12,
        "gFieldTimers.magicRoomTimer": TARGET - 10,
        "gFieldTimers.trickRoomTimer": TARGET - 8,
        "gFieldTimers.terrainTimer": TARGET - 6,
        "gFieldTimers.gravityTimer": TARGET - 4,
        "gFieldTimers.fairyLockTimer": TARGET - 2,
        "gBattleTurnCounter (u16)": TARGET,
        "gBattlerAbility (u8)": TARGET + 2,
    }

    for name, addr in computed_layout.items():
        n_refs = len(find_all_refs(rom_data, addr))
        existing_name = KNOWN.get(addr, "")
        print(f"  0x{addr:08X}: {n_refs:4d} ROM refs  {name}" + (f"  [{existing_name}]" if existing_name else ""))

    print()

    # Also check gMonSpritesGfxPtr and gBattleSpriteData which are BEFORE gBattleMovePower
    print("  Variables BEFORE gBattleMovePower:")
    pre_vars = {
        "gBattleSpriteDataPtr (ptr)": TARGET - 24 - 4,   # -28
        "gMonSpritesGfxPtr (ptr)": TARGET - 24 - 4 - 4,  # -32
    }
    for name, addr in pre_vars.items():
        n_refs = len(find_all_refs(rom_data, addr))
        existing_name = KNOWN.get(addr, "")
        print(f"  0x{addr:08X}: {n_refs:4d} ROM refs  {name}" + (f"  [{existing_name}]" if existing_name else ""))

    print()

    # =========================================================================
    # PART 3: Check gFieldStatuses candidate
    # gFieldStatuses is a u32 with 15-25 ROM refs typically
    # If gBattleTurnCounter = 0x02023708, gFieldStatuses = 0x020236F4
    # But we previously found gFieldStatuses candidates at 0x02023958 and 0x02023960
    # Those would imply gBattleTurnCounter at 0x0202396C or 0x02023974 (0 refs each)
    # =========================================================================
    print("=" * 90)
    print("  PART 3: Verify gFieldStatuses at the computed address")
    print("=" * 90)
    print()

    fs_addr = TARGET - 20  # 0x020236F4
    fs_refs = find_all_refs(rom_data, fs_addr)
    print(f"  gFieldStatuses computed: 0x{fs_addr:08X} ({len(fs_refs)} ROM refs)")
    if len(fs_refs) > 0:
        print(f"  Refs:")
        for r in fs_refs[:10]:
            print(f"    0x{ROM_BASE + r:08X}")
    print()

    # Also check nearby addresses for higher ref counts
    print("  Scanning 0x020236E0-0x02023720 for ref counts:")
    for addr in range(0x020236E0, 0x02023720, 2):
        n_refs = len(find_all_refs(rom_data, addr))
        if n_refs > 0:
            name = KNOWN.get(addr, "")
            print(f"  0x{addr:08X}: {n_refs:4d} refs  {name}")

    print()

    # =========================================================================
    # PART 4: Alternative — what if gBattleTurnCounter is accessed via
    #         base+offset from a NEARBY variable's address?
    #         Look for any LDRH [Rn, #offset] where Rn holds a known
    #         address and base+offset is in range 0x020236E0-0x02023A00
    # =========================================================================
    print("=" * 90)
    print("  PART 4: Check if 0x02023708 code is HandleEndTurnOrder or battle script")
    print("=" * 90)
    print()

    # The function containing the increment at 0x0805B30A — let's identify it better
    inc_pos = 0x0005B30A  # ROM offset of LDR R3, =0x02023708

    # Walk backward to find PUSH
    pos = inc_pos
    push_count = 0
    pushes_found = []
    while pos >= max(0, inc_pos - 16000):
        ci = read_u16_le(rom_data, pos)
        if (ci & 0xFF00) == 0xBD00:
            # Found POP PC — boundary. Next PUSH after this is our function
            search = pos + 2
            while search < inc_pos:
                si = read_u16_le(rom_data, search)
                if (si & 0xFF00) == 0xB500:
                    pushes_found.append(search)
                    break
                search += 2
            if pushes_found:
                break
        pos -= 2

    if pushes_found:
        func_start = pushes_found[-1]
        print(f"  Enclosing function PUSH at 0x{ROM_BASE + func_start:08X}")
        print(f"  Distance from PUSH to increment: {inc_pos - func_start} bytes")

        # Find function end (POP PC)
        pos = inc_pos
        while pos < min(len(rom_data) - 1, inc_pos + 8000):
            ci = read_u16_le(rom_data, pos)
            if (ci & 0xFF00) == 0xBD00:
                func_end = pos + 2
                break
            pos += 2
        else:
            func_end = inc_pos + 100

        func_size = func_end - func_start
        print(f"  Function size: {func_size} bytes (0x{ROM_BASE + func_start:08X} - 0x{ROM_BASE + func_end:08X})")
        print()

        # Show the function from PUSH to the increment area + POP
        # If it's a small function, that supports HandleEndTurnOrder
        if func_size < 200:
            print("  *** SMALL FUNCTION — likely HandleEndTurnOrder! ***")
            print()
            pos = func_start
            while pos < func_end + 32:
                desc, length = disasm_thumb(rom_data, pos)
                addr = ROM_BASE + pos
                marker = ">>>" if pos == inc_pos else "   "
                print(f"    {marker} {addr:08X}: {desc}")
                pos += length
            print()
        else:
            # Large function — show context around the increment
            print(f"  Large function ({func_size} bytes)")
            print()

            # Check what EWRAM addresses this function references
            print("  EWRAM addresses in the enclosing function:")
            ewram_in_func = {}
            pos = func_start
            while pos < func_end and pos + 1 < len(rom_data):
                ci = read_u16_le(rom_data, pos)
                if (ci & 0xF800) == 0x4800:
                    rd, val = get_ldr_pool_value(rom_data, pos)
                    if val is not None and 0x02000000 <= val < 0x04000000:
                        if val not in ewram_in_func:
                            ewram_in_func[val] = 0
                        ewram_in_func[val] += 1
                pos += 2

            for addr in sorted(ewram_in_func.keys()):
                total = len(find_all_refs(rom_data, addr))
                name = KNOWN.get(addr, "")
                print(f"    0x{addr:08X}: {ewram_in_func[addr]} in-func, {total} total  {name}")
            print()

    # =========================================================================
    # PART 5: Check the second ref location
    # =========================================================================
    print("=" * 90)
    print("  PART 5: Analyze both literal pool refs")
    print("=" * 90)
    print()

    for idx, ref_off in enumerate(refs):
        ref_addr = ROM_BASE + ref_off
        print(f"  --- Ref [{idx}] at 0x{ref_addr:08X} ---")

        # Find LDR users
        for scan in range(max(0, ref_off - 4096), ref_off, 2):
            ci = read_u16_le(rom_data, scan)
            if (ci & 0xF800) == 0x4800:
                rd = (ci >> 8) & 7
                imm8 = ci & 0xFF
                scan_addr = ROM_BASE + scan
                pa = ((scan_addr + 4) & ~3) + imm8 * 4
                if pa == ref_addr:
                    print(f"  LDR R{rd} at 0x{scan_addr:08X}")

                    # Disassemble 20 instructions around
                    ctx_start = max(0, scan - 40)
                    ctx_end = min(len(rom_data) - 1, scan + 60)
                    pos = ctx_start
                    while pos < ctx_end:
                        desc, length = disasm_thumb(rom_data, pos)
                        addr = ROM_BASE + pos
                        marker = ">>>" if pos == scan else "   "
                        print(f"    {marker} {addr:08X}: {desc}")
                        pos += length
                    print()

    # =========================================================================
    # PART 6: Search EWRAM range for alternate gBattleTurnCounter candidates
    #         with EXACTLY 2 ROM refs (the expected count)
    # =========================================================================
    print("=" * 90)
    print("  PART 6: ALL EWRAM addresses with exactly 2 ROM refs in battle range")
    print("=" * 90)
    print()

    for addr in range(0x020236E0, 0x02023A20, 2):
        n_refs = len(find_all_refs(rom_data, addr))
        if n_refs == 2:
            name = KNOWN.get(addr, "")
            print(f"  0x{addr:08X}: 2 refs  {name}")
            # Show where the refs are
            for r in find_all_refs(rom_data, addr):
                print(f"    at ROM 0x{ROM_BASE + r:08X}")

    print()
    print("  DONE")


if __name__ == "__main__":
    main()
