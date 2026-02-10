#!/usr/bin/env python3
"""
ROM Scanner -- Re-verify gPaletteFade, gPlttBufferUnfaded, gPlttBufferFaded in Pokemon Run & Bun

MOTIVATION:
  The palette force-complete code at 0x0203759B did not trigger during battle.
  This may mean gPaletteFade is NOT at the previously assumed 0x02037594.
  (Similar to how gSprites was shifted by +0x580 from vanilla in R&B.)

  Previously confirmed addresses (find_palette_vars.py):
    gPlttBufferUnfaded = 0x02036CD4  (79 LDR refs)
    gPlttBufferFaded   = 0x020370D4  (101 LDR refs)
    gPaletteFade       = 0x02037594  (430 LDR refs)

  This script takes a FRESH approach:
    1. Scan ALL EWRAM literal pool references and rank by frequency
    2. Find ALL 0x400-spaced EWRAM pairs (buffer pair candidates)
    3. For each pair, check if pair_high + some_offset is also heavily referenced (gPaletteFade)
    4. Look for the intermediate sPaletteStructs[16] (192 bytes between buffers and fade)
    5. Validate via BeginNormalPaletteFade signature (STRB field access pattern)
    6. Cross-reference with DMA3 pattern (gPlttBufferFaded is DMA source to 0x05000000)
    7. Show ALL viable candidates, not just the first match

KEY INSIGHT:
  gPlttBufferUnfaded and gPlttBufferFaded are 1024 bytes each, separated by exactly 0x400.
  sPaletteStructs[16] = 192 bytes (0xC0) sits between gPlttBufferFaded and gPaletteFade.
  So gPaletteFade = gPlttBufferFaded + 0x400 + 0xC0 = gPlttBufferUnfaded + 0x800 + 0xC0.
  Wait -- actually in vanilla pokeemerald-expansion:
    gPlttBufferUnfaded = EWRAM_DATA (1024 bytes)
    gPlttBufferFaded   = EWRAM_DATA (1024 bytes)  -- exactly +0x400 after unfaded
    sPaletteStructs    = EWRAM_DATA (16 * 12 = 192 bytes)  -- after faded
    gPaletteFade       = EWRAM_DATA (struct, ~12 bytes)  -- after sPaletteStructs

  BUT: the compiler may reorder EWRAM_DATA variables! So the layout may differ.
  The safe assumption is only: unfaded and faded are 0x400 apart.
  gPaletteFade could be at faded+0x4C0 (if sPaletteStructs is between them)
  or it could be elsewhere entirely.

  The previous script assumed gPaletteFade = faded + 0x400 -- this may be WRONG.
  This script checks ALL possibilities.

No Ghidra needed -- reads the .gba file directly.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Hardware addresses
PLTT_ADDR = 0x05000000      # GBA palette RAM
DMA3_SAD  = 0x040000D4      # DMA3 source address register
DMA3_DAD  = 0x040000D8      # DMA3 dest address register
DMA3_CNT  = 0x040000DC      # DMA3 control register
REG_BLDCNT = 0x04000050     # Blend control register

# Previously assumed addresses (to verify)
PREV_UNFADED = 0x02036CD4
PREV_FADED   = 0x020370D4
PREV_FADE    = 0x02037594

# Vanilla Emerald reference addresses
VANILLA_UNFADED = 0x0202F388
VANILLA_FADED   = 0x0202F788
VANILLA_FADE    = 0x0202FC48  # gPaletteFade in vanilla


def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def is_ewram(val):
    return 0x02000000 < val < 0x02040000

def is_iwram(val):
    return 0x03000000 <= val < 0x03008000


# =============================================================================
# LDR Rd,[PC,#imm] resolver
# =============================================================================

def resolve_ldr_pc(data, pos):
    """If instruction at pos is LDR Rd,[PC,#imm], return the loaded value."""
    if pos + 1 >= len(data):
        return None
    instr = read_u16(data, pos)
    if (instr & 0xF800) != 0x4800:
        return None
    imm = (instr & 0xFF) << 2
    ldr_addr = ((pos + 4) & ~3) + imm
    if ldr_addr + 3 >= len(data):
        return None
    return read_u32(data, ldr_addr)


# =============================================================================
# Function boundary detection
# =============================================================================

def find_function_start(data, offset, max_back=2048):
    """Walk backward from offset to find PUSH {..., LR} = 0xB5xx."""
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16(data, pos)
        if (instr & 0xFF00) == 0xB500:
            return pos
    return None


def find_function_end(data, func_start, max_size=2048):
    """Find the first POP {PC} or BX LR after func_start. Stops at next PUSH {LR}."""
    pos = func_start + 2
    limit = min(func_start + max_size, len(data) - 2)
    while pos < limit:
        instr = read_u16(data, pos)
        if (instr & 0xFF00) == 0xBD00:  # POP {PC}
            return pos + 2
        if instr == 0x4770:              # BX LR
            return pos + 2
        if (instr & 0xFF00) == 0xB500 and pos > func_start + 4:  # new PUSH {LR}
            return pos
        if (instr & 0xF800) == 0xF000 and pos + 2 < limit:
            nxt = read_u16(data, pos + 2)
            if (nxt & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return None


# =============================================================================
# BL target decoder and caller index
# =============================================================================

def decode_bl_target(data, pos):
    if pos + 4 > len(data):
        return None
    hi = read_u16(data, pos)
    lo = read_u16(data, pos + 2)
    if (hi & 0xF800) != 0xF000 or (lo & 0xF800) != 0xF800:
        return None
    full = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    if full >= 0x400000:
        full -= 0x800000
    return ROM_BASE + pos + 4 + full


def build_bl_target_index(data):
    """Build dict: BL target addr -> caller count. Single ROM pass."""
    print("  Building BL target index...", flush=True)
    index = defaultdict(int)
    pos = 0
    rom_len = len(data)
    while pos < rom_len - 4:
        hi = read_u16(data, pos)
        if (hi & 0xF800) == 0xF000:
            lo = read_u16(data, pos + 2)
            if (lo & 0xF800) == 0xF800:
                full = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
                if full >= 0x400000:
                    full -= 0x800000
                target = ROM_BASE + pos + 4 + full
                index[target] += 1
                index[target | 1] += 1
                pos += 4
                continue
        pos += 2
    print(f"  BL index: {len(index)} unique targets", flush=True)
    return index


# =============================================================================
# THUMB disassembler (compact, for validation output)
# =============================================================================

def disasm_range(data, start, end, max_instrs=80):
    """Returns list of (rom_offset, addr, mnemonic) tuples."""
    lines = []
    pos = start
    while pos < end and pos + 2 <= len(data):
        if max_instrs and len(lines) >= max_instrs:
            break
        instr = read_u16(data, pos)
        addr = ROM_BASE + pos
        m = ""

        if (instr & 0xFE00) == 0xB400:
            lr = (instr >> 8) & 1
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if lr: regs.append("LR")
            m = f"PUSH {{{', '.join(regs)}}}"
        elif (instr & 0xFE00) == 0xBC00:
            pc = (instr >> 8) & 1
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            if pc: regs.append("PC")
            m = f"POP {{{', '.join(regs)}}}"
        elif (instr & 0xF800) == 0x2000:
            m = f"MOV R{(instr>>8)&7}, #0x{instr&0xFF:02X}"
        elif (instr & 0xF800) == 0x2800:
            m = f"CMP R{(instr>>8)&7}, #0x{instr&0xFF:02X}"
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm8 = instr & 0xFF
            lit_off = ((pos + 4) & ~3) + imm8 * 4
            if lit_off + 4 <= len(data):
                val = read_u32(data, lit_off)
                m = f"LDR R{rd}, =0x{val:08X}"
            else:
                m = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7; rn = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 4
            m = f"LDR R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 7; rn = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 4
            m = f"STR R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x7800:
            rd = instr & 7; rn = (instr >> 3) & 7; off = (instr >> 6) & 0x1F
            m = f"LDRB R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x7000:
            rd = instr & 7; rn = (instr >> 3) & 7; off = (instr >> 6) & 0x1F
            m = f"STRB R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x8800:
            rd = instr & 7; rn = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            m = f"LDRH R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x8000:
            rd = instr & 7; rn = (instr >> 3) & 7; off = ((instr >> 6) & 0x1F) * 2
            m = f"STRH R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xFC00) == 0x4000:
            op = (instr >> 6) & 0xF; rd = instr & 7; rm = (instr >> 3) & 7
            names = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                     "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            m = f"{names[op]} R{rd}, R{rm}"
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF
            soff = instr & 0xFF
            if soff >= 0x80: soff -= 0x100
            target = addr + 4 + soff * 2
            cnames = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                       "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]
            m = f"{cnames[cond]} 0x{target:08X}" if cond < 0xF else f"SVC #{instr&0xFF}"
        elif (instr & 0xF800) == 0xE000:
            soff = instr & 0x7FF
            if soff >= 0x400: soff -= 0x800
            m = f"B 0x{addr + 4 + soff * 2:08X}"
        elif (instr & 0xF800) == 0xF000 and pos + 2 < len(data):
            nxt = read_u16(data, pos + 2)
            if (nxt & 0xF800) == 0xF800:
                target = decode_bl_target(data, pos)
                m = f"BL 0x{target:08X}"
                lines.append((pos, addr, m))
                pos += 4
                continue
        elif (instr & 0xF800) == 0x3000:
            m = f"ADD R{(instr>>8)&7}, #0x{instr&0xFF:02X}"
        elif (instr & 0xF800) == 0x3800:
            m = f"SUB R{(instr>>8)&7}, #0x{instr&0xFF:02X}"
        elif instr == 0x4770:
            m = "BX LR"
        elif (instr & 0xFF00) == 0xB000:
            imm = (instr & 0x7F) * 4
            m = f"{'SUB' if instr & 0x80 else 'ADD'} SP, #0x{imm:X}"
        else:
            m = f"??? 0x{instr:04X}"

        lines.append((pos, addr, m))
        pos += 2
    return lines


def print_disasm(data, start, end, max_instrs=60, indent="      "):
    """Print disassembly of a code range."""
    for rom_off, addr, mnem in disasm_range(data, start, end, max_instrs):
        func_off = rom_off - start
        print(f"{indent}+0x{func_off:04X} | 0x{addr:08X}: {mnem}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        print(f"  Expected: {ROM_PATH.resolve()}")
        sys.exit(1)

    rom = ROM_PATH.read_bytes()
    rom_len = len(rom)
    print(f"ROM loaded: {rom_len:,} bytes ({rom_len / 1024 / 1024:.1f} MB)")
    print(f"ROM path:   {ROM_PATH.resolve()}")
    print()

    # =========================================================================
    # PHASE 1: Build LDR reference database for ALL EWRAM addresses
    # =========================================================================
    print("=" * 78)
    print("  PHASE 1: Build LDR reference database")
    print("=" * 78)
    print()

    # Method A: literal pool scan (4-byte aligned values in ROM)
    print("  Scanning literal pool entries (4-byte aligned)...")
    litpool_refs = defaultdict(list)  # addr -> [rom_offsets of the literal pool entry]
    for i in range(0, rom_len - 3, 4):
        val = read_u32(rom, i)
        if is_ewram(val):
            litpool_refs[val].append(i)

    print(f"  Literal pool: {len(litpool_refs)} unique EWRAM addresses")

    # Method B: actual LDR Rd,[PC,#imm] instructions (more precise)
    print("  Scanning LDR Rd,[PC,#imm] instructions...")
    ldr_refs = defaultdict(list)  # addr -> [rom_offsets of the LDR instruction]
    for pos in range(0, rom_len - 1, 2):
        val = resolve_ldr_pc(rom, pos)
        if val is not None and is_ewram(val):
            ldr_refs[val].append(pos)

    print(f"  LDR instructions: {len(ldr_refs)} unique EWRAM addresses loaded")
    print()

    # =========================================================================
    # PHASE 2: Verify previously assumed addresses
    # =========================================================================
    print("=" * 78)
    print("  PHASE 2: Verify previously assumed addresses")
    print("=" * 78)
    print()

    for name, addr in [("gPlttBufferUnfaded (prev)", PREV_UNFADED),
                        ("gPlttBufferFaded (prev)",   PREV_FADED),
                        ("gPaletteFade (prev)",       PREV_FADE)]:
        lit_count = len(litpool_refs.get(addr, []))
        ldr_count = len(ldr_refs.get(addr, []))
        print(f"  {name:35s} 0x{addr:08X}: {lit_count:4d} literal pool / {ldr_count:4d} LDR refs")

    print()
    print("  Vanilla Emerald reference:")
    for name, addr in [("gPlttBufferUnfaded (vanilla)", VANILLA_UNFADED),
                        ("gPlttBufferFaded (vanilla)",   VANILLA_FADED),
                        ("gPaletteFade (vanilla)",       VANILLA_FADE)]:
        lit_count = len(litpool_refs.get(addr, []))
        ldr_count = len(ldr_refs.get(addr, []))
        print(f"  {name:35s} 0x{addr:08X}: {lit_count:4d} literal pool / {ldr_count:4d} LDR refs")
    print()

    # =========================================================================
    # PHASE 3: Find ALL 0x400-spaced EWRAM pairs (buffer pair candidates)
    # =========================================================================
    print("=" * 78)
    print("  PHASE 3: Find ALL 0x400-spaced EWRAM address pairs")
    print("=" * 78)
    print()

    # Build function -> EWRAM address mapping using LDR refs
    func_ewram = defaultdict(set)  # func_start -> set of EWRAM addresses
    for addr, positions in ldr_refs.items():
        for pos in positions:
            fs = find_function_start(rom, pos)
            if fs is not None:
                func_ewram[fs].add(addr)

    # Find functions that reference TWO EWRAM addresses separated by exactly 0x400
    pair_funcs = defaultdict(list)  # (addr_lo, addr_hi) -> [func_starts]
    for fs, addrs in func_ewram.items():
        sorted_addrs = sorted(addrs)
        for a in sorted_addrs:
            b = a + 0x400
            if b in addrs:
                pair_funcs[(a, b)].append(fs)

    # Count how many functions reference each pair
    print(f"  Found {len(pair_funcs)} unique 0x400-spaced EWRAM pairs")
    print()

    # Rank pairs by number of co-referencing functions
    sorted_pairs = sorted(pair_funcs.items(), key=lambda x: -len(x[1]))

    print("  Top 20 pairs (by # functions referencing both):")
    print(f"  {'Rank':>4}  {'Low':>12}  {'High':>12}  {'#Funcs':>6}  {'LDR_lo':>6}  {'LDR_hi':>6}  Notes")
    print(f"  {'----':>4}  {'---':>12}  {'----':>12}  {'------':>6}  {'------':>6}  {'------':>6}  -----")

    for i, ((lo, hi), funcs) in enumerate(sorted_pairs[:20]):
        ldr_lo = len(ldr_refs.get(lo, []))
        ldr_hi = len(ldr_refs.get(hi, []))
        notes = []
        if lo == PREV_UNFADED and hi == PREV_FADED:
            notes.append("PREV_MATCH")
        # Check what comes after hi (potential gPaletteFade zone)
        for delta in [0x4C0, 0x400, 0x500, 0x480, 0x440]:
            candidate = hi + delta
            c_ldr = len(ldr_refs.get(candidate, []))
            if c_ldr >= 50:
                notes.append(f"+0x{delta:X}=0x{candidate:08X}({c_ldr}LDR)")
        note_str = ", ".join(notes)
        print(f"  {i+1:4d}  0x{lo:08X}  0x{hi:08X}  {len(funcs):6d}  {ldr_lo:6d}  {ldr_hi:6d}  {note_str}")
    print()

    # =========================================================================
    # PHASE 4: For each buffer pair, search for gPaletteFade candidates nearby
    # =========================================================================
    print("=" * 78)
    print("  PHASE 4: Search for gPaletteFade candidates near each buffer pair")
    print("=" * 78)
    print()

    # gPaletteFade is a small struct (~8-12 bytes) that:
    #   - Has MANY LDR references (100+, likely 300+)
    #   - Is accessed with STRB/LDRB at offsets 0, 4, 5, 6, 7 (field access)
    #   - Is in EWRAM, near the buffer pair but NOT overlapping

    all_candidates = []  # list of (pair, fade_addr, score, details)

    # Consider top 10 buffer pairs
    for (lo, hi), funcs in sorted_pairs[:10]:
        ldr_lo = len(ldr_refs.get(lo, []))
        ldr_hi = len(ldr_refs.get(hi, []))

        # Skip pairs with very few references (noise)
        if len(funcs) < 5 or ldr_lo < 20 or ldr_hi < 20:
            continue

        print(f"  Buffer pair: 0x{lo:08X} / 0x{hi:08X} ({len(funcs)} shared funcs, {ldr_lo}/{ldr_hi} LDR)")

        # Search EWRAM addresses in range [hi+0x100, hi+0x800] for gPaletteFade
        # Also search before lo: [lo-0x800, lo-0x100] in case layout is reversed
        search_ranges = [
            (hi, hi + 0x800, "after faded"),
            (lo - 0x800, lo, "before unfaded"),
        ]

        pair_candidates = []

        for range_lo, range_hi, label in search_ranges:
            for candidate_addr in range(max(0x02000000, range_lo), min(0x02040000, range_hi)):
                if candidate_addr not in ldr_refs:
                    continue
                c_ldr = len(ldr_refs[candidate_addr])
                if c_ldr < 30:
                    continue
                # Skip the buffer addresses themselves
                if candidate_addr == lo or candidate_addr == hi:
                    continue

                # Score this candidate
                score = 0
                details = []

                # --- LDR reference count ---
                if c_ldr >= 300:
                    score += 50
                    details.append(f"very many LDR refs ({c_ldr})")
                elif c_ldr >= 100:
                    score += 30
                    details.append(f"many LDR refs ({c_ldr})")
                elif c_ldr >= 50:
                    score += 15
                    details.append(f"moderate LDR refs ({c_ldr})")
                else:
                    score += 5
                    details.append(f"few LDR refs ({c_ldr})")

                # --- Co-location with buffer pair in functions ---
                # How many functions reference this candidate AND the buffer pair?
                cand_funcs = set()
                for p in ldr_refs[candidate_addr]:
                    fs = find_function_start(rom, p)
                    if fs is not None:
                        cand_funcs.add(fs)

                shared_with_pair = len(cand_funcs & set(funcs))
                if shared_with_pair >= 5:
                    score += 25
                    details.append(f"co-located with pair in {shared_with_pair} funcs")
                elif shared_with_pair >= 2:
                    score += 10
                    details.append(f"co-located with pair in {shared_with_pair} funcs")

                # --- Struct field access pattern ---
                # Check if functions that reference this addr use STRB/LDRB at offsets
                # matching gPaletteFade: 0, 4, 5, 6, 7
                strb_offsets = set()
                ldrb_offsets = set()
                str_offsets = set()
                checked_funcs = 0
                for p in ldr_refs[candidate_addr][:50]:
                    fs = find_function_start(rom, p)
                    if fs is None:
                        continue
                    fe = find_function_end(rom, fs)
                    if fe is None:
                        fe = fs + 200
                    checked_funcs += 1
                    scan_pos = fs
                    while scan_pos < fe and scan_pos + 2 <= rom_len:
                        instr = read_u16(rom, scan_pos)
                        if (instr & 0xF800) == 0x7000:   # STRB
                            off = (instr >> 6) & 0x1F
                            strb_offsets.add(off)
                        elif (instr & 0xF800) == 0x7800:  # LDRB
                            off = (instr >> 6) & 0x1F
                            ldrb_offsets.add(off)
                        elif (instr & 0xF800) == 0x6000:  # STR
                            off = ((instr >> 6) & 0x1F) << 2
                            str_offsets.add(off)
                        if (instr & 0xF800) == 0xF000 and scan_pos + 2 < fe:
                            nxt = read_u16(rom, scan_pos + 2)
                            if (nxt & 0xF800) == 0xF800:
                                scan_pos += 4
                                continue
                        scan_pos += 2

                # gPaletteFade signature: fields at offsets 0 (STR), 4, 5, 6, 7 (STRB/LDRB)
                target_byte_offsets = {4, 5, 6, 7}
                byte_match = len((strb_offsets | ldrb_offsets) & target_byte_offsets)
                has_str0 = 0 in str_offsets

                if byte_match >= 3 and has_str0:
                    score += 30
                    details.append(f"STRONG field pattern: STR@0, STRB/LDRB@{sorted((strb_offsets|ldrb_offsets) & target_byte_offsets)}")
                elif byte_match >= 3:
                    score += 20
                    details.append(f"field pattern: byte@{sorted((strb_offsets|ldrb_offsets) & target_byte_offsets)}")
                elif byte_match >= 2:
                    score += 10
                    details.append(f"partial field match: byte@{sorted((strb_offsets|ldrb_offsets) & target_byte_offsets)}")

                # --- Distance from faded buffer ---
                dist = candidate_addr - hi
                if 0x400 <= dist <= 0x600:
                    score += 10
                    details.append(f"expected distance from faded (+0x{dist:X})")
                elif 0x100 <= dist <= 0x400 or 0x600 < dist <= 0x800:
                    score += 5
                    details.append(f"plausible distance from faded (+0x{dist:X})")

                # --- Is it the previously assumed address? ---
                if candidate_addr == PREV_FADE:
                    details.append("== PREVIOUSLY ASSUMED")

                pair_candidates.append((candidate_addr, score, c_ldr, details))

        # Sort by score descending
        pair_candidates.sort(key=lambda x: -x[1])

        if pair_candidates:
            print(f"    gPaletteFade candidates:")
            for j, (caddr, cscore, cldr, cdets) in enumerate(pair_candidates[:8]):
                dist = caddr - hi
                prev_mark = " ***" if caddr == PREV_FADE else ""
                print(f"      #{j+1} 0x{caddr:08X} (score={cscore}, {cldr} LDR, dist_from_faded=+0x{dist:X}){prev_mark}")
                for d in cdets:
                    print(f"           - {d}")
            print()

            all_candidates.extend([(lo, hi, caddr, cscore, cldr, cdets)
                                   for caddr, cscore, cldr, cdets in pair_candidates[:5]])
        else:
            print(f"    No gPaletteFade candidates found near this pair")
            print()

    # =========================================================================
    # PHASE 5: DMA3 validation -- gPlttBufferFaded is the DMA source to PLTT
    # =========================================================================
    print("=" * 78)
    print("  PHASE 5: DMA3 validation (gPlttBufferFaded -> 0x05000000)")
    print("=" * 78)
    print()

    # Find functions that reference both DMA3_SAD (0x040000D4) and PLTT (0x05000000)
    # These functions copy gPlttBufferFaded to palette RAM
    dma3_ldr = ldr_refs.get(DMA3_SAD, []) if DMA3_SAD in ldr_refs else []
    # DMA3 address might be loaded via base+offset, so also check literal pool
    dma3_lit = litpool_refs.get(DMA3_SAD, [])
    pltt_ldr = ldr_refs.get(PLTT_ADDR, []) if PLTT_ADDR in ldr_refs else []
    pltt_lit = litpool_refs.get(PLTT_ADDR, [])

    print(f"  DMA3_SAD (0x{DMA3_SAD:08X}): {len(dma3_ldr)} LDR, {len(dma3_lit)} literal pool")
    print(f"  PLTT     (0x{PLTT_ADDR:08X}): {len(pltt_ldr)} LDR, {len(pltt_lit)} literal pool")
    print()

    # Find functions with PLTT reference and look for which EWRAM address is the DMA source
    pltt_funcs = set()
    for pos in pltt_ldr:
        fs = find_function_start(rom, pos)
        if fs is not None:
            pltt_funcs.add(fs)

    print(f"  Functions referencing PLTT: {len(pltt_funcs)}")
    dma_source_candidates = defaultdict(int)
    for fs in pltt_funcs:
        ewram_in_func = func_ewram.get(fs, set())
        for ea in ewram_in_func:
            if 0x02030000 <= ea < 0x02040000:  # reasonable range for buffers
                dma_source_candidates[ea] += 1

    sorted_dma = sorted(dma_source_candidates.items(), key=lambda x: -x[1])
    print(f"  EWRAM addresses in PLTT-referencing functions (likely gPlttBufferFaded):")
    for addr, count in sorted_dma[:10]:
        ldr_c = len(ldr_refs.get(addr, []))
        prev = ""
        if addr == PREV_FADED:
            prev = " << PREV gPlttBufferFaded"
        elif addr == PREV_UNFADED:
            prev = " << PREV gPlttBufferUnfaded"
        elif addr == PREV_FADE:
            prev = " << PREV gPaletteFade"
        print(f"    0x{addr:08X}: in {count} PLTT funcs, {ldr_c} total LDR{prev}")
    print()

    # =========================================================================
    # PHASE 6: REG_BLDCNT validation -- gPaletteFade accesses blend registers
    # =========================================================================
    print("=" * 78)
    print("  PHASE 6: REG_BLDCNT validation (gPaletteFade uses blend registers)")
    print("=" * 78)
    print()

    bldcnt_ldr = ldr_refs.get(REG_BLDCNT, []) if REG_BLDCNT in ldr_refs else []
    bldcnt_lit = litpool_refs.get(REG_BLDCNT, [])
    print(f"  REG_BLDCNT (0x{REG_BLDCNT:08X}): {len(bldcnt_ldr)} LDR, {len(bldcnt_lit)} literal pool")

    bldcnt_funcs = set()
    for pos in bldcnt_ldr:
        fs = find_function_start(rom, pos)
        if fs is not None:
            bldcnt_funcs.add(fs)

    blend_ewram_candidates = defaultdict(int)
    for fs in bldcnt_funcs:
        ewram_in_func = func_ewram.get(fs, set())
        for ea in ewram_in_func:
            if 0x02030000 <= ea < 0x02040000:
                blend_ewram_candidates[ea] += 1

    sorted_blend = sorted(blend_ewram_candidates.items(), key=lambda x: -x[1])
    print(f"  EWRAM in REG_BLDCNT functions (likely gPaletteFade or buffers):")
    for addr, count in sorted_blend[:15]:
        ldr_c = len(ldr_refs.get(addr, []))
        prev = ""
        if addr == PREV_FADE:
            prev = " << PREV gPaletteFade"
        elif addr == PREV_FADED:
            prev = " << PREV gPlttBufferFaded"
        elif addr == PREV_UNFADED:
            prev = " << PREV gPlttBufferUnfaded"
        print(f"    0x{addr:08X}: in {count} BLDCNT funcs, {ldr_c} total LDR{prev}")
    print()

    # =========================================================================
    # PHASE 7: BeginNormalPaletteFade identification from top candidates
    # =========================================================================
    print("=" * 78)
    print("  PHASE 7: Identify BeginNormalPaletteFade for top gPaletteFade candidates")
    print("=" * 78)
    print()

    bl_index = build_bl_target_index(rom)
    print()

    # Deduplicate all_candidates by fade address
    seen_fade = set()
    unique_candidates = []
    for entry in sorted(all_candidates, key=lambda x: -x[3]):  # sort by score
        fade_addr = entry[2]
        if fade_addr not in seen_fade:
            seen_fade.add(fade_addr)
            unique_candidates.append(entry)

    # For each top fade candidate, find BeginNormalPaletteFade
    for rank, (buf_lo, buf_hi, fade_addr, fade_score, fade_ldr, fade_details) in enumerate(unique_candidates[:5]):
        print(f"  --- Candidate #{rank+1}: gPaletteFade = 0x{fade_addr:08X} ---")
        print(f"      Buffer pair: 0x{buf_lo:08X} / 0x{buf_hi:08X}")
        print(f"      Score: {fade_score}, LDR refs: {fade_ldr}")
        print()

        # Find functions referencing BOTH fade_addr AND buf_hi (gPlttBufferFaded)
        fade_funcs = set()
        for p in ldr_refs.get(fade_addr, []):
            fs = find_function_start(rom, p)
            if fs is not None:
                fade_funcs.add(fs)

        faded_funcs = set()
        for p in ldr_refs.get(buf_hi, []):
            fs = find_function_start(rom, p)
            if fs is not None:
                faded_funcs.add(fs)

        both = fade_funcs & faded_funcs
        print(f"      Functions with gPaletteFade: {len(fade_funcs)}")
        print(f"      Functions with gPlttBufferFaded: {len(faded_funcs)}")
        print(f"      Functions with BOTH: {len(both)}")

        # Among 'both', find BeginNormalPaletteFade signature:
        # - High caller count (200+)
        # - Size 80-300 bytes
        # - Writes STR [Rn,#0] and STRB [Rn,#4..7]
        begin_candidates = []
        for fs in both:
            fe = find_function_end(rom, fs)
            if fe is None:
                fe = fs + 300
            size = fe - fs
            func_addr = ROM_BASE + fs + 1
            callers = max(bl_index.get(func_addr, 0), bl_index.get(func_addr & ~1, 0))

            begin_candidates.append({
                'start': fs, 'end': fe, 'size': size,
                'addr': func_addr, 'callers': callers
            })

        begin_candidates.sort(key=lambda x: -x['callers'])

        print(f"      BeginNormalPaletteFade candidates (from BOTH set):")
        for j, bc in enumerate(begin_candidates[:5]):
            marker = ""
            if bc['callers'] >= 200 and 80 <= bc['size'] <= 300:
                marker = " <<<< STRONG MATCH"
            elif bc['callers'] >= 100:
                marker = " << likely"
            print(f"        #{j+1} 0x{bc['addr']:08X} ({bc['size']} bytes, {bc['callers']} callers){marker}")

        # Show disassembly of top BeginNormalPaletteFade candidate
        if begin_candidates:
            best_begin = begin_candidates[0]
            print()
            print(f"      Best BeginNormalPaletteFade candidate: 0x{best_begin['addr']:08X}")
            print(f"      Size: {best_begin['size']} bytes, Callers: {best_begin['callers']}")
            print()
            print_disasm(rom, best_begin['start'], best_begin['end'], max_instrs=50)
        print()
        print("    " + "-" * 60)
        print()

    # =========================================================================
    # PHASE 8: Brute-force -- scan ENTIRE 0x02035000-0x02039000 range
    # =========================================================================
    print("=" * 78)
    print("  PHASE 8: Exhaustive EWRAM scan in palette region (0x02035000-0x02039000)")
    print("=" * 78)
    print()

    # Show ALL EWRAM addresses in this range that have significant LDR refs
    region_addrs = []
    for addr in sorted(ldr_refs.keys()):
        if 0x02035000 <= addr < 0x02039000:
            c = len(ldr_refs[addr])
            if c >= 5:
                region_addrs.append((addr, c))

    region_addrs.sort(key=lambda x: x[0])

    print(f"  EWRAM addresses in 0x02035000-0x02039000 with >= 5 LDR refs:")
    print(f"  {'Address':>12}  {'LDR':>5}  {'Litpool':>7}  Annotation")
    print(f"  {'-'*12}  {'-'*5}  {'-'*7}  ----------")

    prev_addr = 0
    for addr, ldr_c in region_addrs:
        lit_c = len(litpool_refs.get(addr, []))
        ann = ""
        if addr == PREV_UNFADED:
            ann = "PREV gPlttBufferUnfaded (1024 bytes)"
        elif addr == PREV_FADED:
            ann = "PREV gPlttBufferFaded (1024 bytes)"
        elif addr == PREV_FADE:
            ann = "PREV gPaletteFade (8-12 bytes)"
        elif addr == PREV_UNFADED + 0x400:
            ann = f"= unfaded + 0x400 (expected gPlttBufferFaded)"
        elif addr == PREV_FADED + 0x400:
            ann = f"= faded + 0x400"
        elif PREV_FADED < addr < PREV_FADE:
            ann = f"between faded and fade (+0x{addr - PREV_FADED:X} from faded)"

        # Show gap from previous
        gap = ""
        if prev_addr > 0 and addr - prev_addr > 0x100:
            gap = f"  [gap: 0x{addr - prev_addr:X}]"

        print(f"  0x{addr:08X}  {ldr_c:5d}  {lit_c:7d}  {ann}{gap}")
        prev_addr = addr

    print()

    # =========================================================================
    # PHASE 9: Alternative approach -- find by 0x80 bit test pattern
    # =========================================================================
    print("=" * 78)
    print("  PHASE 9: Find gPaletteFade.active via 0x80 bit test pattern")
    print("=" * 78)
    print()

    # gPaletteFade.active is bit 7 of the flags byte.
    # Code pattern: LDR Rx, =gPaletteFade; LDRB Ry, [Rx, #7]; TST Ry, #0x80 (or MOV+TST)
    # Or: LDRB Ry, [Rx, #7]; CMP Ry, #0 / BNE
    #
    # We look for: LDRB Rd, [Rn, #7] immediately or soon after LDR Rn, =EWRAM_addr
    # where the EWRAM_addr has many LDR refs.

    print("  Searching for EWRAM addresses with 'LDRB Rd,[Rn,#7]' access pattern...")
    print("  (Only addresses with >= 50 LDR refs)")
    print()

    active_bit_candidates = []

    for addr, positions in ldr_refs.items():
        if not is_ewram(addr):
            continue
        if len(positions) < 50:
            continue
        if 0x02035000 > addr or addr >= 0x02039000:
            continue  # Focus on the palette region

        # Count how many LDR sites have LDRB [Rn, #7] within 20 bytes after
        ldrb7_count = 0
        ldrb7_with_tst = 0
        for ldr_pos in positions[:80]:  # Check up to 80 sites
            for delta in range(2, 24, 2):
                check = ldr_pos + delta
                if check + 2 > rom_len:
                    break
                instr = read_u16(rom, check)
                # LDRB Rd, [Rn, #7]: 0x79C0 + Rd (Rn can be any low reg)
                if (instr & 0xF800) == 0x7800:
                    off = (instr >> 6) & 0x1F
                    if off == 7:
                        ldrb7_count += 1
                        # Check for TST/CMP in next few instructions
                        for d2 in range(2, 10, 2):
                            if check + d2 + 2 > rom_len:
                                break
                            i2 = read_u16(rom, check + d2)
                            # TST Rn, Rm
                            if (i2 & 0xFFC0) == 0x4200:
                                ldrb7_with_tst += 1
                                break
                            # CMP Rn, #imm
                            if (i2 & 0xF800) == 0x2800:
                                ldrb7_with_tst += 1
                                break
                        break  # Only count first LDRB #7 per LDR site

        if ldrb7_count >= 5:
            active_bit_candidates.append((addr, len(positions), ldrb7_count, ldrb7_with_tst))

    active_bit_candidates.sort(key=lambda x: (-x[2], -x[1]))

    print(f"  Candidates with LDRB [Rn,#7] pattern (>= 5 occurrences):")
    for addr, total_ldr, ldrb7, ldrb7_tst in active_bit_candidates[:10]:
        prev = ""
        if addr == PREV_FADE:
            prev = " << PREV gPaletteFade"
        print(f"    0x{addr:08X}: {total_ldr:4d} LDR total, {ldrb7:3d} LDRB #7, {ldrb7_tst:3d} with TST/CMP{prev}")
    print()

    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    print("=" * 78)
    print("  FINAL SUMMARY")
    print("=" * 78)
    print()

    # Determine best buffer pair
    if sorted_pairs:
        best_pair = sorted_pairs[0]
        (best_lo, best_hi) = best_pair[0]
        pair_funcs_count = len(best_pair[1])
        print(f"  BEST BUFFER PAIR:")
        print(f"    gPlttBufferUnfaded = 0x{best_lo:08X}  ({len(ldr_refs.get(best_lo,[]))} LDR)")
        print(f"    gPlttBufferFaded   = 0x{best_hi:08X}  ({len(ldr_refs.get(best_hi,[]))} LDR)")
        print(f"    Shared functions:  {pair_funcs_count}")
        match = ""
        if best_lo == PREV_UNFADED and best_hi == PREV_FADED:
            match = "CONFIRMED -- matches previous assumption"
        else:
            match = f"DIFFERS from previous (was 0x{PREV_UNFADED:08X} / 0x{PREV_FADED:08X})"
        print(f"    Status: {match}")
    print()

    # Determine best gPaletteFade
    if unique_candidates:
        best = unique_candidates[0]
        fade_addr = best[2]
        print(f"  BEST gPaletteFade CANDIDATE:")
        print(f"    gPaletteFade = 0x{fade_addr:08X}  ({best[4]} LDR, score={best[3]})")
        print(f"    Offset from gPlttBufferFaded: +0x{fade_addr - best[1]:X}")
        if fade_addr == PREV_FADE:
            print(f"    Status: CONFIRMED -- matches previous assumption")
        else:
            print(f"    Status: DIFFERS from previous (was 0x{PREV_FADE:08X})")
        print()
        print(f"  gPaletteFade struct layout:")
        print(f"    +0x00 (0x{fade_addr:08X}): selectedPalettes (u32)")
        print(f"    +0x04 (0x{fade_addr+4:08X}): delayCounter:6, y:5, targetY:5 (packed)")
        print(f"    +0x05 (0x{fade_addr+5:08X}): continuation of packed bitfields")
        print(f"    +0x06 (0x{fade_addr+6:08X}): blendColor (u16, 15 bits)")
        print(f"    +0x07 (0x{fade_addr+7:08X}): flags byte -- bit 7 = active (0x80)")
    else:
        print("  No gPaletteFade candidate found!")
    print()

    # Active bit address
    if active_bit_candidates:
        top_active = active_bit_candidates[0]
        active_addr = top_active[0] + 7
        print(f"  gPaletteFade ACTIVE FLAG:")
        print(f"    Address: 0x{active_addr:08X} (byte, bit 7 = 0x80)")
        print(f"    To check if fade active:  (read_u8(0x{active_addr:08X}) & 0x80) != 0")
        print(f"    To force-complete fade:   write_u8(0x{active_addr:08X}, read_u8(...) & 0x7F)")
        print(f"    To reset entire struct:   memset(0x{top_active[0]:08X}, 0, 8)")
    print()

    print("=" * 78)
    print("  SCAN COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
