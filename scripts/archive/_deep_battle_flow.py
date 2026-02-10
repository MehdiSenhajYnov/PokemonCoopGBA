"""
Deep analysis of the battle initialization flow in Run & Bun.
The VS screen shows but battle never starts — game is stuck at callback2 = 0x08038819 (NOP).

We need to trace the FULL path from CB2_HandleStartBattle to BattleMainCB2:
1. CB2_HandleStartBattle state machine (all cases)
2. Who sets callback2 = 0x08038819 (the NOP)
3. What tasks run during VS screen
4. What conditions advance to BattleMainCB2
5. What link sync checks block progression
"""
import struct, os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rom", "Pokemon RunBun.gba")

with open(ROM_PATH, 'rb') as f:
    rom = f.read()

def r16(off):
    if off + 2 > len(rom): return None
    return struct.unpack_from('<H', rom, off)[0]

def r32(off):
    if off + 4 > len(rom): return None
    return struct.unpack_from('<I', rom, off)[0]

def decode_bl(h, l, pc):
    full = ((h & 0x7FF) << 12) | ((l & 0x7FF) << 1)
    if full >= 0x400000: full -= 0x800000
    return pc + full

def ldr_pool_val(pos):
    """Get the literal pool value for a LDR Rx, [PC, #imm] at position pos"""
    instr = r16(pos)
    if not instr or (instr & 0xF800) != 0x4800: return None
    imm = (instr & 0xFF) * 4
    pca = ((pos + 4) & ~3)
    la = pca + imm
    if 0 <= la < len(rom) - 3:
        return r32(la)
    return None

LABELS = {
    0x08000544: "SetMainCallback2",
    0x08038819: "NOP_callback",
    0x08038818: "NOP_callback",
    0x08094815: "BattleMainCB2",
    0x08094814: "BattleMainCB2",
    0x080363C1: "CB2_InitBattle",
    0x0803648D: "CB2_InitBattleInternal",
    0x08037B45: "CB2_HandleStartBattle",
    0x0800A4B1: "GetMultiplayerId",
    0x02023364: "gBattleTypeFlags",
    0x02023A18: "gBattleResources",
    0x020233E0: "gActiveBattler",
    0x020233DC: "gBattleControllerExecFlags",
    0x0202370E: "gBattleCommunication",
    0x02020648: "gMain",
    0x020206AE: "gMain.inBattle",
    0x030030FC: "gWirelessCommType",
    0x03003124: "gReceivedRemoteLinkPlayers",
    0x0300307C: "gBlockReceivedStatus",
    0x04000128: "REG_SIOCNT",
}

def label(val):
    if val in LABELS: return LABELS[val]
    if (val & ~1) in LABELS: return LABELS[val & ~1]
    return ""

