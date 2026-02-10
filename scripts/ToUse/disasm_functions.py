#!/usr/bin/env python3
"""
Disassemble specific functions referenced by the target area.
Focus on:
1. 0x0806F0D4 - likely BtlController_Complete (called by almost everything)
2. 0x08004810 - called at start of 0x08071B64 function
3. 0x080C6F14 - called in 0x08071B7C function
4. 0x08003614 - called in 0x08071B7C function
5. 0x081EB1D4 - called in 0x08071B7C function
6. 0x08033F80 - called in 0x08071BD8 function
7. 0x080722A4 - called near end of 0x08071BD8 function
8. PlayerBufferExecCompleted - search for it by pattern
"""

import struct
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

KNOWN = {
    0x02023364: "gBattleTypeFlags",
    0x020233E0: "gBattleControllerExecFlags",
    0x020233DC: "gActiveBattler",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x02023A0C: "gBattleStruct_ptr",
    0x02023A40: "gBattleResources_ptr",
    0x0202356C: "gBattlerPartyIndexes",
    0x02020630: "gSprites",
    0x03005D70: "gBattlerControllerFuncs",
    0x03005D80: "gBattlerSpriteIds",
    0x03005D8C: "gBattlerControllerData?",
    0x03005E10: "gSprites_base?",
    0x030022C0: "gMain",
    0x0803816D: "BattleMainCB2",
    0x0806F0D4: "BtlController_Complete?",
    0x02037594: "gBattleSpritesDataPtr?",
    0x02023A18: "gBattleResources_or_related",
    0x03005D90: "gRngValue",
}

