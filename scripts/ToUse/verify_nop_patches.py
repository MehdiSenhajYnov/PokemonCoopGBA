#!/usr/bin/env python3
"""
Verify HandleLinkBattleSetup NOP patch locations and TryReceiveLinkBattleData
call site in the Pokemon Run & Bun ROM.

HandleLinkBattleSetup is at ROM address 0x0803240C (THUMB).
TryReceiveLinkBattleData is at ROM address 0x08033448 (THUMB).

We verify three BL call sites:
  1. ROM offset 0x032494-0x032496 -> should BL to 0x0803240C
  2. ROM offset 0x036456-0x036458 -> should BL to 0x0803240C
  3. ROM offset 0x0007BC-0x0007BE -> should BL to 0x08033448
"""
import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# ─── THUMB BL decoder ──────────────────────────────────────────────
def decode_thumb_bl(hw1, hw2, pc):
    """
    Decode a THUMB BL (Branch with Link) instruction pair.

    THUMB BL is a 32-bit instruction encoded as two 16-bit halfwords:
      hw1 = 0xF000 | offset_hi[10:0]   (upper 11 bits, sign-extended)
      hw2 = 0xF800 | offset_lo[10:0]   (lower 11 bits)

    Target = (PC + 4) + sign_extend(offset_hi << 12) + (offset_lo << 1)
    PC = instruction address (the address of hw1)

    Returns target address or None if not a valid BL.
    """
    if (hw1 & 0xF800) != 0xF000:
        return None
    if (hw2 & 0xF800) not in (0xF800, 0xE800):
        return None

    offset_hi = hw1 & 0x07FF
    # Sign-extend the 11-bit offset_hi
    if offset_hi & 0x400:
        offset_hi |= 0xFFFFF800  # sign extend to 32-bit (Python int)

    offset_lo = hw2 & 0x07FF

    # Combine: target = (PC + 4) + (offset_hi << 12) + (offset_lo << 1)
    target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
    return target & 0xFFFFFFFF


def read_u16(rom, offset):
    return struct.unpack_from('<H', rom, offset)[0]


def read_u32(rom, offset):
    return struct.unpack_from('<I', rom, offset)[0]


def hex_dump_line(rom, offset, length):
    """Return hex dump string for `length` bytes at `offset`."""
    data = rom[offset:offset + length]
    return ' '.join(f'{b:02X}' for b in data)


def decode_thumb_instruction(rom, rom_offset):
    """Basic THUMB instruction decoder for context display."""
    hw = read_u16(rom, rom_offset)
    addr = 0x08000000 + rom_offset

    # Check for BL first (32-bit instruction)
    if rom_offset + 2 < len(rom):
        hw2 = read_u16(rom, rom_offset + 2)
        bl_target = decode_thumb_bl(hw, hw2, addr)
        if bl_target is not None:
            return f"BL 0x{bl_target:08X}", 4

    # Common THUMB instructions
    if hw == 0x46C0:
        return "NOP (MOV R8, R8)", 2
    elif (hw & 0xFF00) == 0xB500:
        return "PUSH {LR, ...}", 2
    elif (hw & 0xFF00) == 0xBD00:
        return "POP {PC, ...}", 2
    elif (hw & 0xF800) == 0x4800:
        rn = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        pool_addr = ((addr + 4) & ~3) + imm
        pool_offset = pool_addr - 0x08000000
        if 0 <= pool_offset < len(rom) - 4:
            pool_val = read_u32(rom, pool_offset)
            return f"LDR R{rn}, [PC, #0x{imm:X}] -> 0x{pool_val:08X}", 2
        return f"LDR R{rn}, [PC, #0x{imm:X}]", 2
    elif (hw & 0xF800) == 0x6800:
        rn = (hw >> 3) & 7
        rd = hw & 7
        imm = ((hw >> 6) & 0x1F) * 4
        return f"LDR R{rd}, [R{rn}, #0x{imm:X}]", 2
    elif (hw & 0xF800) == 0x6000:
        rn = (hw >> 3) & 7
        rd = hw & 7
        imm = ((hw >> 6) & 0x1F) * 4
        return f"STR R{rd}, [R{rn}, #0x{imm:X}]", 2
    elif (hw & 0xF800) == 0x2000:
        rd = (hw >> 8) & 7
        imm = hw & 0xFF
        return f"MOVS R{rd}, #0x{imm:X}", 2
    elif hw == 0x4770:
        return "BX LR", 2
    elif (hw & 0xFF00) in range(0xD000, 0xDF00):
        cond = (hw >> 8) & 0xF
        offset = hw & 0xFF
        if offset & 0x80:
            offset -= 256
        cond_names = {0: "BEQ", 1: "BNE", 2: "BCS", 3: "BCC", 4: "BMI", 5: "BPL",
                      6: "BVS", 7: "BVC", 8: "BHI", 9: "BLS", 10: "BGE", 11: "BLT",
                      12: "BGT", 13: "BLE"}
        cname = cond_names.get(cond, f"B.cond{cond}")
        tgt = addr + 4 + offset * 2
        return f"{cname} 0x{tgt:08X}", 2
    elif (hw & 0xF800) == 0xE000:
        offset = hw & 0x07FF
        if offset & 0x400:
            offset -= 0x800
        tgt = addr + 4 + offset * 2
        return f"B 0x{tgt:08X}", 2

    return f"0x{hw:04X}", 2