def disasm_range(start, end_off, annotate=True):
    """Disassemble THUMB code range, return list of (addr, instr_hex, description, notes)"""
    lines = []
    pos = start
    while pos < end_off and pos < len(rom) - 1:
        instr = r16(pos)
        if instr is None: break
        addr = 0x08000000 + pos
        raw = f"{instr:04X}"
        desc = f"0x{instr:04X}"
        notes = ""

        # PUSH with LR
        if (instr >> 8) == 0xB5:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            regs.append("LR")
            desc = f"PUSH {{{','.join(regs)}}}"
        # PUSH without LR
        elif (instr & 0xFE00) == 0xB400:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            if instr & 0x100: regs.append("LR")
            desc = f"PUSH {{{','.join(regs)}}}"
        # POP with PC
        elif (instr >> 8) == 0xBD:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            regs.append("PC")
            desc = f"POP {{{','.join(regs)}}}"
        # POP without PC
        elif (instr & 0xFE00) == 0xBC00:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            if instr & 0x100: regs.append("PC")
            desc = f"POP {{{','.join(regs)}}}"
        # BL
        elif (instr & 0xF800) == 0xF000 and pos + 3 < end_off:
            nxt = r16(pos + 2)
            if nxt and (nxt & 0xF800) == 0xF800:
                target = decode_bl(instr, nxt, addr + 4)
                lbl = label(target)
                desc = f"BL 0x{target:08X}"
                if lbl: notes = f"= {lbl}"
                lines.append((addr, f"{instr:04X} {nxt:04X}", desc, notes))
                pos += 4
                continue
        # LDR Rd, [PC, #imm]
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            v = ldr_pool_val(pos)
            if v is not None:
                lbl = label(v)
                desc = f"LDR R{rd}, =0x{v:08X}"
                if lbl: notes = f"= {lbl}"
        # MOV Rd, #imm
        elif (instr & 0xF800) == 0x2000:
            desc = f"MOV R{(instr>>8)&7}, #{instr&0xFF}"
        # CMP Rd, #imm
        elif (instr & 0xF800) == 0x2800:
            desc = f"CMP R{(instr>>8)&7}, #{instr&0xFF}"
        # B unconditional
        elif (instr & 0xF800) == 0xE000:
            imm = instr & 0x7FF
            if imm >= 0x400: imm -= 0x800
            desc = f"B 0x{addr+4+imm*2:08X}"
        # Bcc conditional
        elif (instr & 0xF000) == 0xD000:
            cond = (instr>>8)&0xF; imm = instr&0xFF
            if imm >= 0x80: imm -= 0x100
            cs = {0:'EQ',1:'NE',2:'CS',3:'CC',4:'MI',5:'PL',6:'VS',7:'VC',8:'HI',9:'LS',10:'GE',11:'LT',12:'GT',13:'LE'}
            desc = f"B{cs.get(cond,'??')} 0x{addr+4+imm*2:08X}"
        # BX Rm
        elif (instr & 0xFF80) == 0x4700:
            rm = (instr>>3)&0xF
            desc = f"BX R{rm}"
        # LDR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6800:
            desc = f"LDR R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*4:X}]"
        # STR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6000:
            desc = f"STR R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*4:X}]"
        # LDRB
        elif (instr & 0xF800) == 0x7800:
            desc = f"LDRB R{instr&7}, [R{(instr>>3)&7}, #0x{(instr>>6)&0x1F:X}]"
        # STRB
        elif (instr & 0xF800) == 0x7000:
            desc = f"STRB R{instr&7}, [R{(instr>>3)&7}, #0x{(instr>>6)&0x1F:X}]"
        # LDRH
        elif (instr & 0xF800) == 0x8800:
            desc = f"LDRH R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*2:X}]"
        # STRH
        elif (instr & 0xF800) == 0x8000:
            desc = f"STRH R{instr&7}, [R{(instr>>3)&7}, #0x{((instr>>6)&0x1F)*2:X}]"
        # MOV Rd, Rm (high regs)
        elif (instr & 0xFF00) == 0x4600:
            desc = f"MOV R{(instr&7)|((instr>>4)&8)}, R{(instr>>3)&0xF}"
        # ADD Rd, #imm
        elif (instr & 0xF800) == 0x3000:
            desc = f"ADD R{(instr>>8)&7}, #{instr&0xFF}"
        # SUB Rd, #imm
        elif (instr & 0xF800) == 0x3800:
            desc = f"SUB R{(instr>>8)&7}, #{instr&0xFF}"
        # ADD Rd, Rn, Rm
        elif (instr & 0xFE00) == 0x1800:
            desc = f"ADD R{instr&7}, R{(instr>>3)&7}, R{(instr>>6)&7}"
        # ADD Rd, Rn, #imm3
        elif (instr & 0xFE00) == 0x1C00:
            desc = f"ADD R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&7}"
        # TST
        elif (instr & 0xFFC0) == 0x4200:
            desc = f"TST R{instr&7}, R{(instr>>3)&7}"
        # CMP Rn, Rm
        elif (instr & 0xFFC0) == 0x4280:
            desc = f"CMP R{instr&7}, R{(instr>>3)&7}"
        # AND
        elif (instr & 0xFFC0) == 0x4000:
            desc = f"AND R{instr&7}, R{(instr>>3)&7}"
        # ORR
        elif (instr & 0xFFC0) == 0x4300:
            desc = f"ORR R{instr&7}, R{(instr>>3)&7}"
        # LSL Rd, Rm, #imm
        elif (instr & 0xF800) == 0x0000:
            desc = f"LSL R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&0x1F}"
        # LSR Rd, Rm, #imm
        elif (instr & 0xF800) == 0x0800:
            desc = f"LSR R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&0x1F}"
        # NOP
        elif instr == 0x46C0:
            desc = "NOP"
        # ADD/SUB SP
        elif (instr & 0xFF00) == 0xB000:
            imm = (instr & 0x7F) * 4
            desc = f"{'SUB' if instr & 0x80 else 'ADD'} SP, #{imm}"
        # LDR Rd, [SP, #imm]
        elif (instr & 0xF800) == 0x9800:
            desc = f"LDR R{(instr>>8)&7}, [SP, #0x{(instr&0xFF)*4:X}]"
        # STR Rd, [SP, #imm]
        elif (instr & 0xF800) == 0x9000:
            desc = f"STR R{(instr>>8)&7}, [SP, #0x{(instr&0xFF)*4:X}]"
        # ADD Rd, PC, #imm
        elif (instr & 0xF800) == 0xA000:
            desc = f"ADD R{(instr>>8)&7}, PC, #0x{(instr&0xFF)*4:X}"

        lines.append((addr, raw, desc, notes))
        pos += 2
    return lines

