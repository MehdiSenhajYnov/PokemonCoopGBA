#!/usr/bin/env python3
"""
find_setup_battle_vars.py — Find SetUpBattleVarsAndBirchZigzagoon and its
HandleLinkBattleSetup call site in the Run & Bun ROM.

Known addresses:
  CB2_InitBattle          = 0x080363C1
  CB2_InitBattleInternal  = 0x0803648D
  SetUpBattleVars (config)= 0x0806F1D9 (actually InitBattleControllers? Need to verify)
  HandleLinkBattleSetup (config) = patched via nopHandleLinkSetup_SetUpBV at ROM 0x032494
  gBattleTypeFlags        = 0x02023364
  gBattleControllerExecFlags = 0x020233E0
  gBattleMainFunc         = 0x03005D04 (IWRAM)
  gBattlerControllerFuncs = 0x03005D70 (IWRAM)

From the decomp:
  void SetUpBattleVarsAndBirchZigzagoon(void) {
      gBattleMainFunc = BeginBattleIntroDummy;
      for (i = 0; i < 4; i++) {
          gBattlerControllerFuncs[i] = BattleControllerDummy;
          gBattlerPositions[i] = 0xFF;
          gActionSelectionCursor[i] = 0;
          gMoveSelectionCursor[i] = 0;
      }
      HandleLinkBattleSetup();          // <-- NOP target for GBA-PK
      gBattleControllerExecFlags = 0;
      ClearBattleAnimationVars();
      BattleAI_SetupItems();
      BattleAI_SetupFlags();
      if (gBattleTypeFlags & BATTLE_TYPE_FIRST_BATTLE) { ... }
  }

  void InitBattleControllers(void) {
      ...
      SetUpBattleVarsAndBirchZigzagoon();   // <-- or inlined
      InitBtlControllersInternal();
      SetBattlePartyIds();
      ...
  }

  InitBattleControllers is called from CB2_InitBattleInternal state machine.

Strategy:
  1. Disassemble CB2_InitBattleInternal to find BL calls
  2. Find which BL target matches InitBattleControllers (large function with many BLs)
  3. Within that function, find SetUpBattleVarsAndBirchZigzagoon (may be inlined)
  4. Within SetUpBattleVars, find BL to HandleLinkBattleSetup
  5. HandleLinkBattleSetup calls CreateTask twice when BATTLE_TYPE_LINK is set

  Also: Look for HandleLinkBattleSetup independently:
  - Small function (<200 bytes)
  - References gBattleTypeFlags (0x02023364)
  - Tests bit 1 (LINK)
  - Calls CreateTask (0x080024E8)
  - Creates Task_HandleSendLinkBuffersData and Task_HandleCopyReceivedLinkBuffersData
"""
import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses
CB2_INIT_BATTLE = 0x080363C1
CB2_INIT_BATTLE_INTERNAL = 0x0803648D
SETUP_BATTLE_VARS_CONFIG = 0x0806F1D9  # From config — may be InitBattleControllers
G_BATTLE_TYPE_FLAGS = 0x02023364
G_BATTLE_CONTROLLER_EXEC_FLAGS = 0x020233E0
G_BATTLE_MAIN_FUNC = 0x03005D04  # IWRAM
G_BATTLER_CONTROLLER_FUNCS = 0x03005D70  # IWRAM
HANDLE_LINK_BATTLE_SETUP_NOP_OFFSET_SETUPBV = 0x032494  # From config
HANDLE_LINK_BATTLE_SETUP_NOP_OFFSET_CB2INIT = 0x036456  # From config


def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()


def decode_bl(hw1, hw2, pc):
    """Decode a THUMB BL instruction pair. Returns target address or None."""
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) in (0xF800, 0xE800):
        offset_hi = hw1 & 0x07FF
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800
        offset_lo = hw2 & 0x07FF
        target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
        return target & 0xFFFFFFFF
    return None


