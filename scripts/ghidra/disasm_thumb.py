#!/usr/bin/env python3
"""
THUMB disassembler for GBA ROM analysis.
Decodes THUMB instructions from a GBA ROM file at specified addresses.
Focuses on BL calls, LDR literal pool loads, branches, and function structure.
"""

import struct
import sys

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses for cross-referencing
KNOWN_ADDRS = {
    0x08000544: "SetMainCallback2",
    0x08000578: "SetVBlankCallback",
    0x080363C1: "CB2_InitBattle",
    0x08036D01: "cb2_during_comm_processing",
    0x08037B45: "CB2_HandleStartBattle",
    0x0803816D: "stuck_callback2",
    0x08094815: "BattleMainCB2",
    0x0806F1D9: "SetUpBattleVars",
    0x0806F0D5: "PlayerBufferExecCompleted",
    0x08078789: "LinkOpponentBufferExecCompleted",
    0x08032FA9: "PrepareBufferDataTransferLink",
    0x0800A4B1: "GetMultiplayerId",
}

# THUMB condition codes
COND_CODES = {
    0: "EQ", 1: "NE", 2: "CS/HS", 3: "CC/LO",
    4: "MI", 5: "PL", 6: "VS", 7: "VC",
    8: "HI", 9: "LS", 10: "GE", 11: "LT",
    12: "GT", 13: "LE", 14: "AL", 15: "NV"
}

REG_NAMES = ["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7",
             "R8", "R9", "R10", "R11", "R12", "SP", "LR", "PC"]


def read_rom(path):
    with open(path, "rb") as f:
        return f.read()


def u16(rom, offset):
    return struct.unpack_from("<H", rom, offset)[0]


def u32(rom, offset):
    return struct.unpack_from("<I", rom, offset)[0]


def s32(val):
    if val >= 0x80000000:
        return val - 0x100000000
    return val


def reglist_str(mask, include_lr=False, include_pc=False):
    regs = []
    for i in range(8):
        if mask & (1 << i):
            regs.append(REG_NAMES[i])
    if include_lr:
        regs.append("LR")
    if include_pc:
        regs.append("PC")
    return "{" + ", ".join(regs) + "}"


def lookup_addr(addr):
    """Look up known address name."""
    # Check with and without THUMB bit
    for a in [addr, addr | 1, addr & ~1]:
        if a in KNOWN_ADDRS:
            return KNOWN_ADDRS[a]
    return None


