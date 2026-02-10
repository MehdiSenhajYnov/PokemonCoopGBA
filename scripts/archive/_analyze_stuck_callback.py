"""
Analyze the callback at 0x08038819 where the battle gets stuck.
The VS screen shows but inBattle never goes to 1.
callback2 = 0x08038819 (THUMB) = ROM offset 0x038818

Goals:
1. Find the function at 0x038818 and its containing function
2. Disassemble it to find link wait loops
3. Identify what link functions it calls
4. Find patchable locations to skip link waits

Also investigate the full CB2_HandleStartBattle state machine since the stuck
callback might be set by one of its cases.
"""
import struct
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rom", "Pokemon RunBun.gba")

def read_u16(data, off):
    if off + 2 > len(data): return None
    return struct.unpack_from('<H', data, off)[0]

def read_u32(data, off):
    if off + 4 > len(data): return None
    return struct.unpack_from('<I', data, off)[0]

def decode_bl(h, l, pc):
    full = ((h & 0x7FF) << 12) | ((l & 0x7FF) << 1)
    if full >= 0x400000: full -= 0x800000
    return pc + full

def find_func_start(data, off, max_back=8192):
    for pos in range(off, max(0, off - max_back), -2):
        instr = read_u16(data, pos)
        if instr and (instr >> 8) == 0xB5:
            return pos
    return None

def decode_thumb_range(data, start, end):
    lines = []
    pos = start
    while pos < end:
        instr = read_u16(data, pos)
        if instr is None: break
        addr = 0x08000000 + pos
        desc = f"0x{instr:04X}"

        if (instr >> 8) == 0xB5:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            regs.append("LR")
            desc = f"PUSH {{{','.join(regs)}}}"
        elif (instr & 0xFE00) == 0xB400:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            if instr & 0x100: regs.append("LR")
            desc = f"PUSH {{{','.join(regs)}}}"
        elif (instr >> 8) == 0xBD:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            regs.append("PC")
            desc = f"POP {{{','.join(regs)}}}"
            lines.append(f"  0x{addr:08X}  {desc}")
            pos += 2
            continue
        elif (instr & 0xFE00) == 0xBC00:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            if instr & 0x100: regs.append("PC")
            desc = f"POP {{{','.join(regs)}}}"
        elif (instr & 0xF800) == 0xF000 and pos + 3 < end:
            nxt = read_u16(data, pos + 2)
            if nxt and (nxt & 0xF800) == 0xF800:
                target = decode_bl(instr, nxt, addr + 4)
                desc = f"BL 0x{target:08X}"
                lines.append(f"  0x{addr:08X}  {desc}")
                pos += 4
                continue
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            pca = ((pos + 4) & ~3) + 0x08000000
            la = pca + imm - 0x08000000
            if 0 <= la < len(data) - 3:
                v = read_u32(data, la)
                desc = f"LDR R{rd}, =0x{v:08X}"
        elif (instr & 0xF800) == 0x2000:
            desc = f"MOV R{(instr>>8)&7}, #{instr&0xFF}"
        elif (instr & 0xF800) == 0x2800:
            desc = f"CMP R{(instr>>8)&7}, #{instr&0xFF}"
        elif (instr & 0xF800) == 0xE000:
            imm = instr & 0x7FF
            if imm >= 0x400: imm -= 0x800
            desc = f"B 0x{addr+4+imm*2:08X}"
        elif (instr & 0xF000) == 0xD000:
            cond = (instr>>8)&0xF; imm = instr&0xFF
            if imm >= 0x80: imm -= 0x100
            cs = {0:'EQ',1:'NE',2:'CS',3:'CC',4:'MI',5:'PL',6:'VS',7:'VC',8:'HI',9:'LS',10:'GE',11:'LT',12:'GT',13:'LE'}
            desc = f"B{cs.get(cond,'??')} 0x{addr+4+imm*2:08X}"
        elif (instr & 0xFF80) == 0x4700:
            desc = f"BX R{(instr>>3)&0xF}"
        elif (instr & 0xF800) == 0x6800:
            desc = f"LDR R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*4:X}]"
        elif (instr & 0xF800) == 0x6000:
            desc = f"STR R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*4:X}]"
        elif (instr & 0xF800) == 0x7800:
            desc = f"LDRB R{instr&7}, [R{(instr>>3)&7}, #0x{(instr>>6)&0x1F:X}]"
        elif (instr & 0xF800) == 0x7000:
            desc = f"STRB R{instr&7}, [R{(instr>>3)&7}, #0x{(instr>>6)&0x1F:X}]"
        elif (instr & 0xF800) == 0x8800:
            desc = f"LDRH R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*2:X}]"
        elif (instr & 0xF800) == 0x8000:
            desc = f"STRH R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*2:X}]"
        elif (instr & 0xFF00) == 0x4600:
            desc = f"MOV R{(instr&7)|((instr>>4)&8)}, R{(instr>>3)&0xF}"
        elif (instr & 0xF800) == 0x3000:
            desc = f"ADD R{(instr>>8)&7}, #{instr&0xFF}"
        elif (instr & 0xF800) == 0x3800:
            desc = f"SUB R{(instr>>8)&7}, #{instr&0xFF}"
        elif (instr & 0xFE00) == 0x1800:
            desc = f"ADD R{instr&7}, R{(instr>>3)&7}, R{(instr>>6)&7}"
        elif (instr & 0xFE00) == 0x1C00:
            desc = f"ADD R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&7}"
        elif (instr & 0xFFC0) == 0x4200:
            desc = f"TST R{instr&7}, R{(instr>>3)&7}"
        elif (instr & 0xFFC0) == 0x4280:
            desc = f"CMP R{instr&7}, R{(instr>>3)&7}"
        elif (instr & 0xFFC0) == 0x4000:
            desc = f"AND R{instr&7}, R{(instr>>3)&7}"
        elif (instr & 0xFFC0) == 0x4300:
            desc = f"ORR R{instr&7}, R{(instr>>3)&7}"
        elif instr == 0x46C0:
            desc = "NOP"
        elif (instr & 0xFF00) == 0xB000:
            imm = (instr & 0x7F) * 4
            if instr & 0x80:
                desc = f"SUB SP, #{imm}"
            else:
                desc = f"ADD SP, #{imm}"

        lines.append(f"  0x{addr:08X}  {desc}")
        pos += 2
    return lines

