#!/usr/bin/env python3
"""
ROM Scanner — Find gPaletteFade in Pokemon Run & Bun

CONFIRMED RESULTS (2026-02-07):
  gPlttBufferUnfaded     = 0x02036CD4  (79 LDR refs, 1024 bytes)
  gPlttBufferFaded       = 0x020370D4  (101 LDR refs, 1024 bytes, DMA source to PLTT)
  sPaletteStructs[16]    = 0x020374D4  (12 bytes each, 16 entries = 192 bytes)
  gPaletteFade           = 0x02037594  (430 LDR refs, 8 bytes packed bitfield struct)
  BeginNormalPaletteFade = 0x080BF911  (THUMB, 331 callers)

  gPaletteFade struct layout:
    +0x00 (0x02037594): selectedPalettes (u32) — bitmask of which palettes to fade
    +0x04 (0x02037598): delayCounter:6, y:5, targetY:5 (packed bitfield)
    +0x05 (0x02037599): continuation of packed bitfields
    +0x06 (0x0203759A): blendColor (u16, 15 bits)
    +0x07 (0x0203759B): flags byte — bit 7 = active (0x80), bit 6 = yDec (0x40)

  Battle black screen fix:
    active flag = byte at 0x0203759B, bit 7 (0x80)
    To stop fade: clear bit 7 at 0x0203759B
    To reset: zero 8 bytes at 0x02037594

Strategy used:
  A) Find all 0x400-spaced EWRAM pairs referenced together in functions
  B) Identify BeginNormalPaletteFade by finding the function that uses the
     top pair AND writes to a struct with field offsets +0, +4, +5, +6, +7
  C) The struct base in BeginNormalPaletteFade = gPaletteFade
  D) Confirmed: buffer pair 0x02036CD4/0x020370D4 in 46 functions,
     gPaletteFade = 0x02037594 (430 LDR refs, 375 accesses to +0x07 flags byte)
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

PLTT_ADDR = 0x05000000
DMA3_SAD  = 0x040000D4
REG_BLDCNT = 0x04000050

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

def find_function_start(rom_data, offset, max_back=2048):
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) == 0xB500:
            return pos
    return None

def is_ewram(val):
    return 0x02000000 < val < 0x02040000

def resolve_ldr_pc(rom_data, pos):
    if pos + 1 >= len(rom_data):
        return None
    instr = read_u16_le(rom_data, pos)
    if (instr & 0xF800) != 0x4800:
        return None
    imm = (instr & 0xFF) << 2
    ldr_addr = ((pos + 4) & ~3) + imm
    if ldr_addr + 3 >= len(rom_data):
        return None
    return read_u32_le(rom_data, ldr_addr)

def scan_function_literals(rom_data, func_start, max_size=2048):
    """Scan function, return all LDR Rd,[PC,#imm] literal values."""
    literals = []
    end = min(func_start + max_size, len(rom_data) - 1)
    pos = func_start
    while pos < end:
        instr = read_u16_le(rom_data, pos)
        if pos > func_start + 2:
            if (instr & 0xFF00) == 0xBD00 or instr == 0x4770:
                break
        val = resolve_ldr_pc(rom_data, pos)
        if val is not None:
            literals.append((pos, val))
        if (instr & 0xF800) == 0xF000 and pos + 2 < end:
            next_instr = read_u16_le(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue
        pos += 2
    return literals

def disasm_function(rom_data, func_start, max_size=600):
    lines = []
    end = min(func_start + max_size, len(rom_data) - 1)
    pos = func_start
    while pos < end:
        instr = read_u16_le(rom_data, pos)
        addr = ROM_BASE + pos
        desc = ""

        if (instr & 0xFF00) == 0xB500:
            regs = [f"R{b}" for b in range(8) if instr & (1 << b)]
            regs.append("LR")
            desc = f"PUSH {{{', '.join(regs)}}}"
        elif (instr & 0xFF00) == 0xBD00:
            regs = [f"R{b}" for b in range(8) if instr & (1 << b)]
            regs.append("PC")
            desc = f"POP {{{', '.join(regs)}}}"
            lines.append(f"  0x{addr:08X}: {instr:04X}  {desc}")
            break
        elif instr == 0x4770:
            desc = "BX LR"
            lines.append(f"  0x{addr:08X}: {instr:04X}  {desc}")
            break
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) << 2
            ldr_addr = ((pos + 4) & ~3) + imm
            if ldr_addr + 3 < len(rom_data):
                lit_val = read_u32_le(rom_data, ldr_addr)
                desc = f"LDR R{rd}, =0x{lit_val:08X}"
            else:
                desc = f"LDR R{rd}, [PC, #0x{imm:X}]"
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc = f"MOV R{rd}, #0x{imm:X}"
        elif (instr & 0xFE00) == 0x7000:
            # STRB Rd, [Rn, #imm]
            rd = instr & 7
            rn = (instr >> 3) & 7
            off = (instr >> 6) & 0x1F
            desc = f"STRB R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xFE00) == 0x7800:
            # LDRB Rd, [Rn, #imm]
            rd = instr & 7
            rn = (instr >> 3) & 7
            off = (instr >> 6) & 0x1F
            desc = f"LDRB R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x8000:
            # STRH Rd, [Rn, #imm]
            rd = instr & 7
            rn = (instr >> 3) & 7
            off = ((instr >> 6) & 0x1F) << 1
            desc = f"STRH R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x8800:
            # LDRH Rd, [Rn, #imm]
            rd = instr & 7
            rn = (instr >> 3) & 7
            off = ((instr >> 6) & 0x1F) << 1
            desc = f"LDRH R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 7
            rn = (instr >> 3) & 7
            off = ((instr >> 6) & 0x1F) << 2
            desc = f"STR R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7
            rn = (instr >> 3) & 7
            off = ((instr >> 6) & 0x1F) << 2
            desc = f"LDR R{rd}, [R{rn}, #0x{off:X}]"
        elif (instr & 0xFFC0) == 0x4300:
            rd = instr & 7
            rs = (instr >> 3) & 7
            desc = f"ORR R{rd}, R{rs}"
        elif (instr & 0xFFC0) == 0x4380:
            rd = instr & 7
            rs = (instr >> 3) & 7
            desc = f"BIC R{rd}, R{rs}"
        elif (instr & 0xF800) == 0xF000:
            if pos + 2 < end:
                next_instr = read_u16_le(rom_data, pos + 2)
                if (next_instr & 0xF800) == 0xF800:
                    off11hi = instr & 0x07FF
                    off11lo = next_instr & 0x07FF
                    full_off = (off11hi << 12) | (off11lo << 1)
                    if full_off >= 0x400000:
                        full_off -= 0x800000
                    bl_target = ROM_BASE + pos + 4 + full_off
                    desc = f"BL 0x{bl_target:08X}"
                    lines.append(f"  0x{addr:08X}: {instr:04X} {next_instr:04X}  {desc}")
                    pos += 4
                    continue

        lines.append(f"  0x{addr:08X}: {instr:04X}  {desc}")
        pos += 2
    return "\n".join(lines)


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes ({len(rom_data)/1024/1024:.1f} MB)")
    print()

    # =========================================================================
    # Build LDR reference database
    # =========================================================================
    print("Building LDR reference database...")
    ewram_ldr = defaultdict(list)  # addr -> [rom positions of LDR instructions]
    for pos in range(0, len(rom_data) - 1, 2):
        val = resolve_ldr_pc(rom_data, pos)
        if val is not None and is_ewram(val):
            ewram_ldr[val].append(pos)
    print(f"  {len(ewram_ldr)} unique EWRAM addresses in LDR instructions")
    print()

    # =========================================================================
    # PHASE 1: Examine the 5 PLTT LDR instructions
    # =========================================================================
    print("=" * 70)
    print("  PHASE 1: Examine PLTT (0x05000000) LDR instructions in detail")
    print("=" * 70)
    print()

    pltt_positions = []
    for pos in range(0, len(rom_data) - 1, 2):
        val = resolve_ldr_pc(rom_data, pos)
        if val == PLTT_ADDR:
            pltt_positions.append(pos)

    print(f"  {len(pltt_positions)} LDR instructions load 0x05000000")
    for pltt_pos in pltt_positions:
        fs = find_function_start(rom_data, pltt_pos)
        if fs:
            func_addr = ROM_BASE + fs + 1
            lits = scan_function_literals(rom_data, fs)
            all_vals = [v for _, v in lits]
            ewram_vals = [v for v in all_vals if is_ewram(v)]
            io_vals = [v for v in all_vals if 0x04000000 <= v < 0x04001000]
            print(f"  Function 0x{func_addr:08X} (LDR @0x{ROM_BASE+pltt_pos:08X}):")
            print(f"    All literals: {[f'0x{v:08X}' for v in all_vals]}")
            print(f"    EWRAM: {[f'0x{v:08X}' for v in ewram_vals]}")
            print(f"    IO regs: {[f'0x{v:08X}' for v in io_vals]}")
            print(disasm_function(rom_data, fs, max_size=200))
            print()
        else:
            print(f"  LDR @0x{ROM_BASE+pltt_pos:08X}: no function found")
    print()

    # =========================================================================
    # PHASE 2: Find CpuSet / CpuFastSet calls (used by BeginNormalPaletteFade)
    # =========================================================================
    print("=" * 70)
    print("  PHASE 2: Search for palette buffer copy pattern")
    print("=" * 70)
    print()

    # CpuSet/CpuFastSet are BIOS calls in GBA. They're called via SWI instruction.
    # In compiled code: SWI 0x0B (CpuSet) or SWI 0x0C (CpuFastSet)
    # But pokeemerald wraps them: CpuSet(src, dst, mode) which does SWI internally.
    # The wrapper is likely a small function.
    #
    # Actually, BeginNormalPaletteFade does:
    #   CpuFastSet(gPlttBufferFaded, gPlttBufferUnfaded, 0x100)
    # where 0x100 = 256 words = 1024 bytes
    #
    # So the function loads BOTH buffer addresses as arguments to CpuFastSet.
    #
    # Strategy: Find functions that reference TWO EWRAM addresses spaced 0x400 apart.

    print("  Scanning for functions referencing TWO 0x400-spaced EWRAM addresses...")
    print()

    func_pairs = defaultdict(list)  # func_start -> [(addr_a, addr_b), ...]

    # Build function -> EWRAM address mapping
    func_ewram = defaultdict(set)
    for addr, positions in ewram_ldr.items():
        for pos in positions:
            fs = find_function_start(rom_data, pos)
            if fs:
                func_ewram[fs].add(addr)

    # Find functions with 0x400-spaced pairs
    for fs, addrs in func_ewram.items():
        sorted_addrs = sorted(addrs)
        for a in sorted_addrs:
            if (a + 0x400) in addrs:
                func_pairs[fs].append((a, a + 0x400))

    print(f"  Functions with 0x400-spaced EWRAM pairs: {len(func_pairs)}")
    print()

    # Count which pairs appear most across functions
    pair_count = defaultdict(int)
    for fs, pairs_list in func_pairs.items():
        for pair in pairs_list:
            pair_count[pair] += 1

    sorted_pairs = sorted(pair_count.items(), key=lambda x: -x[1])
    print("  Most common 0x400-spaced pairs:")
    for (a, b), count in sorted_pairs[:15]:
        ldr_a = len(ewram_ldr.get(a, []))
        ldr_b = len(ewram_ldr.get(b, []))
        fade_candidate = b + 0x400
        fade_refs = len(ewram_ldr.get(fade_candidate, []))
        print(f"    0x{a:08X} / 0x{b:08X} -> in {count:2d} functions  "
              f"(LDR: {ldr_a}/{ldr_b}, candidate gPaletteFade=0x{fade_candidate:08X} [{fade_refs} LDR])")
    print()

    # =========================================================================
    # PHASE 3: For top pairs, look for BeginNormalPaletteFade signature
    # =========================================================================
    print("=" * 70)
    print("  PHASE 3: Identify BeginNormalPaletteFade from top pairs")
    print("=" * 70)
    print()

    # BeginNormalPaletteFade signature:
    # - References both buffer addresses (0x400 apart)
    # - References gPaletteFade (struct, = buffer_b + 0x400)
    # - Has BL calls (to CpuFastSet)
    # - ~100-300 bytes
    # - Stores to struct fields with STRB offsets +4, +5, +6, +8

    for (a, b), count in sorted_pairs[:5]:
        fade_candidate = b + 0x400
        print(f"  Pair: 0x{a:08X} / 0x{b:08X}, gPaletteFade candidate: 0x{fade_candidate:08X}")
        print(f"  LDR refs: {len(ewram_ldr.get(a,[]))} / {len(ewram_ldr.get(b,[]))} / fade={len(ewram_ldr.get(fade_candidate,[]))}")

        # Find functions that reference BOTH buffer addresses
        funcs_with_pair = [fs for fs, pairs_list in func_pairs.items()
                           if (a, b) in pairs_list]

        # Among those, which also reference gPaletteFade?
        funcs_with_fade = []
        for fs in funcs_with_pair:
            if fade_candidate in func_ewram[fs]:
                funcs_with_fade.append(fs)

        print(f"  Functions with both buffers: {len(funcs_with_pair)}")
        print(f"  Functions with both buffers + gPaletteFade: {len(funcs_with_fade)}")

        if funcs_with_fade:
            for fs in funcs_with_fade:
                func_addr = ROM_BASE + fs + 1
                print(f"    0x{func_addr:08X} (STRONG candidate for BeginNormalPaletteFade):")
                print(disasm_function(rom_data, fs, max_size=400))
                print()
        elif funcs_with_pair:
            # Show functions with both buffers even without fade struct
            for fs in funcs_with_pair[:3]:
                func_addr = ROM_BASE + fs + 1
                ewram_in_func = sorted(func_ewram[fs])
                print(f"    0x{func_addr:08X}: EWRAM = {[f'0x{v:08X}' for v in ewram_in_func[:8]]}")
                print(disasm_function(rom_data, fs, max_size=300))
                print()
        print()

    # =========================================================================
    # PHASE 4: Alternative - find gPaletteFade by its STRB offset pattern
    # =========================================================================
    print("=" * 70)
    print("  PHASE 4: Search for gPaletteFade via STRB field access pattern")
    print("=" * 70)
    print()

    # gPaletteFade is a 12-byte struct. Functions accessing it do:
    #   LDR Rn, =gPaletteFade
    #   STR Rd, [Rn, #0]     ; selectedPalettes (u32)
    #   STRB Rd, [Rn, #4]    ; delayCounter
    #   STRB Rd, [Rn, #5]    ; y
    #   STRB Rd, [Rn, #8]    ; active/yDec/etc
    #   STRB Rd, [Rn, #9]    ; mode
    #
    # Look for EWRAM addresses where we see LDR + STR/STRB with offsets 0, 4, 5, 8, 9

    # For each EWRAM address with LDR refs, check if the surrounding code
    # has STRB with offsets matching gPaletteFade fields
    print("  Scanning for EWRAM addresses with struct-like STRB access pattern...")

    fade_candidates = []

    for addr, positions in ewram_ldr.items():
        if len(positions) < 5:  # gPaletteFade should have decent number of refs
            continue

        # Check each LDR site for nearby STRB instructions
        field_offsets_seen = set()
        for ldr_pos in positions[:30]:  # Check first 30 refs
            # Scan 40 bytes after LDR for STRB Rd, [Rn, #offset]
            for delta in range(2, 40, 2):
                check_pos = ldr_pos + delta
                if check_pos + 1 >= len(rom_data):
                    break
                instr = read_u16_le(rom_data, check_pos)

                # STRB Rd, [Rn, #imm5]
                if (instr & 0xF800) == 0x7000:
                    off = (instr >> 6) & 0x1F
                    field_offsets_seen.add(off)

                # STR Rd, [Rn, #imm5*4]
                if (instr & 0xF800) == 0x6000:
                    off = ((instr >> 6) & 0x1F) << 2
                    field_offsets_seen.add(off)

                # LDRB Rd, [Rn, #imm5]
                if (instr & 0xF800) == 0x7800:
                    off = (instr >> 6) & 0x1F
                    field_offsets_seen.add(off)

                # LDR Rd, [Rn, #imm5*4]
                if (instr & 0xF800) == 0x6800:
                    off = ((instr >> 6) & 0x1F) << 2
                    field_offsets_seen.add(off)

        # gPaletteFade signature: accesses at offsets 0, 4, 5, 8 (at minimum)
        target_offsets = {0, 4, 5, 8}
        match_count = len(field_offsets_seen & target_offsets)
        if match_count >= 3:
            fade_candidates.append((addr, match_count, field_offsets_seen, len(positions)))

    fade_candidates.sort(key=lambda x: (-x[1], -x[3]))

    print(f"  Found {len(fade_candidates)} candidates with struct-like access (offsets 0,4,5,8):")
    for addr, match_count, offsets, ldr_count in fade_candidates[:20]:
        offset_str = ",".join(str(o) for o in sorted(offsets))
        # Check if addr - 0x400 is also an EWRAM ref (= gPlttBufferFaded)
        faded_candidate = addr - 0x400
        unfaded_candidate = addr - 0x800
        has_faded = faded_candidate in ewram_ldr
        has_unfaded = unfaded_candidate in ewram_ldr
        marker = ""
        if has_faded and has_unfaded:
            marker = f" *** BUFFER PAIR: unfaded=0x{unfaded_candidate:08X}({len(ewram_ldr[unfaded_candidate])}), faded=0x{faded_candidate:08X}({len(ewram_ldr[faded_candidate])}) ***"
        elif has_faded:
            marker = f" (faded=0x{faded_candidate:08X}: {len(ewram_ldr[faded_candidate])} LDR)"
        print(f"    0x{addr:08X}  match={match_count}/4  offsets=[{offset_str}]  {ldr_count} LDR{marker}")
    print()

    # =========================================================================
    # PHASE 5: Final determination
    # =========================================================================
    print("=" * 70)
    print("  PHASE 5: Final determination")
    print("=" * 70)
    print()

    # Best candidate: one that has:
    # 1. Struct-like access (offsets 0, 4, 5, 8)
    # 2. addr-0x400 and addr-0x800 both have many LDR refs (= buffer pair)
    # 3. addr-0x400 appears in 0x400-spaced pair functions

    best = None
    best_score = 0

    for addr, match_count, offsets, ldr_count in fade_candidates:
        faded = addr - 0x400
        unfaded = addr - 0x800
        score = match_count * 100
        if faded in ewram_ldr:
            score += len(ewram_ldr[faded])
        if unfaded in ewram_ldr:
            score += len(ewram_ldr[unfaded])
        if (unfaded, faded) in pair_count:
            score += pair_count[(unfaded, faded)] * 50
        if score > best_score:
            best_score = score
            best = addr

    if best:
        fade = best
        faded = best - 0x400
        unfaded = best - 0x800

        print(f"  RESULT (score={best_score}):")
        print(f"    gPlttBufferUnfaded = 0x{unfaded:08X}  ({len(ewram_ldr.get(unfaded,[]))} LDR refs)")
        print(f"    gPlttBufferFaded   = 0x{faded:08X}  ({len(ewram_ldr.get(faded,[]))} LDR refs)")
        print(f"    gPaletteFade       = 0x{fade:08X}  ({len(ewram_ldr.get(fade,[]))} LDR refs)")
        print()

        # Validation: show functions that reference gPaletteFade
        fade_positions = ewram_ldr.get(fade, [])
        print(f"  Functions referencing gPaletteFade (0x{fade:08X}):")
        seen_funcs = set()
        for pos in fade_positions:
            fs = find_function_start(rom_data, pos)
            if fs and fs not in seen_funcs:
                seen_funcs.add(fs)
                func_addr = ROM_BASE + fs + 1
                ewram_in_func = sorted(func_ewram.get(fs, set()))
                other_ewram = [f"0x{a:08X}" for a in ewram_in_func if a != fade][:5]
                also = ""
                if faded in ewram_in_func:
                    also += " +Faded"
                if unfaded in ewram_in_func:
                    also += " +Unfaded"
                print(f"    0x{func_addr:08X}{also}  other: {other_ewram}")

        # Show BeginNormalPaletteFade (references fade + both buffers)
        print()
        for fs in seen_funcs:
            addrs_in = func_ewram.get(fs, set())
            if fade in addrs_in and faded in addrs_in:
                func_addr = ROM_BASE + fs + 1
                print(f"  Likely BeginNormalPaletteFade = 0x{func_addr:08X}")
                print(disasm_function(rom_data, fs, max_size=400))
                print()

        print()
        print("=" * 70)
        print("  FINAL ANSWER")
        print("=" * 70)
        print()
        print(f"  gPlttBufferUnfaded = 0x{unfaded:08X}")
        print(f"  gPlttBufferFaded   = 0x{faded:08X}")
        print(f"  gPaletteFade       = 0x{fade:08X}")
        print()
        print(f"  gPaletteFade fields:")
        print(f"    +0x00 (0x{fade:08X}): selectedPalettes (u32)")
        print(f"    +0x04 (0x{fade+4:08X}): delayCounter (u8)")
        print(f"    +0x05 (0x{fade+5:08X}): y (u8)")
        print(f"    +0x06 (0x{fade+6:08X}): targetY:6, blendColor bits")
        print(f"    +0x08 (0x{fade+8:08X}): active:1, yDec:1, bufferTransferDisabled:1, ...")
        print(f"    +0x09 (0x{fade+9:08X}): mode (u8)")
        print(f"    +0x0A (0x{fade+0xA:08X}): shouldResetBlendRegisters:1, ...")
    else:
        print("  FAILED to determine gPaletteFade address.")
        print("  Top EWRAM by LDR count for manual analysis:")
        sorted_all = sorted(ewram_ldr.items(), key=lambda x: -len(x[1]))
        for addr, refs in sorted_all[:30]:
            print(f"    0x{addr:08X}: {len(refs)} LDR refs")

    print()
    print("=" * 70)
    print("  SCAN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
