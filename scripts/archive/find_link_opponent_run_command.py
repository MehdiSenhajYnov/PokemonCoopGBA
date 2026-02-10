"""
Find LinkOpponentBufferRunCommand address in Run & Bun ROM.

Known: LinkOpponentBufferExecCompleted = 0x08078789 (ROM offset 0x078788)

Strategy:
1. ExecCompleted's FIRST instruction is:
     gBattlerControllerFuncs[battler] = LinkOpponentBufferRunCommand;
   So the literal pool of ExecCompleted MUST contain the address of RunCommand.

2. ExecCompleted is small (~60 bytes). Its literal pool is right after its code.
   The literal pool contains:
   - Address of gBattlerControllerFuncs (0x03005D70)
   - Address of LinkOpponentBufferRunCommand (WHAT WE WANT)
   - Address of gBattleTypeFlags (0x02023364)
   - Other addresses used in the function

3. We also look at SetControllerToLinkOpponent which is defined just before
   LinkOpponentBufferRunCommand in the source. It stores both RunCommand and
   ExecCompleted pointers.

4. RunCommand itself is a small function that:
   - Calls IsBattleControllerActiveOnLocal(battler)
   - Reads gBattleResources->bufferA[battler][0]
   - Indexes into sLinkOpponentBufferCommands table
   - Calls the handler or BtlController_Complete
"""

import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses
EXEC_COMPLETED_ROM = 0x078788   # ROM offset (without 0x08000000)
EXEC_COMPLETED_THUMB = 0x08078789  # THUMB address
GBATTLER_CONTROLLER_FUNCS = 0x03005D70  # IWRAM
GBATTLE_TYPE_FLAGS = 0x02023364

with open(ROM_PATH, "rb") as f:
    rom = f.read()

print(f"ROM size: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)")
print(f"ExecCompleted ROM offset: 0x{EXEC_COMPLETED_ROM:06X}")
print()

# ---- APPROACH 1: Disassemble ExecCompleted and find its literal pool ----
print("="*70)
print("APPROACH 1: Disassemble around ExecCompleted")
print("="*70)

# Read bytes around ExecCompleted
start = EXEC_COMPLETED_ROM
# ExecCompleted is small - about 30-50 bytes of THUMB code + literal pool
# Let's read 128 bytes to be safe
region = rom[start:start+256]

print(f"\nRaw bytes at ExecCompleted (0x{start:06X}):")
for i in range(0, min(128, len(region)), 2):
    hw = struct.unpack_from("<H", region, i)[0]
    addr = 0x08000000 + start + i
    print(f"  0x{addr:08X}: 0x{hw:04X}", end="")

    # Detect PUSH
    if hw & 0xFF00 == 0xB500:
        regs = []
        if hw & 0x100: regs.append("LR")
        for b in range(8):
            if hw & (1 << b): regs.append(f"r{b}")
        print(f"  ; PUSH {{{', '.join(regs)}}}", end="")

    # Detect POP
    if hw & 0xFF00 == 0xBD00:
        regs = []
        if hw & 0x100: regs.append("PC")
        for b in range(8):
            if hw & (1 << b): regs.append(f"r{b}")
        print(f"  ; POP {{{', '.join(regs)}}}", end="")

    # Detect BX
    if hw & 0xFF80 == 0x4700:
        rm = (hw >> 3) & 0xF
        print(f"  ; BX r{rm}", end="")

    # Detect LDR literal (PC-relative)
    if hw & 0xF800 == 0x4800:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        pc = (0x08000000 + start + i + 4) & ~2  # PC is current + 4, aligned
        target = pc + imm
        # Read the literal value
        lit_offset = (start + i + 4) & ~2  # align
        lit_offset = lit_offset - 0x08000000 if lit_offset >= 0x08000000 else lit_offset
        lit_rom_offset = ((start + i + 4) & ~2) + imm - (start)
        # Actually compute properly
        pc_val = (start + i + 4) & ~2
        lit_rom_offset = pc_val + imm
        if lit_rom_offset < len(rom):
            lit_val = struct.unpack_from("<I", rom, lit_rom_offset)[0]
            print(f"  ; LDR r{rd}, [PC, #0x{imm:X}] -> [0x{0x08000000+lit_rom_offset:08X}] = 0x{lit_val:08X}", end="")

    # Detect BL (two halfwords)
    if hw & 0xF800 == 0xF000:
        if i + 2 < len(region):
            hw2 = struct.unpack_from("<H", region, i+2)[0]
            if hw2 & 0xF800 == 0xF800:
                offset_hi = (hw & 0x7FF) << 12
                offset_lo = (hw2 & 0x7FF) << 1
                if offset_hi & 0x400000:
                    offset_hi |= 0xFF800000  # sign extend
                bl_target = (0x08000000 + start + i + 4) + offset_hi + offset_lo
                print(f"  ; BL 0x{bl_target:08X}", end="")

    print()

