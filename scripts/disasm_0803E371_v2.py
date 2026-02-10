#!/usr/bin/env python3
"""
Disassembly v2: Follow-up analysis of 0x0803E371.

From v1 we know:
- 0x03005D04 is used to store function pointers (gBattleMainFunc!)
- At 0x0803E310: STR 0x0803E371 into [0x03005D04] -- this sets gBattleMainFunc = our target
- The function at 0x0803E370 is ~0xCC bytes (to 0x0803E43C/0x0803E440)
- It references gBattleCommunication[8] (at 0x02023716), gBattleStruct
- It calls 0x0803DDE4 and 0x0803DF48 (unknown functions)
- The function at 0x0803E450 starts a NEW function that checks gBattleTypeFlags for LINK (0x02000002)
- Jump table entries at 0x0803E538 point to 0x0803E610 and 0x0803E624

Key questions:
1. What is at 0x0803E310 -- which function sets bmf to our target?
2. What are the jump table targets at 0x0803E610, 0x0803E624, 0x0803E62E, 0x0803E634?
3. What are the called functions at 0x0803DDE4 and 0x0803DF48?
4. Is 0x03005D04 = gBattleMainFunc?
5. What is 0x020233FB? (loaded into r6) -- it's gBattleTypeFlags+0x97, but actually it's
   a DIFFERENT variable since gBattleTypeFlags is at 0x02023364.
"""

import struct
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

KNOWN_ADDRS = {
    0x02023364: "gBattleTypeFlags",
    0x020233E0: "gBattleControllerExecFlags",
    0x020233E4: "gBattlersCount",  # likely, offset 0x80 from gBattleTypeFlags
    0x020233FA: "gCurrentTurnActionNumber",  # offset 0x96 from gBattleTypeFlags base
    0x020233FB: "gCurrentActionFuncId",  # offset 0x97 from gBattleTypeFlags base
    0x020233FC: "gBattleMons",
    0x0202359C: "gBattleMainFunc_or_gBattleScriptCurrInstr?",  # needs verification
    0x02023604: "gHitMarker",  # likely
    0x0202370E: "gBattleCommunication",
    0x02023716: "gBattleCommunication[8]=gBattleOutcome",
    0x02023A0C: "gBattleStruct_ptr",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x0202064C: "gMain.callback2",
    0x020232BE: "gBattleScripting.moveendState?",
    0x02023594: "gBattleResources_field?",
    0x020381AE: "gBattleResults.battleTurnCounter?",
    0x02036BB0: "gSpecialVar_Result?",
    0x030022C0: "gMain",
    0x03005D04: "gBattleMainFunc",
    0x03005D70: "gBattlerControllerFuncs",
    0x03005D90: "gRngValue",

    # ROM functions
    0x0803ACB1: "DoBattleIntro",
    0x0803BE39: "HandleTurnActionSelectionState",
    0x0803DDE4: "DoEndTurnEffects_or_related",
    0x0803DF48: "HandleFaintedMonActions_or_BattleArenaTurnEnd",
    0x0803E371: "TARGET=RunTurnActionsFunctions?",
    0x0803E451: "SetActionsAndBattlersTurnOrder_or_similar",
    0x083458B0: "sTurnActionsFuncsTable_dispatch",
    0x080C49D8: "BeginFastPaletteFade_or_BattlePutTextOnWindow",
    0x0807721C: "BattleScriptExecute",
    0x08094815: "CB2_BattleMain",
    0x080363C1: "CB2_InitBattle",

    # Table addresses
    0x083AD6C8: "sTurnActionsFuncsTable",
    0x083AD720: "sEndTurnFuncsTable",
    0x08339C3D: "BattleScript_something1",
    0x08339C8F: "BattleScript_something2",
    0x08339B27: "BattleScript_something3",
    0x08398880: "gTrainerSlides_or_data_table",
}

BATTLE_TYPE_FLAGS = {
    0x00000002: "LINK",
    0x00000008: "TRAINER",
    0x00000200: "WALLY_TUTORIAL",
    0x00100000: "INGAME_PARTNER",
}


