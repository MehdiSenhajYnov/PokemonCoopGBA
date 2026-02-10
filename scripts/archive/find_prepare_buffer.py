import struct, os

PROJ = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ROM_PATH = os.path.join(PROJ, "rom", "Pokemon RunBun.gba")
PREP_LINK_ROM = 0x032FA8
TARGET_ADDR = 0x08032FA8

with open(ROM_PATH, "rb") as fr:
    rom = fr.read()
print(f"ROM size: {len(rom)} bytes")


def disasm(rom_data, off, hw):
    d = ""
    if (hw & 0xFF00) == 0xB500:
        regs = [f"r{b}" for b in range(8) if hw & (1 << b)]
        if hw & 0x100: regs.append("lr")
        d = "PUSH {" + ", ".join(regs) + "}"
    elif (hw & 0xFF00) == 0xBD00:
        regs = [f"r{b}" for b in range(8) if hw & (1 << b)]
        if hw & 0x100: regs.append("pc")
        d = "POP {" + ", ".join(regs) + "}"
    elif (hw & 0xF800) == 0x2000:
        d = f"MOVS r{(hw>>8)&7}, #0x{hw&0xFF:02X}"
    elif (hw & 0xF800) == 0x2800:
        d = f"CMP r{(hw>>8)&7}, #0x{hw&0xFF:02X}"
    elif hw == 0x4770:
        d = "BX LR"
    elif (hw & 0xFF00) == 0x4600:
        rd = (hw & 7) | ((hw >> 4) & 8)
        rm = (hw >> 3) & 0xF
        d = f"MOV r{rd}, r{rm}"
    elif (hw & 0xFFC0) == 0x4200:
        d = f"TST r{hw&7}, r{(hw>>3)&7}"
    elif (hw & 0xFFC0) == 0x4000:
        d = f"ANDS r{hw&7}, r{(hw>>3)&7}"
    elif (hw & 0xFFC0) == 0x4280:
        d = f"CMP r{hw&7}, r{(hw>>3)&7}"
    elif (hw & 0xFF00) == 0xD000:
        imm = hw & 0xFF
        if imm & 0x80: imm -= 256
        d = f"BEQ 0x{off+4+imm*2:06X} ({imm*2:+d})"
    elif (hw & 0xFF00) == 0xD100:
        imm = hw & 0xFF
        if imm & 0x80: imm -= 256
        d = f"BNE 0x{off+4+imm*2:06X} ({imm*2:+d})"
    elif (hw & 0xFF00) == 0xD200:
        imm = hw & 0xFF
        if imm & 0x80: imm -= 256
        d = f"BCS 0x{off+4+imm*2:06X}"
    elif (hw & 0xFF00) == 0xD300:
        imm = hw & 0xFF
        if imm & 0x80: imm -= 256
        d = f"BCC 0x{off+4+imm*2:06X}"
    elif (hw & 0xF800) == 0xE000:
        imm = hw & 0x7FF
        if imm & 0x400: imm -= 0x800
        d = f"B 0x{off+4+imm*2:06X} ({imm*2:+d})"
    elif (hw & 0xF800) == 0xF000:
        if off + 2 < len(rom_data):
            hw2 = struct.unpack_from("<H", rom_data, off + 2)[0]
            if (hw2 & 0xF800) == 0xF800:
                hi = hw & 0x7FF
                lo = hw2 & 0x7FF
                blo = (hi << 12) | (lo << 1)
                if blo & 0x400000: blo -= 0x800000
                tgt = 0x08000000 + off + 4 + blo
                d = f"BL 0x{tgt:08X} [hw2=0x{hw2:04X}]"
    elif (hw & 0xF800) == 0x4800:
        reg = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        pa = ((off + 4) & ~3) + imm
        if pa + 4 <= len(rom_data):
            pv = struct.unpack_from("<I", rom_data, pa)[0]
            d = f"LDR r{reg}, [PC, #0x{imm:X}] (=0x{pv:08X} @0x{pa:06X})"
        else:
            d = f"LDR r{reg}, [PC, #0x{imm:X}]"
    elif (hw & 0xF800) == 0x6800:
        d = f"LDR r{hw&7}, [r{(hw>>3)&7}, #0x{((hw>>6)&0x1F)*4:X}]"
    elif (hw & 0xF800) == 0x6000:
        d = f"STR r{hw&7}, [r{(hw>>3)&7}, #0x{((hw>>6)&0x1F)*4:X}]"
    elif (hw & 0xF800) == 0x7800:
        d = f"LDRB r{hw&7}, [r{(hw>>3)&7}, #0x{(hw>>6)&0x1F:X}]"
    elif (hw & 0xF800) == 0x7000:
        d = f"STRB r{hw&7}, [r{(hw>>3)&7}, #0x{(hw>>6)&0x1F:X}]"
    elif (hw & 0xF800) == 0x8800:
        d = f"LDRH r{hw&7}, [r{(hw>>3)&7}, #0x{((hw>>6)&0x1F)*2:X}]"
    elif (hw & 0xF800) == 0x8000:
        d = f"STRH r{hw&7}, [r{(hw>>3)&7}, #0x{((hw>>6)&0x1F)*2:X}]"
    elif (hw & 0xFE00) == 0x1C00:
        d = f"ADDS r{hw&7}, r{(hw>>3)&7}, #{(hw>>6)&7}"
    elif (hw & 0xFE00) == 0x1800:
        d = f"ADDS r{hw&7}, r{(hw>>3)&7}, r{(hw>>6)&7}"
    elif (hw & 0xF800) == 0x3000:
        d = f"ADDS r{(hw>>8)&7}, #0x{hw&0xFF:02X}"
    elif (hw & 0xF800) == 0x3800:
        d = f"SUBS r{(hw>>8)&7}, #0x{hw&0xFF:02X}"
    elif (hw & 0xF800) == 0x0000 and hw != 0:
        d = f"LSLS r{hw&7}, r{(hw>>3)&7}, #{(hw>>6)&0x1F}"
    elif (hw & 0xF800) == 0x0800:
        d = f"LSRS r{hw&7}, r{(hw>>3)&7}, #{(hw>>6)&0x1F}"
    elif (hw & 0xFF00) == 0x4700:
        d = f"BX r{(hw>>3)&0xF}"
    return d