with open(ROM_PATH, 'rb') as f:
    rom = f.read()

# Key addresses
STUCK_CALLBACK = 0x08038818  # 0x08038819 with THUMB bit
CB2_HANDLE_START = 0x08037B44  # 0x08037B45 with THUMB bit
CB2_INIT_BATTLE = 0x080363C0
CB2_INIT_INTERNAL = 0x0803648C

# Known link-related addresses
LINK_ADDRS = {
    0x030030FC: "gWirelessCommType",
    0x03003124: "gReceivedRemoteLinkPlayers",
    0x0300307C: "gBlockReceivedStatus",
    0x04000128: "REG_SIOCNT",
    0x02023364: "gBattleTypeFlags",
    0x02023A18: "gBattleResources",
    0x020233E0: "gActiveBattler",
    0x020233DC: "gBattleControllerExecFlags",
    0x0202370E: "gBattleCommunication",
    0x0800A4B0: "GetMultiplayerId",
}

print("=" * 70)
print("ANALYSIS OF STUCK CALLBACK 0x08038819")
print("=" * 70)

# 1. Find function containing 0x038818
print("\n[1] Finding function start for 0x08038818...")
func_start = find_func_start(rom, 0x038818)
if func_start:
    func_addr = 0x08000000 + func_start + 1
    func_size = 0x038818 - func_start
    print(f"  Function starts at ROM 0x{func_start:06X} (0x{func_addr:08X})")
    print(f"  Offset from func start: 0x{func_size:X} bytes")

    # Find function end (next POP{PC} or BX LR)
    func_end = func_start
    for p in range(func_start, min(func_start + 8192, len(rom)), 2):
        instr = read_u16(rom, p)
        if instr and (instr >> 8) == 0xBD:
            func_end = p + 2
            # Check if there's a literal pool after POP
            break
    total_size = func_end - func_start
    print(f"  Function size: ~{total_size} bytes (until first POP{{PC}})")
else:
    print("  Could not find function start!")

# 2. Check if 0x038818 is a function start itself
print(f"\n[2] Is 0x038818 a function start?")
instr_at = read_u16(rom, 0x038818)
print(f"  Instruction at 0x038818: 0x{instr_at:04X}")
if (instr_at >> 8) == 0xB5:
    print(f"  YES - PUSH {{..., LR}} = function prologue!")
else:
    print(f"  NO - not a PUSH prologue")
    # Check nearby
    for off in range(0x038810, 0x038820, 2):
        i = read_u16(rom, off)
        if i and (i >> 8) == 0xB5:
            print(f"  PUSH found at 0x{off:06X}: 0x{i:04X}")

# 3. Disassemble the function at 0x038818
print(f"\n[3] Disassembly of function at 0x08038819 (first 200 instructions)...")
# Find real function start
if func_start and func_start != 0x038818:
    start = func_start
else:
    start = 0x038818
end = min(start + 400, len(rom))  # ~200 instructions
for line in decode_thumb_range(rom, start, end):
    print(line)

# 4. Look for literal pool refs to link-related addresses near the function
print(f"\n[4] Literal pool refs to link-related addresses near 0x038818...")
search_start = max(0, 0x038818 - 4096)
search_end = min(len(rom) - 3, 0x038818 + 4096)
for off in range(search_start, search_end, 4):
    val = read_u32(rom, off)
    if val in LINK_ADDRS:
        print(f"  ROM 0x{off:06X}: 0x{val:08X} = {LINK_ADDRS[val]}")

