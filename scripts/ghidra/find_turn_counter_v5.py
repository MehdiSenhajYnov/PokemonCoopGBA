#!/usr/bin/env python3
"""
Find gBattleTurnCounter — v5: Full disassembly of HandleEndTurnOrder area

From battle_end_turn.c:28-40, HandleEndTurnOrder does:
    gBattleTurnCounter++;                         // <-- WHAT WE WANT
    gBattleStruct->eventState.endTurn++;           // via struct pointer
    for (u32 i = 0; i < gBattlersCount; i++)
        gBattlerByTurnOrder[i] = i;
    SortBattlersBySpeed(gBattlerByTurnOrder, FALSE);

From v4 we found: SortBattlersBySpeed(gBattlerByTurnOrder) is called at 0x0803FAEC
(BL 0x0804B430 with LDR R0, =0x020233F6 at 0x0803FAE2).

The HandleEndTurnOrder function should be BEFORE this call. It's a small static function
(~100-200 bytes) whose PUSH should be within ~100-200 bytes before the BL.

This script will:
1. Disassemble from 0x0803FA00 through 0x0803FB80 (full region)
2. Look for ALL LDRH+any_add+STRH patterns (relaxed matching)
3. Also search for gBattleStruct dereference (LDR ptr then field access)
4. Track all LDR pool loads and their resolved values
"""

import struct
import sys
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000


def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


KNOWN = {
    0x020233F6: "gBattlerByTurnOrder",
    0x020233F2: "gActionsByTurnOrder",
    0x02023598: "gChosenActionByBattler",
    0x020235FA: "gChosenMoveByBattler",
    0x0202370E: "gBattleCommunication",
    0x020233E4: "gBattlersCount",
    0x020233FC: "gBattleMons",
    0x020233DC: "gActiveBattler",
    0x02023364: "gBattleTypeFlags",
    0x020233E0: "gBattleControllerExecFlags",
    0x020233EE: "gBattlerPositions",
    0x020233E6: "gBattlerPartyIndexes",
    0x020233FA: "gCurrentTurnActionNumber",
    0x020233FB: "gCurrentActionFuncId",
    0x02023A18: "gBattleResources",
    0x0202356C: "gBattlerSpriteIds",
    0x02023594: "gBattlescriptCurrInstr",
    0x0202359C: "gBattlerAttacker",
    0x020239D0: "gBattleStruct?",
    0x02023A0C: "gBattleSpritesDataPtr?",
    0x02023958: "candidate_0x958",
    0x02023960: "candidate_0x960",
}


