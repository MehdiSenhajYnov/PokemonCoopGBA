"""
Find CB2_InitBattle using the CORRECT CB2_InitBattleInternal address: 0x0803648D
(not 0x08036491 which was incorrectly identified - it's PUSH {R7} in the middle of the function)

Real function start: ROM 0x03648C = 0x0803648D (THUMB)
Prologue: PUSH {R4, R5, R6, R7, LR}; MOV R7, R8; PUSH {R7}; SUB SP, #8

Search for:
1. Literal pool refs to 0x0803648D (THUMB addr) and 0x0803648C (non-THUMB)
2. BL instructions to 0x0803648C across entire ROM
3. B instructions to 0x0803648C
4. Also search for what's BEFORE 0x03648C to check for CB2_InitBattle
"""
import struct
import os
import json

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rom", "Pokemon RunBun.gba")

REAL_CB2_INIT_INTERNAL_THUMB = 0x0803648D
REAL_CB2_INIT_INTERNAL_PC    = 0x0803648C
CB2_HANDLE_START = 0x08037B45

def read_u16(data, off):
    if off+2>len(data): return None
    return struct.unpack_from('<H',data,off)[0]

def read_u32(data, off):
    if off+4>len(data): return None
    return struct.unpack_from('<I',data,off)[0]

def decode_bl(h, l, pc):
    off11hi = h & 0x07FF
    off11lo = l & 0x07FF
    full = (off11hi<<12)|(off11lo<<1)
    if full>=0x400000: full-=0x800000
    return pc + full

def decode_b(instr, pc):
    if (instr&0xF800)!=0xE000: return None
    imm=instr&0x7FF
    if imm>=0x400: imm-=0x800
    return pc+4+imm*2

def find_func_start(data, off, max_back=4096):
    start = max(0, off - max_back)
    for pos in range(off-2, start-1, -2):
        instr = read_u16(data, pos)
        if instr is None: continue
        # PUSH {... LR} — high byte 0xB5xx
        if (instr >> 8) == 0xB5:
            return pos
    return None

def decode_thumb_range(data, start, end):
    """Decode all THUMB instructions in [start, end)"""
    lines = []
    pos = start
    while pos < end - 1:
        instr = read_u16(data, pos)
        if instr is None: break
        addr = 0x08000000 + pos
        desc = f"0x{instr:04X}"

        # PUSH
        if (instr & 0xFE00) == 0xB400:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            if instr & 0x100: regs.append("LR")
            desc = f"PUSH {{{','.join(regs)}}}"
        elif (instr >> 8) == 0xB5:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            regs.append("LR")
            desc = f"PUSH {{{','.join(regs)}}}"
        # POP
        elif (instr & 0xFE00) == 0xBC00:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            if instr & 0x100: regs.append("PC")
            desc = f"POP {{{','.join(regs)}}}"
        elif (instr >> 8) == 0xBD:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            regs.append("PC")
            desc = f"POP {{{','.join(regs)}}}"
        # BL
        elif (instr & 0xF800) == 0xF000 and pos+3 < end:
            nxt = read_u16(data, pos+2)
            if nxt and (nxt & 0xF800) == 0xF800:
                target = decode_bl(instr, nxt, addr+4)
                desc = f"BL 0x{target:08X}"
                lines.append(f"  0x{addr:08X}  {desc}")
                pos += 4
                continue
        # B
        elif (instr & 0xF800) == 0xE000:
            t = decode_b(instr, addr)
            desc = f"B 0x{t:08X}" if t else f"B ???"
        # Bcc
        elif (instr & 0xF000) == 0xD000:
            cond = (instr>>8)&0xF
            imm = instr&0xFF
            if imm >= 0x80: imm -= 0x100
            t = addr + 4 + imm*2
            conds = {0:'EQ',1:'NE',2:'CS',3:'CC',4:'MI',5:'PL',6:'VS',7:'VC',8:'HI',9:'LS',10:'GE',11:'LT',12:'GT',13:'LE'}
            desc = f"B{conds.get(cond,'??')} 0x{t:08X}"
        # BX
        elif (instr & 0xFF80) == 0x4700:
            rm = (instr>>3)&0xF
            desc = f"BX R{rm}"
        # LDR Rd, [PC, #imm]
        elif (instr & 0xF800) == 0x4800:
            rd = (instr>>8)&7
            imm = (instr&0xFF)*4
            pca = ((pos+4)&~3)+0x08000000
            la = pca+imm-0x08000000
            if 0<=la<len(data)-3:
                v = read_u32(data, la)
                desc = f"LDR R{rd}, =0x{v:08X}"
            else:
                desc = f"LDR R{rd}, [PC, #0x{imm:X}]"
        # MOV imm
        elif (instr & 0xF800) == 0x2000:
            desc = f"MOV R{(instr>>8)&7}, #{instr&0xFF}"

        lines.append(f"  0x{addr:08X}  {desc}")
        pos += 2
    return lines

with open(ROM_PATH, 'rb') as f:
    rom = f.read()

print(f"ROM size: {len(rom)} bytes")