def disasm_thumb_region(rom, rom_addr, size, label=""):
    """
    Disassemble a region of THUMB code.
    rom_addr: the GBA address (0x08xxxxxx), must be even (THUMB bit stripped)
    size: number of bytes to read
    """
    cart0_offset = (rom_addr & ~1) - 0x08000000
    print(f"\n{'='*80}")
    print(f"  Disassembly: 0x{rom_addr:08X} (cart0: 0x{cart0_offset:06X})")
    if label:
        print(f"  Label: {label}")
    print(f"  Size: {size} bytes ({size//2} halfwords)")
    print(f"{'='*80}\n")

    bl_targets = []
    ldr_pool_loads = []
    branches = []

    pc = rom_addr & ~1  # Ensure even
    end = pc + size
    i = 0

    while pc < end and cart0_offset + i < len(rom):
        hw = u16(rom, cart0_offset + i)
        addr_str = f"0x{pc:08X}"
        hex_str = f"{hw:04X}"
        comment = ""
        instr = ""

        # ---- BL/BLX (32-bit: two halfwords) ----
        if (hw >> 11) == 0x1E:  # F000-F7FF: BL prefix (upper)
            if cart0_offset + i + 2 < len(rom):
                hw2 = u16(rom, cart0_offset + i + 2)
                if (hw2 >> 11) == 0x1F:  # F800-FFFF: BL suffix
                    offset_hi = hw & 0x7FF
                    offset_lo = hw2 & 0x7FF
                    # Sign extend the upper 11 bits
                    if offset_hi & 0x400:
                        offset_hi |= 0xFFFFF800
                        offset_hi = offset_hi - 0x100000000 if offset_hi > 0x7FFFFFFF else offset_hi
                    target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
                    target &= 0xFFFFFFFF
                    name = lookup_addr(target)
                    name_str = f"  ; {name}" if name else ""
                    instr = f"BL      0x{target:08X}{name_str}"
                    hex_str = f"{hw:04X} {hw2:04X}"
                    bl_targets.append((pc, target, name))
                    print(f"  {addr_str}:  {hex_str:12s}  {instr}")
                    pc += 4
                    i += 4
                    continue
                elif (hw2 >> 11) == 0x1D:  # BLX suffix (to ARM)
                    offset_hi = hw & 0x7FF
                    offset_lo = hw2 & 0x7FF
                    if offset_hi & 0x400:
                        offset_hi |= 0xFFFFF800
                        offset_hi = offset_hi - 0x100000000 if offset_hi > 0x7FFFFFFF else offset_hi
                    target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
                    target &= 0xFFFFFFFC  # ARM align
                    name = lookup_addr(target)
                    name_str = f"  ; {name}" if name else ""
                    instr = f"BLX     0x{target:08X}{name_str}"
                    hex_str = f"{hw:04X} {hw2:04X}"
                    bl_targets.append((pc, target, name))
                    print(f"  {addr_str}:  {hex_str:12s}  {instr}")
                    pc += 4
                    i += 4
                    continue

        # ---- PUSH ----
        if (hw >> 8) == 0xB4:
            mask = hw & 0xFF
            instr = f"PUSH    {reglist_str(mask)}"
        elif (hw >> 8) == 0xB5:
            mask = hw & 0xFF
            instr = f"PUSH    {reglist_str(mask, include_lr=True)}"

        # ---- POP ----
        elif (hw >> 8) == 0xBC:
            mask = hw & 0xFF
            instr = f"POP     {reglist_str(mask)}"
        elif (hw >> 8) == 0xBD:
            mask = hw & 0xFF
            instr = f"POP     {reglist_str(mask, include_pc=True)}"
            comment = " ; FUNCTION RETURN"

        # ---- BX ----
        elif (hw >> 7) == 0x8E:  # 0x4700 range: BX
            rm = (hw >> 3) & 0xF
            instr = f"BX      {REG_NAMES[rm]}"
            if rm == 14:
                comment = " ; RETURN (BX LR)"

        # ---- BLX register ----
        elif (hw >> 7) == 0x8F:  # 0x4780: BLX Rm
            rm = (hw >> 3) & 0xF
            instr = f"BLX     {REG_NAMES[rm]}"

        # ---- LDR Rd,[PC,#imm] (literal pool) ----
        elif (hw >> 11) == 0x09:  # 0x48xx
            rd = (hw >> 8) & 0x7
            imm = (hw & 0xFF) * 4
            # PC is current + 4, aligned to 4
            load_addr = ((pc + 4) & ~3) + imm
            load_offset = (load_addr & 0x0FFFFFFF)
            if load_offset < len(rom):
                val = u32(rom, load_offset)
                name = lookup_addr(val)
                name_str = f"  ; ={name}" if name else ""
                instr = f"LDR     {REG_NAMES[rd]}, [PC, #0x{imm:X}]  ; [0x{load_addr:08X}] = 0x{val:08X}{name_str}"
                ldr_pool_loads.append((pc, rd, load_addr, val, name))
            else:
                instr = f"LDR     {REG_NAMES[rd]}, [PC, #0x{imm:X}]  ; addr=0x{load_addr:08X} (out of range)"

        # ---- LDR Rd,[Rn,#imm] ----
        elif (hw >> 11) == 0x0D:  # 0x68xx
            imm = ((hw >> 6) & 0x1F) * 4
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"LDR     {REG_NAMES[rd]}, [{REG_NAMES[rn]}, #0x{imm:X}]"

        # ---- LDRB Rd,[Rn,#imm] ----
        elif (hw >> 11) == 0x0F:  # 0x78xx
            imm = (hw >> 6) & 0x1F
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"LDRB    {REG_NAMES[rd]}, [{REG_NAMES[rn]}, #0x{imm:X}]"

        # ---- LDRH Rd,[Rn,#imm] ----
        elif (hw >> 11) == 0x11:  # 0x88xx
            imm = ((hw >> 6) & 0x1F) * 2
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"LDRH    {REG_NAMES[rd]}, [{REG_NAMES[rn]}, #0x{imm:X}]"

        # ---- STR Rd,[Rn,#imm] ----
        elif (hw >> 11) == 0x0C:  # 0x60xx
            imm = ((hw >> 6) & 0x1F) * 4
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"STR     {REG_NAMES[rd]}, [{REG_NAMES[rn]}, #0x{imm:X}]"

        # ---- STRB Rd,[Rn,#imm] ----
        elif (hw >> 11) == 0x0E:  # 0x70xx
            imm = (hw >> 6) & 0x1F
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"STRB    {REG_NAMES[rd]}, [{REG_NAMES[rn]}, #0x{imm:X}]"

        # ---- STRH Rd,[Rn,#imm] ----
        elif (hw >> 11) == 0x10:  # 0x80xx
            imm = ((hw >> 6) & 0x1F) * 2
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"STRH    {REG_NAMES[rd]}, [{REG_NAMES[rn]}, #0x{imm:X}]"

        # ---- MOV Rd,#imm ----
        elif (hw >> 11) == 0x04:  # 0x20xx
            rd = (hw >> 8) & 0x7
            imm = hw & 0xFF
            instr = f"MOV     {REG_NAMES[rd]}, #0x{imm:X}"

        # ---- CMP Rn,#imm ----
        elif (hw >> 11) == 0x05:  # 0x28xx
            rn = (hw >> 8) & 0x7
            imm = hw & 0xFF
            instr = f"CMP     {REG_NAMES[rn]}, #0x{imm:X}"

        # ---- ADD Rd,#imm ----
        elif (hw >> 11) == 0x06:  # 0x30xx
            rd = (hw >> 8) & 0x7
            imm = hw & 0xFF
            instr = f"ADD     {REG_NAMES[rd]}, #0x{imm:X}"

        # ---- SUB Rd,#imm ----
        elif (hw >> 11) == 0x07:  # 0x38xx
            rd = (hw >> 8) & 0x7
            imm = hw & 0xFF
            instr = f"SUB     {REG_NAMES[rd]}, #0x{imm:X}"

        # ---- ADD SP,#imm ----
        elif (hw >> 7) == 0x160:  # 0xB0xx, bit7=0 → ADD SP
            imm = (hw & 0x7F) * 4
            instr = f"ADD     SP, #0x{imm:X}"

        # ---- SUB SP,#imm ----
        elif (hw >> 7) == 0x161:  # 0xB0xx, bit7=1 → SUB SP
            imm = (hw & 0x7F) * 4
            instr = f"SUB     SP, #0x{imm:X}"

        # ---- Conditional branch B<cond> ----
        elif (hw >> 12) == 0xD:
            cond = (hw >> 8) & 0xF
            if cond < 14:  # Not SWI
                offset = hw & 0xFF
                if offset & 0x80:
                    offset = offset - 0x100
                target = pc + 4 + offset * 2
                cond_str = COND_CODES.get(cond, "??")
                instr = f"B{cond_str:6s} 0x{target & 0xFFFFFFFF:08X}"
                branches.append((pc, target & 0xFFFFFFFF, cond_str))
            elif cond == 14:
                instr = f"UDF     #{hw & 0xFF}"
            elif cond == 15:
                instr = f"SWI     #0x{hw & 0xFF:X}"

        # ---- Unconditional branch B ----
        elif (hw >> 11) == 0x1C:  # 0xE000-E7FF
            offset = hw & 0x7FF
            if offset & 0x400:
                offset = offset - 0x800
            target = pc + 4 + offset * 2
            instr = f"B       0x{target & 0xFFFFFFFF:08X}"
            branches.append((pc, target & 0xFFFFFFFF, "AL"))

        # ---- ADD Rd,Rn,Rm (format 2) ----
        elif (hw >> 9) == 0x0C:  # 0x18xx
            rm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"ADD     {REG_NAMES[rd]}, {REG_NAMES[rn]}, {REG_NAMES[rm]}"

        # ---- SUB Rd,Rn,Rm (format 2) ----
        elif (hw >> 9) == 0x0D:  # 0x1Axx
            rm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"SUB     {REG_NAMES[rd]}, {REG_NAMES[rn]}, {REG_NAMES[rm]}"

        # ---- ADD Rd,Rn,#imm3 ----
        elif (hw >> 9) == 0x0E:  # 0x1Cxx
            imm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"ADD     {REG_NAMES[rd]}, {REG_NAMES[rn]}, #0x{imm:X}"

        # ---- SUB Rd,Rn,#imm3 ----
        elif (hw >> 9) == 0x0F:  # 0x1Exx
            imm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"SUB     {REG_NAMES[rd]}, {REG_NAMES[rn]}, #0x{imm:X}"

        # ---- LSL Rd,Rm,#imm ----
        elif (hw >> 11) == 0x00:  # 0x00xx
            imm = (hw >> 6) & 0x1F
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            if imm == 0 and rm == rd and rd == 0:
                instr = f"NOP     ; (MOV R0, R0)"
            else:
                instr = f"LSL     {REG_NAMES[rd]}, {REG_NAMES[rm]}, #{imm}"

        # ---- LSR Rd,Rm,#imm ----
        elif (hw >> 11) == 0x01:  # 0x08xx
            imm = (hw >> 6) & 0x1F
            if imm == 0: imm = 32
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"LSR     {REG_NAMES[rd]}, {REG_NAMES[rm]}, #{imm}"

        # ---- ASR Rd,Rm,#imm ----
        elif (hw >> 11) == 0x02:  # 0x10xx
            imm = (hw >> 6) & 0x1F
            if imm == 0: imm = 32
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"ASR     {REG_NAMES[rd]}, {REG_NAMES[rm]}, #{imm}"

        # ---- ALU operations (format 4) ----
        elif (hw >> 10) == 0x10:  # 0x40xx
            op = (hw >> 6) & 0xF
            rs = (hw >> 3) & 0x7
            rd = hw & 0x7
            alu_ops = ["AND", "EOR", "LSL", "LSR", "ASR", "ADC", "SBC", "ROR",
                       "TST", "NEG", "CMP", "CMN", "ORR", "MUL", "BIC", "MVN"]
            instr = f"{alu_ops[op]:7s} {REG_NAMES[rd]}, {REG_NAMES[rs]}"

        # ---- Hi register operations / BX ----
        elif (hw >> 10) == 0x11:  # 0x44xx-0x47xx
            op = (hw >> 8) & 3
            h1 = (hw >> 7) & 1
            h2 = (hw >> 6) & 1
            rs = ((h2 << 3) | ((hw >> 3) & 7))
            rd = ((h1 << 3) | (hw & 7))
            if op == 0:
                instr = f"ADD     {REG_NAMES[rd]}, {REG_NAMES[rs]}"
            elif op == 1:
                instr = f"CMP     {REG_NAMES[rd]}, {REG_NAMES[rs]}"
            elif op == 2:
                instr = f"MOV     {REG_NAMES[rd]}, {REG_NAMES[rs]}"
            elif op == 3:
                if h1:
                    instr = f"BLX     {REG_NAMES[rs]}"
                else:
                    instr = f"BX      {REG_NAMES[rs]}"
                    if rs == 14:
                        comment = " ; RETURN (BX LR)"

        # ---- LDR Rd,[SP,#imm] ----
        elif (hw >> 11) == 0x13:  # 0x98xx
            rd = (hw >> 8) & 0x7
            imm = (hw & 0xFF) * 4
            instr = f"LDR     {REG_NAMES[rd]}, [SP, #0x{imm:X}]"

        # ---- STR Rd,[SP,#imm] ----
        elif (hw >> 11) == 0x12:  # 0x90xx
            rd = (hw >> 8) & 0x7
            imm = (hw & 0xFF) * 4
            instr = f"STR     {REG_NAMES[rd]}, [SP, #0x{imm:X}]"

        # ---- ADD Rd,PC,#imm ----
        elif (hw >> 11) == 0x14:  # 0xA0xx
            rd = (hw >> 8) & 0x7
            imm = (hw & 0xFF) * 4
            val = ((pc + 4) & ~3) + imm
            instr = f"ADD     {REG_NAMES[rd]}, PC, #0x{imm:X}  ; =0x{val:08X}"

        # ---- ADD Rd,SP,#imm ----
        elif (hw >> 11) == 0x15:  # 0xA8xx
            rd = (hw >> 8) & 0x7
            imm = (hw & 0xFF) * 4
            instr = f"ADD     {REG_NAMES[rd]}, SP, #0x{imm:X}"

        # ---- LDMIA ----
        elif (hw >> 11) == 0x19:  # 0xC8xx
            rn = (hw >> 8) & 0x7
            mask = hw & 0xFF
            instr = f"LDMIA   {REG_NAMES[rn]}!, {reglist_str(mask)}"

        # ---- STMIA ----
        elif (hw >> 11) == 0x18:  # 0xC0xx
            rn = (hw >> 8) & 0x7
            mask = hw & 0xFF
            instr = f"STMIA   {REG_NAMES[rn]}!, {reglist_str(mask)}"

        # ---- LDR Rd,[Rn,Rm] ----
        elif (hw >> 9) == 0x2C:  # 0x58xx
            rm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"LDR     {REG_NAMES[rd]}, [{REG_NAMES[rn]}, {REG_NAMES[rm]}]"

        # ---- STR Rd,[Rn,Rm] ----
        elif (hw >> 9) == 0x28:  # 0x50xx
            rm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"STR     {REG_NAMES[rd]}, [{REG_NAMES[rn]}, {REG_NAMES[rm]}]"

        # ---- LDRB Rd,[Rn,Rm] ----
        elif (hw >> 9) == 0x2E:  # 0x5Cxx
            rm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"LDRB    {REG_NAMES[rd]}, [{REG_NAMES[rn]}, {REG_NAMES[rm]}]"

        # ---- STRB Rd,[Rn,Rm] ----
        elif (hw >> 9) == 0x2A:  # 0x54xx
            rm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"STRB    {REG_NAMES[rd]}, [{REG_NAMES[rn]}, {REG_NAMES[rm]}]"

        # ---- LDRH Rd,[Rn,Rm] ----
        elif (hw >> 9) == 0x2D:  # 0x5Axx
            rm = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            instr = f"LDRH    {REG_NAMES[rd]}, [{REG_NAMES[rn]}, {REG_NAMES[rm]}]"

        # ---- Default: raw hex ----
        else:
            instr = f".hword  0x{hw:04X}"

        if not instr:
            instr = f".hword  0x{hw:04X}"

        print(f"  {addr_str}:  {hex_str:12s}  {instr}{comment}")
        pc += 2
        i += 2

    # Summary
    print(f"\n  --- Summary ---")
    if bl_targets:
        print(f"  BL calls ({len(bl_targets)}):")
        for src, tgt, name in bl_targets:
            name_str = f" ({name})" if name else ""
            print(f"    0x{src:08X} -> 0x{tgt:08X}{name_str}")
    if ldr_pool_loads:
        print(f"\n  LDR literal pool loads ({len(ldr_pool_loads)}):")
        for src, rd, addr, val, name in ldr_pool_loads:
            name_str = f" ({name})" if name else ""
            print(f"    0x{src:08X}: {REG_NAMES[rd]} = [0x{addr:08X}] = 0x{val:08X}{name_str}")
    if branches:
        print(f"\n  Conditional/unconditional branches ({len(branches)}):")
        for src, tgt, cond in branches:
            print(f"    0x{src:08X}: B{cond} -> 0x{tgt:08X}")
    print()

    return bl_targets, ldr_pool_loads, branches