# 5. Find what calls/sets callback2 to 0x08038819
print(f"\n[5] Who sets callback2 = 0x08038819?")
target_bytes_1 = struct.pack('<I', 0x08038819)  # THUMB
target_bytes_2 = struct.pack('<I', 0x08038818)  # non-THUMB
lit_refs = []
for off in range(0, len(rom) - 3, 4):
    if rom[off:off+4] == target_bytes_1 or rom[off:off+4] == target_bytes_2:
        lit_refs.append(off)
print(f"  Found {len(lit_refs)} literal pool refs to 0x08038819")
for ref in lit_refs[:10]:
    # Find the LDR that uses this
    for pos in range(max(0, ref - 1024), ref, 2):
        instr = read_u16(rom, pos)
        if instr and (instr & 0xF800) == 0x4800:
            imm = (instr & 0xFF) * 4
            pca = ((pos + 4) & ~3) + 0x08000000
            lit = pca + imm - 0x08000000
            if lit == ref:
                fs = find_func_start(rom, pos)
                fn = f"0x{0x08000000+fs+1:08X}" if fs else "?"
                print(f"  Literal at ROM 0x{ref:06X}, loaded by LDR at 0x{pos:06X}, in function {fn}")

# 6. BL calls to 0x038818
print(f"\n[6] BL calls to 0x08038818...")
bl_calls = []
for pos in range(0, len(rom) - 3, 2):
    h = read_u16(rom, pos)
    l = read_u16(rom, pos + 2)
    if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800:
        target = decode_bl(h, l, 0x08000000 + pos + 4)
        if target == 0x08038818 or target == 0x08038819:
            bl_calls.append(pos)
print(f"  Found {len(bl_calls)} BL calls")
for bc in bl_calls[:5]:
    fs = find_func_start(rom, bc)
    fn = f"0x{0x08000000+fs+1:08X}" if fs else "?"
    print(f"  BL at ROM 0x{bc:06X}, in function {fn}")

# 7. Analyze CB2_HandleStartBattle's switch table
print(f"\n[7] CB2_HandleStartBattle switch table analysis...")
print(f"  CB2_HandleStartBattle at 0x{CB2_HANDLE_START:08X}")
# Disassemble first 100 instructions looking for switch pattern
switch_cases = []
pos = CB2_HANDLE_START
for i in range(200):
    instr = read_u16(rom, pos)
    if instr is None: break
    addr = 0x08000000 + pos

    # Look for CMP Rn, #imm patterns (switch case count)
    if (instr & 0xF800) == 0x2800:
        rd = (instr >> 8) & 7
        imm = instr & 0xFF
        print(f"  CMP R{rd}, #{imm} at 0x{addr:08X}")

    # Look for LDR Rn, =0x08038819 pattern
    if (instr & 0xF800) == 0x4800:
        rd = (instr >> 8) & 7
        imm2 = (instr & 0xFF) * 4
        pca = ((pos + 4) & ~3) + 0x08000000
        la = pca + imm2 - 0x08000000
        if 0 <= la < len(rom) - 3:
            v = read_u32(rom, la)
            if v == 0x08038819 or v == 0x08038818:
                print(f"  *** LDR R{rd}, =0x{v:08X} at 0x{addr:08X} — THIS loads the stuck callback!")

    # Look for BL instructions
    if (instr & 0xF800) == 0xF000:
        nxt = read_u16(rom, pos + 2)
        if nxt and (nxt & 0xF800) == 0xF800:
            target = decode_bl(instr, nxt, addr + 4)
            # Check if it's SetMainCallback2
            if target == 0x08000544:
                print(f"  BL SetMainCallback2 at 0x{addr:08X}")
            pos += 4
            continue

    pos += 2

# 8. Look for what addresses the stuck function references (all literal pool entries)
print(f"\n[8] All literal pool entries in the stuck function area...")
if func_start:
    scan_start = func_start
else:
    scan_start = 0x038818
# Scan from function start to function start + 2KB for literal pool entries
for off in range(scan_start, min(scan_start + 2048, len(rom) - 3), 4):
    val = read_u32(rom, off)
    # Only show interesting values (EWRAM, IWRAM, ROM function ptrs)
    if (val >= 0x02000000 and val < 0x02040000) or \
       (val >= 0x03000000 and val < 0x03008000) or \
       (val >= 0x04000000 and val < 0x04000400) or \
       (val >= 0x08000000 and val < 0x0A000000 and (val & 1)):  # THUMB ptrs
        label = LINK_ADDRS.get(val & 0xFFFFFFFE, LINK_ADDRS.get(val, ""))
        if not label and val >= 0x08000000:
            label = "ROM func"
        print(f"  ROM 0x{off:06X}: 0x{val:08X} {label}")

print("\n=== END OF ANALYSIS ===")
