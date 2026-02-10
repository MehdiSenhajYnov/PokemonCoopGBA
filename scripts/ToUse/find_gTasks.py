"""Find gTasks array address in Pokemon Run & Bun ROM."""
import struct, os, sys

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rom", "Pokemon RunBun.gba")

def ru16(d, o):
    if o + 2 > len(d): return None
    return struct.unpack_from("<H", d, o)[0]

def ru32(d, o):
    if o + 4 > len(d): return None
    return struct.unpack_from("<I", d, o)[0]

def decode_bl(h, l, pc):
    full = ((h & 0x7FF) << 12) | ((l & 0x7FF) << 1)
    if full >= 0x400000: full -= 0x800000
    return pc + full

def find_func_start(data, offset, max_back=4096):
    for pos in range(offset - 2, max(0, offset - max_back) - 1, -2):
        i = ru16(data, pos)
        if i is not None and (i >> 8) == 0xB5: return pos
    return None

def disasm(data, start, count=50):
    lines = []
    pos = start
    for _ in range(count):
        if pos + 2 > len(data): break
        ins = ru16(data, pos)
        addr = 0x08000000 + pos
        desc = ""
        hi = (ins >> 8) & 0xFF
        if hi == 0xB5:
            rr = [f"r{i}" for i in range(8) if ins & (1<<i)]
            if ins & 0x100: rr.append("lr")
            desc = "PUSH {" + ", ".join(rr) + "}"
        elif hi == 0xBD:
            rr = [f"r{i}" for i in range(8) if ins & (1<<i)]
            if ins & 0x100: rr.append("pc")
            desc = "POP {" + ", ".join(rr) + "}"
        elif (ins & 0xF800) == 0x2000:
            desc = f"MOV r{(ins>>8)&7}, #0x{ins&0xFF:02X}"
        elif (ins & 0xF800) == 0x4800:
            off = (ins & 0xFF) * 4
            lpc = (pos + 4) & ~3
            t = lpc + off
            v = ru32(data, t) if t + 4 <= len(data) else None
            desc = f"LDR r{(ins>>8)&7}, [PC, #0x{off:X}]" + (f"  ; =0x{v:08X}" if v else "")
        elif (ins & 0xFFC0) == 0x4340:
            desc = f"MUL r{ins&7}, r{(ins>>3)&7}"
        elif (ins & 0xFE00) == 0x1800:
            desc = f"ADD r{ins&7}, r{(ins>>3)&7}, r{(ins>>6)&7}"
        elif (ins & 0xF800) == 0x3000:
            desc = f"ADD r{(ins>>8)&7}, #0x{ins&0xFF:02X}"
        elif (ins & 0xF800) == 0x3800:
            desc = f"SUB r{(ins>>8)&7}, #0x{ins&0xFF:02X}"
        elif (ins & 0xF800) == 0x7000:
            desc = f"STRB r{ins&7}, [r{(ins>>3)&7}, #0x{(ins>>6)&0x1F:X}]"
        elif (ins & 0xF800) == 0x7800:
            desc = f"LDRB r{ins&7}, [r{(ins>>3)&7}, #0x{(ins>>6)&0x1F:X}]"
        elif (ins & 0xF800) == 0x6000:
            desc = f"STR r{ins&7}, [r{(ins>>3)&7}, #0x{((ins>>6)&0x1F)*4:X}]"
        elif (ins & 0xF800) == 0x6800:
            desc = f"LDR r{ins&7}, [r{(ins>>3)&7}, #0x{((ins>>6)&0x1F)*4:X}]"
        elif (ins & 0xF800) == 0x8000:
            desc = f"STRH r{ins&7}, [r{(ins>>3)&7}, #0x{((ins>>6)&0x1F)*2:X}]"
        elif (ins & 0xF800) == 0x8800:
            desc = f"LDRH r{ins&7}, [r{(ins>>3)&7}, #0x{((ins>>6)&0x1F)*2:X}]"
        elif (ins & 0xF800) == 0xF000:
            if pos + 4 <= len(data):
                i2 = ru16(data, pos + 2)
                if i2 is not None and (i2 & 0xF800) == 0xF800:
                    tgt = decode_bl(ins, i2, 0x08000000 + pos + 4)
                    desc = f"BL 0x{tgt:08X}"
                    lines.append(f"  0x{addr:08X}: {ins:04X} {i2:04X}  {desc}")
                    pos += 4
                    continue
        elif (ins & 0xF800) == 0xE000:
            imm = ins & 0x7FF
            if imm >= 0x400: imm -= 0x800
            desc = f"B 0x{0x08000000+pos+4+imm*2:08X}"
        elif ins == 0x4770: desc = "BX LR"
        elif (ins & 0xFF00) == 0x4700: desc = f"BX r{(ins>>3)&0xF}"
        elif (ins & 0xFF00) == 0x4600:
            desc = f"MOV r{(ins&7)|((ins>>4)&8)}, r{(ins>>3)&0xF}"
        elif (ins & 0xFFC0) == 0x4280: desc = f"CMP r{ins&7}, r{(ins>>3)&7}"
        elif (ins & 0xF800) == 0x2800: desc = f"CMP r{(ins>>8)&7}, #0x{ins&0xFF:02X}"
        elif (ins & 0xFF00) == 0xD000:
            o8 = ins & 0xFF
            if o8 >= 0x80: o8 -= 0x100
            desc = f"BEQ 0x{0x08000000+pos+4+o8*2:08X}"
        elif (ins & 0xFF00) == 0xD100:
            o8 = ins & 0xFF
            if o8 >= 0x80: o8 -= 0x100
            desc = f"BNE 0x{0x08000000+pos+4+o8*2:08X}"
        elif (ins & 0xFFC0) == 0x0000 and ins != 0:
            desc = f"LSL r{ins&7}, r{(ins>>3)&7}, #0x{(ins>>6)&0x1F:X}"
        lines.append(f"  0x{addr:08X}: {ins:04X}      {desc}")
        pos += 2
    return "\n".join(lines)

