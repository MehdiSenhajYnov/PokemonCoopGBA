#!/usr/bin/env python3
"""
Full disassembly of SetUpBattleVarsAndBirchZigzagoon to find HandleLinkBattleSetup call.

The decomp source shows:
  SetUpBattleVarsAndBirchZigzagoon() {
    gBattleMainFunc = BeginBattleIntroDummy;   // store func ptr
    for (i=0; i<MAX_BATTLERS_COUNT; i++) {     // loop 4x
      gBattlerControllerFuncs[i] = BattleControllerDummy;
      gBattlerPositions[i] = 0xFF;
      gActionSelectionCursor[i] = 0;
      gMoveSelectionCursor[i] = 0;
    }
    HandleLinkBattleSetup();                   // <-- THE CALL WE WANT
    gBattleControllerExecFlags = 0;            // store 0
    ClearBattleAnimationVars();
    BattleAI_SetupItems();
    BattleAI_SetupFlags();
    if (gBattleTypeFlags & BATTLE_TYPE_FIRST_BATTLE) { ... }
  }

We know it has 7 BL calls. Let's match them to the source:
  BL 1: ClearBattleAnimationVars? or something in the loop?
  BL 2: same target as BL1 - must be loop body
  BL 3-7: HandleLinkBattleSetup, ClearBattleAnimationVars, BattleAI_SetupItems, BattleAI_SetupFlags, and ?

Let's do detailed disassembly with ALL instruction types.
"""
import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_bl(hw1, hw2, pc):
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) in (0xF800, 0xE800):
        offset_hi = hw1 & 0x07FF
        if offset_hi & 0x400:
            offset_hi |= 0xFFFFF800
        offset_lo = hw2 & 0x07FF
        target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
        return target & 0xFFFFFFFF
    return None

def disasm_full(rom, rom_offset, length):
    """Full THUMB disassembly with all common instructions."""
    i = 0
    while i < length:
        hw = struct.unpack_from("<H", rom, rom_offset + i)[0]
        addr = 0x08000000 + rom_offset + i

        # Check BL (32-bit)
        if i + 2 < length:
            hw2 = struct.unpack_from("<H", rom, rom_offset + i + 2)[0]
            bl_target = decode_bl(hw, hw2, addr)
            if bl_target is not None:
                print(f"  +0x{i:03X} [{addr:08X}]: BL 0x{bl_target:08X}")
                i += 4
                continue

        desc = decode_thumb(hw, addr, rom, rom_offset)
        print(f"  +0x{i:03X} [{addr:08X}]: 0x{hw:04X}  {desc}")

        # Stop at BX LR or POP {PC} after reasonable length
        if (hw & 0xFF87) == 0x4700 and i > 8:  # BX Rm
            rm = (hw >> 3) & 0xF
            if rm == 14:  # BX LR
                print("  --- possible function end (BX LR) ---")
        if (hw & 0xFF00) == 0xBD00:
            print("  --- function end (POP {PC}) ---")
            break

        i += 2