# ─── Verification logic ───────────────────────────────────────────

def verify_bl_callsite(rom, name, rom_offset, expected_target):
    """
    Verify that the 4 bytes at rom_offset encode a THUMB BL to expected_target.

    rom_offset: offset into the ROM file (no 0x08000000 base)
    expected_target: full GBA address (e.g. 0x0803240C)
    """
    hw1 = read_u16(rom, rom_offset)
    hw2 = read_u16(rom, rom_offset + 2)
    pc = 0x08000000 + rom_offset  # GBA address of the instruction

    decoded_target = decode_thumb_bl(hw1, hw2, pc)

    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")
    print(f"  ROM offset:     0x{rom_offset:06X} - 0x{rom_offset + 3:06X}")
    print(f"  GBA address:    0x{pc:08X}")
    print(f"  Raw halfwords:  hw1=0x{hw1:04X}  hw2=0x{hw2:04X}")
    print(f"  Raw bytes:      {hex_dump_line(rom, rom_offset, 4)}")
    print()

    # Decode the BL
    if decoded_target is not None:
        # Clean comparison (strip THUMB bit)
        expected_clean = expected_target & ~1
        decoded_clean = decoded_target & ~1
        match = (decoded_clean == expected_clean)

        print(f"  Decoded as:     BL 0x{decoded_target:08X}")
        print(f"  Expected target: 0x{expected_target:08X}")
        print(f"  Match:          {'YES - VERIFIED' if match else 'NO - MISMATCH!'}")

        if not match:
            print(f"  WARNING: Decoded target 0x{decoded_target:08X} != expected 0x{expected_target:08X}")
    else:
        print(f"  Decoded as:     NOT A VALID BL INSTRUCTION")
        print(f"  Expected:       BL 0x{expected_target:08X}")
        print(f"  Match:          NO - NOT A BL!")
        # Show what it actually is
        desc, _ = decode_thumb_instruction(rom, rom_offset)
        print(f"  Actual insn:    {desc}")
        match = False

    # ─── Manual BL encoding verification ───
    print()
    print(f"  --- Manual BL Encoding Check ---")
    offset_hi_raw = hw1 & 0x07FF
    offset_lo_raw = hw2 & 0x07FF

    # Sign extend
    offset_hi_signed = offset_hi_raw
    if offset_hi_signed & 0x400:
        offset_hi_signed = offset_hi_signed - 0x800

    combined_offset = (offset_hi_signed << 12) | (offset_lo_raw << 1)
    computed_target = (pc + 4 + combined_offset) & 0xFFFFFFFF

    print(f"  offset_hi (raw 11 bits): 0x{offset_hi_raw:03X} (signed: {offset_hi_signed})")
    print(f"  offset_lo (raw 11 bits): 0x{offset_lo_raw:03X}")
    print(f"  offset_hi << 12:         0x{(offset_hi_signed << 12) & 0xFFFFFFFF:08X} ({offset_hi_signed << 12})")
    print(f"  offset_lo << 1:          0x{offset_lo_raw << 1:08X} ({offset_lo_raw << 1})")
    print(f"  Combined offset:         {combined_offset} (0x{combined_offset & 0xFFFFFFFF:08X})")
    print(f"  PC + 4:                  0x{(pc + 4):08X}")
    print(f"  Computed target:         0x{computed_target:08X}")

    # ─── Context: 32 bytes around the call site ───
    print()
    print(f"  --- Context (32 bytes around ROM 0x{rom_offset:06X}) ---")
    ctx_start = max(0, rom_offset - 16)
    ctx_end = min(len(rom), rom_offset + 4 + 16)

    i = ctx_start
    while i < ctx_end:
        addr = 0x08000000 + i
        desc, size = decode_thumb_instruction(rom, i)
        marker = ""
        if i == rom_offset:
            marker = "  <-- PATCH TARGET (hw1)"
        elif i == rom_offset + 2 and size == 2:
            marker = "  <-- PATCH TARGET (hw2)"

        raw = hex_dump_line(rom, i, size)
        print(f"    0x{i:06X} [{addr:08X}]: {raw:12s}  {desc}{marker}")
        i += size

    return match


