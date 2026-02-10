#!/usr/bin/env python3
"""
Find the REAL GetMultiplayerId function in Pokemon Run & Bun ROM.

The previously identified address 0x0833D67F is WRONG -- disassembly shows it's
an SIO initialization function (writes to SIO registers, not reads).

The real GetMultiplayerId in vanilla Emerald (0x0800A468) looks like:
    u16 GetMultiplayerId(void) {
        if (gWirelessCommType != 0)
            return Rfu_GetMultiplayerId();
        return SIO_MULTI_CNT->id;  // read bits 4-5 of 0x04000120
    }

Strategy:
1. Find ALL ROM literal pool references to gWirelessCommType (0x030030FC)
2. For each reference, find the CLOSEST enclosing THUMB function (walk back to PUSH {LR})
3. Find the function end correctly (stop at first POP {PC} or BX LR, not crossing literal pools)
4. Filter for SMALL functions (< 80 bytes)
5. Check if it also references SIO_MULTI_CNT (0x04000120) OR an IWRAM cached copy
6. Check instruction pattern: LDRB gWirelessCommType, CMP #0, BEQ/BNE, BL Rfu_xxx
7. The function that's small, has 1 BL, and returns an ID value is GetMultiplayerId

Also finds related link functions in the same ROM region:
- GetLinkPlayerCount (similar pattern, different return value)
- IsLinkMaster
- Other link utility functions

No Ghidra needed -- reads the .gba file directly.
"""

import struct
import sys
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known addresses
GWIRELESS_COMM_TYPE = 0x030030FC  # IWRAM, confirmed
SIO_MULTI_CNT      = 0x04000120  # Hardware IO register (SIO multi-player control)
REG_SIOCNT         = 0x04000128  # Hardware IO register (SIO control -- THIS is what GetMultiplayerId actually reads)
WRONG_GMI          = 0x0833D67F  # Previously identified (WRONG)

# Both 0x04000120 and 0x04000128 are SIO registers. In pokeemerald source code,
# GetMultiplayerId reads REG_SIOCNT (0x04000128) and extracts bits 5:4 for the ID.
# Some versions may use SIO_MULTI_CNT (0x04000120) instead.
SIO_REGISTERS = {0x04000120, 0x04000128}


# =============================================================================
# Low-level ROM read helpers
# =============================================================================

def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


# =============================================================================
# Function boundary detection
# =============================================================================

def find_all_literal_refs(rom_data, target_value):
    """Find all 4-byte aligned positions in ROM where target_value appears."""
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs


def find_function_start(rom_data, offset, max_back=1024):
    """Walk backward to find PUSH {..., LR} = 0xB5xx."""
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16(rom_data, pos)
        if (instr & 0xFF00) == 0xB500:  # PUSH {..., LR}
            return pos
    return None


def find_function_end(rom_data, func_start, max_size=512):
    """Find function end: first POP {PC} or POP {Rn}+BX Rn after at least 4 bytes.
    Also detect BX LR. Stop before entering literal pool territory."""
    pos = func_start + 2  # skip the PUSH instruction
    limit = min(func_start + max_size, len(rom_data) - 2)

    while pos < limit:
        instr = read_u16(rom_data, pos)

        # POP {..., PC} = 0xBDxx
        if (instr & 0xFF00) == 0xBD00:
            return pos + 2

        # BX LR = 0x4770
        if instr == 0x4770:
            return pos + 2

        # POP {Rn} (no PC) followed by BX Rn
        if (instr & 0xFE00) == 0xBC00 and not (instr & 0x100):
            if pos + 2 < limit:
                next_instr = read_u16(rom_data, pos + 2)
                if (next_instr & 0xFF80) == 0x4700:  # BX Rm
                    return pos + 4

        # Skip BL 32-bit pairs
        if (instr & 0xF800) == 0xF000 and pos + 2 < limit:
            next_instr = read_u16(rom_data, pos + 2)
            if (next_instr & 0xF800) == 0xF800:
                pos += 4
                continue

        pos += 2

    return None


def get_ldr_pc_literals(rom_data, func_start, func_end):
    """Extract all LDR Rd,[PC,#imm] literal pool values within a function range."""
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

        # Skip BL pairs
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


# =============================================================================
# THUMB disassembler
# =============================================================================

COND_NAMES = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
              "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]