def decode_thumb(hw, addr, rom, base_offset):
    """Decode a single THUMB instruction."""
    # Format 1: Move shifted register
    if (hw & 0xE000) == 0x0000:
        op = (hw >> 11) & 3
        imm5 = (hw >> 6) & 0x1F
        rs = (hw >> 3) & 7
        rd = hw & 7
        ops = ["LSL", "LSR", "ASR"]
        if op < 3:
            return f"{ops[op]}S R{rd}, R{rs}, #{imm5}"

    # Format 2: Add/subtract
    if (hw & 0xF800) == 0x1800:
        rn_imm = (hw >> 6) & 7
        rs = (hw >> 3) & 7
        rd = hw & 7
        if hw & 0x0400:  # immediate
            return f"ADDS R{rd}, R{rs}, #{rn_imm}" if not (hw & 0x0200) else f"SUBS R{rd}, R{rs}, #{rn_imm}"
        else:
            return f"ADDS R{rd}, R{rs}, R{rn_imm}" if not (hw & 0x0200) else f"SUBS R{rd}, R{rs}, R{rn_imm}"

    # Format 3: Move/compare/add/subtract immediate
    if (hw & 0xE000) == 0x2000:
        op = (hw >> 11) & 3
        rd = (hw >> 8) & 7
        imm = hw & 0xFF
        ops = ["MOVS", "CMP", "ADDS", "SUBS"]
        return f"{ops[op]} R{rd}, #0x{imm:X} ({imm})"

    # Format 4: ALU operations
    if (hw & 0xFC00) == 0x4000:
        op = (hw >> 6) & 0xF
        rs = (hw >> 3) & 7
        rd = hw & 7
        ops = ["ANDS","EORS","LSLS","LSRS","ASRS","ADCS","SBCS","RORS",
               "TST","NEGS","CMP","CMN","ORRS","MULS","BICS","MVNS"]
        return f"{ops[op]} R{rd}, R{rs}"

    # Format 5: Hi register ops / BX
    if (hw & 0xFC00) == 0x4400:
        op = (hw >> 8) & 3
        h1 = (hw >> 7) & 1
        h2 = (hw >> 6) & 1
        rs = ((hw >> 3) & 7) | (h2 << 3)
        rd = (hw & 7) | (h1 << 3)
        if op == 0: return f"ADD R{rd}, R{rs}"
        if op == 1: return f"CMP R{rd}, R{rs}"
        if op == 2: return f"MOV R{rd}, R{rs}"
        if op == 3: return f"BX R{rs}"

    # Format 6: PC-relative load
    if (hw & 0xF800) == 0x4800:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        pool_addr = ((addr + 4) & ~3) + imm
        pool_offset = pool_addr - 0x08000000
        if 0 <= pool_offset < len(rom) - 4:
            pool_val = struct.unpack_from("<I", rom, pool_offset)[0]
            return f"LDR R{rd}, =0x{pool_val:08X}  ; [PC+0x{imm:X}]"
        return f"LDR R{rd}, [PC, #0x{imm:X}]"

    # Format 7: Load/Store register offset
    if (hw & 0xF200) == 0x5000:
        ro = (hw >> 6) & 7
        rb = (hw >> 3) & 7
        rd = hw & 7
        l = (hw >> 11) & 1
        b = (hw >> 10) & 1
        if l:
            return f"LDR{'B' if b else ''} R{rd}, [R{rb}, R{ro}]"
        else:
            return f"STR{'B' if b else ''} R{rd}, [R{rb}, R{ro}]"

    # Format 8: Load/Store sign-extended byte/halfword
    if (hw & 0xF200) == 0x5200:
        ro = (hw >> 6) & 7
        rb = (hw >> 3) & 7
        rd = hw & 7
        op = (hw >> 10) & 3
        ops = ["STRH", "LDSB", "LDRH", "LDSH"]
        return f"{ops[op]} R{rd}, [R{rb}, R{ro}]"

    # Format 9: Load/Store word/byte immediate offset
    if (hw & 0xE000) == 0x6000:
        l = (hw >> 11) & 1
        b = (hw >> 10) & 1
        imm = (hw >> 6) & 0x1F
        rb = (hw >> 3) & 7
        rd = hw & 7
        if not b: imm *= 4
        if l:
            return f"LDR{'B' if b else ''} R{rd}, [R{rb}, #0x{imm:X}]"
        else:
            return f"STR{'B' if b else ''} R{rd}, [R{rb}, #0x{imm:X}]"

    # Format 10: Load/Store halfword
    if (hw & 0xF000) == 0x8000:
        l = (hw >> 11) & 1
        imm = ((hw >> 6) & 0x1F) * 2
        rb = (hw >> 3) & 7
        rd = hw & 7
        if l:
            return f"LDRH R{rd}, [R{rb}, #0x{imm:X}]"
        else:
            return f"STRH R{rd}, [R{rb}, #0x{imm:X}]"

    # Format 11: SP-relative load/store
    if (hw & 0xF000) == 0x9000:
        l = (hw >> 11) & 1
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        if l:
            return f"LDR R{rd}, [SP, #0x{imm:X}]"
        else:
            return f"STR R{rd}, [SP, #0x{imm:X}]"

    # Format 12: Load address
    if (hw & 0xF000) == 0xA000:
        rd = (hw >> 8) & 7
        imm = (hw & 0xFF) * 4
        sp = (hw >> 11) & 1
        if sp:
            return f"ADD R{rd}, SP, #0x{imm:X}"
        else:
            return f"ADD R{rd}, PC, #0x{imm:X}"

    # Format 13: Add offset to SP
    if (hw & 0xFF00) == 0xB000:
        imm = (hw & 0x7F) * 4
        if hw & 0x80:
            return f"SUB SP, #0x{imm:X}"
        else:
            return f"ADD SP, #0x{imm:X}"

    # Format 14: Push/Pop
    if (hw & 0xF600) == 0xB400:
        l = (hw >> 11) & 1
        r = (hw >> 8) & 1
        rlist = hw & 0xFF
        regs = [f"R{i}" for i in range(8) if rlist & (1 << i)]
        if r:
            regs.append("LR" if not l else "PC")
        op = "POP" if l else "PUSH"
        return f"{op} {{{', '.join(regs)}}}"

    # Format 16: Conditional branch
    if (hw & 0xF000) == 0xD000:
        cond = (hw >> 8) & 0xF
        offset = hw & 0xFF
        if offset & 0x80: offset = offset - 256
        cond_names = {0:"BEQ",1:"BNE",2:"BCS",3:"BCC",4:"BMI",5:"BPL",
                     6:"BVS",7:"BVC",8:"BHI",9:"BLS",10:"BGE",11:"BLT",
                     12:"BGT",13:"BLE",14:"(undef)",15:"SWI"}
        cname = cond_names.get(cond, f"B.{cond}")
        if cond == 15:
            return f"SWI 0x{hw & 0xFF:02X}"
        target = addr + 4 + offset * 2
        return f"{cname} 0x{target:08X}"

    # Format 18: Unconditional branch
    if (hw & 0xF800) == 0xE000:
        offset = hw & 0x7FF
        if offset & 0x400: offset = offset - 2048
        target = addr + 4 + offset * 2
        return f"B 0x{target:08X}"

    return f"??? (0x{hw:04X})"

def main():
    rom = read_rom()

    setup_offset = 0x06F1D8
    print(f"=== SetUpBattleVarsAndBirchZigzagoon (ROM 0x{setup_offset:06X}) ===")
    print(f"=== Full THUMB disassembly (first 400 bytes) ===\n")
    disasm_full(rom, setup_offset, 400)

if __name__ == "__main__":
    main()
