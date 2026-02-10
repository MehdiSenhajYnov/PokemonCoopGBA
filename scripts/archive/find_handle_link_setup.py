#!/usr/bin/env python3
"""
Find HandleLinkBattleSetup call in SetUpBattleVarsAndBirchZigzagoon for R&B.

Strategy:
1. We know SetUpBattleVarsAndBirchZigzagoon starts at 0x0806F1D9 (ROM offset 0x06F1D8)
2. Disassemble all BL instructions in the first 200 bytes
3. Each BL target: check if it references gBattleTypeFlags (0x02023364) AND
   gReceivedRemoteLinkPlayers (0x03003124) or OpenLink/CreateTask
4. Also check SetUpBattleVars by looking for the EXACT pattern:
   - After the init loop, there should be a BL that goes to HandleLinkBattleSetup
   - Then immediately: gBattleControllerExecFlags = 0 (store 0 to 0x020233E0)
"""

import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses
SETUP_BATTLE_VARS = 0x0806F1D8  # ROM addr (THUMB, so func entry at 0x0806F1D9)
SETUP_ROM_OFFSET = 0x06F1D8

# Key RAM addresses to look for in literal pools
KEY_ADDRS = {
    0x02023364: "gBattleTypeFlags",
    0x020233E0: "gBattleControllerExecFlags",
    0x03003124: "gReceivedRemoteLinkPlayers",
    0x030030FC: "gWirelessCommType",
    0x03005E00: "gTasks",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
}

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_bl(hw1, hw2, pc):
    """Decode a THUMB BL instruction pair. Returns target address or None."""
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) in (0xF800, 0xE800):
        offset_hi = hw1 & 0x07FF
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800  # sign extend
        offset_lo = hw2 & 0x07FF
        target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
        return target & 0xFFFFFFFF
    return None

def disasm_thumb_region(rom, rom_offset, length):
    """Disassemble THUMB code, finding all BL instructions."""
    results = []
    i = 0
    while i < length - 2:
        hw1 = struct.unpack_from("<H", rom, rom_offset + i)[0]
        if i + 2 < length:
            hw2 = struct.unpack_from("<H", rom, rom_offset + i + 2)[0]
            pc = 0x08000000 + rom_offset + i
            target = decode_bl(hw1, hw2, pc)
            if target is not None:
                results.append((i, pc, target, hw1, hw2))
                i += 4
                continue
        i += 2
    return results

def find_literal_pool_refs(rom, func_rom_offset, func_size):
    """Find 32-bit values in the literal pool area after the function."""
    refs = {}
    # Scan from func start to func start + 2*func_size to catch literal pool
    start = func_rom_offset
    end = min(start + func_size + 256, len(rom) - 4)
    for i in range(start, end, 4):
        val = struct.unpack_from("<I", rom, i)[0]
        if val in KEY_ADDRS:
            refs[val] = KEY_ADDRS[val]
    return refs

def analyze_bl_target(rom, target_addr):
    """Analyze a BL target function to see what it references."""
    if target_addr < 0x08000000 or target_addr >= 0x0A000000:
        return {}
    target_offset = (target_addr & ~1) - 0x08000000
    if target_offset >= len(rom):
        return {}
    # Scan 400 bytes for literal pool references
    return find_literal_pool_refs(rom, target_offset, 400)