def disassemble_range(rom_data, start, end):
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

        # ADD/SUB 3-reg
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

        # SP-relative
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
                mnem = f"SUB SP, #{imm}"
            else:
                mnem = f"ADD SP, #{imm}"

        # NOP
        elif instr == 0x46C0:
            mnem = "NOP"
        elif instr == 0x0000:
            mnem = "DATA 0x0000"

        else:
            mnem = f"??? 0x{instr:04X}"

        lines.append((pos, addr, raw, mnem))
        pos += 2

    return lines


# =============================================================================
# Vanilla Emerald GetMultiplayerId for comparison
# =============================================================================

VANILLA_GMI_DESC = """
Vanilla Emerald GetMultiplayerId (0x0800A468):
    PUSH {LR}
    LDR  R0, =gWirelessCommType     ; 0x030022C4 in vanilla, 0x030030FC in R&B
    LDRB R0, [R0]
    CMP  R0, #0
    BEQ  sio_path
    BL   Rfu_GetMultiplayerId       ; wireless path
    LSL  R0, R0, #24
    LSR  R0, R0, #24               ; mask to u8
    B    done
sio_path:
    LDR  R0, =REG_SIOCNT           ; 0x04000128 (or SIO_MULTI_CNT 0x04000120)
    LDR  R0, [R0]                  ; read 32-bit value from SIO register
    LSL  R0, R0, #26              ; extract bits 5:4 (shift left 26, then right 30)
    LSR  R0, R0, #30              ; result = 0-3 (2-bit player ID)
    B    done
done:
    POP  {R1}
    BX   R1

Key signature:
- Small (~40-50 bytes)
- 1 BL call (to Rfu_GetMultiplayerId)
- Loads gWirelessCommType (0x030030FC)
- Loads REG_SIOCNT (0x04000128) or SIO_MULTI_CNT (0x04000120) -- SIO hardware register
- Extracts bits 5:4 via LSL#26+LSR#30 or LSR#4+AND#3
- Returns u16 (0-3)
- No parameters (void function)
"""


# =============================================================================
# Main analysis
# =============================================================================