# ---- APPROACH 2: Scan literal pool after ExecCompleted ----
print()
print("="*70)
print("APPROACH 2: Scan for literal pool entries after ExecCompleted")
print("="*70)

# The literal pool comes after the function's code (after POP/BX return).
# ExecCompleted is probably 30-60 bytes. Scan the area for 32-bit values
# that look like THUMB function pointers (0x080xxxxx with bit 0 set, odd).

# Find the end of ExecCompleted - look for POP {PC} or BX
func_end = None
for i in range(0, 128, 2):
    hw = struct.unpack_from("<H", region, i)[0]
    # POP with PC
    if hw & 0xFF00 == 0xBD00 and hw & 0x100:
        func_end = i + 2
        # But there might be more code paths... let's find the LAST return before alignment
    # BX lr
    if hw == 0x4770:
        func_end = i + 2

print(f"Estimated function end offset: +0x{func_end:X}" if func_end else "Could not find function end")

# Scan literals in the area 0x078788 to 0x078800 (aligned to 4)
print(f"\n4-byte aligned values in range 0x{start:06X} to 0x{start+256:06X}:")
for i in range(0, 256, 4):
    offset = start + i
    if offset + 4 <= len(rom):
        val = struct.unpack_from("<I", rom, offset)[0]
        # Filter for interesting values
        is_thumb = (val & 0xFF000001) == 0x08000001  # ROM THUMB pointer
        is_arm = (val & 0xFF000003) == 0x08000000    # ROM ARM pointer
        is_ewram = (val & 0xFF000000) == 0x02000000  # EWRAM
        is_iwram = (val & 0xFF000000) == 0x03000000  # IWRAM

        if is_thumb or is_arm or is_ewram or is_iwram:
            tag = ""
            if val == GBATTLER_CONTROLLER_FUNCS:
                tag = " *** gBattlerControllerFuncs ***"
            elif val == GBATTLE_TYPE_FLAGS:
                tag = " *** gBattleTypeFlags ***"
            elif val == EXEC_COMPLETED_THUMB:
                tag = " *** LinkOpponentBufferExecCompleted ***"
            elif is_thumb:
                tag = " (THUMB func ptr)"
            elif is_ewram:
                tag = " (EWRAM)"
            elif is_iwram:
                tag = " (IWRAM)"

            print(f"  0x{0x08000000+offset:08X}: 0x{val:08X}{tag}")

# ---- APPROACH 3: Look BEFORE ExecCompleted for SetControllerToLinkOpponent ----
print()
print("="*70)
print("APPROACH 3: Look before ExecCompleted for SetControllerToLinkOpponent")
print("="*70)
print("SetControllerToLinkOpponent stores BOTH RunCommand and ExecCompleted.")
print("It's defined just before RunCommand in the source. So the order is:")
print("  SetControllerToLinkOpponent → RunCommand → ... → ExecCompleted")
print()

# SetControllerToLinkOpponent is a tiny function (stores 2 pointers, returns).
# It's probably 20-30 bytes. RunCommand is maybe 30-50 bytes.
# The command table sLinkOpponentBufferCommands is between them.
# Actually, in compiled code, static data goes to .rodata, not inline.
# So the functions are likely consecutive or close.

# Let's look backwards from ExecCompleted for the ExecCompleted THUMB address
# in literal pools. SetControllerToLinkOpponent stores ExecCompleted's address,
# so searching backwards should find it.

print("Searching backwards from ExecCompleted for its own THUMB address in literal pools:")
search_start = max(0, EXEC_COMPLETED_ROM - 0x2000)  # 8KB before
for offset in range(search_start, EXEC_COMPLETED_ROM, 4):
    val = struct.unpack_from("<I", rom, offset)[0]
    if val == EXEC_COMPLETED_THUMB:
        print(f"  Found ExecCompleted ref at ROM 0x{offset:06X} (0x{0x08000000+offset:08X})")
        # The literal pool belongs to a function. Look at nearby values.
        print(f"  Nearby literals:")
        for j in range(-16, 20, 4):
            nearby_off = offset + j
            if 0 <= nearby_off < len(rom) - 4:
                nearby_val = struct.unpack_from("<I", rom, nearby_off)[0]
                marker = ""
                if nearby_val == EXEC_COMPLETED_THUMB:
                    marker = " <- ExecCompleted"
                elif nearby_val == GBATTLER_CONTROLLER_FUNCS:
                    marker = " <- gBattlerControllerFuncs"
                elif (nearby_val & 0xFF000001) == 0x08000001:
                    marker = " <- THUMB ptr"
                elif (nearby_val & 0xFF000000) == 0x02000000:
                    marker = " <- EWRAM"
                elif (nearby_val & 0xFF000000) == 0x03000000:
                    marker = " <- IWRAM"
                print(f"    0x{0x08000000+nearby_off:08X}: 0x{nearby_val:08X}{marker}")
        print()