def main():
    rom = read_rom()
    print(f"ROM size: {len(rom)} bytes")
    print(f"\n=== SetUpBattleVarsAndBirchZigzagoon at 0x{SETUP_BATTLE_VARS:08X} (ROM 0x{SETUP_ROM_OFFSET:06X}) ===\n")

    # Disassemble first 300 bytes of SetUpBattleVars
    bls = disasm_thumb_region(rom, SETUP_ROM_OFFSET, 300)

    print(f"Found {len(bls)} BL instructions:\n")

    handle_link_candidates = []

    for offset, pc, target, hw1, hw2 in bls:
        print(f"  +0x{offset:03X} (ROM 0x{SETUP_ROM_OFFSET+offset:06X}) [0x{hw1:04X} 0x{hw2:04X}]: BL 0x{target:08X}", end="")

        # Analyze what the target references
        refs = analyze_bl_target(rom, target)
        if refs:
            ref_names = ", ".join(refs.values())
            print(f" -> refs: {ref_names}", end="")

            # Check if this looks like HandleLinkBattleSetup
            if 0x02023364 in refs:  # gBattleTypeFlags
                handle_link_candidates.append((offset, pc, target, refs))
                print(" <- CANDIDATE (refs gBattleTypeFlags!)", end="")
            if 0x03003124 in refs:  # gReceivedRemoteLinkPlayers
                print(" <- STRONG CANDIDATE (refs gReceivedRemoteLinkPlayers!)", end="")

        print()

    # Also check: what's immediately after each BL? If it stores 0 to gBattleControllerExecFlags,
    # the BL before it is likely HandleLinkBattleSetup
    print("\n=== Checking instruction after each BL for 'store 0 to gBattleControllerExecFlags' pattern ===\n")

    for offset, pc, target, hw1, hw2 in bls:
        after_offset = SETUP_ROM_OFFSET + offset + 4
        if after_offset + 4 < len(rom):
            # Check next few instructions for a STR of 0 pattern
            # Typically: MOVS R0, #0 / STR R0, [Rn, #imm] or LDR Rn, =gBattleControllerExecFlags
            next_bytes = rom[after_offset:after_offset+16]
            for j in range(0, min(12, len(next_bytes)-2), 2):
                hw = struct.unpack_from("<H", next_bytes, j)[0]
                # MOVS Rd, #0 = 0x2000 | (Rd<<8)
                if hw & 0xFF00 == 0x2000 and hw & 0x00FF == 0x00:
                    print(f"  +0x{offset:03X}: BL 0x{target:08X} → followed by MOVS R{(hw>>8)&7}, #0 at +{j} bytes after")
                    # Check if next instruction after that is a STR
                    if j + 2 < len(next_bytes):
                        next_hw = struct.unpack_from("<H", next_bytes, j+2)[0]
                        # Check for STR or LDR for literal pool
                        print(f"           then 0x{next_hw:04X}")

    # Deep analysis of candidates
    if handle_link_candidates:
        print(f"\n=== Deep analysis of {len(handle_link_candidates)} HandleLinkBattleSetup candidate(s) ===\n")
        for offset, pc, target, refs in handle_link_candidates:
            target_offset = (target & ~1) - 0x08000000
            print(f"  Candidate at +0x{offset:03X} -> 0x{target:08X} (ROM 0x{target_offset:06X})")
            print(f"  References: {', '.join(refs.values())}")

            # Check its BL calls (sub-function calls)
            sub_bls = disasm_thumb_region(rom, target_offset, 200)
            print(f"  Sub-BL calls: {len(sub_bls)}")
            for so, spc, starget, shw1, shw2 in sub_bls:
                sub_refs = analyze_bl_target(rom, starget)
                ref_str = f" -> refs: {', '.join(sub_refs.values())}" if sub_refs else ""
                print(f"    +0x{so:03X}: BL 0x{starget:08X}{ref_str}")
    else:
        print("\n=== No candidates found via literal pool. Trying alternative: find BL whose target refs gReceivedRemoteLinkPlayers ===\n")
        # Broader search: check ALL BL targets for gReceivedRemoteLinkPlayers
        for offset, pc, target, hw1, hw2 in bls:
            refs = analyze_bl_target(rom, target)
            if 0x03003124 in refs or 0x030030FC in refs:
                print(f"  +0x{offset:03X}: BL 0x{target:08X} -> refs: {', '.join(refs.values())}")

    # ALSO: Direct approach - search for HandleLinkBattleSetup in ROM by signature
    print("\n=== Searching entire ROM for HandleLinkBattleSetup signature ===")
    print("  (function that: loads gBattleTypeFlags, tests bit 1, conditionally calls OpenLink/CreateTask)\n")

    # The function should start with:
    # LDR R0, =gBattleTypeFlags  ; load address 0x02023364
    # LDR R0, [R0]               ; load value
    # MOVS R1, #2                ; BATTLE_TYPE_LINK = bit 1
    # TST R0, R1                 ; test
    # BEQ .end                   ; skip if not link
    # ... calls to SetWirelessCommType1, OpenLink, CreateTask, CreateTasksForSendRecvLinkBuffers

    # Search for the pattern: somewhere in ROM that loads 0x02023364, then tests bit 1
    # Look for LDR Rn, [PC, #imm] pointing to literal pool with 0x02023364

    btf_bytes = struct.pack("<I", 0x02023364)
    pos = 0
    candidates = []
    while True:
        pos = rom.find(btf_bytes, pos)
        if pos == -1:
            break
        # This is a literal pool entry. Find LDR instructions pointing to it.
        # LDR Rn, [PC, #imm] = 0x4800 | (Rn<<8) | (imm/4)
        # PC-relative: actual address = (PC + 4) & ~3 + imm*4
        # So we need to search backwards for LDR instructions
        for back in range(4, 260, 2):  # search up to 256 bytes before
            if pos - back < 0:
                break
            hw = struct.unpack_from("<H", rom, pos - back)[0]
            if (hw & 0xF800) == 0x4800:  # LDR Rn, [PC, #imm]
                rn = (hw >> 8) & 7
                imm = (hw & 0xFF) * 4
                ldr_pc = 0x08000000 + (pos - back)
                ldr_target = ((ldr_pc + 4) & ~3) + imm
                actual_pool_addr = ldr_target - 0x08000000
                if actual_pool_addr == pos:
                    # This LDR loads gBattleTypeFlags!
                    func_start_estimate = pos - back
                    # Check if this is near the start of a function (PUSH instruction before)
                    for fb in range(0, 40, 2):
                        if func_start_estimate - fb < 0:
                            break
                        fhw = struct.unpack_from("<H", rom, func_start_estimate - fb)[0]
                        if (fhw & 0xFF00) == 0xB500 or (fhw & 0xFF00) == 0xB400 or (fhw & 0xFE00) == 0xB400:
                            # PUSH instruction found
                            real_start = func_start_estimate - fb
                            # Check size: HandleLinkBattleSetup is small (~30-50 bytes)
                            func_size = pos - real_start + 4  # rough estimate
                            if func_size < 100:  # small function
                                # Check if it has BL calls to CreateTask-like functions
                                func_bls = disasm_thumb_region(rom, real_start, func_size + 50)
                                if len(func_bls) >= 2:  # needs at least 2 BLs (CreateTask + CreateTasksFor...)
                                    rom_addr = 0x08000000 + real_start
                                    candidates.append((real_start, rom_addr, func_size, func_bls))
                            break
        pos += 4

    print(f"  Found {len(candidates)} small functions loading gBattleTypeFlags with 2+ BL calls:\n")
    for c_offset, c_addr, c_size, c_bls in candidates:
        print(f"  Function at ROM 0x{c_offset:06X} (0x{c_addr:08X}), ~{c_size} bytes, {len(c_bls)} BLs:")
        for so, spc, starget, shw1, shw2 in c_bls:
            sub_refs = analyze_bl_target(rom, starget)
            ref_str = f" -> {', '.join(sub_refs.values())}" if sub_refs else ""
            print(f"    +0x{so:03X}: BL 0x{starget:08X}{ref_str}")
        # Check if any BL target has gTasks reference (CreateTask uses gTasks)
        for so, spc, starget, shw1, shw2 in c_bls:
            sub_refs = analyze_bl_target(rom, starget)
            if 0x03005E00 in sub_refs:
                print(f"    ^^^ This BL target references gTasks — likely CreateTask!")

if __name__ == "__main__":
    main()