def main():
    print("=" * 70)
    print("gTasks FINDER - Pokemon Run & Bun ROM Scanner")
    print("=" * 70)
    with open(ROM_PATH, "rb") as f:
        rom = f.read()
    print(f"ROM loaded: {len(rom)} bytes ({len(rom)/(1024*1024):.1f} MB)")
    SCAN = min(len(rom), 0x800000)
    KNOWN = {0x030022C0: "gMain", 0x03005D90: "gRngValue", 0x03005D70: "gBattlerControllerFuncs"}

    # PHASE 1: IWRAM literal pool frequency
    print("\n" + "=" * 70)
    print("PHASE 1: IWRAM literal pool frequency")
    print("=" * 70)
    iwram_refs = {}
    for pos in range(0, SCAN - 3, 4):
        val = ru32(rom, pos)
        if val and 0x03000000 <= val < 0x03008000:
            iwram_refs.setdefault(val, []).append(pos)
    sorted_iwram = sorted(iwram_refs.items(), key=lambda x: -len(x[1]))
    print(f"Found {len(sorted_iwram)} unique IWRAM addresses")
    for addr, refs in sorted_iwram[:40]:
        note = KNOWN.get(addr, "")
        if not note and abs(addr - 0x030022C0) < 0x800:
            d = addr - 0x030022C0
            note = f"(gMain+0x{d:X})" if d >= 0 else f"(gMain-0x{-d:X})"
        print(f"  0x{addr:08X} {len(refs):>6}  {note}")

    # PHASE 2: MOV #0x28 + MUL sites
    print("\n" + "=" * 70)
    print("PHASE 2: MOV #0x28 + MUL sites")
    print("=" * 70)
    mul28_sites = []
    for pos in range(0, SCAN - 20, 2):
        ins = ru16(rom, pos)
        if ins and (ins & 0xF800) == 0x2000 and (ins & 0xFF) == 0x28:
            for off in range(2, 16, 2):
                i2 = ru16(rom, pos + off)
                if i2 is not None and (i2 & 0xFFC0) == 0x4340:
                    mul28_sites.append(pos)
                    break
    print(f"Found {len(mul28_sites)} MOV#0x28 + MUL sites")

    # Cross-ref IWRAM addresses near MUL28 sites
    iwram_near = {}
    for site in mul28_sites:
        for off in range(-40, 40, 2):
            cp = site + off
            if cp < 0 or cp + 2 > len(rom): continue
            ins = ru16(rom, cp)
            if ins and (ins & 0xF800) == 0x4800:
                imm = (ins & 0xFF) * 4
                lpc = (cp + 4) & ~3
                lo = lpc + imm
                if lo + 4 <= len(rom):
                    val = ru32(rom, lo)
                    if val and 0x03000000 <= val < 0x03008000:
                        iwram_near.setdefault(val, []).append(site)
    sorted_near = sorted(iwram_near.items(), key=lambda x: -len(x[1]))
    print("\nIWRAM addresses near MOV#0x28+MUL:")
    for addr, sites in sorted_near[:20]:
        tr = len(iwram_refs.get(addr, []))
        note = KNOWN.get(addr, "")
        print(f"  0x{addr:08X}: {len(sites)} MUL28-hits (total refs: {tr}) {note}")

    # Also EWRAM
    ewram_near = {}
    for site in mul28_sites:
        for off in range(-40, 40, 2):
            cp = site + off
            if cp < 0 or cp + 2 > len(rom): continue
            ins = ru16(rom, cp)
            if ins and (ins & 0xF800) == 0x4800:
                imm = (ins & 0xFF) * 4
                lpc = (cp + 4) & ~3
                lo = lpc + imm
                if lo + 4 <= len(rom):
                    val = ru32(rom, lo)
                    if val and 0x02000000 <= val < 0x02040000:
                        ewram_near.setdefault(val, []).append(site)
    sorted_ewram = sorted(ewram_near.items(), key=lambda x: -len(x[1]))
    if sorted_ewram:
        print("\nEWRAM addresses near MOV#0x28+MUL:")
        for addr, sites in sorted_ewram[:10]:
            print(f"  0x{addr:08X}: {len(sites)} MUL28-hits")

    # PHASE 3: CreateTask identification
    print("\n" + "=" * 70)
    print("PHASE 3: CreateTask identification")
    print("=" * 70)
    best_addr = sorted_near[0][0] if sorted_near and len(sorted_near[0][1]) >= 3 else None
    if best_addr:
        refs = iwram_refs.get(best_addr, [])
        print(f"Analyzing candidate 0x{best_addr:08X} ({len(refs)} refs)")
        func_map = {}
        for ro in refs:
            fs = find_func_start(rom, ro, max_back=512)
            if fs is not None:
                func_map.setdefault(0x08000000 + fs, []).append(ro)
        print(f"{len(func_map)} unique functions reference this address")
        ct_cands = []
        dt_cands = []
        for fa, rolist in func_map.items():
            fo = fa - 0x08000000
            m28 = mul = sb4 = sb7 = s0 = lb4 = m0 = sb5 = sb6 = False
            ce = min(fo + 256, len(rom) - 1)
            for pos in range(fo, ce, 2):
                ins = ru16(rom, pos)
                if ins is None: continue
                if (ins & 0xF800) == 0x2000 and (ins & 0xFF) == 0x28: m28 = True
                if (ins & 0xFFC0) == 0x4340: mul = True
                if (ins & 0xFFC0) == 0x7100: sb4 = True
                if (ins & 0xFFC0) == 0x71C0: sb7 = True
                if (ins & 0xFFC0) == 0x6000: s0 = True
                if (ins & 0xFFC0) == 0x7900: lb4 = True
                if (ins & 0xF800) == 0x2000 and (ins & 0xFF) == 0: m0 = True
                if (ins & 0xFFC0) == 0x7140: sb5 = True
                if (ins & 0xFFC0) == 0x7180: sb6 = True
            if m28 and mul and sb4 and s0 and lb4:
                score = sum([m28, mul, sb4, sb7, s0, lb4, sb5, sb6])
                ct_cands.append((fa, score, fo))
            elif m28 and mul and m0 and sb4:
                dt_cands.append((fa, fo))
        if ct_cands:
            ct_cands.sort(key=lambda x: -x[1])
            print("\nCreateTask candidates:")
            for fa, sc, fo in ct_cands[:5]:
                print(f"\n  >>> 0x{fa:08X} | THUMB: 0x{fa|1:08X} (score={sc})")
                print(disasm(rom, fo, count=50))
        if dt_cands:
            print("\nDestroyTask candidates:")
            for fa, fo in dt_cands[:3]:
                print(f"\n  >>> 0x{fa:08X} | THUMB: 0x{fa|1:08X}")
                print(disasm(rom, fo, count=40))

    # FINAL VERDICT
    print("\n" + "=" * 70)
    print("FINAL VERDICT")
    print("=" * 70)
    if sorted_near:
        b = sorted_near[0]
        tr = len(iwram_refs.get(b[0], []))
        print(f"\n  >>> gTasks (IWRAM): 0x{b[0]:08X}")
        print(f"      MUL28 hits: {len(b[1])}, Total refs: {tr}")
        print(f"      Array: 0x{b[0]:08X} - 0x{b[0]+640:08X} (640 bytes = 16 x 40)")
        if len(sorted_near) > 1:
            print(f"  Runner-up: 0x{sorted_near[1][0]:08X} ({len(sorted_near[1][1])} MUL28 hits)")
    print("\nDone.")

if __name__ == "__main__":
    main()