# ---- APPROACH 4: Find RunCommand by pattern ----
print()
print("="*70)
print("APPROACH 4: Find RunCommand via its pattern")
print("="*70)
print("RunCommand calls IsBattleControllerActiveOnLocal, then indexes into")
print("sLinkOpponentBufferCommands. It's typically right after SetControllerToLinkOpponent.")
print()

# RunCommand THUMB address should appear in:
# 1. ExecCompleted's literal pool (first store)
# 2. SetControllerToLinkOpponent's literal pool

# From Approach 2, let's identify candidate THUMB pointers in ExecCompleted's literal pool
# These are THUMB pointers that are NOT ExecCompleted itself and are in the nearby ROM area.

print("Candidate RunCommand addresses from ExecCompleted's literal pool:")
candidates = []
for i in range(0, 256, 4):
    offset = start + i
    if offset + 4 <= len(rom):
        val = struct.unpack_from("<I", rom, offset)[0]
        # THUMB pointer in nearby ROM area (within 0x1000 of ExecCompleted)
        if (val & 0xFF000001) == 0x08000001:
            rom_off = (val & 0x01FFFFFF) & ~1  # clear thumb bit
            if abs(rom_off - EXEC_COMPLETED_ROM) < 0x2000 and val != EXEC_COMPLETED_THUMB:
                candidates.append((offset, val, rom_off))
                print(f"  At pool 0x{0x08000000+offset:08X}: target 0x{val:08X} (ROM 0x{rom_off:06X})")

# For each candidate, check if it looks like the start of a function (PUSH)
print("\nChecking candidates for PUSH instruction (function start):")
for pool_off, thumb_addr, rom_off in candidates:
    if rom_off < len(rom) - 2:
        hw = struct.unpack_from("<H", rom, rom_off)[0]
        is_push = (hw & 0xFF00) == 0xB500
        print(f"  0x{thumb_addr:08X} → first halfword: 0x{hw:04X} {'<- PUSH (function start!)' if is_push else ''}")
        if is_push:
            # Disassemble first few instructions
            print(f"    Disassembly:")
            for j in range(0, 40, 2):
                if rom_off + j + 2 <= len(rom):
                    ihw = struct.unpack_from("<H", rom, rom_off + j)[0]
                    addr = 0x08000000 + rom_off + j
                    desc = ""
                    if ihw & 0xF800 == 0x4800:
                        rd = (ihw >> 8) & 7
                        imm = (ihw & 0xFF) * 4
                        pc_val = (rom_off + j + 4) & ~2
                        lit_off = pc_val + imm
                        if lit_off < len(rom) - 4:
                            lit_val = struct.unpack_from("<I", rom, lit_off)[0]
                            desc = f"LDR r{rd}, =0x{lit_val:08X}"
                    elif ihw & 0xF800 == 0xF000 and rom_off + j + 2 < len(rom):
                        ihw2 = struct.unpack_from("<H", rom, rom_off + j + 2)[0]
                        if ihw2 & 0xF800 == 0xF800:
                            off_hi = (ihw & 0x7FF) << 12
                            off_lo = (ihw2 & 0x7FF) << 1
                            if off_hi & 0x400000:
                                off_hi |= 0xFF800000
                            bl_target = (0x08000000 + rom_off + j + 4) + off_hi + off_lo
                            desc = f"BL 0x{bl_target:08X}"
                    elif ihw & 0xFF00 == 0xBD00:
                        desc = "POP {..., PC}"
                    elif ihw & 0xFF00 == 0xB500:
                        desc = "PUSH {..., LR}"

                    print(f"      0x{addr:08X}: 0x{ihw:04X}  {desc}")

# ---- APPROACH 5: Direct literal pool scan of ExecCompleted ----
print()
print("="*70)
print("APPROACH 5: Parse LDR instructions in ExecCompleted to find RunCommand")
print("="*70)
print("ExecCompleted's first line stores RunCommand into gBattlerControllerFuncs[battler].")
print("This means one of the first LDR instructions loads the RunCommand address.")
print()

