"""
Verify that 0x0807793D is LinkOpponentBufferRunCommand.

The function should:
1. Call IsBattleControllerActiveOnLocal(battler)
2. Load gBattleResources->bufferA[battler][0]
3. Compare against CONTROLLER_CMDS_COUNT (around 50)
4. Index into sLinkOpponentBufferCommands table
5. Call the handler

Also verify by checking SetControllerToLinkOpponent which stores
both RunCommand (0x0807793D) and ExecCompleted (0x08078789).
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

CANDIDATE = 0x0807793D
CANDIDATE_ROM = 0x0807793C  # without THUMB bit
EXEC_COMPLETED = 0x08078789

with open(ROM_PATH, "rb") as f:
    rom = f.read()

rom_off = CANDIDATE_ROM - 0x08000000
print(f"Examining function at 0x{CANDIDATE:08X} (ROM offset 0x{rom_off:06X})")
print(f"="*70)
print()

# Disassemble the function
i = 0
max_bytes = 120
while i < max_bytes:
    if rom_off + i + 2 > len(rom):
        break
    hw = struct.unpack_from("<H", rom, rom_off + i)[0]
    addr = 0x08000000 + rom_off + i
    desc = ""

    # PUSH
    if hw & 0xFF00 == 0xB500:
        regs = []
        if hw & 0x100: regs.append("LR")
        for b in range(8):
            if hw & (1 << b): regs.append(f"r{b}")
        desc = f"PUSH {{{', '.join(regs)}}}"

    # POP
    elif hw & 0xFF00 == 0xBD00:
        regs = []
        if hw & 0x100: regs.append("PC")
        for b in range(8):
            if hw & (1 << b): regs.append(f"r{b}")
        desc = f"POP {{{', '.join(regs)}}}"

    # LDR Rd, [PC, #imm]
    elif hw & 0xF800 == 0x4800:
        rd = (hw >> 8) & 7
        imm8 = (hw & 0xFF) * 4
        pc_val = (rom_off + i + 4) & ~2
        lit_off = pc_val + imm8
        if lit_off + 4 <= len(rom):
            lit_val = struct.unpack_from("<I", rom, lit_off)[0]
            desc = f"LDR r{rd}, [PC, #0x{imm8:X}] = 0x{lit_val:08X}"
            # Annotate known addresses
            if lit_val == 0x03005D70:
                desc += "  (gBattlerControllerFuncs)"
            elif lit_val == 0x02023364:
                desc += "  (gBattleTypeFlags)"
            elif lit_val == 0x020233E0:
                desc += "  (gBattleControllerExecFlags)"
            elif (lit_val & 0xFF000001) == 0x08000001:
                desc += f"  (THUMB func)"
        else:
            desc = f"LDR r{rd}, [PC, #0x{imm8:X}]"

    # LDR Rd, [Rn, #imm]
    elif hw & 0xF800 == 0x6800:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm5 = ((hw >> 6) & 0x1F) * 4
        desc = f"LDR r{rd}, [r{rn}, #0x{imm5:X}]"

    # STR Rd, [Rn, #imm]
    elif hw & 0xF800 == 0x6000:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm5 = ((hw >> 6) & 0x1F) * 4
        desc = f"STR r{rd}, [r{rn}, #0x{imm5:X}]"

    # LDRB
    elif hw & 0xF800 == 0x7800:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm5 = (hw >> 6) & 0x1F
        desc = f"LDRB r{rd}, [r{rn}, #0x{imm5:X}]"

    # LDRH
    elif hw & 0xF800 == 0x8800:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm5 = ((hw >> 6) & 0x1F) * 2
        desc = f"LDRH r{rd}, [r{rn}, #0x{imm5:X}]"

    # MOV Rd, #imm
    elif hw & 0xF800 == 0x2000:
        rd = (hw >> 8) & 7
        imm8 = hw & 0xFF
        desc = f"MOV r{rd}, #0x{imm8:X} ({imm8})"

    # CMP Rn, #imm
    elif hw & 0xF800 == 0x2800:
        rn = (hw >> 8) & 7
        imm8 = hw & 0xFF
        desc = f"CMP r{rn}, #0x{imm8:X} ({imm8})"

    # ADD Rd, PC, #imm (ADR)
    elif hw & 0xF800 == 0xA000:
        rd = (hw >> 8) & 7
        imm8 = (hw & 0xFF) * 4
        target = ((rom_off + i + 4) & ~2) + imm8
        desc = f"ADR r{rd}, 0x{0x08000000+target:08X}"

    # LSL
    elif hw & 0xF800 == 0x0000:
        rd = hw & 7
        rm = (hw >> 3) & 7
        imm5 = (hw >> 6) & 0x1F
        desc = f"LSL r{rd}, r{rm}, #{imm5}"

    # ADD Rd, Rn, #imm3
    elif hw & 0xFE00 == 0x1C00:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm3 = (hw >> 6) & 7
        desc = f"ADD r{rd}, r{rn}, #{imm3}"

    # ADD Rd, #imm8
    elif hw & 0xF800 == 0x3000:
        rd = (hw >> 8) & 7
        imm8 = hw & 0xFF
        desc = f"ADD r{rd}, #0x{imm8:X}"

    # BL (two halfwords)
    elif hw & 0xF800 == 0xF000:
        if rom_off + i + 2 < len(rom):
            hw2 = struct.unpack_from("<H", rom, rom_off + i + 2)[0]
            if hw2 & 0xF800 == 0xF800:
                off_hi = (hw & 0x7FF) << 12
                off_lo = (hw2 & 0x7FF) << 1
                if off_hi & 0x400000:
                    off_hi |= 0xFF800000
                bl_target = (0x08000000 + rom_off + i + 4) + (off_hi | off_lo)
                desc = f"BL 0x{bl_target:08X}"
                print(f"  0x{addr:08X}: 0x{hw:04X} 0x{hw2:04X}  {desc}")
                i += 4
                continue

    # BEQ/BNE/BCS/BCC etc
    elif hw & 0xF000 == 0xD000:
        cond = (hw >> 8) & 0xF
        soff = hw & 0xFF
        if soff & 0x80:
            soff -= 256
        target = (0x08000000 + rom_off + i + 4) + soff * 2
        cond_names = {0:"BEQ",1:"BNE",2:"BCS",3:"BCC",4:"BMI",5:"BPL",
                      6:"BVS",7:"BVC",8:"BHI",9:"BLS",10:"BGE",11:"BLT",
                      12:"BGT",13:"BLE"}
        cname = cond_names.get(cond, f"B{cond}")
        desc = f"{cname} 0x{target:08X}"

    # BX Rm
    elif hw & 0xFF80 == 0x4700:
        rm = (hw >> 3) & 0xF
        desc = f"BX r{rm}"

    # BLX Rm
    elif hw & 0xFF80 == 0x4780:
        rm = (hw >> 3) & 0xF
        desc = f"BLX r{rm}"

    # ADD (reg)
    elif hw & 0xFE00 == 0x1800:
        rd = hw & 7
        rn = (hw >> 3) & 7
        rm = (hw >> 6) & 7
        desc = f"ADD r{rd}, r{rn}, r{rm}"

    print(f"  0x{addr:08X}: 0x{hw:04X}  {desc}")

    # Stop at return
    if (hw & 0xFF00 == 0xBD00) or (hw == 0x4770):
        break

    i += 2

print()
print("="*70)
print("CROSS-VERIFICATION: Search for SetControllerToLinkOpponent")
print("="*70)
print()
print("SetControllerToLinkOpponent stores both:")
print(f"  RunCommand   = 0x{CANDIDATE:08X}")
print(f"  ExecCompleted = 0x{EXEC_COMPLETED:08X}")
print()
print("Searching ROM for literal pool containing BOTH addresses close together...")

# Search for ExecCompleted address (0x08078789) in ROM literal pools
# It should be near RunCommand address (0x0807793D)
exec_bytes = struct.pack("<I", EXEC_COMPLETED)
run_bytes = struct.pack("<I", CANDIDATE)

# Find all occurrences of ExecCompleted
exec_locs = []
offset = 0
while True:
    pos = rom.find(exec_bytes, offset)
    if pos == -1:
        break
    if pos % 4 == 0:  # literal pool entries are word-aligned
        exec_locs.append(pos)
    offset = pos + 1

print(f"ExecCompleted (0x{EXEC_COMPLETED:08X}) found at {len(exec_locs)} word-aligned ROM locations:")
for loc in exec_locs:
    print(f"  ROM 0x{loc:06X} (0x{0x08000000+loc:08X})")
    # Check if RunCommand is nearby (within 32 bytes)
    for delta in range(-32, 36, 4):
        check = loc + delta
        if 0 <= check < len(rom) - 4:
            val = struct.unpack_from("<I", rom, check)[0]
            if val == CANDIDATE:
                print(f"    -> RunCommand (0x{CANDIDATE:08X}) found at delta {delta:+d} (ROM 0x{check:06X})")

# Also find all occurrences of RunCommand
print()
run_locs = []
offset = 0
while True:
    pos = rom.find(run_bytes, offset)
    if pos == -1:
        break
    if pos % 4 == 0:
        run_locs.append(pos)
    offset = pos + 1

print(f"RunCommand (0x{CANDIDATE:08X}) found at {len(run_locs)} word-aligned ROM locations:")
for loc in run_locs:
    print(f"  ROM 0x{loc:06X} (0x{0x08000000+loc:08X})")

print()
print("="*70)
print("FINAL ANSWER")
print("="*70)
print(f"LinkOpponentBufferRunCommand = 0x{CANDIDATE:08X}")
print(f"ROM offset = 0x{CANDIDATE_ROM - 0x08000000:06X}")
