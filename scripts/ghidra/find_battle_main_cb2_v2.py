#!/usr/bin/env python3
"""
Find BattleMainCB2 v2 - Follow the jump table state 18 analysis.

From v1 results:
  State 18 handler at 0x08037130
  It loads 0x0803816D into R0, then BL 0x08000544 (= SetMainCallback2)
  So BattleMainCB2 = 0x0803816D (THUMB address, function at 0x0803816C)

  Also loads 0x08039C65 — likely BattleMainCB2 or another CB.

Let's disassemble both candidates and also examine the SetMainCallback2 call to confirm.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known function addresses
KNOWN_FUNCS = {
    0x080069D0: "AnimateSprites",
    0x08006A1C: "BuildOamBuffer",
    0x080C6F84: "RunTextPrinters",
    0x080BF858: "UpdatePaletteFade",
    0x08004788: "RunTasks",
    0x08000544: "SetMainCallback2",
    0x08076964: "BattleInitAllSprites? (needs verify)",
}

def read_rom(path):
    with open(path, "rb") as f:
        return f.read()

def decode_thumb_bl(hw1, hw2):
    if (hw1 & 0xF800) not in (0xF000, 0xF400):
        return None
    if (hw2 & 0xF800) != 0xF800:
        return None
    s = (hw1 >> 10) & 1
    imm10 = hw1 & 0x3FF
    imm11 = hw2 & 0x7FF
    offset = (s << 22) | (imm10 << 12) | (imm11 << 1)
    if s:
        offset |= 0xFF800000
        offset = offset - 0x100000000
    return offset

def disassemble_thumb(rom, addr, num_bytes=64, known=None):
    """Disassemble THUMB code at given address."""
    if known is None:
        known = KNOWN_FUNCS

    rom_off = (addr & 0x01FFFFFF)
    lines = []
    i = 0
    while i < num_bytes:
        pos = rom_off + i
        if pos + 2 > len(rom):
            break
        hw = struct.unpack_from("<H", rom, pos)[0]
        cur_addr = 0x08000000 + pos

        # Check for BL pair
        if (hw & 0xF800) in (0xF000, 0xF400) and pos + 4 <= len(rom):
            hw2 = struct.unpack_from("<H", rom, pos + 2)[0]
            if (hw2 & 0xF800) == 0xF800:
                bl_off = decode_thumb_bl(hw, hw2)
                if bl_off is not None:
                    pc = cur_addr + 4
                    target = pc + bl_off
                    target_clean = target & 0xFFFFFFFE
                    name = known.get(target_clean, known.get(target, ""))
                    if name:
                        name = f" = {name}"
                    lines.append(f"  0x{cur_addr:08X}: BL 0x{target:08X}{name}")
                    i += 4
                    continue

        # PUSH
        if (hw & 0xFE00) == 0xB400:
            regs = [f"R{b}" for b in range(8) if hw & (1 << b)]
            if hw & 0x100:
                regs.append("LR")
            lines.append(f"  0x{cur_addr:08X}: PUSH {{{', '.join(regs)}}}")
        # POP
        elif (hw & 0xFE00) == 0xBC00:
            regs = [f"R{b}" for b in range(8) if hw & (1 << b)]
            if hw & 0x100:
                regs.append("PC")
            lines.append(f"  0x{cur_addr:08X}: POP {{{', '.join(regs)}}}")
        # BX LR
        elif hw == 0x4770:
            lines.append(f"  0x{cur_addr:08X}: BX LR")
        # BX Rm
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            lines.append(f"  0x{cur_addr:08X}: BX R{rm}")
        # MOV Rd, #imm8
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{cur_addr:08X}: MOV R{rd}, #0x{imm:02X} ({imm})")
        # LDR Rd, [PC, #imm]
        elif (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc_aligned = (cur_addr + 4) & 0xFFFFFFFC
            pool_addr = pc_aligned + imm
            pool_rom = pool_addr - 0x08000000
            if 0 <= pool_rom and pool_rom + 4 <= len(rom):
                val = struct.unpack_from("<I", rom, pool_rom)[0]
                val_name = known.get(val & 0xFFFFFFFE, known.get(val, ""))
                if val_name:
                    val_name = f" = {val_name}"
                lines.append(f"  0x{cur_addr:08X}: LDR R{rd}, [PC, #0x{imm:X}] ; =0x{val:08X}{val_name}")
            else:
                lines.append(f"  0x{cur_addr:08X}: LDR R{rd}, [PC, #0x{imm:X}]")
        # ADD Rd, PC, #imm
        elif (hw & 0xF800) == 0xA000:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            lines.append(f"  0x{cur_addr:08X}: ADD R{rd}, PC, #0x{imm:X}")
        # STR/LDR with register offset or immediate
        elif (hw & 0xF800) == 0x6000:  # STR Rt, [Rn, #imm]
            imm = ((hw >> 6) & 0x1F) * 4
            rn = (hw >> 3) & 7
            rt = hw & 7
            lines.append(f"  0x{cur_addr:08X}: STR R{rt}, [R{rn}, #0x{imm:X}]")
        elif (hw & 0xF800) == 0x6800:  # LDR Rt, [Rn, #imm]
            imm = ((hw >> 6) & 0x1F) * 4
            rn = (hw >> 3) & 7
            rt = hw & 7
            lines.append(f"  0x{cur_addr:08X}: LDR R{rt}, [R{rn}, #0x{imm:X}]")
        # CMP Rn, #imm8
        elif (hw & 0xF800) == 0x2800:
            rn = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{cur_addr:08X}: CMP R{rn}, #0x{imm:02X} ({imm})")
        # Conditional branches
        elif (hw & 0xF000) == 0xD000:
            cond = (hw >> 8) & 0xF
            cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                          "BHI","BLS","BGE","BLT","BGT","BLE","B(AL)","SVC"]
            soff = hw & 0xFF
            if soff & 0x80:
                soff = soff - 256
            target = cur_addr + 4 + soff * 2
            lines.append(f"  0x{cur_addr:08X}: {cond_names[cond]} 0x{target:08X}")
        # Unconditional branch B
        elif (hw & 0xF800) == 0xE000:
            soff = hw & 0x7FF
            if soff & 0x400:
                soff = soff - 0x800
            target = cur_addr + 4 + soff * 2
            lines.append(f"  0x{cur_addr:08X}: B 0x{target:08X}")
        # LSL/LSR/ASR/ADD/SUB with imm
        elif (hw & 0xE000) == 0x0000:
            op = (hw >> 11) & 3
            imm5 = (hw >> 6) & 0x1F
            rs = (hw >> 3) & 7
            rd = hw & 7
            ops = ["LSL", "LSR", "ASR", "---"]
            lines.append(f"  0x{cur_addr:08X}: {ops[op]} R{rd}, R{rs}, #{imm5}")
        # ADD/SUB register/imm3
        elif (hw & 0xF800) == 0x1800:
            rm_imm = (hw >> 6) & 7
            rs = (hw >> 3) & 7
            rd = hw & 7
            if hw & 0x0400:  # immediate
                lines.append(f"  0x{cur_addr:08X}: ADD R{rd}, R{rs}, #{rm_imm}")
            else:
                lines.append(f"  0x{cur_addr:08X}: ADD R{rd}, R{rs}, R{rm_imm}")
        elif (hw & 0xF800) == 0x1A00:
            rm_imm = (hw >> 6) & 7
            rs = (hw >> 3) & 7
            rd = hw & 7
            if hw & 0x0400:
                lines.append(f"  0x{cur_addr:08X}: SUB R{rd}, R{rs}, #{rm_imm}")
            else:
                lines.append(f"  0x{cur_addr:08X}: SUB R{rd}, R{rs}, R{rm_imm}")
        # ADD Rd, #imm8
        elif (hw & 0xF800) == 0x3000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{cur_addr:08X}: ADD R{rd}, #0x{imm:02X} ({imm})")
        # SUB Rd, #imm8
        elif (hw & 0xF800) == 0x3800:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{cur_addr:08X}: SUB R{rd}, #0x{imm:02X} ({imm})")
        # TST, AND, ORR, etc (ALU ops)
        elif (hw & 0xFC00) == 0x4000:
            op = (hw >> 6) & 0xF
            rs = (hw >> 3) & 7
            rd = hw & 7
            alu_ops = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                       "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            lines.append(f"  0x{cur_addr:08X}: {alu_ops[op]} R{rd}, R{rs}")
        else:
            lines.append(f"  0x{cur_addr:08X}: 0x{hw:04X}")

        i += 2

        # Stop at POP {PC} or BX LR
        if hw == 0x4770 or (hw & 0xFE00) == 0xBC00 and (hw & 0x100):
            break

    return lines

def find_literal_pool_refs(rom, target_val):
    """Find all places where target_val appears in ROM as a literal pool value."""
    results = []
    for off in range(0, len(rom) - 4, 4):
        val = struct.unpack_from("<I", rom, off)[0]
        if val == target_val:
            results.append(0x08000000 + off)
    return results

def main():
    rom = read_rom(ROM_PATH)
    print(f"ROM: {len(rom):,} bytes")

    print("\n" + "=" * 70)
    print("STATE 18 HANDLER (0x08037130) - Full Disassembly")
    print("=" * 70)
    lines = disassemble_thumb(rom, 0x08037130, 128)
    for l in lines:
        print(l)

    # Key findings from state 18:
    # 0x08037146: LDR R0, [PC, ...] ; =0x08039C65
    # This is stored to [R1] where R1=0x030022C0 — that's gMain+0x08 = savedCallback
    # 0x0803714A: LDR R0, [PC, ...] ; =0x0803816D
    # Then BL 0x08000544 = SetMainCallback2
    # So BattleMainCB2 = 0x0803816C (THUMB addr 0x0803816D)

    candidates = [0x0803816C, 0x08039C64]

    for addr in candidates:
        thumb = addr | 1
        print(f"\n{'=' * 70}")
        print(f"CANDIDATE: 0x{addr:08X} (THUMB: 0x{thumb:08X})")
        print(f"{'=' * 70}")

        lines = disassemble_thumb(rom, addr, 80)
        for l in lines:
            print(l)

        # Check if this calls our 5 target functions
        rom_off = addr & 0x01FFFFFF
        bl_calls = []
        for i in range(0, 80, 2):
            pos = rom_off + i
            if pos + 4 > len(rom):
                break
            hw1 = struct.unpack_from("<H", rom, pos)[0]
            hw2 = struct.unpack_from("<H", rom, pos + 2)[0]
            bl_off = decode_thumb_bl(hw1, hw2)
            if bl_off is not None:
                pc = 0x08000000 + pos + 4
                target = pc + bl_off
                target_clean = target & 0xFFFFFFFE
                name = KNOWN_FUNCS.get(target_clean, KNOWN_FUNCS.get(target, f"0x{target:08X}"))
                bl_calls.append((0x08000000 + pos, target, name))

        if bl_calls:
            print(f"\n  BL calls found ({len(bl_calls)}):")
            for bl_addr, bl_target, bl_name in bl_calls:
                print(f"    0x{bl_addr:08X}: BL 0x{bl_target:08X} ({bl_name})")

    # Now look at SetMainCallback2 to confirm
    print(f"\n{'=' * 70}")
    print("SetMainCallback2 (0x08000544) - Disassembly")
    print(f"{'=' * 70}")
    lines = disassemble_thumb(rom, 0x08000544, 32)
    for l in lines:
        print(l)

    # Also check what's at 0x08039C64 - is it BattleMainCB2 or something else?
    # And 0x0803816C - disassemble more carefully

    # Let's also look for PUSH{LR} + BL patterns that might be BattleMainCB2
    # with different function order or additional calls
    print(f"\n{'=' * 70}")
    print("EXTENDED SCAN: Functions calling all 5 targets (any order)")
    print(f"{'=' * 70}")

    TARGETS = {
        0x080069D0: "AnimateSprites",
        0x08006A1C: "BuildOamBuffer",
        0x080C6F84: "RunTextPrinters",
        0x080BF858: "UpdatePaletteFade",
        0x08004788: "RunTasks",
    }

    # Scan every PUSH{LR} and check next ~60 bytes for BL to all 5 targets
    rom_size = len(rom)
    found = []
    for offset in range(0, rom_size - 2, 2):
        hw = struct.unpack_from("<H", rom, offset)[0]
        # PUSH {LR} or PUSH {regs, LR}
        if (hw & 0xFF00) != 0xB500 and (hw & 0xFF00) != 0xB400:
            continue
        if not (hw & 0x100):  # Must include LR
            continue

        # Scan next 80 bytes for BL instructions
        targets_found = set()
        for i in range(2, 80, 2):
            pos = offset + i
            if pos + 4 > rom_size:
                break
            hw1 = struct.unpack_from("<H", rom, pos)[0]
            hw2 = struct.unpack_from("<H", rom, pos + 2)[0]

            # Check for POP {PC} - end of function
            if (hw1 & 0xFE00) == 0xBC00 and (hw1 & 0x100):
                break

            bl_off = decode_thumb_bl(hw1, hw2)
            if bl_off is not None:
                pc = 0x08000000 + pos + 4
                target = (pc + bl_off) & 0xFFFFFFFE
                if target in TARGETS:
                    targets_found.add(target)

        if len(targets_found) == 5:
            func_addr = 0x08000000 + offset
            found.append(func_addr)

    print(f"\n  Functions calling ALL 5 targets: {len(found)}")
    for addr in found:
        print(f"\n    0x{addr:08X}:")
        lines = disassemble_thumb(rom, addr, 60)
        for l in lines:
            print(f"    {l}")

    # Summary
    print(f"\n{'=' * 70}")
    print("FINAL ANALYSIS")
    print(f"{'=' * 70}")
    print(f"""
From State 18 (0x08037130) of CB2_InitBattleInternal:
  - 0x08039C65 is stored to gMain.savedCallback (0x030022C0+0x08 area)
  - 0x0803816D is passed to SetMainCallback2 (0x08000544)

So: SetMainCallback2(0x0803816C) is called = this sets callback2 = BattleMainCB2

BattleMainCB2 = 0x0803816C (THUMB: 0x0803816D)
""")

if __name__ == "__main__":
    main()