def disasm_short(rom, rom_offset, size, base_addr, label=""):
    """Short disassembly with literal pool decoding."""
    if label:
        print(f"\n--- {label} at 0x{base_addr:08X} (ROM 0x{rom_offset:06X}, {size} bytes) ---")

    i = 0
    while i < size:
        pc = base_addr + i
        if rom_offset + i + 1 >= len(rom):
            break
        hw = struct.unpack_from('<H', rom, rom_offset + i)[0]

        # BL pair
        if (hw >> 11) == 0x1E and i + 2 < size:
            hw2 = struct.unpack_from('<H', rom, rom_offset + i + 2)[0]
            if (hw2 >> 11) == 0x1F:
                offset_hi = hw & 0x7FF
                if offset_hi & 0x400:
                    offset_hi |= 0xFFFFF800
                offset_lo = hw2 & 0x7FF
                target = (pc + 4 + (offset_hi << 12) + (offset_lo << 1)) & 0xFFFFFFFF
                name = KNOWN.get(target | 1, KNOWN.get(target & ~1, ""))
                extra = f"  ; {name}" if name else ""
                print(f"  {pc:08X}: {hw:04X} {hw2:04X}  BL 0x{target:08X}{extra}")
                i += 4
                continue

        # LDR PC-relative
        if (hw >> 11) == 9:
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            pool_addr = ((pc + 4) & ~2) + imm8 * 4
            pool_rom = pool_addr & ~0x08000000
            if pool_rom + 3 < len(rom):
                val = struct.unpack_from('<I', rom, pool_rom)[0]
                name = KNOWN.get(val, "")
                extra = f"  ; {name}" if name else ""
                print(f"  {pc:08X}: {hw:04X}      LDR r{rd}, =0x{val:08X}{extra}")
            else:
                print(f"  {pc:08X}: {hw:04X}      LDR r{rd}, [PC, #0x{imm8*4:X}]")
            i += 2
            continue

        # PUSH/POP
        if (hw & 0xF600) == 0xB400:
            pop = (hw >> 11) & 1
            r = (hw >> 8) & 1
            rlist = hw & 0xFF
            regs = [f"r{i}" for i in range(8) if rlist & (1 << i)]
            if r:
                regs.append("pc" if pop else "lr")
            op = "POP" if pop else "PUSH"
            print(f"  {pc:08X}: {hw:04X}      {op} {{{', '.join(regs)}}}")
            i += 2
            continue

        # BX
        if (hw & 0xFF00) == 0x4700:
            rs = (hw >> 3) & 0xF
            rname = "lr" if rs == 14 else f"r{rs}"
            print(f"  {pc:08X}: {hw:04X}      BX {rname}")
            i += 2
            continue

        # Conditional branch
        if (hw >> 12) == 0xD and ((hw >> 8) & 0xF) < 0xE:
            conds = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                     "BHI","BLS","BGE","BLT","BGT","BLE"]
            cond = (hw >> 8) & 0xF
            off = hw & 0xFF
            if off & 0x80: off -= 256
            target = pc + 4 + off * 2
            print(f"  {pc:08X}: {hw:04X}      {conds[cond]} 0x{target:08X}")
            i += 2
            continue

        # Unconditional branch
        if (hw >> 11) == 0x1C:
            off = hw & 0x7FF
            if off & 0x400: off -= 2048
            target = pc + 4 + off * 2
            print(f"  {pc:08X}: {hw:04X}      B 0x{target:08X}")
            i += 2
            continue

        # MOV immediate
        if (hw >> 11) == 4:
            rd = (hw >> 8) & 0x7
            imm = hw & 0xFF
            print(f"  {pc:08X}: {hw:04X}      MOV r{rd}, #0x{imm:02X}")
            i += 2
            continue

        # CMP immediate
        if (hw >> 11) == 5:
            rd = (hw >> 8) & 0x7
            imm = hw & 0xFF
            print(f"  {pc:08X}: {hw:04X}      CMP r{rd}, #0x{imm:02X}")
            i += 2
            continue

        # ADD immediate
        if (hw >> 11) == 6:
            rd = (hw >> 8) & 0x7
            imm = hw & 0xFF
            print(f"  {pc:08X}: {hw:04X}      ADD r{rd}, #0x{imm:02X}")
            i += 2
            continue

        # STR Rd, [Rb, #imm]
        if (hw >> 13) == 3 and not ((hw >> 12) & 1):
            bl = (hw >> 11) & 1
            off = ((hw >> 6) & 0x1F) * 4
            rb = (hw >> 3) & 7
            rd = hw & 7
            op = "LDR" if bl else "STR"
            print(f"  {pc:08X}: {hw:04X}      {op} r{rd}, [r{rb}, #0x{off:X}]")
            i += 2
            continue

        # LDRB Rd, [Rb, #imm]
        if (hw >> 13) == 3 and ((hw >> 12) & 1):
            bl = (hw >> 11) & 1
            off = (hw >> 6) & 0x1F
            rb = (hw >> 3) & 7
            rd = hw & 7
            op = "LDRB" if bl else "STRB"
            print(f"  {pc:08X}: {hw:04X}      {op} r{rd}, [r{rb}, #0x{off:X}]")
            i += 2
            continue

        # TST
        if (hw >> 6) == 0x108:
            rs = (hw >> 3) & 7
            rd = hw & 7
            print(f"  {pc:08X}: {hw:04X}      TST r{rd}, r{rs}")
            i += 2
            continue

        # AND
        if (hw >> 6) == 0x100:
            rs = (hw >> 3) & 7
            rd = hw & 7
            print(f"  {pc:08X}: {hw:04X}      AND r{rd}, r{rs}")
            i += 2
            continue

        # LSL imm
        if (hw >> 11) == 0:
            off = (hw >> 6) & 0x1F
            rs = (hw >> 3) & 7
            rd = hw & 7
            print(f"  {pc:08X}: {hw:04X}      LSL r{rd}, r{rs}, #{off}")
            i += 2
            continue

        # LSR imm
        if (hw >> 11) == 1:
            off = (hw >> 6) & 0x1F
            rs = (hw >> 3) & 7
            rd = hw & 7
            print(f"  {pc:08X}: {hw:04X}      LSR r{rd}, r{rs}, #{off}")
            i += 2
            continue

        # ADD reg
        if (hw >> 9) == 0x18:
            rn = (hw >> 6) & 7
            rs = (hw >> 3) & 7
            rd = hw & 7
            print(f"  {pc:08X}: {hw:04X}      ADD r{rd}, r{rs}, r{rn}")
            i += 2
            continue

        # ADD low reg (format 2, imm3)
        if (hw >> 9) == 0x1C:
            imm3 = (hw >> 6) & 7
            rs = (hw >> 3) & 7
            rd = hw & 7
            print(f"  {pc:08X}: {hw:04X}      ADD r{rd}, r{rs}, #{imm3}")
            i += 2
            continue

        # SUB SP
        if (hw & 0xFF80) == 0xB080:
            imm = (hw & 0x7F) * 4
            print(f"  {pc:08X}: {hw:04X}      SUB SP, #0x{imm:X}")
            i += 2
            continue

        # ADD SP
        if (hw & 0xFF80) == 0xB000:
            imm = (hw & 0x7F) * 4
            print(f"  {pc:08X}: {hw:04X}      ADD SP, #0x{imm:X}")
            i += 2
            continue

        # High register MOV
        if (hw & 0xFF00) == 0x4600:
            h1 = (hw >> 7) & 1
            h2 = (hw >> 6) & 1
            rs = ((hw >> 3) & 7) | (h2 << 3)
            rd = (hw & 7) | (h1 << 3)
            print(f"  {pc:08X}: {hw:04X}      MOV r{rd}, r{rs}")
            i += 2
            continue

        # LDRH
        if (hw >> 12) == 8:
            bl = (hw >> 11) & 1
            off = ((hw >> 6) & 0x1F) * 2
            rb = (hw >> 3) & 7
            rd = hw & 7
            op = "LDRH" if bl else "STRH"
            print(f"  {pc:08X}: {hw:04X}      {op} r{rd}, [r{rb}, #0x{off:X}]")
            i += 2
            continue

        print(f"  {pc:08X}: {hw:04X}      ??? (raw)")
        i += 2


