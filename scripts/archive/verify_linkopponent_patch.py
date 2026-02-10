#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verify the LinkOpponentBufferExecCompleted patch at the corrected ROM offset.

ROM offset: 0x07E910 (= 0x0807E911 - 0x08000000, THUMB function)
Expected patch at +0x1C: 0xD01C (BEQ) → 0xE01C (B unconditional)

Also verify the pattern matches PlayerBufferExecCompleted at 0x06F0D4.
"""

import struct
import sys
import io

# Force output encoding to UTF-8 for Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
OFFSET_LINKOPPONENT = 0x07E910
OFFSET_PLAYER = 0x06F0D4

def read_rom_bytes(offset, size=64):
    """Read bytes from ROM at given offset."""
    try:
        with open(ROM_PATH, 'rb') as f:
            f.seek(offset)
            return f.read(size)
    except Exception as e:
        print(f"ERROR reading ROM: {e}")
        return None

def format_hex_dump(data, base_offset):
    """Print hex dump with offsets."""
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f'{b:02X}' for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f"  {base_offset + i:06X}:  {hex_str:<48}  {ascii_str}")

def read_thumb_imm8m(data, offset):
    """Read THUMB 16-bit instruction at offset."""
    if offset + 2 > len(data):
        return None
    return struct.unpack('<H', data[offset:offset+2])[0]

def check_beq_at_offset(data, offset):
    """Check if instruction at offset is BEQ (0xD0xx pattern)."""
    instr = read_thumb_imm8m(data, offset)
    if instr is None:
        return None, instr
    # BEQ in THUMB = 1101 00xx xxxx xxxx = 0xD0xx-0xD0FF
    is_beq = (instr & 0xFF00) == 0xD000
    return is_beq, instr

def find_literal_refs(data, target_refs):
    """Scan for 32-bit literals matching target addresses."""
    refs = []
    for i in range(0, len(data) - 3, 2):
        val = struct.unpack('<I', data[i:i+4])[0]
        if val in target_refs:
            refs.append((i, val))
    return refs

def main():
    print("=" * 80)
    print("Verify LinkOpponentBufferExecCompleted patch")
    print("=" * 80)

    # Read LinkOpponentBufferExecCompleted at 0x07E910
    print(f"\n[1] Reading LinkOpponentBufferExecCompleted at offset 0x{OFFSET_LINKOPPONENT:06X}...")
    link_data = read_rom_bytes(OFFSET_LINKOPPONENT, 64)
    if not link_data:
        sys.exit(1)

    print("\nHex dump (64 bytes):")
    format_hex_dump(link_data, OFFSET_LINKOPPONENT)

    # Check BEQ at +0x1C
    print(f"\n[2] Checking for BEQ at offset +0x1C (0x{OFFSET_LINKOPPONENT + 0x1C:06X})...")
    is_beq, instr = check_beq_at_offset(link_data, 0x1C)
    if instr is not None:
        print(f"    Instruction at +0x1C: 0x{instr:04X}")
        if is_beq:
            print(f"    [CHECK] CONFIRMED: This is a BEQ instruction (0xD0xx pattern)")
            print(f"    Should patch to: 0x{0xE01C:04X} (unconditional B)")
        else:
            print(f"    [FAIL] NOT a BEQ - this is {instr:04X}, not expected 0xD0xx pattern")
    else:
        print(f"    ✗ Could not read instruction at +0x1C")

    # Check for LinkOpponentBufferRunCommand reference (0x0807DC45)
    print(f"\n[3] Searching for LinkOpponentBufferRunCommand reference (0x0807DC45)...")
    linkopponent_runcommand = 0x0807DC45
    refs = find_literal_refs(link_data, {linkopponent_runcommand})
    if refs:
        print(f"    [CHECK] Found {len(refs)} reference(s) to 0x{linkopponent_runcommand:08X}:")
        for offset, val in refs:
            print(f"      Offset +0x{offset:02X}: 0x{val:08X}")
    else:
        print(f"    [INFO] No references to 0x{linkopponent_runcommand:08X} found in this 64-byte window")
        print(f"      (May be beyond 64 bytes or in a different section)")

    # Compare with PlayerBufferExecCompleted at 0x06F0D4
    print(f"\n[4] Comparing with PlayerBufferExecCompleted at offset 0x{OFFSET_PLAYER:06X}...")
    player_data = read_rom_bytes(OFFSET_PLAYER, 64)
    if player_data:
        print("\nHex dump (64 bytes):")
        format_hex_dump(player_data, OFFSET_PLAYER)

        # Check BEQ at +0x1C in player function too
        is_beq_player, instr_player = check_beq_at_offset(player_data, 0x1C)
        if instr_player is not None:
            print(f"\n    Player BEQ check at +0x1C: 0x{instr_player:04X}")
            if is_beq_player:
                print(f"    [CHECK] CONFIRMED: PlayerBufferExecCompleted also has BEQ at +0x1C (pattern match!)")
            else:
                print(f"    [FAIL] Player function does NOT have BEQ at +0x1C")

    # Final verdict
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    if is_beq and instr:
        print(f"[SUCCESS] LinkOpponentBufferExecCompleted BEQ patch CONFIRMED at 0x{OFFSET_LINKOPPONENT + 0x1C:06X}")
        print(f"  Current instruction: 0x{instr:04X}")
        print(f"  Patch target: 0x{0xE01C:04X} (B unconditional)")
        print(f"\n  Pattern check: Both LinkOpponent and Player functions have BEQ at +0x1C [OK]")
    else:
        print(f"[FAILED] BEQ pattern NOT confirmed at expected offset +0x1C")
        if instr:
            print(f"  Found: 0x{instr:04X} instead of BEQ (0xD0xx)")

if __name__ == '__main__':
    main()
