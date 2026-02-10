#!/usr/bin/env python3
"""
Check if CB2_HandleStartBattle or related battle init functions
reference gBlockReceivedStatus directly or call functions that do.
"""

import struct
from pathlib import Path

ROM_PATH = Path(r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba")

# Key addresses
GBRS_ADDRESS = 0x0300307C
CB2_INIT_BATTLE = 0x080363C1
CB2_INIT_BATTLE_INTERNAL = 0x0803648D
CB2_HANDLE_START_BATTLE = 0x08037B45
GET_BLOCK_RECEIVED_STATUS = 0x0800A599  # The function we patch

# The 3 functions that access GBRS directly
SET_BLOCK_RECEIVED_FLAG = 0x0800A5D1
RESET_BLOCK_RECEIVED_FLAGS = 0x0800A5FD
CLEAR_RECEIVED_BLOCK_STATUS = 0x0800A635

BATTLE_INIT_FUNCTIONS = [
    ("CB2_InitBattle", 0x080363C1, 204),
    ("CB2_InitBattleInternal", 0x0803648D, 4096),
    ("CB2_HandleStartBattle", 0x08037B45, 2048),
]

def read_rom():
    return ROM_PATH.read_bytes()

def check_literal_pool_refs(rom, func_name, func_addr, func_size, target_addr):
    """
    Check if a function contains a literal pool reference to target_addr.
    """
    rom_offset = (func_addr & 0x01FFFFFF) - 1
    end_offset = rom_offset + func_size

    target_bytes = struct.pack('<I', target_addr)
    refs = []

    for i in range(rom_offset, min(end_offset, len(rom) - 3), 4):
        if rom[i:i+4] == target_bytes:
            gba_addr = 0x08000000 + i
            refs.append((i, gba_addr))

    if refs:
        print(f"\n[!] {func_name} (0x{func_addr:08X}) contains literal pool ref to 0x{target_addr:08X}:")
        for rom_off, gba_addr in refs:
            print(f"    ROM offset: 0x{rom_off:08X}, GBA addr: 0x{gba_addr:08X}")
        return True
    return False

def find_bl_calls_in_function(rom, func_name, func_addr, func_size, target_funcs):
    """
    Find BL calls to any of target_funcs within a function.
    """
    rom_offset = (func_addr & 0x01FFFFFF) - 1
    end_offset = rom_offset + func_size

    calls = []

    for i in range(rom_offset, min(end_offset - 3, len(rom) - 3), 2):
        instr1 = struct.unpack('<H', rom[i:i+2])[0]
        instr2 = struct.unpack('<H', rom[i+2:i+4])[0]

        if (instr1 & 0xF800) == 0xF000 and (instr2 & 0xF800) == 0xF800:
            # BL instruction
            imm11_1 = instr1 & 0x7FF
            imm11_2 = instr2 & 0x7FF
            if imm11_1 & 0x400:
                imm11_1 |= 0xFFFFF800
            offset_val = (imm11_1 << 12) | (imm11_2 << 1)
            pc = 0x08000000 + i + 4
            bl_target = pc + offset_val

            for target_name, target_addr in target_funcs:
                if bl_target == target_addr:
                    caller_addr = 0x08000000 + i + 1
                    calls.append((caller_addr, target_name, target_addr))

    if calls:
        print(f"\n[!] {func_name} (0x{func_addr:08X}) calls functions that access GBRS:")
        for caller, target_name, target_addr in calls:
            print(f"    At 0x{caller:08X}: BL {target_name} (0x{target_addr:08X})")
        return True
    return False

def main():
    print("[*] Reading ROM...")
    rom = read_rom()

    print("\n" + "="*80)
    print("CHECKING BATTLE INIT FUNCTIONS FOR DIRECT GBRS ACCESS")
    print("="*80)

    direct_refs_found = False
    function_calls_found = False

    # Check for direct literal pool references to gBlockReceivedStatus
    print("\n1. Checking for direct literal pool references to gBlockReceivedStatus...")
    for func_name, func_addr, func_size in BATTLE_INIT_FUNCTIONS:
        if check_literal_pool_refs(rom, func_name, func_addr, func_size, GBRS_ADDRESS):
            direct_refs_found = True

    if not direct_refs_found:
        print("  [+] No direct literal pool references found.")

    # Check for calls to GetBlockReceivedStatus (which we patch)
    print("\n2. Checking for calls to GetBlockReceivedStatus (our patched function)...")
    for func_name, func_addr, func_size in BATTLE_INIT_FUNCTIONS:
        if find_bl_calls_in_function(rom, func_name, func_addr, func_size,
                                     [("GetBlockReceivedStatus", GET_BLOCK_RECEIVED_STATUS)]):
            print(f"    [+] {func_name} calls GetBlockReceivedStatus → SAFE (we patch this)")

    # Check for calls to the 3 functions that BYPASS our patch
    print("\n3. Checking for calls to functions that BYPASS our patch...")
    direct_access_funcs = [
        ("SetBlockReceivedFlag", SET_BLOCK_RECEIVED_FLAG),
        ("ResetBlockReceivedFlags", RESET_BLOCK_RECEIVED_FLAGS),
        ("ClearReceivedBlockStatus", CLEAR_RECEIVED_BLOCK_STATUS),
    ]

    for func_name, func_addr, func_size in BATTLE_INIT_FUNCTIONS:
        if find_bl_calls_in_function(rom, func_name, func_addr, func_size, direct_access_funcs):
            function_calls_found = True

    if not function_calls_found:
        print("  [+] No calls to direct-access functions found.")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    if direct_refs_found or function_calls_found:
        print("\n[!] POTENTIAL ISSUE DETECTED:")
        if direct_refs_found:
            print("  - Battle init functions contain DIRECT literal pool refs to gBlockReceivedStatus")
        if function_calls_found:
            print("  - Battle init functions call functions that BYPASS our GetBlockReceivedStatus patch")
        print("\n[!] These code paths will see 0x0F instead of GBA-PK's 0x0 or 0x03.")
        print("[!] This could cause different behavior than GBA-PK.")
        print("\n[?] Recommendation:")
        print("  - Follow GBA-PK's approach: write 0x0 first, then 0x03 at stage 4")
        print("  - OR: Verify these functions are NOT called during our battle init sequence")
    else:
        print("\n[+] NO ISSUES DETECTED:")
        print("  - Battle init functions do NOT directly access gBlockReceivedStatus")
        print("  - Battle init functions do NOT call functions that bypass our patch")
        print("  - All gBlockReceivedStatus reads go through GetBlockReceivedStatus (which we patch)")
        print("\n[+] Our approach (writing 0x0F immediately) is SAFE.")

if __name__ == '__main__':
    main()