def main():
    print(f"Reading ROM: {ROM_PATH}")
    try:
        with open(ROM_PATH, 'rb') as f:
            rom = f.read()
    except FileNotFoundError:
        print(f"ERROR: ROM file not found at {ROM_PATH}")
        sys.exit(1)

    print(f"ROM size: {len(rom):,} bytes ({len(rom) / 1024 / 1024:.1f} MB)")

    results = []

    # ─── 1. HandleLinkBattleSetup call site #1 ───
    # ROM offset 0x032494 (4 bytes: 0x032494-0x032497)
    r1 = verify_bl_callsite(
        rom,
        "HandleLinkBattleSetup call site #1",
        0x032494,
        0x0803240C
    )
    results.append(("HandleLinkBattleSetup call #1 @ 0x032494", r1))

    # ─── 2. HandleLinkBattleSetup call site #2 ───
    # ROM offset 0x036456 (4 bytes: 0x036456-0x036459)
    r2 = verify_bl_callsite(
        rom,
        "HandleLinkBattleSetup call site #2",
        0x036456,
        0x0803240C
    )
    results.append(("HandleLinkBattleSetup call #2 @ 0x036456", r2))

    # ─── 3. TryReceiveLinkBattleData call site ───
    # ROM offset 0x0007BC (4 bytes: 0x0007BC-0x0007BF)
    r3 = verify_bl_callsite(
        rom,
        "TryReceiveLinkBattleData call in VBlank",
        0x0007BC,
        0x08033448
    )
    results.append(("TryReceiveLinkBattleData call @ 0x0007BC", r3))

    # ─── NOP patch description ───
    print(f"\n{'=' * 70}")
    print(f"  NOP PATCH INSTRUCTIONS")
    print(f"{'=' * 70}")
    print()
    print("  To NOP these call sites, replace each 4-byte BL with two 2-byte NOPs:")
    print("    NOP = 0x46C0 (MOV R8, R8)")
    print()
    print("  HandleLinkBattleSetup call #1:")
    print("    Write 0x46C0 at ROM 0x032494 (replaces hw1)")
    print("    Write 0x46C0 at ROM 0x032496 (replaces hw2)")
    print()
    print("  HandleLinkBattleSetup call #2:")
    print("    Write 0x46C0 at ROM 0x036456 (replaces hw1)")
    print("    Write 0x46C0 at ROM 0x036458 (replaces hw2)")
    print()
    print("  TryReceiveLinkBattleData call:")
    print("    Write 0x46C0 at ROM 0x0007BC (replaces hw1)")
    print("    Write 0x46C0 at ROM 0x0007BE (replaces hw2)")

    # ─── Additional: find ALL callers of HandleLinkBattleSetup ───
    print(f"\n{'=' * 70}")
    print(f"  EXHAUSTIVE SEARCH: All BL calls to HandleLinkBattleSetup (0x0803240C)")
    print(f"{'=' * 70}")

    target_clean = 0x0803240C & ~1  # 0x0803240C (already even)
    found_callers = []
    search_end = min(len(rom), 0x01000000)  # 16 MB max

    i = 0
    while i < search_end - 4:
        hw1 = read_u16(rom, i)
        if (hw1 & 0xF800) == 0xF000:
            hw2 = read_u16(rom, i + 2)
            if (hw2 & 0xF800) in (0xF800, 0xE800):
                pc = 0x08000000 + i
                bl = decode_thumb_bl(hw1, hw2, pc)
                if bl is not None and (bl & ~1) == target_clean:
                    found_callers.append(i)
                i += 4
                continue
        i += 2

    print(f"\n  Found {len(found_callers)} BL calls to HandleLinkBattleSetup:")
    for off in found_callers:
        gba_addr = 0x08000000 + off
        hw1 = read_u16(rom, off)
        hw2 = read_u16(rom, off + 2)
        expected_1 = (off == 0x032494)
        expected_2 = (off == 0x036456)
        marker = ""
        if expected_1:
            marker = " <-- Call site #1 (expected)"
        elif expected_2:
            marker = " <-- Call site #2 (expected)"
        else:
            marker = " <-- UNEXPECTED CALLER!"
        print(f"    ROM 0x{off:06X} [0x{gba_addr:08X}]: 0x{hw1:04X} 0x{hw2:04X}{marker}")

    # Check if our expected offsets are in the list
    if 0x032494 not in found_callers:
        print(f"\n  WARNING: Expected call site #1 (0x032494) NOT FOUND in BL scan!")
    if 0x036456 not in found_callers:
        print(f"\n  WARNING: Expected call site #2 (0x036456) NOT FOUND in BL scan!")

    # ─── Additional: find ALL callers of TryReceiveLinkBattleData (0x08033448) ───
    print(f"\n{'=' * 70}")
    print(f"  EXHAUSTIVE SEARCH: All BL calls to TryReceiveLinkBattleData (0x08033448)")
    print(f"{'=' * 70}")

    target_clean2 = 0x08033448 & ~1
    found_callers2 = []

    i = 0
    while i < search_end - 4:
        hw1 = read_u16(rom, i)
        if (hw1 & 0xF800) == 0xF000:
            hw2 = read_u16(rom, i + 2)
            if (hw2 & 0xF800) in (0xF800, 0xE800):
                pc = 0x08000000 + i
                bl = decode_thumb_bl(hw1, hw2, pc)
                if bl is not None and (bl & ~1) == target_clean2:
                    found_callers2.append(i)
                i += 4
                continue
        i += 2

    print(f"\n  Found {len(found_callers2)} BL calls to TryReceiveLinkBattleData:")
    for off in found_callers2:
        gba_addr = 0x08000000 + off
        hw1 = read_u16(rom, off)
        hw2 = read_u16(rom, off + 2)
        expected_3 = (off == 0x0007BC)
        marker = ""
        if expected_3:
            marker = " <-- VBlank call site (expected)"
        else:
            marker = " <-- OTHER CALLER"
        print(f"    ROM 0x{off:06X} [0x{gba_addr:08X}]: 0x{hw1:04X} 0x{hw2:04X}{marker}")

    if 0x0007BC not in found_callers2:
        print(f"\n  WARNING: Expected VBlank call site (0x0007BC) NOT FOUND in BL scan!")

    # ─── Summary ───
    print(f"\n{'=' * 70}")
    print(f"  FINAL SUMMARY")
    print(f"{'=' * 70}")
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}")

    print()
    if all_pass:
        print("  All call sites verified successfully.")
        print("  The NOP patches at the specified offsets are correct.")
    else:
        print("  SOME CALL SITES DID NOT MATCH. Review the output above.")

    print()
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
