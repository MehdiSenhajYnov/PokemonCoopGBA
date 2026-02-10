#!/usr/bin/env python3
"""
Find BattleMainCB1 in the Pokemon Run & Bun ROM.

BattleMainCB1 from pokeemerald-expansion decomp:
    static void BattleMainCB1(void) {
        u32 battler;
        gBattleMainFunc();
        for (battler = 0; battler < gBattlersCount; battler++)
            gBattlerControllerFuncs[battler](battler);
    }

Known addresses:
- gBattleTypeFlags = 0x02023364
- gActiveBattler = 0x020233E0
- gBattleControllerExecFlags = 0x020233DC
- gBattleCommunication = 0x0202370E
- gBattleResources = 0x02023A18
- SetMainCallback2 = 0x08000544
- BattleMainCB2 = 0x0803816D
- gMain.callback1 = 0x030022C0
- CB2_InitBattleInternal = 0x08036D01
- Jump table starts at 0x08036D44
"""

import struct
import sys
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses
KNOWN = {
    "gBattleTypeFlags":          0x02023364,
    "gActiveBattler":            0x020233E0,
    "gBattleControllerExecFlags":0x020233DC,
    "gBattleCommunication":      0x0202370E,
    "gBattleResources":          0x02023A18,
    "SetMainCallback2":          0x08000544,
    "BattleMainCB2":             0x0803816D,
    "gMain_callback1":           0x030022C0,
    "gMain_callback2":           0x030022C4,  # callback2 is +4 after callback1 typically
}

# Reverse lookup for addresses
ADDR_NAMES = {}
for name, addr in KNOWN.items():
    ADDR_NAMES[addr] = name
    ADDR_NAMES[addr & ~1] = name  # without THUMB bit
    ADDR_NAMES[addr | 1] = name   # with THUMB bit


def read_rom(path):
    with open(path, "rb") as f:
        return f.read()


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def s16(data, offset):
    return struct.unpack_from("<h", data, offset)[0]


def addr_name(addr):
    """Return a name for a known address, or hex string."""
    if addr in ADDR_NAMES:
        return f"{ADDR_NAMES[addr]} (0x{addr:08X})"
    return f"0x{addr:08X}"


def decode_thumb_bl(hw1, hw2):
    """Decode a THUMB BL instruction pair. Returns target offset or None."""
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) == 0xF800:
        # BL encoding
        offset_hi = hw1 & 0x07FF
        offset_lo = hw2 & 0x07FF
        # Sign extend the high part
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800
            offset_hi = offset_hi - 0x100000000 if offset_hi > 0x7FFFFFFF else offset_hi
            # Actually let's do proper sign extension
        offset_hi_signed = offset_hi if offset_hi < 0x400 else offset_hi - 0x800
        offset = (offset_hi_signed << 12) | (offset_lo << 1)
        return offset
    return None


