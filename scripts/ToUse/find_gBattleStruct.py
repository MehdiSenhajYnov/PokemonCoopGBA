#!/usr/bin/env python3
"""
Scan Pokemon Run & Bun ROM to find gBattleStruct pointer address.

Strategy:
  DoBattleIntro (ROM 0x0803ACB0, file offset 0x03ACB0) is a THUMB function
  that accesses gBattleStruct->eventState.battleIntro early on.

  In THUMB code, global pointers are loaded via:
    LDR Rd, [PC, #imm8*4]   (opcode 0x48xx)
  which loads a 32-bit value from a literal pool.

  gBattleStruct is a pointer to an EWRAM struct. After loading it,
  the code dereferences it and accesses offset 0x58 (eventState.battleIntro).

  We scan the first 300 bytes of DoBattleIntro for all PC-relative LDR
  instructions and dump the literal pool values, highlighting EWRAM pointers
  and any nearby accesses at offset 0x58.
"""

import struct
import sys
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# DoBattleIntro ROM address (THUMB, so bit 0 is set in pointer but actual code is at even address)
DO_BATTLE_INTRO_ROM = 0x0803ACB0
DO_BATTLE_INTRO_FILE = DO_BATTLE_INTRO_ROM & 0x01FFFFFF  # Strip upper bits for file offset = 0x03ACB0

SCAN_BYTES = 300  # How many bytes of the function to scan
CONTEXT_BYTES = 600  # Read extra for literal pool references that may be beyond scan range

EWRAM_LOW  = 0x02000000
EWRAM_HIGH = 0x0203FFFF
IWRAM_LOW  = 0x03000000
IWRAM_HIGH = 0x03007FFF
ROM_LOW    = 0x08000000
ROM_HIGH   = 0x09FFFFFF

TARGET_OFFSET = 0x58  # eventState.battleIntro offset in gBattleStruct


def classify_address(val):
    """Classify a 32-bit value by GBA memory region."""
    if EWRAM_LOW <= val <= EWRAM_HIGH:
        return "EWRAM"
    elif IWRAM_LOW <= val <= IWRAM_HIGH:
        return "IWRAM"
    elif ROM_LOW <= val <= ROM_HIGH:
        return "ROM"
    elif val == 0:
        return "NULL"
    else:
        return "OTHER"