def decode_thumb(rom_data, pos, known=None):
    """Decode a single THUMB instruction, return (length_bytes, description, details_dict)."""
    if known is None:
        known = {}

    instr = read_u16_le(rom_data, pos)
    rom_addr = ROM_BASE + pos
    length = 2
    desc = f"0x{instr:04X}"
    details = {"type": "unknown", "instr": instr, "rom_addr": rom_addr}

    # PUSH
    if (instr & 0xFF00) in (0xB400, 0xB500):
        regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
        if instr & 0x100:
            regs.append("LR" if (instr & 0xFF00) == 0xB500 else "R8")
        desc = f"PUSH {{{', '.join(regs)}}}"
        details = {"type": "push", "regs": regs}

    # POP
    elif (instr & 0xFF00) in (0xBC00, 0xBD00):
        regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
        if instr & 0x100:
            regs.append("PC" if (instr & 0xFF00) == 0xBD00 else "R8")
        desc = f"POP {{{', '.join(regs)}}}"
        details = {"type": "pop", "regs": regs, "returns": "PC" in regs}

    # LDR Rd, [PC, #imm8*4] -- literal pool load
    elif (instr & 0xF800) == 0x4800:
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        pool_addr = ((rom_addr + 4) & ~3) + imm8 * 4
        pf = pool_addr - ROM_BASE
        val = 0
        if 0 <= pf < len(rom_data) - 3:
            val = read_u32_le(rom_data, pf)
            name = known.get(val, "")
            if name:
                desc = f"LDR R{rd}, =0x{val:08X}  <-- {name}"
            else:
                desc = f"LDR R{rd}, =0x{val:08X}"
        details = {"type": "ldr_pool", "rd": rd, "value": val}

    # MOV Rd, #imm8
    elif (instr & 0xF800) == 0x2000:
        rd = (instr >> 8) & 7
        imm = instr & 0xFF
        desc = f"MOV R{rd}, #0x{imm:X}"
        details = {"type": "mov_imm", "rd": rd, "imm": imm}

    # CMP Rn, #imm8
    elif (instr & 0xF800) == 0x2800:
        rn = (instr >> 8) & 7
        imm = instr & 0xFF
        desc = f"CMP R{rn}, #0x{imm:X}"
        details = {"type": "cmp_imm", "rn": rn, "imm": imm}

    # ADD Rd, #imm8 (Thumb format 3)
    elif (instr & 0xFF00) == 0x3000:
        rd = (instr >> 8) & 7
        imm = instr & 0xFF
        desc = f"ADD R{rd}, #0x{imm:X}"
        details = {"type": "add_imm8", "rd": rd, "imm": imm}

    # SUB Rd, #imm8 (Thumb format 3)
    elif (instr & 0xFF00) == 0x3800:
        rd = (instr >> 8) & 7
        imm = instr & 0xFF
        desc = f"SUB R{rd}, #0x{imm:X}"
        details = {"type": "sub_imm8", "rd": rd, "imm": imm}

    # ADDS Rd, Rs, #imm3 (Thumb format 2)
    elif (instr & 0xFE00) == 0x1C00:
        rd = instr & 7
        rs = (instr >> 3) & 7
        imm = (instr >> 6) & 7
        desc = f"ADDS R{rd}, R{rs}, #{imm}"
        details = {"type": "adds_imm3", "rd": rd, "rs": rs, "imm": imm}

    # SUBS Rd, Rs, #imm3
    elif (instr & 0xFE00) == 0x1E00:
        rd = instr & 7
        rs = (instr >> 3) & 7
        imm = (instr >> 6) & 7
        desc = f"SUBS R{rd}, R{rs}, #{imm}"
        details = {"type": "subs_imm3", "rd": rd, "rs": rs, "imm": imm}

    # ADD Rd, Rs, Rn (Thumb format 2, register)
    elif (instr & 0xFE00) == 0x1800:
        rd = instr & 7
        rs = (instr >> 3) & 7
        rn = (instr >> 6) & 7
        desc = f"ADDS R{rd}, R{rs}, R{rn}"
        details = {"type": "adds_reg", "rd": rd, "rs": rs, "rn": rn}

    # LDRH Rd, [Rb, #imm5*2]
    elif (instr & 0xFE00) == 0x8800:
        rd = instr & 7
        rb = (instr >> 3) & 7
        imm = ((instr >> 6) & 0x1F) * 2
        desc = f"LDRH R{rd}, [R{rb}, #0x{imm:X}]"
        details = {"type": "ldrh", "rd": rd, "rb": rb, "offset": imm}

    # STRH Rd, [Rb, #imm5*2]
    elif (instr & 0xFE00) == 0x8000:
        rd = instr & 7
        rb = (instr >> 3) & 7
        imm = ((instr >> 6) & 0x1F) * 2
        desc = f"STRH R{rd}, [R{rb}, #0x{imm:X}]"
        details = {"type": "strh", "rd": rd, "rb": rb, "offset": imm}

    # LDR Rd, [Rb, #imm5*4]
    elif (instr & 0xFE00) == 0x6800:
        rd = instr & 7
        rb = (instr >> 3) & 7
        imm = ((instr >> 6) & 0x1F) * 4
        desc = f"LDR R{rd}, [R{rb}, #0x{imm:X}]"
        details = {"type": "ldr", "rd": rd, "rb": rb, "offset": imm}

    # STR Rd, [Rb, #imm5*4]
    elif (instr & 0xFE00) == 0x6000:
        rd = instr & 7
        rb = (instr >> 3) & 7
        imm = ((instr >> 6) & 0x1F) * 4
        desc = f"STR R{rd}, [R{rb}, #0x{imm:X}]"
        details = {"type": "str", "rd": rd, "rb": rb, "offset": imm}

    # LDRB Rd, [Rb, #imm5]
    elif (instr & 0xFE00) == 0x7800:
        rd = instr & 7
        rb = (instr >> 3) & 7
        imm = (instr >> 6) & 0x1F
        desc = f"LDRB R{rd}, [R{rb}, #0x{imm:X}]"
        details = {"type": "ldrb", "rd": rd, "rb": rb, "offset": imm}

    # STRB Rd, [Rb, #imm5]
    elif (instr & 0xFE00) == 0x7000:
        rd = instr & 7
        rb = (instr >> 3) & 7
        imm = (instr >> 6) & 0x1F
        desc = f"STRB R{rd}, [R{rb}, #0x{imm:X}]"
        details = {"type": "strb", "rd": rd, "rb": rb, "offset": imm}

    # LDRH Rd, [Rb, Ro]
    elif (instr & 0xFE00) == 0x5A00:
        rd = instr & 7
        rb = (instr >> 3) & 7
        ro = (instr >> 6) & 7
        desc = f"LDRH R{rd}, [R{rb}, R{ro}]"
        details = {"type": "ldrh_reg", "rd": rd, "rb": rb, "ro": ro}

    # STRH Rd, [Rb, Ro]
    elif (instr & 0xFE00) == 0x5200:
        rd = instr & 7
        rb = (instr >> 3) & 7
        ro = (instr >> 6) & 7
        desc = f"STRH R{rd}, [R{rb}, R{ro}]"
        details = {"type": "strh_reg", "rd": rd, "rb": rb, "ro": ro}

    # LDRB Rd, [Rb, Ro]
    elif (instr & 0xFE00) == 0x5C00:
        rd = instr & 7
        rb = (instr >> 3) & 7
        ro = (instr >> 6) & 7
        desc = f"LDRB R{rd}, [R{rb}, R{ro}]"
        details = {"type": "ldrb_reg", "rd": rd, "rb": rb, "ro": ro}

    # STRB Rd, [Rb, Ro]
    elif (instr & 0xFE00) == 0x5400:
        rd = instr & 7
        rb = (instr >> 3) & 7
        ro = (instr >> 6) & 7
        desc = f"STRB R{rd}, [R{rb}, R{ro}]"
        details = {"type": "strb_reg", "rd": rd, "rb": rb, "ro": ro}

    # LDR Rd, [Rb, Ro]
    elif (instr & 0xFE00) == 0x5800:
        rd = instr & 7
        rb = (instr >> 3) & 7
        ro = (instr >> 6) & 7
        desc = f"LDR R{rd}, [R{rb}, R{ro}]"
        details = {"type": "ldr_reg", "rd": rd, "rb": rb, "ro": ro}

    # STR Rd, [Rb, Ro]
    elif (instr & 0xFE00) == 0x5000:
        rd = instr & 7
        rb = (instr >> 3) & 7
        ro = (instr >> 6) & 7
        desc = f"STR R{rd}, [R{rb}, R{ro}]"
        details = {"type": "str_reg", "rd": rd, "rb": rb, "ro": ro}

    # MOV Rd, Rm (high register)
    elif (instr & 0xFF00) == 0x4600:
        rd = ((instr >> 4) & 8) | (instr & 7)
        rm = (instr >> 3) & 0xF
        desc = f"MOV R{rd}, R{rm}"
        details = {"type": "mov_reg", "rd": rd, "rm": rm}

    # CMP Rn, Rm (low reg)
    elif (instr & 0xFFC0) == 0x4280:
        rn = instr & 7
        rm = (instr >> 3) & 7
        desc = f"CMP R{rn}, R{rm}"
        details = {"type": "cmp_reg", "rn": rn, "rm": rm}

    # LSL Rd, Rs, #imm5
    elif (instr & 0xF800) == 0x0000 and instr != 0:
        rd = instr & 7
        rs = (instr >> 3) & 7
        imm = (instr >> 6) & 0x1F
        desc = f"LSL R{rd}, R{rs}, #{imm}"
        details = {"type": "lsl_imm", "rd": rd, "rs": rs, "imm": imm}

    # LSR Rd, Rs, #imm5
    elif (instr & 0xF800) == 0x0800:
        rd = instr & 7
        rs = (instr >> 3) & 7
        imm = (instr >> 6) & 0x1F
        if imm == 0: imm = 32
        desc = f"LSR R{rd}, R{rs}, #{imm}"
        details = {"type": "lsr_imm", "rd": rd, "rs": rs, "imm": imm}

    # BX Rm
    elif (instr & 0xFF80) == 0x4700:
        rm = (instr >> 3) & 0xF
        desc = f"BX R{rm}"
        details = {"type": "bx", "rm": rm}

    # BX LR
    elif instr == 0x4770:
        desc = "BX LR"
        details = {"type": "bx_lr"}

    # ALU operations (Thumb format 4)
    elif (instr & 0xFC00) == 0x4000:
        op = (instr >> 6) & 0xF
        rs = (instr >> 3) & 7
        rd = instr & 7
        alu_names = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                     "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
        desc = f"{alu_names[op]} R{rd}, R{rs}"
        details = {"type": "alu", "op": alu_names[op], "rd": rd, "rs": rs}

    # Conditional branch
    elif (instr & 0xF000) == 0xD000:
        cond = (instr >> 8) & 0xF
        names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                 "BHI","BLS","BGE","BLT","BGT","BLE","???","SWI"]
        off = instr & 0xFF
        if off >= 0x80: off -= 0x100
        target = rom_addr + 4 + off * 2
        desc = f"{names[cond]} 0x{target:08X}"
        details = {"type": "cond_branch", "cond": names[cond], "target": target}

    # Unconditional branch
    elif (instr & 0xF800) == 0xE000:
        off = instr & 0x7FF
        if off >= 0x400: off -= 0x800
        target = rom_addr + 4 + off * 2
        desc = f"B 0x{target:08X}"
        details = {"type": "branch", "target": target}

    # BL (32-bit)
    elif (instr & 0xF800) == 0xF000 and pos + 2 < len(rom_data):
        next_instr = read_u16_le(rom_data, pos + 2)
        if (next_instr & 0xF800) == 0xF800:
            off11hi = instr & 0x07FF
            off11lo = next_instr & 0x07FF
            full_off = (off11hi << 12) | (off11lo << 1)
            if full_off >= 0x400000: full_off -= 0x800000
            target = rom_addr + 4 + full_off
            desc = f"BL 0x{target:08X}"
            details = {"type": "bl", "target": target}
            length = 4

    # ADD Rd, SP, #imm8*4
    elif (instr & 0xF800) == 0xA800:
        rd = (instr >> 8) & 7
        imm = (instr & 0xFF) * 4
        desc = f"ADD R{rd}, SP, #0x{imm:X}"
        details = {"type": "add_sp", "rd": rd, "imm": imm}

    # ADD SP, #imm7*4
    elif (instr & 0xFF80) == 0xB000:
        imm = (instr & 0x7F) * 4
        desc = f"ADD SP, #0x{imm:X}"
        details = {"type": "add_sp_imm", "imm": imm}

    # SUB SP, #imm7*4
    elif (instr & 0xFF80) == 0xB080:
        imm = (instr & 0x7F) * 4
        desc = f"SUB SP, #0x{imm:X}"
        details = {"type": "sub_sp_imm", "imm": imm}

    # STR/LDR Rd, [SP, #imm8*4]
    elif (instr & 0xF000) == 0x9000:
        is_load = (instr >> 11) & 1
        rd = (instr >> 8) & 7
        imm = (instr & 0xFF) * 4
        op = "LDR" if is_load else "STR"
        desc = f"{op} R{rd}, [SP, #0x{imm:X}]"
        details = {"type": f"{op.lower()}_sp", "rd": rd, "imm": imm}

    return length, desc, details


