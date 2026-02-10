#!/usr/bin/env python3
import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
TARGET_ADDR = 0x08033448
ROM_BASE = 0x08000000

KNOWN_FUNCTIONS = {
    0x080363C0: "CB2_InitBattle",
    0x0803648C: "CB2_InitBattleInternal",
    0x08037B44: "CB2_HandleStartBattle",
    0x0803816C: "BattleMainCB2",
    0x08094814: "CB2_BattleMain",
    0x08033448: "TryReceiveLinkBattleData",
    0x08000544: "SetMainCallback2",
    0x08007440: "CB2_LoadMap",
    0x080A89A4: "CB2_Overworld",
}

def sign_extend(value, bits):
    if value & (1 << (bits - 1)):
        value -= (1 << bits)
    return value

def decode_bl_target(rom_offset, hw1, hw2):
    if (hw1 & 0xF800) != 0xF000: return None
    if (hw2 & 0xF800) != 0xF800: return None
    offset_hi = hw1 & 0x7FF
    offset_lo = hw2 & 0x7FF
    offset_hi_signed = sign_extend(offset_hi, 11)
    pc = ROM_BASE + rom_offset + 4
    target = pc + (offset_hi_signed << 12) + (offset_lo << 1)
    return target & 0xFFFFFFFF

def find_containing_function(rom_data, call_offset):
    for off in range(call_offset - 2, max(0, call_offset - 4096) - 1, -2):
        if off < 0: break
        hw = struct.unpack_from("<H", rom_data, off)[0]
        if (hw & 0xFF00) == 0xB500: return off
    return None

def lookup_func(addr):
    r = KNOWN_FUNCTIONS.get(addr)
    if r: return r
    r = KNOWN_FUNCTIONS.get(addr & ~1)
    if r: return r
    r = KNOWN_FUNCTIONS.get(addr | 1)
    if r: return r
    return None

def identify_instruction(rom_data, rom_size, ctx_off, bl_offset):
    hw = struct.unpack_from("<H", rom_data, ctx_off)[0]
    if ctx_off == bl_offset: return "BL TryReceiveLinkBattleData"
    if ctx_off == bl_offset + 2: return "(BL low half)"
    if (hw & 0xF800) == 0xF000:
        nx = ctx_off + 2
        if nx < rom_size:
            nh = struct.unpack_from("<H", rom_data, nx)[0]
            t = decode_bl_target(ctx_off, hw, nh)
            if t is not None:
                n = lookup_func(t) or "0x%08X" % t
                return "BL %s" % n
    if (hw & 0xFF00) == 0xB500: return "PUSH {...,LR}"
    if (hw & 0xFF00) == 0xBD00: return "POP {...,PC}"
    if (hw & 0xF800) == 0x4800:
        rd = (hw >> 8) & 0x7
        imm = (hw & 0xFF) * 4
        pa = ((ROM_BASE + ctx_off + 4) & ~3) + imm
        pr = pa - ROM_BASE
        if 0 <= pr < rom_size - 4:
            lit = struct.unpack_from("<I", rom_data, pr)[0]
            ln = lookup_func(lit)
            if ln: return "LDR r%d, =0x%08X (%s)" % (rd, lit, ln)
            return "LDR r%d, =0x%08X" % (rd, lit)
    if hw == 0x4770: return "BX LR"
    if (hw & 0xF000) == 0xD000:
        c = (hw >> 8) & 0xF
        cn = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE"]
        if c < 0xE:
            im = sign_extend(hw & 0xFF, 8)
            tg = ROM_BASE + ctx_off + 4 + (im << 1)
            return "%s 0x%08X" % (cn[c], tg & 0xFFFFFFFF)
    if (hw & 0xF800) == 0x6800:
        im = ((hw >> 6) & 0x1F) * 4
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        return "LDR r%d, [r%d, #0x%X]" % (rd, rb, im)
    if (hw & 0xF800) == 0x6000:
        im = ((hw >> 6) & 0x1F) * 4
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        return "STR r%d, [r%d, #0x%X]" % (rd, rb, im)
    if (hw & 0xF800) == 0x2000:
        rd = (hw >> 8) & 0x7
        return "MOVS r%d, #0x%02X" % (rd, hw & 0xFF)
    if (hw & 0xF800) == 0x2800:
        rd = (hw >> 8) & 0x7
        return "CMP r%d, #0x%02X" % (rd, hw & 0xFF)
    return ""

