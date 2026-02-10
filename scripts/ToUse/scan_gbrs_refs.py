#!/usr/bin/env python3
"""
Scan ROM for direct references to gBlockReceivedStatus address.
Purpose: Determine if any ROM code reads gBlockReceivedStatus DIRECTLY (bypassing our patch).
"""

import struct
import sys

# From config/run_and_bun.lua
GBRS_ADDRESS = 0x0300307C  # IWRAM
GET_BLOCK_RECEIVED_STATUS_ROM = 0x0800A599  # ROM function we patch

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom():
    """Read entire ROM into memory."""
    with open(ROM_PATH, 'rb') as f:
        return f.read()

def find_literal_pool_refs(rom_data, target_addr):
    """
    Find all literal pool references to target_addr in ROM.
    ARM literal pools store 32-bit addresses aligned to 4 bytes.
    """
    refs = []
    target_bytes = struct.pack('<I', target_addr)

    # Search for 4-byte aligned references
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            rom_offset = i
            gba_addr = 0x08000000 + rom_offset
            refs.append((rom_offset, gba_addr))

    return refs

def disassemble_context(rom_data, rom_offset, context_bytes=64):
    """
    Print hex dump around the reference for manual inspection.
    """
    start = max(0, rom_offset - context_bytes)
    end = min(len(rom_data), rom_offset + context_bytes)

    print(f"  Context (±{context_bytes} bytes):")
    for i in range(start, end, 16):
        hex_str = ' '.join(f'{b:02X}' for b in rom_data[i:i+16])
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in rom_data[i:i+16])
        marker = ' <--' if i <= rom_offset < i+16 else ''
        print(f"    {i:08X}: {hex_str:<48} {ascii_str}{marker}")

def find_function_containing(rom_data, rom_offset):
    """
    Try to identify the function containing this literal pool reference.
    ARM functions typically start with a PUSH instruction and end with POP+BX.
    This is heuristic — not guaranteed to be accurate.
    """
    # Search backwards for common function prologue: PUSH {r4-r7, lr} or similar
    # Common patterns: B5xx, B4xx (PUSH), 47xx (BX LR), BDxx (POP)

    # Search up to 1KB backwards
    search_start = max(0, rom_offset - 1024)

    # Look for PUSH patterns (B5xx, B4xx)
    for i in range(rom_offset - 2, search_start, -2):
        thumb_instr = struct.unpack('<H', rom_data[i:i+2])[0]
        if (thumb_instr & 0xFE00) == 0xB400:  # PUSH
            func_start = i
            func_addr = 0x08000000 + func_start + 1  # +1 for Thumb
            return func_start, func_addr

    return None, None

def main():
    print(f"[*] Reading ROM: {ROM_PATH}")
    rom_data = read_rom()
    print(f"[*] ROM size: {len(rom_data)} bytes ({len(rom_data)//1024//1024} MB)")

    print(f"\n[*] Searching for literal pool references to gBlockReceivedStatus (0x{GBRS_ADDRESS:08X})...")
    refs = find_literal_pool_refs(rom_data, GBRS_ADDRESS)

    print(f"\n[+] Found {len(refs)} literal pool references:\n")

    for rom_offset, gba_addr in refs:
        print(f"  ROM offset: 0x{rom_offset:08X}")
        print(f"  GBA address: 0x{gba_addr:08X}")

        # Try to find containing function
        func_start, func_addr = find_function_containing(rom_data, rom_offset)
        if func_addr:
            print(f"  Likely function start: 0x{func_addr:08X}")
            if func_addr == GET_BLOCK_RECEIVED_STATUS_ROM:
                print(f"    -> THIS IS GetBlockReceivedStatus() itself (PATCHED)")
        else:
            print(f"  Could not identify containing function")

        disassemble_context(rom_data, rom_offset, context_bytes=48)
        print()

    # Summary
    print(f"\n[*] Summary:")
    print(f"  Total literal pool references: {len(refs)}")
    print(f"  GetBlockReceivedStatus() ROM addr: 0x{GET_BLOCK_RECEIVED_STATUS_ROM:08X}")
    print(f"\n[*] Analysis:")
    print(f"  - If refs found ONLY in GetBlockReceivedStatus(): SAFE (patch covers all access)")
    print(f"  - If refs found in OTHER functions: RISKY (direct reads bypass patch)")
    print(f"  - Functions reading gBlockReceivedStatus directly will see 0x0F instead of GBA-PK's 0x0/0x03")

    # Check if any refs are NOT in GetBlockReceivedStatus
    non_patched_refs = []
    for rom_offset, gba_addr in refs:
        func_start, func_addr = find_function_containing(rom_data, rom_offset)
        if func_addr and func_addr != GET_BLOCK_RECEIVED_STATUS_ROM:
            non_patched_refs.append((rom_offset, gba_addr, func_addr))

    if non_patched_refs:
        print(f"\n[!] WARNING: Found {len(non_patched_refs)} references in OTHER functions:")
        for rom_offset, gba_addr, func_addr in non_patched_refs:
            print(f"  - 0x{gba_addr:08X} (in function at 0x{func_addr:08X})")
        print(f"\n[!] These functions may read gBlockReceivedStatus DIRECTLY, bypassing our patch!")
        print(f"[!] They will see 0x0F when GBA-PK would set 0x0 or 0x03.")
    else:
        print(f"\n[+] All references appear to be in GetBlockReceivedStatus() itself.")
        print(f"[+] Our patch should cover all ROM access to gBlockReceivedStatus.")

if __name__ == '__main__':
    main()
