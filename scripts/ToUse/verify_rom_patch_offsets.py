"""
Verify ROM patch offsets for Pokemon Run & Bun.
Reads the ROM file and checks the 2-byte values at each patch location.
"""
import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_u16(rom, offset):
    """Read a 16-bit little-endian value at the given offset."""
    return struct.unpack_from('<H', rom, offset)[0]

def hex_dump(rom, offset, length=16):
    """Return a hex dump of `length` bytes starting at `offset`."""
    data = rom[offset:offset+length]
    hex_str = ' '.join(f'{b:02X}' for b in data)
    return hex_str

def check_patch(rom, name, offset, expected_original, patch_value=None):
    """Check a single patch location."""
    actual = read_u16(rom, offset)
    status = "MATCH" if actual == expected_original else "MISMATCH"

    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"  ROM offset: 0x{offset:06X}")
    print(f"  Expected original: 0x{expected_original:04X}")
    print(f"  Actual value:      0x{actual:04X}  [{status}]")
    if patch_value is not None:
        print(f"  Patch target:      0x{patch_value:04X}")
        if actual == patch_value:
            print(f"  NOTE: Already patched!")

    # Context: 16 bytes before and after
    ctx_before_start = max(0, offset - 16)
    ctx_after_end = min(len(rom), offset + 2 + 16)

    print(f"\n  Context (16 bytes before offset 0x{offset:06X}):")
    print(f"    0x{ctx_before_start:06X}: {hex_dump(rom, ctx_before_start, offset - ctx_before_start)}")
    print(f"  * 0x{offset:06X}: {hex_dump(rom, offset, 2)}  <-- TARGET")
    print(f"  Context (16 bytes after):")
    print(f"    0x{offset+2:06X}: {hex_dump(rom, offset + 2, ctx_after_end - offset - 2)}")

def check_nop(rom, name, offset):
    """Check a NOP patch location (expected original is some instruction, patch = 0x46C0 NOP)."""
    actual = read_u16(rom, offset)
    print(f"\n  {name} @ 0x{offset:06X}: 0x{actual:04X}", end="")
    if actual == 0x46C0:
        print("  [ALREADY NOP'D]")
    else:
        print(f"  [ORIGINAL INSTRUCTION]")