def main():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()

    # 1. BtlController_Complete candidate at 0x0806F0D4
    print("="*80)
    print("FUNCTION 1: 0x0806F0D4 (BtlController_Complete candidate)")
    print("Called by nearly every function in the battle controller area")
    print("="*80)
    disasm_short(rom, 0x6F0D4, 64, 0x0806F0D4)

    # 2. Function at 0x08004810
    print("\n" + "="*80)
    print("FUNCTION 2: 0x08004810 (called at start of 0x08071B64)")
    print("="*80)
    disasm_short(rom, 0x4810, 64, 0x08004810)

    # 3. 0x080C6F14
    print("\n" + "="*80)
    print("FUNCTION 3: 0x080C6F14 (called from 0x08071BAC)")
    print("="*80)
    disasm_short(rom, 0xC6F14, 64, 0x080C6F14)

    # 4. 0x08003614
    print("\n" + "="*80)
    print("FUNCTION 4: 0x08003614 (called from 0x08071BB0)")
    print("="*80)
    disasm_short(rom, 0x3614, 64, 0x08003614)

    # 5. 0x081EB1D4
    print("\n" + "="*80)
    print("FUNCTION 5: 0x081EB1D4 (called from 0x08071BB6)")
    print("="*80)
    disasm_short(rom, 0x1EB1D4, 64, 0x081EB1D4)

    # 6. 0x08033F80
    print("\n" + "="*80)
    print("FUNCTION 6: 0x08033F80 (called from 0x08071C00)")
    print("="*80)
    disasm_short(rom, 0x33F80, 128, 0x08033F80)

    # 7. 0x080722A4
    print("\n" + "="*80)
    print("FUNCTION 7: 0x080722A4 (called from 0x08071C42)")
    print("="*80)
    disasm_short(rom, 0x722A4, 64, 0x080722A4)

    # Now search for PlayerBufferExecCompleted pattern:
    # It should:
    # - Load gBattlerControllerFuncs (0x03005D70)
    # - Load gBattleTypeFlags (0x02023364)
    # - Test bit 1 (TST with #2 or AND with #2)
    # - Branch to link path or local path
    print("\n" + "="*80)
    print("SEARCH: PlayerBufferExecCompleted pattern")
    print("Looking for functions that load BOTH gBattlerControllerFuncs AND gBattleTypeFlags")
    print("="*80)

    # Find all literal pool entries for gBattleTypeFlags
    btf_locs = []
    for off in range(0, len(rom) - 3, 4):
        val = struct.unpack_from('<I', rom, off)[0]
        if val == 0x02023364:
            btf_locs.append(off)

    print(f"\nFound {len(btf_locs)} literal pool entries for gBattleTypeFlags (0x02023364)")

    # For each, find nearby references to gBattlerControllerFuncs
    for btf_off in btf_locs:
        btf_addr = 0x08000000 + btf_off
        # Check LDR instructions that reference this pool entry (within 1KB before)
        for check_off in range(max(0, btf_off - 1020), btf_off, 2):
            hw = struct.unpack_from('<H', rom, check_off)[0]
            if (hw >> 11) == 9:  # LDR Rd, [PC, #imm]
                pc = 0x08000000 + check_off
                imm8 = hw & 0xFF
                ref_addr = ((pc + 4) & ~2) + imm8 * 4
                if ref_addr == btf_addr:
                    # Now check if nearby (within 64 bytes) there's also gBattlerControllerFuncs
                    func_start = check_off
                    # Look backward for PUSH
                    for back in range(check_off, max(0, check_off - 64), -2):
                        hw_b = struct.unpack_from('<H', rom, back)[0]
                        if (hw_b & 0xFE00) == 0xB400:  # PUSH
                            func_start = back
                            break

                    # Check if gBattlerControllerFuncs (0x03005D70) is in nearby literal pool
                    for pool_check in range(func_start, min(len(rom) - 3, func_start + 256), 4):
                        val2 = struct.unpack_from('<I', rom, pool_check)[0]
                        if val2 == 0x03005D70:
                            func_addr = 0x08000000 + func_start
                            print(f"\n  CANDIDATE at 0x{func_addr:08X} (ROM 0x{func_start:06X})")
                            print(f"    gBattleTypeFlags pool at 0x{btf_addr:08X}")
                            print(f"    gBattlerControllerFuncs pool at 0x{0x08000000 + pool_check:08X}")
                            # Disassemble
                            disasm_short(rom, func_start, 96, func_addr, "Candidate function")
                            break

    # Also: search for the exact sequence that looks like PlayerBufferExecCompleted
    # It does: gBattlerControllerFuncs[battler] = PlayerBufferRunCommand
    # then checks gBattleTypeFlags & BATTLE_TYPE_LINK
    print("\n" + "="*80)
    print("SEARCH: Functions that check gBattleTypeFlags and call PrepareBufferDataTransferLink")
    print("Looking for TST/AND with #0x02 near gBattleTypeFlags loads")
    print("="*80)

    for btf_off in btf_locs:
        btf_addr = 0x08000000 + btf_off
        for check_off in range(max(0, btf_off - 1020), btf_off, 2):
            hw = struct.unpack_from('<H', rom, check_off)[0]
            if (hw >> 11) == 9:
                pc = 0x08000000 + check_off
                imm8 = hw & 0xFF
                ref_addr = ((pc + 4) & ~2) + imm8 * 4
                if ref_addr == btf_addr:
                    # Check next few instructions for TST/AND with #2 or LDR + TST
                    for delta in range(2, 20, 2):
                        if check_off + delta + 1 < len(rom):
                            hw_next = struct.unpack_from('<H', rom, check_off + delta)[0]
                            # MOV Rx, #2 then TST
                            # Or direct TST with register that has #2
                            # Common pattern: LDR r0, =gBTF; LDR r0, [r0]; MOV r1, #2; AND r0, r1
                            if hw_next == 0x2102 or hw_next == 0x2002:  # MOV r1, #2 or MOV r0, #2
                                func_start = check_off
                                for back in range(check_off, max(0, check_off - 64), -2):
                                    hw_b = struct.unpack_from('<H', rom, back)[0]
                                    if (hw_b & 0xFE00) == 0xB400:
                                        func_start = back
                                        break
                                func_addr = 0x08000000 + func_start
                                print(f"\n  FOUND: TST pattern at 0x{pc + delta:08X} near gBattleTypeFlags ref at 0x{pc:08X}")
                                print(f"    Function starts around 0x{func_addr:08X}")
                                disasm_short(rom, func_start, 128, func_addr, "Pattern match")
                                break


if __name__ == '__main__':
    main()
