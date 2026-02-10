#!/usr/bin/env python3
"""
Find ROM functions to patch for Link Battle Emulation in Pokemon Run & Bun.

Targets:
  1. CB2_HandleStartBattle      (vanilla 0x08036FAC) — very large, refs gBattleResources + gWirelessCommType + gReceivedRemoteLinkPlayers
  2. SetUpBattleVars             (vanilla 0x0803269C) — medium, refs gBattleResources + gBattleTypeFlags, calls CreateTask
  3. PlayerBufferExecCompleted   (vanilla 0x0805748C) — small-medium, refs gBattleControllerExecFlags, calls GetMultiplayerId
  4. LinkOpponentBufferExecCompleted (vanilla 0x08065068) — twin of #3
  5. PrepareBufferDataTransferLink  (vanilla 0x080331B8) — small, refs gBattleResources, link send code

Strategy: cross-reference known EWRAM/IWRAM addresses in ROM literal pools to find
containing functions, then score by size, BL count, and instruction patterns.

No Ghidra needed — reads the .gba file directly.
"""

import struct
import sys
from pathlib import Path
from collections import defaultdict

# =============================================================================
# Configuration
# =============================================================================

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known R&B addresses (confirmed)
KNOWN = {
    # EWRAM
    "gBattleResources":            0x02023A18,  # 650 literal pool refs
    "gPlayerParty":                0x02023A98,
    "gEnemyParty":                 0x02023CF0,
    "gBattleTypeFlags":            0x020090E8,  # 0 literal pool refs (base+offset access)
    "gMainCallback2":              0x0202064C,
    # IWRAM
    "gWirelessCommType":           0x030030FC,  # 132 ROM refs
    "gReceivedRemoteLinkPlayers":  0x03003124,
    "gBlockReceivedStatus":        0x0300307C,
    # ROM
    "GetMultiplayerId":            0x0800A4B1,  # confirmed
    "CB2_BattleMain":              0x08094815,
    "CB2_LoadMap":                 0x08007441,
}

# Vanilla Emerald addresses (for reference / delta estimation)
VANILLA = {
    "CB2_HandleStartBattle":             0x08036FAC,
    "SetUpBattleVars":                   0x0803269C,
    "PlayerBufferExecCompleted":         0x0805748C,
    "LinkOpponentBufferExecCompleted":   0x08065068,
    "PrepareBufferDataTransferLink":     0x080331B8,
    "gBattleControllerExecFlags":        0x02024068,
    "gBattleCommunication":              0x02024332,
    "gActiveBattler":                    0x02024064,
}


# =============================================================================
# Low-level ROM helpers
# =============================================================================

def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


# =============================================================================
# Literal pool scanner
# =============================================================================

def find_all_literal_refs(rom_data, target_value):
    """Find all 4-byte aligned positions in ROM where target_value appears."""
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs


# =============================================================================
# Function boundary detection
# =============================================================================

def find_function_start(rom_data, offset, max_back=4096):
    """Walk backward to find PUSH {..., LR} = 0xB5xx."""
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16(rom_data, pos)
        if (instr & 0xFF00) == 0xB500:  # PUSH {..., LR}
            return pos
    return None


def find_function_end(rom_data, func_start, max_size=4096):
    """Find function end: last POP {PC} or BX LR before hitting another PUSH {LR}
    or going too far. For large functions with multiple POP {PC} (switch/case),
    we continue past internal POPs."""
    pos = func_start + 2
    limit = min(func_start + max_size, len(rom_data) - 2)
    last_pop_pc = None

    while pos < limit:
        instr = read_u16(rom_data, pos)

        # POP {..., PC} = 0xBDxx
        if (instr & 0xFF00) == 0xBD00:
            last_pop_pc = pos + 2
            # Check if next instruction starts a new function (PUSH {LR})
            if pos + 2 < limit:
                next_instr = read_u16(rom_data, pos + 2)
                if (next_instr & 0xFF00) == 0xB500:
                    return pos + 2
            # Check if we hit literal pool data (non-instruction patterns)
            # Keep going for now - large functions have multiple POP {PC}
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

        # New PUSH {LR} = new function start (unless it's in literal pool data)
        if (instr & 0xFF00) == 0xB500 and pos > func_start + 4:
            # This is likely the start of a new function
            # Return the position just before this
            if last_pop_pc is not None:
                return last_pop_pc
            return pos

        # Skip BL 32-bit pairs
        if (instr & 0xF800) == 0xF000 and pos + 2 < limit:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue

        pos += 2

    return last_pop_pc if last_pop_pc else func_start + max_size


def find_function_end_simple(rom_data, func_start, max_size=512):
    """Find function end: FIRST POP {PC} or BX LR. For small functions."""
    pos = func_start + 2
    limit = min(func_start + max_size, len(rom_data) - 2)

    while pos < limit:
        instr = read_u16(rom_data, pos)

        if (instr & 0xFF00) == 0xBD00:
            return pos + 2
        if instr == 0x4770:
            return pos + 2
        # POP {Rn} + BX Rn
        if (instr & 0xFE00) == 0xBC00 and not (instr & 0x100):
            if pos + 2 < limit:
                next_instr = read_u16(rom_data, pos + 2)
                if (next_instr & 0xFF80) == 0x4700:
                    return pos + 4

        if (instr & 0xF800) == 0xF000 and pos + 2 < limit:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2

    return None


# =============================================================================
# Function analysis helpers
# =============================================================================

def get_ldr_pc_literals(rom_data, func_start, func_end):
    """Extract all LDR Rd,[PC,#imm] literal pool values within a range."""
    results = []
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        if (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            lit_rom_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_rom_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_rom_off)
                results.append((pos - func_start, rd, val, lit_rom_off))

        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return results


def decode_bl_target(rom_data, pos):
    """Decode THUMB BL at pos, return target address."""
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


