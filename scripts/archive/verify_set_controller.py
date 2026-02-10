"""
Verify SetControllerToLinkOpponent function.
Its literal pool at 0x08077930-0x0807793C contains:
  0x03005D70 (gBattlerControllerFuncs)
  0x020233DC (gActiveBattler or gBattlerControllerEndFuncs?)
  0x0807793D (RunCommand)

But we expected it to also store ExecCompleted (0x08078789).
Let's look at the function code just before the literal pool.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

with open(ROM_PATH, "rb") as f:
    rom = f.read()

# The literal pool starts at 0x077930. The function is before it.
# SetControllerToLinkOpponent is small (~20 bytes).
# Let's look at 0x077910-0x077940

print("Disassembly before the literal pool at 0x08077930:")
print("(SetControllerToLinkOpponent should be here)")
print()

# Search backward from 0x077930 for PUSH
start = 0x077910
for i in range(start, 0x077940, 2):
    hw = struct.unpack_from("<H", rom, i)[0]
    addr = 0x08000000 + i
    desc = ""

    if hw & 0xFF00 == 0xB500:
        regs = []
        if hw & 0x100: regs.append("LR")
        for b in range(8):
            if hw & (1 << b): regs.append(f"r{b}")
        desc = f"PUSH {{{', '.join(regs)}}}"

    elif hw & 0xFF00 == 0xBD00:
        regs = []
        if hw & 0x100: regs.append("PC")
        for b in range(8):
            if hw & (1 << b): regs.append(f"r{b}")
        desc = f"POP {{{', '.join(regs)}}}"

    elif hw & 0xF800 == 0x4800:
        rd = (hw >> 8) & 7
        imm8 = (hw & 0xFF) * 4
        pc_val = (i + 4) & ~2
        lit_off = pc_val + imm8
        if lit_off + 4 <= len(rom):
            lit_val = struct.unpack_from("<I", rom, lit_off)[0]
            desc = f"LDR r{rd}, =0x{lit_val:08X}"
            if lit_val == 0x03005D70: desc += " (gBattlerControllerFuncs)"
            elif lit_val == 0x0807793D: desc += " (RunCommand!)"
            elif lit_val == 0x08078789: desc += " (ExecCompleted!)"
            elif (lit_val & 0xFF000001) == 0x08000001: desc += " (THUMB)"
            elif (lit_val & 0xFF000000) == 0x02000000: desc += " (EWRAM)"
            elif (lit_val & 0xFF000000) == 0x03000000: desc += " (IWRAM)"

    elif hw & 0xF800 == 0x6000:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm5 = ((hw >> 6) & 0x1F) * 4
        desc = f"STR r{rd}, [r{rn}, #0x{imm5:X}]"

    elif hw & 0xF800 == 0x7800:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm5 = (hw >> 6) & 0x1F
        desc = f"LDRB r{rd}, [r{rn}, #0x{imm5:X}]"

    elif hw == 0x4770:
        desc = "BX LR"

    elif hw & 0xF800 == 0x0000:
        rd = hw & 7
        rm = (hw >> 3) & 7
        imm5 = (hw >> 6) & 0x1F
        desc = f"LSL r{rd}, r{rm}, #{imm5}"

    elif hw & 0xFE00 == 0x1800:
        rd = hw & 7
        rn = (hw >> 3) & 7
        rm = (hw >> 6) & 7
        desc = f"ADD r{rd}, r{rn}, r{rm}"

    elif hw & 0xFF80 == 0x4700:
        rm = (hw >> 3) & 0xF
        desc = f"BX r{rm}"

    # Check if this is in literal pool range
    if i >= 0x077930 and i < 0x077940:
        if i % 4 == 0:
            val = struct.unpack_from("<I", rom, i)[0]
            desc = f"[LITERAL] 0x{val:08X}"
            if val == 0x03005D70: desc += " (gBattlerControllerFuncs)"
            elif val == 0x0807793D: desc += " (RunCommand)"
            elif val == 0x08078789: desc += " (ExecCompleted)"
            elif val == 0x020233DC: desc += " (EWRAM)"

    print(f"  0x{addr:08X}: 0x{hw:04X}  {desc}")

# Now let's check: where is gBattlerControllerEndFuncs?
# In vanilla emerald it's separate. In expansion it might be nearby.
# SetControllerToLinkOpponent stores ExecCompleted into EndFuncs.
# The literal pool has 0x020233DC - this might be gBattlerControllerEndFuncs?
# No wait, 0x020233DC appeared in RunCommand too as "gActiveBattler" context

# Let me search specifically for ExecCompleted THUMB address as 4 bytes
print()
print("Searching ROM for ExecCompleted THUMB address 0x08078789...")
exec_bytes = struct.pack("<I", 0x08078789)
offset = 0
count = 0
while True:
    pos = rom.find(exec_bytes, offset)
    if pos == -1:
        break
    count += 1
    print(f"  Found at ROM 0x{pos:06X} (aligned: {'yes' if pos % 4 == 0 else 'no'})")
    if count > 20:
        print("  ... (stopped at 20)")
        break
    offset = pos + 1

if count == 0:
    print("  Not found as exact bytes!")
    print()
    # Maybe the compiler stores it differently. Let's check if it's stored
    # as 0x08078788 (without THUMB bit) somewhere
    print("Searching for 0x08078788 (without THUMB bit)...")
    exec_bytes2 = struct.pack("<I", 0x08078788)
    offset = 0
    while True:
        pos = rom.find(exec_bytes2, offset)
        if pos == -1:
            break
        if pos % 4 == 0:
            print(f"  Found at ROM 0x{pos:06X} (0x{0x08000000+pos:08X})")
            # Show context
            for d in range(-8, 12, 4):
                c = pos + d
                if 0 <= c < len(rom) - 4:
                    v = struct.unpack_from("<I", rom, c)[0]
                    m = " <--" if c == pos else ""
                    print(f"    0x{0x08000000+c:08X}: 0x{v:08X}{m}")
        offset = pos + 1

# The key insight: SetControllerToLinkOpponent might store ExecCompleted
# via a DIFFERENT approach - maybe it stores the pointer from a different
# literal pool or uses a different address for gBattlerControllerEndFuncs.
print()
print("Looking for gBattlerControllerEndFuncs...")
print("In expansion, it's a separate array, likely in IWRAM near gBattlerControllerFuncs (0x03005D70)")
print()

# gBattlerControllerFuncs is at 0x03005D70, holds 4 function pointers (4 battlers)
# = 16 bytes, so next array could be at 0x03005D80
# Or gBattlerControllerEndFuncs could be in EWRAM

# From the SetControllerToLinkOpponent literal pool, we have:
# 0x03005D70 - gBattlerControllerFuncs
# 0x020233DC - unknown EWRAM
# 0x0807793D - RunCommand
# But we don't see ExecCompleted...

# Maybe the function before 0x077920 is SetControllerToLinkOpponent with
# a different literal pool. Let me look further back.
print("Looking further back for SetControllerToLinkOpponent...")
print()

# Search for a function that references BOTH gBattlerControllerFuncs AND ExecCompleted
# Actually, let's look at what references 0x0807793D (RunCommand)
# We found it at 0x077938 and 0x0787D4.
# 0x077938 is in a literal pool. The function using this pool is right before it.
# Let me find what LDR instruction references 0x077938.

# An LDR Rd, [PC, #imm] at address A loads from ((A+4)&~2) + imm*4
# We need ((A+4)&~2) + imm = 0x077938
# So A is somewhere before 0x077938, within 1020 bytes (max imm=255, *4=1020)

print("Functions that load RunCommand from literal pool at 0x08077938:")
for i in range(0x077938 - 1020, 0x077938, 2):
    if i < 0: continue
    hw = struct.unpack_from("<H", rom, i)[0]
    if hw & 0xF800 == 0x4800:  # LDR Rd, [PC, #imm]
        rd = (hw >> 8) & 7
        imm8 = (hw & 0xFF) * 4
        pc_val = (i + 4) & ~2
        target = pc_val + imm8
        if target == 0x077938:
            print(f"  LDR r{rd}, =RunCommand at 0x{0x08000000+i:08X}")
            # Show surrounding context
            for d in range(-10, 14, 2):
                ci = i + d
                if 0 <= ci < len(rom) - 2:
                    chw = struct.unpack_from("<H", rom, ci)[0]
                    m = " <-- LDR RunCommand" if ci == i else ""
                    # Check for LDR to literal pool
                    if chw & 0xF800 == 0x4800:
                        crd = (chw >> 8) & 7
                        cimm = (chw & 0xFF) * 4
                        cpc = (ci + 4) & ~2
                        ctarget = cpc + cimm
                        if ctarget + 4 <= len(rom):
                            cval = struct.unpack_from("<I", rom, ctarget)[0]
                            m += f" LDR r{crd}, =0x{cval:08X}"
                    print(f"    0x{0x08000000+ci:08X}: 0x{chw:04X}{m}")
