#!/usr/bin/env python3
"""
FINAL approach: Find SetUpBattleVarsAndBirchZigzagoon by its unique behavior:
- Stores a function pointer to gBattleMainFunc (known at 0x02023A3C from disasm)
- Has a loop that stores BattleControllerDummy to gBattlerControllerFuncs
- Then calls HandleLinkBattleSetup
- Then stores 0 to gBattleControllerExecFlags

Alternative approach: In the decomp, SetUpBattleVarsAndBirchZigzagoon is declared
in battle_controllers.c right after HandleLinkBattleSetup. In the ROM, functions
from the same .c file tend to be laid out contiguously.

Also: Let's find the EXACT gTasks address for R&B (might not be 0x03005E00).
From the expansion decomp, gTasks is declared in task.c.
"""
import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_bl(hw1, hw2, pc):
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) in (0xF800, 0xE800):
        offset_hi = hw1 & 0x07FF
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800
        offset_lo = hw2 & 0x07FF
        target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
        return target & 0xFFFFFFFF
    return None

def main():
    rom = read_rom()

    # From the disasm, we see the big function at 0x06F1D8 uses these addresses:
    # 0x02023A18 = gBattleResources
    # 0x020233DC = gActiveBattler
    # 0x030022C0 = gMain
    # 0x03005DA0 = some pointer
    # 0x02023A3C = gBattleMainFunc
    # 0x02023A1C = some battle global

    # The key insight: In expansion, the compiler may have inlined SetUpBattleVars.
    # If so, HandleLinkBattleSetup would either also be inlined, or be a separate call.
    #
    # From the decomp (battle_controllers.c:56-67):
    # void HandleLinkBattleSetup(void)
    # {
    #     if (gBattleTypeFlags & BATTLE_TYPE_LINK)
    #     {
    #         if (gWirelessCommType)
    #             SetWirelessCommType1();
    #         if (!gReceivedRemoteLinkPlayers)
    #             OpenLink();
    #         CreateTask(Task_WaitForLinkPlayerConnection, 0);
    #         CreateTasksForSendRecvLinkBuffers();
    #     }
    # }
    #
    # The function checks gBattleTypeFlags (0x02023364) for bit 1.
    # If set, it:
    #   - checks gWirelessCommType (0x030030FC)
    #   - calls SetWirelessCommType1
    #   - checks gReceivedRemoteLinkPlayers (0x03003124)
    #   - calls OpenLink
    #   - calls CreateTask with Task_WaitForLinkPlayerConnection
    #   - calls CreateTasksForSendRecvLinkBuffers

    # Let's find this by searching for a contiguous region with references to:
    # gBattleTypeFlags (0x02023364) AND gWirelessCommType (0x030030FC) AND gReceivedRemoteLinkPlayers (0x03003124)

    print("=== Finding HandleLinkBattleSetup by multi-reference signature ===")
    print("  Searching for region with all 3: gBattleTypeFlags, gWirelessCommType, gReceivedRemoteLinkPlayers\n")

    btf = struct.pack("<I", 0x02023364)
    gwc = struct.pack("<I", 0x030030FC)
    grlp = struct.pack("<I", 0x03003124)

    # Find all gBattleTypeFlags locations
    btf_locs = []
    pos = 0
    while True:
        idx = rom.find(btf, pos, 0x02000000)
        if idx == -1:
            break
        btf_locs.append(idx)
        pos = idx + 4

    print(f"  gBattleTypeFlags literals: {len(btf_locs)}")

    # For each, check if gWirelessCommType and gReceivedRemoteLinkPlayers are within 200 bytes
    for btf_loc in btf_locs:
        region_start = max(0, btf_loc - 200)
        region_end = min(len(rom), btf_loc + 200)
        region = rom[region_start:region_end]

        has_gwc = gwc in region
        has_grlp = grlp in region

        if has_gwc and has_grlp:
            gwc_idx = region.find(gwc) + region_start
            grlp_idx = region.find(grlp) + region_start

            print(f"  MATCH at region around ROM 0x{btf_loc:06X}:")
            print(f"    gBattleTypeFlags at 0x{btf_loc:06X}")
            print(f"    gWirelessCommType at 0x{gwc_idx:06X}")
            print(f"    gReceivedRemoteLinkPlayers at 0x{grlp_idx:06X}")

            # Find the function containing this literal pool
            min_loc = min(btf_loc, gwc_idx, grlp_idx)
            max_loc = max(btf_loc, gwc_idx, grlp_idx)

            # Search backward from earliest literal for PUSH
            for back in range(4, 400, 2):
                if min_loc - back < 0:
                    break
                hw = struct.unpack_from("<H", rom, min_loc - back)[0]
                if (hw & 0xFF00) == 0xB500 or (hw & 0xFE00) == 0xB400:
                    func_start = min_loc - back
                    func_addr = 0x08000000 + func_start
                    func_end_estimate = max_loc + 8

                    print(f"    Function at ROM 0x{func_start:06X} (0x{func_addr:08X})")
                    print(f"    Estimated size: ~{func_end_estimate - func_start} bytes")

                    # Find all BL calls in this function
                    print(f"    BL calls:")
                    j = 0
                    while j < func_end_estimate - func_start + 50:
                        if func_start + j + 4 > len(rom):
                            break
                        h1 = struct.unpack_from("<H", rom, func_start + j)[0]
                        h2 = struct.unpack_from("<H", rom, func_start + j + 2)[0]
                        fpc = 0x08000000 + func_start + j
                        fbl = decode_bl(h1, h2, fpc)
                        if fbl is not None:
                            print(f"      +0x{j:03X}: BL 0x{fbl:08X}")
                            j += 4
                        else:
                            # Check for POP PC / BX LR
                            if j > 20 and ((h1 & 0xFF00) == 0xBD00 or h1 == 0x4770):
                                if h1 != 0x4770:
                                    print(f"      +0x{j:03X}: POP {{PC}} (function end)")
                                else:
                                    print(f"      +0x{j:03X}: BX LR (function end)")
                                break
                            j += 2

                    # Find callers
                    print(f"    Callers:")
                    # Search 0x060000-0x0A0000 for calls to this function
                    ci = 0x060000
                    while ci < 0x0A0000:
                        ch1 = struct.unpack_from("<H", rom, ci)[0]
                        ch2 = struct.unpack_from("<H", rom, ci + 2)[0]
                        cpc = 0x08000000 + ci
                        cbl = decode_bl(ch1, ch2, cpc)
                        if cbl is not None:
                            if (cbl & ~1) == (func_addr & ~1):
                                offset_in_caller = ci - 0x06F1D8
                                print(f"      ROM 0x{ci:06X} (0x{cpc:08X}) [InitBattleControllers+0x{offset_in_caller:03X}]")
                            ci += 4
                        else:
                            ci += 2
                    break

            print()

    # Also: Let's just look at ALL BL targets called from InitBattleControllers
    # and find which one has the HandleLinkBattleSetup signature
    print("\n=== All BL calls from InitBattleControllers (0x06F1D8 - 0x06F600) ===")
    i = 0x06F1D8
    end = 0x06F600
    bl_targets = {}
    while i < end:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        if (hw1 & 0xF800) == 0xF000:
            hw2 = struct.unpack_from("<H", rom, i + 2)[0]
            pc = 0x08000000 + i
            bl = decode_bl(hw1, hw2, pc)
            if bl is not None:
                offset = i - 0x06F1D8
                if bl not in bl_targets:
                    bl_targets[bl] = []
                bl_targets[bl].append(offset)
                i += 4
                continue
        i += 2

    print(f"\n  Unique targets: {len(bl_targets)}")
    for target, offsets in sorted(bl_targets.items()):
        off_str = ", ".join(f"+0x{o:03X}" for o in offsets)
        # Check what each target references in its literal pool (first 200 bytes)
        t_offset = (target & ~1) - 0x08000000
        if t_offset < 0 or t_offset >= len(rom):
            continue
        refs = []
        KEY_ADDRS = {
            0x02023364: "gBattleTypeFlags",
            0x020233E0: "gExecFlags",
            0x03003124: "gRecvRemoteLinkPlayers",
            0x030030FC: "gWirelessCommType",
            0x02023A3C: "gBattleMainFunc",
            0x03005D70: "gBattlerCtrlFuncs",
            0x020233DC: "gActiveBattler",
        }
        for k in range(t_offset, min(t_offset + 200, len(rom) - 4), 4):
            val = struct.unpack_from("<I", rom, k)[0]
            if val in KEY_ADDRS:
                refs.append(KEY_ADDRS[val])
        ref_str = f" [{', '.join(refs)}]" if refs else ""
        print(f"  0x{target:08X} at {off_str}{ref_str}")

if __name__ == "__main__":
    main()
