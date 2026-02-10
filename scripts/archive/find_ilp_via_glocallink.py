"""Find InitLocalLinkPlayer via gLocalLinkPlayer (0x02022D74) + gSaveBlock2Ptr (0x03005D90)"""
import struct

ROM_PATH = "rom/Pokemon RunBun.gba"
with open(ROM_PATH, "rb") as f:
    rom = f.read()

ROM_SIZE = len(rom)
TARGET = 0x02022D74   # gLocalLinkPlayer
SB2PTR = 0x03005D90   # gSaveBlock2Ptr

def find_func_start(offset):
    """Scan backwards for PUSH {.., LR}"""
    for back in range(offset, max(offset - 2048, 0), -2):
        hw = struct.unpack_from('<H', rom, back)[0]
        if (hw & 0xFF00) == 0xB500:
            return back
    return None

def find_func_end(offset):
    """Scan forward for POP {.., PC} or BX LR"""
    for fwd in range(offset, min(offset + 2048, ROM_SIZE - 1), 2):
        hw = struct.unpack_from('<H', rom, fwd)[0]
        if (hw & 0xFF00) == 0xBD00:  # POP {.., PC}
            return fwd + 2
        if hw == 0x4770:  # BX LR
            return fwd + 2
    return offset + 200

def decode_bl(offset):
    """Decode THUMB BL at given ROM offset, return target address"""
    if offset + 3 >= ROM_SIZE:
        return None
    hi = struct.unpack_from('<H', rom, offset)[0]
    lo = struct.unpack_from('<H', rom, offset + 2)[0]
    if (hi >> 11) != 0x1E or (lo >> 11) != 0x1F:
        return None
    off_hi = hi & 0x7FF
    off_lo = lo & 0x7FF
    combined = (off_hi << 12) | (off_lo << 1)
    if combined & 0x400000:
        combined -= 0x800000
    return (0x08000000 + offset + 4) + combined

