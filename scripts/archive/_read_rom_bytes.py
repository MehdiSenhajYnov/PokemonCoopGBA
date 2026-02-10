"""
Read raw ROM bytes around CB2_InitBattleInternal and the literal pool ref.
Decode THUMB instructions to understand the function structure.
"""
import struct
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rom", "Pokemon RunBun.gba")

def read_u16(data, offset):
    if offset + 2 > len(data):
        return None
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    if offset + 4 > len(data):
        return None
    return struct.unpack_from('<I', data, offset)[0]

def decode_thumb(data, rom_offset, count=60):
    """Decode THUMB instructions starting at rom_offset"""
    for i in range(count):
        pos = rom_offset + i * 2
        if pos + 2 > len(data):
            break
        instr = read_u16(data, pos)
        addr = 0x08000000 + pos

        desc = ""

        # PUSH
        if (instr & 0xFE00) == 0xB400:
            regs = []
            for r in range(8):
                if instr & (1 << r):
                    regs.append(f"R{r}")
            if instr & 0x100:
                regs.append("LR")
            desc = f"PUSH {{{', '.join(regs)}}}"
        # POP
        elif (instr & 0xFE00) == 0xBC00:
            regs = []
            for r in range(8):
                if instr & (1 << r):
                    regs.append(f"R{r}")
            if instr & 0x100:
                regs.append("PC")
            desc = f"POP {{{', '.join(regs)}}}"
        # MOV Rd, #imm
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc = f"MOV R{rd}, #{imm}"
        # CMP Rd, #imm
        elif (instr & 0xF800) == 0x2800:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc = f"CMP R{rd}, #{imm}"
        # LDR Rd, [PC, #imm]
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            pc_aligned = ((pos + 4) & ~3) + 0x08000000
            lit_addr = pc_aligned + imm
            lit_rom_off = lit_addr - 0x08000000
            if 0 <= lit_rom_off < len(data) - 3:
                lit_val = read_u32(data, lit_rom_off)
                desc = f"LDR R{rd}, [PC, #0x{imm:X}] = LDR R{rd}, =0x{lit_val:08X}"
            else:
                desc = f"LDR R{rd}, [PC, #0x{imm:X}]"
        # B (unconditional)
        elif (instr & 0xF800) == 0xE000:
            imm11 = instr & 0x07FF
            if imm11 >= 0x400:
                imm11 -= 0x800
            target = addr + 4 + imm11 * 2
            desc = f"B 0x{target:08X}"
        # Bcc (conditional)
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF
            imm8 = instr & 0xFF
            if imm8 >= 0x80:
                imm8 -= 0x100
            target = addr + 4 + imm8 * 2
            cond_names = {0:'EQ',1:'NE',2:'CS',3:'CC',4:'MI',5:'PL',6:'VS',7:'VC',8:'HI',9:'LS',10:'GE',11:'LT',12:'GT',13:'LE',14:'AL',15:'NV'}
            desc = f"B{cond_names.get(cond, '??')} 0x{target:08X}"
        # BX Rm
        elif (instr & 0xFF80) == 0x4700:
            rm = (instr >> 3) & 0xF
            desc = f"BX R{rm}"
        # BLX Rm
        elif (instr & 0xFF80) == 0x4780:
            rm = (instr >> 3) & 0xF
            desc = f"BLX R{rm}"
        # STR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 4
            desc = f"STR R{rd}, [R{rn}, #0x{imm:X}]"
        # LDR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 4
            desc = f"LDR R{rd}, [R{rn}, #0x{imm:X}]"
        # ADD/SUB
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm3 = (instr >> 6) & 7
            desc = f"ADD R{rd}, R{rn}, #{imm3}"
        elif (instr & 0xFE00) == 0x1E00:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm3 = (instr >> 6) & 7
            desc = f"SUB R{rd}, R{rn}, #{imm3}"
        # ADD Rd, #imm
        elif (instr & 0xF800) == 0x3000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc = f"ADD R{rd}, #{imm}"
        # MOV (register)
        elif (instr & 0xFF00) == 0x4600:
            rd = (instr & 7) | ((instr >> 4) & 0x8)
            rm = (instr >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"
        # BL (first half-word)
        elif (instr & 0xF800) == 0xF000:
            nxt = read_u16(data, pos + 2)
            if nxt and (nxt & 0xF800) == 0xF800:
                bl_target = 0x08000000 + pos + 4
                off11hi = instr & 0x07FF
                off11lo = nxt & 0x07FF
                full_off = (off11hi << 12) | (off11lo << 1)
                if full_off >= 0x400000:
                    full_off -= 0x800000
                target = bl_target + full_off - 4  # -4 because bl_target already includes +4
                # Actually: target = pc + fullOff, where pc = address + 4
                target = addr + 4 + full_off
                desc = f"BL 0x{target:08X} (2-word)"
        # NOP
        elif instr == 0x46C0:
            desc = "NOP (MOV R8,R8)"

        if not desc:
            desc = f"??? (0x{instr:04X})"

        print(f"  0x{addr:08X}  {instr:04X}  {desc}")

with open(ROM_PATH, 'rb') as f:
    rom = f.read()

# 1. Read bytes at CB2_InitBattleInternal (0x036490)
print("=== Bytes at CB2_InitBattleInternal (ROM 0x036490) ===")
print(f"  Raw: {rom[0x036490:0x036490+32].hex(' ')}")
decode_thumb(rom, 0x036490, 40)

# 2. Read bytes BEFORE CB2_InitBattleInternal (look for the previous function)
print("\n=== Bytes before CB2_InitBattleInternal (ROM 0x036400-0x036490) ===")
# Find the previous PUSH and analyze
for off in range(0x036490 - 2, 0x036400 - 1, -2):
    instr = read_u16(rom, off)
    if instr is not None and (instr & 0xFF00) in (0xB500, 0xB580, 0xB5F0):
        print(f"  Found PUSH at ROM 0x{off:06X} (0x{0x08000000+off:08X})")
        decode_thumb(rom, off, 60)
        break
else:
    # Try wider search
    for off in range(0x036490 - 2, 0x036000 - 1, -2):
        instr = read_u16(rom, off)
        if instr is not None and (instr >> 8) == 0xB5:
            print(f"  Found PUSH at ROM 0x{off:06X} (0x{0x08000000+off:08X})")
            decode_thumb(rom, off, 80)
            break

# 3. Also show what's at the literal pool ref (0x03666C)
print("\n=== Literal pool ref at ROM 0x03666C ===")
print(f"  Value at 0x03666C: 0x{read_u32(rom, 0x03666C):08X}")
# Find containing function
for off in range(0x03666C - 2, 0x03666C - 2048, -2):
    instr = read_u16(rom, off)
    if instr is not None and (instr >> 8) == 0xB5:
        print(f"  Containing function starts at ROM 0x{off:06X}")
        # Check size
        decode_thumb(rom, off, 30)
        break

# 4. Check what the first instruction at 0x036490 is
print(f"\n=== First instruction at 0x036490 ===")
first = read_u16(rom, 0x036490)
print(f"  0x{first:04X} - high byte: 0x{(first>>8):02X}")
if (first >> 8) == 0xB5:
    print("  -> PUSH {LR, ...}")
elif (first >> 8) == 0xB4:
    print("  -> PUSH {...}")
else:
    print("  -> NOT a PUSH instruction!")
    print(f"  Check: is 0x08036491 really the function start?")
    # Try looking at 0x036490 - maybe it's data or the PUSH is slightly different
    print(f"  Bytes at 0x036488-0x036498: {rom[0x036488:0x036498].hex(' ')}")
    # Maybe the scanner was wrong - let me check nearby for PUSH
    for off in range(0x036490 - 20, 0x036490 + 20, 2):
        instr = read_u16(rom, off)
        if instr is not None and (instr >> 8) == 0xB5:
            print(f"  PUSH found at ROM 0x{off:06X}: 0x{instr:04X}")