def get_bl_targets(rom_data, func_start, func_end):
    """Get all BL call targets within a function."""
    targets = []
    pos = func_start
    while pos < func_end and pos + 4 <= len(rom_data):
        hi = read_u16(rom_data, pos)
        lo = read_u16(rom_data, pos + 2)
        if (hi & 0xF800) == 0xF000 and (lo & 0xF800) == 0xF800:
            t = decode_bl_target(rom_data, pos)
            if t is not None:
                targets.append((pos - func_start, t))
            pos += 4
        else:
            pos += 2
    return targets


def count_conditional_branches(rom_data, func_start, func_end):
    """Count conditional branch instructions (BEQ, BNE, etc.)."""
    count = 0
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        if (instr & 0xF000) == 0xD000 and ((instr >> 8) & 0xF) < 0xE:
            count += 1
        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return count


def count_pop_pc(rom_data, func_start, func_end):
    """Count POP {PC} instructions (indicator of switch/case complexity)."""
    count = 0
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        if (instr & 0xFF00) == 0xBD00:
            count += 1
        if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return count


# =============================================================================
# THUMB disassembler (reused from find_getmultiplayerid.py, extended)
# =============================================================================

COND_NAMES = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
              "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]

def disassemble_range(rom_data, start, end, max_instrs=None):
    """Disassemble THUMB code. Returns list of (rom_offset, addr, raw_hex, mnemonic)."""
    lines = []
    pos = start
    while pos < end and pos + 2 <= len(rom_data):
        if max_instrs is not None and len(lines) >= max_instrs:
            break
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
            mnem = f"ADD R{rd}, #{imm} (0x{imm:02X})"

        # SUB Rd, #imm
        elif (instr & 0xF800) == 0x3800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            mnem = f"SUB R{rd}, #{imm} (0x{imm:02X})"

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

        # LDR/LDRB/LDRH Rd, [Rn, Rm]
        elif (instr & 0xFE00) == 0x5800:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"LDR R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5C00:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"LDRB R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5A00:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"LDRH R{rd}, [R{rn}, R{rm}]"

        # STR/STRB/STRH Rd, [Rn, Rm]
        elif (instr & 0xFE00) == 0x5000:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"STR R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5400:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"STRB R{rd}, [R{rn}, R{rm}]"
        elif (instr & 0xFE00) == 0x5200:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            mnem = f"STRH R{rd}, [R{rn}, R{rm}]"

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
                mnem = f"BL 0x{target:08X}"
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

        # LDMIA / STMIA
        elif (instr & 0xF800) == 0xC800:
            rn = (instr >> 8) & 7
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            mnem = f"LDMIA R{rn}!, {{{', '.join(regs)}}}"
        elif (instr & 0xF800) == 0xC000:
            rn = (instr >> 8) & 7
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            mnem = f"STMIA R{rn}!, {{{', '.join(regs)}}}"

        else:
            mnem = f"??? 0x{instr:04X}"

        lines.append((pos, addr, raw, mnem))
        pos += 2

    return lines


# =============================================================================
# Function info builder
# =============================================================================

def build_function_info(rom_data, func_start, func_end):
    """Build a comprehensive info dict for a function."""
    size = func_end - func_start
    func_addr = ROM_BASE + func_start + 1  # +1 for THUMB

    lits = get_ldr_pc_literals(rom_data, func_start, func_end)
    lit_vals = set(v for _, _, v, _ in lits)
    bl_targets = get_bl_targets(rom_data, func_start, func_end)
    cond_branches = count_conditional_branches(rom_data, func_start, func_end)
    pop_pcs = count_pop_pc(rom_data, func_start, func_end)

    # Classify literal pool values
    ewram_vals = sorted(set(v for _, _, v, _ in lits if 0x02000000 <= v < 0x02040000))
    iwram_vals = sorted(set(v for _, _, v, _ in lits if 0x03000000 <= v < 0x03008000))
    io_vals    = sorted(set(v for _, _, v, _ in lits if 0x04000000 <= v < 0x05000000))
    rom_vals   = sorted(set(v for _, _, v, _ in lits if 0x08000000 <= v < 0x0A000000))

    return {
        'start': func_start,
        'end': func_end,
        'size': size,
        'addr': func_addr,
        'lits': lits,
        'lit_vals': lit_vals,
        'bl_targets': bl_targets,
        'cond_branches': cond_branches,
        'pop_pcs': pop_pcs,
        'ewram_vals': ewram_vals,
        'iwram_vals': iwram_vals,
        'io_vals': io_vals,
        'rom_vals': rom_vals,
    }


# =============================================================================
# Build function database from literal pool references
# =============================================================================

def build_function_db(rom_data, anchor_addr, max_back=4096, use_large_end=False):
    """Find all unique functions that reference anchor_addr in their literal pool.
    Returns dict: func_start -> info."""
    refs = find_all_literal_refs(rom_data, anchor_addr)
    functions = {}

    for lit_off in refs:
        func_start = find_function_start(rom_data, lit_off, max_back=max_back)
        if func_start is None or func_start in functions:
            continue

        if use_large_end:
            func_end = find_function_end(rom_data, func_start, max_size=4096)
        else:
            func_end = find_function_end_simple(rom_data, func_start, max_size=2048)
            if func_end is None:
                func_end = find_function_end(rom_data, func_start, max_size=2048)

        if func_end is None:
            func_end = func_start + 200

        functions[func_start] = build_function_info(rom_data, func_start, func_end)

    return functions


# =============================================================================
# Pretty printing helpers
# =============================================================================

def annotate_addr(val):
    """Return a label for known addresses."""
    for name, addr in KNOWN.items():
        if val == addr:
            return f" ; {name}"
    if val == VANILLA.get("gBattleControllerExecFlags"):
        return " ; vanilla gBattleControllerExecFlags"
    if 0x02000000 <= val < 0x02040000:
        return " (EWRAM)"
    if 0x03000000 <= val < 0x03008000:
        return " (IWRAM)"
    if 0x04000000 <= val < 0x05000000:
        return " (IO)"
    if 0x08000000 <= val < 0x0A000000:
        return " (ROM)"
    return ""


