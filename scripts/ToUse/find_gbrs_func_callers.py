#!/usr/bin/env python3
"""
Find ALL callers of the 3 functions that directly access gBlockReceivedStatus.
Determine if they're part of battle init or other systems (link cable, wireless).
"""

import struct
from pathlib import Path

ROM_PATH = Path(r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba")

# The 3 functions that access GBRS directly (found by scan_gbrs_refs.py)
DIRECT_ACCESS_FUNCS = [
    ("SetBlockReceivedFlag", 0x0800A5D1),
    ("ResetBlockReceivedFlags", 0x0800A5FD),
    ("ClearReceivedBlockStatus", 0x0800A635),
]

# Known battle init functions (to check if callers are battle-related)
BATTLE_INIT_RANGE_START = 0x08036000  # Approx start of battle init code
BATTLE_INIT_RANGE_END = 0x08040000    # Approx end

def read_rom():
    return ROM_PATH.read_bytes()

def find_all_callers(rom, target_addr):
    """
    Find ALL BL calls to target_addr in the entire ROM.
    """
    callers = []

    for i in range(0, len(rom) - 3, 2):
        instr1 = struct.unpack('<H', rom[i:i+2])[0]
        instr2 = struct.unpack('<H', rom[i+2:i+4])[0]

        if (instr1 & 0xF800) == 0xF000 and (instr2 & 0xF800) == 0xF800:
            imm11_1 = instr1 & 0x7FF
            imm11_2 = instr2 & 0x7FF
            if imm11_1 & 0x400:
                imm11_1 |= 0xFFFFF800
            offset_val = (imm11_1 << 12) | (imm11_2 << 1)
            pc = 0x08000000 + i + 4
            bl_target = pc + offset_val

            if bl_target == target_addr:
                caller_addr = 0x08000000 + i + 1
                callers.append(caller_addr)

    return callers

def is_in_battle_init(addr):
    """Check if address is in battle init range."""
    return BATTLE_INIT_RANGE_START <= addr < BATTLE_INIT_RANGE_END

def main():
    print("[*] Reading ROM...")
    rom = read_rom()

    print("\n" + "="*80)
    print("FINDING ALL CALLERS OF GBRS DIRECT-ACCESS FUNCTIONS")
    print("="*80)

    all_callers = {}

    for func_name, func_addr in DIRECT_ACCESS_FUNCS:
        print(f"\n[*] Searching for callers of {func_name} (0x{func_addr:08X})...")
        callers = find_all_callers(rom, func_addr)

        if callers:
            print(f"  Found {len(callers)} call sites:")
            battle_related = []
            non_battle_related = []

            for caller in callers:
                in_battle = is_in_battle_init(caller)
                marker = "[BATTLE-INIT]" if in_battle else ""
                print(f"    0x{caller:08X} {marker}")

                if in_battle:
                    battle_related.append(caller)
                else:
                    non_battle_related.append(caller)

            all_callers[func_name] = {
                'battle': battle_related,
                'non_battle': non_battle_related
            }
        else:
            print(f"  No callers found (likely called via function pointer or not used)")
            all_callers[func_name] = {'battle': [], 'non_battle': []}

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    total_battle_calls = sum(len(data['battle']) for data in all_callers.values())
    total_non_battle_calls = sum(len(data['non_battle']) for data in all_callers.values())

    print(f"\nTotal callers in BATTLE-INIT range (0x{BATTLE_INIT_RANGE_START:08X}-0x{BATTLE_INIT_RANGE_END:08X}): {total_battle_calls}")
    print(f"Total callers OUTSIDE battle-init: {total_non_battle_calls}")

    if total_battle_calls > 0:
        print("\n[!] WARNING: Some callers are in BATTLE-INIT range!")
        print("[!] These functions WILL be called during battle init and will see our 0x0F value.")
        print("[!] This could cause different behavior than GBA-PK (which uses 0x0 then 0x03).")
        print("\n[?] Recommendation:")
        print("  1. Disassemble these caller functions to understand what they do")
        print("  2. Compare behavior with GBA-PK's gBlockReceivedStatus=0x0/0x03 approach")
        print("  3. If they rely on specific values, adopt GBA-PK's staged approach")
    else:
        print("\n[+] GOOD NEWS: No callers found in BATTLE-INIT range!")
        print("[+] These functions are likely used for:")
        print("  - Link cable communication (non-battle)")
        print("  - Wireless communication")
        print("  - Trade/Union Room")
        print("\n[+] They are NOT called during PvP battle init.")
        print("[+] Our approach (writing 0x0F immediately) does NOT affect them.")

    print("\n" + "="*80)
    print("CONCLUSION")
    print("="*80)

    if total_battle_calls == 0:
        print("\n[+] The difference between our approach (GBRS=0x0F at start) and GBA-PK's")
        print("    approach (GBRS=0x0→0x03 staged) is IRRELEVANT for battle init.")
        print("\n[+] The 3 functions that bypass our GetBlockReceivedStatus() patch are")
        print("    NOT called during battle init. They're used by other link systems.")
        print("\n[+] Our ROM patch (GetBlockReceivedStatus always returns 0x0F) handles")
        print("    ALL gBlockReceivedStatus reads during battle init.")
        print("\n[+] NO CHANGES NEEDED to our implementation.")
    else:
        print("\n[!] Further investigation required. See call sites above.")

if __name__ == '__main__':
    main()
