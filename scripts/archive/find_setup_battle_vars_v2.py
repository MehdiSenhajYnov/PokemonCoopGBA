#!/usr/bin/env python3
"""
Find the REAL SetUpBattleVarsAndBirchZigzagoon by its unique signature:
- It stores a pointer (BeginBattleIntroDummy) to gBattleMainFunc
- gBattleMainFunc should be near gBattleCommunication (0x0202370E) and other battle globals
- It then loops 4x storing to gBattlerControllerFuncs, gBattlerPositions, etc.
- Then calls HandleLinkBattleSetup()
- Then stores 0 to gBattleControllerExecFlags (0x020233E0)

Also: let's look at what function calls the BL at ROM 0x06F2D8.
The key question: is 0x0806F1D8 really SetUpBattleVarsAndBirchZigzagoon, or is it something else?

Let's check InitBattleControllers (line 98 of decomp) which is called from CB2_InitBattleInternal.
Actually the issue is: 0x0806F1D8 may be InitBattleControllers, not SetUpBattleVars.
SetUpBattleVars is called FROM InitBattleControllers!

Let's search for SetUpBattleVars as a small function that:
1. References gBattleMainFunc
2. Has a loop storing 0xFF to gBattlerPositions
3. Calls HandleLinkBattleSetup
4. Stores 0 to gBattleControllerExecFlags

But also: InitBattleControllers CALLS SetUpBattleVars. So let's look for the call chain.
"""
import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_bl(hw1, hw2, pc):
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) in (0xF800, 0xE800):
        offset_hi = hw1 & 0x07FF
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800
        offset_lo = hw2 & 0x07FF
        target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
        return target & 0xFFFFFFFF
    return None

def find_all_bl_to(rom, target_addr, search_start=0, search_end=None):
    """Find all BL instructions in the ROM that call target_addr."""
    if search_end is None:
        search_end = min(len(rom), 0x02000000)  # Search code region

    results = []
    i = search_start
    while i < search_end - 4:
        hw1 = struct.unpack_from("<H", rom, i)[0]
        hw2 = struct.unpack_from("<H", rom, i + 2)[0]
        pc = 0x08000000 + i
        bl_target = decode_bl(hw1, hw2, pc)
        if bl_target is not None:
            if (bl_target & ~1) == (target_addr & ~1):
                results.append((i, pc))
            i += 4
        else:
            i += 2
    return results

