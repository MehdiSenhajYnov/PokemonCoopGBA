import struct

with open('C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/rom/Pokemon RunBun.gba', 'rb') as f:
    func_start = 0x037B44
    f.seek(func_start)
    data = f.read(0x630)  # Full function + literal pool

    # 1. Jump table analysis
    print("=== JUMP TABLE (loaded at func+0x40) ===")
    # The literal pool at func+0x2E loads the jump table base from [PC+16]
    # PC = func+0x30, aligned = func+0x30, +16 = func+0x40
    # Value at func+0x40 = 0x08037B88 (the jump table base address)
    jt_base_val = struct.unpack_from('<I', data, 0x40)[0]
    print(f"Jump table base address (loaded by LDR at +0x2E): 0x{jt_base_val:08X}")
    # Jump table starts at ROM 0x037B88 = func+0x44
    jt_offset = jt_base_val - 0x08000000 - func_start
    print(f"Jump table starts at func+0x{jt_offset:04X}")
    print(f"Bounds check: CMP R0, #10 -> states 0-10 (11 entries)")
    print()
    for i in range(11):
        entry_off = jt_offset + i * 4
        target = struct.unpack_from('<I', data, entry_off)[0]
        func_off = target - 0x08000000 - func_start
        print(f"  State {i:2d}: 0x{target:08X} = func+0x{func_off:04X}")

    # Calculate state ranges
    state_starts = []
    for i in range(11):
        entry_off = jt_offset + i * 4
        target = struct.unpack_from('<I', data, entry_off)[0]
        func_off = target - 0x08000000 - func_start
        state_starts.append((i, func_off))
    state_starts.append((11, 0x600))  # epilogue

    print("\n=== STATE RANGES ===")
    for i in range(len(state_starts)-1):
        s, start = state_starts[i]
        _, end = state_starts[i+1]
        size = end - start
        print(f"  State {s}: +0x{start:04X} to +0x{end-1:04X} ({size} bytes)")

    # 2. Find ALL BL instructions in the function
    print("\n=== ALL BL CALLS IN FUNCTION ===")
    known = {
        0x0800A568: "IsLinkTaskFinished",
        0x0800A598: "GetBlockReceivedStatus",
        0x0800A4D8: "BitmaskAllOtherLinkPlayers",
        0x0800A4F4: "SendBlock",
        0x0800A5FC: "ResetBlockReceivedFlags",
        0x08000544: "SetMainCallback2",
        0x08347BB4: "memcpy",
        0x08001AE4: "IsDma3ManagerBusyWithBgCopy?",
        0x08001B40: "ShowBg",
        0x080776D0: "SetGpuReg?",
        0x080367A8: "SetAllPlayersBerryData?",
        0x08036890: "func_36890",
        0x0800A4B0: "func_A4B0",
        0x080C6F84: "RunTasks",
        0x080069D0: "AnimateSprites",
        0x08006A1C: "BuildOamBuffer",
        0x0800E120: "func_E120",
        0x0800DFEC: "func_DFEC",
        0x08036958: "func_36958",
        0x080C6E28: "func_C6E28",
        0x081B7258: "func_1B7258",
        0x08076964: "func_76964",
    }

    i = 0
    while i < len(data) - 3:
        instr = struct.unpack_from('<H', data, i)[0]
        if (instr >> 11) == 0b11110:
            instr2 = struct.unpack_from('<H', data, i+2)[0]
            if (instr2 >> 11) == 0b11111:
                off_hi = instr & 0x7FF
                off_lo = instr2 & 0x7FF
                offset = (off_hi << 12) | (off_lo << 1)
                if offset & 0x400000: offset -= 0x800000
                target = 0x08000000 + func_start + i + 4 + offset

                # Find which state this is in
                state = "?"
                for si in range(len(state_starts)-1):
                    s, start = state_starts[si]
                    _, end = state_starts[si+1]
                    if start <= i < end:
                        state = str(s)
                        break
                if i < state_starts[0][1]:
                    state = "prologue"

                name = known.get(target, "")
                print(f"  +0x{i:04X} [State {state:>3s}]: BL 0x{target:08X}  {name}")
                i += 4
                continue
        i += 2

    # 3. Find all literal pool references
    print("\n=== KEY LITERAL POOL VALUES ===")
    known_addrs = {
        0x02023364: "gBattleTypeFlags",
        0x0202370E: "gBattleCommunication",
        0x02023A98: "gPlayerParty",
        0x02023CF0: "gEnemyParty",
        0x030022C0: "gMain",
        0x03005D70: "gBattlerControllerFuncs",
        0x020233E0: "gBattleControllerExecFlags",
        0x020233FC: "gBattleMons",
        0x02023A0C: "gBattleStruct_ptr",
        0x0803816D: "BattleMainCB2",
        0x080363C1: "CB2_InitBattle",
        0x08000544: "SetMainCallback2",
    }

    # Scan literal pool area (after epilogue)
    for off in range(0x600, min(0x628, len(data)-3), 4):
        val = struct.unpack_from('<I', data, off)[0]
        name = known_addrs.get(val, "")
        if name or (0x02000000 <= val <= 0x0203FFFF) or (0x03000000 <= val <= 0x03007FFF) or (0x08000000 <= val <= 0x09FFFFFF):
            print(f"  +0x{off:04X}: 0x{val:08X}  {name}")

    # Also scan inline literal pools within states
    # Check all literal pool references (LDR Rd, [PC, #imm])
    print("\n=== ALL LDR PC-RELATIVE REFS ===")
    i = 0
    while i < 0x600:
        instr = struct.unpack_from('<H', data, i)[0]
        if (instr >> 13) == 0b01001:
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            pool_addr_rom = ((func_start + i + 4) & ~3) + imm
            pool_off = pool_addr_rom - func_start
            if pool_off < len(data) - 3:
                pool_val = struct.unpack_from('<I', data, pool_off)[0]
                name = known_addrs.get(pool_val, "")

                # Find state
                state = "?"
                for si in range(len(state_starts)-1):
                    s, start = state_starts[si]
                    _, end = state_starts[si+1]
                    if start <= i < end:
                        state = str(s)
                        break

                if name or (0x02000000 <= pool_val <= 0x0203FFFF) or (0x03000000 <= pool_val <= 0x03007FFF):
                    print(f"  +0x{i:04X} [State {state:>3s}]: LDR R{rd}, [PC] → pool+0x{pool_off:04X} = 0x{pool_val:08X}  {name}")
        i += 2

    # 4. Specifically analyze state 1 code for SendBlock patch target
    print("\n=== STATE 1 DETAILED (+0xB4 - +0x15C) ===")
    print("Looking for SendBlock call to NOP...")
    # State 1 checks BATTLE_TYPE_LINK, then calls IsLinkTaskFinished,
    # then calls SendBlock. We want to NOP the SendBlock BL.
    # From earlier analysis: SendBlock BL is at +0x0102
    print(f"  SendBlock BL at func+0x0102 (4 bytes: +0x0102 and +0x0104)")
    print(f"  ROM offset for NOP: 0x{func_start + 0x0102:06X} and 0x{func_start + 0x0104:06X}")
    print(f"  Cart0 offset: 0x{func_start + 0x0102:06X} and 0x{func_start + 0x0104:06X}")

    # 5. Analyze memcpy calls in state 4
    print("\n=== STATE 4 MEMCPY ANALYSIS (+0x254 - +0x348) ===")
    print("Searching for memcpy BL instructions in state 4...")
    i = 0x254
    while i < 0x348:
        instr = struct.unpack_from('<H', data, i)[0]
        if (instr >> 11) == 0b11110:
            instr2 = struct.unpack_from('<H', data, i+2)[0]
            if (instr2 >> 11) == 0b11111:
                off_hi = instr & 0x7FF
                off_lo = instr2 & 0x7FF
                offset = (off_hi << 12) | (off_lo << 1)
                if offset & 0x400000: offset -= 0x800000
                target = 0x08000000 + func_start + i + 4 + offset
                name = known.get(target, "")
                if target == 0x08347BB4:
                    print(f"  MEMCPY at +0x{i:04X}: BL 0x{target:08X}")
                    print(f"    NOP hi: ROM 0x{func_start + i:06X}, NOP lo: ROM 0x{func_start + i + 2:06X}")
                    # Check what R2 (size) was set to before this call
                    for j in range(i-10, i, 2):
                        if j >= 0:
                            prev = struct.unpack_from('<H', data, j)[0]
                            if (prev >> 8) & 0xF8 == 0x20:
                                rd = (prev >> 8) & 7
                                val = prev & 0xFF
                                if rd == 2:
                                    print(f"    Size: R2 = {val} (0x{val:02X}) set at +0x{j:04X}")
                i += 4
                continue
        i += 2
