"""
Focused analysis: trace the path from stuck NOP callback to BattleMainCB2.

Key findings from deep analysis:
- CB2_HandleStartBattle switch is on gBattleCommunication[0], 11 cases (0-10)
- Jump table at 0x08037B88
- SetMainCallback2 calls with sub-callbacks: 0x0803816D, 0x08038231, 0x030022C0
- NOP callback = 0x08038819 (BX LR)
- BattleMainCB2 = 0x08094815, referenced by functions at 0x08094761, 0x080947F1

This script:
1. Decodes the jump table to get all case addresses
2. Disassembles each case individually
3. Traces the sub-callbacks (0x0803816D, 0x08038231)
4. Disassembles the BattleMainCB2 setter functions
5. Searches for ALL references to 0x08038819 in ROM
"""
import struct, os, sys

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rom", "Pokemon RunBun.gba")

with open(ROM_PATH, 'rb') as f:
    rom = f.read()

# Force UTF-8 output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

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
    instr = r16(pos)
    if not instr or (instr & 0xF800) != 0x4800: return None
    imm = (instr & 0xFF) * 4
    pca = ((pos + 4) & ~3)
    return r32(pca + imm)

LABELS = {
    0x08000544: "SetMainCallback2",
    0x08038819: "NOP_cb", 0x08038818: "NOP_cb",
    0x08094815: "BattleMainCB2", 0x08094814: "BattleMainCB2",
    0x080363C1: "CB2_InitBattle", 0x080363C0: "CB2_InitBattle",
    0x0803648D: "CB2_InitBattleInternal",
    0x08037B45: "CB2_HandleStartBattle", 0x08037B44: "CB2_HandleStartBattle",
    0x0800A4B1: "GetMultiplayerId", 0x0800A4B0: "GetMultiplayerId",
    0x0803816D: "sub_callback_A", 0x0803816C: "sub_callback_A",
    0x08038231: "sub_callback_B", 0x08038230: "sub_callback_B",
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
    0x030022C0: "IWRAM_savedCallback",
    0x04000128: "REG_SIOCNT",
    0x080A89A5: "CB2_Overworld",
}

def label(val):
    if val in LABELS: return LABELS[val]
    if (val & ~1) in LABELS: return LABELS[val & ~1]
    return ""

def disasm(start, end_off):
    lines = []
    pos = start
    while pos < end_off and pos < len(rom) - 1:
        instr = r16(pos)
        if instr is None: break
        addr = 0x08000000 + pos
        raw = f"{instr:04X}"
        desc = f"0x{instr:04X}"
        notes = ""

        if (instr >> 8) == 0xB5:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            desc = f"PUSH {{{','.join(regs)},LR}}"
        elif (instr >> 8) == 0xBD:
            regs = [f"R{r}" for r in range(8) if instr & (1<<r)]
            desc = f"POP {{{','.join(regs)},PC}}"
        elif (instr & 0xF800) == 0xF000 and pos + 3 < end_off:
            nxt = r16(pos + 2)
            if nxt and (nxt & 0xF800) == 0xF800:
                target = decode_bl(instr, nxt, addr + 4)
                lbl = label(target)
                desc = f"BL 0x{target:08X}"
                if lbl: notes = lbl
                lines.append((addr, f"{instr:04X} {nxt:04X}", desc, notes))
                pos += 4
                continue
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            v = ldr_pool_val(pos)
            if v is not None:
                lbl = label(v)
                desc = f"LDR R{rd}, =0x{v:08X}"
                if lbl: notes = lbl
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
            cs = {0:'EQ',1:'NE',2:'CS',3:'CC',4:'MI',5:'PL',8:'HI',9:'LS',10:'GE',11:'LT',12:'GT',13:'LE'}
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
            desc = f"{'SUB' if instr & 0x80 else 'ADD'} SP, #{imm}"
        elif (instr & 0xF800) == 0x9800:
            desc = f"LDR R{(instr>>8)&7}, [SP, #0x{(instr&0xFF)*4:X}]"
        elif (instr & 0xF800) == 0x9000:
            desc = f"STR R{(instr>>8)&7}, [SP, #0x{(instr&0xFF)*4:X}]"
        elif (instr & 0xFE00) == 0x1800:
            desc = f"ADD R{instr&7}, R{(instr>>3)&7}, R{(instr>>6)&7}"
        elif (instr & 0xFE00) == 0x1C00:
            desc = f"ADD R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&7}"
        elif (instr & 0xF800) == 0x0000 and instr != 0:
            desc = f"LSL R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&0x1F}"
        elif (instr & 0xF800) == 0x0800:
            desc = f"LSR R{instr&7}, R{(instr>>3)&7}, #{(instr>>6)&0x1F}"

        lines.append((addr, raw, desc, notes))
        pos += 2
    return lines