def disasm_thumb_simple(hw, pc):
    """Very simple THUMB disassembly for display purposes."""
    op = (hw >> 8) & 0xFF

    # LDR Rd, [PC, #imm8*4] — format 6
    if (hw >> 11) == 0x09:  # 0b01001
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        target = ((pc & ~2) + 4) + imm8 * 4
        return f"LDR R{rd}, [PC, #0x{imm8*4:X}]  ; =>[0x{target:08X}]"

    # LDR Rd, [Rn, #imm5*4] — format 9 (word)
    if (hw >> 11) == 0x0D:  # 0b01101
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 0x7
        rd = hw & 0x7
        return f"LDR R{rd}, [R{rn}, #0x{imm5*4:X}]"

    # LDRB Rd, [Rn, #imm5] — format 9 (byte)
    if (hw >> 11) == 0x0F:  # 0b01111
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 0x7
        rd = hw & 0x7
        return f"LDRB R{rd}, [R{rn}, #0x{imm5:X}]"

    # LDRH Rd, [Rn, #imm5*2] — format 10 (halfword)
    if (hw >> 11) == 0x11:  # 0b10001
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 0x7
        rd = hw & 0x7
        return f"LDRH R{rd}, [R{rn}, #0x{imm5*2:X}]"

    # STR Rd, [Rn, #imm5*4]
    if (hw >> 11) == 0x0C:  # 0b01100
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 0x7
        rd = hw & 0x7
        return f"STR R{rd}, [R{rn}, #0x{imm5*4:X}]"

    # STRB Rd, [Rn, #imm5]
    if (hw >> 11) == 0x0E:  # 0b01110
        imm5 = (hw >> 6) & 0x1F
        rn = (hw >> 3) & 0x7
        rd = hw & 0x7
        return f"STRB R{rd}, [R{rn}, #0x{imm5:X}]"

    # ADD Rd, #imm8
    if (hw >> 11) == 0x06:  # 0b00110
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        return f"ADD R{rd}, #0x{imm8:X}"

    # MOV Rd, #imm8
    if (hw >> 11) == 0x04:  # 0b00100
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        return f"MOV R{rd}, #0x{imm8:X}"

    # CMP Rd, #imm8
    if (hw >> 11) == 0x05:  # 0b00101
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        return f"CMP R{rd}, #0x{imm8:X}"

    # PUSH
    if (hw >> 9) == 0x5A:  # 0b1011010x
        L = (hw >> 8) & 1
        rlist = hw & 0xFF
        regs = [f"R{i}" for i in range(8) if rlist & (1 << i)]
        if L:
            regs.append("LR")
        return f"PUSH {{{', '.join(regs)}}}"

    # POP
    if (hw >> 9) == 0x5E:  # 0b1011110x
        P = (hw >> 8) & 1
        rlist = hw & 0xFF
        regs = [f"R{i}" for i in range(8) if rlist & (1 << i)]
        if P:
            regs.append("PC")
        return f"POP {{{', '.join(regs)}}}"

    # BL/BLX (32-bit instruction, first half)
    if (hw >> 11) == 0x1E:  # 0b11110
        return f"BL(hi) imm11=0x{hw & 0x7FF:03X}"
    if (hw >> 11) == 0x1F:  # 0b11111
        return f"BL(lo) imm11=0x{hw & 0x7FF:03X}"

    # B (unconditional)
    if (hw >> 11) == 0x1C:  # 0b11100
        imm11 = hw & 0x7FF
        if imm11 & 0x400:
            imm11 |= 0xFFFFF800  # sign extend
        return f"B #0x{(imm11 * 2) & 0xFFFFFFFF:X}"

    # B<cond>
    if (hw >> 12) == 0xD:
        cond = (hw >> 8) & 0xF
        cond_names = ["EQ","NE","CS","CC","MI","PL","VS","VC","HI","LS","GE","LT","GT","LE","AL","NV"]
        imm8 = hw & 0xFF
        if imm8 & 0x80:
            imm8 |= 0xFFFFFF00
        if cond < 16:
            return f"B{cond_names[cond]} #0x{(imm8 * 2) & 0xFFFFFFFF:X}"

    return f"??? (0x{hw:04X})"


