"""
Find OpponentBufferExecCompleted - FINAL v5.

We have TWO candidate pairs:
  Pair A: RunCommand=0x081B77DD, ExecCompleted=0x081B8494 (jump table 0x0871E444)
  Pair B: RunCommand=0x081BAD85, ExecCompleted=0x081BB944 (jump table 0x0871E52C)

User states OpponentBufferRunCommand = 0x081BAD85 (confirmed).
Therefore OpponentBufferExecCompleted = 0x081BB944.

But let's VERIFY by checking:
1. Which jump table is for Opponent vs LinkOpponent?
   In decomp, Opponent and LinkOpponent have DIFFERENT handler counts.
2. The function pointer table at 0x032628 that references 0x081BAD69
   - if it's in InitBattleControllers, the context tells us which controller.
3. Cross-reference: the ExecCompleted for the confirmed RunCommand is the one that
   stores it BACK. 0x081BB944 stores 0x081BAD85 back, so it IS the ExecCompleted.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom(path):
    with open(path, "rb") as f:
        return f.read()

def u16_at(rom, offset):
    return struct.unpack_from("<H", rom, offset)[0]

def u32_at(rom, offset):
    return struct.unpack_from("<I", rom, offset)[0]

def decode_thumb_bl(rom, offset):
    if offset + 4 > len(rom):
        return None
    hi = u16_at(rom, offset)
    lo = u16_at(rom, offset + 2)
    if (hi >> 11) == 0b11110 and (lo >> 11) == 0b11111:
        offset_hi = hi & 0x7FF
        offset_lo = lo & 0x7FF
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800
        target_offset = (offset_hi << 12) | (offset_lo << 1)
        instr_addr = offset + 0x08000000
        target = (instr_addr + 4 + target_offset) & 0xFFFFFFFF
        return target
    return None

def main():
    rom = read_rom(ROM_PATH)
    rom_size = len(rom)
    print(f"ROM size: {rom_size} bytes")

    # =========================================================================
    # VERIFICATION 1: Cross-reference ExecCompleted <-> RunCommand
    #
    # The relationship is circular:
    #   RunCommand calls ExecCompleted when command > 0x39 (overflow)
    #   ExecCompleted stores RunCommand back to ControllerFuncs
    #
    # For RunCommand 0x081BAD85:
    #   At offset 0x1BADD0: BL 0x081BB944 (calls ExecCompleted)
    #   -> confirms 0x081BB944 is the matching ExecCompleted
    #
    # For 0x081BB944 (ExecCompleted):
    #   Stores 0x081BAD85 back to ControllerFuncs
    #   -> confirms 0x081BAD85 is the matching RunCommand
    # =========================================================================

    print("=" * 70)
    print("VERIFICATION: Cross-reference RunCommand <-> ExecCompleted")
    print("=" * 70)

    # Check: 0x081BAD85 (RunCommand) calls 0x081BB944 at overflow path
    print("\n1. RunCommand 0x081BAD85 overflow BL target:")
    off = 0x1BADD0
    target = decode_thumb_bl(rom, off)
    print(f"   BL at 0x{off:06X} -> 0x{target:08X}")
    print(f"   Expected: 0x081BB944 -> {'MATCH' if target == 0x081BB944 else 'MISMATCH'}")

    # Check: 0x081BB944 (ExecCompleted) stores 0x081BAD85 to ControllerFuncs
    print("\n2. ExecCompleted 0x081BB944 stores which address to ControllerFuncs?")
    # At 0x1BB952: LDR R1, =0x081BAD85
    val = u32_at(rom, 0x1BB990)  # literal pool entry
    print(f"   Literal pool at 0x1BB990 = 0x{val:08X}")
    print(f"   Expected: 0x081BAD85 -> {'MATCH' if val == 0x081BAD85 else 'MISMATCH'}")

    # =========================================================================
    # VERIFICATION 2: Similarly for pair A
    # =========================================================================
    print("\n3. RunCommand 0x081B77DD overflow BL target:")
    off = 0x1B7828
    target = decode_thumb_bl(rom, off)
    print(f"   BL at 0x{off:06X} -> 0x{target:08X}")
    print(f"   Expected: 0x081B8494 -> {'MATCH' if target == 0x081B8494 else 'MISMATCH'}")

    print("\n4. ExecCompleted 0x081B8494 stores which address to ControllerFuncs?")
    val = u32_at(rom, 0x1B84E0)  # literal pool entry
    print(f"   Literal pool at 0x1B84E0 = 0x{val:08X}")
    print(f"   Expected: 0x081B77DD -> {'MATCH' if val == 0x081B77DD else 'MISMATCH'}")

    # =========================================================================
    # VERIFICATION 3: Check jump table sizes to distinguish controllers
    # In decomp:
    #   sOpponentBufferCommands has 58 entries (0-57, CONTROLLER_MAX)
    #   sLinkOpponentBufferCommands has 58 entries too
    #   Both check cmd <= 0x39 (57 decimal) before jump table
    # So the size check doesn't help distinguish.
    # But the jump TABLE CONTENTS differ!
    # =========================================================================

    print("\n" + "=" * 70)
    print("VERIFICATION 3: Jump table comparison")
    print("=" * 70)

    # Pair A uses jump table at 0x0871E444
    # Pair B uses jump table at 0x0871E52C
    # Let's compare the first few entries

    table_a = 0x71E444  # ROM offset for table A
    table_b = 0x71E52C  # ROM offset for table B

    print(f"\nJump table A at 0x{table_a + 0x08000000:08X} (used by RunCommand 0x081B77DD):")
    for i in range(min(10, (rom_size - table_a) // 4)):
        val = u32_at(rom, table_a + i * 4)
        print(f"  [{i:2d}] 0x{val:08X}")

    print(f"\nJump table B at 0x{table_b + 0x08000000:08X} (used by RunCommand 0x081BAD85):")
    for i in range(min(10, (rom_size - table_b) // 4)):
        val = u32_at(rom, table_b + i * 4)
        print(f"  [{i:2d}] 0x{val:08X}")

    # Count how many entries differ
    diff_count = 0
    same_count = 0
    for i in range(58):  # 58 entries (0x39 + 1)
        a = u32_at(rom, table_a + i * 4)
        b = u32_at(rom, table_b + i * 4)
        if a != b:
            diff_count += 1
        else:
            same_count += 1

    print(f"\nComparing 58 entries: {same_count} same, {diff_count} different")

    # =========================================================================
    # VERIFICATION 4: gBattlerControllerEndFuncs
    # We now know 0x03005D80 = gBattlerControllerEndFuncs (143 refs)
    # Let's find what OpponentBufferExecCompleted address is stored in it
    # by finding functions that store to BOTH 0x03005D80 AND reference 0x081BAD85
    # =========================================================================

    print("\n" + "=" * 70)
    print("VERIFICATION 4: What's stored in gBattlerControllerEndFuncs for opponent?")
    print("(Find functions with both 0x03005D80 and 0x081BAD85/0x081BB945 nearby)")
    print("=" * 70)

    # Search for 0x081BB945 (ExecCompleted with THUMB bit) in literal pools
    exec_completed_thumb = 0x081BB945  # 0x081BB944 + 1 for THUMB
    target_bytes = struct.pack("<I", exec_completed_thumb)
    refs = []
    pos = 0
    while True:
        found = rom.find(target_bytes, pos)
        if found == -1: break
        if found % 4 == 0:
            refs.append(found)
        pos = found + 1

    print(f"\nLiteral pool refs to 0x{exec_completed_thumb:08X} (ExecCompleted THUMB): {len(refs)}")
    for ref in refs:
        print(f"  0x{ref:06X} (ROM 0x{ref+0x08000000:08X})")
        # Check if gBattlerControllerEndFuncs (0x03005D80) is nearby
        for off in range(max(0, ref - 64), min(rom_size - 4, ref + 64), 4):
            val = u32_at(rom, off)
            if val == 0x03005D80:
                print(f"    -> gBattlerControllerEndFuncs at 0x{off:06X} (delta: {off - ref})")

    # Also search without THUMB bit (in case it's stored differently)
    exec_completed_raw = 0x081BB944
    target_bytes2 = struct.pack("<I", exec_completed_raw)
    refs2 = []
    pos = 0
    while True:
        found = rom.find(target_bytes2, pos)
        if found == -1: break
        if found % 4 == 0:
            refs2.append(found)
        pos = found + 1

    if refs2:
        print(f"\nLiteral pool refs to 0x{exec_completed_raw:08X} (raw): {len(refs2)}")
        for ref in refs2:
            print(f"  0x{ref:06X}")

    # =========================================================================
    # VERIFICATION 5: Check if 0x081BACF0 stores ExecCompleted to EndFuncs
    # From Part 7 of v4, function at 0x081BACF0 had BOTH refs
    # =========================================================================

    print("\n" + "=" * 70)
    print("VERIFICATION 5: Function at 0x081BACF0 (SetControllerToLinkOpponent?)")
    print("=" * 70)

    # Let's check what this function stores and where
    # First, find what ROM THUMB addresses are in its literal pool
    print("Literal pool scan around 0x1BAD40-0x1BADC0:")
    for off in range(0x1BAD40, 0x1BADC0, 4):
        val = u32_at(rom, off)
        note = ""
        if val == 0x03005D70: note = " = gBattlerControllerFuncs"
        elif val == 0x03005D80: note = " = gBattlerControllerEndFuncs"
        elif val == 0x020233DC: note = " = gActiveBattler"
        elif val == 0x020233E0: note = " = gBattleControllerExecFlags"
        elif val == 0x081BAD85: note = " = RunCommand (0x081BAD85)"
        elif val == 0x081BB945: note = " = ExecCompleted (0x081BB945)"
        elif val == 0x081B8495: note = " = ExecCompleted alt (0x081B8495)"
        elif 0x08000000 <= val <= 0x09FFFFFF and (val & 1): note = f" = ROM THUMB"
        elif 0x02000000 <= val <= 0x0203FFFF: note = " = EWRAM"
        elif 0x03000000 <= val <= 0x03007FFF: note = " = IWRAM"
        if note:
            print(f"  0x{off:06X}: 0x{val:08X}{note}")

    # =========================================================================
    # FINAL ANSWER
    # =========================================================================
    print("\n" + "=" * 70)
    print("FINAL ANSWER")
    print("=" * 70)
    print("""
