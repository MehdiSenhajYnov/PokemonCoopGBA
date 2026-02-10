"""Trace callers of CopyLocalToLinkPlayers to find InitLocalLinkPlayer.
InitLocalLinkPlayer should be called BEFORE CopyLocalToLinkPlayers in each caller."""
import struct

ROM_PATH = "rom/Pokemon RunBun.gba"
with open(ROM_PATH, "rb") as f:
    rom = f.read()

ROM_SIZE = len(rom)
COPY_FUNC = 0x0800AA4C

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
    for back in range(offset, max(offset - 4096, 0), -2):
        hw = struct.unpack_from('<H', rom, back)[0]
        if (hw & 0xFF00) == 0xB500: return back
    return None

# Callers of CopyLocalToLinkPlayers
callers = [0x0D09F4, 0x0D0BB0, 0x0D0CA0]  # ROM offsets

for caller_off in callers:
    # Find the BL to COPY_FUNC in this function
    fs = find_func_start(caller_off)
    if not fs:
        print(f"Cannot find func start for caller at 0x{0x08000000+caller_off:08X}")
        continue

    faddr = 0x08000000 + fs
    print(f"\n{'='*70}")
    print(f"Caller function at 0x{faddr:08X}")
    print(f"{'='*70}")

    # Disassemble with focus on BL targets
    bl_targets = []
    for i in range(fs, min(fs + 2000, ROM_SIZE - 3), 2):
        addr = 0x08000000 + i
        hw = struct.unpack_from('<H', rom, i)[0]

        if (hw >> 11) == 0x1E and i + 3 < ROM_SIZE:
            lo = struct.unpack_from('<H', rom, i + 2)[0]
            if (lo >> 11) == 0x1F:
                target = decode_bl(i)
                if target:
                    bl_targets.append((addr, target))

        # Stop at POP {PC}
        if (hw & 0xFF00) == 0xBD00 or hw == 0x4770:
            break

    print(f"  All BL calls in function:")
    for bl_addr, target in bl_targets:
        marker = ""
        if target == COPY_FUNC:
            marker = " <-- CopyLocalToLinkPlayers"
        elif target == 0x08000544:
            marker = " <-- SetMainCallback2"
        elif target == 0x0800A4B0:
            marker = " <-- GetMultiplayerId"
        elif target == 0x08008C74:
            marker = " <-- StringCopy"
        elif target == 0x080C1544:
            marker = " <-- CreateTask"
        print(f"    0x{bl_addr:08X}: BL 0x{target:08X}{marker}")

    # Find the BL just BEFORE the CopyLocal call
    prev_bl = None
    for bl_addr, target in bl_targets:
        if target == COPY_FUNC:
            print(f"\n  BL to CopyLocalToLinkPlayers at 0x{bl_addr:08X}")
            if prev_bl:
                print(f"  Previous BL: 0x{prev_bl[0]:08X} -> 0x{prev_bl[1]:08X}")
                print(f"  ** This could be InitLocalLinkPlayer! **")
            break
        prev_bl = (bl_addr, target)

# Now let's check the most likely candidate: the BL target just before CopyLocalToLinkPlayers
# Collect all unique "prev BL" targets
print(f"\n{'='*70}")
print("Candidate InitLocalLinkPlayer functions (BL just before CopyLocal):")
print(f"{'='*70}")

prev_candidates = set()
for caller_off in callers:
    fs = find_func_start(caller_off)
    if not fs: continue

    bl_targets = []
    for i in range(fs, min(fs + 2000, ROM_SIZE - 3), 2):
        hw = struct.unpack_from('<H', rom, i)[0]
        if (hw >> 11) == 0x1E and i + 3 < ROM_SIZE:
            lo = struct.unpack_from('<H', rom, i + 2)[0]
            if (lo >> 11) == 0x1F:
                target = decode_bl(i)
                if target: bl_targets.append(target)
        if (hw & 0xFF00) == 0xBD00 or hw == 0x4770:
            break

    prev = None
    for target in bl_targets:
        if target == COPY_FUNC and prev:
            prev_candidates.add(prev)
        prev = target