def print_disasm(start, end_off, title=""):
    if title: print(f"\n  --- {title} ---")
    for addr, raw, desc, notes in disasm(start, end_off):
        note_str = f"  ; {notes}" if notes else ""
        important = any(k in notes for k in ["SetMainCallback2", "NOP_cb", "BattleMainCB2", "gBattleCommunication", "gReceivedRemoteLinkPlayers", "gMain.inBattle"])
        mrk = ">>>" if important else "   "
        print(f"  {mrk} {addr:08X}  {raw:<9s}  {desc:<45s}{note_str}")

# ================================================================
print("=" * 70)
print("STEP 1: Decode jump table (gBattleCommunication[0] switch)")
print("=" * 70)

jt_base = 0x037B88  # Jump table in ROM
cases = []
for i in range(11):
    val = r32(jt_base + i * 4)
    rom_off = val - 0x08000000
    cases.append((i, val, rom_off))
    print(f"  Case {i:2d}: 0x{val:08X}")

# ================================================================
print("\n" + "=" * 70)
print("STEP 2: Disassemble each case (key cases only)")
print("=" * 70)

for i in range(11):
    case_idx, case_addr, case_rom = cases[i]
    if i + 1 < 11:
        next_rom = cases[i+1][2]
    else:
        next_rom = case_rom + 256
    case_size = next_rom - case_rom
    print(f"\n{'='*50}")
    print(f"  CASE {i} at 0x{case_addr:08X} ({case_size} bytes)")
    print(f"{'='*50}")
    # Disassemble with a reasonable limit
    end = min(case_rom + case_size, case_rom + 400)
    print_disasm(case_rom, end)

# ================================================================
print("\n" + "=" * 70)
print("STEP 3: Sub-callback A at 0x0803816D (set by Case 10)")
print("=" * 70)
# Find function extent
sub_a_start = 0x03816C
sub_a_end = sub_a_start + 256
# Find POP{PC} to determine end
for p in range(sub_a_start, sub_a_start + 512, 2):
    i = r16(p)
    if i and (i >> 8) == 0xBD:
        sub_a_end = p + 2
        break
print(f"  sub_callback_A: 0x{0x08000000+sub_a_start:08X} to 0x{0x08000000+sub_a_end:08X} ({sub_a_end-sub_a_start} bytes)")
print_disasm(sub_a_start, sub_a_end)

# ================================================================
print("\n" + "=" * 70)
print("STEP 4: Sub-callback B at 0x08038231 (set after A)")
print("=" * 70)
sub_b_start = 0x038230
sub_b_end = sub_b_start + 256
for p in range(sub_b_start, sub_b_start + 512, 2):
    i = r16(p)
    if i and (i >> 8) == 0xBD:
        sub_b_end = p + 2
        break
print(f"  sub_callback_B: 0x{0x08000000+sub_b_start:08X} to 0x{0x08000000+sub_b_end:08X} ({sub_b_end-sub_b_start} bytes)")
print_disasm(sub_b_start, sub_b_end)

# ================================================================
print("\n" + "=" * 70)
print("STEP 5: Functions that set BattleMainCB2 (0x08094815)")
print("=" * 70)

# Function at 0x08094761
func1_start = 0x094760
func1_end = func1_start + 256
for p in range(func1_start + 2, func1_start + 512, 2):
    i = r16(p)
    if i and (i >> 8) == 0xBD:
        func1_end = p + 2
        break
print(f"\n  Function 1: 0x{0x08000000+func1_start:08X} ({func1_end-func1_start} bytes)")
print_disasm(func1_start, func1_end)

# Function at 0x080947F1
func2_start = 0x0947F0
func2_end = func2_start + 256
for p in range(func2_start + 2, func2_start + 512, 2):
    i = r16(p)
    if i and (i >> 8) == 0xBD:
        func2_end = p + 2
        break
print(f"\n  Function 2: 0x{0x08000000+func2_start:08X} ({func2_end-func2_start} bytes)")
print_disasm(func2_start, func2_end)

