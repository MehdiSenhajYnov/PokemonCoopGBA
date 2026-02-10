#!/usr/bin/env python3
"""
Find BattleMainCB2 in Pokemon Run & Bun ROM.

BattleMainCB2 is a small function that calls exactly 5 functions in order:
  1. AnimateSprites    = 0x080069D0
  2. BuildOamBuffer    = 0x08006A1C
  3. RunTextPrinters   = 0x080C6F84
  4. UpdatePaletteFade = 0x080BF858
  5. RunTasks          = 0x08004788

It's a THUMB function: PUSH{LR}, 5x BL, POP{PC} = ~24 bytes.

Also analyzes the CB2_InitBattleInternal jump table to find state 18's handler.
"""

import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known function addresses (ROM addresses with THUMB bit cleared for comparison)
TARGETS = [
    0x080069D0,  # AnimateSprites
    0x08006A1C,  # BuildOamBuffer
    0x080C6F84,  # RunTextPrinters
    0x080BF858,  # UpdatePaletteFade
    0x08004788,  # RunTasks
]

TARGET_NAMES = [
    "AnimateSprites",
    "BuildOamBuffer",
    "RunTextPrinters",
    "UpdatePaletteFade",
    "RunTasks",
]

def read_rom(path):
    with open(path, "rb") as f:
        return f.read()

def decode_thumb_bl(hw1, hw2):
    """
    Decode a THUMB BL instruction pair.
    hw1 = first halfword (F000-F7FF range, upper bits of offset)
    hw2 = second halfword (F800-FFFF range for BL, lower bits)

    Returns the signed offset (to be added to PC+4 of hw1).
    """
    # BL encoding (ARMv4T):
    # hw1: 1111 0 Soo oooo oooo  (S = sign, o = offset[21:11])
    # hw2: 1111 1ooo oooo oooo  (o = offset[10:0])

    # Check prefixes
    if (hw1 & 0xF800) != 0xF000 and (hw1 & 0xF800) != 0xF400:
        return None
    if (hw2 & 0xF800) != 0xF800:
        return None

    # Extract fields
    s = (hw1 >> 10) & 1
    imm10 = hw1 & 0x3FF
    j1 = (hw2 >> 13) & 1
    j2 = (hw2 >> 11) & 1  # Wait - for ARMv4T BL, it's simpler
    imm11 = hw2 & 0x7FF

    # ARMv4T BL (not BLX): simpler encoding
    # offset = SignExtend(S:imm10:imm11:0, 23)
    offset = (s << 22) | (imm10 << 12) | (imm11 << 1)

    # Sign extend from 23 bits
    if s:
        offset |= 0xFF800000  # sign extend
        offset = offset - 0x100000000  # make negative in Python

    return offset

def find_bl_sequences(rom):
    """
    Scan the entire ROM for sequences of 5 consecutive BL instructions
    calling the target functions in order.
    """
    results = []
    rom_size = len(rom)

    # We're looking for THUMB code, so scan every 2 bytes
    # A BL is 4 bytes (2 halfwords), so 5 BLs = 20 bytes
    # With PUSH{LR} before and POP{PC} after, total ~24 bytes

    for offset in range(0, rom_size - 24, 2):
        # Try to decode 5 consecutive BL instructions starting here
        # First check if there might be a PUSH before this

        bl_targets = []
        pos = offset

        for i in range(5):
            if pos + 4 > rom_size:
                break
            hw1 = struct.unpack_from("<H", rom, pos)[0]
            hw2 = struct.unpack_from("<H", rom, pos + 2)[0]

            bl_offset = decode_thumb_bl(hw1, hw2)
            if bl_offset is None:
                break

            # PC is at pos + 4 (THUMB: PC = current instruction + 4)
            pc = 0x08000000 + pos + 4
            target = pc + bl_offset
            bl_targets.append(target)
            pos += 4

        if len(bl_targets) == 5:
            # Check if all 5 targets match
            match = True
            for i in range(5):
                # Clear THUMB bit for comparison
                expected = TARGETS[i] & 0xFFFFFFFE
                actual = bl_targets[i] & 0xFFFFFFFE
                if expected != actual:
                    match = False
                    break

            if match:
                func_addr = 0x08000000 + offset
                results.append((func_addr, bl_targets))

    return results