def print_function_detail(rom_data, info, max_disasm=80):
    """Print full details of a function candidate."""
    print(f"    Address:   0x{info['addr']:08X} (ROM offset 0x{info['start']:06X})")
    print(f"    Size:      {info['size']} bytes")
    print(f"    BL calls:  {len(info['bl_targets'])}")
    print(f"    Cond branches: {info['cond_branches']}")
    print(f"    POP {{PC}}: {info['pop_pcs']}")

    if info['ewram_vals']:
        print(f"    EWRAM refs: {len(info['ewram_vals'])}")
        for v in info['ewram_vals'][:15]:
            print(f"      0x{v:08X}{annotate_addr(v)}")
        if len(info['ewram_vals']) > 15:
            print(f"      ... and {len(info['ewram_vals'])-15} more")
    if info['iwram_vals']:
        print(f"    IWRAM refs:")
        for v in info['iwram_vals']:
            print(f"      0x{v:08X}{annotate_addr(v)}")
    if info['io_vals']:
        print(f"    IO refs:")
        for v in info['io_vals']:
            print(f"      0x{v:08X}{annotate_addr(v)}")

    if info['bl_targets']:
        print(f"    BL targets:")
        for off, target in info['bl_targets'][:25]:
            label = ""
            for name, addr in KNOWN.items():
                if target == addr or target == (addr & ~1):
                    label = f" ; {name}"
            print(f"      +0x{off:04X}: BL 0x{target:08X}{label}")
        if len(info['bl_targets']) > 25:
            print(f"      ... and {len(info['bl_targets'])-25} more")

    # Disassembly
    print(f"    Disassembly (first {max_disasm} instructions):")
    disasm = disassemble_range(rom_data, info['start'], info['end'], max_instrs=max_disasm)
    for off, addr, raw, mnem in disasm:
        annotation = ""
        for val_str in ["0x02023A18", "0x030030FC", "0x03003124", "0x020090E8",
                        "0x0300307C", "0x0800A4B1", "0x08094815"]:
            if val_str in mnem:
                for name, kaddr in KNOWN.items():
                    if f"0x{kaddr:08X}" == val_str:
                        annotation = f"  ; {name}"
                        break
        func_off = off - info['start']
        print(f"      +0x{func_off:04X} | 0x{addr:08X}: {raw:<12s} {mnem}{annotation}")
    print()


# =============================================================================
# TARGET 1: CB2_HandleStartBattle
# =============================================================================