def find_all_bl_in_range(rom, start_offset, end_offset):
    """Find all BL instructions in a ROM range. Returns list of (offset, pc, target)."""
    results = []
    i = start_offset
    while i < end_offset - 3:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        hw2 = struct.unpack_from("<H", rom, i + 2)[0]
        pc = 0x08000000 + i
        bl_target = decode_bl(hw1, hw2, pc)
        if bl_target is not None:
            results.append((i, pc, bl_target))
            i += 4
        else:
            i += 2
    return results


def find_all_bl_to(rom, target_addr, search_start=0, search_end=None):
    """Find all BL instructions that call a specific address."""
    if search_end is None:
        search_end = min(len(rom), 0x02000000)
    target_clean = target_addr & ~1  # Remove THUMB bit
    results = []
    i = search_start
    while i < search_end - 3:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        hw2 = struct.unpack_from("<H", rom, i + 2)[0]
        pc = 0x08000000 + i
        bl_target = decode_bl(hw1, hw2, pc)
        if bl_target is not None:
            if (bl_target & ~1) == target_clean:
                results.append((i, pc))
            i += 4
        else:
            i += 2
    return results


def find_literal_pool_refs(rom, value, search_start=0, search_end=None):
    """Find all literal pool entries containing a specific 32-bit value."""
    if search_end is None:
        search_end = min(len(rom), 0x02000000)
    value_bytes = struct.pack("<I", value)
    results = []
    pos = search_start
    while True:
        idx = rom.find(value_bytes, pos, search_end)
        if idx == -1:
            break
        results.append(idx)
        pos = idx + 4
    return results


def find_function_start(rom, addr_within):
    """Search backward for PUSH {Rn..., LR} to find function start."""
    offset = addr_within
    for back in range(0, 500, 2):
        if offset - back < 0:
            break
        hw = struct.unpack_from("<H", rom, offset - back)[0]
        # PUSH {Rn, ..., LR} pattern: B5xx
        if (hw & 0xFF00) == 0xB500:
            return offset - back
        # PUSH {Rn, ...} without LR: B4xx
        if (hw & 0xFE00) == 0xB400 and back > 0:
            return offset - back
    return None


def decode_ldr_pc(hw, addr, rom):
    """Decode LDR Rd, [PC, #imm8*4] and return (rd, pool_value) or None."""
    if (hw & 0xF800) == 0x4800:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        pool_addr = ((addr + 4) & ~3) + imm
        pool_offset = pool_addr - 0x08000000
        if 0 <= pool_offset < len(rom) - 3:
            val = struct.unpack_from("<I", rom, pool_offset)[0]
            return (rd, val)
    return None


def disasm_function_summary(rom, func_offset, max_bytes=800):
    """Disassemble a function and return summary info."""
    bls = []
    literals = []
    size = 0

    i = 0
    while i < max_bytes:
        if func_offset + i + 1 >= len(rom):
            break

        hw = struct.unpack_from("<H", rom, func_offset + i)[0]
        addr = 0x08000000 + func_offset + i

        # BL
        if i + 3 < max_bytes and func_offset + i + 3 < len(rom):
            hw2 = struct.unpack_from("<H", rom, func_offset + i + 2)[0]
            bl_target = decode_bl(hw, hw2, addr)
            if bl_target is not None:
                bls.append((i, bl_target))
                i += 4
                continue

        # LDR PC-relative
        ldr = decode_ldr_pc(hw, addr, rom)
        if ldr is not None:
            literals.append((i, ldr[0], ldr[1]))

        # POP {PC} = function end
        if (hw & 0xFF00) == 0xBD00 and i > 4:
            size = i + 2
            break

        # BX LR
        if hw == 0x4770 and i > 4:
            size = i + 2
            break

        i += 2

    if size == 0:
        size = i

    return {
        "offset": func_offset,
        "addr": 0x08000000 + func_offset,
        "size": size,
        "bls": bls,
        "literals": literals,
    }