def disasm_range(start_off, end_off):
    """Simple THUMB disassembler for display"""
    lines = []
    i = start_off
    while i < end_off and i + 1 < ROM_SIZE:
        addr = 0x08000000 + i
        hw = struct.unpack_from('<H', rom, i)[0]

        # Check for 32-bit LP values at aligned positions
        if i % 4 == 0 and i + 3 < ROM_SIZE:
            w32 = struct.unpack_from('<I', rom, i)[0]
            if w32 == TARGET:
                lines.append(f"  0x{addr:08X}: .word 0x{w32:08X}  ; gLocalLinkPlayer")
                i += 4
                continue
            if w32 == SB2PTR:
                lines.append(f"  0x{addr:08X}: .word 0x{w32:08X}  ; gSaveBlock2Ptr")
                i += 4
                continue

        # LDR Rd, [PC, #imm]
        if (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc = (addr + 4) & ~3
            lp_off = (pc + imm) - 0x08000000
            if 0 <= lp_off < ROM_SIZE - 3:
                lp_val = struct.unpack_from('<I', rom, lp_off)[0]
                note = ""
                if lp_val == TARGET: note = " ; gLocalLinkPlayer"
                elif lp_val == SB2PTR: note = " ; gSaveBlock2Ptr"
                elif lp_val == 0x02022CE8: note = " ; gLinkPlayers"
                elif lp_val == 0x030022C0: note = " ; gMain"
                lines.append(f"  0x{addr:08X}: LDR R{rd}, [PC, #0x{imm:X}]  ; =0x{lp_val:08X}{note}")
            else:
                lines.append(f"  0x{addr:08X}: LDR R{rd}, [PC, #0x{imm:X}]")
        elif (hw & 0xFF00) == 0xB500:
            lines.append(f"  0x{addr:08X}: PUSH {{..., LR}}  (0x{hw:04X})")
        elif (hw & 0xFF00) == 0xBD00:
            lines.append(f"  0x{addr:08X}: POP {{..., PC}}  (0x{hw:04X})")
        elif hw == 0x4770:
            lines.append(f"  0x{addr:08X}: BX LR")
        elif (hw >> 11) == 0x1E:
            # BL first half
            if i + 3 < ROM_SIZE:
                lo_hw = struct.unpack_from('<H', rom, i + 2)[0]
                if (lo_hw >> 11) == 0x1F:
                    target = decode_bl(i)
                    lines.append(f"  0x{addr:08X}: BL 0x{target:08X}")
                    i += 4
                    continue
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")
        elif (hw & 0xFE00) == 0x7000:
            lines.append(f"  0x{addr:08X}: STRB  (0x{hw:04X})")
        elif (hw & 0xFE00) == 0x8000:
            lines.append(f"  0x{addr:08X}: STRH  (0x{hw:04X})")
        elif (hw & 0xFE00) == 0x6000:
            lines.append(f"  0x{addr:08X}: STR   (0x{hw:04X})")
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: MOV R{rd}, #0x{imm:X}")
        else:
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")
        i += 2
    return lines


# ============================================================
# PHASE 1: Find ALL LP refs to gLocalLinkPlayer
# ============================================================
print("=" * 70)
print("PHASE 1: All LP refs to gLocalLinkPlayer (0x02022D74)")
print("=" * 70)

glp_lp_offsets = []
for off in range(0, ROM_SIZE - 3, 4):
    val = struct.unpack_from('<I', rom, off)[0]
    if val == TARGET:
        glp_lp_offsets.append(off)

print(f"Found {len(glp_lp_offsets)} LP refs")

# Group by containing function
func_map = {}
for lp_off in glp_lp_offsets:
    fs = find_func_start(lp_off)
    if fs is not None:
        if fs not in func_map:
            func_map[fs] = []
        func_map[fs].append(lp_off)
    else:
        print(f"  LP at 0x{0x08000000+lp_off:08X}: no func found")

print(f"Maps to {len(func_map)} unique functions")
for fs in sorted(func_map.keys()):
    fe = find_func_end(fs)
    fsize = fe - fs
    addr = 0x08000000 + fs
    print(f"  func 0x{addr:08X} (THUMB 0x{addr+1:08X}), ~{fsize} bytes, {len(func_map[fs])} LP refs")


# ============================================================
# PHASE 2: Find functions with BOTH gLocalLinkPlayer + gSaveBlock2Ptr
# ============================================================
print()
print("=" * 70)
print("PHASE 2: Functions with BOTH gLocalLinkPlayer + gSaveBlock2Ptr")
print("=" * 70)

matches = []
for fs in sorted(func_map.keys()):
    fe = find_func_end(fs)
    # Extend search to include LP after function body
    search_end = min(fe + 256, ROM_SIZE - 3)
    has_sb2 = False
    for scan in range(fs, search_end, 4):
        val = struct.unpack_from('<I', rom, scan)[0]
        if val == SB2PTR:
            has_sb2 = True
            break
    if has_sb2:
        addr = 0x08000000 + fs
        matches.append((fs, fe))
        print(f"\n  *** MATCH: func=0x{addr:08X} (THUMB: 0x{addr+1:08X}) ***")
        lines = disasm_range(fs, min(fe + 64, ROM_SIZE))
        for l in lines:
            print(l)

if not matches:
    print("  No functions with both gLocalLinkPlayer AND gSaveBlock2Ptr found.")

    # ============================================================
    # PHASE 3: Functions that write TO gLocalLinkPlayer (stores)
    # ============================================================
    print()
    print("=" * 70)
    print("PHASE 3: Functions with gLocalLinkPlayer that have many stores")
    print("=" * 70)

    for fs in sorted(func_map.keys()):
        fe = find_func_end(fs)
        fsize = fe - fs
        if fsize > 400:
            continue  # Too big

        # Count stores
        stores = 0
        bls = 0
        for off in range(fs, fe, 2):
            hw = struct.unpack_from('<H', rom, off)[0]
            if (hw & 0xFE00) in (0x7000, 0x8000, 0x6000):
                stores += 1
            if (hw >> 11) == 0x1E and off + 3 < ROM_SIZE:
                lo = struct.unpack_from('<H', rom, off + 2)[0]
                if (lo >> 11) == 0x1F:
                    bls += 1

        addr = 0x08000000 + fs
        if stores >= 3:
            print(f"\n  func 0x{addr:08X} ({fsize}b, {stores} stores, {bls} BLs)")
            # Check LP values
            lp_vals = set()
            for off in range(fs, min(fe + 128, ROM_SIZE - 3), 4):
                val = struct.unpack_from('<I', rom, off)[0]
                if 0x02000000 <= val <= 0x0203FFFF or 0x03000000 <= val <= 0x03007FFF:
                    lp_vals.add(val)
            if lp_vals:
                print(f"    LP RAM refs: {', '.join(f'0x{v:08X}' for v in sorted(lp_vals))}")
            lines = disasm_range(fs, min(fe + 32, ROM_SIZE))
            for l in lines:
                print(l)


# ============================================================
# PHASE 4: Broader — find all gSaveBlock2Ptr LP refs and check for
# gLocalLinkPlayer in same function
# ============================================================
print()
print("=" * 70)
print("PHASE 4: All gSaveBlock2Ptr LP refs → check for gLocalLinkPlayer nearby")
print("=" * 70)

sb2_lp_offsets = []
for off in range(0, ROM_SIZE - 3, 4):
    val = struct.unpack_from('<I', rom, off)[0]
    if val == SB2PTR:
        sb2_lp_offsets.append(off)

print(f"Found {len(sb2_lp_offsets)} gSaveBlock2Ptr LP refs")

for lp_off in sb2_lp_offsets:
    fs = find_func_start(lp_off)
    if fs is None:
        continue
    fe = find_func_end(fs)
    search_end = min(fe + 256, ROM_SIZE - 3)
    has_glp = False
    for scan in range(fs, search_end, 4):
        val = struct.unpack_from('<I', rom, scan)[0]
        if val == TARGET:
            has_glp = True
            break
    if has_glp:
        addr = 0x08000000 + fs
        fsize = fe - fs
        print(f"\n  *** MATCH: func=0x{addr:08X} ({fsize}b) has both gSaveBlock2Ptr + gLocalLinkPlayer ***")
        lines = disasm_range(fs, min(fe + 64, ROM_SIZE))
        for l in lines:
            print(l)

print()
print("=" * 70)
print("DONE")
print("=" * 70)