def disasm_region(rom_data, start_offset, end_offset, known=None):
    """Disassemble a region and return list of (rom_addr, raw, desc, details)."""
    if known is None:
        known = {}

    results = []
    pos = start_offset
    while pos < end_offset and pos + 1 < len(rom_data):
        length, desc, details = decode_thumb(rom_data, pos, known)
        rom_addr = ROM_BASE + pos

        if length == 4:
            raw = f"{read_u16_le(rom_data, pos):04X} {read_u16_le(rom_data, pos+2):04X}"
        else:
            raw = f"{read_u16_le(rom_data, pos):04X}     "

        results.append((rom_addr, raw, desc, details))
        pos += length

    return results


def find_all_refs(rom_data, target_value):
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes")
    print()

    # =========================================================================
    # PART 1: Find HandleEndTurnOrder by walking backward from SortBattlersBySpeed call
    # =========================================================================
    print("=" * 90)
    print("  PART 1: Disassemble HandleEndTurnOrder region")
    print("  SortBattlersBySpeed(gBattlerByTurnOrder) call at 0x0803FAEC")
    print("  LDR R0, =gBattlerByTurnOrder at 0x0803FAE2")
    print("=" * 90)
    print()

    # Walk backward from 0x0803FAE2 to find the function's PUSH
    sort_call_offset = 0x0003FAE2  # file offset of LDR R0, =gBTTO

    # Find the PUSH instruction (function start) by scanning backward
    # HandleEndTurnOrder may be a case in a large switch — search up to 8KB
    func_start = None
    for back in range(2, 8192, 2):
        pos = sort_call_offset - back
        if pos < 0:
            break
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) in (0xB400, 0xB500):
            func_start = pos
            break

    if func_start is None:
        print("  WARNING: Could not find function start within 8KB")
        # Just disassemble 200 bytes before the SortBattlersBySpeed call
        func_start = sort_call_offset - 200
        print(f"  Using fallback start: 0x{ROM_BASE + func_start:08X}")
    else:
        func_rom = ROM_BASE + func_start
        print(f"  Function start: 0x{func_rom:08X} (THUMB: 0x{func_rom+1:08X})")
        print(f"  Distance from PUSH to SortBattlersBySpeed call: {sort_call_offset - func_start} bytes")

    print()

    # Find the function end (POP {PC} or BX LR) after the SortBattlersBySpeed call
    func_end = sort_call_offset + 100  # At least past the call
    pos = sort_call_offset + 10  # After the BL
    while pos < sort_call_offset + 200:
        instr = read_u16_le(rom_data, pos)
        if (instr & 0xFF00) == 0xBD00 or instr == 0x4770:  # POP {PC} or BX LR
            func_end = pos + 2
            break
        pos += 2

    print(f"  Function end: ~0x{ROM_BASE + func_end:08X}")
    print()

    # Disassemble region around the SortBattlersBySpeed call
    # Start 200 bytes before the call, end 100 bytes after
    disasm_start = max(0, sort_call_offset - 200)
    disasm_end = func_end + 64
    disasm = disasm_region(rom_data, disasm_start, disasm_end, KNOWN)

    print("  FULL DISASSEMBLY:")
    print("-" * 90)
    for rom_addr, raw, desc, details in disasm:
        marker = ""
        if rom_addr == ROM_BASE + sort_call_offset:
            marker = "  <<< LDR gBattlerByTurnOrder"
        elif details.get("type") == "bl" and details.get("target") == 0x0804B430:
            marker = "  <<< SortBattlersBySpeed"
        elif details.get("type") in ("ldrh", "strh"):
            marker = "  <<< HALFWORD ACCESS"
        elif details.get("type") == "push":
            marker = "  <<< FUNCTION START"
        elif details.get("type") == "pop" and details.get("returns"):
            marker = "  <<< FUNCTION RETURN"
        print(f"  {rom_addr:08X}:  {raw}  {desc}{marker}")

    print()

    # =========================================================================
    # PART 2: Analyze the disassembly for the increment pattern
    # =========================================================================
    print("=" * 90)
    print("  PART 2: Analyze increment patterns in this function")
    print("=" * 90)
    print()

    # Look for any LDRH followed by any form of +1 then STRH
    for i, (rom_addr, raw, desc, details) in enumerate(disasm):
        if details.get("type") == "ldrh":
            rd = details["rd"]
            rb = details["rb"]
            off = details["offset"]

            # Look at next few instructions for +1 to rd, then STRH
            for j in range(i+1, min(i+5, len(disasm))):
                _, _, _, d2 = disasm[j]
                added_to = None

                # ADD Rx, #1
                if d2.get("type") == "add_imm8" and d2.get("imm") == 1:
                    added_to = d2["rd"]
                # ADDS Rx, Ry, #1
                elif d2.get("type") == "adds_imm3" and d2.get("imm") == 1:
                    added_to = d2["rd"]

                if added_to is not None:
                    # Look for STRH
                    for k in range(j+1, min(j+4, len(disasm))):
                        _, _, _, d3 = disasm[k]
                        if d3.get("type") == "strh":
                            print(f"  ** INCREMENT PATTERN FOUND:")
                            for idx in range(i, k+1):
                                a, r, d, _ = disasm[idx]
                                print(f"     {a:08X}:  {r}  {d}")

                            # What address is in rb?
                            # Trace backward to find what was loaded into rb
                            for bi in range(i-1, max(0, i-10), -1):
                                _, _, _, bd = disasm[bi]
                                if bd.get("type") == "ldr_pool" and bd.get("rd") == rb:
                                    val = bd["value"]
                                    name = KNOWN.get(val, "UNKNOWN")
                                    print(f"     => Base register R{rb} = 0x{val:08X} ({name})")
                                    print(f"     => LDRH offset = 0x{off:X}")
                                    actual_addr = val + off
                                    print(f"     => EFFECTIVE ADDRESS = 0x{actual_addr:08X}")
                                    break
                            print()

    # =========================================================================
    # PART 3: Also check the wider region — the function might be larger
    #         or HandleEndTurnOrder might be inlined into a bigger function
    # =========================================================================
    print("=" * 90)
    print("  PART 3: Extended disassembly (0x0803F900 - 0x0803FC00)")
    print("  Looking for ALL LDRH/STRH pairs with +1")
    print("=" * 90)
    print()

    ext_start = 0x0003F900
    ext_end = 0x0003FC00
    ext_disasm = disasm_region(rom_data, ext_start, ext_end, KNOWN)

    for i, (rom_addr, raw, desc, details) in enumerate(ext_disasm):
        if details.get("type") == "ldrh":
            rd = details["rd"]
            rb = details["rb"]
            off = details["offset"]

            for j in range(i+1, min(i+5, len(ext_disasm))):
                _, _, _, d2 = ext_disasm[j]
                added_to = None

                if d2.get("type") == "add_imm8" and d2.get("imm") == 1:
                    added_to = d2["rd"]
                elif d2.get("type") == "adds_imm3" and d2.get("imm") == 1:
                    added_to = d2["rd"]

                if added_to is not None:
                    for k in range(j+1, min(j+4, len(ext_disasm))):
                        _, _, _, d3 = ext_disasm[k]
                        if d3.get("type") in ("strh", "strh_reg"):
                            print(f"  ** INCREMENT at 0x{ext_disasm[i][0]:08X}:")
                            for idx in range(max(0, i-3), min(k+2, len(ext_disasm))):
                                a, r, d, _ = ext_disasm[idx]
                                print(f"     {a:08X}:  {r}  {d}")

                            # Trace rb
                            for bi in range(i-1, max(0, i-10), -1):
                                _, _, _, bd = ext_disasm[bi]
                                if bd.get("type") == "ldr_pool" and bd.get("rd") == rb:
                                    val = bd["value"]
                                    actual = val + off
                                    name = KNOWN.get(val, KNOWN.get(actual, ""))
                                    print(f"     => R{rb} = 0x{val:08X}, offset=0x{off:X}, effective=0x{actual:08X} {name}")
                                    break
                                elif bd.get("type") == "ldr_pool" and bd.get("rd") == rd:
                                    # Might have loaded value, not base pointer
                                    pass
                            print()

    # =========================================================================
    # PART 4: Search for gBattleTurnCounter as a DIRECT literal pool ref
    #         in the ENTIRE ROM, checking ALL LDRH+ADD/ADDS+STRH patterns
    #         with RELAXED matching (any register, any ordering)
    # =========================================================================
    print("=" * 90)
    print("  PART 4: Exhaustive search for u16 increment across ALL EWRAM")
    print("  Range: 0x02023700 - 0x02023B00 (wider than before)")
    print("  Pattern: LDR Rx, =addr + LDRH + (any add by 1) + STRH")
    print("  Also checking: LDRH offset != 0 (base+offset addressing)")
    print("=" * 90)
    print()

    # For each EWRAM address in the range that has literal pool refs
    for addr in range(0x02023700, 0x02023B00, 2):
        refs = find_all_refs(rom_data, addr)
        if not refs:
            continue

        for ref_off in refs:
            # This is a literal pool entry at file offset ref_off
            pool_rom_addr = ROM_BASE + ref_off

            # Find LDR instructions pointing to this pool entry
            for scan_off in range(max(0, ref_off - 1024), ref_off, 2):
                instr = read_u16_le(rom_data, scan_off)
                if (instr & 0xF800) != 0x4800:
                    continue
                pc = ROM_BASE + scan_off
                pool_calc = ((pc + 4) & ~3) + (instr & 0xFF) * 4
                if pool_calc != pool_rom_addr:
                    continue

                rd_ldr = (instr >> 8) & 7  # Register holding the EWRAM address

                # Scan next 12 instructions for LDRH from this register with ANY offset
                for ci_off in range(scan_off + 2, min(scan_off + 26, len(rom_data) - 1), 2):
                    ci = read_u16_le(rom_data, ci_off)

                    # LDRH Rx, [Rd_ldr, #offset]
                    if (ci & 0xFE00) == 0x8800 and ((ci >> 3) & 7) == rd_ldr:
                        rx = ci & 7
                        ldrh_offset = ((ci >> 6) & 0x1F) * 2

                        # Check next 4 instructions for any ADD/ADDS by 1 targeting rx or any reg
                        for ai_off in range(ci_off + 2, min(ci_off + 10, len(rom_data) - 1), 2):
                            ai = read_u16_le(rom_data, ai_off)
                            add_dest = -1

                            # ADD Rx, #1 (format 3)
                            if (ai & 0xFF00) == 0x3000 and (ai & 0xFF) == 1:
                                add_dest = (ai >> 8) & 7
                            # ADDS Rd, Rs, #1 (format 2) where Rs could be rx
                            elif (ai & 0xFE00) == 0x1C00 and ((ai >> 6) & 7) == 1:
                                add_src = (ai >> 3) & 7
                                if add_src == rx:
                                    add_dest = ai & 7

                            if add_dest < 0:
                                continue

                            # Check for STRH back
                            for si_off in range(ai_off + 2, min(ai_off + 6, len(rom_data) - 1), 2):
                                si = read_u16_le(rom_data, si_off)
                                # STRH add_dest, [rd_ldr, #same_offset]
                                expected_strh = 0x8000 | (rd_ldr << 3) | add_dest | ((ldrh_offset // 2) << 6)
                                if si == expected_strh:
                                    effective_addr = addr + ldrh_offset
                                    name = KNOWN.get(effective_addr, KNOWN.get(addr, ""))
                                    print(f"  *** 0x{effective_addr:08X} (base=0x{addr:08X}+0x{ldrh_offset:X}): "
                                          f"INCREMENT at 0x{ROM_BASE+scan_off:08X} {name}")
                                    # Show context
                                    ctx = disasm_region(rom_data, scan_off - 4, si_off + 4, KNOWN)
                                    for a, r, d, _ in ctx:
                                        print(f"     {a:08X}:  {r}  {d}")
                                    print()

    # =========================================================================
    # PART 5: Check if gBattleTurnCounter uses gBattleStruct-relative addressing
    #         gBattleStruct = gBattleResources->battleStruct (first field)
    # =========================================================================
    print("=" * 90)
    print("  PART 5: Check gBattleStruct pointer-based access pattern")
    print("  HandleEndTurnOrder also does: gBattleStruct->eventState.endTurn++")
    print("  If compiler optimizes, gBattleTurnCounter might be adjacent to gBattleStruct")
    print("  and accessed via the same base pointer")
    print("=" * 90)
    print()

    # gBattleResources = 0x02023A18, refs in ROM
    gBR_refs = find_all_refs(rom_data, 0x02023A18)
    print(f"  gBattleResources (0x02023A18): {len(gBR_refs)} ROM literal pool refs")

    # Also check gBattleStruct candidates
    for candidate in [0x020239D0, 0x020239D4, 0x020239D8]:
        refs = find_all_refs(rom_data, candidate)
        if refs:
            print(f"  0x{candidate:08X}: {len(refs)} ROM refs")

    print()

    # =========================================================================
    # PART 6: Source declares gBattleTurnCounter AFTER gFieldTimers.
    #         gFieldTimers is a struct. Let's find gFieldStatuses first,
    #         then trace forward.
    #         gFieldStatuses (u32) -> gFieldTimers (struct FieldTimer) -> gBattleTurnCounter (u16)
    # =========================================================================
    print("=" * 90)
    print("  PART 6: Find gFieldStatuses & gFieldTimers to locate gBattleTurnCounter")
    print("  Source order: gFieldStatuses(u32) -> gFieldTimers(struct) -> gBattleTurnCounter(u16)")
    print("=" * 90)
    print()

    # gFieldStatuses should have decent refs (it's a u32 with flags)
    # Search in range after gBattleSpritesDataPtr and before gBattleResources
    # Expected area: ~0x02023900-0x02023A18

    print("  Scanning 0x02023900-0x02023A18 for u32-aligned addrs with 5+ refs:")
    fs_candidates = []
    for addr in range(0x02023900, 0x02023A18, 4):
        refs = find_all_refs(rom_data, addr)
        count = len(refs)
        if count >= 5:
            name = KNOWN.get(addr, "")
            print(f"    0x{addr:08X}: {count:3d} refs  {name}")
            fs_candidates.append((addr, count))

    print()

    # gBattleTurnCounter (u16) is right after gFieldTimers.
    # FieldTimer struct in expansion:
    #   fairyLockTimer(u8), fairyLockTimerBattlerId(u8), gravityTimer(u8), etc.
    #   Check refs/pokeemerald-expansion/include/battle.h for struct FieldTimer

    # Let's just search for u16 addresses with 2-20 refs right after the
    # high-ref-count u32 addresses (those are likely gFieldStatuses area)
    print("  Scanning 0x02023940-0x02023980 for u16-aligned addrs with 1-20 refs:")
    for addr in range(0x02023940, 0x02023980, 2):
        refs = find_all_refs(rom_data, addr)
        count = len(refs)
        if count >= 1:
            name = KNOWN.get(addr, "")
            print(f"    0x{addr:08X}: {count:3d} refs  {name}")

    print()

    # =========================================================================
    # PART 7: Check ALL TryDoEventsBeforeFirstTurn references
    #         This function sets gBattleTurnCounter = 0
    #         It's in battle_main.c, references gBattlerByTurnOrder AND
    #         gChosenActionByBattler. Find it.
    # =========================================================================
    print("=" * 90)
    print("  PART 7: Find TryDoEventsBeforeFirstTurn (sets gBattleTurnCounter = 0)")
    print("  Pattern: function with gBattlerByTurnOrder + gChosenActionByBattler + MOV #0 + STRH")
    print("=" * 90)
    print()

    btto_refs = find_all_refs(rom_data, 0x020233F6)  # gBattlerByTurnOrder
    cab_refs_set = set()
    for r in find_all_refs(rom_data, 0x02023598):  # gChosenActionByBattler
        # Find function containing this ref
        for back in range(2, 4096, 2):
            pos = r - back
            if pos < 0: break
            instr = read_u16_le(rom_data, pos)
            if (instr & 0xFF00) in (0xB400, 0xB500):
                cab_refs_set.add(pos)
                break

    # For each function referencing gBattlerByTurnOrder, check if it also refs gChosenActionByBattler
    for btto_ref in btto_refs:
        func_start = None
        for back in range(2, 4096, 2):
            pos = btto_ref - back
            if pos < 0: break
            instr = read_u16_le(rom_data, pos)
            if (instr & 0xFF00) in (0xB400, 0xB500):
                func_start = pos
                break

        if func_start is None or func_start not in cab_refs_set:
            continue

        # This function refs both gBattlerByTurnOrder AND gChosenActionByBattler
        # Disassemble it and look for MOV #0 + STRH pattern with a nearby LDR =EWRAM_addr
        func_disasm = disasm_region(rom_data, func_start, func_start + 4096, KNOWN)

        # Find all "MOV Rx, #0" instructions
        for i, (rom_addr, raw, desc, details) in enumerate(func_disasm):
            if details.get("type") == "mov_imm" and details.get("imm") == 0:
                zero_reg = details["rd"]

                # Look for STRH zero_reg, [Ry, #0] in next few instructions
                for j in range(i+1, min(i+4, len(func_disasm))):
                    _, _, _, d2 = func_disasm[j]
                    if d2.get("type") == "strh" and d2.get("rd") == zero_reg and d2.get("offset") == 0:
                        base_reg = d2["rb"]

                        # Trace backward to find what was loaded into base_reg
                        for bi in range(i-1, max(0, i-8), -1):
                            _, _, _, bd = func_disasm[bi]
                            if bd.get("type") == "ldr_pool" and bd.get("rd") == base_reg:
                                val = bd["value"]
                                if 0x02023000 <= val < 0x02024000:
                                    total_refs = len(find_all_refs(rom_data, val))
                                    name = KNOWN.get(val, "")
                                    print(f"  STORE_ZERO to 0x{val:08X} ({total_refs} refs) in func 0x{ROM_BASE+func_start+1:08X} {name}")
                                    # Show context
                                    for idx in range(max(0, bi), min(j+1, len(func_disasm))):
                                        a, r, d, _ = func_disasm[idx]
                                        print(f"     {a:08X}:  {r}  {d}")
                                    print()
                                break

    print()
    print("  DONE")
    print()


if __name__ == "__main__":
    main()
