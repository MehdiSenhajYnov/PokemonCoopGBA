"""
Verify CB2_InitBattle = 0x080363C1 by finding:
1. Literal pool refs to 0x080363C1 (callers that pass it to SetMainCallback2)
2. Decode a wider range of the function at 0x080363C0 to understand full flow
3. Find gPreBattleCallback1 address (global used by ReturnFromBattleToOverworld)
"""
import struct
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rom", "Pokemon RunBun.gba")

CB2_INIT_BATTLE = 0x080363C1
CB2_INIT_BATTLE_PC = 0x080363C0
CB2_INIT_BATTLE_INTERNAL = 0x0803648D

def read_u16(data, off):
    if off+2>len(data): return None
    return struct.unpack_from('<H',data,off)[0]
def read_u32(data, off):
    if off+4>len(data): return None
    return struct.unpack_from('<I',data,off)[0]
def decode_bl(h, l, pc):
    full = ((h&0x7FF)<<12)|((l&0x7FF)<<1)
    if full>=0x400000: full-=0x800000
    return pc + full

with open(ROM_PATH, 'rb') as f:
    rom = f.read()

# 1. Search for literal pool refs to CB2_InitBattle (0x080363C1)
print("=== Literal pool refs to CB2_InitBattle (0x080363C1) ===")
target = struct.pack('<I', CB2_INIT_BATTLE)
target2 = struct.pack('<I', CB2_INIT_BATTLE_PC)
refs = []
for off in range(0, len(rom)-3, 4):
    if rom[off:off+4] == target or rom[off:off+4] == target2:
        refs.append((off, read_u32(rom, off)))
print(f"Found {len(refs)} literal pool refs")
for off, val in refs:
    print(f"  ROM 0x{off:06X}: value=0x{val:08X}")
    # Find which LDR instruction references this
    for pos in range(max(0, off-1024), off, 2):
        instr = read_u16(rom, pos)
        if instr and (instr & 0xF800) == 0x4800:
            imm = (instr & 0xFF) * 4
            pca = ((pos + 4) & ~3) + 0x08000000
            lit = pca + imm - 0x08000000
            if lit == off:
                rd = (instr >> 8) & 7
                # Find containing function
                func = None
                for p in range(pos, max(pos-4096, -1), -2):
                    i = read_u16(rom, p)
                    if i and (i >> 8) == 0xB5:
                        func = p
                        break
                print(f"    LDR R{rd} at ROM 0x{pos:06X}, in func 0x{0x08000000+func+1:08X}" if func else f"    LDR R{rd} at ROM 0x{pos:06X}")

