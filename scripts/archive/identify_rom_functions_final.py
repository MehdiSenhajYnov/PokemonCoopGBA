"""
Final identification of the unknown controller functions.
Now we know they are CompleteOnBattlerSpriteCallbackDummy or CompleteOnBankSpriteCallbackDummy2.
These are identical functions from vanilla pokeemerald that check:
    gSprites[gBattlerSpriteIds[gActiveBattler]].callback == SpriteCallbackDummy
    -> if yes, call *BufferExecCompleted()

Let's check the sequential functions and verify the reference context.
"""
import struct
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

def read_rom(path):
    with open(path, "rb") as f:
        return f.read()


def find_bl_target(rom, func_offset, scan_bytes=40):
    """Find the BL target in a function."""
    for i in range(0, scan_bytes, 2):
        if func_offset + i + 3 >= len(rom):
            break
        hw = struct.unpack_from("<H", rom, func_offset + i)[0]
        if (hw >> 11) == 0b11110:
            hw2 = struct.unpack_from("<H", rom, func_offset + i + 2)[0]
            if (hw2 >> 11) == 0b11111:
                addr = func_offset + 0x08000000 + i
                offset11 = hw & 0x7FF
                offset_low = hw2 & 0x7FF
                if offset11 & 0x400:
                    offset11 |= ~0x7FF
                full_offset = (offset11 << 12) | (offset_low << 1)
                target = (addr + 4 + full_offset) & 0xFFFFFFFF
                return target
    return None


def main():
    rom = read_rom(ROM_PATH)

    print("="*70)
    print("DEFINITIVE IDENTIFICATION")
    print("="*70)
    print()
    print("Both functions are from vanilla pokeemerald's battle controller pattern:")
    print()
    print("  static void CompleteOnBattlerSpriteCallbackDummy(void) {")
    print("      if (gSprites[gBattlerSpriteIds[gActiveBattler]].callback == SpriteCallbackDummy)")
    print("          PlayerBufferExecCompleted();  // or LinkOpponentBufferExecCompleted()")
    print("  }")
    print()

    # Verified addresses:
    print("KEY FINDINGS:")
    print()
    print("0x08070BB5 (THUMB) = CompleteOnBattlerSpriteCallbackDummy (Player controller)")
    print("  - Located in battle_controller_player.c area")
    print("  - Calls PlayerBufferExecCompleted at 0x0806F0D4")
    print("  - Checks gSprites[gBattlerSpriteIds[gActiveBattler]].callback == SpriteCallbackDummy")
    print()
    print("0x0807DC99 (THUMB) = CompleteOnBattlerSpriteCallbackDummy (LinkOpponent controller)")
    print("  - Located in battle_controller_link_opponent.c area")
    print("  - Calls LinkOpponentBufferExecCompleted at 0x0807E910")
    print("  - Checks gSprites[gBattlerSpriteIds[gActiveBattler]].callback == SpriteCallbackDummy")
    print()

    # Verify the next function (0x08070BEC) is CompleteOnBankSpriteCallbackDummy2
    # which is identical to CompleteOnBattlerSpriteCallbackDummy
    next_func = 0x070BEC
    bl_target = find_bl_target(rom, next_func)
    print(f"Next function at 0x08070BEC: BL target = 0x{bl_target:08X}" if bl_target else "Not found")
    if bl_target:
        # Check if it's also calling PlayerBufferExecCompleted
        if (bl_target & ~1) == 0x0806F0D4:
            print("  -> Also calls PlayerBufferExecCompleted = CompleteOnBankSpriteCallbackDummy2 (Player)")

    # Also check 0x0807DCD0 (next after 0x0807DC98)
    next_func2 = 0x07DCD0
    bl_target2 = find_bl_target(rom, next_func2)
    print(f"Next function at 0x0807DCD0: BL target = 0x{bl_target2:08X}" if bl_target2 else "Not found")
    if bl_target2:
        if (bl_target2 & ~1) == 0x0807E910:
            print("  -> Also calls LinkOpponentBufferExecCompleted = CompleteOnBankSpriteCallbackDummy2 (LinkOpponent)")

    print()
    print("="*70)
    print("BONUS: Newly discovered addresses")
    print("="*70)
    print()
    print("0x08007441 (THUMB) = SpriteCallbackDummy (NOT CB2_LoadMap!)")
    print("  - Just 'BX LR' (empty function)")
    print("  - 0x08007440 in ROM: 0x4770 (BX LR)")
    print()
    print("0x02020630 = gSprites (array of struct Sprite, 65 entries * 68 bytes)")
    print("0x0202356C = gBattlerSpriteIds (u8[4])")
    print("0x020233DC = gActiveBattler (u8)")
    print()
    print("0x0806F0D4 = PlayerBufferExecCompleted")
    print("  - Sets gBattlerControllerFuncs[battler] = PlayerBufferRunCommand (0x0806F151)")
    print("  - Checks gBattleTypeFlags (0x02023364) & BATTLE_TYPE_LINK")
    print("  - If LINK: PrepareBufferDataTransferLink")
    print("  - Else: MarkBattleControllerIdleOnLocal via gBattleControllerExecFlags (0x020233E0)")
    print()
    print("0x0807E910 = LinkOpponentBufferExecCompleted")
    print("  - Sets gBattlerControllerFuncs[battler] = LinkOpponentBufferRunCommand (0x0807DC45)")
    print("  - Same LINK/local pattern as Player version")
    print()

    # Correct the CB2_LoadMap misidentification
    print("="*70)
    print("WARNING: CB2_LoadMap address needs correction!")
    print("="*70)
    print()
    print("CLAUDE.md states CB2_LoadMap = 0x08007441")
    print("But 0x08007441 is actually SpriteCallbackDummy (BX LR)")
    print()
    print("The real CB2_LoadMap needs to be re-identified.")
    print("Looking at the warp code: the function that triggers map load...")
    print()

    # Let's find the real CB2_LoadMap by searching for references to it
    # CB2_LoadMap should be referenced by SetCB2WarpAndLoadMap
    # It should be a function that does actual map loading work
    # The function at 0x08007444 (right after SpriteCallbackDummy) is a larger function
    # Let's check if THAT is relevant

    # Actually, looking back at the HAL code, CB2_LoadMap was used for warp detection
    # (checking callback2 == CB2_LoadMap to know when a map load is happening)
    # The address was probably correct in a different context.
    # Let me check what the warp code actually uses.

    # Search for 0x08007441 in the ROM to see all references
    needle = struct.pack("<I", 0x08007441)
    print(f"References to 0x08007441 (SpriteCallbackDummy) in ROM:")
    count = 0
    pos = 0
    while count < 20:
        idx = rom.find(needle, pos)
        if idx == -1:
            break
        rom_addr = idx + 0x08000000
        print(f"  ROM 0x{idx:06X} (addr 0x{rom_addr:08X})")
        pos = idx + 4
        count += 1
    print(f"  Total found: {count}+ references")


if __name__ == "__main__":
    main()
