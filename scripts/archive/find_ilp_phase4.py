"""Phase 4+5: Find InitLocalLinkPlayer
- Phase 4: gSaveBlock2Ptr LP refs -> check for gLocalLinkPlayer nearby
- Phase 5: Find callers of the copy function (0x0800AA4C) and trace back
- Phase 6: Find all BL->StringCopy(0x08008C74) near link.c region
- Phase 7: Brute force: scan for functions with gLocalLinkPlayer that do struct init
"""
import struct

ROM_PATH = "rom/Pokemon RunBun.gba"
with open(ROM_PATH, "rb") as f:
    rom = f.read()

ROM_SIZE = len(rom)
GLP = 0x02022D74       # gLocalLinkPlayer
SB2PTR = 0x03005D90    # gSaveBlock2Ptr
GLINKPLAYERS = 0x02022CE8
STRINGCOPY = 0x08008C74  # from BL at 0x0800AB8A
COPY_FUNC = 0x0800AA4C   # CopyLocalLinkPlayerToAll

def decode_bl(offset):
    if offset + 3 >= ROM_SIZE: return None
    hi = struct.unpack_from('<H', rom, offset)[0]
    lo = struct.unpack_from('<H', rom, offset + 2)[0]
    if (hi >> 11) != 0x1E or (lo >> 11) != 0x1F: return None
    off_hi = hi & 0x7FF
    off_lo = lo & 0x7FF
    combined = (off_hi << 12) | (off_lo << 1)
    if combined & 0x400000: combined -= 0x800000
    return (0x08000000 + offset + 4) + combined

def find_func_start(offset):
    for back in range(offset, max(offset - 2048, 0), -2):
        hw = struct.unpack_from('<H', rom, back)[0]
        if (hw & 0xFF00) == 0xB500: return back
    return None

def find_func_end(offset):
    for fwd in range(offset, min(offset + 2048, ROM_SIZE - 1), 2):
        hw = struct.unpack_from('<H', rom, fwd)[0]
        if (hw & 0xFF00) == 0xBD00: return fwd + 2
        if hw == 0x4770: return fwd + 2
    return offset + 200

def get_lp_values(func_off, func_end):
    """Get all 32-bit LP values in function+LP area"""
    vals = {}
    end = min(func_end + 256, ROM_SIZE - 3)
    for off in range(func_off, end, 4):
        val = struct.unpack_from('<I', rom, off)[0]
        if (0x02000000 <= val <= 0x0203FFFF or
            0x03000000 <= val <= 0x03007FFF or
            0x08000000 <= val <= 0x09FFFFFF):
            vals[0x08000000 + off] = val
    return vals