def main():
    rom = read_rom()
    print(f"ROM loaded: {len(rom)} bytes")
    print()

    # ====================================================================
    # PART 1: Analyze the function at config's SetUpBattleVars (0x0806F1D9)
    # ====================================================================
    setup_offset = (SETUP_BATTLE_VARS_CONFIG & ~1) - 0x08000000  # 0x06F1D8
    print("=" * 70)
    print(f"PART 1: Analyze function at config SetUpBattleVars = 0x{SETUP_BATTLE_VARS_CONFIG:08X}")
    print(f"  ROM offset: 0x{setup_offset:06X}")
    print("=" * 70)

    info = disasm_function_summary(rom, setup_offset, max_bytes=1000)
    print(f"  Size: {info['size']} bytes ({info['size']:#x})")
    print(f"  BL calls: {len(info['bls'])}")
    print(f"  Literal pool refs: {len(info['literals'])}")
    print()

    # Check if this looks like SetUpBattleVars or InitBattleControllers
    # SetUpBattleVars should be ~100-200 bytes with ~7 BLs
    # InitBattleControllers should be ~400-700 bytes with ~20+ BLs
    if info['size'] > 400 and len(info['bls']) > 15:
        print("  VERDICT: This is likely InitBattleControllers (large, many BLs)")
        print("           SetUpBattleVarsAndBirchZigzagoon may be INLINED into it.")
    elif info['size'] < 300 and len(info['bls']) < 12:
        print("  VERDICT: This could be SetUpBattleVarsAndBirchZigzagoon (small, few BLs)")
    else:
        print("  VERDICT: Ambiguous size")
    print()

    # Print BL targets
    print("  BL calls:")
    for bl_off, bl_target in info['bls']:
        # Check if target is HandleLinkBattleSetup area
        abs_off = setup_offset + bl_off
        marker = ""
        if abs_off == HANDLE_LINK_BATTLE_SETUP_NOP_OFFSET_SETUPBV:
            marker = " <-- HandleLinkBattleSetup NOP target (config)"
        elif abs_off == HANDLE_LINK_BATTLE_SETUP_NOP_OFFSET_SETUPBV - 2:
            marker = " <-- HandleLinkBattleSetup NOP target -2"
        print(f"    +0x{bl_off:03X} (ROM 0x{abs_off:06X}): BL 0x{bl_target:08X}{marker}")
    print()

    # Print interesting literals
    print("  Key literal pool references:")
    for lit_off, lit_rd, lit_val in info['literals']:
        tag = ""
        if lit_val == G_BATTLE_TYPE_FLAGS:
            tag = " = gBattleTypeFlags"
        elif lit_val == G_BATTLE_CONTROLLER_EXEC_FLAGS:
            tag = " = gBattleControllerExecFlags"
        elif lit_val == G_BATTLE_MAIN_FUNC:
            tag = " = gBattleMainFunc (IWRAM)"
        elif lit_val == G_BATTLER_CONTROLLER_FUNCS:
            tag = " = gBattlerControllerFuncs (IWRAM)"
        elif lit_val == 0x020233EE:
            tag = " = gBattlerPositions"
        elif lit_val == 0x020233E4:
            tag = " = gBattlersCount"

        if tag or lit_val in (0x02023364, 0x020233E0, 0x03005D04, 0x03005D70):
            print(f"    +0x{lit_off:03X}: R{lit_rd} = 0x{lit_val:08X}{tag}")
    print()

    # ====================================================================
    # PART 2: Verify the NOP targets in config
    # ====================================================================
    print("=" * 70)
    print("PART 2: Verify HandleLinkBattleSetup NOP targets from config")
    print("=" * 70)

    nop_targets = [
        ("nopHandleLinkSetup_SetUpBV", HANDLE_LINK_BATTLE_SETUP_NOP_OFFSET_SETUPBV),
        ("nopHandleLinkSetup_CB2Init", HANDLE_LINK_BATTLE_SETUP_NOP_OFFSET_CB2INIT),
    ]

    for name, rom_off in nop_targets:
        if rom_off + 3 >= len(rom):
            print(f"  {name} at ROM 0x{rom_off:06X}: OUT OF RANGE")
            continue

        hw1 = struct.unpack_from("<H", rom, rom_off)[0]
        hw2 = struct.unpack_from("<H", rom, rom_off + 2)[0]
        pc = 0x08000000 + rom_off
        bl_target = decode_bl(hw1, hw2, pc)

        if bl_target is not None:
            print(f"  {name} at ROM 0x{rom_off:06X}: BL 0x{bl_target:08X}")

            # Analyze the BL target (HandleLinkBattleSetup?)
            target_offset = (bl_target & ~1) - 0x08000000
            if 0 <= target_offset < len(rom):
                target_info = disasm_function_summary(rom, target_offset, max_bytes=400)
                print(f"    Target function at 0x{bl_target:08X}: {target_info['size']} bytes, {len(target_info['bls'])} BLs")

                # Check if it references gBattleTypeFlags
                refs_btf = any(v == G_BATTLE_TYPE_FLAGS for _, _, v in target_info['literals'])
                print(f"    References gBattleTypeFlags: {refs_btf}")

                # Print its BL calls
                for bl_off, bl_t in target_info['bls']:
                    print(f"      +0x{bl_off:03X}: BL 0x{bl_t:08X}")
        elif hw1 == 0x46C0 and hw2 == 0x46C0:
            print(f"  {name} at ROM 0x{rom_off:06X}: Already NOP'd (0x46C0 0x46C0)")
        else:
            print(f"  {name} at ROM 0x{rom_off:06X}: 0x{hw1:04X} 0x{hw2:04X} (NOT a BL instruction)")
    print()

    # ====================================================================
    # PART 3: Find HandleLinkBattleSetup independently
    # ====================================================================
    print("=" * 70)
    print("PART 3: Independent search for HandleLinkBattleSetup")
    print("  Criteria: loads gBattleTypeFlags, tests LINK bit, calls CreateTask")
    print("=" * 70)

    # Find all literal pool references to gBattleTypeFlags
    btf_refs = find_literal_pool_refs(rom, G_BATTLE_TYPE_FLAGS, 0x030000, 0x200000)
    print(f"\n  gBattleTypeFlags literal pool entries: {len(btf_refs)}")

    # For each, try to find the LDR instruction that loads it, then check if
    # nearby there's a test for bit 1 and a BL to a CreateTask-like function
    candidates = []
    for pool_off in btf_refs:
        # Search backward for LDR Rn, [PC, #imm] pointing to this pool entry
        for back in range(4, 512, 2):
            if pool_off - back < 0:
                break
            hw = struct.unpack_from("<H", rom, pool_off - back)[0]
            if (hw & 0xF800) == 0x4800:
                rd = (hw >> 8) & 7
                imm = (hw & 0xFF) * 4
                ldr_addr = 0x08000000 + pool_off - back
                ldr_target = ((ldr_addr + 4) & ~3) + imm
                actual_pool_off = ldr_target - 0x08000000
                if actual_pool_off == pool_off:
                    ldr_offset = pool_off - back
                    # Found the LDR. Now find function start.
                    func_start = find_function_start(rom, ldr_offset)
                    if func_start is not None:
                        func_info = disasm_function_summary(rom, func_start, max_bytes=300)
                        # HandleLinkBattleSetup should be small (<200 bytes) with 2-4 BLs
                        if func_info['size'] < 200 and 2 <= len(func_info['bls']) <= 6:
                            candidates.append({
                                "func_start": func_start,
                                "func_addr": 0x08000000 + func_start,
                                "ldr_offset": ldr_offset,
                                "info": func_info,
                            })
                    break

    # Deduplicate by function start
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c["func_start"] not in seen:
            seen.add(c["func_start"])
            unique_candidates.append(c)

    print(f"  HandleLinkBattleSetup candidates: {len(unique_candidates)}")
    print()

    for c in unique_candidates:
        info = c["info"]
        print(f"  Function at 0x{c['func_addr']:08X} (ROM 0x{c['func_start']:06X}):")
        print(f"    Size: {info['size']} bytes, {len(info['bls'])} BLs")

        # Check who calls this function
        callers = find_all_bl_to(rom, c['func_addr'] | 1, 0x030000, 0x200000)
        print(f"    Called from {len(callers)} location(s):")
        for co, cpc in callers[:5]:
            caller_func = find_function_start(rom, co)
            caller_label = ""
            if caller_func is not None:
                caller_faddr = 0x08000000 + caller_func
                if caller_faddr == SETUP_BATTLE_VARS_CONFIG & ~1:
                    caller_label = " (= config SetUpBattleVars / InitBattleControllers)"
                elif caller_faddr == CB2_INIT_BATTLE_INTERNAL & ~1:
                    caller_label = " (= CB2_InitBattleInternal)"
            print(f"      ROM 0x{co:06X} (0x{cpc:08X}){caller_label}")

        # Print BLs within this function
        print(f"    Internal BL calls:")
        for bl_off, bl_target in info['bls']:
            print(f"      +0x{bl_off:03X}: BL 0x{bl_target:08X}")

        # Check literals
        refs_btf = any(v == G_BATTLE_TYPE_FLAGS for _, _, v in info['literals'])
        print(f"    References gBattleTypeFlags: {refs_btf}")
        print()

    # ====================================================================
    # PART 4: Analyze BL at config NOP offsets to identify the exact
    #         HandleLinkBattleSetup function
    # ====================================================================
    print("=" * 70)
    print("PART 4: Trace the BL target from NOP offset 0x032494")
    print("=" * 70)

    # The config says SetUpBattleVars at 0x0806F1D9, BL HandleLinkBattleSetup at +0x040 (ROM 0x032494).
    # Wait -- ROM 0x032494 is NOT near 0x06F1D8. This is in a different region!
    # SetUpBattleVars is supposedly at 0x08032455 based on offset 0x032454, and
    # the BL at 0x032494 is at +0x040 from 0x032454.
    # But config says SetUpBattleVars = 0x0806F1D9...
    # Let me check both.

    # Let's find which function contains ROM 0x032494
    func_containing_032494 = find_function_start(rom, 0x032494)
    if func_containing_032494 is not None:
        func_addr = 0x08000000 + func_containing_032494
        print(f"\n  ROM 0x032494 is inside function at 0x{func_addr:08X} (ROM 0x{func_containing_032494:06X})")
        offset_within = 0x032494 - func_containing_032494
        print(f"    Offset within function: +0x{offset_within:03X}")

        # Disassemble this function
        info = disasm_function_summary(rom, func_containing_032494, max_bytes=800)
        print(f"    Size: {info['size']} bytes, {len(info['bls'])} BLs")

        # Check what function this is
        callers = find_all_bl_to(rom, func_addr | 1, 0x030000, 0x200000)
        print(f"    Called from {len(callers)} location(s):")
        for co, cpc in callers[:5]:
            print(f"      ROM 0x{co:06X} (0x{cpc:08X})")

        # Print BLs
        print(f"    BL calls:")
        for bl_off, bl_target in info['bls']:
            abs_off = func_containing_032494 + bl_off
            marker = ""
            if abs_off == 0x032494:
                marker = " <-- NOP target (config nopHandleLinkSetup_SetUpBV)"
            print(f"      +0x{bl_off:03X} (ROM 0x{abs_off:06X}): BL 0x{bl_target:08X}{marker}")

        # Print key literals
        print(f"    Key literals:")
        for lit_off, lit_rd, lit_val in info['literals']:
            tag = ""
            if lit_val == G_BATTLE_TYPE_FLAGS: tag = " = gBattleTypeFlags"
            elif lit_val == G_BATTLE_CONTROLLER_EXEC_FLAGS: tag = " = gBattleControllerExecFlags"
            elif lit_val == G_BATTLE_MAIN_FUNC: tag = " = gBattleMainFunc"
            elif lit_val == G_BATTLER_CONTROLLER_FUNCS: tag = " = gBattlerControllerFuncs"
            elif lit_val == 0x020233EE: tag = " = gBattlerPositions"

            if tag:
                print(f"      +0x{lit_off:03X}: R{lit_rd} = 0x{lit_val:08X}{tag}")
    print()

    # ====================================================================
    # PART 5: Analyze the BL target AT 0x032494
    # ====================================================================
    print("=" * 70)
    print("PART 5: What does the BL at ROM 0x032494 actually call?")
    print("=" * 70)

    hw1 = struct.unpack_from("<H", rom, 0x032494)[0]
    hw2 = struct.unpack_from("<H", rom, 0x032496)[0]
    pc = 0x08000000 + 0x032494
    bl_target = decode_bl(hw1, hw2, pc)

    if bl_target is not None:
        print(f"\n  BL at ROM 0x032494 -> 0x{bl_target:08X}")
        target_offset = (bl_target & ~1) - 0x08000000
        if 0 <= target_offset < len(rom):
            target_info = disasm_function_summary(rom, target_offset, max_bytes=400)
            print(f"  Target: 0x{bl_target:08X}, {target_info['size']} bytes, {len(target_info['bls'])} BLs")

            refs_btf = any(v == G_BATTLE_TYPE_FLAGS for _, _, v in target_info['literals'])
            print(f"  References gBattleTypeFlags: {refs_btf}")

            print(f"\n  BL calls within target:")
            for bl_off, bl_t in target_info['bls']:
                print(f"    +0x{bl_off:03X}: BL 0x{bl_t:08X}")

            print(f"\n  Key literals in target:")
            for lit_off, lit_rd, lit_val in target_info['literals']:
                tag = ""
                if lit_val == G_BATTLE_TYPE_FLAGS: tag = " = gBattleTypeFlags"
                elif lit_val == 0x03005E00: tag = " = gTasks (IWRAM)"
                elif lit_val == 0x030030FC: tag = " = gWirelessCommType (IWRAM)"
                elif lit_val == 0x03003124: tag = " = gReceivedRemoteLinkPlayers (IWRAM)"
                elif lit_val >= 0x08000000 and lit_val < 0x0A000000: tag = " = ROM function ptr"
                print(f"    +0x{lit_off:03X}: R{lit_rd} = 0x{lit_val:08X}{tag}")

            # Is this HandleLinkBattleSetup?
            if refs_btf and target_info['size'] < 200:
                print("\n  VERDICT: This is likely HandleLinkBattleSetup!")
            elif refs_btf:
                print("\n  VERDICT: References gBattleTypeFlags but larger than expected")
            else:
                print("\n  VERDICT: Does NOT reference gBattleTypeFlags - maybe NOT HandleLinkBattleSetup")
    elif hw1 == 0x46C0 and hw2 == 0x46C0:
        print(f"\n  ROM 0x032494: Already NOP'd (0x46C0 0x46C0) — was patched in a previous session!")
        print("  Restart mGBA with clean ROM to see original instruction.")
    else:
        print(f"\n  ROM 0x032494: 0x{hw1:04X} 0x{hw2:04X} — NOT a BL instruction")
    print()

    # ====================================================================
    # PART 6: Same analysis for CB2_InitBattleInternal's HandleLinkBattleSetup call
    # ====================================================================
    print("=" * 70)
    print("PART 6: BL at ROM 0x036456 (CB2_InitBattleInternal's HandleLinkBattleSetup)")
    print("=" * 70)

    hw1 = struct.unpack_from("<H", rom, 0x036456)[0]
    hw2 = struct.unpack_from("<H", rom, 0x036458)[0]
    pc = 0x08000000 + 0x036456
    bl_target = decode_bl(hw1, hw2, pc)

    if bl_target is not None:
        print(f"\n  BL at ROM 0x036456 -> 0x{bl_target:08X}")
        target_offset = (bl_target & ~1) - 0x08000000
        if 0 <= target_offset < len(rom):
            target_info = disasm_function_summary(rom, target_offset, max_bytes=400)
            print(f"  Target: 0x{bl_target:08X}, {target_info['size']} bytes, {len(target_info['bls'])} BLs")
            refs_btf = any(v == G_BATTLE_TYPE_FLAGS for _, _, v in target_info['literals'])
            print(f"  References gBattleTypeFlags: {refs_btf}")
    elif hw1 == 0x46C0 and hw2 == 0x46C0:
        print(f"\n  ROM 0x036456: Already NOP'd (0x46C0 0x46C0)")
    else:
        print(f"\n  ROM 0x036456: 0x{hw1:04X} 0x{hw2:04X}")
    print()

    # ====================================================================
    # PART 7: Verify the REAL SetUpBattleVarsAndBirchZigzagoon location
    # ====================================================================
    print("=" * 70)
    print("PART 7: Find the real SetUpBattleVarsAndBirchZigzagoon")
    print("  Search for function that: stores to gBattleMainFunc, loops 4x storing 0xFF,")
    print("  calls HandleLinkBattleSetup, stores 0 to gBattleControllerExecFlags")
    print("=" * 70)

    # Look for literal pool entries of gBattleMainFunc (0x03005D04 IWRAM)
    bmf_refs = find_literal_pool_refs(rom, G_BATTLE_MAIN_FUNC, 0x030000, 0x200000)
    print(f"\n  gBattleMainFunc literal pool entries: {len(bmf_refs)}")

    for pool_off in bmf_refs:
        func_start = find_function_start(rom, pool_off)
        if func_start is None:
            continue

        func_info = disasm_function_summary(rom, func_start, max_bytes=500)
        func_addr = 0x08000000 + func_start

        # Also check if function references gBattleControllerExecFlags
        refs_ecf = any(v == G_BATTLE_CONTROLLER_EXEC_FLAGS for _, _, v in func_info['literals'])
        refs_bcf = any(v == G_BATTLER_CONTROLLER_FUNCS for _, _, v in func_info['literals'])

        # SetUpBattleVars should reference both gBattleMainFunc AND gBattlerControllerFuncs
        # and store 0 to gBattleControllerExecFlags
        if refs_ecf and refs_bcf:
            print(f"\n  MATCH: Function at 0x{func_addr:08X} (ROM 0x{func_start:06X})")
            print(f"    Size: {func_info['size']} bytes, {len(func_info['bls'])} BLs")
            print(f"    Refs gBattleControllerExecFlags: {refs_ecf}")
            print(f"    Refs gBattlerControllerFuncs: {refs_bcf}")

            # Check callers
            callers = find_all_bl_to(rom, func_addr | 1, 0x030000, 0x200000)
            print(f"    Called from {len(callers)} location(s):")
            for co, cpc in callers[:5]:
                print(f"      ROM 0x{co:06X} (0x{cpc:08X})")

            # Print BLs
            print(f"    BL calls:")
            for bl_off, bl_t in func_info['bls']:
                abs_off = func_start + bl_off
                marker = ""
                if abs_off == 0x032494:
                    marker = " <-- HandleLinkBattleSetup NOP target"
                print(f"      +0x{bl_off:03X} (ROM 0x{abs_off:06X}): BL 0x{bl_t:08X}{marker}")
    print()

    # ====================================================================
    # SUMMARY
    # ====================================================================
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"""
Key findings:
  - Config SetUpBattleVars (0x{SETUP_BATTLE_VARS_CONFIG:08X}): Check PART 1 for whether this
    is actually InitBattleControllers or SetUpBattleVars.
  - HandleLinkBattleSetup NOP targets:
    * SetUpBV call: ROM 0x{HANDLE_LINK_BATTLE_SETUP_NOP_OFFSET_SETUPBV:06X}
    * CB2Init call: ROM 0x{HANDLE_LINK_BATTLE_SETUP_NOP_OFFSET_CB2INIT:06X}
  - The NOP patches (0x46C0 0x46C0) replace the 4-byte BL instruction with 2 NOP halfwords.
    This prevents HandleLinkBattleSetup from creating link buffer tasks.
""")


if __name__ == "__main__":
    main()