# Step 1: What's before 0x03648C?
print("\n=== What's before the real CB2_InitBattleInternal (0x03648C) ===")
prev_func = find_func_start(rom, 0x03648C - 2)
if prev_func:
    print(f"Previous function starts at ROM 0x{prev_func:06X}")
    # Find where it ends (POP {PC} before 0x03648C)
    for p in range(prev_func, 0x03648C, 2):
        instr = read_u16(rom, p)
        if instr is not None and ((instr >> 8) == 0xBD or instr == 0x4770):
            print(f"  Previous function ends at ROM 0x{p:06X} (0x{instr:04X})")
            # Print the gap between end and 0x03648C
            gap = 0x03648C - (p+2)
            if gap > 0:
                print(f"  Gap of {gap} bytes before 0x03648C")
                print(f"  Gap bytes: {rom[p+2:0x03648C].hex(' ')}")
            break
    # Decode last 20 instructions of previous function
    print("  Last instructions of previous function:")
    start_show = max(prev_func, 0x03648C - 60)
    for line in decode_thumb_range(rom, start_show, 0x03648C + 2):
        print(line)

# Step 2: Literal pool refs to 0x0803648D
print("\n=== Literal pool refs to 0x0803648D ===")
target_bytes_1 = struct.pack('<I', REAL_CB2_INIT_INTERNAL_THUMB)
target_bytes_2 = struct.pack('<I', REAL_CB2_INIT_INTERNAL_PC)
refs = []
for off in range(0, len(rom)-3, 4):
    if rom[off:off+4] == target_bytes_1 or rom[off:off+4] == target_bytes_2:
        refs.append(off)
print(f"Found {len(refs)} refs")
for r in refs:
    func_start = find_func_start(rom, r)
    print(f"  ROM 0x{r:06X}: value=0x{read_u32(rom,r):08X}, containing func at 0x{func_start:06X}" if func_start else f"  ROM 0x{r:06X}: no func found")
    if func_start:
        for line in decode_thumb_range(rom, func_start, min(func_start+120, len(rom))):
            print(line)

# Step 3: BL to 0x0803648C (entire ROM)
print("\n=== BL to CB2_InitBattleInternal (entire ROM) ===")
bl_calls = []
for pos in range(0, len(rom)-3, 2):
    h = read_u16(rom, pos)
    l = read_u16(rom, pos+2)
    if h and l and (h&0xF800)==0xF000 and (l&0xF800)==0xF800:
        target = decode_bl(h, l, 0x08000000+pos+4)
        if target == REAL_CB2_INIT_INTERNAL_PC or target == REAL_CB2_INIT_INTERNAL_THUMB:
            bl_calls.append(pos)
for bc in bl_calls:
    print(f"  BL at ROM 0x{bc:06X} (0x{0x08000000+bc:08X})")
    func_start = find_func_start(rom, bc)
    if func_start:
        print(f"    in function at 0x{0x08000000+func_start+1:08X}")
        for line in decode_thumb_range(rom, func_start, min(func_start+100, len(rom))):
            print(line)
print(f"Total: {len(bl_calls)} BL calls")

# Step 4: B to 0x0803648C
print("\n=== B to CB2_InitBattleInternal ===")
b_jumps = []
for pos in range(0, len(rom)-1, 2):
    instr = read_u16(rom, pos)
    if instr and (instr&0xF800)==0xE000:
        target = decode_b(instr, 0x08000000+pos)
        if target == REAL_CB2_INIT_INTERNAL_PC or target == REAL_CB2_INIT_INTERNAL_THUMB:
            b_jumps.append(pos)
for bj in b_jumps:
    print(f"  B at ROM 0x{bj:06X} (0x{0x08000000+bj:08X})")
    func_start = find_func_start(rom, bj)
    if func_start:
        print(f"    in function at 0x{0x08000000+func_start+1:08X}")
        for line in decode_thumb_range(rom, func_start, min(func_start+100, len(rom))):
            print(line)
print(f"Total: {len(b_jumps)} B jumps")

# Step 5: Search for BX to register that was loaded with 0x0803648D
# This requires finding LDR Rx, =0x0803648D followed by BX Rx
print("\n=== LDR + BX pattern for CB2_InitBattleInternal ===")
for r in refs:
    # For each literal pool ref, find which LDR instruction reads it
    # Search backward from the literal pool for LDR Rd, [PC, #imm] that resolves to this address
    for pos in range(max(0, r - 1024), r, 2):
        instr = read_u16(rom, pos)
        if instr and (instr & 0xF800) == 0x4800:
            imm = (instr & 0xFF) * 4
            pca = ((pos + 4) & ~3) + 0x08000000
            lit_addr = pca + imm - 0x08000000
            if lit_addr == r:
                rd = (instr >> 8) & 7
                print(f"  LDR R{rd}, =0x0803648D at ROM 0x{pos:06X}")
                # Look for BX Rd or MOV + BX nearby
                for p2 in range(pos+2, min(pos+20, len(rom)-1), 2):
                    i2 = read_u16(rom, p2)
                    if i2 and (i2 & 0xFF80) == 0x4700:
                        rm = (i2 >> 3) & 0xF
                        if rm == rd:
                            print(f"    BX R{rd} at ROM 0x{p2:06X}")

# Summary
print(f"\n=== Summary ===")
print(f"CB2_InitBattleInternal (corrected): 0x0803648D")
print(f"Literal pool refs: {len(refs)}")
print(f"BL calls: {len(bl_calls)}")
print(f"B jumps: {len(b_jumps)}")
if refs or bl_calls or b_jumps:
    print("There ARE references — CB2_InitBattle likely exists as a separate function")
else:
    print("NO external references found — CB2_InitBattle likely INLINED into callers")
    print("Check if the function at 0x0803648D is actually the MERGED CB2_InitBattle+Internal")
