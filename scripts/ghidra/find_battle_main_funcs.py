#!/usr/bin/env python3
"""
Find TryDoEventsBeforeFirstTurn and HandleTurnActionSelectionState in Pokemon Run & Bun ROM.

Strategy:
  1. DoBattleIntro is at 0x0803ACB1 (ROM offset 0x03ACB0).
  2. Near the END of DoBattleIntro, it sets gBattleMainFunc = TryDoEventsBeforeFirstTurn.
     gBattleMainFunc is stored at IWRAM 0x03005D04.
  3. Scan DoBattleIntro's literal pools for references to 0x03005D04.
     The value stored TO gBattleMainFunc via STR = TryDoEventsBeforeFirstTurn address.
  4. Then repeat: scan TryDoEventsBeforeFirstTurn for the same pattern to find
     HandleTurnActionSelectionState.

All code is THUMB (16-bit instructions).
Function pointers have bit 0 set (THUMB bit) in literal pool values.
"""

import struct
import sys
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known addresses
DO_BATTLE_INTRO_ROM_OFFSET = 0x03ACB0  # ROM file offset (address 0x0803ACB1 with THUMB bit)
G_BATTLE_MAIN_FUNC = 0x03005D04       # IWRAM address where gBattleMainFunc is stored


# =============================================================================
# Low-level ROM helpers
# =============================================================================

def read_u16(data, offset):
    if offset + 2 > len(data):
        return 0
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    if offset + 4 > len(data):
        return 0
    return struct.unpack_from('<I', data, offset)[0]


# =============================================================================
# THUMB disassembler (minimal, focused on what we need)
# =============================================================================

COND_NAMES = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
              "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]

def decode_bl_target(rom_data, pos):
    """Decode THUMB BL at pos, return target ROM address."""
    if pos + 4 > len(rom_data):
        return None
    hi = read_u16(rom_data, pos)
    lo = read_u16(rom_data, pos + 2)
    if (hi & 0xF800) != 0xF000 or (lo & 0xF800) != 0xF800:
        return None
    full = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    if full >= 0x400000:
        full -= 0x800000
    return ROM_BASE + pos + 4 + full