def analyze_jump_table(rom):
    """
    Analyze the CB2_InitBattleInternal jump table at 0x08036D44.
    19 entries x 4 bytes each. Read state 18's target.
    """
    print("\n" + "=" * 70)
    print("JUMP TABLE ANALYSIS: CB2_InitBattleInternal")
    print("=" * 70)

    jump_table_rom_offset = 0x00036D44
    num_states = 19

    print(f"\nJump table at ROM 0x{jump_table_rom_offset:08X} (0x{0x08000000 + jump_table_rom_offset:08X})")
    print(f"Number of states: {num_states}")
    print()

    for state in range(num_states):
        entry_offset = jump_table_rom_offset + state * 4
        if entry_offset + 4 > len(rom):
            print(f"  State {state:2d}: OUT OF BOUNDS")
            continue
        addr = struct.unpack_from("<I", rom, entry_offset)[0]
        # Mark states of interest
        marker = ""
        if state == 18:
            marker = " <-- LAST STATE (sets BattleMainCB2)"
        elif state == 0:
            marker = " <-- FIRST STATE"
        print(f"  State {state:2d}: 0x{addr:08X}{marker}")

    # Focus on state 18
    state18_offset = jump_table_rom_offset + 18 * 4
    state18_addr = struct.unpack_from("<I", rom, state18_offset)[0]
    state18_rom = (state18_addr & 0x01FFFFFF)  # strip 0x08 prefix and THUMB bit

    print(f"\n--- Disassembly of State 18 handler at 0x{state18_addr:08X} ---")
    print(f"    ROM offset: 0x{state18_rom:08X}")

    # Disassemble ~64 bytes of THUMB code from state 18 handler
    # Look for BL instructions (calls to SetMainCallback2, etc.)
    disasm_start = state18_rom & 0xFFFFFFFE  # align
    for i in range(0, 64, 2):
        pos = disasm_start + i
        if pos + 2 > len(rom):
            break
        hw = struct.unpack_from("<H", rom, pos)[0]
        rom_addr = 0x08000000 + pos

        # Check for BL first halfword
        if (hw & 0xF800) == 0xF000 or (hw & 0xF800) == 0xF400:
            if pos + 4 <= len(rom):
                hw2 = struct.unpack_from("<H", rom, pos + 2)[0]
                if (hw2 & 0xF800) == 0xF800:
                    bl_off = decode_thumb_bl(hw, hw2)
                    if bl_off is not None:
                        pc = rom_addr + 4
                        target = pc + bl_off
                        # Try to identify the target
                        target_name = ""
                        for j, t in enumerate(TARGETS):
                            if (target & 0xFFFFFFFE) == (t & 0xFFFFFFFE):
                                target_name = f" = {TARGET_NAMES[j]}"
                                break
                        # Check if target could be SetMainCallback2
                        # (we'll identify it by what it's called with)
                        print(f"  0x{rom_addr:08X}: BL 0x{target:08X}{target_name}")
                        i += 2  # skip second halfword (handled in next iteration naturally)
                        continue

        # Check for PUSH/POP
        if (hw & 0xFE00) == 0xB400:  # PUSH
            regs = []
            for bit in range(8):
                if hw & (1 << bit):
                    regs.append(f"R{bit}")
            if hw & 0x100:
                regs.append("LR")
            print(f"  0x{rom_addr:08X}: PUSH {{{', '.join(regs)}}}")
        elif (hw & 0xFE00) == 0xBC00:  # POP
            regs = []
            for bit in range(8):
                if hw & (1 << bit):
                    regs.append(f"R{bit}")
            if hw & 0x100:
                regs.append("PC")
            print(f"  0x{rom_addr:08X}: POP {{{', '.join(regs)}}}")
        elif hw == 0x4770:  # BX LR
            print(f"  0x{rom_addr:08X}: BX LR")
        elif (hw & 0xFF00) == 0x2000:  # MOV Rd, #imm8 (R0)
            imm = hw & 0xFF
            print(f"  0x{rom_addr:08X}: MOV R0, #0x{imm:02X} ({imm})")
        elif (hw & 0xFF00) == 0x2100:  # MOV R1, #imm8
            imm = hw & 0xFF
            print(f"  0x{rom_addr:08X}: MOV R1, #0x{imm:02X} ({imm})")
        elif (hw & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            # PC is aligned to 4 + 4
            pc_aligned = (rom_addr + 4) & 0xFFFFFFFC
            pool_addr = pc_aligned + imm
            pool_rom = pool_addr - 0x08000000
            if pool_rom + 4 <= len(rom):
                val = struct.unpack_from("<I", rom, pool_rom)[0]
                print(f"  0x{rom_addr:08X}: LDR R{rd}, [PC, #0x{imm:X}] ; =0x{val:08X}")
            else:
                print(f"  0x{rom_addr:08X}: LDR R{rd}, [PC, #0x{imm:X}]")
        elif (hw & 0xFFC0) == 0x4680:  # MOV R8-R15, Rn (high register)
            # MOV Rd, Rs where Rd is high
            h1 = (hw >> 7) & 1
            h2 = (hw >> 6) & 1
            rs = ((hw >> 3) & 7) | (h2 << 3)  # wait, different encoding
            # Actually: MOV Rd, Rm  where D:Rd = dest, Rm = source
            rm = (hw >> 3) & 0xF
            rd = (hw & 7) | (h1 << 3)
            print(f"  0x{rom_addr:08X}: MOV R{rd}, R{rm}")
        elif (hw & 0xFF00) == 0x4600 and (hw & 0x00C0) == 0x0000:
            # Generic high register ops
            print(f"  0x{rom_addr:08X}: 0x{hw:04X}")
        else:
            print(f"  0x{rom_addr:08X}: 0x{hw:04X}")

    return state18_addr

def scan_for_push_5bl_pop(rom):
    """
    Alternative scan: look for PUSH{LR} followed by exactly 5 BL instructions
    and then POP{PC}. This is the exact pattern of BattleMainCB2.
    """
    print("\n" + "=" * 70)
    print("ALTERNATIVE SCAN: PUSH{LR} + 5xBL + POP{PC} pattern")
    print("=" * 70)

    results = []
    rom_size = len(rom)

    for offset in range(0, rom_size - 26, 2):
        # Check for PUSH {LR} = 0xB500
        hw = struct.unpack_from("<H", rom, offset)[0]
        if hw != 0xB500:  # PUSH {LR} only
            continue

        # Now check for 5 consecutive BL instructions
        bl_targets = []
        pos = offset + 2
        valid = True

        for i in range(5):
            if pos + 4 > rom_size:
                valid = False
                break
            hw1 = struct.unpack_from("<H", rom, pos)[0]
            hw2 = struct.unpack_from("<H", rom, pos + 2)[0]

            bl_off = decode_thumb_bl(hw1, hw2)
            if bl_off is None:
                valid = False
                break

            pc = 0x08000000 + pos + 4
            target = pc + bl_off
            bl_targets.append(target)
            pos += 4

        if not valid or len(bl_targets) != 5:
            continue

        # Check for POP {PC} = 0xBD00
        if pos + 2 > rom_size:
            continue
        hw_pop = struct.unpack_from("<H", rom, pos)[0]
        if hw_pop != 0xBD00:
            continue

        func_addr = 0x08000000 + offset

        # Check if targets match our known functions
        all_match = True
        for i in range(5):
            expected = TARGETS[i] & 0xFFFFFFFE
            actual = bl_targets[i] & 0xFFFFFFFE
            if expected != actual:
                all_match = False
                break

        if all_match:
            results.append((func_addr, bl_targets, "EXACT MATCH"))
            print(f"\n  *** EXACT MATCH at 0x{func_addr:08X} ***")
            for i, t in enumerate(bl_targets):
                print(f"      BL #{i+1}: 0x{t:08X} = {TARGET_NAMES[i]}")
            print(f"      Total size: {pos + 2 - offset} bytes")
        else:
            # Print partial matches (at least 3 of 5 match) for debugging
            match_count = sum(1 for i in range(5) if (bl_targets[i] & 0xFFFFFFFE) == (TARGETS[i] & 0xFFFFFFFE))
            if match_count >= 3:
                results.append((func_addr, bl_targets, f"PARTIAL ({match_count}/5)"))
                print(f"\n  Partial match ({match_count}/5) at 0x{func_addr:08X}")
                for i, t in enumerate(bl_targets):
                    match_flag = "OK" if (t & 0xFFFFFFFE) == (TARGETS[i] & 0xFFFFFFFE) else "MISMATCH"
                    name = TARGET_NAMES[i] if match_flag == "OK" else "???"
                    print(f"      BL #{i+1}: 0x{t:08X} [{match_flag}] (expected 0x{TARGETS[i]:08X} {TARGET_NAMES[i]})")

    if not results:
        print("\n  No matches found with PUSH{LR}+5BL+POP{PC} pattern.")

    return results

def scan_bl_anywhere(rom):
    """
    Scan for any sequence of 5 BL instructions (not necessarily preceded by PUSH)
    that call our target functions in order.
    """
    print("\n" + "=" * 70)
    print("BROAD SCAN: Any 5 consecutive BL to target functions")
    print("=" * 70)

    results = find_bl_sequences(rom)

    if results:
        for func_addr, bl_targets in results:
            print(f"\n  Match at 0x{func_addr:08X}")
            for i, t in enumerate(bl_targets):
                print(f"    BL #{i+1}: 0x{t:08X} = {TARGET_NAMES[i]}")

            # Check what's before and after
            rom_off = func_addr - 0x08000000
            if rom_off >= 2:
                hw_before = struct.unpack_from("<H", rom, rom_off - 2)[0]
                print(f"    Instruction before: 0x{hw_before:04X}", end="")
                if (hw_before & 0xFF00) == 0xB500:
                    print(" (PUSH {LR})")
                elif hw_before == 0xB500:
                    print(" (PUSH {LR})")
                else:
                    print()

            after_off = rom_off + 20  # 5 * 4 bytes
            if after_off + 2 <= len(rom):
                hw_after = struct.unpack_from("<H", rom, after_off)[0]
                print(f"    Instruction after:  0x{hw_after:04X}", end="")
                if hw_after == 0xBD00:
                    print(" (POP {PC})")
                else:
                    print()
    else:
        print("\n  No exact 5-BL sequence found.")

    return results

def find_references_to_address(rom, target_addr):
    """
    Find all BL instructions in the ROM that call target_addr.
    Also find literal pool references to target_addr.
    """
    results_bl = []
    results_ldr = []
    rom_size = len(rom)

    target_thumb = target_addr | 1  # THUMB bit set
    target_clean = target_addr & 0xFFFFFFFE

    # Find BL references
    for offset in range(0, rom_size - 4, 2):
        hw1 = struct.unpack_from("<H", rom, offset)[0]
        hw2 = struct.unpack_from("<H", rom, offset + 2)[0]

        bl_off = decode_thumb_bl(hw1, hw2)
        if bl_off is not None:
            pc = 0x08000000 + offset + 4
            bl_target = pc + bl_off
            if (bl_target & 0xFFFFFFFE) == target_clean:
                results_bl.append(0x08000000 + offset)

    # Find literal pool references
    for offset in range(0, rom_size - 4, 4):
        val = struct.unpack_from("<I", rom, offset)[0]
        if val == target_thumb or val == target_clean:
            results_ldr.append((0x08000000 + offset, val))

    return results_bl, results_ldr

def main():
    print("=" * 70)
    print("BattleMainCB2 Scanner for Pokemon Run & Bun")
    print("=" * 70)

    rom = read_rom(ROM_PATH)
    print(f"ROM loaded: {len(rom):,} bytes ({len(rom) / 1024 / 1024:.1f} MB)")

    # Method 1: Scan for PUSH{LR} + 5xBL + POP{PC}
    exact_results = scan_for_push_5bl_pop(rom)

    # Method 2: Broad scan for 5 consecutive BLs
    broad_results = scan_bl_anywhere(rom)

    # Method 3: Jump table analysis
    analyze_jump_table(rom)

    # If we found BattleMainCB2, find all references to it
    if exact_results:
        for func_addr, _, match_type in exact_results:
            if "EXACT" in match_type:
                print(f"\n{'=' * 70}")
                print(f"REFERENCES to BattleMainCB2 (0x{func_addr:08X})")
                print(f"{'=' * 70}")

                bl_refs, ldr_refs = find_references_to_address(rom, func_addr)

                print(f"\n  BL calls to 0x{func_addr:08X}: {len(bl_refs)}")
                for ref in bl_refs:
                    print(f"    0x{ref:08X}")

                print(f"\n  Literal pool refs to 0x{func_addr:08X}: {len(ldr_refs)}")
                for ref_addr, ref_val in ldr_refs:
                    print(f"    0x{ref_addr:08X}: 0x{ref_val:08X}")

                    # For each literal pool ref, find the LDR instruction that loads it
                    # LDR Rd, [PC, #imm] where PC+imm points to ref_addr
                    ref_rom = ref_addr - 0x08000000
                    # Search backwards for LDR instructions that could reference this pool entry
                    for search_off in range(max(0, ref_rom - 1024), ref_rom, 2):
                        hw = struct.unpack_from("<H", rom, search_off)[0]
                        if (hw & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
                            rd = (hw >> 8) & 7
                            imm = (hw & 0xFF) * 4
                            pc_aligned = (0x08000000 + search_off + 4) & 0xFFFFFFFC
                            pool_target = pc_aligned + imm
                            if pool_target == ref_addr:
                                instr_addr = 0x08000000 + search_off
                                print(f"      <- LDR R{rd}, [PC, ...] at 0x{instr_addr:08X}")

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")

    if exact_results:
        for func_addr, _, match_type in exact_results:
            if "EXACT" in match_type:
                thumb_addr = func_addr | 1
                print(f"\n  BattleMainCB2 = 0x{func_addr:08X} (THUMB: 0x{thumb_addr:08X})")
                print(f"  ROM offset:    0x{func_addr - 0x08000000:08X}")
    else:
        print("\n  BattleMainCB2 NOT FOUND via direct pattern matching.")
        print("  Check if function addresses are correct or if compiler reordered calls.")

if __name__ == "__main__":
    main()