def dump_region(start, size, label=""):
    if label:
        print()
        print(f"{label}:")
    skip = False
    for i in range(0, size, 2):
        if skip:
            skip = False
            continue
        o = start + i
        hw = struct.unpack_from("<H", rom, o)[0]
        d = disasm(rom, o, hw)
        if (hw & 0xF800) == 0xF000 and o + 2 < len(rom):
            hw2 = struct.unpack_from("<H", rom, o + 2)[0]
            if (hw2 & 0xF800) == 0xF800:
                print(f"  +0x{i:02X} (0x{o:06X}): 0x{hw:04X} 0x{hw2:04X}  {d}")
                skip = True
                continue
        print(f"  +0x{i:02X} (0x{o:06X}): 0x{hw:04X}       {d}")


# STEP 1: Find end of PrepareBufferDataTransferLink
print()
print("=" * 70)
print("STEP 1: Find end of PrepareBufferDataTransferLink (0x032FA8)")
print("=" * 70)
dump_region(PREP_LINK_ROM, 160, "PrepareBufferDataTransferLink")

func_end = None
for i in range(0, 300, 2):
    o = PREP_LINK_ROM + i
    hw = struct.unpack_from("<H", rom, o)[0]
    if (hw & 0xFF00) == 0xBD00:
        print(f"  POP at 0x{o:06X} (0x{hw:04X}), +{i}")
        if func_end is None:
            func_end = o + 2
    elif hw == 0x4770:
        print(f"  BX LR at 0x{o:06X}, +{i}")
        if func_end is None:
            func_end = o + 2
if func_end:
    print(f"End at 0x{func_end:06X} (size={func_end - PREP_LINK_ROM})")
else:
    func_end = PREP_LINK_ROM + 142

# STEP 2: What is right after
print()
print("=" * 70)
print(f"STEP 2: Code after func end (0x{func_end:06X})")
print("=" * 70)
dump_region(func_end, 128, f"After PrepareBufferDataTransferLink")

for delta in range(0, 8, 2):
    o = func_end + delta
    hw = struct.unpack_from("<H", rom, o)[0]
    if (hw & 0xFF00) == 0xB500:
        print()
        print(f"*** PUSH at 0x{o:06X} (0x{hw:04X}) => PrepareBufferDataTransfer ***")
        print(f"    THUMB: 0x{0x08000001+o:08X}")
# STEP 3: Search for BL -> PrepareBufferDataTransferLink
print()
print("=" * 70)
print("STEP 3: BL instructions targeting 0x08032FA8")
print("=" * 70)

bl_found = []
for s, e, lab in [(0x032FA8, 0x033400, "narrow"), (0x030000, 0x038000, "wide")]:
    if bl_found:
        break
    print()
    print(f"Search {lab}: 0x{s:06X}-0x{e:06X}")
    for src in range(s, e, 2):
        if src + 4 > len(rom): break
        hw1 = struct.unpack_from("<H", rom, src)[0]
        hw2 = struct.unpack_from("<H", rom, src + 2)[0]
        if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) == 0xF800:
            hi = hw1 & 0x7FF
            lo = hw2 & 0x7FF
            ov = (hi << 12) | (lo << 1)
            if ov & 0x400000: ov -= 0x800000
            sa = 0x08000000 + src
            ct = (sa + 4 + ov) & 0xFFFFFFFF
            if ct == TARGET_ADDR or ct == (TARGET_ADDR | 1):
                print(f"  FOUND BL at 0x{src:06X} (0x{sa:08X}), target=0x{ct:08X}")
                bl_found.append(src)

