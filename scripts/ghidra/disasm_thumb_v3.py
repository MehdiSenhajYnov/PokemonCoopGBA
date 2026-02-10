#!/usr/bin/env python3
"""
THUMB disassembler v3 - targeted analysis of key transition points.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

KNOWN_ADDRS = {
    0x08000544: "SetMainCallback2",
    0x08000578: "SetVBlankCallback",
    0x020090E8: "gBattleTypeFlags",
    0x02020648: "gMain",
    0x0202064C: "gMain.callback2",
    0x020206AE: "gMain.inBattle",
    0x020233DC: "gBattleControllerExecFlags",
    0x020233E0: "gActiveBattler",
    0x02023364: "gBattleTypeFlags_ptr",  # This seems to be a pointer variable
    0x02023A18: "gBattleResources",
    0x02023A95: "gPlayerPartyCount",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x020229E8: "gLinkPlayers",
    0x020239D0: "sBattleStruct?",
    0x0202370E: "gBattleStage/State",
    0x02023716: "gBattleVar2",
    0x02036BB0: "gBattleVar3",
    0x030022C0: "gMain_IWRAM?",
    0x030030FC: "gWirelessCommType",
    0x03003124: "gReceivedRemoteLinkPlayers",
    0x0300307C: "gBlockReceivedStatus",
    0x03005D90: "gRngValue",
    0x080363C1: "CB2_InitBattle",
    0x08036D01: "CB2_InitBattleInternal",
    0x08037B45: "CB2_HandleStartBattle",
    0x0803816D: "stuck_callback2",
    0x08038231: "next_cb2_after_stuck",
    0x08094815: "BattleMainCB2_WRONG",
    0x0806F1D9: "SetUpBattleVars",
    0x0800A4B0: "GetMultiplayerId",
    0x0800A4B1: "GetMultiplayerId",
    0x080069D0: "AnimateSprites",
    0x08006A1C: "BuildOamBuffer",
    0x08004788: "RunTasks",
    0x080BF858: "UpdatePaletteFade",
    0x080C6F84: "RunTextPrinters",
    0x080BFE0C: "BeginNormalPaletteFade?",
    0x080BF910: "BlendPalettes?",
    0x08001AE4: "IsLinkTaskFinished?",
    0x08001B40: "LinkSomething?",
    0x080776D0: "BattleSetup_func?",
    0x0800E120: "LinkRfu_func?",
    0x0800A568: "IsLinkConnected?",
    0x08094AD0: "CalculatePlayerPartyCount?",
}


def read_rom(path):
    with open(path, "rb") as f:
        return f.read()

def u16(rom, offset):
    if 0 <= offset < len(rom) - 1:
        return struct.unpack_from("<H", rom, offset)[0]
    return 0

def u32(rom, offset):
    if 0 <= offset < len(rom) - 3:
        return struct.unpack_from("<I", rom, offset)[0]
    return 0

def gba_to_rom(addr):
    if 0x08000000 <= addr < 0x0A000000:
        return addr - 0x08000000
    return None

def lookup(val):
    for a in [val, val|1, val&~1]:
        if a in KNOWN_ADDRS:
            return KNOWN_ADDRS[a]
    if 0x02000000 <= val < 0x02040000: return f"EWRAM+0x{val-0x02000000:05X}"
    if 0x03000000 <= val < 0x03008000: return f"IWRAM+0x{val-0x03000000:04X}"
    if 0x04000000 <= val < 0x04000400: return f"IO+0x{val-0x04000000:03X}"
    if 0x08000000 <= val < 0x0A000000: return f"ROM+0x{val-0x08000000:06X}"
    return None

def resolve_pool(rom, pc, imm8):
    aligned_pc = (pc + 4) & ~3
    load_addr = aligned_pc + imm8 * 4
    rom_off = gba_to_rom(load_addr)
    if rom_off is not None and 0 <= rom_off < len(rom) - 3:
        return load_addr, u32(rom, rom_off)
    return load_addr, None

def disasm(rom, start_addr, size, label):
    print(f"\n{'='*90}")
    print(f"  {label}")
    print(f"  Address: 0x{start_addr:08X}  Cart0: 0x{start_addr-0x08000000:06X}")
    print(f"{'='*90}\n")

    pc = start_addr
    end = start_addr + size

    while pc < end:
        off = gba_to_rom(pc)
        if off is None or off >= len(rom) - 1:
            break
        hw = u16(rom, off)
        line = ""
        extra = ""

        # BL 32-bit
        if (hw >> 11) == 0x1E and off + 2 < len(rom):
            hw2 = u16(rom, off + 2)
            if (hw2 >> 11) in (0x1F, 0x1D):
                ohi = hw & 0x7FF
                if ohi & 0x400: ohi -= 0x800
                olo = hw2 & 0x7FF
                tgt = ((pc + 4) + (ohi << 12) + (olo << 1)) & 0xFFFFFFFF
                if (hw2 >> 11) == 0x1D: tgt &= 0xFFFFFFFC
                n = lookup(tgt)
                ns = f"  ; {n}" if n else ""
                pfx = "BLX" if (hw2>>11)==0x1D else "BL "
                print(f"  0x{pc:08X}:  {hw:04X} {hw2:04X}  {pfx}     0x{tgt:08X}{ns}")
                pc += 4
                continue

        # PUSH
        if (hw >> 8) == 0xB5:
            regs = [f"R{i}" for i in range(8) if hw&(1<<i)] + ["LR"]
            line = f"PUSH    {{{', '.join(regs)}}}"
        elif (hw >> 8) == 0xB4:
            regs = [f"R{i}" for i in range(8) if hw&(1<<i)]
            line = f"PUSH    {{{', '.join(regs)}}}"
        # POP
        elif (hw >> 8) == 0xBD:
            regs = [f"R{i}" for i in range(8) if hw&(1<<i)] + ["PC"]
            line = f"POP     {{{', '.join(regs)}}}"
            extra = " <<< RETURN"
        elif (hw >> 8) == 0xBC:
            regs = [f"R{i}" for i in range(8) if hw&(1<<i)]
            line = f"POP     {{{', '.join(regs)}}}"
        # BX
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            rn = ["R0","R1","R2","R3","R4","R5","R6","R7","R8","R9","R10","R11","R12","SP","LR","PC"][rm]
            line = f"BX      {rn}"
            if rm == 14: extra = " <<< RETURN"
            if rm == 0: extra = " (indirect jump via R0)"
        # LDR Rd,[PC,#imm]
        elif (hw >> 11) == 0x09:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            la, val = resolve_pool(rom, pc, imm8)
            if val is not None:
                n = lookup(val)
                ns = f"  ({n})" if n else ""
                line = f"LDR     R{rd}, =0x{val:08X}{ns}  ; [0x{la:08X}]"
            else:
                line = f"LDR     R{rd}, [PC, #0x{imm8*4:X}]"
        # LDR Rd,[Rn,#imm]
        elif (hw >> 11) == 0x0D:
            imm = ((hw>>6)&0x1F)*4; rn=(hw>>3)&7; rd=hw&7
            line = f"LDR     R{rd}, [R{rn}, #0x{imm:X}]"
        # LDRB
        elif (hw >> 11) == 0x0F:
            imm = (hw>>6)&0x1F; rn=(hw>>3)&7; rd=hw&7
            line = f"LDRB    R{rd}, [R{rn}, #0x{imm:X}]"
        # LDRH
        elif (hw >> 11) == 0x11:
            imm = ((hw>>6)&0x1F)*2; rn=(hw>>3)&7; rd=hw&7
            line = f"LDRH    R{rd}, [R{rn}, #0x{imm:X}]"
        # STR
        elif (hw >> 11) == 0x0C:
            imm = ((hw>>6)&0x1F)*4; rn=(hw>>3)&7; rd=hw&7
            line = f"STR     R{rd}, [R{rn}, #0x{imm:X}]"
        # STRB
        elif (hw >> 11) == 0x0E:
            imm = (hw>>6)&0x1F; rn=(hw>>3)&7; rd=hw&7
            line = f"STRB    R{rd}, [R{rn}, #0x{imm:X}]"
        # STRH
        elif (hw >> 11) == 0x10:
            imm = ((hw>>6)&0x1F)*2; rn=(hw>>3)&7; rd=hw&7
            line = f"STRH    R{rd}, [R{rn}, #0x{imm:X}]"
        # MOV
        elif (hw >> 11) == 0x04:
            rd=(hw>>8)&7; imm=hw&0xFF
            line = f"MOV     R{rd}, #0x{imm:X}"
        # CMP imm
        elif (hw >> 11) == 0x05:
            rn=(hw>>8)&7; imm=hw&0xFF
            line = f"CMP     R{rn}, #0x{imm:X}"
        # ADD imm8
        elif (hw >> 11) == 0x06:
            rd=(hw>>8)&7; imm=hw&0xFF
            line = f"ADD     R{rd}, #0x{imm:X}"
        # SUB imm8
        elif (hw >> 11) == 0x07:
            rd=(hw>>8)&7; imm=hw&0xFF
            line = f"SUB     R{rd}, #0x{imm:X}"
        # ADD/SUB SP
        elif (hw >> 8) == 0xB0:
            imm = (hw & 0x7F) * 4
            if hw & 0x80: line = f"SUB     SP, #0x{imm:X}"
            else: line = f"ADD     SP, #0x{imm:X}"
        # Cond branch
        elif (hw >> 12) == 0xD:
            cond=(hw>>8)&0xF
            conds=["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE","BAL","SWI"]
            if cond < 15:
                off_val = hw & 0xFF
                if off_val & 0x80: off_val -= 0x100
                tgt = pc + 4 + off_val * 2
                line = f"{conds[cond]:7s} 0x{tgt&0xFFFFFFFF:08X}"
            else:
                line = f"SWI     #0x{hw&0xFF:X}"
        # Uncond branch
        elif (hw >> 11) == 0x1C:
            off_val = hw & 0x7FF
            if off_val & 0x400: off_val -= 0x800
            tgt = pc + 4 + off_val * 2
            line = f"B       0x{tgt&0xFFFFFFFF:08X}"
        # LSL
        elif (hw >> 11) == 0x00:
            imm=(hw>>6)&0x1F; rm=(hw>>3)&7; rd=hw&7
            if hw == 0: line = "NOP"
            else: line = f"LSL     R{rd}, R{rm}, #{imm}"
        # LSR
        elif (hw >> 11) == 0x01:
            imm=(hw>>6)&0x1F; rm=(hw>>3)&7; rd=hw&7
            if imm==0: imm=32
            line = f"LSR     R{rd}, R{rm}, #{imm}"
        # ALU
        elif (hw >> 10) == 0x10:
            op=(hw>>6)&0xF; rs=(hw>>3)&7; rd=hw&7
            ops=["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR","TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            line = f"{ops[op]:7s} R{rd}, R{rs}"
        # Hi reg
        elif (hw >> 10) == 0x11:
            op=(hw>>8)&3; h1=(hw>>7)&1; h2=(hw>>6)&1
            rs=(h2<<3)|((hw>>3)&7); rd=(h1<<3)|(hw&7)
            rn=["R0","R1","R2","R3","R4","R5","R6","R7","R8","R9","R10","R11","R12","SP","LR","PC"]
            if op==0: line=f"ADD     {rn[rd]}, {rn[rs]}"
            elif op==1: line=f"CMP     {rn[rd]}, {rn[rs]}"
            elif op==2: line=f"MOV     {rn[rd]}, {rn[rs]}"
            elif op==3:
                if h1: line=f"BLX     {rn[rs]}"
                else: line=f"BX      {rn[rs]}"
        # ADD 3-reg
        elif (hw >> 9) == 0x0C:
            rm=(hw>>6)&7; rn=(hw>>3)&7; rd=hw&7
            line = f"ADD     R{rd}, R{rn}, R{rm}"
        elif (hw >> 9) == 0x0E:
            imm=(hw>>6)&7; rn=(hw>>3)&7; rd=hw&7
            line = f"ADD     R{rd}, R{rn}, #{imm}"
        elif (hw >> 9) == 0x0F:
            imm=(hw>>6)&7; rn=(hw>>3)&7; rd=hw&7
            line = f"SUB     R{rd}, R{rn}, #{imm}"
        # LDR/STR SP
        elif (hw >> 11) == 0x13:
            rd=(hw>>8)&7; imm=(hw&0xFF)*4
            line = f"LDR     R{rd}, [SP, #0x{imm:X}]"
        elif (hw >> 11) == 0x12:
            rd=(hw>>8)&7; imm=(hw&0xFF)*4
            line = f"STR     R{rd}, [SP, #0x{imm:X}]"
        # LDR/STR reg
        elif (hw >> 9) == 0x2C:
            rm=(hw>>6)&7; rn=(hw>>3)&7; rd=hw&7
            line = f"LDR     R{rd}, [R{rn}, R{rm}]"
        elif (hw >> 9) == 0x28:
            rm=(hw>>6)&7; rn=(hw>>3)&7; rd=hw&7
            line = f"STR     R{rd}, [R{rn}, R{rm}]"
        elif (hw >> 9) == 0x2E:
            rm=(hw>>6)&7; rn=(hw>>3)&7; rd=hw&7
            line = f"LDRB    R{rd}, [R{rn}, R{rm}]"
        elif (hw >> 9) == 0x2A:
            rm=(hw>>6)&7; rn=(hw>>3)&7; rd=hw&7
            line = f"STRB    R{rd}, [R{rn}, R{rm}]"
        # ADD Rd,PC
        elif (hw >> 11) == 0x14:
            rd=(hw>>8)&7; imm=(hw&0xFF)*4
            val = ((pc+4)&~3)+imm
            line = f"ADD     R{rd}, PC, #0x{imm:X}  ; =0x{val:08X}"
        # STMIA/LDMIA
        elif (hw >> 11) == 0x18:
            rn=(hw>>8)&7; mask=hw&0xFF
            regs=[f"R{i}" for i in range(8) if mask&(1<<i)]
            line = f"STMIA   R{rn}!, {{{', '.join(regs)}}}"
        elif (hw >> 11) == 0x19:
            rn=(hw>>8)&7; mask=hw&0xFF
            regs=[f"R{i}" for i in range(8) if mask&(1<<i)]
            line = f"LDMIA   R{rn}!, {{{', '.join(regs)}}}"
        else:
            line = f".hword  0x{hw:04X}"

        if not line:
            line = f".hword  0x{hw:04X}"

        print(f"  0x{pc:08X}:  {hw:04X}      {line}{extra}")
        pc += 2

    print()


def main():
    rom = read_rom(ROM_PATH)
    print(f"ROM: {ROM_PATH} ({len(rom)} bytes)\n")

    # 1. The function that stuck_callback sets via SetMainCallback2
    disasm(rom, 0x08038230, 80, "next_cb2_after_stuck (0x08038231) - what stuck_callback transitions to")

    # 2. Case 10 (0x0A) of CB2_HandleStartBattle - the LAST case, likely the transition to battle
    disasm(rom, 0x08038108, 100, "CB2_HandleStartBattle case 10 (0x08038108) - last case, battle transition?")

    # 3. Case 9 (0x09) of CB2_HandleStartBattle
    disasm(rom, 0x080380B8, 80, "CB2_HandleStartBattle case 9 (0x080380B8)")

    # 4. Case 8 of CB2_HandleStartBattle
    disasm(rom, 0x08038078, 64, "CB2_HandleStartBattle case 8 (0x08038078)")

    # 5. Where 0x0803816D is loaded and SetMainCallback2 is called (the 3 sites in battle area)
    print(f"\n{'='*90}")
    print(f"  WHO SETS callback2 = 0x0803816D (stuck_callback2)?")
    print(f"{'='*90}")

    # Site 1: 0x0803714A (in cb2_during_comm_processing jump table, likely case 0x11 or 0x12)
    disasm(rom, 0x08037130, 80, "Site 1: around 0x0803714A (cb2_during_comm jump table case 0x12)")

    # Site 2: 0x0803770E
    disasm(rom, 0x080376F0, 80, "Site 2: around 0x0803770E")

    # Site 3: 0x08038122 (in CB2_HandleStartBattle case 10)
    # Already covered above

    # 6. The real BattleMainCB2 - check what refs 0x08094815
    # Found at 0x08094806 and 0x08094786
    disasm(rom, 0x08094780, 100, "Code around 0x08094786 (refs 0x08094815 literal pool)")
    disasm(rom, 0x08094800, 32, "Code around 0x08094806 (refs 0x08094815 literal pool)")

    # 7. Let's check if 0x030022C0 is really gMain (IWRAM)
    # gMain is at 0x02020648 (EWRAM). But 0x030022C0 is IWRAM.
    # In pokeemerald-expansion, IntrMain/IntrMain_Intrcheck uses IWRAM
    # Let's check what accesses [0x030022C0 + 0x2C] - that's the vblank counter
    print(f"\n{'='*90}")
    print(f"  ANALYSIS: Key EWRAM variables")
    print(f"{'='*90}\n")

    print("  0x02023364 - loaded by both CB2_HandleStartBattle and cb2_during_comm")
    print("    Both do: LDR R0/R2, =0x02023364 then LDR R1, [R0/R2, #0x0]")
    print("    Then check bit 1 (0x2 = BATTLE_TYPE_LINK)")
    print("    This is likely gBattleTypeFlags (pointer at 0x02023364)")
    print()

    print("  0x0202370E - the state/stage variable")
    print("    CB2_HandleStartBattle: switch on [0x0202370E], 11 cases (0-0xA)")
    print("    cb2_during_comm: switch on [0x0202370E], 19 cases (0-0x12)")
    print("    This is likely gBattleCommunication[0] or a battle setup state counter")
    print()

    print("  0x020239D0 - loaded, then +0x25 = multiplayerId storage")
    print("    Both funcs: GetMultiplayerId() -> store at [0x020239D0 + 0x25]")
    print("    0x020239D0 + 0x25 = 0x020239F5")
    print("    This could be sBattleStruct or gBattleStruct")
    print()

    # 8. Check what 0x08094815 actually is - it stores 0x08007441 into [R2+0x1C]
    # 0x08007441 in literal pool. R2 = R0 (first param). This is a sprite callback.
    # The REAL BattleMainCB2 must be a different function.
    # Let's find it by looking for a function that:
    # 1. Calls AnimateSprites (0x080069D0)
    # 2. Calls BuildOamBuffer (0x08006A1C)
    # 3. Calls RunTasks (0x08004788)
    # 4. Calls UpdatePaletteFade (0x080BF858)
    # 5. Is referenced as a SetMainCallback2 target

    # The stuck_callback2 (0x0803816D) already calls ALL of these!
    # PUSH LR; BL AnimateSprites; BL BuildOamBuffer; BL RunTasks; BL UpdatePaletteFade; BL RunTextPrinters
    # Then checks conditions and may call SetMainCallback2(0x08038231)
    # This IS the battle main loop! It's the "VS screen" callback that runs during battle init.

    print(f"\n{'='*90}")
    print(f"  KEY INSIGHT: 0x0803816D IS the battle main loop callback!")
    print(f"{'='*90}\n")
    print("  0x0803816D calls the standard game loop functions:")
    print("    BL 0x080069D0 (AnimateSprites)")
    print("    BL 0x08006A1C (BuildOamBuffer)")
    print("    BL 0x08004788 (RunTasks)")
    print("    BL 0x080BF858 (UpdatePaletteFade)")
    print("    BL 0x080C6F84 (RunTextPrinters)")
    print()
    print("  Then it checks three conditions:")
    print("    1. [0x030022C0 + 0x2C] & 0x2 != 0  (VBlank flag?)")
    print("    2. [*0x02023364] & 0x01000000 != 0  (gBattleTypeFlags & BATTLE_TYPE_LINK)")
    print("    3. BL 0x081B7724 returns nonzero     (IsLinkBattleReady?)")
    print()
    print("  If ALL three pass:")
    print("    - Store 5 to [0x02023716] and [0x02036BB0]")
    print("    - BL 0x080BFE0C (BeginNormalPaletteFade)")
    print("    - BL 0x080BF910 (BlendPalettes)")
    print("    - SetMainCallback2(0x08038231)")
    print()
    print("  0x08038231 is the NEXT callback in the chain.")
    print("  If conditions DON'T pass, the function just returns (loops).")
    print()
    print("  THE PROBLEM: One of the three conditions is failing!")
    print("    - Condition 1: VBlank flag - should be set by hardware")
    print("    - Condition 2: BATTLE_TYPE_LINK flag check")
    print("    - Condition 3: 0x081B7724 (link-related check)")
    print()
    print("  Since this is link battle emulation and we're patching link functions,")
    print("  conditions 2 or 3 are likely failing because the link state isn't")
    print("  properly emulated.")

    # 9. Disassemble the check function at 0x081B7724
    disasm(rom, 0x081B7724, 48, "0x081B7724 - link check function called from stuck_callback")

    # 10. Compute the constant: 0x80 << 17 = ?
    val = 0x80 << 17
    print(f"\n  NOTE: 0x80 << 17 = 0x{val:08X} = {val}")
    print(f"  This is bit 24 = 0x01000000")
    print(f"  BATTLE_TYPE_LINK = 0x02 (bit 1)")
    print(f"  But the check is for bit 24... Let me check the vanilla constants:")
    print(f"  BATTLE_TYPE_MULTI = 0x40, BATTLE_TYPE_RECORDED_LINK = 0x01000000")
    print(f"  So the stuck callback checks BATTLE_TYPE_RECORDED_LINK (0x01000000)")
    print(f"  NOT BATTLE_TYPE_LINK (0x02)!")
    print()
    print(f"  Wait - 0x02023364 is NOT gBattleTypeFlags directly.")
    print(f"  The code does: LDR R0, =0x02023364; LDR R0, [R0, #0x0]")
    print(f"  So it reads a POINTER at 0x02023364 and dereferences it.")
    print(f"  0x02023364 might be gBattleTypeFlags_ptr or gBattlescriptCurrInstr?")
    print()

    # 11. Check the battle_type_flags constant check more carefully
    # In CB2_HandleStartBattle case 1 (0x08037BF8):
    # LDR R2, =0x02023364; LDR R1, [R2, #0x0]; check bit 1
    # So [0x02023364] is read as u32 and bit 1 checked
    # In stuck_callback:
    # LDR R0, =0x02023364; LDR R0, [R0, #0x0]; check bit 24 (0x01000000)
    # So it's the SAME variable but different bit checks
    print(f"  Actually: 0x02023364 appears to contain the battle type flags directly")
    print(f"  (not a pointer). The code does LDR R0, [ptr], then checks bits.")
    print(f"  CB2_HandleStartBattle checks bit 1 (BATTLE_TYPE_LINK)")
    print(f"  stuck_callback checks bit 24 (BATTLE_TYPE_RECORDED_LINK? or custom)")
    print()

    # Wait, let me re-read the stuck callback more carefully
    # LDR R0, [PC, #0x44] -> loads 0x02023364
    # LDR R0, [R0, #0x0]  -> loads *0x02023364 (this IS a dereference)
    # So if 0x02023364 contains the flags directly (e.g. value 0x020002)
    # then it checks if 0x020002 & 0x01000000 which would be FALSE
    # But if 0x02023364 is a pointer to the flags...

    # Actually, gBattleTypeFlags is at 0x020090E8 per the config.
    # But the code references 0x02023364.
    # Let me check: could 0x02023364 be a pointer variable that POINTS to the flags?
    # Or is this NOT gBattleTypeFlags at all?

    # The config says gBattleTypeFlags = 0x020090E8
    # Let's search for 0x020090E8 in ROM literal pools near the battle code
    print(f"\n--- Searching for 0x020090E8 (gBattleTypeFlags) in ROM near battle code ---")
    target = struct.pack("<I", 0x020090E8)
    for off in range(0x036000, min(0x03A000, len(rom) - 3), 4):
        if rom[off:off+4] == target:
            print(f"  Found at ROM 0x{off:06X} (GBA: 0x{0x08000000+off:08X})")

    # Also search wider
    print(f"\n  Wider search (0x000000-0x200000):")
    count = 0
    for off in range(0, min(0x200000, len(rom) - 3), 4):
        if rom[off:off+4] == target:
            if count < 20:
                print(f"  Found at ROM 0x{off:06X} (GBA: 0x{0x08000000+off:08X})")
            count += 1
    print(f"  Total: {count} occurrences")


if __name__ == "__main__":
    main()