# 2. Full decode of CB2_InitBattle
print(f"\n=== Full CB2_InitBattle (0x080363C0) ===")
pos = 0x0363C0
while pos < 0x03648C:
    instr = read_u16(rom, pos)
    if instr is None: break
    addr = 0x08000000 + pos
    desc = f"0x{instr:04X}"

    # Decode common instructions
    if (instr >> 8) == 0xB5 or (instr & 0xFE00) == 0xB400:
        regs = [f"R{r}" for r in range(8) if instr&(1<<r)]
        if instr & 0x100: regs.append("LR" if (instr>>8)==0xB5 or (instr&0xFE00)==0xB400 else "PC")
        desc = f"PUSH {{{','.join(regs)}}}"
    elif (instr >> 8) == 0xBD or (instr & 0xFE00) == 0xBC00:
        regs = [f"R{r}" for r in range(8) if instr&(1<<r)]
        if instr & 0x100: regs.append("PC")
        desc = f"POP {{{','.join(regs)}}}"
    elif (instr & 0xF800) == 0x2000:
        desc = f"MOV R{(instr>>8)&7}, #{instr&0xFF}"
    elif (instr & 0xF800) == 0x2800:
        desc = f"CMP R{(instr>>8)&7}, #{instr&0xFF}"
    elif (instr & 0xF800) == 0x4800:
        imm = (instr&0xFF)*4; pca=((pos+4)&~3)+0x08000000
        la = pca+imm-0x08000000
        if 0<=la<len(rom)-3:
            v=read_u32(rom,la)
            desc=f"LDR R{(instr>>8)&7}, =0x{v:08X}"
    elif (instr & 0xF800) == 0xE000:
        imm=instr&0x7FF
        if imm>=0x400: imm-=0x800
        desc=f"B 0x{addr+4+imm*2:08X}"
    elif (instr & 0xF000) == 0xD000:
        cond=(instr>>8)&0xF; imm=instr&0xFF
        if imm>=0x80: imm-=0x100
        cs={0:'EQ',1:'NE',2:'CS',3:'CC',4:'MI',5:'PL',6:'VS',7:'VC',8:'HI',9:'LS',10:'GE',11:'LT',12:'GT',13:'LE'}
        desc=f"B{cs.get(cond,'??')} 0x{addr+4+imm*2:08X}"
    elif (instr & 0xFF80) == 0x4700:
        desc=f"BX R{(instr>>3)&0xF}"
    elif (instr & 0xF800) == 0xF000 and pos+3 < len(rom):
        nxt=read_u16(rom,pos+2)
        if nxt and (nxt&0xF800)==0xF800:
            t=decode_bl(instr,nxt,addr+4)
            desc=f"BL 0x{t:08X}"
            print(f"  0x{addr:08X}  {desc}")
            pos+=4; continue
    elif (instr & 0xF800) == 0x6000:
        desc=f"STR R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*4:X}]"
    elif (instr & 0xF800) == 0x6800:
        desc=f"LDR R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*4:X}]"
    elif (instr & 0xFFC0) == 0x4340:
        desc=f"MUL R{instr&7}, R{(instr>>3)&7}"
    elif (instr & 0xFFC0) == 0x4000:
        desc=f"AND R{instr&7}, R{(instr>>3)&7}"
    elif (instr & 0xFFC0) == 0x1800:
        desc=f"ADD R{instr&7}, R{(instr>>3)&7}, R{(instr>>6)&7}"
    elif (instr & 0xFE00) == 0x1C00:
        desc=f"ADD R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&7}"
    elif (instr & 0xFF00) == 0x4600:
        desc=f"MOV R{(instr&7)|((instr>>4)&8)}, R{(instr>>3)&0xF}"
    elif (instr & 0xF800) == 0x3000:
        desc=f"ADD R{(instr>>8)&7}, #{instr&0xFF}"
    elif (instr & 0xF800) == 0x7800:
        desc=f"LDRB R{instr&7}, [R{(instr>>3)&7}, #0x{(instr>>6)&0x1F:X}]"
    elif (instr & 0xF800) == 0x7000:
        desc=f"STRB R{instr&7}, [R{(instr>>3)&7}, #0x{(instr>>6)&0x1F:X}]"
    elif (instr & 0xF800) == 0x8800:
        desc=f"LDRH R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*2:X}]"
    elif (instr & 0xF800) == 0x8000:
        desc=f"STRH R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*2:X}]"
    elif (instr & 0xFE00) == 0x0600:
        desc=f"LSL R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&0x1F}"
    elif (instr & 0xFE00) == 0x0800:
        desc=f"LSR R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&0x1F}"
    elif instr == 0xB001:
        desc = "ADD SP, #4"
    elif instr == 0xB081:
        desc = "SUB SP, #4"
    elif instr == 0xB082:
        desc = "SUB SP, #8"

    print(f"  0x{addr:08X}  {desc}")
    pos += 2

# 3. Find BL calls to CB2_InitBattle across ROM (for confirmation)
print(f"\n=== BL to CB2_InitBattle (0x080363C0) ===")
bl_calls = []
for pos in range(0, len(rom)-3, 2):
    h=read_u16(rom,pos); l=read_u16(rom,pos+2)
    if h and l and (h&0xF800)==0xF000 and (l&0xF800)==0xF800:
        t=decode_bl(h,l,0x08000000+pos+4)
        if t==CB2_INIT_BATTLE_PC or t==CB2_INIT_BATTLE:
            bl_calls.append(pos)
print(f"Found {len(bl_calls)} BL calls to CB2_InitBattle")
for bc in bl_calls[:5]:
    func = None
    for p in range(bc, max(bc-4096,-1), -2):
        i=read_u16(rom,p)
        if i and (i>>8)==0xB5:
            func=p; break
    print(f"  BL at ROM 0x{bc:06X}, func 0x{0x08000000+func+1:08X}" if func else f"  BL at ROM 0x{bc:06X}")