def find_func_end(start, max_size=8192):
    """Find end of a THUMB function (POP{...,PC} followed by potential literal pool)"""
    pos = start
    last_pop = None
    while pos < min(start + max_size, len(rom) - 1):
        instr = r16(pos)
        if instr is None: break
        # POP{...,PC}
        if (instr >> 8) == 0xBD:
            last_pop = pos + 2
            # Check if next instructions are more code or literal pool
            # If next is a PUSH{...,LR} or data, this was the end
            nxt = r16(pos + 2)
            if nxt:
                # Next is PUSH (new function) → this was the end
                if (nxt >> 8) == 0xB5:
                    return last_pop
                # Next is a literal pool value (typically an address)
                val = r32(pos + 2)
                if val and (val >= 0x02000000 or val >= 0x08000000):
                    # Probably literal pool → scan until we hit code again
                    p2 = pos + 2
                    while p2 < min(start + max_size, len(rom) - 3):
                        v = r32(p2)
                        if v and not ((v >= 0x02000000 and v < 0x10000000) or v == 0 or (v >= 0x08000000)):
                            break
                        # Check if it looks like a function start
                        i = r16(p2)
                        if i and (i >> 8) == 0xB5:
                            return p2
                        p2 += 4
                    return p2
        pos += 2
    return last_pop or (start + max_size)

# ================================================================
print("=" * 70)
print("DEEP BATTLE FLOW ANALYSIS")
print("=" * 70)

# 1. Disassemble CB2_HandleStartBattle FULLY
print("\n" + "=" * 70)
print("[1] CB2_HandleStartBattle (0x08037B44) — FULL disassembly")
print("=" * 70)

cb2hs_start = 0x037B44
cb2hs_end = find_func_end(cb2hs_start, 4096)
print(f"  Function: 0x{0x08000000+cb2hs_start:08X} to 0x{0x08000000+cb2hs_end:08X} ({cb2hs_end-cb2hs_start} bytes)")

# Find all interesting references within
setcb2_calls = []
ldr_refs = {}
for a, raw, desc, notes in disasm_range(cb2hs_start, cb2hs_end):
    if "SetMainCallback2" in desc or "SetMainCallback2" in notes:
        setcb2_calls.append(a)
    if "LDR R" in desc and "=0x" in desc:
        val_str = desc.split("=0x")[1].rstrip(")")
        try:
            val = int(val_str, 16)
            lbl = label(val)
            if lbl:
                if lbl not in ldr_refs: ldr_refs[lbl] = []
                ldr_refs[lbl].append(a)
        except: pass