# ================================================================
print("\n" + "=" * 70)
print("STEP 6: ALL literal pool refs to 0x08038819 in entire ROM")
print("=" * 70)
nop_val_1 = struct.pack('<I', 0x08038819)
nop_val_2 = struct.pack('<I', 0x08038818)
found = 0
for off in range(0, len(rom) - 3, 4):
    if rom[off:off+4] in (nop_val_1, nop_val_2):
        val = r32(off)
        found += 1
        # Find the LDR instruction that loads this
        for pos in range(max(0, off - 1024), off, 2):
            instr = r16(pos)
            if instr and (instr & 0xF800) == 0x4800:
                imm = (instr & 0xFF) * 4
                pca = ((pos + 4) & ~3)
                lit = pca + imm
                if lit == off:
                    rd = (instr >> 8) & 7
                    # Find containing function
                    fn_start = None
                    for back in range(pos, max(0, pos-8192), -2):
                        fi = r16(back)
                        if fi and (fi >> 8) == 0xB5:
                            fn_start = back
                            break
                    fn_str = f"in func 0x{0x08000000+fn_start+1:08X}" if fn_start else ""
                    print(f"  Literal at 0x{off:06X} (val=0x{val:08X}), LDR R{rd} at 0x{0x08000000+pos:08X} {fn_str}")
                    # Check if followed by BL SetMainCallback2
                    for p2 in range(pos + 2, min(pos + 30, len(rom) - 3), 2):
                        h = r16(p2)
                        l = r16(p2 + 2) if p2 + 3 < len(rom) else None
                        if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800:
                            target = decode_bl(h, l, 0x08000000 + p2 + 4)
                            if target == 0x08000544:
                                print(f"    -> BL SetMainCallback2 at 0x{0x08000000+p2:08X}")
                            break
                    break
if found == 0:
    print("  NONE FOUND! NOP callback may be set via indirect reference.")
    # Search for the value as a direct STR to callback2 address
    print("  Searching for STR to callback2 (0x0202064C)...")
    cb2_bytes = struct.pack('<I', 0x0202064C)
    for off in range(0x037000, min(0x039000, len(rom) - 3), 4):
        if rom[off:off+4] == cb2_bytes:
            print(f"    callback2 addr in literal pool at 0x{off:06X}")

# ================================================================
print("\n" + "=" * 70)
print("STEP 7: What calls BattleMainCB2-setter functions?")
print("=" * 70)
# Find BL calls to 0x08094761 and 0x080947F1
for target_addr, name in [(0x08094760, "func_0x08094761"), (0x080947F0, "func_0x080947F1")]:
    print(f"\n  BL calls to {name}:")
    for pos in range(0, len(rom) - 3, 2):
        h = r16(pos)
        l = r16(pos + 2)
        if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800:
            target = decode_bl(h, l, 0x08000000 + pos + 4)
            if (target & ~1) == target_addr:
                fn_start = None
                for back in range(pos, max(0, pos-8192), -2):
                    fi = r16(back)
                    if fi and (fi >> 8) == 0xB5:
                        fn_start = back
                        break
                fn_str = f"in func 0x{0x08000000+fn_start+1:08X}" if fn_start else ""
                print(f"    BL at 0x{0x08000000+pos:08X} {fn_str}")

# ================================================================
print("\n" + "=" * 70)
print("STEP 8: IsLinkTaskFinished candidates")
print("=" * 70)
# IsLinkTaskFinished is commonly called before advancing link states
# It typically checks gLinkStatus or similar — search for BL targets from CB2_HandleStartBattle
bl_targets = {}
for pos in range(0x037B44, 0x038B44, 2):
    h = r16(pos)
    l = r16(pos + 2) if pos + 3 < len(rom) else None
    if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800:
        target = decode_bl(h, l, 0x08000000 + pos + 4)
        if target not in bl_targets:
            bl_targets[target] = []
        bl_targets[target].append(0x08000000 + pos)

print(f"  Unique BL targets from CB2_HandleStartBattle: {len(bl_targets)}")
# Show the most frequently called
sorted_targets = sorted(bl_targets.items(), key=lambda x: -len(x[1]))
for target, callers in sorted_targets[:20]:
    lbl = label(target)
    print(f"    0x{target:08X} ({len(callers):2d} calls) {lbl}")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"""
CB2_HandleStartBattle switch on gBattleCommunication[0], 11 cases:
  Cases 0-6: Battle init, link checks, VS screen
  Cases 7-9: More init with gBattleTypeFlags checks
  Case 10: SetMainCallback2 to sub-callbacks

Sub-callbacks: 0x0803816D and 0x08038231
NOP callback: 0x08038819 = BX LR (literal pool existence checked above)
BattleMainCB2 setters: 0x08094761, 0x080947F1
""")