def disassemble_thumb(rom_data, start, end):
    """Disassemble THUMB code. Returns list of (rom_offset, addr, raw_hex, mnemonic)."""
    lines = []
    pos = start
    while pos < end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        addr = ROM_BASE + pos
        raw = f"{instr:04X}"
        mnem = ""

        # PUSH
        if (instr & 0xFE00) == 0xB400:
            lr = (instr >> 8) & 1
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if lr: regs.append("LR")
            mnem = f"PUSH {{{', '.join(regs)}}}"

        # POP
        elif (instr & 0xFE00) == 0xBC00:
            pc = (instr >> 8) & 1
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if pc: regs.append("PC")
            mnem = f"POP {{{', '.join(regs)}}}"

        # MOV Rd, #imm
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            mnem = f"MOV R{rd}, #{imm} (0x{imm:02X})"

        # CMP Rn, #imm
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7
            imm = instr & 0xFF
            mnem = f"CMP R{rn}, #{imm} (0x{imm:02X})"

        # ADD Rd, #imm
        elif (instr & 0xF800) == 0x3000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            mnem = f"ADD R{rd}, #{imm}"

        # SUB Rd, #imm
        elif (instr & 0xF800) == 0x3800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            mnem = f"SUB R{rd}, #{imm}"

        # LDR Rd, [PC, #imm] (literal pool)
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_off)
                mnem = f"LDR R{rd}, =0x{val:08X}"
            else:
                mnem = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"

        # LDR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            mnem = f"LDR R{rd}, [R{rn}, #{imm}]"

        # STR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            mnem = f"STR R{rd}, [R{rn}, #{imm}]"

        # LDRB Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x7800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            mnem = f"LDRB R{rd}, [R{rn}, #{imm}]"

        # STRB Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x7000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            mnem = f"STRB R{rd}, [R{rn}, #{imm}]"

        # LDRH Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x8800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            mnem = f"LDRH R{rd}, [R{rn}, #{imm}]"

        # STRH Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x8000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            mnem = f"STRH R{rd}, [R{rn}, #{imm}]"

        # LDR/STR Rd, [Rn, Rm]
        elif (instr & 0xFE00) == 0x5800:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"LDR R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5000:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"STR R{rd}, [R{rn}, R{rm}]"

        # ALU format 4
        elif (instr & 0xFC00) == 0x4000:
            op = (instr >> 6) & 0xF; rd = instr & 7; rm = (instr >> 3) & 7
            names = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                     "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            mnem = f"{names[op]} R{rd}, R{rm}"

        # High register ops (format 5)
        elif (instr & 0xFC00) == 0x4400:
            op = (instr >> 8) & 3; h1 = (instr >> 7) & 1; h2 = (instr >> 6) & 1
            rd = (instr & 7) | (h1 << 3); rm = ((instr >> 3) & 7) | (h2 << 3)
            ops = ["ADD","CMP","MOV","BX"]
            mnem = f"{ops[op]} R{rd}, R{rm}"

        # Conditional branch
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF
            soff = instr & 0xFF
            if soff >= 0x80: soff -= 0x100
            target = addr + 4 + soff * 2
            if cond < 0xF:
                mnem = f"{COND_NAMES[cond]} 0x{target:08X}"
            else:
                mnem = f"SVC #{instr & 0xFF}"

        # Unconditional branch
        elif (instr & 0xF800) == 0xE000:
            soff = instr & 0x7FF
            if soff >= 0x400: soff -= 0x800
            target = addr + 4 + soff * 2
            mnem = f"B 0x{target:08X}"

        # BL (32-bit)
        elif (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                target = decode_bl_target(rom_data, pos)
                raw = f"{instr:04X} {next_instr:04X}"
                mnem = f"BL 0x{target:08X}" if target else "BL ???"
                lines.append((pos, addr, raw, mnem))
                pos += 4
                continue

        # SP-relative LDR/STR
        elif (instr & 0xF800) == 0x9800:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            mnem = f"LDR R{rd}, [SP, #0x{imm:X}]"
        elif (instr & 0xF800) == 0x9000:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            mnem = f"STR R{rd}, [SP, #0x{imm:X}]"

        # ADD Rd, PC/SP, #imm
        elif (instr & 0xF800) == 0xA000:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            mnem = f"ADD R{rd}, PC, #0x{imm:X}"
        elif (instr & 0xF800) == 0xA800:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            mnem = f"ADD R{rd}, SP, #0x{imm:X}"

        # SP adjust
        elif (instr & 0xFF00) == 0xB000:
            imm = (instr & 0x7F) * 4
            if instr & 0x80:
                mnem = f"SUB SP, #{imm}"
            else:
                mnem = f"ADD SP, #{imm}"

        # NOP
        elif instr == 0x46C0:
            mnem = "NOP"
        elif instr == 0x0000:
            mnem = "DATA 0x0000"

        # Shifts
        elif (instr & 0xF800) == 0x0000 and instr != 0:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            mnem = f"LSL R{rd}, R{rm}, #{imm5}"
        elif (instr & 0xF800) == 0x0800:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            if imm5 == 0: imm5 = 32
            mnem = f"LSR R{rd}, R{rm}, #{imm5}"
        elif (instr & 0xF800) == 0x1000:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            if imm5 == 0: imm5 = 32
            mnem = f"ASR R{rd}, R{rm}, #{imm5}"

        # ADD/SUB 3-reg / imm3
        elif (instr & 0xFE00) == 0x1800:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"ADD R{rd}, R{rn}, R{rm}"
        elif (instr & 0xFE00) == 0x1A00:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"SUB R{rd}, R{rn}, R{rm}"
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7; rn = (instr >> 3) & 7; imm3 = (instr >> 6) & 7
            mnem = f"ADD R{rd}, R{rn}, #{imm3}"
        elif (instr & 0xFE00) == 0x1E00:
            rd = instr & 7; rn = (instr >> 3) & 7; imm3 = (instr >> 6) & 7
            mnem = f"SUB R{rd}, R{rn}, #{imm3}"

        else:
            mnem = f"??? 0x{instr:04X}"

        lines.append((pos, addr, raw, mnem))
        pos += 2

    return lines


# =============================================================================
# Function boundary helpers
# =============================================================================

def find_function_end(rom_data, func_start, max_size=8192):
    """Find function end by scanning for the LAST POP {PC} or BX LR before a new PUSH {LR}.
    For very large functions (DoBattleIntro is huge), we need to handle multiple POP {PC}
    that are internal exit points (switch/case branches), NOT the real function end."""
    pos = func_start + 2
    limit = min(func_start + max_size, len(rom_data) - 2)
    last_pop_pc = None

    while pos < limit:
        instr = read_u16(rom_data, pos)

        # POP {..., PC} = 0xBDxx
        if (instr & 0xFF00) == 0xBD00:
            last_pop_pc = pos + 2
            # Check if next non-data instruction is a PUSH {LR} = new function
            next_pos = pos + 2
            # Skip potential literal pool data (4-byte aligned words that look like addresses)
            while next_pos < limit:
                next_instr = read_u16(rom_data, next_pos)
                if (next_instr & 0xFF00) == 0xB500:
                    # New function starts here
                    return pos + 2
                # If we see a valid instruction that's NOT data, keep going in this function
                if next_instr != 0x0000 and (next_instr & 0xF800) != 0x4800:
                    break
                next_pos += 2
                if next_pos - pos > 32:  # Don't skip too much potential data
                    break
            pos += 2
            continue

        # BX LR = 0x4770
        if instr == 0x4770:
            last_pop_pc = pos + 2
            if pos + 2 < limit:
                next_instr = read_u16(rom_data, pos + 2)
                if (next_instr & 0xFF00) == 0xB500:
                    return pos + 2
            pos += 2
            continue

        # New PUSH {LR} well past the start = new function
        if (instr & 0xFF00) == 0xB500 and pos > func_start + 4:
            if last_pop_pc is not None:
                return last_pop_pc
            return pos

        # Skip BL 32-bit pairs
        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue

        pos += 2

    return last_pop_pc if last_pop_pc else func_start + max_size


# =============================================================================
# Core analysis: find what value is stored to gBattleMainFunc in a function
# =============================================================================

def find_stores_to_address(rom_data, func_start, func_end, target_iwram_addr):
    """
    Scan a function's code and literal pools to find all STR instructions
    that store a value to the given target address (via literal pool load).

    The pattern is:
        LDR Rx, =<function_pointer>     ; load value to store
        LDR Ry, =<target_iwram_addr>    ; load destination address
        STR Rx, [Ry, #0]                ; store value at destination

    Returns list of (store_offset, value_stored, value_lit_offset) tuples.
    """
    results = []

    # First, build a map of all LDR Rd, [PC, #imm] instructions and their loaded values
    # Key: rom_offset -> (register, value_loaded, literal_pool_offset)
    ldr_pc_map = {}
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)

        # LDR Rd, [PC, #imm] = 0x4800-0x4FFF
        if (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_off)
                ldr_pc_map[pos] = (rd, val, lit_off)

        # Skip BL pairs
        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2

    # Now find the pattern: LDR Rx, =value; LDR Ry, =target; STR Rx, [Ry, #0]
    # The LDR instructions don't have to be immediately adjacent to the STR.
    # We track register state: which register last loaded what value.

    # Simple approach: track last-loaded value per register within a small window
    reg_vals = {}  # register -> (value, literal_pool_offset, load_rom_offset)

    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)

        # Track LDR Rd, [PC, #imm]
        if pos in ldr_pc_map:
            rd, val, lit_off = ldr_pc_map[pos]
            reg_vals[rd] = (val, lit_off, pos)

        # STR Rd, [Rn, #0] = store Rd at address in Rn
        if (instr & 0xF800) == 0x6000:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 4

            if imm == 0 and rn in reg_vals:
                dest_val, _, _ = reg_vals[rn]
                if dest_val == target_iwram_addr:
                    # Found a store to the target address!
                    if rd in reg_vals:
                        stored_val, stored_lit_off, stored_load_pos = reg_vals[rd]
                        results.append((pos, stored_val, stored_lit_off, stored_load_pos))

        # Also handle STR Rd, [Rn, Rm] - less common but possible
        if (instr & 0xFE00) == 0x5000:
            rd = instr & 7
            rn = (instr >> 3) & 7
            rm = (instr >> 6) & 7
            # If Rm is 0 (or we track Rm), this could be a store to target
            # Skip for now - the #0 offset pattern is standard

        # Clear register on MOV/other writes (simplified)
        if (instr & 0xF800) == 0x2000:  # MOV Rd, #imm
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            reg_vals[rd] = (imm, None, pos)

        # BL clobbers R0-R3, LR
        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                for r in [0, 1, 2, 3]:
                    reg_vals.pop(r, None)
                pos += 4
                continue

        # Conditional/unconditional branches - don't clear regs (values may persist)
        # But PUSH/POP can change things
        if (instr & 0xFF00) == 0xBD00:  # POP {PC}
            # End of an exit path - reset tracking
            reg_vals.clear()

        pos += 2

    return results


