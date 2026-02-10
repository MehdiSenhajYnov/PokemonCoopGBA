#!/usr/bin/env python3
"""
ROM Scanner -- Find BeginNormalPaletteFade and UpdatePaletteFade in Pokemon Run & Bun

Known addresses:
  gPaletteFade       = 0x02037594  (EWRAM, 8 bytes packed bitfield struct)
  gPlttBufferUnfaded = 0x02036CD4  (EWRAM, 1024 bytes = 512 colors)
  gPlttBufferFaded   = 0x020370D4  (EWRAM, 1024 bytes = 512 colors)

Strategy:
  1. Scan the ROM for literal pool references to gPaletteFade (0x02037594)
  2. For each reference, find the containing function (search backwards for PUSH{...,LR})
  3. Identify BeginNormalPaletteFade by its signature:
     - References gPaletteFade
     - Also references gPlttBufferFaded (copies faded -> unfaded at start)
     - Checks the active bit (LDRB +0x07, TST #0x80) and returns early if active
     - Called from many places (common utility), ~120-200 bytes
     - Writes multiple fields: STR [Rn,#0], STRB [Rn,#4], STRB [Rn,#5], etc.
  4. Identify UpdatePaletteFade:
     - Also references gPaletteFade
     - References gPlttBufferFaded AND gPlttBufferUnfaded (blends palettes)
     - Larger function (~300-600 bytes), more BL calls (BlendPalettes, etc.)
     - Usually near BeginNormalPaletteFade in ROM

Output: addresses and first 32 bytes of each function found.

No Ghidra needed -- reads the .gba file directly.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known addresses (confirmed in find_palette_vars.py)
KNOWN = {
    "gPaletteFade":       0x02037594,
    "gPlttBufferUnfaded": 0x02036CD4,
    "gPlttBufferFaded":   0x020370D4,
}

# gPaletteFade struct layout:
#   +0x00: selectedPalettes (u32)
#   +0x04: delayCounter:6, y:5, targetY:5 (packed)
#   +0x05: continuation of packed bitfields
#   +0x06: blendColor (u16, 15 bits)
#   +0x07: flags byte -- bit 7 = active (0x80), bit 6 = yDec (0x40)

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
    """Find all 4-byte aligned positions in ROM where target_value appears (literal pool entries)."""
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs


# =============================================================================
# LDR Rd,[PC,#imm] resolver
# =============================================================================

def resolve_ldr_pc(rom_data, pos):
    """If instruction at pos is LDR Rd,[PC,#imm], return the loaded value. Else None."""
    if pos + 1 >= len(rom_data):
        return None
    instr = read_u16(rom_data, pos)
    if (instr & 0xF800) != 0x4800:
        return None
    imm = (instr & 0xFF) << 2
    ldr_addr = ((pos + 4) & ~3) + imm
    if ldr_addr + 3 >= len(rom_data):
        return None
    return read_u32(rom_data, ldr_addr)


# =============================================================================
# Function boundary detection
# =============================================================================

def find_function_start(rom_data, offset, max_back=2048):
    """Walk backward from offset to find PUSH {..., LR} = 0xB5xx."""
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16(rom_data, pos)
        if (instr & 0xFF00) == 0xB500:
            return pos
    return None


def find_function_end(rom_data, func_start, max_size=2048):
    """Find function end: first POP {PC} or BX LR after the first instruction.
    For small-to-medium functions. Skips BL 32-bit pairs."""
    pos = func_start + 2
    limit = min(func_start + max_size, len(rom_data) - 2)

    while pos < limit:
        instr = read_u16(rom_data, pos)

        # POP {..., PC}
        if (instr & 0xFF00) == 0xBD00:
            return pos + 2

        # BX LR
        if instr == 0x4770:
            return pos + 2

        # Skip BL 32-bit instruction pairs
        if (instr & 0xF800) == 0xF000 and pos + 2 < limit:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue

        pos += 2

    return None


def find_function_end_large(rom_data, func_start, max_size=2048):
    """Find function end for larger functions that may have multiple POP {PC} (switch/case).
    Returns the last POP {PC} before a new PUSH {LR}."""
    pos = func_start + 2
    limit = min(func_start + max_size, len(rom_data) - 2)
    last_end = None

    while pos < limit:
        instr = read_u16(rom_data, pos)

        # POP {..., PC}
        if (instr & 0xFF00) == 0xBD00:
            last_end = pos + 2
            # If next instruction is a new PUSH {LR}, this is the real end
            if pos + 2 < limit:
                next_instr = read_u16(rom_data, pos + 2)
                if (next_instr & 0xFF00) == 0xB500:
                    return pos + 2
            pos += 2
            continue

        # BX LR
        if instr == 0x4770:
            last_end = pos + 2
            if pos + 2 < limit:
                next_instr = read_u16(rom_data, pos + 2)
                if (next_instr & 0xFF00) == 0xB500:
                    return pos + 2
            pos += 2
            continue

        # New PUSH {LR} well past the function start = new function
        if (instr & 0xFF00) == 0xB500 and pos > func_start + 4:
            if last_end is not None:
                return last_end
            return pos

        # Skip BL 32-bit
        if (instr & 0xF800) == 0xF000 and pos + 2 < limit:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue

        pos += 2

    return last_end if last_end else func_start + max_size


# =============================================================================
# BL target decoder
# =============================================================================

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


# =============================================================================
# Function analysis
# =============================================================================

def analyze_function(rom_data, func_start, func_end):
    """Analyze a function and return a dict of properties."""
    size = func_end - func_start
    func_addr = ROM_BASE + func_start + 1  # +1 for THUMB bit

    # Extract all LDR Rd,[PC,#imm] literal values
    lit_vals = set()
    ewram_vals = set()
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        val = resolve_ldr_pc(rom_data, pos)
        if val is not None:
            lit_vals.add(val)
            if 0x02000000 <= val < 0x02040000:
                ewram_vals.add(val)
        instr = read_u16(rom_data, pos)
        if (instr & 0xF800) == 0xF000 and pos + 2 < func_end:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2

    # Extract BL targets
    bl_targets = []
    pos = func_start
    while pos < func_end and pos + 4 <= len(rom_data):
        t = decode_bl_target(rom_data, pos)
        if t is not None:
            bl_targets.append((pos - func_start, t))
            pos += 4
        else:
            pos += 2

    # Count STRB [Rn, #imm] instructions and collect offsets
    strb_offsets = set()
    ldrb_offsets = set()
    str_offsets = set()
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        if (instr & 0xF800) == 0x7000:  # STRB Rd, [Rn, #imm5]
            off = (instr >> 6) & 0x1F
            strb_offsets.add(off)
        elif (instr & 0xF800) == 0x7800:  # LDRB Rd, [Rn, #imm5]
            off = (instr >> 6) & 0x1F
            ldrb_offsets.add(off)
        elif (instr & 0xF800) == 0x6000:  # STR Rd, [Rn, #imm5*4]
            off = ((instr >> 6) & 0x1F) << 2
            str_offsets.add(off)
        if (instr & 0xF800) == 0xF000 and pos + 2 < func_end:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2

    # Check for TST Rn, Rm or AND pattern (active bit check)
    has_tst = False
    pos = func_start
    while pos < func_end and pos + 2 <= len(rom_data):
        instr = read_u16(rom_data, pos)
        if (instr & 0xFFC0) == 0x4200:  # TST Rn, Rm
            has_tst = True
            break
        if (instr & 0xFFC0) == 0x4000:  # AND Rd, Rm
            has_tst = True
            break
        if (instr & 0xF800) == 0xF000 and pos + 2 < func_end:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2

    # Caller count will be filled in later by the batch caller counter
    caller_count = 0

    return {
        'start': func_start,
        'end': func_end,
        'size': size,
        'addr': func_addr,
        'lit_vals': lit_vals,
        'ewram_vals': ewram_vals,
        'bl_targets': bl_targets,
        'strb_offsets': strb_offsets,
        'ldrb_offsets': ldrb_offsets,
        'str_offsets': str_offsets,
        'has_tst': has_tst,
        'caller_count': caller_count,
    }


# =============================================================================
# Batch caller counter — builds BL target index ONCE, then looks up all funcs
# =============================================================================

def build_bl_target_index(rom_data):
    """Build a dict mapping BL target addresses to caller counts. Single pass over ROM."""
    print("  Building BL target index (single ROM pass)...", flush=True)
    index = defaultdict(int)
    rom_len = len(rom_data)
    pos = 0
    while pos < rom_len - 4:
        hi = read_u16(rom_data, pos)
        if (hi & 0xF800) == 0xF000:
            lo = read_u16(rom_data, pos + 2)
            if (lo & 0xF800) == 0xF800:
                full = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
                if full >= 0x400000:
                    full -= 0x800000
                target = ROM_BASE + pos + 4 + full
                index[target] += 1
                index[target | 1] += 1  # also count THUMB-bit variant
                pos += 4
                continue
        pos += 2
    print(f"  BL target index built: {len(index)} unique targets", flush=True)
    return index


def fill_caller_counts(functions, bl_index):
    """Fill in caller_count for all functions using the pre-built BL index."""
    for info in functions:
        addr_thumb = info['addr']       # with THUMB bit
        addr_plain = addr_thumb & ~1     # without THUMB bit
        info['caller_count'] = max(bl_index.get(addr_thumb, 0), bl_index.get(addr_plain, 0))


# =============================================================================
# THUMB disassembler (compact)
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
            mnem = f"MOV R{rd}, #0x{imm:02X}"

        # CMP Rn, #imm
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7
            imm = instr & 0xFF
            mnem = f"CMP R{rn}, #0x{imm:02X}"

        # ADD Rd, #imm
        elif (instr & 0xF800) == 0x3000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            mnem = f"ADD R{rd}, #0x{imm:02X}"

        # SUB Rd, #imm
        elif (instr & 0xF800) == 0x3800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            mnem = f"SUB R{rd}, #0x{imm:02X}"

        # LDR Rd, [PC, #imm] (literal pool)
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(rom_data):
                val = read_u32(rom_data, lit_off)
                label = ""
                for name, known_addr in KNOWN.items():
                    if val == known_addr:
                        label = f"  ; {name}"
                        break
                mnem = f"LDR R{rd}, =0x{val:08X}{label}"
            else:
                mnem = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"

        # LDR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            mnem = f"LDR R{rd}, [R{rn}, #0x{imm:X}]"

        # STR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 4
            mnem = f"STR R{rd}, [R{rn}, #0x{imm:X}]"

        # LDRB Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x7800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            mnem = f"LDRB R{rd}, [R{rn}, #0x{imm:X}]"

        # STRB Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x7000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = (instr >> 6) & 0x1F
            mnem = f"STRB R{rd}, [R{rn}, #0x{imm:X}]"

        # LDRH Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x8800:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            mnem = f"LDRH R{rd}, [R{rn}, #0x{imm:X}]"

        # STRH Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x8000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm = ((instr >> 6) & 0x1F) * 2
            mnem = f"STRH R{rd}, [R{rn}, #0x{imm:X}]"

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

        # SP adjust
        elif (instr & 0xFF00) == 0xB000:
            imm = (instr & 0x7F) * 4
            if instr & 0x80:
                mnem = f"SUB SP, #0x{imm:X}"
            else:
                mnem = f"ADD SP, #0x{imm:X}"

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

        # ADD 3-reg
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

        # NOP
        elif instr == 0x46C0:
            mnem = "NOP"

        else:
            mnem = f"??? 0x{instr:04X}"

        lines.append((pos, addr, raw, mnem))
        pos += 2

    return lines


# =============================================================================
# Print helpers
# =============================================================================

def print_function_header(rom_data, info, label):
    """Print a formatted header block for a function candidate."""
    print(f"    [{label}]")
    print(f"    Address:    0x{info['addr']:08X} (ROM offset 0x{info['start']:06X})")
    print(f"    Size:       {info['size']} bytes")
    print(f"    BL calls:   {len(info['bl_targets'])}")
    print(f"    Callers:    {info['caller_count']}")
    print(f"    Has TST:    {info['has_tst']}")
    print(f"    STRB offs:  {sorted(info['strb_offsets'])}")
    print(f"    LDRB offs:  {sorted(info['ldrb_offsets'])}")
    print(f"    STR offs:   {sorted(info['str_offsets'])}")
    print(f"    EWRAM refs: {[f'0x{v:08X}' for v in sorted(info['ewram_vals'])]}")


def print_first_bytes(rom_data, func_start, count=32):
    """Print the first `count` bytes of a function as hex."""
    end = min(func_start + count, len(rom_data))
    data = rom_data[func_start:end]
    hex_str = " ".join(f"{b:02X}" for b in data)
    print(f"    First {count} bytes: {hex_str}")


def print_disassembly(rom_data, info, max_instrs=60):
    """Print disassembly of a function."""
    disasm = disassemble_range(rom_data, info['start'], info['end'], max_instrs=max_instrs)
    print(f"    Disassembly ({min(len(disasm), max_instrs)} instructions):")
    for off, addr, raw, mnem in disasm:
        func_off = off - info['start']
        print(f"      +0x{func_off:04X} | 0x{addr:08X}: {raw:<12s} {mnem}")


# =============================================================================
# PHASE 1: Find all functions referencing gPaletteFade
# =============================================================================

def find_palette_fade_functions(rom_data):
    """Find all functions that reference gPaletteFade via literal pool."""
    print("=" * 70)
    print("  PHASE 1: Find all functions referencing gPaletteFade (0x{:08X})".format(
        KNOWN["gPaletteFade"]))
    print("=" * 70)
    print()

    # Step 1a: Find literal pool entries for gPaletteFade
    fade_refs = find_all_literal_refs(rom_data, KNOWN["gPaletteFade"])
    print(f"  gPaletteFade literal pool entries: {len(fade_refs)}")

    # Step 1b: Also find LDR instructions that reference these literal pool entries
    # (within 1024 bytes before each literal)
    ldr_positions = []
    for lit_off in fade_refs:
        # Search backwards up to 1020 bytes for LDR Rd,[PC,#imm] pointing here
        for scan_pos in range(max(0, lit_off - 1020), lit_off, 2):
            val = resolve_ldr_pc(rom_data, scan_pos)
            if val == KNOWN["gPaletteFade"]:
                ldr_positions.append(scan_pos)

    print(f"  LDR instructions loading gPaletteFade: {len(ldr_positions)}")
    print()

    # Step 1c: Find unique containing functions
    seen_starts = set()
    functions = []

    for ldr_pos in ldr_positions:
        func_start = find_function_start(rom_data, ldr_pos)
        if func_start is None or func_start in seen_starts:
            continue
        seen_starts.add(func_start)

        # Try simple end first, fall back to large
        func_end = find_function_end(rom_data, func_start, max_size=1024)
        if func_end is None:
            func_end = find_function_end_large(rom_data, func_start, max_size=1024)
        if func_end is None:
            func_end = func_start + 300

        info = analyze_function(rom_data, func_start, func_end)
        functions.append(info)

    print(f"  Unique functions referencing gPaletteFade: {len(functions)}")
    print()

    return functions


# =============================================================================
# PHASE 2: Identify BeginNormalPaletteFade
# =============================================================================

def identify_begin_normal_palette_fade(rom_data, functions):
    """Score and rank candidates for BeginNormalPaletteFade."""
    print("=" * 70)
    print("  PHASE 2: Identify BeginNormalPaletteFade")
    print("=" * 70)
    print()

    # BeginNormalPaletteFade signature:
    # - References gPaletteFade (required -- already filtered)
    # - Also references gPlttBufferFaded (copies faded -> unfaded via CpuFastSet)
    # - Checks active bit: LDRB [Rn,#7] then TST/AND #0x80 then BNE (return early)
    # - Writes struct fields: STR [Rn,#0] (selectedPalettes), STRB [Rn,#4], STRB [Rn,#5], etc.
    # - ~100-250 bytes
    # - Many callers (200+, it's a common utility)
    # - Has 1-3 BL calls (CpuFastSet, maybe BlendPalette)

    candidates = []

    for info in functions:
        score = 0
        reasons = []

        # --- Size check ---
        if 80 <= info['size'] <= 300:
            score += 15
            reasons.append(f"good size ({info['size']} bytes)")
        elif 300 < info['size'] <= 500:
            score += 5
            reasons.append(f"slightly large ({info['size']} bytes)")
        else:
            reasons.append(f"size out of range ({info['size']} bytes)")

        # --- References gPlttBufferFaded ---
        if KNOWN["gPlttBufferFaded"] in info['ewram_vals']:
            score += 25
            reasons.append("refs gPlttBufferFaded")

        # --- References gPlttBufferUnfaded ---
        if KNOWN["gPlttBufferUnfaded"] in info['ewram_vals']:
            score += 10
            reasons.append("refs gPlttBufferUnfaded")

        # --- Struct field access pattern ---
        # BeginNormalPaletteFade writes: STR [Rn,#0], STRB [Rn,#4], STRB [Rn,#5], STRB [Rn,#6], STRB [Rn,#7]
        fade_write_offsets = {0, 4, 5, 6, 7}
        matching_strb = info['strb_offsets'] & fade_write_offsets
        matching_str = info['str_offsets'] & {0}
        total_field_matches = len(matching_strb) + len(matching_str)
        if total_field_matches >= 4:
            score += 20
            reasons.append(f"writes gPaletteFade fields (STRB@{sorted(matching_strb)}, STR@{sorted(matching_str)})")
        elif total_field_matches >= 2:
            score += 10
            reasons.append(f"partial field writes ({total_field_matches} matches)")

        # --- Active bit check (LDRB [Rn,#7] + TST) ---
        if 7 in info['ldrb_offsets'] and info['has_tst']:
            score += 15
            reasons.append("checks active bit (LDRB #7 + TST)")
        elif 7 in info['ldrb_offsets']:
            score += 5
            reasons.append("reads flags byte (LDRB #7)")

        # --- BL count ---
        bl_count = len(info['bl_targets'])
        if 1 <= bl_count <= 4:
            score += 10
            reasons.append(f"BL calls = {bl_count} (expected 1-3)")
        elif bl_count == 0:
            score += 3
            reasons.append("no BL calls (inlined CpuFastSet?)")
        else:
            reasons.append(f"many BL calls ({bl_count})")

        # --- Caller count: BeginNormalPaletteFade should be called from MANY places ---
        if info['caller_count'] >= 200:
            score += 30
            reasons.append(f"very many callers ({info['caller_count']}) -- strong indicator")
        elif info['caller_count'] >= 100:
            score += 20
            reasons.append(f"many callers ({info['caller_count']})")
        elif info['caller_count'] >= 30:
            score += 10
            reasons.append(f"moderate callers ({info['caller_count']})")
        else:
            reasons.append(f"few callers ({info['caller_count']})")

        candidates.append((score, info, reasons))

    candidates.sort(key=lambda x: -x[0])

    # Print ranked results
    print("  RANKED CANDIDATES FOR BeginNormalPaletteFade:")
    print()
    for rank, (score, info, reasons) in enumerate(candidates[:10]):
        marker = "  <<<< BEST MATCH" if rank == 0 else ""
        print(f"  #{rank+1} Score={score} | 0x{info['addr']:08X} ({info['size']} bytes, {info['caller_count']} callers){marker}")
        for r in reasons:
            print(f"       - {r}")
        print()

    # Print detailed info for top 3
    print()
    print("  DETAILED ANALYSIS (top 3):")
    print()
    for rank, (score, info, reasons) in enumerate(candidates[:3]):
        print(f"  --- Candidate #{rank+1} (score={score}) ---")
        print_function_header(rom_data, info, f"#{rank+1}")
        print_first_bytes(rom_data, info['start'], 32)
        print()
        print_disassembly(rom_data, info, max_instrs=60)
        print()
        print("    " + "-" * 60)
        print()

    if candidates:
        best = candidates[0]
        return best[1]
    return None


# =============================================================================
# PHASE 3: Identify UpdatePaletteFade
# =============================================================================

def identify_update_palette_fade(rom_data, functions, begin_fade_info):
    """Score and rank candidates for UpdatePaletteFade."""
    print("=" * 70)
    print("  PHASE 3: Identify UpdatePaletteFade")
    print("=" * 70)
    print()

    # UpdatePaletteFade signature:
    # - References gPaletteFade (required -- already filtered)
    # - References BOTH gPlttBufferFaded AND gPlttBufferUnfaded (blends them)
    # - Larger than BeginNormalPaletteFade (~200-600 bytes)
    # - More BL calls (BlendPalettes, CpuFastSet, etc.)
    # - Fewer callers than BeginNormalPaletteFade (called from main loop, ~5-30 callers)
    # - Reads active bit, decrements/increments y, checks delayCounter
    # - Often near BeginNormalPaletteFade in ROM

    begin_fade_start = begin_fade_info['start'] if begin_fade_info else 0

    candidates = []

    for info in functions:
        # Skip BeginNormalPaletteFade itself
        if begin_fade_info and info['start'] == begin_fade_info['start']:
            continue

        score = 0
        reasons = []

        # --- Must reference BOTH buffers ---
        has_faded = KNOWN["gPlttBufferFaded"] in info['ewram_vals']
        has_unfaded = KNOWN["gPlttBufferUnfaded"] in info['ewram_vals']
        if has_faded and has_unfaded:
            score += 30
            reasons.append("refs BOTH gPlttBufferFaded and gPlttBufferUnfaded")
        elif has_faded:
            score += 10
            reasons.append("refs gPlttBufferFaded only")
        elif has_unfaded:
            score += 10
            reasons.append("refs gPlttBufferUnfaded only")
        else:
            reasons.append("does NOT ref either buffer")

        # --- Size check ---
        if 150 <= info['size'] <= 700:
            score += 15
            reasons.append(f"good size ({info['size']} bytes)")
        elif 100 <= info['size'] < 150:
            score += 5
            reasons.append(f"slightly small ({info['size']} bytes)")
        elif info['size'] > 700:
            score += 5
            reasons.append(f"large ({info['size']} bytes)")
        else:
            reasons.append(f"too small ({info['size']} bytes)")

        # --- BL calls ---
        bl_count = len(info['bl_targets'])
        if 3 <= bl_count <= 15:
            score += 10
            reasons.append(f"BL calls = {bl_count} (expected 3-10+)")
        elif bl_count >= 2:
            score += 5
            reasons.append(f"BL calls = {bl_count}")
        else:
            reasons.append(f"too few BL calls ({bl_count})")

        # --- Caller count: UpdatePaletteFade has moderate callers ---
        if 3 <= info['caller_count'] <= 50:
            score += 15
            reasons.append(f"moderate callers ({info['caller_count']})")
        elif info['caller_count'] > 50:
            score += 5
            reasons.append(f"many callers ({info['caller_count']}) -- might be too many for Update")
        else:
            reasons.append(f"very few callers ({info['caller_count']})")

        # --- Reads active bit (LDRB #7) ---
        if 7 in info['ldrb_offsets']:
            score += 10
            reasons.append("reads flags byte (LDRB #7)")

        # --- Field access: reads/writes y, delayCounter, targetY ---
        # These are at offsets 4, 5, 6 in the struct
        fade_rw_offsets = {4, 5, 6, 7}
        matching = (info['ldrb_offsets'] | info['strb_offsets']) & fade_rw_offsets
        if len(matching) >= 3:
            score += 10
            reasons.append(f"accesses multiple gPaletteFade fields ({sorted(matching)})")

        # --- Proximity to BeginNormalPaletteFade ---
        if begin_fade_start > 0:
            distance = abs(info['start'] - begin_fade_start)
            if distance < 0x200:
                score += 10
                reasons.append(f"near BeginNormalPaletteFade (delta=0x{distance:X})")
            elif distance < 0x1000:
                score += 5
                reasons.append(f"moderately near BeginNormalPaletteFade (delta=0x{distance:X})")

        candidates.append((score, info, reasons))

    candidates.sort(key=lambda x: -x[0])

    # Print ranked results
    print("  RANKED CANDIDATES FOR UpdatePaletteFade:")
    print()
    for rank, (score, info, reasons) in enumerate(candidates[:10]):
        marker = "  <<<< BEST MATCH" if rank == 0 else ""
        print(f"  #{rank+1} Score={score} | 0x{info['addr']:08X} ({info['size']} bytes, {info['caller_count']} callers){marker}")
        for r in reasons:
            print(f"       - {r}")
        print()

    # Print detailed info for top 3
    print()
    print("  DETAILED ANALYSIS (top 3):")
    print()
    for rank, (score, info, reasons) in enumerate(candidates[:3]):
        print(f"  --- Candidate #{rank+1} (score={score}) ---")
        print_function_header(rom_data, info, f"#{rank+1}")
        print_first_bytes(rom_data, info['start'], 32)
        print()
        print_disassembly(rom_data, info, max_instrs=80)
        print()
        print("    " + "-" * 60)
        print()

    if candidates:
        best = candidates[0]
        return best[1]
    return None


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        print(f"  Expected: {ROM_PATH.resolve()}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size:,} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print(f"ROM path: {ROM_PATH.resolve()}")
    print()

    # Verify known addresses
    print("=" * 70)
    print("  PRELIMINARY: Verify known address literal pool ref counts")
    print("=" * 70)
    print()
    for name, addr in sorted(KNOWN.items()):
        refs = find_all_literal_refs(rom_data, addr)
        print(f"  {name:<25s} (0x{addr:08X}): {len(refs):4d} literal pool entries")
    print()

    # Phase 1: Find all functions referencing gPaletteFade
    functions = find_palette_fade_functions(rom_data)

    # Build BL index and fill caller counts (single pass, much faster)
    bl_index = build_bl_target_index(rom_data)
    fill_caller_counts(functions, bl_index)

    # Phase 2: Identify BeginNormalPaletteFade
    begin_fade = identify_begin_normal_palette_fade(rom_data, functions)

    # Phase 3: Identify UpdatePaletteFade
    update_fade = identify_update_palette_fade(rom_data, functions, begin_fade)

    # ==========================================================================
    # FINAL SUMMARY
    # ==========================================================================
    print()
    print("=" * 70)
    print("  FINAL SUMMARY")
    print("=" * 70)
    print()

    if begin_fade:
        print(f"  BeginNormalPaletteFade = 0x{begin_fade['addr']:08X}")
        print(f"    ROM offset: 0x{begin_fade['start']:06X}")
        print(f"    Size:       {begin_fade['size']} bytes")
        print(f"    Callers:    {begin_fade['caller_count']}")
        print_first_bytes(rom_data, begin_fade['start'], 32)
    else:
        print("  BeginNormalPaletteFade = NOT FOUND")

    print()

    if update_fade:
        print(f"  UpdatePaletteFade     = 0x{update_fade['addr']:08X}")
        print(f"    ROM offset: 0x{update_fade['start']:06X}")
        print(f"    Size:       {update_fade['size']} bytes")
        print(f"    Callers:    {update_fade['caller_count']}")
        print_first_bytes(rom_data, update_fade['start'], 32)
    else:
        print("  UpdatePaletteFade     = NOT FOUND")

    print()
    print("  Known addresses:")
    print(f"    gPaletteFade       = 0x{KNOWN['gPaletteFade']:08X}")
    print(f"    gPlttBufferUnfaded = 0x{KNOWN['gPlttBufferUnfaded']:08X}")
    print(f"    gPlttBufferFaded   = 0x{KNOWN['gPlttBufferFaded']:08X}")

    print()
    print("=" * 70)
    print("  SCAN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