def check_connection(bl_targets_1, bl_targets_2, rom):
    """Check if the first function's BL targets include SetMainCallback2 with BattleMainCB2."""
    print(f"\n{'='*80}")
    print(f"  ANALYSIS: Connection from stuck_callback2 to BattleMainCB2")
    print(f"{'='*80}\n")

    set_main_cb2 = 0x08000544
    battle_main_cb2 = 0x08094815

    for targets_list, label in [(bl_targets_1, "0x0803816D"), (bl_targets_2, "0x08036D01")]:
        print(f"  Checking {label}:")
        has_set_main = False
        for src, tgt, name in targets_list:
            if (tgt & ~1) == (set_main_cb2 & ~1):
                has_set_main = True
                print(f"    FOUND: BL SetMainCallback2 at 0x{src:08X}")
                # Check what R1 was set to before this BL
                # Look backwards for LDR R1 or MOV R1 with BattleMainCB2
                cart0 = (src & ~1) - 0x08000000
                # Search up to 10 instructions back
                for back in range(2, 22, 2):
                    check_addr = cart0 - back
                    if check_addr < 0:
                        break
                    prev_hw = u16(rom, check_addr)
                    # LDR R1,[PC,#imm]
                    if (prev_hw >> 11) == 0x09 and ((prev_hw >> 8) & 0x7) == 1:
                        imm = (prev_hw & 0xFF) * 4
                        load_pc = (src - back + 4) & ~3
                        load_addr = load_pc + imm - 0x08000000
                        if load_addr < len(rom):
                            val = u32(rom, load_addr)
                            name = lookup_addr(val)
                            print(f"      At 0x{src-back:08X}: LDR R1,[PC,#0x{imm:X}] -> 0x{val:08X}", end="")
                            if name:
                                print(f" ({name})")
                            else:
                                print()
                            if (val & ~1) == (battle_main_cb2 & ~1):
                                print(f"      *** MATCH: SetMainCallback2(BattleMainCB2) ***")

        if not has_set_main:
            print(f"    No direct BL to SetMainCallback2 found")
            # Check if any BL target might be RunTasks or AnimateSprites
            for src, tgt, name in targets_list:
                # Common game loop functions
                cart0_tgt = (tgt & ~1) - 0x08000000
                if cart0_tgt >= 0 and cart0_tgt < len(rom):
                    # Read first instruction of target
                    first_hw = u16(rom, cart0_tgt)
                    print(f"    BL target 0x{tgt:08X}: first instr = 0x{first_hw:04X}", end="")
                    if name:
                        print(f" ({name})")
                    else:
                        print()
        print()