def find_all_literal_pool_values_for_address(rom_data, func_start, func_end, target_addr):
    """Find all literal pool entries within a function's range that contain target_addr."""
    results = []
    # Literal pools are 4-byte aligned
    for off in range(func_start & ~3, func_end + 256, 4):  # scan past func_end for trailing lit pools
        if off + 4 > len(rom_data):
            break
        val = read_u32(rom_data, off)
        if val == target_addr:
            results.append(off)
    return results


# =============================================================================
# Main analysis
# =============================================================================

def analyze_function(rom_data, func_name, func_rom_offset, search_target_addr):
    """Analyze a function to find what value it stores to search_target_addr.
    Returns the stored value (function pointer) or None."""

    func_start = func_rom_offset
    func_addr = ROM_BASE + func_start + 1  # +1 for THUMB bit

    print(f"\n{'='*80}")
    print(f"  Analyzing: {func_name}")
    print(f"  Address: 0x{func_addr:08X} (ROM offset 0x{func_start:06X})")
    print(f"  Searching for stores to: 0x{search_target_addr:08X} (gBattleMainFunc)")
    print(f"{'='*80}\n")

    # Find function end
    func_end = find_function_end(rom_data, func_start, max_size=8192)
    func_size = func_end - func_start
    print(f"  Function size: {func_size} bytes (0x{func_start:06X} - 0x{func_end:06X})")
    print()

    # First, check if gBattleMainFunc (0x03005D04) appears in literal pools near this function
    lit_pool_refs = find_all_literal_pool_values_for_address(
        rom_data, func_start, func_end, search_target_addr
    )
    print(f"  Literal pool refs to 0x{search_target_addr:08X}: {len(lit_pool_refs)}")
    for ref_off in lit_pool_refs:
        print(f"    ROM offset 0x{ref_off:06X} (addr 0x{ROM_BASE + ref_off:08X})")
    print()

    # Find stores to gBattleMainFunc
    stores = find_stores_to_address(rom_data, func_start, func_end, search_target_addr)

    if stores:
        print(f"  Found {len(stores)} store(s) to gBattleMainFunc:\n")
        for store_off, stored_val, lit_off, load_off in stores:
            # Check if stored value looks like a ROM function pointer (0x08xxxxxx with THUMB bit)
            is_rom_ptr = (stored_val & 0xFF000001) == 0x08000001
            thumb_str = " (THUMB)" if (stored_val & 1) else ""
            rom_offset_str = f"ROM offset 0x{(stored_val & ~1) - ROM_BASE:06X}" if is_rom_ptr else "NOT a ROM pointer"

            print(f"    STR at ROM offset 0x{store_off:06X} (addr 0x{ROM_BASE + store_off:08X})")
            print(f"      Value stored:  0x{stored_val:08X}{thumb_str}")
            print(f"      Loaded from:   ROM offset 0x{load_off:06X}" if load_off else "      Loaded from: immediate")
            print(f"      Literal pool:  ROM offset 0x{lit_off:06X}" if lit_off else "      Literal pool: N/A")
            print(f"      Interpretation: {rom_offset_str}")
            print()

        # Show context around each store
        print("  Context around stores:\n")
        for store_off, stored_val, lit_off, load_off in stores:
            # Show 10 instructions before and 5 after the store
            ctx_start = max(func_start, store_off - 30)
            ctx_end = min(func_end, store_off + 16)
            disasm = disassemble_thumb(rom_data, ctx_start, ctx_end)
            print(f"    --- Context around STR at 0x{ROM_BASE + store_off:08X} ---")
            for off, addr, raw, mnem in disasm:
                marker = " <<<" if off == store_off else ""
                if off == load_off:
                    marker = " <<< loads value"
                func_off = off - func_start
                print(f"      +0x{func_off:04X} | 0x{addr:08X}: {raw:<12s} {mnem}{marker}")
            print()

        # Return the last stored value (typically the final assignment near function end)
        # Filter for ROM function pointers only
        rom_ptrs = [(off, val, lit, load) for off, val, lit, load in stores
                    if (val & 0xFF000001) == 0x08000001]
        if rom_ptrs:
            # Return the one closest to the function end (the "main" assignment)
            best = max(rom_ptrs, key=lambda x: x[0])
            return best[1]

    # Fallback: if the simple register tracking missed it, do a broader scan.
    # Look for any LDR that loads a ROM pointer, followed within a few instructions
    # by a reference to gBattleMainFunc, followed by STR.
    print("  Simple tracking found no stores. Trying broader pattern scan...\n")

    # Scan all LDR Rd, [PC, #imm] that load a ROM function pointer
    rom_ptr_loads = []
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        if (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_off)
                if (val & 0xFF000001) == 0x08000001:
                    rom_ptr_loads.append((pos, rd, val, lit_off))
        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2

    # For each ROM pointer load, check if gBattleMainFunc is loaded nearby and a STR follows
    candidates = []
    for load_off, load_rd, load_val, load_lit in rom_ptr_loads:
        # Search within +/- 20 instructions (40 bytes) for gBattleMainFunc load + STR
        search_start = max(func_start, load_off - 40)
        search_end = min(func_end, load_off + 40)

        found_gmf_load = False
        gmf_reg = -1
        spos = search_start
        while spos < search_end and spos + 2 <= len(rom_data):
            sinstr = read_u16(rom_data, spos)
            if (sinstr & 0xF800) == 0x4800:
                srd = (sinstr >> 8) & 7
                simm8 = sinstr & 0xFF
                slit_off = ((spos + 4) & ~3) + simm8 * 4
                if slit_off + 4 <= len(rom_data):
                    sval = read_u32(rom_data, slit_off)
                    if sval == search_target_addr:
                        found_gmf_load = True
                        gmf_reg = srd

            # Check for STR load_rd, [gmf_reg, #0]
            if (sinstr & 0xF800) == 0x6000 and found_gmf_load:
                str_rd = sinstr & 7
                str_rn = (sinstr >> 3) & 7
                str_imm = ((sinstr >> 6) & 0x1F) * 4
                if str_imm == 0 and str_rn == gmf_reg and str_rd == load_rd:
                    candidates.append((spos, load_val, load_lit, load_off))

            if (sinstr & 0xF800) == 0xF000 and spos + 2 < len(rom_data):
                next_sinstr = read_u16(rom_data, spos + 2)
                if (next_sinstr & 0xF800) == 0xF800:
                    spos += 4
                    continue
            spos += 2

    if candidates:
        print(f"  Broader scan found {len(candidates)} candidate(s):\n")
        for store_off, stored_val, lit_off, load_off in candidates:
            print(f"    STR at 0x{ROM_BASE + store_off:08X}")
            print(f"    Value: 0x{stored_val:08X} (ROM offset 0x{(stored_val & ~1) - ROM_BASE:06X})")

            # Show context
            ctx_start = max(func_start, min(load_off, store_off) - 10)
            ctx_end = min(func_end, max(load_off, store_off) + 10)
            disasm = disassemble_thumb(rom_data, ctx_start, ctx_end)
            for off, addr, raw, mnem in disasm:
                marker = ""
                if off == store_off: marker = " <<< STR to gBattleMainFunc"
                if off == load_off: marker = " <<< loads function pointer"
                func_off = off - func_start
                print(f"      +0x{func_off:04X} | 0x{addr:08X}: {raw:<12s} {mnem}{marker}")
            print()

        # Return the last (closest to function end) candidate
        best = max(candidates, key=lambda x: x[0])
        return best[1]

    # Last resort: just dump all ROM pointer loads near gBattleMainFunc literal pool refs
    print("  Broader scan also found nothing. Dumping ALL ROM pointer loads near gBattleMainFunc refs:\n")
    for lit_ref in lit_pool_refs:
        # Find all LDR instructions that reference this literal pool entry
        nearby_loads = []
        for load_off, load_rd, load_val, load_lit in rom_ptr_loads:
            if abs(load_off - lit_ref) < 200:
                nearby_loads.append((load_off, load_rd, load_val, load_lit))

        if nearby_loads:
            print(f"  Near gBattleMainFunc literal at 0x{ROM_BASE + lit_ref:08X}:")
            for load_off, load_rd, load_val, load_lit in nearby_loads:
                print(f"    +0x{load_off - func_start:04X}: LDR R{load_rd}, =0x{load_val:08X} (ROM offset 0x{(load_val & ~1) - ROM_BASE:06X})")
    print()

    # Dump the last 200 bytes of the function for manual inspection
    dump_start = max(func_start, func_end - 200)
    print(f"  Last ~200 bytes of function (0x{ROM_BASE + dump_start:08X} - 0x{ROM_BASE + func_end:08X}):\n")
    disasm = disassemble_thumb(rom_data, dump_start, func_end)
    for off, addr, raw, mnem in disasm:
        func_off = off - func_start
        annotation = ""
        if "03005D04" in mnem:
            annotation = "  ; gBattleMainFunc"
        print(f"    +0x{func_off:04X} | 0x{addr:08X}: {raw:<12s} {mnem}{annotation}")
    print()

    return None