print("Loading ROM: %s" % ROM_PATH)
with open(ROM_PATH, "rb") as f:
    rom_data = f.read()

rom_size = len(rom_data)
print("ROM size: %d bytes (%.1f MB)" % (rom_size, rom_size / 1024 / 1024))
print("Target: TryReceiveLinkBattleData @ 0x%08X" % TARGET_ADDR)
print("Scanning for BL instructions...")
print("=" * 80)

call_sites = []
for offset in range(0, rom_size - 4, 2):
    hw1 = struct.unpack_from("<H", rom_data, offset)[0]
    if (hw1 & 0xF800) != 0xF000: continue
    hw2 = struct.unpack_from("<H", rom_data, offset + 2)[0]
    if (hw2 & 0xF800) != 0xF800: continue
    target = decode_bl_target(offset, hw1, hw2)
    if target == TARGET_ADDR:
        call_sites.append(offset)

print()
print("Found %d call site(s) to TryReceiveLinkBattleData:" % len(call_sites))
print()

for i, offset in enumerate(call_sites):
    rom_addr = ROM_BASE + offset
    hw1 = struct.unpack_from("<H", rom_data, offset)[0]
    hw2 = struct.unpack_from("<H", rom_data, offset + 2)[0]
    func_offset = find_containing_function(rom_data, offset)
    func_info = ""
    if func_offset is not None:
        fa = ROM_BASE + func_offset
        fn = lookup_func(fa)
        if fn:
            func_info = "in %s" % fn
        else:
            func_info = "function @ 0x%08X" % fa
        func_info += " (+0x%X into func)" % (offset - func_offset)
    print("  [%d] ROM offset: 0x%06X" % (i + 1, offset))
    print("       Address:    0x%08X" % rom_addr)
    print("       Encoding:   0x%04X 0x%04X" % (hw1, hw2))
    print("       Context:    %s" % func_info)
    print("       Disasm:")
    ctx_start = max(0, offset - 24)
    ctx_end = min(rom_size, offset + 16)
    for ctx_off in range(ctx_start, ctx_end, 2):
        hw = struct.unpack_from("<H", rom_data, ctx_off)[0]
        marker = " >>>" if ctx_off == offset else "    "
        ctx_addr = ROM_BASE + ctx_off
        desc = identify_instruction(rom_data, rom_size, ctx_off, offset)
        if desc: desc = "  ; " + desc
        print("      %s 0x%08X: %04X%s" % (marker, ctx_addr, hw, desc))
    print()

print("=" * 80)
print("Literal pool scan for 0x%08X and 0x%08X..." % (TARGET_ADDR, TARGET_ADDR | 1))
lit_refs = []
for offset in range(0, rom_size - 4, 4):
    val = struct.unpack_from("<I", rom_data, offset)[0]
    if val == TARGET_ADDR or val == (TARGET_ADDR | 1):
        lit_refs.append((offset, val))

print("Found %d literal pool ref(s):" % len(lit_refs))
for offset, val in lit_refs:
    rom_addr = ROM_BASE + offset
    print("  0x%06X -> 0x%08X: val=0x%08X" % (offset, rom_addr, val))
    search_start = max(0, offset - 1024)
    for ldr_off in range(search_start, offset, 2):
        hw = struct.unpack_from("<H", rom_data, ldr_off)[0]
        if (hw & 0xF800) == 0x4800:
            imm = (hw & 0xFF) * 4
            pool_addr_calc = ((ROM_BASE + ldr_off + 4) & ~3) + imm - ROM_BASE
            if pool_addr_calc == offset:
                rd = (hw >> 8) & 0x7
                func_off = find_containing_function(rom_data, ldr_off)
                fs = "unknown"
                if func_off is not None:
                    fa = ROM_BASE + func_off
                    fs = lookup_func(fa) or "func@0x%08X" % fa
                print("    <- LDR r%d at 0x%08X (in %s)" % (rd, ROM_BASE + ldr_off, fs))

print()
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print("BL call sites: %d" % len(call_sites))
print("Literal pool refs: %d" % len(lit_refs))
for offset in call_sites:
    print("  BL at 0x%08X" % (ROM_BASE + offset))
for offset, val in lit_refs:
    print("  LitPool at 0x%08X (val 0x%08X)" % (ROM_BASE + offset, val))
print("Done.")