def main():
    print("GBA THUMB Disassembler")
    print(f"ROM: {ROM_PATH}")

    rom = read_rom(ROM_PATH)
    print(f"ROM size: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)\n")

    # 1. Stuck callback2 at 0x0803816D
    bl1, ldr1, br1 = disasm_thumb_region(rom, 0x0803816C, 256,
        "stuck_callback2 (0x0803816D) - VS screen / intermediate callback?")

    # 2. Callback2 during comm processing at 0x08036D01
    bl2, ldr2, br2 = disasm_thumb_region(rom, 0x08036D00, 256,
        "cb2_during_comm_processing (0x08036D01) - active during frames 8-66")

    # 3. BattleMainCB2 at 0x08094815 - just confirm prologue
    bl3, ldr3, br3 = disasm_thumb_region(rom, 0x08094814, 64,
        "BattleMainCB2 (0x08094815) - expected final battle callback (prologue check)")

    # 4. Connection analysis
    check_connection(bl1, bl2, rom)

    # 5. Extra: disassemble a bit around CB2_HandleStartBattle for context
    print(f"\n{'='*80}")
    print(f"  BONUS: CB2_HandleStartBattle (0x08037B45) - first 128 bytes")
    print(f"{'='*80}")
    disasm_thumb_region(rom, 0x08037B44, 128,
        "CB2_HandleStartBattle - beginning of the main start-battle handler")

    # 6. Check what happens at the end of CB2_HandleStartBattle
    # It's 1850 bytes long, so check near the end for SetMainCallback2 calls
    print(f"\n{'='*80}")
    print(f"  BONUS: CB2_HandleStartBattle near end (last ~128 bytes)")
    print(f"  (Start + 1850 bytes = 0x08037B44 + 0x73A = 0x0803827E)")
    print(f"{'='*80}")
    disasm_thumb_region(rom, 0x08038200, 128,
        "CB2_HandleStartBattle - near the end, looking for SetMainCallback2")

    # 7. Specifically look for where SetMainCallback2 is called with BattleMainCB2
    # Scan around the stuck callback area
    print(f"\n{'='*80}")
    print(f"  SEARCH: Scanning 0x08037B44-0x08038300 for LDR patterns loading 0x08094815")
    print(f"{'='*80}\n")

    target_bytes = struct.pack("<I", 0x08094815)
    start_off = 0x037B44
    end_off = 0x038300
    found = False
    for off in range(start_off, min(end_off, len(rom) - 3)):
        if rom[off:off+4] == target_bytes:
            gba_addr = 0x08000000 + off
            print(f"  Found 0x08094815 at ROM offset 0x{off:06X} (GBA: 0x{gba_addr:08X})")
            # Show context: what instructions reference this literal pool entry
            # Search backwards for LDR Rd,[PC,#imm] that could reach this
            for check_off in range(max(start_off, off - 512), off, 2):
                hw = u16(rom, check_off)
                if (hw >> 11) == 0x09:  # LDR Rd,[PC,#imm]
                    rd = (hw >> 8) & 0x7
                    imm = (hw & 0xFF) * 4
                    pc_val = (0x08000000 + check_off + 4) & ~3
                    load_addr = pc_val + imm
                    if (load_addr & 0x0FFFFFFF) == off:
                        print(f"    Referenced by LDR {REG_NAMES[rd]} at 0x{0x08000000+check_off:08X}")
                        # Show a few instructions around it
                        ctx_start = max(start_off, check_off - 8)
                        for ctx in range(ctx_start, min(check_off + 12, end_off), 2):
                            chw = u16(rom, ctx)
                            marker = " >>>" if ctx == check_off else "    "
                            print(f"    {marker} 0x{0x08000000+ctx:08X}: {chw:04X}")
            found = True
    if not found:
        print(f"  0x08094815 NOT found in literal pools in range 0x{start_off:06X}-0x{end_off:06X}")
        # Widen search
        print(f"\n  Widening search to full ROM...")
        for off in range(0, len(rom) - 3, 4):  # Literal pools are word-aligned
            if rom[off:off+4] == target_bytes:
                gba_addr = 0x08000000 + off
                if off < 0x040000:  # Only show ones in the battle code area
                    print(f"  Found at ROM 0x{off:06X} (GBA: 0x{gba_addr:08X})")


if __name__ == "__main__":
    main()