def read_u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def sign_extend(val, bits):
    if val & (1 << (bits - 1)):
        val -= (1 << bits)
    return val

def addr_name(addr):
    if addr in KNOWN_ADDRS:
        return f" = {KNOWN_ADDRS[addr]}"
    for ka, name in KNOWN_ADDRS.items():
        if 0 < addr - ka < 32:
            return f" = {name}+0x{addr-ka:X}"
    return ""

def quick_disasm(data, rom_addr, count=30, label=""):
    """Quick disassembly of count instructions at rom_addr."""
    offset = rom_addr - 0x08000000
    if offset < 0 or offset >= len(data):
        print(f"  [Invalid offset for 0x{rom_addr:08X}]")
        return

    if label:
        print(f"\n--- {label} ---")
    print(f"  Disassembly at 0x{rom_addr:08X}:")

    i = 0
    while i < count:
        if offset + i*2 + 1 >= len(data):
            break
        instr = read_u16(data, offset + i*2)
        addr = rom_addr + i*2

        # Simple decode for key patterns
        decoded = simple_decode(instr, addr, data)

        # Check for BL pair
        if (instr >> 11) == 0x1E and offset + (i+1)*2 + 1 < len(data):
            instr2 = read_u16(data, offset + (i+1)*2)
            if (instr2 >> 11) == 0x1F:
                imm11_hi = instr & 0x7FF
                imm11_lo = instr2 & 0x7FF
                bl_offset = (sign_extend(imm11_hi, 11) << 12) | (imm11_lo << 1)
                target = (addr + 4 + bl_offset) & 0xFFFFFFFF
                name = addr_name(target)
                print(f"    0x{addr:08X}: {instr:04X} {instr2:04X}  BL 0x{target:08X}{name}")
                i += 2
                continue

        print(f"    0x{addr:08X}: {instr:04X}      {decoded}")

        # Stop at BX LR or POP {... PC}
        if instr == 0x4770:  # BX LR
            break
        if (instr & 0xFF00) == 0xBD00:  # POP {... PC}
            break

        i += 1