print(f"\n  SetMainCallback2 calls within CB2_HandleStartBattle:")
for a in setcb2_calls:
    # Find what was loaded into R0 before the BL
    print(f"    BL at 0x{a:08X}")
    # Look back up to 10 instructions for LDR R0
    for back in range(2, 22, 2):
        prev_pos = (a - 0x08000000) - back
        if prev_pos >= cb2hs_start:
            prev_instr = r16(prev_pos)
            if prev_instr and (prev_instr & 0xF800) == 0x4800:
                rd = (prev_instr >> 8) & 7
                if rd == 0:  # R0 = callback argument
                    v = ldr_pool_val(prev_pos)
                    if v:
                        lbl = label(v)
                        print(f"      R0 loaded from 0x{v:08X} {lbl} (at 0x{0x08000000+prev_pos:08X})")
                    break

print(f"\n  Interesting literal pool refs:")
for lbl, addrs in sorted(ldr_refs.items()):
    print(f"    {lbl}: {len(addrs)} refs at {', '.join(f'0x{a:08X}' for a in addrs[:5])}")

# 2. Full disassembly of CB2_HandleStartBattle — focus on switch cases
print("\n" + "=" * 70)
print("[2] CB2_HandleStartBattle switch-case states")
print("=" * 70)

# Print full disasm with annotations for readability
all_lines = disasm_range(cb2hs_start, cb2hs_end)
in_switch = False
for i, (addr, raw, desc, notes) in enumerate(all_lines):
    # Highlight important lines
    important = False
    if "SetMainCallback2" in notes or "SetMainCallback2" in desc:
        important = True
    if "NOP_callback" in notes or "BattleMainCB2" in notes:
        important = True
    if "gBattleCommunication" in notes:
        important = True
    if "gReceivedRemoteLinkPlayers" in notes:
        important = True
    if "gMain" in notes and "inBattle" in notes:
        important = True
    if desc.startswith("CMP") and "#" in desc:
        try:
            imm = int(desc.split("#")[1])
            if imm >= 5: important = True
        except: pass
    if desc.startswith("PUSH") and "LR" in desc:
        important = True
    if desc.startswith("POP") and "PC" in desc:
        important = True

    if important:
        marker = ">>>"
    else:
        marker = "   "
    note_str = f"  ; {notes}" if notes else ""
    print(f"  {marker} {addr:08X}  {raw:<9s}  {desc:<40s}{note_str}")

# 3. Analyze the functions that set BattleMainCB2
print("\n" + "=" * 70)
print("[3] Functions that reference BattleMainCB2 (0x08094815)")
print("=" * 70)

# Find all literal pool refs
bm_target = struct.pack('<I', 0x08094815)
bm_target2 = struct.pack('<I', 0x08094814)
for off in range(0, len(rom) - 3, 4):
    if rom[off:off+4] == bm_target or rom[off:off+4] == bm_target2:
        # Find the LDR that uses this
        for pos in range(max(0, off - 1024), off, 2):
            instr = r16(pos)
            if instr and (instr & 0xF800) == 0x4800:
                imm = (instr & 0xFF) * 4
                pca = ((pos + 4) & ~3)
                lit = pca + imm
                if lit == off:
                    rd = (instr >> 8) & 7
                    # Find function start
                    for back in range(pos, max(0, pos-8192), -2):
                        fi = r16(back)
                        if fi and (fi >> 8) == 0xB5:
                            func_start = back
                            func_end = find_func_end(func_start, 2048)
                            func_size = func_end - func_start
                            print(f"\n  Function at 0x{0x08000000+func_start+1:08X} ({func_size} bytes)")
                            print(f"  LDR R{rd}, =BattleMainCB2 at 0x{0x08000000+pos:08X}")
                            # Disassemble this function
                            for a, raw, desc, notes in disasm_range(func_start, func_end):
                                note_str = f"  ; {notes}" if notes else ""
                                mrk = ">>>" if ("BattleMainCB2" in notes or "SetMainCallback2" in notes or "inBattle" in notes) else "   "
                                print(f"    {mrk} {a:08X}  {raw:<9s}  {desc:<40s}{note_str}")
                            break
                    break