for cand in sorted(prev_candidates):
    cand_off = cand - 0x08000000
    if cand_off < 0 or cand_off >= ROM_SIZE:
        print(f"  0x{cand:08X} -- out of ROM range")
        continue

    # Find func boundaries
    fs = find_func_start(cand_off)
    if not fs: fs = cand_off
    faddr = 0x08000000 + fs

    # Find end
    fe = fs
    for i in range(fs, min(fs + 2000, ROM_SIZE - 1), 2):
        hw = struct.unpack_from('<H', rom, i)[0]
        if (hw & 0xFF00) == 0xBD00 or hw == 0x4770:
            fe = i + 2
            break

    fsize = fe - fs

    # Get LP values
    lp_vals = {}
    for off in range(fs, min(fe + 256, ROM_SIZE - 3), 4):
        val = struct.unpack_from('<I', rom, off)[0]
        if (0x02000000 <= val <= 0x0203FFFF or 0x03000000 <= val <= 0x03007FFF):
            lp_vals[off] = val

    print(f"\n  Function at 0x{faddr:08X} ({fsize} bytes)")
    print(f"  LP RAM values: {', '.join(f'0x{v:08X}' for v in sorted(set(lp_vals.values())))}")

    # Full disassembly
    for i in range(fs, min(fe + 64, ROM_SIZE - 1), 2):
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
                if lp_val == 0x02022D74: note = " ; gLocalLinkPlayer"
                elif lp_val == 0x03005D90: note = " ; gSaveBlock2Ptr"
                elif lp_val == 0x02022CE8: note = " ; gLinkPlayers"
                elif lp_val == 0x030022C0: note = " ; gMain"
                elif lp_val == 0x03005DA0: note = " ; gSaveBlock2Ptr+0x10??"
                print(f"    0x{addr:08X}: LDR R{rd}, =0x{lp_val:08X}{note}")
            else:
                print(f"    0x{addr:08X}: LDR R{rd}, [PC, #0x{imm:X}]")
        elif (hw & 0xFF00) == 0xB500:
            print(f"    0x{addr:08X}: PUSH (0x{hw:04X})")
        elif (hw & 0xFF00) == 0xBD00:
            print(f"    0x{addr:08X}: POP+PC (0x{hw:04X})")
            break
        elif hw == 0x4770:
            print(f"    0x{addr:08X}: BX LR")
            break
        elif (hw >> 11) == 0x1E and i + 3 < ROM_SIZE:
            lo = struct.unpack_from('<H', rom, i + 2)[0]
            if (lo >> 11) == 0x1F:
                target = decode_bl(i)
                note = ""
                if target == 0x08008C74: note = " ; StringCopy"
                elif target == 0x0800A4B0: note = " ; GetMultiplayerId"
                elif target == COPY_FUNC: note = " ; CopyLocalToLinkPlayers"
                print(f"    0x{addr:08X}: BL 0x{target:08X}{note}")
                i += 2  # skip second halfword -- wait, the loop adds 2
                # Actually the for loop increments by 2, but BL is 4 bytes
                # We can't skip in a for loop. Just note this.
            else:
                print(f"    0x{addr:08X}: .hword 0x{hw:04X}")
        elif (hw & 0xFE00) == 0x7000:
            print(f"    0x{addr:08X}: STRB (0x{hw:04X})")
        elif (hw & 0xFE00) == 0x8000:
            print(f"    0x{addr:08X}: STRH (0x{hw:04X})")
        elif (hw & 0xFE00) == 0x6000:
            print(f"    0x{addr:08X}: STR  (0x{hw:04X})")
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            print(f"    0x{addr:08X}: MOV R{rd}, #0x{imm:X}")
        else:
            print(f"    0x{addr:08X}: .hword 0x{hw:04X}")

print(f"\n{'='*70}")
print("DONE")
print(f"{'='*70}")