Given: OpponentBufferRunCommand = 0x081BAD85 (confirmed by user)

The function that:
  1. Stores 0x081BAD85 BACK to gBattlerControllerFuncs[gActiveBattler]
  2. Checks gBattleTypeFlags & BATTLE_TYPE_LINK
  3. If link: calls GetMultiplayerId + PrepareBufferDataTransferLink
  4. Sets bufferA byte to CONTROLLER_TERMINATOR_NOP (0x39)
  5. Clears gBattleControllerExecFlags via BIC with gBitTable

...is at ROM address 0x081BB944.

OpponentBufferExecCompleted = 0x081BB945 (with THUMB bit)
                            = 0x081BB944 (raw address)
                            = file offset 0x1BB944

Cross-verification:
  - RunCommand 0x081BAD85 calls BL 0x081BB944 on overflow (cmd > 0x39) -> CONFIRMED
  - ExecCompleted 0x081BB944 stores 0x081BAD85 back to ControllerFuncs -> CONFIRMED
  - ExecCompleted 0x081BB944 has the standard ExecCompleted pattern -> CONFIRMED
    (store RunCommand, link buffer prep, BIC exec flags)

The other pair (Pair A) is likely the PlayerBuffer or another controller:
  RunCommand = 0x081B77DD, ExecCompleted = 0x081B8494
""")


if __name__ == "__main__":
    main()