# 4. Trace: find all SetMainCallback2 calls with NOP_callback (0x08038819) as arg
print("\n" + "=" * 70)
print("[4] All SetMainCallback2(NOP_callback) calls in ROM")
print("=" * 70)

nop_bytes = struct.pack('<I', 0x08038819)
nop_bytes2 = struct.pack('<I', 0x08038818)
set_cb2_addr = 0x08000544

for off in range(0, len(rom) - 3, 4):
    if rom[off:off+4] == nop_bytes or rom[off:off+4] == nop_bytes2:
        # Find LDR that loads this
        for pos in range(max(0, off - 1024), off, 2):
            instr = r16(pos)
            if instr and (instr & 0xF800) == 0x4800:
                rd = (instr >> 8) & 7
                imm = (instr & 0xFF) * 4
                pca = ((pos + 4) & ~3)
                lit = pca + imm
                if lit == off:
                    # Check if followed by BL SetMainCallback2 within 20 bytes
                    for p2 in range(pos + 2, min(pos + 24, len(rom) - 3), 2):
                        h = r16(p2)
                        l = r16(p2 + 2)
                        if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800:
                            target = decode_bl(h, l, 0x08000000 + p2 + 4)
                            if target == set_cb2_addr:
                                # Find containing function
                                for back in range(pos, max(0, pos-8192), -2):
                                    fi = r16(back)
                                    if fi and (fi >> 8) == 0xB5:
                                        print(f"\n  In function 0x{0x08000000+back+1:08X}:")
                                        print(f"    LDR R{rd}, =NOP_callback at 0x{0x08000000+pos:08X}")
                                        print(f"    BL SetMainCallback2 at 0x{0x08000000+p2:08X}")
                                        # Show context: 10 instructions before and after
                                        ctx_start = max(back, pos - 20)
                                        ctx_end = min(back + 4096, p2 + 24)
                                        for a, raw, desc, notes in disasm_range(ctx_start, ctx_end):
                                            if a >= 0x08000000 + pos and a <= 0x08000000 + p2 + 4:
                                                mrk = ">>>"
                                            else:
                                                mrk = "   "
                                            note_str = f"  ; {notes}" if notes else ""
                                            print(f"    {mrk} {a:08X}  {raw:<9s}  {desc:<40s}{note_str}")
                                        break
                            break

# 5. Search for IsLinkTaskFinished and related link sync functions
print("\n" + "=" * 70)
print("[5] Key link synchronization patterns")
print("=" * 70)

# gReceivedRemoteLinkPlayers checks in CB2_HandleStartBattle area
print("\n  gReceivedRemoteLinkPlayers (0x03003124) usage near battle init:")
grlp_bytes = struct.pack('<I', 0x03003124)
for off in range(0x037000, min(0x03A000, len(rom) - 3), 4):
    if rom[off:off+4] == grlp_bytes:
        for pos in range(max(0x037000, off - 512), off, 2):
            instr = r16(pos)
            if instr and (instr & 0xF800) == 0x4800:
                imm = (instr & 0xFF) * 4
                pca = ((pos + 4) & ~3)
                lit = pca + imm
                if lit == off:
                    rd = (instr >> 8) & 7
                    print(f"  LDR R{rd} at 0x{0x08000000+pos:08X} (literal at 0x{off:06X})")
                    # Show context
                    for a, raw, desc, notes in disasm_range(max(pos-10, 0x037000), min(pos+20, 0x03A000)):
                        mrk = ">>>" if a == 0x08000000+pos else "   "
                        note_str = f"  ; {notes}" if notes else ""
                        print(f"    {mrk} {a:08X}  {raw:<9s}  {desc:<40s}{note_str}")

# 6. What function is at 0x08038819?
print("\n" + "=" * 70)
print("[6] What is at ROM 0x038818 (callback 0x08038819)?")
print("=" * 70)
# Check the instruction
i_at = r16(0x038818)
print(f"  Instruction at 0x038818: 0x{i_at:04X}")
if i_at == 0x4770:
    print(f"  = BX LR (return immediately = NOP function)")
elif (i_at >> 8) == 0xB5:
    print(f"  = PUSH prologue (actual function)")