def disasm_func(func_off, max_bytes=300):
    end = min(func_off + max_bytes, ROM_SIZE - 1)
    lines = []
    i = func_off
    while i < end and i + 1 < ROM_SIZE:
        addr = 0x08000000 + i
        hw = struct.unpack_from('<H', rom, i)[0]

        if (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc = (addr + 4) & ~3
            lp_off = (pc + imm) - 0x08000000
            if 0 <= lp_off < ROM_SIZE - 3:
                lp_val = struct.unpack_from('<I', rom, lp_off)[0]
                note = ""
                if lp_val == GLP: note = " ; gLocalLinkPlayer"
                elif lp_val == SB2PTR: note = " ; gSaveBlock2Ptr"
                elif lp_val == GLINKPLAYERS: note = " ; gLinkPlayers"
                lines.append(f"  0x{addr:08X}: LDR R{rd}, =0x{lp_val:08X}{note}")
            else:
                lines.append(f"  0x{addr:08X}: LDR R{rd}, [PC, #0x{imm:X}]")
        elif (hw & 0xFF00) == 0xB500:
            lines.append(f"  0x{addr:08X}: PUSH (0x{hw:04X})")
        elif (hw & 0xFF00) == 0xBD00:
            lines.append(f"  0x{addr:08X}: POP+PC (0x{hw:04X})")
            break
        elif hw == 0x4770:
            lines.append(f"  0x{addr:08X}: BX LR")
            break
        elif (hw >> 11) == 0x1E and i + 3 < ROM_SIZE:
            lo = struct.unpack_from('<H', rom, i + 2)[0]
            if (lo >> 11) == 0x1F:
                target = decode_bl(i)
                note = ""
                if target == STRINGCOPY: note = " ; StringCopy!"
                elif target == COPY_FUNC: note = " ; CopyLocalToLinkPlayers!"
                elif target == 0x08000544: note = " ; SetMainCallback2"
                lines.append(f"  0x{addr:08X}: BL 0x{target:08X}{note}")
                i += 4; continue
        elif (hw & 0xFE00) == 0x7000:
            lines.append(f"  0x{addr:08X}: STRB (0x{hw:04X})")
        elif (hw & 0xFE00) == 0x8000:
            lines.append(f"  0x{addr:08X}: STRH (0x{hw:04X})")
        elif (hw & 0xFE00) == 0x6000:
            lines.append(f"  0x{addr:08X}: STR  (0x{hw:04X})")
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: MOV R{rd}, #0x{imm:X}")
        else:
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")
        i += 2
    return lines

# ============================================================
# PHASE 4: gSaveBlock2Ptr LP refs -> check gLocalLinkPlayer
# ============================================================
print("=" * 70)
print("PHASE 4: gSaveBlock2Ptr LP refs -> check for gLocalLinkPlayer")
print("=" * 70)

sb2_offsets = []
for off in range(0, ROM_SIZE - 3, 4):
    val = struct.unpack_from('<I', rom, off)[0]
    if val == SB2PTR:
        sb2_offsets.append(off)
print(f"Found {len(sb2_offsets)} gSaveBlock2Ptr LP refs")

for off in sb2_offsets:
    fs = find_func_start(off)
    if fs is None: continue
    fe = find_func_end(fs)
    # Check if gLocalLinkPlayer is in same function LP
    for scan in range(fs, min(fe + 256, ROM_SIZE - 3), 4):
        val = struct.unpack_from('<I', rom, scan)[0]
        if val == GLP:
            addr = 0x08000000 + fs
            print(f"\n  MATCH: func=0x{addr:08X} has BOTH SB2Ptr + gLocalLinkPlayer")
            for l in disasm_func(fs): print(l)
            break

# ============================================================
# PHASE 5: Find all BL callers of CopyLocalLinkPlayerToAll (0x0800AA4C)
# ============================================================
print()
print("=" * 70)
print("PHASE 5: BL callers of CopyLocalToLinkPlayers (0x0800AA4C)")
print("=" * 70)

callers = []
for off in range(0, ROM_SIZE - 3, 2):
    target = decode_bl(off)
    if target == COPY_FUNC:
        fs = find_func_start(off)
        caller_addr = 0x08000000 + off
        func_addr = 0x08000000 + fs if fs else 0
        callers.append((off, fs))
        print(f"  BL at 0x{caller_addr:08X}, func=0x{func_addr:08X}")

print(f"\nTotal callers: {len(callers)}")
for bl_off, fs in callers:
    if fs is None: continue
    fe = find_func_end(fs)
    faddr = 0x08000000 + fs
    lp_vals = get_lp_values(fs, fe)
    # Check if this caller also references SaveBlock2 or does struct init
    has_sb2 = any(v == SB2PTR for v in lp_vals.values())
    has_glp = any(v == GLP for v in lp_vals.values())
    interesting = has_sb2 or has_glp
    if interesting:
        print(f"\n  *** Interesting caller at 0x{faddr:08X} (SB2={has_sb2}, GLP={has_glp}) ***")
        for l in disasm_func(fs): print(l)

# ============================================================
# PHASE 6: BL->StringCopy near link.c (0x08009000-0x0800C000)
# ============================================================
print()
print("=" * 70)
print("PHASE 6: BL->StringCopy (0x08008C74) in link.c region")
print("=" * 70)

for off in range(0x9000, min(0xC000, ROM_SIZE - 3), 2):
    target = decode_bl(off)
    if target == STRINGCOPY:
        fs = find_func_start(off)
        addr = 0x08000000 + off
        func_addr = 0x08000000 + fs if fs else 0
        print(f"  BL StringCopy at 0x{addr:08X}, func=0x{func_addr:08X}")

# ============================================================
# PHASE 7: Check vanilla address 0x08009638 area
# ============================================================
print()
print("=" * 70)
print("PHASE 7: What's at vanilla InitLocalLinkPlayer address (0x08009638)?")
print("=" * 70)

# Check a range around vanilla address
for start in [0x9600, 0x9620, 0x9638, 0x9650]:
    fs = find_func_start(start)
    if fs:
        fe = find_func_end(fs)
        faddr = 0x08000000 + fs
        fsize = fe - fs
        lp = get_lp_values(fs, fe)
        ram_refs = [f"0x{v:08X}" for v in lp.values() if 0x02000000 <= v <= 0x0203FFFF or 0x03000000 <= v <= 0x03007FFF]
        print(f"\n  func 0x{faddr:08X} ({fsize}b)")
        if ram_refs:
            print(f"    RAM refs: {', '.join(ram_refs)}")
        for l in disasm_func(fs, 150): print(l)

# ============================================================
# PHASE 8: Find InitLocalLinkPlayer by elimination
# All 4 gLocalLinkPlayer functions are at 0x0800AA-0x0800AB.
# InitLocalLinkPlayer should be JUST BEFORE or called from them.
# Check what calls into the 0x0800A9-0x0800AB range.
# ============================================================
print()
print("=" * 70)
print("PHASE 8: Functions in 0x08009800-0x0800AA4C (between GetMultiplayerId and copy func)")
print("=" * 70)

# List all function starts in this range
func_starts = []
for off in range(0x9800, 0xAA4C, 2):
    hw = struct.unpack_from('<H', rom, off)[0]
    if (hw & 0xFF00) == 0xB500:
        # Verify it's a real function (not in the middle of a literal pool)
        # Check if previous instruction is BX/POP or literal pool data
        if off >= 2:
            prev = struct.unpack_from('<H', rom, off - 2)[0]
            if prev == 0x4770 or (prev & 0xFF00) == 0xBD00 or prev == 0x0000 or (prev & 0xF800) == 0x4800:
                func_starts.append(off)
            # Also accept if 4 bytes before is a 32-bit value (literal pool)
            elif off >= 4:
                prev4 = struct.unpack_from('<I', rom, off - 4)[0]
                if 0x02000000 <= prev4 <= 0x0203FFFF or 0x03000000 <= prev4 <= 0x03007FFF or 0x08000000 <= prev4 <= 0x09FFFFFF:
                    func_starts.append(off)

print(f"Found {len(func_starts)} potential functions")

for fs in func_starts:
    fe = find_func_end(fs)
    fsize = fe - fs
    faddr = 0x08000000 + fs
    lp = get_lp_values(fs, fe)

    # Count stores and BLs
    stores = 0
    bls_list = []
    for i in range(fs, fe, 2):
        hw = struct.unpack_from('<H', rom, i)[0]
        if (hw & 0xFE00) in (0x7000, 0x8000, 0x6000):
            stores += 1
        if (hw >> 11) == 0x1E and i + 3 < ROM_SIZE:
            lo = struct.unpack_from('<H', rom, i + 2)[0]
            if (lo >> 11) == 0x1F:
                target = decode_bl(i)
                if target: bls_list.append(target)

    # Filter: functions with stores that might be InitLocalLinkPlayer
    # It should have: stores >= 3, BL to StringCopy or other helpers, small-medium size
    has_sb2 = any(v == SB2PTR for v in lp.values())
    has_glp = any(v == GLP for v in lp.values())
    calls_stringcopy = STRINGCOPY in bls_list

    interesting = (stores >= 4 and fsize < 300) or has_sb2 or has_glp or calls_stringcopy

    if interesting:
        print(f"\n  func 0x{faddr:08X} ({fsize}b, {stores} stores, {len(bls_list)} BLs)")
        if has_sb2: print("    ** HAS gSaveBlock2Ptr **")
        if has_glp: print("    ** HAS gLocalLinkPlayer **")
        if calls_stringcopy: print("    ** CALLS StringCopy **")
        bl_str = ", ".join(f"0x{t:08X}" for t in bls_list[:10])
        print(f"    BL targets: {bl_str}")
        ram_refs = [f"0x{v:08X}" for v in sorted(set(lp.values())) if 0x02000000 <= v <= 0x03FFFFFF]
        if ram_refs: print(f"    RAM refs: {', '.join(ram_refs)}")
        for l in disasm_func(fs, 200): print(l)

print()
print("=" * 70)
print("DONE")
print("=" * 70)