def main():
    if not os.path.exists(ROM_PATH):
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_size = os.path.getsize(ROM_PATH)
    print(f"ROM: {ROM_PATH}")
    print(f"ROM size: {rom_size:,} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print()

    with open(ROM_PATH, "rb") as f:
        # Read a chunk around DoBattleIntro
        f.seek(DO_BATTLE_INTRO_FILE)
        data = f.read(CONTEXT_BYTES)

    print(f"DoBattleIntro at ROM 0x{DO_BATTLE_INTRO_ROM:08X} (file offset 0x{DO_BATTLE_INTRO_FILE:06X})")
    print(f"Scanning first {SCAN_BYTES} bytes for THUMB LDR Rd,[PC,#imm] instructions")
    print(f"Looking for gBattleStruct (EWRAM pointer, accessed with offset 0x{TARGET_OFFSET:02X})")
    print("=" * 100)
    print()

    # --- Pass 1: Find all PC-relative LDR instructions and their literal pool values ---

    ldr_refs = []  # (func_offset, rom_addr, reg, lit_pool_rom, lit_pool_file, value, region)

    print(f"{'Offset':>6} | {'ROM Addr':>10} | {'Instruction':40} | {'Lit Pool':>10} | {'Value':>10} | {'Region':>6}")
    print("-" * 100)

    for i in range(0, SCAN_BYTES, 2):
        if i + 1 >= len(data):
            break

        hw = struct.unpack_from("<H", data, i)[0]
        pc = DO_BATTLE_INTRO_ROM + i  # Current PC (ROM address)

        # Check for LDR Rd, [PC, #imm8*4] — encoding: 0100 1ddd iiii iiii
        if (hw >> 11) == 0x09:  # 0b01001
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF

            # Literal pool address: (PC & ~2) + 4 + imm8*4
            lit_pool_rom = ((pc & ~2) + 4) + imm8 * 4
            lit_pool_file = lit_pool_rom & 0x01FFFFFF

            # Read the 32-bit value from literal pool
            lit_pool_local = lit_pool_file - DO_BATTLE_INTRO_FILE
            if 0 <= lit_pool_local < len(data) - 3:
                value = struct.unpack_from("<I", data, lit_pool_local)[0]
            else:
                # Need to read from ROM directly
                with open(ROM_PATH, "rb") as f:
                    f.seek(lit_pool_file)
                    raw = f.read(4)
                    if len(raw) == 4:
                        value = struct.unpack("<I", raw)[0]
                    else:
                        value = 0xDEADBEEF

            region = classify_address(value)
            marker = ""
            if region == "EWRAM":
                marker = " <-- EWRAM CANDIDATE"

            disasm = disasm_thumb_simple(hw, pc)
            print(f"+0x{i:03X} | 0x{pc:08X} | {disasm:40} | 0x{lit_pool_rom:08X} | 0x{value:08X} | {region}{marker}")

            ldr_refs.append({
                "offset": i,
                "rom_addr": pc,
                "reg": rd,
                "lit_pool_rom": lit_pool_rom,
                "lit_pool_file": lit_pool_file,
                "value": value,
                "region": region,
            })

    print()
    print("=" * 100)
    print()

    # --- Pass 2: For each EWRAM reference, check if offset 0x58 is accessed nearby ---

    ewram_refs = [r for r in ldr_refs if r["region"] == "EWRAM"]

    if not ewram_refs:
        print("WARNING: No EWRAM references found in the scanned range!")
        print("This might mean DoBattleIntro is at a different address or the scan range is too small.")
        return

    print(f"Found {len(ewram_refs)} EWRAM reference(s). Analyzing access patterns...")
    print()

    for ref in ewram_refs:
        print(f"--- EWRAM candidate: 0x{ref['value']:08X} loaded at +0x{ref['offset']:03X} into R{ref['reg']} ---")

        # Look for LDR/LDRB/LDRH with offset 0x58 in the next ~40 bytes after this LDR
        # The register might be dereferenced first (LDR Rn, [Rn]) then offset accessed
        search_start = ref["offset"] + 2
        search_end = min(ref["offset"] + 60, SCAN_BYTES)

        found_058 = False
        for j in range(search_start, search_end, 2):
            if j + 1 >= len(data):
                break
            hw2 = struct.unpack_from("<H", data, j)[0]
            pc2 = DO_BATTLE_INTRO_ROM + j
            disasm2 = disasm_thumb_simple(hw2, pc2)

            # Check for any instruction referencing offset 0x58
            # LDRB Rd, [Rn, #0x58]: would be invalid since imm5 max = 31 for LDRB
            # So compiler likely uses ADD Rd, #0x58 then LDRB
            # Or LDR Rd, [Rn, #0x58]: imm5=0x58/4=0x16=22, valid!

            # LDR Rd, [Rn, #imm5*4]: offset = imm5*4, max = 31*4 = 124
            if (hw2 >> 11) == 0x0D:
                imm5 = (hw2 >> 6) & 0x1F
                if imm5 * 4 == TARGET_OFFSET:
                    print(f"  +0x{j:03X}: {disasm2}  *** OFFSET 0x{TARGET_OFFSET:02X} ACCESS (word) ***")
                    found_058 = True

            # LDRB Rd, [Rn, #imm5]: offset = imm5, max = 31
            if (hw2 >> 11) == 0x0F:
                imm5 = (hw2 >> 6) & 0x1F
                if imm5 == TARGET_OFFSET:
                    # imm5 max is 31, 0x58=88 > 31, so this won't match directly
                    print(f"  +0x{j:03X}: {disasm2}  *** OFFSET 0x{TARGET_OFFSET:02X} ACCESS (byte) ***")
                    found_058 = True

            # LDRH Rd, [Rn, #imm5*2]: offset = imm5*2, max = 31*2 = 62
            if (hw2 >> 11) == 0x11:
                imm5 = (hw2 >> 6) & 0x1F
                if imm5 * 2 == TARGET_OFFSET:
                    # 0x58 = 88 > 62, won't match
                    print(f"  +0x{j:03X}: {disasm2}  *** OFFSET 0x{TARGET_OFFSET:02X} ACCESS (halfword) ***")
                    found_058 = True

            # ADD Rd, #imm8 — could be adding 0x58 to the pointer
            if (hw2 >> 11) == 0x06:
                imm8 = hw2 & 0xFF
                if imm8 == TARGET_OFFSET:
                    print(f"  +0x{j:03X}: {disasm2}  *** ADD 0x{TARGET_OFFSET:02X} TO REGISTER ***")
                    found_058 = True

            # MOV Rd, #0x58
            if (hw2 >> 11) == 0x04:
                imm8 = hw2 & 0xFF
                if imm8 == TARGET_OFFSET:
                    print(f"  +0x{j:03X}: {disasm2}  *** MOV 0x{TARGET_OFFSET:02X} ***")
                    found_058 = True

        if not found_058:
            print(f"  (No direct 0x{TARGET_OFFSET:02X} offset access found in next 60 bytes)")
            print(f"  Note: 0x{TARGET_OFFSET:02X}={TARGET_OFFSET} exceeds LDRB imm5 max (31), compiler uses ADD+LDRB or LDR [Rn,#0x58/4]")

        print()

    # --- Pass 3: Full disassembly of first 300 bytes for context ---

    print()
    print("=" * 100)
    print("FULL DISASSEMBLY of first 300 bytes of DoBattleIntro:")
    print("=" * 100)
    print()

    for i in range(0, SCAN_BYTES, 2):
        if i + 1 >= len(data):
            break
        hw = struct.unpack_from("<H", data, i)[0]
        pc = DO_BATTLE_INTRO_ROM + i
        disasm = disasm_thumb_simple(hw, pc)

        # Mark interesting instructions
        marker = ""
        if (hw >> 11) == 0x09:  # LDR from literal pool
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            lit_addr = ((pc & ~2) + 4) + imm8 * 4
            lit_file = lit_addr & 0x01FFFFFF
            lit_local = lit_file - DO_BATTLE_INTRO_FILE
            if 0 <= lit_local < len(data) - 3:
                val = struct.unpack_from("<I", data, lit_local)[0]
                region = classify_address(val)
                if region == "EWRAM":
                    marker = f"  ; =0x{val:08X} **EWRAM**"
                else:
                    marker = f"  ; =0x{val:08X} ({region})"

        print(f"  0x{pc:08X} (+0x{i:03X}):  {hw:04X}  {disasm}{marker}")

    # --- Summary ---
    print()
    print("=" * 100)
    print("SUMMARY — gBattleStruct candidates (EWRAM pointers):")
    print("=" * 100)
    print()

    for ref in ewram_refs:
        print(f"  0x{ref['value']:08X}  (loaded at +0x{ref['offset']:03X} / ROM 0x{ref['rom_addr']:08X} into R{ref['reg']})")

    if ewram_refs:
        # The most likely candidate is an EWRAM pointer that:
        # 1. Is loaded early in the function
        # 2. Points to a struct (not a simple variable)
        # 3. Has offset 0x58 accessed nearby
        print()
        print("NOTE: gBattleStruct is a POINTER (it stores the address of the struct).")
        print("The value shown above is the ADDRESS OF THE POINTER, not the struct itself.")
        print("At runtime: *(uint32_t*)POINTER_ADDR = actual struct address in EWRAM.")
        print()
        print(f"To verify, check at runtime: mem:read32(candidate_addr) should give an EWRAM address,")
        print(f"and mem:read8(deref + 0x{TARGET_OFFSET:02X}) should be eventState.battleIntro.")


if __name__ == "__main__":
    main()