def simple_decode(instr, addr, data):
    """Simplified THUMB decoder for key patterns."""
    # PUSH
    if (instr & 0xFE00) == 0xB400:
        r = (instr >> 8) & 1
        rlist = instr & 0xFF
        regs = [f"r{b}" for b in range(8) if rlist & (1 << b)]
        if r: regs.append("LR")
        return f"PUSH {{{', '.join(regs)}}}"

    # POP
    if (instr & 0xFE00) == 0xBC00:
        r = (instr >> 8) & 1
        rlist = instr & 0xFF
        regs = [f"r{b}" for b in range(8) if rlist & (1 << b)]
        if r: regs.append("PC")
        return f"POP {{{', '.join(regs)}}}"

    # LDR Rd, [PC, #imm]
    if (instr >> 11) == 0x9:
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        pc_val = (addr + 4) & ~3
        pool_addr = pc_val + imm8 * 4
        pool_offset = pool_addr - 0x08000000
        if 0 <= pool_offset < len(data) - 3:
            val = read_u32(data, pool_offset)
            name = addr_name(val)
            return f"LDR r{rd}, [PC, #0x{imm8*4:X}] ; =0x{val:08X}{name}"
        return f"LDR r{rd}, [PC, #0x{imm8*4:X}]"

    # STR Rd, [Rb, #imm]
    if (instr >> 13) == 3:
        b_flag = (instr >> 12) & 1
        l_flag = (instr >> 11) & 1
        off5 = (instr >> 6) & 0x1F
        rb = (instr >> 3) & 7
        rd = instr & 7
        if b_flag:
            op = "LDRB" if l_flag else "STRB"
            return f"{op} r{rd}, [r{rb}, #0x{off5:X}]"
        else:
            op = "LDR" if l_flag else "STR"
            return f"{op} r{rd}, [r{rb}, #0x{off5*4:X}]"

    # MOV/CMP/ADD/SUB immediate
    if (instr >> 13) == 1:
        op = (instr >> 11) & 3
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        ops = ["MOV", "CMP", "ADD", "SUB"]
        return f"{ops[op]} r{rd}, #0x{imm8:02X}"

    # Conditional branch
    if (instr >> 12) == 0xD and ((instr >> 8) & 0xF) < 0xE:
        cond = (instr >> 8) & 0xF
        soff = sign_extend(instr & 0xFF, 8)
        target = addr + 4 + soff * 2
        conds = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                 "BHI","BLS","BGE","BLT","BGT","BLE"]
        name = addr_name(target & 0xFFFFFFFF)
        return f"{conds[cond]} 0x{target & 0xFFFFFFFF:08X}{name}"

    # Unconditional branch
    if (instr >> 11) == 0x1C:
        soff = sign_extend(instr & 0x7FF, 11)
        target = addr + 4 + soff * 2
        name = addr_name(target & 0xFFFFFFFF)
        return f"B 0x{target & 0xFFFFFFFF:08X}{name}"

    # BX
    if (instr & 0xFF80) == 0x4700:
        rm = (instr >> 3) & 0xF
        return f"BX r{rm}"

    # ALU
    if (instr >> 10) == 0x10:
        op = (instr >> 6) & 0xF
        rs = (instr >> 3) & 7
        rd = instr & 7
        ops = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
               "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
        return f"{ops[op]} r{rd}, r{rs}"

    # Hi-reg MOV/ADD/CMP/BX
    if (instr >> 10) == 0x11:
        op = (instr >> 8) & 3
        h1 = (instr >> 7) & 1
        h2 = (instr >> 6) & 1
        rs = ((h2 << 3) | ((instr >> 3) & 7))
        rd = ((h1 << 3) | (instr & 7))
        if op == 0: return f"ADD r{rd}, r{rs}"
        elif op == 1: return f"CMP r{rd}, r{rs}"
        elif op == 2: return f"MOV r{rd}, r{rs}"
        elif op == 3: return f"BX r{rs}"

    # LDRH/STRH
    if (instr >> 12) == 8:
        l = (instr >> 11) & 1
        off5 = (instr >> 6) & 0x1F
        rb = (instr >> 3) & 7
        rd = instr & 7
        op = "LDRH" if l else "STRH"
        return f"{op} r{rd}, [r{rb}, #0x{off5*2:X}]"

    # SP-relative
    if (instr >> 12) == 9:
        l = (instr >> 11) & 1
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        op = "LDR" if l else "STR"
        return f"{op} r{rd}, [SP, #0x{imm8*4:X}]"

    # ADD PC/SP
    if (instr >> 12) == 0xA:
        sp = (instr >> 11) & 1
        rd = (instr >> 8) & 7
        imm8 = instr & 0xFF
        src = "SP" if sp else "PC"
        return f"ADD r{rd}, {src}, #0x{imm8*4:X}"

    # SP adjust
    if (instr >> 8) == 0xB0:
        s = (instr >> 7) & 1
        imm7 = instr & 0x7F
        return f"{'SUB' if s else 'ADD'} SP, #0x{imm7*4:X}"

    # Format 2: ADD/SUB 3-reg
    op_top3 = instr >> 11
    if op_top3 == 0x3:  # 00011
        i_flag = (instr >> 10) & 1
        op = (instr >> 9) & 1
        rn = (instr >> 6) & 7
        rs = (instr >> 3) & 7
        rd = instr & 7
        opn = "SUB" if op else "ADD"
        if i_flag:
            return f"{opn} r{rd}, r{rs}, #{rn}"
        return f"{opn} r{rd}, r{rs}, r{rn}"

    # LSL/LSR/ASR immediate
    if (instr >> 13) == 0:
        op = (instr >> 11) & 3
        off5 = (instr >> 6) & 0x1F
        rs = (instr >> 3) & 7
        rd = instr & 7
        ops = ["LSL","LSR","ASR"]
        if op < 3:
            return f"{ops[op]} r{rd}, r{rs}, #{off5}"

    # LDMIA/STMIA
    if (instr >> 12) == 0xC:
        l = (instr >> 11) & 1
        rb = (instr >> 8) & 7
        rlist = instr & 0xFF
        regs = [f"r{b}" for b in range(8) if rlist & (1 << b)]
        op = "LDMIA" if l else "STMIA"
        return f"{op} r{rb}!, {{{', '.join(regs)}}}"

    return f"??? (0x{instr:04X})"