def main():
    print(f"Reading ROM: {ROM_PATH}")
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()
    print(f"ROM size: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)")

    # =========================================================
    # 1. Three exec flag function patches (BEQ -> B)
    # =========================================================
    print("\n" + "=" * 60)
    print("  EXEC FLAG FUNCTION PATCHES (BEQ -> B)")
    print("=" * 60)

    check_patch(rom, "MarkBattlerForControllerExec (markBattlerExecLocal)",
                0x040F50, 0xD010, 0xE010)

    check_patch(rom, "IsBattlerMarkedForControllerExec (isBattlerExecLocal)",
                0x040EFC, 0xD00E, 0xE00E)

    check_patch(rom, "MarkAllBattlersForControllerExec (markAllBattlersExecLocal)",
                0x040E88, 0xD018, 0xE018)

    # =========================================================
    # 2. Buffer exec skip patches
    # =========================================================
    print("\n" + "=" * 60)
    print("  BUFFER EXEC SKIP PATCHES")
    print("=" * 60)

    check_patch(rom, "PlayerBufferExecCompleted skip (playerBufExecSkip)",
                0x06F0F0, 0xD01C, 0xE01C)

    check_patch(rom, "LinkOpponentBufferExecCompleted skip (linkOpponentBufExecSkip)",
                0x07E92C, 0xD01C, 0xE01C)

    check_patch(rom, "PrepareBufferDataTransferLink local (prepBufDataTransferLocal)",
                0x032FC0, 0xD008, 0xE008)

    # =========================================================
    # 3. NOP patches (HandleLinkBattleSetup + TryReceiveLinkBattleData)
    # =========================================================
    print("\n" + "=" * 60)
    print("  NOP PATCHES (HandleLinkBattleSetup)")
    print("=" * 60)

    for offset in [0x032494, 0x032496, 0x036456, 0x036458]:
        actual = read_u16(rom, offset)
        print(f"  0x{offset:06X}: 0x{actual:04X}", end="")
        if actual == 0x46C0:
            print("  [NOP]")
        else:
            # Decode THUMB instruction briefly
            print(f"  [ORIGINAL]")

    # Show context around HandleLinkBattleSetup patches
    print(f"\n  Context around 0x032494:")
    for i in range(-4, 6):
        off = 0x032494 + i * 2
        val = read_u16(rom, off)
        marker = " <--" if i == 0 or i == 1 else ""
        print(f"    0x{off:06X}: 0x{val:04X}{marker}")

    print(f"\n  Context around 0x036456:")
    for i in range(-4, 6):
        off = 0x036456 + i * 2
        val = read_u16(rom, off)
        marker = " <--" if i == 0 or i == 1 else ""
        print(f"    0x{off:06X}: 0x{val:04X}{marker}")

    print("\n" + "=" * 60)
    print("  NOP PATCHES (TryReceiveLinkBattleData in VBlank)")
    print("=" * 60)

    for offset in [0x0007BC, 0x0007BE]:
        actual = read_u16(rom, offset)
        print(f"  0x{offset:06X}: 0x{actual:04X}", end="")
        if actual == 0x46C0:
            print("  [NOP]")
        else:
            print(f"  [ORIGINAL]")

    # Show context
    print(f"\n  Context around 0x0007BC:")
    for i in range(-4, 6):
        off = 0x0007BC + i * 2
        val = read_u16(rom, off)
        marker = " <--" if i == 0 or i == 1 else ""
        print(f"    0x{off:06X}: 0x{val:04X}{marker}")

    # =========================================================
    # Summary
    # =========================================================
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)

    all_patches = [
        ("markBattlerExecLocal", 0x040F50, 0xD010, 0xE010),
        ("isBattlerExecLocal", 0x040EFC, 0xD00E, 0xE00E),
        ("markAllBattlersExecLocal", 0x040E88, 0xD018, 0xE018),
        ("playerBufExecSkip", 0x06F0F0, 0xD01C, 0xE01C),
        ("linkOpponentBufExecSkip", 0x07E92C, 0xD01C, 0xE01C),
        ("prepBufDataTransferLocal", 0x032FC0, 0xD008, 0xE008),
    ]

    nop_patches = [
        ("HandleLinkBattleSetup call 1a", 0x032494),
        ("HandleLinkBattleSetup call 1b", 0x032496),
        ("HandleLinkBattleSetup call 2a", 0x036456),
        ("HandleLinkBattleSetup call 2b", 0x036458),
        ("TryReceiveLinkBattleData call 1a", 0x0007BC),
        ("TryReceiveLinkBattleData call 1b", 0x0007BE),
    ]

    print(f"\n  {'Patch Name':<40} {'Offset':>8} {'Expected':>10} {'Actual':>10} {'Status':>10}")
    print(f"  {'-'*40} {'-'*8} {'-'*10} {'-'*10} {'-'*10}")

    for name, offset, expected, patch in all_patches:
        actual = read_u16(rom, offset)
        if actual == expected:
            status = "ORIGINAL"
        elif actual == patch:
            status = "PATCHED"
        else:
            status = "UNKNOWN!"
        print(f"  {name:<40} {offset:>#08X} {expected:>#010X} {actual:>#010X} {status:>10}")

    for name, offset in nop_patches:
        actual = read_u16(rom, offset)
        if actual == 0x46C0:
            status = "NOP'D"
        else:
            status = "ORIGINAL"
        print(f"  {name:<40} {offset:>#08X} {'N/A':>10} {actual:>#010X} {status:>10}")

if __name__ == '__main__':
    main()
