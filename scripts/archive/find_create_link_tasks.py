"""
Find CreateTasksForSendRecvLinkBuffers and HandleLinkBattleSetup in Pokemon Run & Bun ROM.
Also find Task_HandleSendLinkBuffersData and Task_HandleCopyReceivedLinkBuffersData.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses from Step 2 analysis
HANDLE_LINK_BATTLE_SETUP = 0x0803240C  # Confirmed via literal pool pattern
CREATE_TASKS_ADDR = 0x08033044         # Last BL in HandleLinkBattleSetup
CREATE_TASK = 0x080C6E28               # CreateTask function (from HandleLinkBattleSetup BL #3)
SETUP_BATTLE_VARS_OFFSET = 0x06F1D8    # SetUpBattleVars ROM offset
NOP_PATCH_OFFSET_HI = 0x06F420         # Current NOP patch location


def read_rom(path):
    with open(path, "rb") as f:
        return f.read()


def decode_bl(rom, offset):
    """Decode a THUMB BL instruction at given ROM offset."""
    if offset + 4 > len(rom):
        return None
    hi = struct.unpack_from("<H", rom, offset)[0]
    lo = struct.unpack_from("<H", rom, offset + 2)[0]
    if (hi >> 11) != 0x1E:
        return None
    if (lo >> 11) == 0x1F:
        s = (hi >> 10) & 1
        imm10 = hi & 0x3FF
        j1 = (lo >> 13) & 1
        j2 = (lo >> 11) & 1
        imm11 = lo & 0x7FF
        i1 = 1 - (j1 ^ s)
        i2 = 1 - (j2 ^ s)
        imm32 = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
        if s:
            imm32 |= 0xFE000000
            imm32 -= 0x100000000
        pc = 0x08000000 + offset + 4
        return pc + imm32
    return None


def find_all_bls(rom, start_offset, max_length=300):
    """Find all BL instructions until POP PC or BX LR."""
    bls = []
    off = start_offset
    end = min(start_offset + max_length, len(rom) - 2)
    while off < end:
        hw = struct.unpack_from("<H", rom, off)[0]
        if (hw >> 11) == 0x1E and off + 2 < end:
            target = decode_bl(rom, off)
            if target is not None:
                bls.append((off, target))
                off += 4
                continue
        if hw == 0x4770:  # BX LR
            break
        if (hw >> 8) == 0xBD:  # POP {..., PC}
            break
        off += 2
    return bls


def disasm_thumb(rom, start_offset, length):
    """Print THUMB disassembly."""
    end = min(start_offset + length, len(rom))
    off = start_offset
    while off < end:
        hw = struct.unpack_from("<H", rom, off)[0]
        if (hw >> 11) == 0x1E and off + 2 < end:
            target = decode_bl(rom, off)
            if target is not None:
                print(f"  0x{0x08000000+off:08X}: BL 0x{target:08X}")
                off += 4
                continue

        if (hw >> 11) == 0x09:  # LDR Rn, [PC, #imm]
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc_aligned = ((0x08000000 + off + 4) & ~3)
            lit_addr = pc_aligned + imm
            lit_off = lit_addr - 0x08000000
            if 0 <= lit_off < len(rom):
                lit_val = struct.unpack_from("<I", rom, lit_off)[0]
                print(f"  0x{0x08000000+off:08X}: LDR R{rd}, =0x{lit_val:08X}  (pool @0x{lit_addr:08X})")
            else:
                print(f"  0x{0x08000000+off:08X}: LDR R{rd}, [PC, #0x{imm:X}]")
        elif (hw >> 8) == 0xB5 or (hw >> 8) == 0xB4:
            regs = hw & 0xFF
            lr = (hw >> 8) & 1
            rlist = [f"R{i}" for i in range(8) if regs & (1 << i)]
            if lr: rlist.append("LR")
            print(f"  0x{0x08000000+off:08X}: PUSH {{{', '.join(rlist)}}}")
        elif (hw >> 8) == 0xBD or (hw >> 8) == 0xBC:
            regs = hw & 0xFF
            pc = (hw >> 8) & 1
            rlist = [f"R{i}" for i in range(8) if regs & (1 << i)]
            if pc: rlist.append("PC")
            print(f"  0x{0x08000000+off:08X}: POP {{{', '.join(rlist)}}}")
        elif hw == 0x46C0:
            print(f"  0x{0x08000000+off:08X}: NOP")
        elif hw == 0x4770:
            print(f"  0x{0x08000000+off:08X}: BX LR")
        elif (hw >> 11) == 0x04:  # STR Rd, [Rn, #imm]
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = ((hw >> 6) & 0x1F) * 4
            print(f"  0x{0x08000000+off:08X}: STR R{rd}, [R{rn}, #0x{imm:X}]")
        elif (hw >> 11) == 0x0D:  # STR Rd, [SP, #imm]
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            print(f"  0x{0x08000000+off:08X}: STR R{rd}, [SP, #0x{imm:X}]")
        elif (hw >> 11) == 0x0C:  # LDR Rd, [SP, #imm]
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            print(f"  0x{0x08000000+off:08X}: LDR R{rd}, [SP, #0x{imm:X}]")
        elif (hw >> 9) == 0x0B:  # STRH
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = ((hw >> 6) & 0x1F) * 2
            print(f"  0x{0x08000000+off:08X}: STRH R{rd}, [R{rn}, #0x{imm:X}]")
        elif (hw >> 13) == 1:  # MOV/CMP/ADD/SUB immediate
            op = (hw >> 11) & 3
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            ops = ["MOV", "CMP", "ADD", "SUB"]
            print(f"  0x{0x08000000+off:08X}: {ops[op]} R{rd}, #0x{imm:02X}")
        elif (hw >> 8) == 0x46:  # MOV high regs
            print(f"  0x{0x08000000+off:08X}: MOV (high) 0x{hw:04X}")
        elif (hw >> 6) == 0x010C:  # ADD Rd, Rs, Rn
            rd = hw & 7
            rs = (hw >> 3) & 7
            rn = (hw >> 6) & 7
            print(f"  0x{0x08000000+off:08X}: ADD R{rd}, R{rs}, R{rn}")
        elif (hw >> 6) == 0x01C0 >> 6:  # ADD Rd, Rn, #imm3
            print(f"  0x{0x08000000+off:08X}: ADD (imm3) 0x{hw:04X}")
        else:
            print(f"  0x{0x08000000+off:08X}: 0x{hw:04X}")
        off += 2


def main():
    rom = read_rom(ROM_PATH)
    print(f"ROM loaded: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)")

    # =====================================================================
    # PART 1: Confirm HandleLinkBattleSetup at 0x0803240C
    # =====================================================================
    print()
    print("=" * 70)
    print("PART 1: HandleLinkBattleSetup at 0x0803240C")
    print("=" * 70)
    off = HANDLE_LINK_BATTLE_SETUP - 0x08000000
    print("\nDisassembly:")
    disasm_thumb(rom, off, 60)

    bls = find_all_bls(rom, off, 60)
    print(f"\nBL targets:")
    for bl_off, bl_tgt in bls:
        print(f"  0x{0x08000000+bl_off:08X} -> 0x{bl_tgt:08X}")

    # =====================================================================
    # PART 2: CreateTasksForSendRecvLinkBuffers at 0x08033044
    # =====================================================================
    print()
    print("=" * 70)
    print("PART 2: CreateTasksForSendRecvLinkBuffers at 0x08033044")
    print("=" * 70)
    ct_off = CREATE_TASKS_ADDR - 0x08000000
    # Clear THUMB bit if needed
    ct_off = ct_off & ~1

    print("\nDisassembly (200 bytes):")
    disasm_thumb(rom, ct_off, 200)

    bls = find_all_bls(rom, ct_off, 200)
    print(f"\nBL targets:")
    for bl_off, bl_tgt in bls:
        print(f"  0x{0x08000000+bl_off:08X} -> 0x{bl_tgt:08X}")

    # Count BLs per target
    targets = {}
    for _, tgt in bls:
        targets[tgt] = targets.get(tgt, 0) + 1

    for tgt, cnt in targets.items():
        if cnt >= 2:
            print(f"\n  *** CreateTask confirmed: 0x{tgt:08X} (called {cnt}x) ***")

    # Find literal pool values (IWRAM/EWRAM)
    print("\nLiteral pool values (IWRAM/EWRAM):")
    for scan_off in range(ct_off, min(ct_off + 200, len(rom) - 4), 4):
        val = struct.unpack_from("<I", rom, scan_off)[0]
        if 0x03000000 <= val < 0x03008000:
            print(f"  @0x{0x08000000+scan_off:08X}: 0x{val:08X} (IWRAM)")
        elif 0x02000000 <= val < 0x02040000:
            print(f"  @0x{0x08000000+scan_off:08X}: 0x{val:08X} (EWRAM)")

    # =====================================================================
    # PART 3: Identify task function pointers loaded before each BL CreateTask
    # =====================================================================
    print()
    print("=" * 70)
    print("PART 3: Task function pointers")
    print("=" * 70)

    # For each BL to CreateTask, find the preceding LDR R0
    create_task_addr = None
    for tgt, cnt in targets.items():
        if cnt >= 2:
            create_task_addr = tgt

    if create_task_addr:
        for i, (bl_off, bl_tgt) in enumerate(bls):
            if bl_tgt == create_task_addr:
                # Search backward for LDR R0, [PC, #imm]
                for search_off in range(bl_off - 2, max(ct_off, bl_off - 20), -2):
                    hw = struct.unpack_from("<H", rom, search_off)[0]
                    if (hw >> 11) == 0x09 and ((hw >> 8) & 7) == 0:  # LDR R0
                        pc_aligned = ((0x08000000 + search_off + 4) & ~3)
                        imm = (hw & 0xFF) * 4
                        lit_off_local = pc_aligned + imm - 0x08000000
                        if 0 <= lit_off_local < len(rom):
                            task_func = struct.unpack_from("<I", rom, lit_off_local)[0]
                            names = {0: "Task_HandleSendLinkBuffersData",
                                     1: "Task_HandleCopyReceivedLinkBuffersData"}
                            n = names.get(i, f"Task #{i}")
                            print(f"  {n}: 0x{task_func:08X}")
                        break
    else:
        print("  CreateTask not found with 2 calls -- checking all BLs")
        for i, (bl_off, bl_tgt) in enumerate(bls):
            for search_off in range(bl_off - 2, max(ct_off, bl_off - 20), -2):
                hw = struct.unpack_from("<H", rom, search_off)[0]
                if (hw >> 11) == 0x09 and ((hw >> 8) & 7) == 0:
                    pc_aligned = ((0x08000000 + search_off + 4) & ~3)
                    imm = (hw & 0xFF) * 4
                    lit_off_local = pc_aligned + imm - 0x08000000
                    if 0 <= lit_off_local < len(rom):
                        task_func = struct.unpack_from("<I", rom, lit_off_local)[0]
                        print(f"  BL #{i} to 0x{bl_tgt:08X}: R0 = 0x{task_func:08X}")
                    break

    # =====================================================================
    # PART 4: Find gTasks address
    # =====================================================================
    print()
    print("=" * 70)
    print("PART 4: Find gTasks address")
    print("=" * 70)

    # gTasks is COMMON_DATA (BSS in IWRAM). sizeof(Task) = 40, NUM_TASKS = 16, total = 640 bytes.
    # CreateTasksForSendRecvLinkBuffers stores return value of CreateTask into sLinkSendTaskId (EWRAM)
    # then accesses gTasks[taskId].data fields.
    # The decomp shows: gTasks[sLinkSendTaskId].tState = 0, etc.
    # This means the function loads gTasks base address from literal pool.

    # Look for IWRAM addresses in the literal pool that could be gTasks
    # gTasks should be in IWRAM 0x03005Exx range (after gBattlerControllerFuncs at 0x03005D70)
    print("Looking for gTasks in nearby IWRAM references...")

    # CreateTask itself (0x080C6E28) will reference gTasks
    create_task_off = (CREATE_TASK & ~1) - 0x08000000
    print(f"\nCreateTask at 0x{CREATE_TASK:08X}, disassembling:")
    disasm_thumb(rom, create_task_off, 120)

    print(f"\nCreateTask literal pool:")
    for scan_off in range(create_task_off, min(create_task_off + 120, len(rom) - 4), 4):
        val = struct.unpack_from("<I", rom, scan_off)[0]
        if 0x03000000 <= val < 0x03008000:
            print(f"  @0x{0x08000000+scan_off:08X}: 0x{val:08X} (IWRAM) -- possible gTasks")

    # =====================================================================
    # PART 5: Find sLinkSendTaskId and sLinkReceiveTaskId
    # =====================================================================
    print()
    print("=" * 70)
    print("PART 5: sLinkSendTaskId / sLinkReceiveTaskId (EWRAM)")
    print("=" * 70)

    # These are EWRAM_DATA u8 variables stored right after CreateTask returns.
    # The function does:
    #   sLinkSendTaskId = CreateTask(...)
    #   <store R0 to EWRAM via STRB>
    #   gTasks[sLinkSendTaskId]... = 0
    # Look for EWRAM STRB targets after BL CreateTask

    print("Looking for STRB targets after BL CreateTask calls...")
    for bl_off, bl_tgt in bls:
        # After BL, look for STRB R0, [Rn, #0] pattern
        for search_off in range(bl_off + 4, min(bl_off + 16, len(rom) - 2), 2):
            hw = struct.unpack_from("<H", rom, search_off)[0]
            # STRB: 0111 0 imm5 Rn Rd
            if (hw >> 11) == 0x0E:  # STRB Rd, [Rn, #imm5]
                rd = hw & 7
                rn = (hw >> 3) & 7
                imm = (hw >> 6) & 0x1F
                print(f"  After BL @0x{0x08000000+bl_off:08X}: STRB R{rd}, [R{rn}, #0x{imm:X}] at 0x{0x08000000+search_off:08X}")
                break

    # =====================================================================
    # PART 6: Verify NOP patch offset
    # =====================================================================
    print()
    print("=" * 70)
    print("PART 6: Verify NOP patch offset for HandleLinkBattleSetup BL")
    print("=" * 70)

    # The current NOP patch is at 0x06F420, but the BL there goes to 0x0806F0D4,
    # which is PlayerBufferExecCompleted, NOT HandleLinkBattleSetup.
    # We need to find where SetUpBattleVars calls HandleLinkBattleSetup.

    bl_at_nop = decode_bl(rom, NOP_PATCH_OFFSET_HI)
    print(f"Current BL at 0x06F420: -> 0x{bl_at_nop:08X}" if bl_at_nop else "Not a BL at 0x06F420")

    # Search SetUpBattleVars for BL to HandleLinkBattleSetup (0x0803240C)
    print(f"\nSearching SetUpBattleVars (0x{SETUP_BATTLE_VARS_OFFSET:06X}) for BL to HandleLinkBattleSetup (0x{HANDLE_LINK_BATTLE_SETUP:08X})...")
    setup_bls = find_all_bls(rom, SETUP_BATTLE_VARS_OFFSET, 700)  # SetUpBattleVars is 674 bytes
    found_hlbs = False
    for bl_off, bl_tgt in setup_bls:
        # Check if target matches HandleLinkBattleSetup (with or without THUMB bit)
        if (bl_tgt & ~1) == (HANDLE_LINK_BATTLE_SETUP & ~1):
            delta = bl_off - SETUP_BATTLE_VARS_OFFSET
            print(f"  FOUND: BL at 0x{0x08000000+bl_off:08X} (SetUpBattleVars + 0x{delta:X}) -> 0x{bl_tgt:08X}")
            found_hlbs = True

    if not found_hlbs:
        # Maybe HandleLinkBattleSetup is called indirectly, or from SetUpBattleVarsAndBirchZigzagoon
        # In the decomp, HandleLinkBattleSetup() is called from SetUpBattleVarsAndBirchZigzagoon,
        # NOT from SetUpBattleVars. Let me search the BLs for it.
        print("  Not found in SetUpBattleVars. Checking all BLs in SetUpBattleVars range:")
        for bl_off, bl_tgt in setup_bls[:30]:  # Show first 30
            print(f"    0x{0x08000000+bl_off:08X} (+0x{bl_off-SETUP_BATTLE_VARS_OFFSET:X}) -> 0x{bl_tgt:08X}")

    # Also search the broader ROM region around 0x06F1D8 for a BL to 0x0803240C
    print(f"\nSearching wider region 0x06F000-0x06F800 for BL to HandleLinkBattleSetup...")
    for off in range(0x06F000, 0x06F800, 2):
        hw = struct.unpack_from("<H", rom, off)[0]
        if (hw >> 11) == 0x1E:
            target = decode_bl(rom, off)
            if target and (target & ~1) == (HANDLE_LINK_BATTLE_SETUP & ~1):
                print(f"  FOUND: BL at 0x{0x08000000+off:08X} -> 0x{target:08X}")

    # =====================================================================
    # SUMMARY
    # =====================================================================
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"HandleLinkBattleSetup:             0x{HANDLE_LINK_BATTLE_SETUP:08X} (THUMB: 0x{HANDLE_LINK_BATTLE_SETUP | 1:08X})")
    print(f"CreateTasksForSendRecvLinkBuffers: 0x{CREATE_TASKS_ADDR:08X}")
    print(f"CreateTask:                        0x{CREATE_TASK:08X}")

    if create_task_addr:
        print(f"CreateTask (confirmed 2x calls):   0x{create_task_addr:08X}")

    print(f"\nSetUpBattleVars:                   0x{0x08000000 + SETUP_BATTLE_VARS_OFFSET:08X}")


if __name__ == "__main__":
    main()