def dump_full_function(rom_data, func_name, func_rom_offset, max_instrs=300):
    """Dump full disassembly of a function for debugging."""
    func_start = func_rom_offset
    func_end = find_function_end(rom_data, func_start, max_size=8192)
    func_size = func_end - func_start

    print(f"\n{'='*80}")
    print(f"  FULL DISASSEMBLY: {func_name}")
    print(f"  Address: 0x{ROM_BASE + func_start + 1:08X}")
    print(f"  Size: {func_size} bytes")
    print(f"{'='*80}\n")

    disasm = disassemble_thumb(rom_data, func_start, func_end)
    for i, (off, addr, raw, mnem) in enumerate(disasm):
        if i >= max_instrs:
            print(f"    ... truncated after {max_instrs} instructions ({len(disasm)} total)")
            break
        func_off = off - func_start
        annotation = ""
        if "03005D04" in mnem:
            annotation = "  ; gBattleMainFunc"
        elif "0803AC" in mnem:
            annotation = "  ; near DoBattleIntro"
        print(f"    +0x{func_off:04X} | 0x{addr:08X}: {raw:<12s} {mnem}{annotation}")
    print()


def main():
    # Load ROM
    rom_path = ROM_PATH
    if not rom_path.exists():
        print(f"ERROR: ROM not found at {rom_path}")
        print(f"  Expected: {rom_path.resolve()}")
        sys.exit(1)

    rom_data = rom_path.read_bytes()
    print(f"ROM loaded: {len(rom_data):,} bytes ({len(rom_data) / 1024 / 1024:.1f} MB)")
    print(f"ROM path: {rom_path.resolve()}")
    print()

    # Verify DoBattleIntro starts with PUSH {LR}
    dbi_instr = read_u16(rom_data, DO_BATTLE_INTRO_ROM_OFFSET)
    print(f"DoBattleIntro at ROM offset 0x{DO_BATTLE_INTRO_ROM_OFFSET:06X}:")
    print(f"  First instruction: 0x{dbi_instr:04X}", end="")
    if (dbi_instr & 0xFF00) == 0xB500:
        print(" (PUSH {..., LR}) -- confirmed function start")
    else:
        print(" -- WARNING: not PUSH {LR}, may not be function start!")
    print()

    # Verify gBattleMainFunc has literal pool refs
    target_bytes = struct.pack('<I', G_BATTLE_MAIN_FUNC)
    gmf_refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            gmf_refs.append(i)
    print(f"gBattleMainFunc (0x{G_BATTLE_MAIN_FUNC:08X}) literal pool refs in ROM: {len(gmf_refs)}")
    if gmf_refs:
        # Show a few
        for ref in gmf_refs[:10]:
            print(f"  ROM offset 0x{ref:06X} (addr 0x{ROM_BASE + ref:08X})")
        if len(gmf_refs) > 10:
            print(f"  ... and {len(gmf_refs) - 10} more")
    print()

    # =========================================================================
    # STEP 1: Find TryDoEventsBeforeFirstTurn from DoBattleIntro
    # =========================================================================

    result1 = analyze_function(
        rom_data,
        "DoBattleIntro",
        DO_BATTLE_INTRO_ROM_OFFSET,
        G_BATTLE_MAIN_FUNC
    )

    if result1 is not None:
        try_do_events_addr = result1
        try_do_events_rom_offset = (try_do_events_addr & ~1) - ROM_BASE
        print(f"\n{'*'*80}")
        print(f"  RESULT: TryDoEventsBeforeFirstTurn = 0x{try_do_events_addr:08X}")
        print(f"  ROM offset: 0x{try_do_events_rom_offset:06X}")
        print(f"{'*'*80}\n")

        # Dump it for verification
        dump_full_function(rom_data, "TryDoEventsBeforeFirstTurn", try_do_events_rom_offset, max_instrs=150)

        # =====================================================================
        # STEP 2: Find HandleTurnActionSelectionState from TryDoEventsBeforeFirstTurn
        # =====================================================================

        result2 = analyze_function(
            rom_data,
            "TryDoEventsBeforeFirstTurn",
            try_do_events_rom_offset,
            G_BATTLE_MAIN_FUNC
        )

        if result2 is not None:
            handle_turn_addr = result2
            handle_turn_rom_offset = (handle_turn_addr & ~1) - ROM_BASE
            print(f"\n{'*'*80}")
            print(f"  RESULT: HandleTurnActionSelectionState = 0x{handle_turn_addr:08X}")
            print(f"  ROM offset: 0x{handle_turn_rom_offset:06X}")
            print(f"{'*'*80}\n")

            # Dump it for verification
            dump_full_function(rom_data, "HandleTurnActionSelectionState", handle_turn_rom_offset, max_instrs=150)
        else:
            print("\n  FAILED to find HandleTurnActionSelectionState!")
            print("  TryDoEventsBeforeFirstTurn may not store to gBattleMainFunc in the expected pattern.")
    else:
        print("\n  FAILED to find TryDoEventsBeforeFirstTurn!")
        print("  DoBattleIntro may not store to gBattleMainFunc in the expected pattern.")
        print("  Check the full disassembly above for manual inspection.")

    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================

    print(f"\n{'='*80}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*80}\n")

    print(f"  {'DoBattleIntro':<45s} = 0x{ROM_BASE + DO_BATTLE_INTRO_ROM_OFFSET + 1:08X}  (ROM offset 0x{DO_BATTLE_INTRO_ROM_OFFSET:06X}) [KNOWN]")

    if result1 is not None:
        r1_rom = (result1 & ~1) - ROM_BASE
        print(f"  {'TryDoEventsBeforeFirstTurn':<45s} = 0x{result1:08X}  (ROM offset 0x{r1_rom:06X}) [FOUND]")
    else:
        print(f"  {'TryDoEventsBeforeFirstTurn':<45s} = NOT FOUND")

    if result1 is not None and result2 is not None:
        r2_rom = (result2 & ~1) - ROM_BASE
        print(f"  {'HandleTurnActionSelectionState':<45s} = 0x{result2:08X}  (ROM offset 0x{r2_rom:06X}) [FOUND]")
    else:
        print(f"  {'HandleTurnActionSelectionState':<45s} = NOT FOUND")

    print(f"\n  {'gBattleMainFunc':<45s} = 0x{G_BATTLE_MAIN_FUNC:08X}  (IWRAM) [KNOWN]")
    print()


if __name__ == "__main__":
    main()