# Parse ExecCompleted instruction by instruction
print("Detailed disassembly of ExecCompleted:")
i = 0
ldr_targets = []
while i < 128:
    hw = struct.unpack_from("<H", region, i)[0]
    addr = 0x08000000 + start + i
    desc = ""
    extra = ""

    # LDR Rd, [PC, #imm]
    if hw & 0xF800 == 0x4800:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        pc_val = (start + i + 4) & ~2
        lit_off = pc_val + imm
        if lit_off < len(rom) - 4:
            lit_val = struct.unpack_from("<I", rom, lit_off)[0]
            desc = f"LDR r{rd}, [PC, #0x{imm:X}] = 0x{lit_val:08X}"
            ldr_targets.append((i, rd, lit_val, lit_off))
            if lit_val == GBATTLER_CONTROLLER_FUNCS:
                extra = " <- gBattlerControllerFuncs"
            elif lit_val == GBATTLE_TYPE_FLAGS:
                extra = " <- gBattleTypeFlags"
            elif (lit_val & 0xFF000001) == 0x08000001:
                extra = f" <- THUMB func @ ROM 0x{(lit_val & ~1) - 0x08000000:06X}"

    # STR Rd, [Rn, #imm]
    elif hw & 0xF800 == 0x6000:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm = ((hw >> 6) & 0x1F) * 4
        desc = f"STR r{rd}, [r{rn}, #0x{imm:X}]"

    # PUSH
    elif hw & 0xFF00 == 0xB500:
        desc = "PUSH {LR, ...}"

    # POP
    elif hw & 0xFF00 == 0xBD00:
        desc = "POP {PC, ...}"
        print(f"  0x{addr:08X}: 0x{hw:04X}  {desc}{extra}")
        break

    # BL
    elif hw & 0xF800 == 0xF000 and i + 2 < 128:
        hw2 = struct.unpack_from("<H", region, i + 2)[0]
        if hw2 & 0xF800 == 0xF800:
            off_hi = (hw & 0x7FF) << 12
            off_lo = (hw2 & 0x7FF) << 1
            if off_hi & 0x400000:
                off_hi |= 0xFF800000
            bl_target = (addr + 4) + off_hi + off_lo
            desc = f"BL 0x{bl_target:08X}"
            i += 2  # skip second halfword

    # MOV, CMP, etc.
    elif hw & 0xFC00 == 0x0000:
        desc = f"LSL ..."

    print(f"  0x{addr:08X}: 0x{hw:04X}  {desc}{extra}")
    i += 2

print(f"\nLDR targets found in ExecCompleted:")
for off, rd, val, lit_off in ldr_targets:
    tag = ""
    if val == GBATTLER_CONTROLLER_FUNCS:
        tag = "gBattlerControllerFuncs"
    elif val == GBATTLE_TYPE_FLAGS:
        tag = "gBattleTypeFlags"
    elif (val & 0xFF000001) == 0x08000001:
        # Check if it starts with PUSH
        func_rom = (val & ~1) - 0x08000000
        if func_rom < len(rom) - 2:
            first_hw = struct.unpack_from("<H", rom, func_rom)[0]
            if first_hw & 0xFF00 == 0xB500:
                tag = f"THUMB function (starts with PUSH) — CANDIDATE RunCommand"
            else:
                tag = f"THUMB pointer (first hw: 0x{first_hw:04X})"
    elif (val & 0xFF000000) == 0x02000000:
        tag = "EWRAM"
    elif (val & 0xFF000000) == 0x03000000:
        tag = "IWRAM"

    print(f"  r{rd} <- 0x{val:08X}  [{tag}]")

print()
print("="*70)
print("SUMMARY")
print("="*70)

# Collect all THUMB function pointer candidates from ExecCompleted's literal pool
run_cmd_candidates = []
for off, rd, val, lit_off in ldr_targets:
    if (val & 0xFF000001) == 0x08000001 and val != EXEC_COMPLETED_THUMB:
        func_rom = (val & ~1) - 0x08000000
        if func_rom < len(rom) - 2:
            first_hw = struct.unpack_from("<H", rom, func_rom)[0]
            if first_hw & 0xFF00 == 0xB500:
                run_cmd_candidates.append(val)

if run_cmd_candidates:
    for c in run_cmd_candidates:
        print(f"\n*** LinkOpponentBufferRunCommand = 0x{c:08X} ***")
        print(f"    ROM offset: 0x{(c & ~1) - 0x08000000:06X}")
else:
    print("No clear candidate found. Manual analysis needed.")
    print("Check the disassembly above for the first LDR that loads a THUMB pointer.")