# Check a few instructions around it
for p in range(0x038810, 0x038830, 2):
    i = r16(p)
    if i:
        # Simple decode
        if i == 0x4770: d = "BX LR"
        elif (i >> 8) == 0xB5: d = "PUSH{...,LR}"
        elif (i >> 8) == 0xBD: d = "POP{...,PC}"
        else: d = f"0x{i:04X}"
        print(f"    0x{0x08000000+p:08X}  {d}")

# 7. gMain.state writes in CB2_HandleStartBattle
print("\n" + "=" * 70)
print("[7] gMain.state writes in battle init area")
print("=" * 70)
# gMain.state is at gMain + 0x65. In R&B, gMain = 0x02020648, so gMainState = 0x020206AD
# The compiler uses LDR Rn, =gMain then STRB Rm, [Rn, #0x65]
# Or LDR Rn, =gMainState then STRB Rm, [Rn, #0]
gmain_bytes = struct.pack('<I', 0x02020648)
for off in range(0x037000, min(0x03A000, len(rom) - 3), 4):
    if rom[off:off+4] == gmain_bytes:
        for pos in range(max(0x037000, off - 1024), off, 2):
            instr = r16(pos)
            if instr and (instr & 0xF800) == 0x4800:
                imm = (instr & 0xFF) * 4
                pca = ((pos + 4) & ~3)
                lit = pca + imm
                if lit == off:
                    rd = (instr >> 8) & 7
                    # Look for LDRB/STRB [Rn, #0x65] nearby
                    for p2 in range(pos, min(pos + 40, 0x03A000), 2):
                        i2 = r16(p2)
                        if i2:
                            # STRB Rm, [Rd, #0x65]  — 0x65 doesn't fit in 5-bit immediate (max 0x1F)
                            # So compiler uses ADD Rd, #0x65 then STRB Rm, [Rd, #0]
                            # Or uses a separate LDR for gMainState directly
                            pass

# Actually, for gMain.state at +0x65, compiler can't use STRB [Rn, #0x65] (5-bit max = 31)
# It must use: ADD Rn, #0x65 then STRB Rm, [Rn, #0]
# Let's look for the state read pattern instead: LDRB + CMP + switch
print("  Looking for gMain state read pattern (LDRB + CMP/switch)...")
for off in range(0x037000, min(0x03A000, len(rom) - 3), 4):
    if rom[off:off+4] == gmain_bytes:
        for pos in range(max(0x037000, off - 1024), off, 2):
            instr = r16(pos)
            if instr and (instr & 0xF800) == 0x4800:
                imm = (instr & 0xFF) * 4
                pca = ((pos + 4) & ~3)
                lit = pca + imm
                if lit == off:
                    rd = (instr >> 8) & 7
                    # Check if there's ADD Rd, #0x65 followed by LDRB nearby
                    for p2 in range(pos + 2, min(pos + 20, 0x03A000), 2):
                        i2 = r16(p2)
                        if i2 and (i2 & 0xF800) == 0x3000:
                            r2 = (i2 >> 8) & 7
                            imm2 = i2 & 0xFF
                            if r2 == rd and imm2 == 0x65:
                                print(f"  gMain + 0x65 (state) at 0x{0x08000000+p2:08X}")
                                # Show context
                                for a, raw, desc, notes in disasm_range(pos - 4, min(p2 + 30, 0x03A000)):
                                    note_str = f"  ; {notes}" if notes else ""
                                    print(f"    0x{a:08X}  {desc:<40s}{note_str}")
                                break

print("\n" + "=" * 70)
print("[8] Summary — Battle flow path")
print("=" * 70)
print("""
  CB2_InitBattle (0x080363C1)
    → CB2_InitBattleInternal (0x0803648D)
      → SetMainCallback2(CB2_HandleStartBattle = 0x08037B45)
        → CB2_HandleStartBattle runs with gMain.state switch
          → At some case: SetMainCallback2(NOP = 0x08038819)
            → Tasks run VS screen + link sync
              → STUCK HERE — link sync never completes
          → Need: reach SetMainCallback2(BattleMainCB2 = 0x08094815)
""")