if not bl_found:
    print()
    print("  Full ROM scan...")
    for src in range(0, len(rom) - 4, 2):
        hw1 = struct.unpack_from("<H", rom, src)[0]
        hw2 = struct.unpack_from("<H", rom, src + 2)[0]
        if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) == 0xF800:
            hi = hw1 & 0x7FF
            lo = hw2 & 0x7FF
            ov = (hi << 12) | (lo << 1)
            if ov & 0x400000: ov -= 0x800000
            sa = 0x08000000 + src
            ct = (sa + 4 + ov) & 0xFFFFFFFF
            if ct == TARGET_ADDR or ct == (TARGET_ADDR | 1):
                print(f"  FOUND BL at 0x{src:06X} (0x{sa:08X}), target=0x{ct:08X}")
                bl_found.append(src)

print()
print(f"Total BLs: {len(bl_found)}")

# STEP 4: Find enclosing functions
print()
print("=" * 70)
print("STEP 4: Find enclosing functions")
print("=" * 70)

candidates = []
for bl in bl_found:
    print()
    print(f"BL at 0x{bl:06X}:")
    for back in range(0, 256, 2):
        co = bl - back
        if co < 0: break
        hw = struct.unpack_from("<H", rom, co)[0]
        if (hw & 0xFF00) == 0xB500:
            print(f"  PUSH at 0x{co:06X} (0x{hw:04X}), dist={back}, THUMB=0x{0x08000001+co:08X}")
            candidates.append((co, bl, back))
            break

# STEP 5: Disassembly
print()
print("=" * 70)
print("STEP 5: Disassembly of candidate functions")
print("=" * 70)

for fs, bl, dist in candidates:
    sz = max(80, dist + 20)
    dump_region(fs, sz, f"Function 0x{fs:06X} (THUMB 0x{0x08000001+fs:08X}), BL@+0x{dist:02X}")
# STEP 6: BATTLE_TYPE_LINK branch to patch
print()
print("=" * 70)
print("STEP 6: BATTLE_TYPE_LINK branch to patch")
print("=" * 70)

for fs, bl, dist in candidates:
    print()
    print(f"Function 0x{fs:06X}:")
    for i in range(0, 200, 2):
        o = fs + i
        hw = struct.unpack_from("<H", rom, o)[0]
        if (hw & 0xF800) == 0x4800:
            reg = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pa = ((o + 4) & ~3) + imm
            if pa + 4 <= len(rom):
                pv = struct.unpack_from("<I", rom, pa)[0]
                if pv == 0x02023364:
                    print(f"  +0x{i:02X}: LDR r{reg}, =gBattleTypeFlags @pool 0x{pa:06X}")
                    print("  Following:")
                    for j in range(2, 20, 2):
                        no = o + j
                        nh = struct.unpack_from("<H", rom, no)[0]
                        nd = disasm(rom, no, nh)
                        tag = "    "
                        if (nh & 0xFF00) in (0xD000, 0xD100):
                            tag = " >> "
                            print(f"  {tag}+0x{i+j:02X} (0x{no:06X}): 0x{nh:04X}  {nd}")
                            print("       *** PATCH HERE ***")
                            print(f"       ROM offset: 0x{no:06X}, func+0x{i+j:02X}")
                            if (nh & 0xFF00) == 0xD100:
                                print("       BNE->link. Patch: NOP(0x46C0)")
                            elif (nh & 0xFF00) == 0xD000:
                                im8 = nh & 0xFF
                                if im8 & 0x80: im8 -= 256
                                bv = 0xE000 | (im8 & 0x7FF)
                                print(f"       BEQ->local. Patch: B(0x{bv:04X})")
                            continue
                        print(f"  {tag}+0x{i+j:02X} (0x{no:06X}): 0x{nh:04X}  {nd}")

# SUMMARY
print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)
print()
print("Vanilla Emerald: PrepareBufferDataTransfer=0x08032ECD, patch+0x16=0xE009")
if candidates:
    for fs, bl, dist in candidates:
        print()
        print("Run and Bun:")
        print(f"  PrepareBufferDataTransfer = 0x{0x08000001+fs:08X} (THUMB)")
        print(f"  ROM offset = 0x{fs:06X}")
        print(f"  BL to Link variant at +0x{dist:02X}")
print()
print("DONE")