def main():
    rom = read_rom()

    # Known: the function at 0x080721DC is called from 0x06F2D8 and 0x06F318
    # Let's check if 0x080721DC is NOT HandleLinkBattleSetup but something else

    # First, let's look at who calls 0x080721DC
    print("=== Finding all callers of 0x080721DC ===")
    callers = find_all_bl_to(rom, 0x080721DC)
    for offset, pc in callers:
        print(f"  ROM 0x{offset:06X} (0x{pc:08X})")

    # The decomp says HandleLinkBattleSetup is called ONLY from SetUpBattleVarsAndBirchZigzagoon
    # If 0x080721DC has many callers, it's NOT HandleLinkBattleSetup
    print(f"  Total callers: {len(callers)}")
    print()

    # Now let's think differently. GBA-PK patches SetUpBattleVars+0x42.
    # In vanilla Emerald, SetUpBattleVars is at around 0x08016918 (for US).
    # The +0x42 offset means the BL to HandleLinkBattleSetup is at byte offset 0x42 from func start.
    # HandleLinkBattleSetup in vanilla is a separate small function.

    # In R&B expansion, SetUpBattleVarsAndBirchZigzagoon might be INLINED into InitBattleControllers.
    # OR it might be a separate function that's called from InitBattleControllers.

    # Let's find InitBattleControllers. We know it's called from CB2_InitBattleInternal (0x0803648D).
    # CB2_InitBattleInternal is a state machine with multiple states.
    # State that calls InitBattleControllers would load its address and call it.

    # Actually, let's approach this differently.
    # The function at 0x0806F1D8 IS InitBattleControllers (it's huge with many branches).
    # SetUpBattleVarsAndBirchZigzagoon is called from it.
    # Let's find all BL calls FROM 0x0806F1D8 function and identify which one calls SetUpBattleVars.

    # The first thing SetUpBattleVars does is:
    # gBattleMainFunc = BeginBattleIntroDummy;
    # gBattleMainFunc is referenced via gBattleResources or directly

    # Let's find gBattleMainFunc. It's used everywhere in battle.
    # In expansion: gBattleMainFunc = 0x02023A3C based on the literal pool (we see it in disasm)

    # Wait - from the disasm at +0x04A, we see LDR R1, =0x02023A3C used as storage target.
    # gBattleMainFunc in vanilla is at the start of battle BSS.

    # Let's look for a SMALL function (PUSH...POP) that:
    # - Stores something to 0x02023A3C (gBattleMainFunc)
    # - Has a loop (stores 0xFF = gBattlerPositions)
    # - Calls something then stores 0 to gBattleControllerExecFlags

    # Actually, the compiler may have INLINED SetUpBattleVarsAndBirchZigzagoon.
    # In -O2 optimization, small functions get inlined.
    # If that's the case, HandleLinkBattleSetup is called directly from InitBattleControllers.

    # Let's check: is 0x0806F1D8 (InitBattleControllers) the function that contains the
    # "store to gBattleMainFunc" + "HandleLinkBattleSetup call" sequence?

    # From the disasm, at +0x04A we see gBattleMainFunc (0x02023A3C) being loaded,
    # and at +0x06C, STR R0, [R1, #0x0] stores to it (R0=0 at that point, or conditional).

    # Let's look at where gBattleControllerExecFlags (0x020233E0) is stored to 0 in the function
    print("=== Searching for store 0 to gBattleControllerExecFlags in InitBattleControllers region ===")

    # Look for literal pool entry 0x020233E0 in the function area
    btf_bytes = struct.pack("<I", 0x020233E0)
    pos = 0x06F1D8
    end = 0x06F600  # generous range
    while pos < end:
        idx = rom.find(btf_bytes, pos, end)
        if idx == -1:
            break
        print(f"  gBattleControllerExecFlags literal at ROM 0x{idx:06X}")
        pos = idx + 4

    print()

    # So the function at 0x0806F1D8 is InitBattleControllers.
    # The BL at +0x100 to 0x080721DC is NOT HandleLinkBattleSetup.
    # HandleLinkBattleSetup might be inlined.

    # NEW APPROACH: Search the ENTIRE ROM for a function that:
    # 1. Checks gBattleTypeFlags & 2 (BATTLE_TYPE_LINK)
    # 2. Calls CreateTask (a function that references gTasks = 0x03005E00)
    # 3. Is small (< 100 bytes)
    # 4. References gReceivedRemoteLinkPlayers (0x03003124) or gWirelessCommType (0x030030FC)

    # From the first scan, we found 0x080721DC has sub-BL calls to:
    # +0x034: BL 0x080024E8
    # +0x03A: BL 0x0800237C
    # These are CreateTask calls! Let's check...

    print("=== Checking if 0x080024E8 is CreateTask ===")
    # CreateTask should reference gTasks (0x03005E00)
    offset_24e8 = 0x0024E8
    for j in range(offset_24e8, min(offset_24e8 + 200, len(rom) - 4), 4):
        val = struct.unpack_from("<I", rom, j)[0]
        if val == 0x03005E00:
            print(f"  0x080024E8 references gTasks at +0x{j - offset_24e8:03X} -> LIKELY CreateTask!")

    print()
    print("=== Checking if 0x0800237C is CreateTasksForSendRecvLinkBuffers ===")
    offset_237c = 0x00237C
    for j in range(offset_237c, min(offset_237c + 200, len(rom) - 4), 4):
        val = struct.unpack_from("<I", rom, j)[0]
        if val == 0x03005E00:
            print(f"  0x0800237C references gTasks at +0x{j - offset_237c:03X}")

    # Check sub-BL calls of 0x0800237C
    print("\n  Sub-BL calls of 0x0800237C:")
    i = 0
    while i < 100:
        if offset_237c + i + 4 > len(rom):
            break
        hw1 = struct.unpack_from("<H", rom, offset_237c + i)[0]
        hw2 = struct.unpack_from("<H", rom, offset_237c + i + 2)[0]
        pc = 0x08000000 + offset_237c + i
        bl = decode_bl(hw1, hw2, pc)
        if bl is not None:
            print(f"    +0x{i:03X}: BL 0x{bl:08X}")
            i += 4
        else:
            i += 2

    print()

    # Let's also check: Is 0x080721DC actually SetUpBattleVarsAndBirchZigzagoon?
    # It has: PUSH {LR}, SUB SP #16, does stuff, BL 0x080024E8 (CreateTask?), BL 0x0800237C
    # That matches HandleLinkBattleSetup! It creates tasks!
    # But wait - the first scanner said it doesn't reference gBattleTypeFlags directly.
    # Let me check more carefully...

    # The function at 0x080721DC takes R0 as parameter and processes it.
    # At +0x022: MOVS R0, #2 and +0x024: ANDS R3 - this tests bit 1 of something!
    # R0 parameter passed in might be gBattleTypeFlags value.

    # WAIT! Looking at the call site:
    # +0x0FE [0806F2D6]: LDR R0, [R0, #0x0]   ; load some value
    # +0x100 [0806F2D8]: BL 0x080721DC          ; call with that value in R0
    # The value loaded is from gBattleResources->something + gActiveBattler offset
    # This is NOT gBattleTypeFlags. The function processes per-battler data.

    # So 0x080721DC is NOT HandleLinkBattleSetup. It's something else.

    # Let's find the REAL HandleLinkBattleSetup.
    # HandleLinkBattleSetup is called from SetUpBattleVarsAndBirchZigzagoon.
    # If SetUpBattleVars is inlined into InitBattleControllers, then
    # HandleLinkBattleSetup is called from within the big function at 0x0806F1D8.

    # The key: HandleLinkBattleSetup checks gBattleTypeFlags. So there must be
    # a load of gBattleTypeFlags (0x02023364) somewhere in the big function,
    # followed by a test for bit 1 (LINK), followed by BL to HandleLinkBattleSetup.

    # OR HandleLinkBattleSetup itself loads gBattleTypeFlags.
    # Let's search for it as: a small function that loads 0x02023364, tests bit 1,
    # and calls 0x080024E8 (CreateTask) and 0x0800237C.

    print("=== Searching for HandleLinkBattleSetup: loads gBattleTypeFlags, tests LINK, calls CreateTask ===")

    # Look for literal pool entry 0x02023364 near a small function
    btf_bytes = struct.pack("<I", 0x02023364)
    pos = 0
    found = []
    while True:
        idx = rom.find(btf_bytes, pos)
        if idx == -1 or idx > 0x02000000:
            break
        # This is a literal pool entry. Find LDR instruction pointing to it.
        for back in range(4, 300, 2):
            if idx - back < 0:
                break
            hw = struct.unpack_from("<H", rom, idx - back)[0]
            if (hw & 0xF800) == 0x4800:  # LDR Rn, [PC, #imm]
                rn = (hw >> 8) & 7
                imm = (hw & 0xFF) * 4
                ldr_pc = 0x08000000 + (idx - back)
                ldr_target = ((ldr_pc + 4) & ~3) + imm
                actual_pool_offset = ldr_target - 0x08000000
                if actual_pool_offset == idx:
                    ldr_offset = idx - back
                    # Found! Now check if nearby there's a BL to 0x080024E8 or 0x0800237C
                    # Search forward from the LDR for BL instructions
                    for fwd in range(0, 60, 2):
                        if ldr_offset + fwd + 4 > len(rom):
                            break
                        fhw1 = struct.unpack_from("<H", rom, ldr_offset + fwd)[0]
                        fhw2 = struct.unpack_from("<H", rom, ldr_offset + fwd + 2)[0]
                        fpc = 0x08000000 + ldr_offset + fwd
                        fbl = decode_bl(fhw1, fhw2, fpc)
                        if fbl is not None and fbl in (0x080024E8, 0x0800237C):
                            found.append((ldr_offset, idx, fbl))
                    break
        pos = idx + 4

    for ldr_off, pool_off, bl_target in found:
        print(f"  LDR gBattleTypeFlags at ROM 0x{ldr_off:06X}, pool at 0x{pool_off:06X}, BL to 0x{bl_target:08X}")
        # Find function start (PUSH before LDR)
        for fb in range(0, 80, 2):
            if ldr_off - fb < 0:
                break
            fhw = struct.unpack_from("<H", rom, ldr_off - fb)[0]
            if (fhw & 0xFE00) == 0xB400 or (fhw & 0xFF00) == 0xB500:
                func_start = ldr_off - fb
                func_addr = 0x08000000 + func_start
                print(f"    Function starts at ROM 0x{func_start:06X} (0x{func_addr:08X})")

                # Find who calls this function
                callers = find_all_bl_to(rom, func_addr | 1, 0x030000, 0x200000)
                for co, cpc in callers:
                    print(f"    Called from ROM 0x{co:06X} (0x{cpc:08X})")
                break

if __name__ == "__main__":
    main()