def disassemble_thumb(rom, rom_offset, size, base_addr=None):
    """
    Simple THUMB disassembler for the instructions we care about.
    Returns list of (offset, raw_hw, description) tuples.
    """
    if base_addr is None:
        base_addr = 0x08000000 + rom_offset

    result = []
    i = 0
    while i < size:
        hw = u16(rom, rom_offset + i)
        pc = base_addr + i
        desc = f"0x{hw:04X}"

        # PUSH {Rlist, LR}
        if (hw & 0xFF00) == 0xB500:
            regs = []
            for r in range(8):
                if hw & (1 << r):
                    regs.append(f"R{r}")
            regs.append("LR")
            desc = f"PUSH {{{', '.join(regs)}}}"

        # POP {Rlist, PC}
        elif (hw & 0xFF00) == 0xBD00:
            regs = []
            for r in range(8):
                if hw & (1 << r):
                    regs.append(f"R{r}")
            regs.append("PC")
            desc = f"POP {{{', '.join(regs)}}}"

        # POP {Rlist} (no PC)
        elif (hw & 0xFF00) == 0xBC00:
            regs = []
            for r in range(8):
                if hw & (1 << r):
                    regs.append(f"R{r}")
            desc = f"POP {{{', '.join(regs)}}}"

        # MOV Rd, #imm8
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"MOV R{rd}, #0x{imm:02X} (={imm})"

        # CMP Rn, #imm8
        elif (hw & 0xF800) == 0x2800:
            rn = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"CMP R{rn}, #0x{imm:02X} (={imm})"

        # ADD Rd, #imm8
        elif (hw & 0xF800) == 0x3000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"ADD R{rd}, #0x{imm:02X} (={imm})"

        # SUB Rd, #imm8
        elif (hw & 0xF800) == 0x3800:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"SUB R{rd}, #0x{imm:02X}"

        # LDR Rd, [PC, #imm8*4]  (literal pool load)
        elif (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            load_pc = (pc + 4) & ~3  # PC is +4 and word-aligned
            load_addr = load_pc + imm
            load_rom_off = load_addr - 0x08000000
            if 0 <= load_rom_off < len(rom) - 4:
                val = u32(rom, load_rom_off)
                val_name = addr_name(val)
                desc = f"LDR R{rd}, [PC, #0x{imm:X}] -> [{addr_name(load_addr)}] = {val_name}"
            else:
                desc = f"LDR R{rd}, [PC, #0x{imm:X}] -> [0x{load_addr:08X}]"

        # LDR Rd, [Rn, #imm5*4]
        elif (hw & 0xF800) == 0x6800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = ((hw >> 6) & 0x1F) * 4
            desc = f"LDR R{rd}, [R{rn}, #0x{imm:X}]"

        # STR Rd, [Rn, #imm5*4]
        elif (hw & 0xF800) == 0x6000:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = ((hw >> 6) & 0x1F) * 4
            desc = f"STR R{rd}, [R{rn}, #0x{imm:X}]"

        # LDRB Rd, [Rn, #imm5]
        elif (hw & 0xF800) == 0x7800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = (hw >> 6) & 0x1F
            desc = f"LDRB R{rd}, [R{rn}, #0x{imm:X}]"

        # STRB Rd, [Rn, #imm5]
        elif (hw & 0xF800) == 0x7000:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = (hw >> 6) & 0x1F
            desc = f"STRB R{rd}, [R{rn}, #0x{imm:X}]"

        # LDRH Rd, [Rn, #imm5*2]
        elif (hw & 0xF800) == 0x8800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = ((hw >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rn}, #0x{imm:X}]"

        # LDR Rd, [Rn, Rm]
        elif (hw & 0xFE00) == 0x5800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            rm = (hw >> 6) & 7
            desc = f"LDR R{rd}, [R{rn}, R{rm}]"

        # ADD Rd, Rn, Rm (format 2)
        elif (hw & 0xFE00) == 0x1800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            rm = (hw >> 6) & 7
            desc = f"ADD R{rd}, R{rn}, R{rm}"

        # SUB Rd, Rn, Rm
        elif (hw & 0xFE00) == 0x1A00:
            rd = hw & 7
            rn = (hw >> 3) & 7
            rm = (hw >> 6) & 7
            desc = f"SUB R{rd}, R{rn}, R{rm}"

        # ADD Rd, Rn, #imm3
        elif (hw & 0xFE00) == 0x1C00:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = (hw >> 6) & 7
            desc = f"ADD R{rd}, R{rn}, #0x{imm:X}"

        # LSL Rd, Rm, #imm5
        elif (hw & 0xF800) == 0x0000:
            rd = hw & 7
            rm = (hw >> 3) & 7
            imm = (hw >> 6) & 0x1F
            if imm == 0 and rd == rm:
                desc = f"NOP (LSL R{rd}, R{rm}, #0)"
            else:
                desc = f"LSL R{rd}, R{rm}, #{imm}"

        # LSR Rd, Rm, #imm5
        elif (hw & 0xF800) == 0x0800:
            rd = hw & 7
            rm = (hw >> 3) & 7
            imm = (hw >> 6) & 0x1F
            desc = f"LSR R{rd}, R{rm}, #{imm}"

        # BX Rm
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            desc = f"BX R{rm}"

        # BLX Rm
        elif (hw & 0xFF80) == 0x4780:
            rm = (hw >> 3) & 0xF
            desc = f"BLX R{rm}"

        # MOV Rd, Rm (high register operations)
        elif (hw & 0xFF00) == 0x4600:
            rd = (hw & 7) | ((hw >> 4) & 8)
            rm = (hw >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"

        # ADD Rd, Rm (high register)
        elif (hw & 0xFF00) == 0x4400:
            rd = (hw & 7) | ((hw >> 4) & 8)
            rm = (hw >> 3) & 0xF
            desc = f"ADD R{rd}, R{rm}"

        # CMP Rn, Rm (high register)
        elif (hw & 0xFF00) == 0x4500:
            rn = (hw & 7) | ((hw >> 4) & 8)
            rm = (hw >> 3) & 0xF
            desc = f"CMP R{rn}, R{rm}"

        # ALU operations
        elif (hw & 0xFC00) == 0x4000:
            op = (hw >> 6) & 0xF
            rd = hw & 7
            rm = (hw >> 3) & 7
            ops = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                   "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            desc = f"{ops[op]} R{rd}, R{rm}"

        # B (unconditional)
        elif (hw & 0xF800) == 0xE000:
            offset = hw & 0x7FF
            if offset & 0x400:
                offset = offset - 0x800
            target = pc + 4 + offset * 2
            desc = f"B 0x{target:08X}"

        # Bcc (conditional)
        elif (hw & 0xF000) == 0xD000:
            cond = (hw >> 8) & 0xF
            offset = hw & 0xFF
            if offset & 0x80:
                offset = offset - 0x100
            target = pc + 4 + offset * 2
            conds = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                     "BHI","BLS","BGE","BLT","BGT","BLE","B??","SWI"]
            desc = f"{conds[cond]} 0x{target:08X}"

        # BL (two halfwords)
        elif (hw & 0xF800) == 0xF000:
            if i + 2 < size:
                hw2 = u16(rom, rom_offset + i + 2)
                bl_offset = decode_thumb_bl(hw, hw2)
                if bl_offset is not None:
                    target = pc + 4 + bl_offset
                    target_name = addr_name(target) if (target | 1) in ADDR_NAMES or target in ADDR_NAMES else f"0x{target:08X}"
                    desc = f"BL {target_name}"
                    result.append((i, pc, hw, desc))
                    i += 2
                    hw2_entry = u16(rom, rom_offset + i)
                    result.append((i, base_addr + i, hw2_entry, f"  (BL second halfword)"))
                    i += 2
                    continue
            desc = f"BL prefix 0x{hw:04X}"

        # ADD Rd, SP, #imm8*4
        elif (hw & 0xFF00) == 0xA800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            desc = f"ADD R{rd}, SP, #0x{imm:X}"

        # ADD Rd, PC, #imm8*4
        elif (hw & 0xFF00) == 0xA000:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            desc = f"ADD R{rd}, PC, #0x{imm:X}"

        # ADD SP, #imm7*4
        elif (hw & 0xFF80) == 0xB000:
            imm = (hw & 0x7F) * 4
            desc = f"ADD SP, #0x{imm:X}"

        # SUB SP, #imm7*4
        elif (hw & 0xFF80) == 0xB080:
            imm = (hw & 0x7F) * 4
            desc = f"SUB SP, #0x{imm:X}"

        # STMIA / LDMIA
        elif (hw & 0xF000) == 0xC000:
            load = (hw >> 11) & 1
            rn = (hw >> 8) & 7
            regs = []
            for r in range(8):
                if hw & (1 << r):
                    regs.append(f"R{r}")
            op = "LDMIA" if load else "STMIA"
            desc = f"{op} R{rn}!, {{{', '.join(regs)}}}"

        result.append((i, pc, hw, desc))
        i += 2

    return result


def print_disasm(entries, title=""):
    if title:
        print(f"\n{'='*70}")
        print(f"  {title}")
        print(f"{'='*70}")
    for offset, pc, hw, desc in entries:
        print(f"  +{offset:04X}  0x{pc:08X}:  {hw:04X}  {desc}")


def find_literal_pool_refs(rom, target_addr, search_start, search_size):
    """Find all LDR Rd, [PC, #imm] that load a specific value from literal pool."""
    results = []
    for i in range(0, search_size, 2):
        off = search_start + i
        if off + 2 > len(rom):
            break
        hw = u16(rom, off)
        if (hw & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc = 0x08000000 + off
            load_pc = (pc + 4) & ~3
            load_addr_rom = (load_pc + imm) - 0x08000000
            if 0 <= load_addr_rom < len(rom) - 4:
                val = u32(rom, load_addr_rom)
                if val == target_addr:
                    results.append((off, pc, rd, load_addr_rom))
    return results


def scan_for_battlemain_cb1_pattern(rom):
    """
    Search ROM for BattleMainCB1-like function:
    - PUSH {LR} or PUSH {Rlist, LR}
    - Loads a function pointer from EWRAM (gBattleMainFunc) and BX/BLX to it
    - Loops calling gBattlerControllerFuncs[battler](battler)
    - Small function (30-60 bytes)

    Pattern:
    1. PUSH {some regs, LR}
    2. LDR Rx, [PC, #imm]  -> gBattleMainFunc address
    3. LDR Rx, [Rx]         -> read the function pointer
    4. BLX Rx or BX Rx      -> call it
    5. LDR Rx, [PC, #imm]  -> gBattlersCount address
    6. LDR Ry, [PC, #imm]  -> gBattlerControllerFuncs address
    7. Loop with CMP and BLT/BCC
    8. POP {PC}
    """
    print("\n" + "=" * 70)
    print("  PART 6: Scanning ROM for BattleMainCB1 pattern")
    print("=" * 70)

    candidates = []

    # Strategy: look for small functions that have:
    # - PUSH {LR} or PUSH {regs, LR} at start
    # - At least 2 BLX instructions (one for gBattleMainFunc, one inside the loop)
    # - A loop (conditional branch backwards)
    # - POP {PC} at end
    # - Total size < 80 bytes
    # - References to EWRAM addresses (0x020xxxxx) via literal pool

    # More targeted: search for functions that load from EWRAM pointers and BLX
    # gBattleMainFunc is a function pointer in EWRAM, so the code will:
    # LDR R0, =gBattleMainFunc  (EWRAM addr)
    # LDR R0, [R0]              (read the pointer)
    # BLX R0                    (call it)

    # Also, gBattlerControllerFuncs is an array of function pointers in EWRAM
    # The loop does:
    # LDR R0, =gBattlerControllerFuncs
    # LDR R1, [R0, R2]  (where R2 = battler * 4)
    # BLX R1

    # Let's look for PUSH...BLX...BLX...POP patterns in reasonable range
    # Battle code is around 0x030000-0x0A0000 in ROM offset

    search_start = 0x030000
    search_end = 0x0A0000

    for off in range(search_start, search_end, 2):
        hw = u16(rom, off)
        # Must start with PUSH {... LR}
        if (hw & 0xFF00) != 0xB500:
            continue

        # Scan next 80 bytes for the pattern
        func_size = 80
        if off + func_size > len(rom):
            continue

        blx_count = 0
        bx_count = 0
        pop_pc_off = None
        ldr_pc_count = 0
        ewram_refs = []
        has_backward_branch = False
        has_ldr_indirect = False  # LDR Rx, [Ry] or LDR Rx, [Ry, Rz]

        for j in range(2, func_size, 2):
            h = u16(rom, off + j)
            pc = 0x08000000 + off + j

            # BLX Rm
            if (h & 0xFF80) == 0x4780:
                blx_count += 1

            # BX Rm (not BX LR which is return)
            if (h & 0xFF80) == 0x4700:
                rm = (h >> 3) & 0xF
                if rm != 14:  # not LR
                    bx_count += 1

            # POP {PC}
            if (h & 0xFF00) == 0xBD00:
                pop_pc_off = j
                break  # end of function

            # LDR Rd, [PC, #imm] - literal pool
            if (h & 0xF800) == 0x4800:
                ldr_pc_count += 1
                rd = (h >> 8) & 7
                imm = (h & 0xFF) * 4
                load_pc = (pc + 4) & ~3
                load_addr_rom = (load_pc + imm) - 0x08000000
                if 0 <= load_addr_rom < len(rom) - 4:
                    val = u32(rom, load_addr_rom)
                    if (val & 0xFF000000) == 0x02000000:
                        ewram_refs.append(val)

            # LDR Rd, [Rn] (offset 0) or LDR Rd, [Rn, Rm]
            if (h & 0xF800) == 0x6800 and ((h >> 6) & 0x1F) == 0:
                has_ldr_indirect = True
            if (h & 0xFE00) == 0x5800:
                has_ldr_indirect = True

            # Backward conditional branch
            if (h & 0xF000) == 0xD000:
                cond = (h >> 8) & 0xF
                soff = h & 0xFF
                if soff & 0x80:
                    has_backward_branch = True

        if pop_pc_off is None:
            continue

        actual_size = pop_pc_off + 2

        # BattleMainCB1 criteria:
        # - Has at least 2 BLX (one for gBattleMainFunc, at least one in loop)
        #   OR 1 BLX + 1 BX
        # - Has backward branch (loop)
        # - Has indirect load (reading function pointer from EWRAM)
        # - Has EWRAM references (gBattleMainFunc, gBattlerControllerFuncs, gBattlersCount)
        # - Size between 20 and 70 bytes

        call_count = blx_count + bx_count
        if (call_count >= 2 and
            has_backward_branch and
            has_ldr_indirect and
            len(ewram_refs) >= 2 and
            20 <= actual_size <= 70):

            rom_addr = 0x08000000 + off
            candidates.append((off, rom_addr, actual_size, blx_count, bx_count, ewram_refs))

    print(f"\nFound {len(candidates)} candidates matching BattleMainCB1 pattern")

    for idx, (off, addr, size, blx_c, bx_c, ewram) in enumerate(candidates):
        print(f"\n--- Candidate {idx+1}: 0x{addr:08X} (THUMB: 0x{addr|1:08X}), size={size} bytes ---")
        print(f"    BLX count: {blx_c}, BX count: {bx_c}")
        print(f"    EWRAM refs: {[f'0x{e:08X}' for e in ewram]}")

        entries = disassemble_thumb(rom, off, size + 32)  # +32 for literal pool
        print_disasm(entries, f"Candidate {idx+1} disassembly")

    return candidates


def main():
    print(f"Loading ROM: {ROM_PATH}")
    rom = read_rom(ROM_PATH)
    print(f"ROM size: {len(rom)} bytes ({len(rom)/(1024*1024):.1f} MB)")

    # =========================================================================
    # PART 1: Read jump table entry 18 at cart0 offset 0x036D8C
    # =========================================================================
    print("\n" + "=" * 70)
    print("  PART 1: Jump table entry 18 of CB2_InitBattleInternal")
    print("=" * 70)

    jt_offset = 0x036D8C  # 0x036D44 + 18*4
    jt_entry = u32(rom, jt_offset)
    print(f"  Jump table base:   0x08036D44")
    print(f"  Entry 18 offset:   0x{jt_offset:08X}")
    print(f"  Entry 18 value:    0x{jt_entry:08X}")

    # Also read nearby entries for context
    print(f"\n  Jump table entries around index 18:")
    jt_base = 0x036D44
    for idx in range(max(0, 16), 22):
        entry_off = jt_base + idx * 4
        if entry_off + 4 <= len(rom):
            entry_val = u32(rom, entry_off)
            marker = " <-- entry 18" if idx == 18 else ""
            print(f"    [{idx:2d}] 0x{entry_off:08X}: 0x{entry_val:08X}{marker}")

    # =========================================================================
    # PART 2: Disassemble the state 18 handler
    # =========================================================================
    state18_rom_offset = (jt_entry & ~1) - 0x08000000  # strip THUMB bit
    state18_addr = jt_entry & ~1

    print(f"\n  State 18 handler at ROM offset: 0x{state18_rom_offset:08X}")
    print(f"  State 18 handler address:       0x{state18_addr:08X} (THUMB: 0x{jt_entry:08X})")

    entries = disassemble_thumb(rom, state18_rom_offset, 256)
    print_disasm(entries, "PART 2: State 18 handler disassembly (256 bytes)")

    # =========================================================================
    # PART 3: Find SetMainCallback2 calls and what's passed as argument
    # =========================================================================
    print("\n" + "=" * 70)
    print("  PART 3: Analyzing SetMainCallback2 calls in state 18 handler")
    print("=" * 70)

    for offset, pc, hw, desc in entries:
        if "BL" in desc and "SetMainCallback2" in desc:
            print(f"\n  Found BL SetMainCallback2 at 0x{pc:08X}")
            # Look backwards for what was loaded into R0
            # SetMainCallback2(callback) takes R0 as first arg
            for prev_offset, prev_pc, prev_hw, prev_desc in entries:
                if prev_pc < pc and prev_pc >= pc - 20:  # within last 10 instructions
                    if "LDR R0" in prev_desc:
                        print(f"    R0 loaded at 0x{prev_pc:08X}: {prev_desc}")

        if "BL" in desc and "0x08000544" in desc:
            print(f"\n  Found BL to 0x08000544 (SetMainCallback2) at 0x{pc:08X}")
            for prev_offset, prev_pc, prev_hw, prev_desc in entries:
                if prev_pc < pc and prev_pc >= pc - 20:
                    if "LDR R0" in prev_desc:
                        print(f"    R0 loaded at 0x{prev_pc:08X}: {prev_desc}")

    # =========================================================================
    # PART 4: Find writes to gMain.callback1 (0x030022C0)
    # =========================================================================
    print("\n" + "=" * 70)
    print("  PART 4: Searching for gMain.callback1 (0x030022C0) references")
    print("=" * 70)

    # Check literal pool in the state 18 handler area
    for offset, pc, hw, desc in entries:
        if "030022C0" in desc or "callback1" in desc.lower():
            print(f"  Found ref at 0x{pc:08X}: {desc}")

    # Also search the literal pool area (after the code, aligned to 4)
    print(f"\n  Scanning literal pool after state 18 handler:")
    pool_start = state18_rom_offset
    pool_end = min(state18_rom_offset + 512, len(rom) - 4)
    for off in range(pool_start, pool_end, 4):
        val = u32(rom, off)
        if val == 0x030022C0:
            print(f"    Found 0x030022C0 at ROM offset 0x{off:08X} (addr 0x{0x08000000+off:08X})")
        if val == 0x030022C4:
            print(f"    Found 0x030022C4 (callback2) at ROM offset 0x{off:08X} (addr 0x{0x08000000+off:08X})")

    # =========================================================================
    # PART 5: Look for BattleMainCB1 in literal pool near state 18 handler
    # =========================================================================
    print("\n" + "=" * 70)
    print("  PART 5: Looking for function pointers in literal pool")
    print("=" * 70)

    # Find all values loaded via LDR Rx, [PC, #imm] in the state 18 handler
    loaded_values = []
    for offset, pc, hw, desc in entries:
        if "LDR R" in desc and "[PC," in desc and "-> [" in desc:
            # Extract the loaded value
            parts = desc.split("= ")
            if len(parts) >= 2:
                val_str = parts[-1].strip()
                if val_str.startswith("0x"):
                    try:
                        val = int(val_str, 16)
                        loaded_values.append((pc, val, desc))
                    except:
                        pass
                elif "(" in val_str:
                    # Named value like "BattleMainCB2 (0x0803816D)"
                    hex_part = val_str.split("(")[1].rstrip(")")
                    try:
                        val = int(hex_part, 16)
                        loaded_values.append((pc, val, desc))
                    except:
                        pass

    print(f"\n  Values loaded from literal pool in state 18 handler:")
    for pc, val, desc in loaded_values:
        region = "ROM" if (val & 0xFF000000) == 0x08000000 else \
                 "EWRAM" if (val & 0xFF000000) == 0x02000000 else \
                 "IWRAM" if (val & 0xFF000000) == 0x03000000 else \
                 "I/O" if (val & 0xFF000000) == 0x04000000 else "???"
        name = addr_name(val)
        print(f"    0x{pc:08X}: loads 0x{val:08X} ({region}) {name}")

        # If it's a ROM function pointer, disassemble a bit to see what it is
        if (val & 0xFF000000) == 0x08000000 and val not in [v for _,v in KNOWN.items()]:
            func_off = (val & ~1) - 0x08000000
            if 0 <= func_off < len(rom) - 64:
                print(f"      Disassembly of 0x{val:08X}:")
                func_entries = disassemble_thumb(rom, func_off, 64)
                for fo, fpc, fhw, fdesc in func_entries:
                    print(f"        +{fo:04X}  0x{fpc:08X}:  {fhw:04X}  {fdesc}")
                    # Stop at POP {PC} or BX LR
                    if "POP" in fdesc and "PC" in fdesc:
                        break
                    if fdesc == "BX R14":
                        break

    # =========================================================================
    # PART 6: Pattern-based ROM scan for BattleMainCB1
    # =========================================================================
    candidates = scan_for_battlemain_cb1_pattern(rom)

    # =========================================================================
    # PART 7: Alternative approach - find functions that reference both
    #         a gBattleMainFunc-like address AND gBattlerControllerFuncs-like address
    # =========================================================================
    print("\n" + "=" * 70)
    print("  PART 7: Searching for gBattleMainFunc and gBattlerControllerFuncs")
    print("=" * 70)

    # In the decomp, gBattleMainFunc and gBattlerControllerFuncs are near other battle vars
    # gBattleTypeFlags = 0x02023364
    # gActiveBattler = 0x020233E0
    # These are in the 0x0202xxxx range

    # Strategy: find all LDR Rd, [PC, #imm] in battle code area that load EWRAM addresses
    # near the known battle variables, then look for functions that:
    # 1. Load an EWRAM addr, dereference it (function pointer), and BLX
    # 2. Have a loop with another EWRAM addr (array of function pointers)

    # Let's find gBattlersCount first - it should be near gActiveBattler (0x020233E0)
    # In vanilla emerald, gBattlersCount is right after gActiveBattler
    # Let's check common offsets

    print("\n  Looking for gBattlersCount (should be near gActiveBattler=0x020233E0):")
    # Search for literal pool entries loading addresses near 0x020233E0
    for test_addr in [0x020233E1, 0x020233E2, 0x020233E4, 0x020233E8,
                      0x020233D8, 0x020233D4, 0x020233D0]:
        refs = find_literal_pool_refs(rom, test_addr, 0x030000, 0x070000)
        if refs:
            print(f"    0x{test_addr:08X}: {len(refs)} ROM refs")

    # Also check near gBattleControllerExecFlags (0x020233DC)
    print("\n  Looking for gBattlerControllerFuncs (should be near gBattleControllerExecFlags=0x020233DC):")
    for delta in range(-0x40, 0x40, 4):
        test_addr = 0x020233DC + delta
        refs = find_literal_pool_refs(rom, test_addr, 0x030000, 0x070000)
        if len(refs) > 0 and len(refs) <= 30:  # Not too many, not zero
            print(f"    0x{test_addr:08X} (delta={delta:+d}): {len(refs)} ROM refs")

    # Find gBattleMainFunc - it's a single function pointer, probably referenced 2-5 times
    print("\n  Looking for gBattleMainFunc (single function pointer, few refs):")
    for delta in range(-0x100, 0x100, 4):
        test_addr = 0x020233DC + delta
        if test_addr < 0x02000000:
            continue
        refs = find_literal_pool_refs(rom, test_addr, 0x030000, 0x070000)
        if 2 <= len(refs) <= 8:
            # Check if any of these refs are in small functions with BLX
            for ref_off, ref_pc, ref_rd, _ in refs[:3]:
                # Check nearby for BLX after LDR [Rn]
                context_start = max(0, ref_off - 20)
                has_blx_nearby = False
                for k in range(ref_off, min(ref_off + 20, len(rom) - 2), 2):
                    h = u16(rom, k)
                    if (h & 0xFF80) == 0x4780:  # BLX Rm
                        has_blx_nearby = True
                        break
                if has_blx_nearby:
                    print(f"    0x{test_addr:08X} (delta={delta:+d}): {len(refs)} refs, BLX nearby at ref 0x{ref_pc:08X}")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  State 18 handler: 0x{jt_entry:08X}")
    print(f"  Pattern scan candidates: {len(candidates)}")
    if candidates:
        for idx, (off, addr, size, blx_c, bx_c, ewram) in enumerate(candidates):
            print(f"    Candidate {idx+1}: 0x{addr|1:08X} (size={size}, BLX={blx_c}, BX={bx_c})")
            print(f"      EWRAM refs: {[f'0x{e:08X}' for e in ewram]}")


if __name__ == "__main__":
    main()