def main():
    with open(ROM_PATH, 'rb') as f:
        rom = f.read()

    print("=" * 80)
    print("ANALYSIS v2 — Identifying the stuck function at 0x0803E371")
    print("=" * 80)

    # 1. Confirm gBattleMainFunc = 0x03005D04
    print("\n## 1. gBattleMainFunc address verification")
    print("At 0x0803E310: LDR r0, =0x0803E371; STR r0, [0x03005D04]")
    print("At 0x0803E3E0: LDR r3, =0x03005D04 then STR r0, [r3]")
    print("=> 0x03005D04 IS gBattleMainFunc")

    # 2. Who calls our function? Check 0x0803BAC0 context
    print("\n## 2. Who sets gBattleMainFunc = 0x0803E371?")
    print("Found reference at 0x0803BAFC (loaded by LDR at 0x0803BAC0)")
    quick_disasm(rom, 0x0803BA80, 50, "Context around 0x0803BAC0 (who sets bmf=target)")

    # 3. Also check 0x0803E30C context (second reference)
    print("\n## 3. Second reference: around 0x0803E310")
    quick_disasm(rom, 0x0803E2D0, 40, "Context around 0x0803E310")

    # 4. Disassemble the called functions
    print("\n## 4. Called function at 0x0803DDE4")
    quick_disasm(rom, 0x0803DDE4, 40, "Function 0x0803DDE4 (called at 0x0803E398)")

    print("\n## 5. Called function at 0x0803DF48")
    quick_disasm(rom, 0x0803DF48, 40, "Function 0x0803DF48 (called at 0x0803E3A0)")

    # 5. Check jump table targets
    print("\n## 6. Jump table at 0x0803E538")
    for i in range(20):
        off = 0x0003E538 + i*4
        if off + 3 < len(rom):
            val = read_u32(rom, off)
            print(f"  [{i:2d}] 0x{val:08X}{addr_name(val)}")

    # 6. Disassemble jump table targets
    print("\n## 7. Jump table target 0x0803E610")
    quick_disasm(rom, 0x0803E610, 20, "Jump target 0x0803E610")

    print("\n## 8. Jump table target 0x0803E624")
    quick_disasm(rom, 0x0803E624, 20, "Jump target 0x0803E624")

    print("\n## 9. Branch target 0x0803E61A")
    quick_disasm(rom, 0x0803E61A, 15, "Branch target 0x0803E61A")

    print("\n## 10. Branch target 0x0803E62E")
    quick_disasm(rom, 0x0803E62E, 15, "Branch target 0x0803E62E")

    print("\n## 11. Branch target 0x0803E634")
    quick_disasm(rom, 0x0803E634, 15, "Branch target 0x0803E634")

    # 7. Key variable identification
    print("\n## 12. Variable identification")
    print("  0x020233FB = gCurrentActionFuncId (offset 0x97 from gBattleTypeFlags base 0x02023364)")
    print("  0x020233FA = gCurrentTurnActionNumber (offset 0x96)")
    print("  0x020233E4 = gBattlersCount (offset 0x80)")
    print("  0x02023604 = gHitMarker")
    print("  0x0202359C = likely gBattlescriptCurrInstr or another func pointer")
    print("  0x03005D04 = gBattleMainFunc")
    print("  0x083AD6C8 = sTurnActionsFuncsTable")
    print("  0x083AD720 = sEndTurnFuncsTable")

    # 8. Critical analysis of the function
    print("\n" + "=" * 80)
    print("## 13. CRITICAL ANALYSIS of 0x0803E370 (RunTurnActionsFunctions)")
    print("=" * 80)

    print("""
RECONSTRUCTED C CODE (from disassembly):

static void RunTurnActionsFunctions(void)  // at 0x0803E370
{
    // 0x0803E372-0x0803E37E: Check gBattleOutcome (gBattleCommunication[8])
    if (gBattleOutcome != 0)   // gBattleCommunication[8] at 0x02023716
        gCurrentActionFuncId = B_ACTION_FINISHED;  // 12

    // r6 = &gCurrentActionFuncId (0x020233FB)
    // r5 = &gBattleStruct ptr (0x02023A0C)

    // 0x0803E380-0x0803E3B2: Check effectsBeforeUsingMoveDone
    if (gCurrentActionFuncId == 0  // B_ACTION_USE_MOVE
        && !(gBattleStruct->someField[0x3C1] & 0x20))  // effectsBeforeUsingMoveDone
    {
        // 0x0803E398: BL 0x0803DDE4 — probably TryDoGimmicksBeforeMoves or IsPursuitTargetSet
        if (func_0803DDE4() != 0)
            goto end;  // return

        // 0x0803E3A0: BL 0x0803DF48 — probably TryDoMoveEffectsBeforeMoves
        if (func_0803DF48() != 0)
            goto end;  // return

        // Set effectsBeforeUsingMoveDone = TRUE
        gBattleStruct->someField[0x3C1] |= 0x20;
    }

    // 0x0803E3B4-0x0803E3C6: Dispatch via sTurnActionsFuncsTable
    gBattleStruct->savedTurnActionNumber = gCurrentTurnActionNumber;

    // sTurnActionsFuncsTable[gCurrentActionFuncId]()  -- BL 0x083458B0
    // This is an indirect call through a function pointer table

    // 0x0803E3CC-0x0803E3D4: Check if all battlers done
    if (gCurrentTurnActionNumber >= gBattlersCount)
    {
        // 0x0803E3D6-0x0803E3F4: Set gBattleMainFunc = sEndTurnFuncsTable[outcome & 0x7F]
        gHitMarker &= ~HITMARKER_UNABLE_TO_USE_MOVE;  // 0xFFEFFFFF
        gBattleMainFunc = sEndTurnFuncsTable[gBattleOutcome & 0x7F];  // at 0x083AD720
    }
    else
    {
        // 0x0803E424-0x0803E43A: Check savedTurnActionNumber changed
        if (gBattleStruct->savedTurnActionNumber != gCurrentTurnActionNumber)
        {
            gHitMarker &= ~HITMARKER_UNABLE_TO_USE_MOVE;  // 0xFFFFFDFF (bit 9)
            gHitMarker &= ~0x00080000;  // HITMARKER_PLAYER_FAINTED? (0xFFF7FFFF)
        }
    }

end:
    return;
}

KEY OBSERVATIONS:
1. This IS RunTurnActionsFunctions — it matches the decomp perfectly!
2. It does NOT check BATTLE_TYPE_LINK directly
3. It does NOT call GetBlockReceivedStatus
4. It does NOT have an infinite loop itself
5. gBattleMainFunc (0x03005D04) is set to sEndTurnFuncsTable[outcome] when done

WHY IT GETS STUCK:
- The function dispatches via sTurnActionsFuncsTable[gCurrentActionFuncId]()
- If the called action function (at 0x083458B0 dispatch) never completes
  (i.e., never increments gCurrentTurnActionNumber), this function loops forever
- The loop is: BattleMainCB2 calls gBattleMainFunc every frame
  -> gBattleMainFunc = RunTurnActionsFunctions
  -> dispatches sTurnActionsFuncsTable[gCurrentActionFuncId]
  -> if that function does nothing (returns immediately due to LINK check),
    gCurrentTurnActionNumber never advances -> bmf stays at RunTurnActionsFunctions

CRITICAL: The action function being dispatched might be checking BATTLE_TYPE_LINK
and blocking there! We need to check what gCurrentActionFuncId value the master has.
""")

    # 9. Check the dispatch function at 0x083458B0
    print("\n## 14. Dispatch function at 0x083458B0")
    quick_disasm(rom, 0x083458B0, 30, "sTurnActionsFuncsTable dispatch (0x083458B0)")

    # 10. Read sTurnActionsFuncsTable entries
    print("\n## 15. sTurnActionsFuncsTable at 0x083AD6C8")
    table_offset = 0x083AD6C8 - 0x08000000
    for i in range(20):
        off = table_offset + i * 4
        if off + 3 < len(rom):
            val = read_u32(rom, off)
            name = addr_name(val)
            print(f"  [{i:2d}] = 0x{val:08X}{name}")

    # 11. Read sEndTurnFuncsTable entries
    print("\n## 16. sEndTurnFuncsTable at 0x083AD720")
    table_offset = 0x083AD720 - 0x08000000
    for i in range(12):
        off = table_offset + i * 4
        if off + 3 < len(rom):
            val = read_u32(rom, off)
            name = addr_name(val)
            print(f"  [{i:2d}] = 0x{val:08X}{name}")

    # 12. Verify: the function at 0x0803E450 — is that what comes after?
    print("\n## 17. Function at 0x0803E450 (right after RunTurnActionsFunctions)")
    quick_disasm(rom, 0x0803E450, 60, "0x0803E450 — next function after target")

    # 13. Check what sets gBattleMainFunc to HTASS (0x0803BE39) — that's the normal path
    print("\n## 18. Where HTASS is set as gBattleMainFunc")
    htass_bytes = struct.pack('<I', 0x0803BE39)
    for off in range(0, min(len(rom), 0x200000), 4):
        if rom[off:off+4] == htass_bytes:
            rom_addr = off + 0x08000000
            # Check if nearby code stores this into gBattleMainFunc
            for check_off in range(max(off - 200, 0), off, 2):
                check_instr = read_u16(rom, check_off)
                if (check_instr >> 11) == 0x9:
                    rd = (check_instr >> 8) & 7
                    imm8 = check_instr & 0xFF
                    pc_val = (check_off + 0x08000000 + 4) & ~3
                    pool = pc_val + imm8 * 4
                    if pool == rom_addr:
                        print(f"  LDR r{rd}, =0x0803BE39 at 0x{check_off + 0x08000000:08X}")
                        # Check if next instruction stores to gBattleMainFunc
                        for store_off in range(check_off + 2, min(check_off + 20, len(rom) - 1), 2):
                            si = read_u16(rom, store_off)
                            # STR rd, [rX, #0]
                            if (si >> 11) == 0xC and (si & 7) == rd:
                                rb = (si >> 3) & 7
                                print(f"    STR r{rd}, [r{rb}] at 0x{store_off + 0x08000000:08X}")

    # 14. Find the action function for B_ACTION_USE_MOVE (index 0)
    print("\n## 19. sTurnActionsFuncsTable[0] = B_ACTION_USE_MOVE handler")
    action0_addr = read_u32(rom, 0x003AD6C8)
    print(f"  Address: 0x{action0_addr:08X}")
    quick_disasm(rom, action0_addr & ~1, 50, f"B_ACTION_USE_MOVE handler at 0x{action0_addr:08X}")

    # 15. Find the action function for B_ACTION_FINISHED (index 12)
    print("\n## 20. sTurnActionsFuncsTable[12] = B_ACTION_FINISHED handler")
    action12_addr = read_u32(rom, 0x003AD6C8 + 12*4)
    print(f"  Address: 0x{action12_addr:08X}")
    quick_disasm(rom, action12_addr & ~1, 30, f"B_ACTION_FINISHED handler at 0x{action12_addr:08X}")


if __name__ == "__main__":
    main()