def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        print(f"  Expected: {ROM_PATH.resolve()}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size:,} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print()
    print(VANILLA_GMI_DESC)

    # =========================================================================
    # STEP 1: Find all literal pool references
    # =========================================================================
    print("=" * 78)
    print("  STEP 1: Literal pool references")
    print("=" * 78)
    print()

    gwct_refs = find_all_literal_refs(rom_data, GWIRELESS_COMM_TYPE)
    sio_refs = find_all_literal_refs(rom_data, SIO_MULTI_CNT)
    siocnt_refs = find_all_literal_refs(rom_data, REG_SIOCNT)
    print(f"  gWirelessCommType (0x{GWIRELESS_COMM_TYPE:08X}): {len(gwct_refs)} refs")
    print(f"  SIO_MULTI_CNT    (0x{SIO_MULTI_CNT:08X}): {len(sio_refs)} refs")
    print(f"  REG_SIOCNT       (0x{REG_SIOCNT:08X}): {len(siocnt_refs)} refs")
    print()

    # =========================================================================
    # STEP 2: For each gWirelessCommType ref, find its INDIVIDUAL function
    # =========================================================================
    print("=" * 78)
    print("  STEP 2: Find individual functions containing gWirelessCommType refs")
    print("=" * 78)
    print()

    # Build set of SIO ref offsets for quick lookup
    sio_ref_set = set(sio_refs)

    # For each gwct literal pool entry, walk backward to find the function start,
    # then forward to find the function end, producing one function per ref
    functions = {}  # func_start -> {info}
    for lit_off in gwct_refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start is None:
            continue
        if func_start in functions:
            continue  # already found this function via another literal ref

        func_end = find_function_end(rom_data, func_start)
        if func_end is None:
            func_end = min(func_start + 200, len(rom_data))

        func_size = func_end - func_start
        func_addr = ROM_BASE + func_start + 1  # +1 for THUMB

        # Get all literal pool values
        lits = get_ldr_pc_literals(rom_data, func_start, func_end)
        lit_vals = set(v for _, _, v, _ in lits)

        # Get BL targets
        bl_targets = get_bl_targets(rom_data, func_start, func_end)

        # Check for any SIO register reference
        has_sio = bool(lit_vals & SIO_REGISTERS)

        # Check for IWRAM addresses (potential cached SIO value)
        iwram_vals = [v for _, _, v, _ in lits if 0x03000000 <= v < 0x03008000 and v != GWIRELESS_COMM_TYPE]

        # Check for IO register addresses
        io_vals = [v for _, _, v, _ in lits if 0x04000000 <= v < 0x05000000]

        functions[func_start] = {
            'start': func_start,
            'end': func_end,
            'size': func_size,
            'addr': func_addr,
            'lits': lits,
            'lit_vals': lit_vals,
            'bl_targets': bl_targets,
            'has_sio': has_sio,
            'iwram_vals': iwram_vals,
            'io_vals': io_vals,
        }

    print(f"  Found {len(functions)} unique functions referencing gWirelessCommType")
    print()

    # =========================================================================
    # STEP 3: Score and rank candidates
    # =========================================================================
    print("=" * 78)
    print("  STEP 3: Score and rank GetMultiplayerId candidates")
    print("=" * 78)
    print()

    scored = []
    for func_start, info in functions.items():
        score = 0
        reasons = []
        size = info['size']
        bl_count = len(info['bl_targets'])

        # --- SIZE SCORING ---
        if size <= 50:
            score += 40
            reasons.append(f"very small ({size} bytes)")
        elif size <= 70:
            score += 30
            reasons.append(f"small ({size} bytes)")
        elif size <= 100:
            score += 15
            reasons.append(f"medium ({size} bytes)")
        else:
            score -= 20
            reasons.append(f"too large ({size} bytes)")

        # --- BL COUNT ---
        if bl_count == 1:
            score += 25
            target = info['bl_targets'][0][1]
            reasons.append(f"exactly 1 BL -> 0x{target:08X}")
        elif bl_count == 0:
            score += 5
            reasons.append("no BL calls (may be inlined)")
        else:
            score -= 10
            reasons.append(f"{bl_count} BL calls (too many)")

        # --- SIO register reference (critical for GetMultiplayerId) ---
        has_sio_reg = any(v in SIO_REGISTERS for v in info['lit_vals'])
        if has_sio_reg:
            sio_addrs = [v for v in info['lit_vals'] if v in SIO_REGISTERS]
            score += 30
            reasons.append(f"refs SIO register: {[f'0x{v:08X}' for v in sio_addrs]}")

        # --- IWRAM value reading (alternative to direct IO) ---
        if info['iwram_vals']:
            score += 3
            reasons.append(f"refs IWRAM: {[f'0x{v:08X}' for v in info['iwram_vals']]}")

        # --- Instruction pattern analysis ---
        disasm = disassemble_range(rom_data, info['start'], info['end'])

        # Look for: LDR gWirelessCommType -> LDRB -> CMP #0 -> BEQ/BNE
        for i, (off, addr, raw, mnem) in enumerate(disasm):
            if "0x030030FC" in mnem and "LDR" in mnem:
                # Check next 3 instructions
                upcoming = [(m, r) for _, _, r, m in disasm[i+1:i+4]]
                has_ldrb = any("LDRB" in m for m, _ in upcoming[:2])
                has_cmp0 = any("CMP" in m and "#0" in m for m, _ in upcoming[:3])
                has_branch = any(m.startswith("BEQ") or m.startswith("BNE") for m, _ in upcoming[:3])

                if has_ldrb and has_cmp0 and has_branch:
                    score += 30
                    reasons.append("PATTERN: LDR gWirelessCommType -> LDRB -> CMP #0 -> branch")
                    break  # only count once

        # Look for SIO ID extraction patterns:
        # Pattern A: LDRH + LSR #4 + AND #3 (vanilla: read SIO_MULTI_CNT, shift right 4, mask 2 bits)
        # Pattern B: LDR + LSL #26 + LSR #30 (R&B: read REG_SIOCNT, extract bits 5:4)
        # Pattern C: LDR + AND + LSR from IWRAM cached value
        has_lsr = False
        has_and = False
        has_ldrh = False
        has_sio_id_extract = False
        for i, (_, _, _, mnem) in enumerate(disasm):
            if "LSR" in mnem: has_lsr = True
            if "AND" in mnem: has_and = True
            if "LDRH" in mnem: has_ldrh = True
            # Check for LSL #26 + LSR #30 pattern (extracts bits 5:4 = 2-bit ID)
            if "LSL" in mnem and "#26" in mnem:
                if i + 1 < len(disasm) and "LSR" in disasm[i+1][3] and "#30" in disasm[i+1][3]:
                    has_sio_id_extract = True

        if has_sio_id_extract:
            score += 25
            reasons.append("SIO ID EXTRACT: LSL#26+LSR#30 (bits 5:4 = multiplayer ID)")
        elif has_ldrh and has_lsr and (has_and or has_sio_reg):
            score += 15
            reasons.append("has LDRH+LSR (SIO register ID extraction)")
        elif has_lsr and has_and:
            score += 8
            reasons.append("has LSR+AND (bit field extraction)")

        # Look for u8 truncation: LSL R0,R0,#24; LSR R0,R0,#24
        for i, (_, _, _, mnem) in enumerate(disasm[:-1]):
            if "LSL" in mnem and "#24" in mnem:
                next_mnem = disasm[i+1][3]
                if "LSR" in next_mnem and "#24" in next_mnem:
                    score += 5
                    reasons.append("has u8 truncation (LSL#24+LSR#24)")
                    break

        # --- Does NOT write to SIO registers (GetMultiplayerId only READS) ---
        has_str_to_io = False
        for _, _, _, mnem in disasm:
            if "STR" in mnem and any(f"0x{v:08X}" in mnem for v in [0x04000120, 0x04000128, 0x04000130]):
                has_str_to_io = True
        if has_str_to_io:
            score -= 50
            reasons.append("WRITES to SIO registers (NOT GetMultiplayerId)")

        # --- Writes to IWRAM callback pointer (this is a link init function, not GetMultiplayerId) ---
        writes_callback = False
        for _, _, _, mnem in disasm:
            if "STR" in mnem and "0x03003140" in str(info['lit_vals']):
                # Check if the function stores a ROM address to 0x03003140
                for _, _, v, _ in info['lits']:
                    if 0x08000000 <= v < 0x0A000000 and v != ROM_BASE + info['start'] + 1:
                        writes_callback = True
        if writes_callback:
            score -= 15
            reasons.append("stores ROM callback to IWRAM (link init function, not GetMultiplayerId)")

        # --- GetMultiplayerId should NOT take parameters (R0 is loaded fresh inside) ---
        # If the function starts with parameter processing (LSL R0,R0,#24 etc.) it's something else
        if len(disasm) >= 2:
            first_mnem = disasm[1][3]  # after PUSH
            if "LSL" in first_mnem and "R0" in first_mnem and "#24" in first_mnem:
                score -= 10
                reasons.append("takes parameter (LSL R0,#24 at start) -- not GetMultiplayerId")

        # --- ROM address range check: vanilla GetMultiplayerId is near 0x0800A468 ---
        # In R&B, link functions tend to be in the same region
        rom_offset = info['start']
        if 0x9000 <= rom_offset <= 0x12000:
            score += 10
            reasons.append("in expected ROM region (link functions)")

        scored.append((score, info, reasons))

    # Sort by score descending
    scored.sort(key=lambda x: -x[0])

    # =========================================================================
    # STEP 4: Display ranked candidates with full disassembly
    # =========================================================================
    print("=" * 78)
    print("  STEP 4: RANKED CANDIDATES with full disassembly")
    print("=" * 78)
    print()

    # Show all candidates scoring >= 50, plus always show top 10
    shown = 0
    for rank, (score, info, reasons) in enumerate(scored):
        if shown >= 15 and score < 50:
            break
        shown += 1

        func_addr = info['addr']
        size = info['size']
        is_wrong = (func_addr == WRONG_GMI)

        marker = ""
        if score >= 90:
            marker = "  <<<< BEST MATCH"
        elif score >= 70:
            marker = "  <<< STRONG CANDIDATE"
        elif score >= 50:
            marker = "  << POSSIBLE"

        wrong_marker = "  [WRONG - previously identified]" if is_wrong else ""

        print(f"  #{rank+1}  0x{func_addr:08X}  score={score}  size={size} bytes{marker}{wrong_marker}")
        for r in reasons:
            print(f"       - {r}")
        print()

        # Full disassembly
        disasm = disassemble_range(rom_data, info['start'], info['end'])
        print(f"    Disassembly:")
        for off, addr, raw, mnem in disasm:
            annotation = ""
            if "0x030030FC" in mnem:
                annotation = "  ; gWirelessCommType"
            elif "0x04000120" in mnem:
                annotation = "  ; SIO_MULTI_CNT"
            elif "0x04000128" in mnem:
                annotation = "  ; REG_SIOCNT"
            print(f"      0x{addr:08X}: {raw:<12s} {mnem}{annotation}")

        # Literal pool
        print(f"    Literal pool:")
        for instr_off, reg, val, _ in info['lits']:
            label = ""
            if val == GWIRELESS_COMM_TYPE: label = " = gWirelessCommType"
            elif val == SIO_MULTI_CNT: label = " = SIO_MULTI_CNT"
            elif 0x03000000 <= val < 0x03008000: label = " (IWRAM)"
            elif 0x02000000 <= val < 0x02040000: label = " (EWRAM)"
            elif 0x04000000 <= val < 0x05000000: label = " (IO REG)"
            elif 0x08000000 <= val < 0x0A000000: label = " (ROM)"
            print(f"      +{instr_off:3d}: R{reg} = 0x{val:08X}{label}")

        # BL targets
        if info['bl_targets']:
            print(f"    BL targets:")
            for off, target in info['bl_targets']:
                print(f"      +{off:3d}: BL 0x{target:08X}")

        print()
        print("    " + "-" * 60)
        print()

    # =========================================================================
    # STEP 5: Disassemble the WRONG address for comparison
    # =========================================================================
    print("=" * 78)
    print("  STEP 5: Disassembly of WRONG address 0x0833D67F for comparison")
    print("=" * 78)
    print()

    wrong_rom_off = (WRONG_GMI & ~1) - ROM_BASE
    wrong_start = find_function_start(rom_data, wrong_rom_off)
    if wrong_start is not None:
        wrong_end = find_function_end(rom_data, wrong_start)
        if wrong_end is None:
            wrong_end = wrong_start + 128
        wrong_size = wrong_end - wrong_start
        wrong_addr = ROM_BASE + wrong_start + 1
        print(f"  Function: 0x{wrong_addr:08X} ({wrong_size} bytes)")
        print()

        disasm = disassemble_range(rom_data, wrong_start, wrong_end)
        for off, addr, raw, mnem in disasm:
            annotation = ""
            if "0x04000120" in mnem: annotation = "  ; SIO_MULTI_CNT"
            elif "0x04000128" in mnem: annotation = "  ; REG_SIOCNT"
            elif "0x0400012" in mnem: annotation = "  ; SIO reg"
            print(f"    0x{addr:08X}: {raw:<12s} {mnem}{annotation}")

        lits = get_ldr_pc_literals(rom_data, wrong_start, wrong_end)
        has_gwct = any(v == GWIRELESS_COMM_TYPE for _, _, v, _ in lits)
        print()
        print(f"  References gWirelessCommType? {'YES' if has_gwct else 'NO'}")
        print(f"  --> {'This IS consistent with GetMultiplayerId' if has_gwct else 'CONFIRMED: NOT GetMultiplayerId (no gWirelessCommType)'}")
    else:
        print(f"  Could not find function start for 0x{wrong_rom_off:06X}")

    # =========================================================================
    # STEP 6: Also scan nearby small functions at 0x0800A4xx-0x0800ACxx
    # (vanilla Emerald GetMultiplayerId is at 0x0800A468 -- R&B may be similar)
    # =========================================================================
    print()
    print("=" * 78)
    print("  STEP 6: Focused scan of ROM region 0x0800A400-0x0800AD00")
    print("  (Vanilla GetMultiplayerId is at 0x0800A468)")
    print("=" * 78)
    print()

    region_start = 0xA400
    region_end = 0xAD00
    pos = region_start

    region_funcs = []
    while pos < region_end:
        if pos + 2 > len(rom_data):
            break
        instr = read_u16(rom_data, pos)
        # Look for PUSH {..., LR}
        if (instr & 0xFF00) == 0xB500:
            func_start = pos
            func_end = find_function_end(rom_data, func_start, max_size=300)
            if func_end is not None:
                size = func_end - func_start
                lits = get_ldr_pc_literals(rom_data, func_start, func_end)
                lit_vals = set(v for _, _, v, _ in lits)
                bls = get_bl_targets(rom_data, func_start, func_end)

                has_gwct = GWIRELESS_COMM_TYPE in lit_vals
                has_sio = bool(lit_vals & SIO_REGISTERS)

                region_funcs.append({
                    'start': func_start,
                    'end': func_end,
                    'size': size,
                    'addr': ROM_BASE + func_start + 1,
                    'has_gwct': has_gwct,
                    'has_sio': has_sio,
                    'lits': lits,
                    'lit_vals': lit_vals,
                    'bls': bls,
                })
                pos = func_end
                # Align to 2
                if pos % 2:
                    pos += 1
                continue
        pos += 2

    print(f"  Found {len(region_funcs)} functions in region 0x0800A400-0x0800AD00")
    print()

    for f in region_funcs:
        gwct_flag = " [gWirelessCommType]" if f['has_gwct'] else ""
        sio_flag = " [SIO_REG]" if f['has_sio'] else ""
        bl_flag = f" [{len(f['bls'])} BL]" if f['bls'] else ""
        interesting = f['has_gwct'] or f['has_sio']
        marker = " ****" if interesting else ""

        print(f"  0x{f['addr']:08X} ({f['size']:3d} bytes){gwct_flag}{sio_flag}{bl_flag}{marker}")

        if interesting:
            print()
            disasm = disassemble_range(rom_data, f['start'], f['end'])
            for off, addr, raw, mnem in disasm:
                annotation = ""
                if "0x030030FC" in mnem: annotation = "  ; gWirelessCommType"
                elif "0x04000120" in mnem: annotation = "  ; SIO_MULTI_CNT"
                print(f"      0x{addr:08X}: {raw:<12s} {mnem}{annotation}")
            print(f"    Literal pool:")
            for ioff, reg, val, _ in f['lits']:
                label = ""
                if val == GWIRELESS_COMM_TYPE: label = " = gWirelessCommType"
                elif val == SIO_MULTI_CNT: label = " = SIO_MULTI_CNT"
                elif 0x03000000 <= val < 0x03008000: label = " (IWRAM)"
                elif 0x02000000 <= val < 0x02040000: label = " (EWRAM)"
                elif 0x04000000 <= val < 0x05000000: label = " (IO REG)"
                elif 0x08000000 <= val < 0x0A000000: label = " (ROM)"
                print(f"      +{ioff:3d}: R{reg} = 0x{val:08X}{label}")
            if f['bls']:
                print(f"    BL targets:")
                for off, target in f['bls']:
                    print(f"      +{off:3d}: BL 0x{target:08X}")
            print()

    # =========================================================================
    # STEP 7: Final verdict
    # =========================================================================
    print("=" * 78)
    print("  STEP 7: FINAL VERDICT")
    print("=" * 78)
    print()

    if scored:
        best_score, best_info, best_reasons = scored[0]
        func_addr = best_info['addr']
        func_size = best_info['size']
        func_start = best_info['start']

        # Also find the second-best for comparison
        second = scored[1] if len(scored) > 1 else None

        if best_score >= 80:
            confidence = "HIGH"
        elif best_score >= 60:
            confidence = "MODERATE"
        else:
            confidence = "LOW"

        print(f"  RESULT: GetMultiplayerId = 0x{func_addr:08X}")
        print(f"  Confidence: {confidence} (score={best_score})")
        print(f"  Size: {func_size} bytes")
        print(f"  ROM file offset: 0x{func_start:06X}")
        print()
        print(f"  Reasons:")
        for r in best_reasons:
            print(f"    - {r}")
        print()

        if second:
            s2_score, s2_info, s2_reasons = second
            print(f"  Runner-up: 0x{s2_info['addr']:08X} (score={s2_score}, {s2_info['size']} bytes)")
            for r in s2_reasons:
                print(f"    - {r}")
            print()

        print(f"  PATCHING INSTRUCTIONS:")
        print(f"  To make this always return 0 (master): overwrite at ROM offset 0x{func_start:06X}")
        print(f"    Bytes: 00 20 70 47  (MOV R0,#0 + BX LR)")
        print(f"  To make this always return 1 (slave): overwrite at ROM offset 0x{func_start:06X}")
        print(f"    Bytes: 01 20 70 47  (MOV R0,#1 + BX LR)")
        print()
        print(f"  ROM address for mGBA memory write:")
        print(f"    cart0 offset: 0x{func_start:06X}")
        print(f"    Full address: 0x{ROM_BASE + func_start:08X}")

    print()
    print("=" * 78)
    print("  SCAN COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()