def find_cb2_handle_start_battle(rom_data):
    """Find CB2_HandleStartBattle: very large, refs gBattleResources + gWirelessCommType + gReceivedRemoteLinkPlayers."""
    print("=" * 80)
    print("  TARGET 1: CB2_HandleStartBattle")
    print("  Vanilla: 0x08036FAC | Very large (>1000 bytes)")
    print("  Refs: gBattleResources + gWirelessCommType + gReceivedRemoteLinkPlayers")
    print("=" * 80)
    print()

    # APPROACH: For very large functions (>1KB), literal pools are split into
    # multiple pools scattered through the function. find_function_start from
    # different pool entries may find different "closest PUSH {LR}" boundaries.
    #
    # New strategy:
    # 1. Find literal pool refs for gWirelessCommType (97 refs) and
    #    gReceivedRemoteLinkPlayers (132 refs) -- these are the most selective.
    # 2. Find pairs of refs from both sets that are within 2KB of each other
    #    (= likely same function).
    # 3. Walk back from the earliest ref to find PUSH {LR}, then scan forward
    #    to find the full function extent.
    # 4. Check that gBattleResources also appears in the literal pools.

    print("  Step 1: Finding literal pool refs for IWRAM anchors...")
    wct_refs = find_all_literal_refs(rom_data, KNOWN["gWirelessCommType"])
    rlp_refs = find_all_literal_refs(rom_data, KNOWN["gReceivedRemoteLinkPlayers"])
    br_refs  = find_all_literal_refs(rom_data, KNOWN["gBattleResources"])
    print(f"    gWirelessCommType:          {len(wct_refs)} literal pool refs")
    print(f"    gReceivedRemoteLinkPlayers: {len(rlp_refs)} literal pool refs")
    print(f"    gBattleResources:           {len(br_refs)} literal pool refs")
    print()

    # Step 2: Find proximity clusters where both IWRAM anchors appear nearby
    print("  Step 2: Finding proximity clusters (gWirelessCommType near gReceivedRemoteLinkPlayers)...")
    PROXIMITY = 3000  # 3KB proximity window
    clusters = []  # (wct_off, rlp_off)
    for woff in wct_refs:
        for roff in rlp_refs:
            if abs(woff - roff) < PROXIMITY:
                clusters.append((min(woff, roff), max(woff, roff)))

    # Deduplicate by function start
    seen_starts = set()
    candidates = []

    for earliest, latest in sorted(set(clusters)):
        # Walk back to find function start
        func_start = find_function_start(rom_data, earliest, max_back=8192)
        if func_start is None or func_start in seen_starts:
            continue
        seen_starts.add(func_start)

        # For very large functions, scan forward aggressively
        # Find the last code before hitting another PUSH {LR} after 'latest'
        scan_end = latest + 2048
        func_end = func_start
        pos = func_start + 2
        last_pop_pc = None
        while pos < min(scan_end, len(rom_data) - 2):
            instr = read_u16(rom_data, pos)
            if (instr & 0xFF00) == 0xBD00:  # POP {PC}
                last_pop_pc = pos + 2
            if instr == 0x4770:  # BX LR
                last_pop_pc = pos + 2
            # New PUSH {LR} well past the start = new function
            if (instr & 0xFF00) == 0xB500 and pos > latest + 4:
                if last_pop_pc and last_pop_pc > latest:
                    func_end = last_pop_pc
                    break
            if (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
                next_instr = read_u16(rom_data, pos + 2)
                if (next_instr & 0xF800) == 0xF800:
                    pos += 4
                    continue
            pos += 2

        if func_end <= func_start:
            func_end = last_pop_pc if last_pop_pc else latest + 256

        info = build_function_info(rom_data, func_start, func_end)

        score = 0
        reasons = []

        # Size: very large
        if info['size'] >= 1000:
            score += 40
            reasons.append(f"very large ({info['size']} bytes)")
        elif info['size'] >= 500:
            score += 25
            reasons.append(f"large ({info['size']} bytes)")
        elif info['size'] >= 200:
            score += 5
            reasons.append(f"medium ({info['size']} bytes)")
        else:
            score -= 20
            reasons.append(f"too small ({info['size']} bytes)")

        # BL count
        bl_count = len(info['bl_targets'])
        if bl_count >= 20:
            score += 30
            reasons.append(f"many BL calls ({bl_count})")
        elif bl_count >= 10:
            score += 15
            reasons.append(f"moderate BL calls ({bl_count})")

        # References
        if KNOWN["gBattleResources"] in info['lit_vals']:
            score += 10
            reasons.append("refs gBattleResources")
        if KNOWN["gWirelessCommType"] in info['lit_vals']:
            score += 10
            reasons.append("refs gWirelessCommType")
        if KNOWN["gReceivedRemoteLinkPlayers"] in info['lit_vals']:
            score += 10
            reasons.append("refs gReceivedRemoteLinkPlayers")

        # POP {PC} count = switch/case
        if info['pop_pcs'] >= 5:
            score += 20
            reasons.append(f"many POP {{PC}} ({info['pop_pcs']}) = switch/case")
        elif info['pop_pcs'] >= 3:
            score += 10
            reasons.append(f"some POP {{PC}} ({info['pop_pcs']})")

        # Conditional branches
        if info['cond_branches'] >= 15:
            score += 10
            reasons.append(f"many conditional branches ({info['cond_branches']})")

        # CB2_BattleMain ref
        if KNOWN["CB2_BattleMain"] in info['lit_vals']:
            score += 15
            reasons.append("refs CB2_BattleMain")

        # BL to GetMultiplayerId
        for _, target in info['bl_targets']:
            if target == KNOWN["GetMultiplayerId"] or target == (KNOWN["GetMultiplayerId"] & ~1):
                score += 10
                reasons.append("calls GetMultiplayerId")
                break

        candidates.append((score, info, reasons))

    print(f"    Found {len(candidates)} candidate functions from proximity clusters")
    print()

    # Fallback: also check gWirelessCommType+gReceivedRemoteLinkPlayers function DB overlap
    if not candidates:
        print("  Step 2b: Fallback — building function DB from gWirelessCommType...")
        wct_funcs = build_function_db(rom_data, KNOWN["gWirelessCommType"], use_large_end=True)
        rlp_funcs = build_function_db(rom_data, KNOWN["gReceivedRemoteLinkPlayers"], use_large_end=True)
        common = set(wct_funcs.keys()) & set(rlp_funcs.keys())
        print(f"    Functions ref both gWirelessCommType + gReceivedRemoteLinkPlayers: {len(common)}")
        for fs in sorted(common):
            if fs in seen_starts:
                continue
            info = wct_funcs[fs]
            fe = find_function_end(rom_data, fs, max_size=4096)
            if fe: info = build_function_info(rom_data, fs, fe)
            score = 0
            reasons = ["fallback: refs gWirelessCommType + gReceivedRemoteLinkPlayers"]
            if info['size'] >= 500: score += 20; reasons.append(f"large ({info['size']} bytes)")
            if len(info['bl_targets']) >= 10: score += 15; reasons.append(f"{len(info['bl_targets'])} BL calls")
            candidates.append((score, info, reasons))

    candidates.sort(key=lambda x: -x[0])

    # Print results
    print("  RANKED CANDIDATES:")
    print()
    for rank, (score, info, reasons) in enumerate(candidates[:5]):
        marker = ""
        if rank == 0: marker = "  <<<< BEST MATCH"
        print(f"  #{rank+1} Score={score} | 0x{info['addr']:08X} ({info['size']} bytes){marker}")
        for r in reasons:
            print(f"       - {r}")
        print()
        print_function_detail(rom_data, info, max_disasm=60)
        print("    " + "-" * 70)
        print()

    if candidates:
        best = candidates[0][1]
        print(f"  >>> RESULT: CB2_HandleStartBattle = 0x{best['addr']:08X}")
        print(f"  >>> ROM offset: 0x{best['start']:06X}")
        print(f"  >>> Size: {best['size']} bytes")
        return best
    else:
        print("  >>> NO CANDIDATES FOUND")
        return None


# =============================================================================
# TARGET 2: SetUpBattleVars
# =============================================================================

def find_setup_battle_vars(rom_data):
    """Find SetUpBattleVars: medium, refs gBattleResources + gBattleTypeFlags area, calls CreateTask."""
    print()
    print("=" * 80)
    print("  TARGET 2: SetUpBattleVars")
    print("  Vanilla: 0x0803269C | Medium (200-600 bytes)")
    print("  Refs: gBattleResources + gBattleTypeFlags | Calls CreateTask + GetMultiplayerId")
    print("=" * 80)
    print()

    # Build from gBattleResources refs
    print("  Step 1: Filtering gBattleResources functions by size + BL pattern...")
    br_funcs = build_function_db(rom_data, KNOWN["gBattleResources"])
    print(f"    {len(br_funcs)} functions total")

    candidates = []
    for func_start, info in br_funcs.items():
        score = 0
        reasons = []

        # Size: 200-600 bytes
        if 150 <= info['size'] <= 700:
            score += 20
            reasons.append(f"good size ({info['size']} bytes)")
        elif info['size'] > 700:
            score -= 10
            reasons.append(f"too large ({info['size']} bytes)")
        else:
            continue  # Skip very small functions

        # BL count: 5-20
        bl_count = len(info['bl_targets'])
        if 5 <= bl_count <= 25:
            score += 15
            reasons.append(f"moderate BL calls ({bl_count})")
        elif bl_count < 5:
            score -= 10
            reasons.append(f"too few BL calls ({bl_count})")
        else:
            score -= 5
            reasons.append(f"many BL calls ({bl_count})")

        # Must reference gBattleResources
        if KNOWN["gBattleResources"] in info['lit_vals']:
            score += 5
            reasons.append("refs gBattleResources")

        # Calls GetMultiplayerId -- strong indicator
        calls_gmi = False
        for _, target in info['bl_targets']:
            if target == KNOWN["GetMultiplayerId"] or target == (KNOWN["GetMultiplayerId"] & ~1):
                calls_gmi = True
                score += 30
                reasons.append("calls GetMultiplayerId")
                break

        # References gBattleTypeFlags (0x020090E8) -- since 0 literal pool refs,
        # it's accessed via base+offset. Look for nearby values or gBattleTypeFlags
        # itself in literal pool (just in case some functions do load it)
        if KNOWN["gBattleTypeFlags"] in info['lit_vals']:
            score += 15
            reasons.append("refs gBattleTypeFlags directly")

        # Look for EWRAM addresses near gBattleTypeFlags (0x020090E8)
        # e.g., 0x020090E0 base + offset 8
        for v in info['ewram_vals']:
            if 0x020090D0 <= v <= 0x020090F8:
                score += 10
                reasons.append(f"refs near gBattleTypeFlags (0x{v:08X})")
                break

        # Should NOT reference gReceivedRemoteLinkPlayers (that's CB2_HandleStartBattle)
        if KNOWN["gReceivedRemoteLinkPlayers"] in info['lit_vals']:
            score -= 15
            reasons.append("refs gReceivedRemoteLinkPlayers (more likely CB2_HandleStartBattle)")

        # Look for CreateTask pattern: BL with R1=#0x50 (priority 80 = 0x50) nearby
        # or R0=function pointer, R1=priority, R2=data_size
        disasm = disassemble_range(rom_data, info['start'], info['end'], max_instrs=200)
        for i, (off, addr, raw, mnem) in enumerate(disasm):
            if "MOV" in mnem and ("#80" in mnem or "#0x50" in mnem or "#5 " in mnem):
                # Check if there's a BL within next 5 instructions
                for j in range(i+1, min(i+6, len(disasm))):
                    if "BL" in disasm[j][3]:
                        score += 10
                        reasons.append(f"CreateTask pattern (MOV + BL at +0x{off-info['start']:04X})")
                        break
                break

        # Additional: should have gWirelessCommType ref or nearby
        if KNOWN["gWirelessCommType"] in info['lit_vals']:
            score += 5
            reasons.append("refs gWirelessCommType")

        if score >= 20:
            candidates.append((score, info, reasons))

    candidates.sort(key=lambda x: -x[0])

    print()
    print("  RANKED CANDIDATES:")
    print()
    for rank, (score, info, reasons) in enumerate(candidates[:5]):
        marker = ""
        if rank == 0: marker = "  <<<< BEST MATCH"
        print(f"  #{rank+1} Score={score} | 0x{info['addr']:08X} ({info['size']} bytes){marker}")
        for r in reasons:
            print(f"       - {r}")
        print()
        print_function_detail(rom_data, info, max_disasm=60)
        print("    " + "-" * 70)
        print()

    if candidates:
        best = candidates[0][1]
        print(f"  >>> RESULT: SetUpBattleVars = 0x{best['addr']:08X}")
        print(f"  >>> ROM offset: 0x{best['start']:06X}")
        print(f"  >>> Size: {best['size']} bytes")

        # Suggest patch points: NOP at +0x42,+0x44 (skip CreateTask for multiplayer)
        print()
        print("  >>> PATCH SUGGESTION (PK-GBA reference: +0x42,+0x44 = 2 NOPs):")
        print("  >>> Look for BL after GetMultiplayerId call -- that's the CreateTask BL to NOP")
        return best
    else:
        print("  >>> NO CANDIDATES FOUND")
        return None


# =============================================================================
# TARGET 3 & 4: PlayerBufferExecCompleted & LinkOpponentBufferExecCompleted
# =============================================================================

def find_buffer_exec_completed_pair(rom_data):
    """Find PlayerBufferExecCompleted and LinkOpponentBufferExecCompleted.
    Both are small-medium, reference gBattleControllerExecFlags, call GetMultiplayerId."""
    print()
    print("=" * 80)
    print("  TARGET 3+4: PlayerBufferExecCompleted + LinkOpponentBufferExecCompleted")
    print("  Vanilla: 0x0805748C / 0x08065068 | Small-medium (100-200 bytes)")
    print("  Both call GetMultiplayerId | Both ref gBattleControllerExecFlags")
    print("=" * 80)
    print()

    # Strategy: find ALL functions that call GetMultiplayerId
    print("  Step 1: Finding all callers of GetMultiplayerId (0x{:08X})...".format(KNOWN["GetMultiplayerId"]))

    gmi_addr = KNOWN["GetMultiplayerId"]
    # Search entire ROM for BL to GetMultiplayerId
    callers = []
    for pos in range(0, len(rom_data) - 4, 2):
        target = decode_bl_target(rom_data, pos)
        if target is not None and (target == gmi_addr or target == (gmi_addr & ~1)):
            func_start = find_function_start(rom_data, pos)
            if func_start is not None:
                callers.append((func_start, pos))

    # Deduplicate by function start
    unique_callers = {}
    for func_start, bl_pos in callers:
        if func_start not in unique_callers:
            unique_callers[func_start] = []
        unique_callers[func_start].append(bl_pos)

    print(f"    Found {len(unique_callers)} unique functions calling GetMultiplayerId")
    print()

    # Build info for each caller
    caller_infos = []
    for func_start in sorted(unique_callers.keys()):
        func_end = find_function_end_simple(rom_data, func_start, max_size=512)
        if func_end is None:
            func_end = find_function_end(rom_data, func_start, max_size=512)
        if func_end is None:
            func_end = func_start + 200
        info = build_function_info(rom_data, func_start, func_end)
        caller_infos.append(info)

    # Step 2: Find pairs with similar structure
    print("  Step 2: Finding similar-sized function pairs that share literal pool values...")
    print()

    # PlayerBufferExecCompleted and LinkOpponentBufferExecCompleted should:
    # - Be 80-300 bytes
    # - Have 1-5 BL calls
    # - Share a common EWRAM address (gBattleControllerExecFlags)
    # - Both call GetMultiplayerId
    # - Have similar instruction count

    # Filter to reasonable size
    filtered = [info for info in caller_infos if 50 <= info['size'] <= 400]
    print(f"    Filtered to {len(filtered)} functions (50-400 bytes) that call GetMultiplayerId")
    print()

    # Find pairs that share EWRAM literal pool values
    pairs = []
    for i in range(len(filtered)):
        for j in range(i+1, len(filtered)):
            a = filtered[i]
            b = filtered[j]
            shared_ewram = set(a['ewram_vals']) & set(b['ewram_vals'])
            if shared_ewram and abs(a['size'] - b['size']) < 100:
                # Both similar size and share EWRAM refs
                score = len(shared_ewram) * 10
                if abs(a['size'] - b['size']) < 30:
                    score += 20  # Very similar size

                # Both should have ~1-5 BL calls
                bl_a = len(a['bl_targets'])
                bl_b = len(b['bl_targets'])
                if 1 <= bl_a <= 8 and 1 <= bl_b <= 8:
                    score += 15

                # Check if they share exactly the same set of non-trivial EWRAM refs
                if len(shared_ewram) >= 2:
                    score += 15

                # ROM address ordering: PlayerBuffer < LinkOpponentBuffer
                pairs.append((score, a, b, shared_ewram))

    pairs.sort(key=lambda x: -x[0])

    # Print top pairs
    print("  RANKED PAIRS (shared EWRAM + similar size):")
    print()
    for rank, (score, a, b, shared) in enumerate(pairs[:5]):
        first = a if a['addr'] < b['addr'] else b
        second = b if a['addr'] < b['addr'] else a
        marker = ""
        if rank == 0: marker = "  <<<< BEST PAIR"
        print(f"  Pair #{rank+1} Score={score}{marker}")
        print(f"    A: 0x{first['addr']:08X} ({first['size']} bytes, {len(first['bl_targets'])} BL)")
        print(f"    B: 0x{second['addr']:08X} ({second['size']} bytes, {len(second['bl_targets'])} BL)")
        print(f"    Shared EWRAM: {[f'0x{v:08X}' for v in sorted(shared)]}")
        print(f"    -> Likely gBattleControllerExecFlags = one of these shared EWRAM addrs")
        print()

    # Also list all small callers individually for inspection
    print()
    print("  ALL GetMultiplayerId callers (50-400 bytes), sorted by size:")
    print()
    sorted_filtered = sorted(filtered, key=lambda x: x['size'])
    for info in sorted_filtered[:15]:
        ewram_str = ", ".join(f"0x{v:08X}" for v in info['ewram_vals'][:5])
        print(f"    0x{info['addr']:08X} | {info['size']:3d} bytes | {len(info['bl_targets'])} BL | EWRAM: [{ewram_str}]")
    print()

    # Print detailed disassembly for top pair
    if pairs:
        best_score, a, b, shared = pairs[0]
        first = a if a['addr'] < b['addr'] else b
        second = b if a['addr'] < b['addr'] else a

        print("  DETAILED ANALYSIS OF BEST PAIR:")
        print()
        print(f"  --- PlayerBufferExecCompleted candidate: 0x{first['addr']:08X} ---")
        print_function_detail(rom_data, first, max_disasm=60)

        print(f"  --- LinkOpponentBufferExecCompleted candidate: 0x{second['addr']:08X} ---")
        print_function_detail(rom_data, second, max_disasm=60)

        # Suggest patch points
        print("  >>> PATCH SUGGESTION (PK-GBA reference: +0x1C = B +0x1A = 0xE01A):")
        print("  >>> Look for link check (LDRB gWirelessCommType + CMP + BEQ) -- patch the BEQ to unconditional B")
        print()

        print(f"  >>> RESULT: PlayerBufferExecCompleted = 0x{first['addr']:08X}")
        print(f"  >>> RESULT: LinkOpponentBufferExecCompleted = 0x{second['addr']:08X}")
        print(f"  >>> RESULT: gBattleControllerExecFlags = one of {[f'0x{v:08X}' for v in sorted(shared)]}")
        return first, second, shared
    else:
        print("  >>> NO PAIRS FOUND")
        # Fallback: show individual candidates
        print("  Falling back to individual analysis...")
        for info in sorted_filtered[:5]:
            print()
            print(f"  --- Candidate: 0x{info['addr']:08X} ---")
            print_function_detail(rom_data, info, max_disasm=40)
        return None, None, set()


# =============================================================================
# TARGET 5: PrepareBufferDataTransferLink
# =============================================================================

def find_prepare_buffer_data_transfer_link(rom_data):
    """Find PrepareBufferDataTransferLink: small, refs gBattleResources, contains link send code."""
    print()
    print("=" * 80)
    print("  TARGET 5: PrepareBufferDataTransferLink")
    print("  Vanilla: 0x080331B8 | Small (60-150 bytes)")
    print("  Refs: gBattleResources | Contains link data send code")
    print("=" * 80)
    print()

    # Build from gBattleResources refs, filter for small functions
    print("  Step 1: Filtering gBattleResources functions for small size + link patterns...")
    br_funcs = build_function_db(rom_data, KNOWN["gBattleResources"])

    candidates = []
    for func_start, info in br_funcs.items():
        score = 0
        reasons = []

        # Size: 40-200 bytes (small)
        if 40 <= info['size'] <= 200:
            score += 20
            reasons.append(f"good size ({info['size']} bytes)")
        elif 200 < info['size'] <= 300:
            score += 5
            reasons.append(f"slightly large ({info['size']} bytes)")
        else:
            continue  # Skip

        # BL count: 1-5
        bl_count = len(info['bl_targets'])
        if 1 <= bl_count <= 6:
            score += 15
            reasons.append(f"few BL calls ({bl_count})")
        elif bl_count == 0:
            score += 5
            reasons.append("no BL calls")
        else:
            continue  # Too many BLs

        # Must reference gBattleResources
        if KNOWN["gBattleResources"] in info['lit_vals']:
            score += 5
            reasons.append("refs gBattleResources")

        # The function name suggests it prepares data for link transfer
        # It should reference some buffer address and possibly gWirelessCommType
        if KNOWN["gWirelessCommType"] in info['lit_vals']:
            score += 10
            reasons.append("refs gWirelessCommType")

        # Look for link-related IWRAM refs
        for v in info['iwram_vals']:
            if v == KNOWN.get("gBlockReceivedStatus"):
                score += 10
                reasons.append("refs gBlockReceivedStatus")
            elif v == KNOWN.get("gReceivedRemoteLinkPlayers"):
                score += 5
                reasons.append("refs gReceivedRemoteLinkPlayers")

        # In vanilla, PrepareBufferDataTransferLink is near SetUpBattleVars
        # (0x080331B8 vs 0x0803269C, delta ~0xB1C)
        # Check if this function is in a similar ROM region to battle code
        rom_off = info['start']
        if 0x30000 <= rom_off <= 0x40000:
            score += 5
            reasons.append("in expected ROM region")

        # Look for memcpy/DMA-like patterns (writing to buffer)
        disasm = disassemble_range(rom_data, info['start'], info['end'], max_instrs=60)
        has_strb_loop = False
        has_ldrb_strb = False
        for i, (off, addr, raw, mnem) in enumerate(disasm):
            if "STRB" in mnem or "STRH" in mnem or "STR " in mnem:
                if i > 0 and ("LDRB" in disasm[i-1][3] or "LDRH" in disasm[i-1][3] or "LDR " in disasm[i-1][3]):
                    has_ldrb_strb = True
            # Look for "B" back to earlier address (loop)
            if mnem.startswith("B 0x") or mnem.startswith("BNE 0x") or mnem.startswith("BCC 0x"):
                try:
                    target_hex = mnem.split("0x")[1][:8]
                    target_addr = int(target_hex, 16)
                    if target_addr < addr:
                        has_strb_loop = True
                except:
                    pass

        if has_ldrb_strb:
            score += 5
            reasons.append("has LDR+STR pattern (data copy)")
        if has_strb_loop:
            score += 5
            reasons.append("has backward branch (loop)")

        if score >= 15:
            candidates.append((score, info, reasons))

    candidates.sort(key=lambda x: -x[0])

    print()
    print("  RANKED CANDIDATES:")
    print()
    for rank, (score, info, reasons) in enumerate(candidates[:8]):
        marker = ""
        if rank == 0: marker = "  <<<< BEST MATCH"
        print(f"  #{rank+1} Score={score} | 0x{info['addr']:08X} ({info['size']} bytes){marker}")
        for r in reasons:
            print(f"       - {r}")
        print()
        print_function_detail(rom_data, info, max_disasm=60)
        print("    " + "-" * 70)
        print()

    if candidates:
        best = candidates[0][1]
        print(f"  >>> RESULT: PrepareBufferDataTransferLink = 0x{best['addr']:08X}")
        print(f"  >>> ROM offset: 0x{best['start']:06X}")
        print(f"  >>> Size: {best['size']} bytes")
        print()
        print("  >>> PATCH SUGGESTION (PK-GBA reference: +0x16 = B +9 = 0xE009):")
        print("  >>> Skip the link send code - replace conditional branch with unconditional B")
        return best
    else:
        print("  >>> NO CANDIDATES FOUND")
        return None


# =============================================================================
# PATCH POINT ANALYSIS
# =============================================================================

def analyze_patch_points(rom_data, func_info, func_name):
    """Analyze a function to suggest specific patch points based on PK-GBA patterns."""
    if func_info is None:
        return

    print()
    print(f"  PATCH POINT ANALYSIS: {func_name}")
    print(f"  Address: 0x{func_info['addr']:08X}")
    print()

    disasm = disassemble_range(rom_data, func_info['start'], func_info['end'], max_instrs=200)

    # Find all interesting patterns
    patterns = []

    for i, (off, addr, raw, mnem) in enumerate(disasm):
        func_off = off - func_info['start']

        # Pattern: BL to GetMultiplayerId
        if "BL" in mnem and f"0x{KNOWN['GetMultiplayerId']:08X}" in mnem:
            patterns.append((func_off, "BL_GetMultiplayerId", mnem))

        # Pattern: Load gWirelessCommType then check
        if "0x030030FC" in mnem:
            patterns.append((func_off, "LDR_gWirelessCommType", mnem))

        # Pattern: Load gReceivedRemoteLinkPlayers
        if "0x03003124" in mnem:
            patterns.append((func_off, "LDR_gReceivedRemoteLinkPlayers", mnem))

        # Pattern: CMP + conditional branch (potential patch point)
        if "CMP" in mnem:
            if i + 1 < len(disasm):
                next_mnem = disasm[i+1][3]
                if next_mnem.startswith("BEQ") or next_mnem.startswith("BNE"):
                    next_off = disasm[i+1][0] - func_info['start']
                    patterns.append((func_off, f"CMP+{next_mnem[:3]}", f"{mnem} -> {next_mnem}"))

        # Pattern: NOP (already patched?)
        if mnem == "NOP":
            patterns.append((func_off, "NOP", mnem))

        # Pattern: Switch case (CMP followed by BHI or sequence of BEQ)
        if "CMP" in mnem:
            check_range = disasm[i+1:i+4]
            for _, _, _, m in check_range:
                if "BHI" in m or "BLS" in m:
                    patterns.append((func_off, "SWITCH_CASE", f"{mnem} followed by {m}"))
                    break

    if patterns:
        print("    Interesting patterns found:")
        for off, ptype, detail in patterns:
            print(f"      +0x{off:04X}: [{ptype}] {detail}")
    else:
        print("    No specific patterns found (manual inspection needed)")
    print()


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not ROM_PATH.exists():
        # Try auto-detect
        alt_paths = [
            Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba",
            Path("rom") / "Pokemon RunBun.gba",
        ]
        rom_path = None
        for p in alt_paths:
            if p.exists():
                rom_path = p
                break
        if rom_path is None:
            print(f"ERROR: ROM not found at {ROM_PATH}")
            print(f"  Expected: {ROM_PATH.resolve()}")
            sys.exit(1)
    else:
        rom_path = ROM_PATH

    rom_data = rom_path.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size:,} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print(f"ROM path: {rom_path.resolve()}")
    print()

    # Verify known addresses have literal pool refs
    print("=" * 80)
    print("  PRELIMINARY: Verifying known anchor literal pool reference counts")
    print("=" * 80)
    print()
    for name, addr in sorted(KNOWN.items()):
        refs = find_all_literal_refs(rom_data, addr)
        print(f"  {name:<35s} (0x{addr:08X}): {len(refs):4d} ROM refs")
    print()

    # Find all 5 targets
    cb2_hsb = find_cb2_handle_start_battle(rom_data)
    subv = find_setup_battle_vars(rom_data)
    player_bec, link_bec, shared_ewram = find_buffer_exec_completed_pair(rom_data)
    prepare_bdtl = find_prepare_buffer_data_transfer_link(rom_data)

    # Patch point analysis
    print()
    print("=" * 80)
    print("  PATCH POINT ANALYSIS FOR ALL TARGETS")
    print("=" * 80)
    analyze_patch_points(rom_data, cb2_hsb, "CB2_HandleStartBattle")
    analyze_patch_points(rom_data, subv, "SetUpBattleVars")
    analyze_patch_points(rom_data, player_bec, "PlayerBufferExecCompleted")
    analyze_patch_points(rom_data, link_bec, "LinkOpponentBufferExecCompleted")
    analyze_patch_points(rom_data, prepare_bdtl, "PrepareBufferDataTransferLink")

    # Final summary
    print()
    print("=" * 80)
    print("  FINAL SUMMARY")
    print("=" * 80)
    print()

    results = [
        ("CB2_HandleStartBattle", cb2_hsb),
        ("SetUpBattleVars", subv),
        ("PlayerBufferExecCompleted", player_bec),
        ("LinkOpponentBufferExecCompleted", link_bec),
        ("PrepareBufferDataTransferLink", prepare_bdtl),
    ]

    for name, info in results:
        if info:
            print(f"  {name:<40s} = 0x{info['addr']:08X}  ({info['size']} bytes, ROM offset 0x{info['start']:06X})")
        else:
            print(f"  {name:<40s} = NOT FOUND")

    if shared_ewram:
        print()
        print(f"  gBattleControllerExecFlags candidates: {[f'0x{v:08X}' for v in sorted(shared_ewram)]}")

    print()
    print("  Known addresses for reference:")
    print(f"  {'GetMultiplayerId':<40s} = 0x{KNOWN['GetMultiplayerId']:08X}  (confirmed)")
    print(f"  {'gBattleResources':<40s} = 0x{KNOWN['gBattleResources']:08X}")
    print(f"  {'gWirelessCommType':<40s} = 0x{KNOWN['gWirelessCommType']:08X}")
    print(f"  {'gReceivedRemoteLinkPlayers':<40s} = 0x{KNOWN['gReceivedRemoteLinkPlayers']:08X}")
    print(f"  {'gBattleTypeFlags':<40s} = 0x{KNOWN['gBattleTypeFlags']:08X}")
    print()

    # PK-GBA patch reference
    print("  PK-GBA PATCH REFERENCE:")
    print("  +-----------------------------------------+------------------+-------------------------+")
    print("  | Function                                | Vanilla addr     | Patch                   |")
    print("  +-----------------------------------------+------------------+-------------------------+")
    print("  | CB2_HandleStartBattle case 1            | 0x08036FAC       | +offset: B +6 (0xE006)  |")
    print("  | CB2_HandleStartBattle case 12           | 0x08036FAC       | +offset: 2x NOP (46C0)  |")
    print("  | SetUpBattleVars +0x42,+0x44             | 0x0803269C       | 2x NOP (0x46C0)         |")
    print("  | PlayerBufferExecCompleted +0x1C         | 0x0805748C       | B +0x1A (0xE01A)        |")
    print("  | LinkOpponentBufferExecCompleted +0x1C   | 0x08065068       | B +0x1A (0xE01A)        |")
    print("  | PrepareBufferDataTransferLink +0x16     | 0x080331B8       | B +9 (0xE009)           |")
    print("  +-----------------------------------------+------------------+-------------------------+")
    print()
    print("  NOTE: The exact offsets within each function will differ in R&B vs vanilla.")
    print("  Use the disassembly above to find the equivalent instruction to patch.")
    print()
    print("=" * 80)
    print("  SCAN COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
