"""
Find the link synchronization wait that prevents the battle from proceeding
past the VS screen.

The game sets callback2 = 0x08038819 (BX LR = NOP) while tasks run.
We need to find:
1. Where SetMainCallback2(0x08038819) is called
2. What conditions advance past the wait
3. Where gMain.inBattle = TRUE is set
4. What gBattleCommunication values are checked
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

with open(ROM_PATH, 'rb') as f:
    rom = f.read()

NOP_CALLBACK = 0x08038819
SET_MAIN_CB2 = 0x08000544
GMAIN_BASE = 0x02020648
IN_BATTLE_ADDR = 0x020206AE  # gMain + 0x66
BATTLE_MAIN_CB2 = 0x08094815
GCOMM = 0x0202370E
CB2_HANDLE_START = 0x08037B44

# ================================================================
# 1. Find all literal pool refs to 0x08038819
# ================================================================
print("=" * 70)
print("[1] Literal pool refs to NOP callback (0x08038819)")
print("=" * 70)
target_bytes = [struct.pack('<I', 0x08038819), struct.pack('<I', 0x08038818)]
lit_refs = []
for off in range(0, len(rom) - 3, 4):
    if rom[off:off+4] in target_bytes:
        lit_refs.append(off)
        val = read_u32(rom, off)
        # Find LDR instruction that loads this
        for pos in range(max(0, off - 1024), off, 2):
            instr = read_u16(rom, pos)
            if instr and (instr & 0xF800) == 0x4800:
                imm = (instr & 0xFF) * 4
                pca = ((pos + 4) & ~3) + 0x08000000
                lit = pca + imm - 0x08000000
                if lit == off:
                    rd = (instr >> 8) & 7
                    fs = find_func_start(rom, pos)
                    fn_str = f"in func 0x{0x08000000+fs+1:08X}" if fs else ""
                    # Check if followed by BL SetMainCallback2
                    for p2 in range(pos + 2, min(pos + 20, len(rom) - 3), 2):
                        i2 = read_u16(rom, p2)
                        i3 = read_u16(rom, p2 + 2) if p2 + 3 < len(rom) else None
                        if i2 and i3 and (i2 & 0xF800) == 0xF000 and (i3 & 0xF800) == 0xF800:
                            bl_target = decode_bl(i2, i3, 0x08000000 + p2 + 4)
                            if bl_target == SET_MAIN_CB2:
                                print(f"  LDR R{rd} at 0x{0x08000000+pos:08X} + BL SetMainCallback2 at 0x{0x08000000+p2:08X} {fn_str}")
                            break

# ================================================================
# 2. Find where gMain.inBattle = TRUE is set (STRB #1 to 0x020206AE)
# ================================================================
print(f"\n{'='*70}")
print("[2] Finding where gMain.inBattle = TRUE (STRB #1 to gMain+0x66)")
print("=" * 70)
# In THUMB: to set gMain.inBattle = 1, the code typically does:
# LDR Rn, =gMainAddr -> MOV Rm, #1 -> STRB Rm, [Rn, #0x66]
# But 0x66 doesn't fit in a 5-bit immediate (max 0x1F for STRB)
# So it might use: LDR Rn, =gMainAddr -> ADD Rn, #0x66 -> MOV Rm, #1 -> STRB Rm, [Rn, #0]
# Or: LDR Rn, =0x020206AE -> MOV Rm, #1 -> STRB Rm, [Rn, #0]

# Search for literal pool refs to IN_BATTLE_ADDR (0x020206AE)
print(f"  Searching for literal pool refs to 0x{IN_BATTLE_ADDR:08X}...")
ib_refs = []
ib_bytes = struct.pack('<I', IN_BATTLE_ADDR)
for off in range(0, len(rom) - 3, 4):
    if rom[off:off+4] == ib_bytes:
        ib_refs.append(off)
print(f"  Found {len(ib_refs)} literal pool refs to gMain.inBattle address")
for ref in ib_refs:
    for pos in range(max(0, ref - 1024), ref, 2):
        instr = read_u16(rom, pos)
        if instr and (instr & 0xF800) == 0x4800:
            imm = (instr & 0xFF) * 4
            pca = ((pos + 4) & ~3) + 0x08000000
            lit = pca + imm - 0x08000000
            if lit == ref:
                rd = (instr >> 8) & 7
                fs = find_func_start(rom, pos)
                fn_str = f"in func 0x{0x08000000+fs+1:08X}" if fs else ""
                addr = 0x08000000 + pos
                # Look for MOV Rm, #1 / STRB pattern nearby
                context = []
                for ci in range(-4, 10, 2):
                    ci_pos = pos + ci
                    if ci_pos >= 0 and ci_pos < len(rom) - 1:
                        ci_instr = read_u16(rom, ci_pos)
                        ci_addr = 0x08000000 + ci_pos
                        if ci_instr is not None:
                            desc = f"0x{ci_instr:04X}"
                            if (ci_instr & 0xF800) == 0x2000:
                                desc = f"MOV R{(ci_instr>>8)&7}, #{ci_instr&0xFF}"
                            elif (ci_instr & 0xF800) == 0x7000:
                                desc = f"STRB R{ci_instr&7}, [R{(ci_instr>>3)&7}, #0x{(ci_instr>>6)&0x1F:X}]"
                            elif (ci_instr & 0xF800) == 0x4800:
                                lit_imm = (ci_instr & 0xFF) * 4
                                lit_pca = ((ci_pos + 4) & ~3) + 0x08000000
                                lit_a = lit_pca + lit_imm - 0x08000000
                                if 0 <= lit_a < len(rom) - 3:
                                    v = read_u32(rom, lit_a)
                                    desc = f"LDR R{(ci_instr>>8)&7}, =0x{v:08X}"
                            context.append(f"    0x{ci_addr:08X} {desc}")
                print(f"  LDR R{rd} at 0x{addr:08X} {fn_str}")
                for c in context:
                    print(c)

# ================================================================
# 3. Find BattleMainCB2 literal pool refs (who sets callback2 = BattleMainCB2?)
# ================================================================
print(f"\n{'='*70}")
print(f"[3] Who sets callback2 = BattleMainCB2 (0x{BATTLE_MAIN_CB2:08X})?")
print("=" * 70)
bm_bytes = struct.pack('<I', BATTLE_MAIN_CB2)
bm_bytes2 = struct.pack('<I', BATTLE_MAIN_CB2 - 1)
bm_refs = []
for off in range(0, len(rom) - 3, 4):
    if rom[off:off+4] == bm_bytes or rom[off:off+4] == bm_bytes2:
        bm_refs.append(off)
print(f"  Found {len(bm_refs)} literal pool refs")
for ref in bm_refs[:8]:
    for pos in range(max(0, ref - 1024), ref, 2):
        instr = read_u16(rom, pos)
        if instr and (instr & 0xF800) == 0x4800:
            imm = (instr & 0xFF) * 4
            pca = ((pos + 4) & ~3) + 0x08000000
            lit = pca + imm - 0x08000000
            if lit == ref:
                rd = (instr >> 8) & 7
                fs = find_func_start(rom, pos)
                fn_str = f"in func 0x{0x08000000+fs+1:08X}" if fs else ""
                print(f"  LDR at 0x{0x08000000+pos:08X} {fn_str}")

# ================================================================
# 4. Disassemble CB2_HandleStartBattle fully (look for link waits)
# ================================================================
print(f"\n{'='*70}")
print(f"[4] CB2_HandleStartBattle (0x08037B45) — full switch analysis")
print("=" * 70)

# Find the switch cases by looking for gMain.state reads and comparisons
# The function reads gMain.state via LDR Rn, =gMainAddr then LDRB Rm, [Rn, #stateOff]
# gMain.state is at gMain + 0x65 in R&B

# Disassemble the full function (up to 4KB)
pos = CB2_HANDLE_START
end = min(CB2_HANDLE_START + 4096, len(rom))
case_addrs = []
bl_targets = []
ldr_values = []

while pos < end:
    instr = read_u16(rom, pos)
    if instr is None: break
    addr = 0x08000000 + pos

    # Track CMP instructions
    if (instr & 0xF800) == 0x2800:
        rd = (instr >> 8) & 7
        imm = instr & 0xFF
        if imm >= 5 and imm <= 20:  # Likely switch case count
            print(f"  CMP R{rd}, #{imm} at 0x{addr:08X} — possible switch max case")

    # Track LDR =address
    if (instr & 0xF800) == 0x4800:
        rd = (instr >> 8) & 7
        imm = (instr & 0xFF) * 4
        pca = ((pos + 4) & ~3) + 0x08000000
        la = pca + imm - 0x08000000
        if 0 <= la < len(rom) - 3:
            v = read_u32(rom, la)
            if v == NOP_CALLBACK or v == (NOP_CALLBACK - 1):
                print(f"  *** LDR R{rd}, =0x{v:08X} (NOP callback) at 0x{addr:08X}")
            elif v == BATTLE_MAIN_CB2 or v == (BATTLE_MAIN_CB2 - 1):
                print(f"  *** LDR R{rd}, =0x{v:08X} (BattleMainCB2) at 0x{addr:08X}")
            elif v == SET_MAIN_CB2 or v == (SET_MAIN_CB2 - 1):
                print(f"  *** LDR R{rd}, =0x{v:08X} (SetMainCallback2) at 0x{addr:08X}")
            elif v == GCOMM:
                print(f"  LDR R{rd}, =0x{v:08X} (gBattleCommunication) at 0x{addr:08X}")
            elif v == IN_BATTLE_ADDR:
                print(f"  *** LDR R{rd}, =0x{v:08X} (gMain.inBattle) at 0x{addr:08X}")

    # Track BL targets
    if (instr & 0xF800) == 0xF000 and pos + 3 < end:
        nxt = read_u16(rom, pos + 2)
        if nxt and (nxt & 0xF800) == 0xF800:
            target = decode_bl(instr, nxt, addr + 4)
            if target == SET_MAIN_CB2:
                print(f"  BL SetMainCallback2 at 0x{addr:08X}")
            pos += 4
            continue

    # Track POP {PC} (function returns)
    if (instr >> 8) == 0xBD:
        # Check if this might be the end of the function
        # (but might just be a nested function or inline)
        pass

    pos += 2

# ================================================================
# 5. Find gBattleCommunication checks near the stuck point
# ================================================================
print(f"\n{'='*70}")
print("[5] gBattleCommunication usage in CB2_HandleStartBattle area")
print("=" * 70)
# Look at all code between CB2_HandleStartBattle and the stuck callback
scan_start = CB2_HANDLE_START
scan_end = min(CB2_HANDLE_START + 8192, len(rom))
gcomm_bytes = struct.pack('<I', GCOMM)
for off in range(scan_start, scan_end, 4):
    if rom[off:off+4] == gcomm_bytes:
        # Find the LDR instruction
        for pos in range(max(scan_start, off - 1024), off, 2):
            instr = read_u16(rom, pos)
            if instr and (instr & 0xF800) == 0x4800:
                imm = (instr & 0xFF) * 4
                pca = ((pos + 4) & ~3) + 0x08000000
                lit = pca + imm - 0x08000000
                if lit == off:
                    rd = (instr >> 8) & 7
                    addr = 0x08000000 + pos
                    # Show context (5 instructions before and after)
                    print(f"\n  gBattleCommunication loaded by LDR R{rd} at 0x{addr:08X}:")
                    for ci in range(-10, 20, 2):
                        ci_pos = pos + ci
                        if ci_pos >= scan_start and ci_pos < scan_end:
                            ci_instr = read_u16(rom, ci_pos)
                            ci_addr = 0x08000000 + ci_pos
                            marker = " >>>" if ci == 0 else "    "
                            desc = f"0x{ci_instr:04X}" if ci_instr else "????"
                            # Decode common instructions
                            if ci_instr:
                                if (ci_instr & 0xF800) == 0x2000:
                                    desc = f"MOV R{(ci_instr>>8)&7}, #{ci_instr&0xFF}"
                                elif (ci_instr & 0xF800) == 0x2800:
                                    desc = f"CMP R{(ci_instr>>8)&7}, #{ci_instr&0xFF}"
                                elif (ci_instr & 0xF800) == 0x7800:
                                    desc = f"LDRB R{ci_instr&7}, [R{(ci_instr>>3)&7}, #0x{(ci_instr>>6)&0x1F:X}]"
                                elif (ci_instr & 0xF800) == 0x7000:
                                    desc = f"STRB R{ci_instr&7}, [R{(ci_instr>>3)&7}, #0x{(ci_instr>>6)&0x1F:X}]"
                                elif (ci_instr & 0xF800) == 0x4800:
                                    lit_imm = (ci_instr & 0xFF) * 4
                                    lit_pca = ((ci_pos + 4) & ~3) + 0x08000000
                                    lit_a = lit_pca + lit_imm - 0x08000000
                                    if 0 <= lit_a < len(rom) - 3:
                                        v = read_u32(rom, lit_a)
                                        desc = f"LDR R{(ci_instr>>8)&7}, =0x{v:08X}"
                                elif (ci_instr & 0xF000) == 0xD000:
                                    cond = (ci_instr >> 8) & 0xF
                                    immb = ci_instr & 0xFF
                                    if immb >= 0x80: immb -= 0x100
                                    cs = {0:'EQ',1:'NE',2:'CS',3:'CC',4:'MI',5:'PL'}
                                    desc = f"B{cs.get(cond,'??')} 0x{ci_addr+4+immb*2:08X}"
                                elif (ci_instr & 0xF800) == 0xF000:
                                    ci_nxt = read_u16(rom, ci_pos + 2)
                                    if ci_nxt and (ci_nxt & 0xF800) == 0xF800:
                                        bl_tgt = decode_bl(ci_instr, ci_nxt, ci_addr + 4)
                                        desc = f"BL 0x{bl_tgt:08X}"
                            print(f"  {marker} 0x{ci_addr:08X} {desc}")
                    break

print(f"\n{'='*70}")
print("[6] Summary")
print("=" * 70)
print(f"  NOP callback (0x08038819) refs: {len(lit_refs)}")
print(f"  gMain.inBattle refs: {len(ib_refs)}")
print(f"  BattleMainCB2 refs: {len(bm_refs)}")
