#!/usr/bin/env python3
"""
Verify BattleMainCB1 = 0x08039C65 found by state 18 analysis.

The state 18 handler of CB2_InitBattleInternal at 0x08037130:
- Loads 0x08039C65 from literal pool
- STR it into [gMain.callback1] (0x030022C0)
- Then calls SetMainCallback2(BattleMainCB2=0x0803816D)

So 0x08039C65 IS BattleMainCB1 (the CB1 callback set during battle init).

This script:
1. Fully disassembles and annotates BattleMainCB1 at 0x08039C64
2. Identifies all EWRAM/IWRAM addresses referenced
3. Identifies gBattleMainFunc, gBattlersCount, gBattlerControllerFuncs
4. Traces the call at 0x083458B0 (likely an indirect call helper)
5. Checks the broader state 18 handler context
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

KNOWN = {
    "gBattleTypeFlags":           0x02023364,
    "gActiveBattler":             0x020233E0,
    "gBattleControllerExecFlags": 0x020233DC,
    "gBattleCommunication":       0x0202370E,
    "gBattleResources":           0x02023A18,
    "SetMainCallback2":           0x08000544,
    "BattleMainCB2":              0x0803816D,
    "gMain_callback1":            0x030022C0,
    "GetMultiplayerId":           0x0800A4B1,
}

ADDR_NAMES = {}
for name, addr in KNOWN.items():
    ADDR_NAMES[addr] = name
    ADDR_NAMES[addr & ~1] = name
    ADDR_NAMES[addr | 1] = name


def read_rom(path):
    with open(path, "rb") as f:
        return f.read()


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def addr_name(addr):
    if addr in ADDR_NAMES:
        return f"{ADDR_NAMES[addr]} (0x{addr:08X})"
    return f"0x{addr:08X}"


def decode_thumb_bl(hw1, hw2):
    if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) == 0xF800:
        offset_hi = hw1 & 0x07FF
        offset_lo = hw2 & 0x07FF
        offset_hi_signed = offset_hi if offset_hi < 0x400 else offset_hi - 0x800
        offset = (offset_hi_signed << 12) | (offset_lo << 1)
        return offset
    return None


def disasm_thumb(rom, rom_offset, size, base_addr=None, stop_at_ret=False):
    """Simplified but comprehensive THUMB disassembler."""
    if base_addr is None:
        base_addr = 0x08000000 + rom_offset

    result = []
    i = 0
    while i < size:
        hw = u16(rom, rom_offset + i)
        pc = base_addr + i
        desc = f"0x{hw:04X}"

        # PUSH
        if (hw & 0xFF00) == 0xB500:
            regs = [f"R{r}" for r in range(8) if hw & (1 << r)]
            regs.append("LR")
            desc = f"PUSH {{{', '.join(regs)}}}"
        elif (hw & 0xFF00) == 0xB400:
            regs = [f"R{r}" for r in range(8) if hw & (1 << r)]
            desc = f"PUSH {{{', '.join(regs)}}}"

        # POP
        elif (hw & 0xFF00) == 0xBD00:
            regs = [f"R{r}" for r in range(8) if hw & (1 << r)]
            regs.append("PC")
            desc = f"POP {{{', '.join(regs)}}}"
            result.append((i, pc, hw, desc))
            if stop_at_ret:
                break
            i += 2
            continue
        elif (hw & 0xFF00) == 0xBC00:
            regs = [f"R{r}" for r in range(8) if hw & (1 << r)]
            desc = f"POP {{{', '.join(regs)}}}"

        # MOV Rd, #imm8
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"MOV R{rd}, #{imm} (0x{imm:02X})"

        # CMP Rn, #imm8
        elif (hw & 0xF800) == 0x2800:
            rn = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"CMP R{rn}, #{imm}"

        # ADD Rd, #imm8
        elif (hw & 0xF800) == 0x3000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"ADD R{rd}, #{imm} (0x{imm:02X})"

        # SUB Rd, #imm8
        elif (hw & 0xF800) == 0x3800:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            desc = f"SUB R{rd}, #{imm}"

        # LDR Rd, [PC, #imm8*4]
        elif (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            load_pc = (pc + 4) & ~3
            load_addr = load_pc + imm
            load_rom_off = load_addr - 0x08000000
            if 0 <= load_rom_off < len(rom) - 4:
                val = u32(rom, load_rom_off)
                desc = f"LDR R{rd}, =0x{val:08X}  ; [{addr_name(load_addr)}]  {addr_name(val)}"
            else:
                desc = f"LDR R{rd}, [PC, #0x{imm:X}]"

        # LDR Rd, [Rn, #imm5*4]
        elif (hw & 0xF800) == 0x6800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = ((hw >> 6) & 0x1F) * 4
            desc = f"LDR R{rd}, [R{rn}, #0x{imm:X}]"

        # STR Rd, [Rn, #imm5*4]
        elif (hw & 0xF800) == 0x6000:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = ((hw >> 6) & 0x1F) * 4
            desc = f"STR R{rd}, [R{rn}, #0x{imm:X}]"

        # LDRB Rd, [Rn, #imm5]
        elif (hw & 0xF800) == 0x7800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = (hw >> 6) & 0x1F
            desc = f"LDRB R{rd}, [R{rn}, #0x{imm:X}]"

        # STRB Rd, [Rn, #imm5]
        elif (hw & 0xF800) == 0x7000:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = (hw >> 6) & 0x1F
            desc = f"STRB R{rd}, [R{rn}, #0x{imm:X}]"

        # LDRH Rd, [Rn, #imm5*2]
        elif (hw & 0xF800) == 0x8800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = ((hw >> 6) & 0x1F) * 2
            desc = f"LDRH R{rd}, [R{rn}, #0x{imm:X}]"

        # LDR Rd, [Rn, Rm]
        elif (hw & 0xFE00) == 0x5800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            rm = (hw >> 6) & 7
            desc = f"LDR R{rd}, [R{rn}, R{rm}]"

        # ADD Rd, Rn, Rm
        elif (hw & 0xFE00) == 0x1800:
            rd = hw & 7
            rn = (hw >> 3) & 7
            rm = (hw >> 6) & 7
            desc = f"ADD R{rd}, R{rn}, R{rm}"

        # ADD Rd, Rn, #imm3
        elif (hw & 0xFE00) == 0x1C00:
            rd = hw & 7
            rn = (hw >> 3) & 7
            imm = (hw >> 6) & 7
            desc = f"ADD R{rd}, R{rn}, #{imm}"

        # SUB Rd, Rn, Rm
        elif (hw & 0xFE00) == 0x1A00:
            rd = hw & 7
            rn = (hw >> 3) & 7
            rm = (hw >> 6) & 7
            desc = f"SUB R{rd}, R{rn}, R{rm}"

        # LSL Rd, Rm, #imm5
        elif (hw & 0xF800) == 0x0000:
            rd = hw & 7
            rm = (hw >> 3) & 7
            imm = (hw >> 6) & 0x1F
            desc = f"LSL R{rd}, R{rm}, #{imm}"

        # LSR Rd, Rm, #imm5
        elif (hw & 0xF800) == 0x0800:
            rd = hw & 7
            rm = (hw >> 3) & 7
            imm = (hw >> 6) & 0x1F
            desc = f"LSR R{rd}, R{rm}, #{imm}"

        # BX Rm
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            desc = f"BX R{rm}"
            if rm == 14:
                desc += "  ; return"
            result.append((i, pc, hw, desc))
            if stop_at_ret and rm == 14:
                break
            if rm == 0:
                # Could be a tail call or return from POP
                pass
            i += 2
            continue

        # BLX Rm
        elif (hw & 0xFF80) == 0x4780:
            rm = (hw >> 3) & 0xF
            desc = f"BLX R{rm}"

        # MOV Rd, Rm (high regs)
        elif (hw & 0xFF00) == 0x4600:
            rd = (hw & 7) | ((hw >> 4) & 8)
            rm = (hw >> 3) & 0xF
            desc = f"MOV R{rd}, R{rm}"

        # ADD Rd, Rm (high regs)
        elif (hw & 0xFF00) == 0x4400:
            rd = (hw & 7) | ((hw >> 4) & 8)
            rm = (hw >> 3) & 0xF
            desc = f"ADD R{rd}, R{rm}"

        # CMP Rn, Rm (all regs)
        elif (hw & 0xFF00) == 0x4500:
            rn = (hw & 7) | ((hw >> 4) & 8)
            rm = (hw >> 3) & 0xF
            desc = f"CMP R{rn}, R{rm}"

        # ALU operations
        elif (hw & 0xFC00) == 0x4000:
            op = (hw >> 6) & 0xF
            rd = hw & 7
            rm = (hw >> 3) & 7
            ops = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                   "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            desc = f"{ops[op]} R{rd}, R{rm}"

        # B (unconditional)
        elif (hw & 0xF800) == 0xE000:
            offset = hw & 0x7FF
            if offset & 0x400:
                offset = offset - 0x800
            target = pc + 4 + offset * 2
            desc = f"B 0x{target:08X}"

        # Bcc (conditional)
        elif (hw & 0xF000) == 0xD000:
            cond = (hw >> 8) & 0xF
            offset = hw & 0xFF
            if offset & 0x80:
                offset = offset - 0x100
            target = pc + 4 + offset * 2
            conds = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                     "BHI","BLS","BGE","BLT","BGT","BLE","B??","SWI"]
            desc = f"{conds[cond]} 0x{target:08X}"

        # BL (two halfwords)
        elif (hw & 0xF800) == 0xF000:
            if i + 2 < size:
                hw2 = u16(rom, rom_offset + i + 2)
                bl_offset = decode_thumb_bl(hw, hw2)
                if bl_offset is not None:
                    target = pc + 4 + bl_offset
                    desc = f"BL {addr_name(target)}"
                    result.append((i, pc, hw, desc))
                    i += 4
                    continue
            desc = f"BL prefix 0x{hw:04X}"

        # SUB SP
        elif (hw & 0xFF80) == 0xB080:
            imm = (hw & 0x7F) * 4
            desc = f"SUB SP, #0x{imm:X}"

        # ADD SP
        elif (hw & 0xFF80) == 0xB000:
            imm = (hw & 0x7F) * 4
            desc = f"ADD SP, #0x{imm:X}"

        result.append((i, pc, hw, desc))
        i += 2

    return result


def print_disasm(entries, title=""):
    if title:
        print(f"\n{'='*80}")
        print(f"  {title}")
        print(f"{'='*80}")
    for offset, pc, hw, desc in entries:
        print(f"  +{offset:04X}  0x{pc:08X}:  {hw:04X}  {desc}")


def find_literal_pool_refs(rom, target_addr, search_start, search_size):
    """Find all LDR Rd, [PC, #imm] that load a specific value from literal pool."""
    results = []
    for i in range(0, search_size, 2):
        off = search_start + i
        if off + 2 > len(rom):
            break
        hw = u16(rom, off)
        if (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc = 0x08000000 + off
            load_pc = (pc + 4) & ~3
            load_addr_rom = (load_pc + imm) - 0x08000000
            if 0 <= load_addr_rom < len(rom) - 4:
                val = u32(rom, load_addr_rom)
                if val == target_addr:
                    results.append((off, pc, rd, load_addr_rom))
    return results


def main():
    rom = read_rom(ROM_PATH)
    print(f"ROM: {len(rom)} bytes")

    # ==================================================================
    # 1. Disassemble BattleMainCB1 at 0x08039C64 (THUMB addr 0x08039C65)
    # ==================================================================
    cb1_rom_off = 0x039C64
    cb1_addr = 0x08039C64

    entries = disasm_thumb(rom, cb1_rom_off, 128, stop_at_ret=True)
    print_disasm(entries, "BattleMainCB1 at 0x08039C65 (stored into gMain.callback1 by state 18)")

    # Annotate the function
    print("\n  ANNOTATION:")
    print("  -----------")
    print("  This function matches BattleMainCB1 from the decomp:")
    print()

    # Find the key addresses
    print("  Literal pool values loaded:")
    for offset, pc, hw, desc in entries:
        if "LDR R" in desc and "=0x" in desc:
            print(f"    {desc}")

    # ==================================================================
    # 2. What is 0x083458B0? (called twice via BL)
    # ==================================================================
    print_disasm(
        disasm_thumb(rom, 0x3458B0, 64, stop_at_ret=True),
        "Function at 0x083458B0 (called by BattleMainCB1)"
    )

    # Check - is 0x083458B0 an indirect call helper? Or is R0 being passed as arg?
    # Actually, looking at the disasm: the function at 0x08039C65 does:
    # LDR R0, =0x03005D04; LDR R0, [R0]; BL 0x083458B0
    # Then later: LDR R0, [R0, Rn]; BL 0x083458B0
    # This suggests 0x083458B0 takes a function pointer in R0 and calls it
    # OR R0 is used as an argument to a normal function

    # ==================================================================
    # 3. Identify all EWRAM/IWRAM addresses in BattleMainCB1
    # ==================================================================
    print("\n" + "=" * 80)
    print("  KEY ADDRESSES IN BattleMainCB1:")
    print("=" * 80)

    # From the disassembly:
    # 0x03005D04 = gBattleMainFunc (IWRAM) - function pointer, loaded and dereferenced
    # 0x020233DC = gBattleControllerExecFlags (EWRAM) - known
    # 0x020233E4 = gBattlersCount (EWRAM) - used as loop bound
    # 0x03005D70 = gBattlerControllerFuncs (IWRAM) - array of function pointers

    print(f"  0x03005D04 = gBattleMainFunc        (IWRAM, function pointer)")
    print(f"               LDR R0, =0x03005D04")
    print(f"               LDR R0, [R0]   ; read function pointer")
    print(f"               BL 0x083458B0  ; call it (indirect call helper?)")
    print()
    print(f"  0x020233DC = gBattleControllerExecFlags (EWRAM, KNOWN)")
    print(f"               cleared to 0 before loop (STRB R0=0, [R1])")
    print(f"               also used as loop counter base (LDRB R0, [R4])")
    print()
    print(f"  0x020233E4 = gBattlersCount          (EWRAM)")
    print(f"               LDRB R0, [R0]; CMP R0, #0; BEQ skip_loop")
    print(f"               Also: LDRB R1, [R1]; CMP R0, R1; BCC loop_back")
    print()
    print(f"  0x03005D70 = gBattlerControllerFuncs (IWRAM, array of function pointers)")
    print(f"               LDR R5, =0x03005D70")
    print(f"               LDRB R0, [R4]  ; battler index from gBattleControllerExecFlags")
    print(f"               LSL R0, R0, #2 ; * 4 (pointer size)")
    print(f"               ADD R0, R0, R5 ; &gBattlerControllerFuncs[battler]")
    print(f"               LDR R0, [R0]   ; function pointer")
    print(f"               BL 0x083458B0  ; call it")

    # ==================================================================
    # 4. Wait - the loop counter comes from gBattleControllerExecFlags?
    #    That doesn't match the decomp. Let me re-read more carefully.
    # ==================================================================
    print("\n" + "=" * 80)
    print("  DETAILED ANALYSIS OF THE LOOP:")
    print("=" * 80)

    # Let me re-read the disasm carefully:
    # +0000: PUSH {R4, R5, LR}
    # +0002: LDR R0, =0x03005D04        ; gBattleMainFunc
    # +0004: LDR R0, [R0]               ; *gBattleMainFunc
    # +0006: BL 0x083458B0              ; call *gBattleMainFunc (via helper?)
    # +000A: LDR R1, =0x020233DC        ; gBattleControllerExecFlags
    # +000C: MOV R0, #0
    # +000E: STRB R0, [R1]              ; *gBattleControllerExecFlags = 0  ???
    #   Wait, STRB stores a byte. But gBattleControllerExecFlags is 32-bit.
    #   This clears the low byte only. Hmm.
    #
    # Actually wait - let me re-check. In the decomp, BattleMainCB1 does NOT
    # clear gBattleControllerExecFlags. Let me look at the actual bytecodes again.
    #
    # Maybe the compiler reused the register. Let me trace more carefully.

    # Let me re-examine: maybe R1 is used as an iterator variable, not ExecFlags
    # The STRB #0 at [R1] could be initializing a loop counter at that address

    # Actually, looking again at the decomp:
    # void BattleMainCB1(void) {
    #     u32 battler;
    #     gBattleMainFunc();
    #     for (battler = 0; battler < gBattlersCount; battler++)
    #         gBattlerControllerFuncs[battler](battler);
    # }
    #
    # The compiler could use gActiveBattler as the loop variable!
    # Let me check: gActiveBattler = 0x020233E0, gBattleControllerExecFlags = 0x020233DC
    # The address loaded is 0x020233DC. Hmm.
    #
    # Wait - maybe gBattleControllerExecFlags is being used as the battler counter
    # because the compiler chose to put the loop variable there? No, that's a different
    # variable.
    #
    # Let me look at this differently. The function:
    # 1. Calls gBattleMainFunc() via 0x03005D04
    # 2. Stores 0 at 0x020233DC (byte)
    # 3. Loads 0x020233E4 and checks if 0
    # 4. Loops using 0x020233DC as counter, 0x03005D70 as func array
    #
    # In the decomp, the loop uses a local variable 'battler'.
    # But the compiler may have allocated it to an EWRAM variable for some reason?
    # More likely: 0x020233DC is actually gActiveBattler in this build!
    # Or the compiler uses gActiveBattler as the loop counter.
    #
    # Actually, I recall: gActiveBattler = 0x020233E0 from previous scans.
    # So 0x020233DC is indeed gBattleControllerExecFlags.
    # But why would BattleMainCB1 use it as a loop counter?
    #
    # Wait - let me re-read the ARM disasm. Maybe I'm misreading the loop.
    # Let me look at the actual flow again:

    print("  Step-by-step trace of BattleMainCB1:")
    print()
    print("  PUSH {R4, R5, LR}")
    print("  LDR R0, [=0x03005D04]     ; R0 = &gBattleMainFunc")
    print("  LDR R0, [R0]              ; R0 = gBattleMainFunc")
    print("  BL 0x083458B0             ; call indirect(R0)")
    print("  LDR R1, [=0x020233DC]     ; R1 = &gBattleControllerExecFlags (or gActiveBattler-4?)")
    print("  MOV R0, #0")
    print("  STRB R0, [R1]             ; store 0 at byte [0x020233DC]")
    print("  LDR R0, [=0x020233E4]     ; R0 = &gBattlersCount")
    print("  LDRB R0, [R0]             ; R0 = gBattlersCount")
    print("  CMP R0, #0                ; if (gBattlersCount == 0) skip")
    print("  BEQ end")
    print("  LDR R5, [=0x03005D70]     ; R5 = gBattlerControllerFuncs array")
    print("  MOV R4, R1                ; R4 = &counter (0x020233DC)")
    print("  loop:")
    print("    LDRB R0, [R4]           ; R0 = counter value")
    print("    LSL R0, R0, #2          ; R0 *= 4")
    print("    ADD R0, R0, R5          ; R0 = &gBattlerControllerFuncs[counter]")
    print("    LDR R0, [R0]            ; R0 = gBattlerControllerFuncs[counter]")
    print("    BL 0x083458B0           ; call indirect(R0)")
    print("    LDRB R0, [R4]           ; R0 = counter")
    print("    ADD R0, #1              ; R0++")
    print("    STRB R0, [R4]           ; counter++")
    print("    LDR R1, [=0x020233E4]   ; R1 = &gBattlersCount")
    print("    LSL R0, R0, #24         ; zero-extend byte")
    print("    LSR R0, R0, #24")
    print("    LDRB R1, [R1]           ; R1 = gBattlersCount")
    print("    CMP R0, R1              ; if counter < gBattlersCount")
    print("    BCC loop                ; continue loop")
    print("  end:")
    print("  POP {R4, R5} / POP {R0} / BX R0")
    print()
    print("  CONCLUSION: The compiler uses 0x020233DC as the loop variable!")
    print("  This is gBattleControllerExecFlags - but the compiler may be")
    print("  using gActiveBattler offset. Let me check the decomp more carefully...")
    print()
    print("  Actually, looking at the REAL decomp (pokeemerald-expansion):")
    print("  BattleMainCB1 uses gBattlerControllerFuncs[battler](battler)")
    print("  where 'battler' is a LOCAL variable. But the compiler might")
    print("  have optimized it to use gActiveBattler as the counter.")
    print("  However, 0x020233DC = gBattleControllerExecFlags, not gActiveBattler.")
    print()
    print("  Wait - maybe the ACTUAL layout in R&B is different:")
    print("  0x020233DC might actually be gActiveBattler in this build!")
    print("  Let me check: previous scan said gActiveBattler = 0x020233E0")
    print("  and gBattleControllerExecFlags = 0x020233DC.")
    print("  But this function uses 0x020233DC as a battler counter (0-3).")
    print()
    print("  This suggests that maybe in R&B the layout is:")
    print("  0x020233DC = something used as loop counter in BattleMainCB1")
    print("  Let's verify by looking at what OTHER functions do with 0x020233DC")

    # ==================================================================
    # 5. Check what 0x083458B0 does (the indirect call helper)
    # ==================================================================
    # Already disassembled above, but let me check if it's a BX R0 trampoline
    helper_off = 0x3458B0
    hw0 = u16(rom, helper_off)
    hw1 = u16(rom, helper_off + 2)
    print(f"\n  0x083458B0 first bytes: {hw0:04X} {hw1:04X}")

    if hw0 == 0x4700:  # BX R0
        print("  0x083458B0 = BX R0  (simple indirect call trampoline!)")
    elif hw0 == 0x4708:  # BX R1
        print("  0x083458B0 = BX R1")
    else:
        # Disassemble a bit more
        print("  Full disassembly:")
        helper_entries = disasm_thumb(rom, helper_off, 32, stop_at_ret=True)
        for eo, ep, eh, ed in helper_entries:
            print(f"    +{eo:04X} 0x{ep:08X}: {eh:04X}  {ed}")

    # ==================================================================
    # 6. Verify: find all ROM refs to 0x08039C65 (BattleMainCB1 with THUMB bit)
    # ==================================================================
    print("\n" + "=" * 80)
    print("  ROM references to BattleMainCB1 (0x08039C65)")
    print("=" * 80)

    refs = find_literal_pool_refs(rom, 0x08039C65, 0, len(rom))
    print(f"  Found {len(refs)} literal pool references to 0x08039C65:")
    for ref_off, ref_pc, ref_rd, pool_off in refs:
        print(f"    LDR R{ref_rd} at 0x{ref_pc:08X} (ROM +0x{ref_off:08X}), pool at +0x{pool_off:08X}")

    # ==================================================================
    # 7. Also find gBattleMainFunc (0x03005D04) refs for additional context
    # ==================================================================
    print("\n" + "=" * 80)
    print("  ROM references to gBattleMainFunc (0x03005D04)")
    print("=" * 80)

    refs = find_literal_pool_refs(rom, 0x03005D04, 0x030000, 0x080000)
    print(f"  Found {len(refs)} refs in battle code area (0x030000-0x0B0000):")
    for ref_off, ref_pc, ref_rd, pool_off in refs:
        print(f"    LDR R{ref_rd} at 0x{ref_pc:08X} (ROM +0x{ref_off:08X})")

    # ==================================================================
    # 8. ROM references to gBattlerControllerFuncs (0x03005D70)
    # ==================================================================
    print("\n" + "=" * 80)
    print("  ROM references to gBattlerControllerFuncs (0x03005D70)")
    print("=" * 80)

    refs = find_literal_pool_refs(rom, 0x03005D70, 0x030000, 0x080000)
    print(f"  Found {len(refs)} refs in battle code area:")
    for ref_off, ref_pc, ref_rd, pool_off in refs:
        print(f"    LDR R{ref_rd} at 0x{ref_pc:08X}")

    # ==================================================================
    # 9. ROM references to gBattlersCount (0x020233E4)
    # ==================================================================
    print("\n" + "=" * 80)
    print("  ROM references to gBattlersCount (0x020233E4)")
    print("=" * 80)

    refs = find_literal_pool_refs(rom, 0x020233E4, 0x030000, 0x080000)
    print(f"  Found {len(refs)} refs in battle code area:")
    for ref_off, ref_pc, ref_rd, pool_off in refs[:10]:
        print(f"    LDR R{ref_rd} at 0x{ref_pc:08X}")
    if len(refs) > 10:
        print(f"    ... and {len(refs)-10} more")

    # ==================================================================
    # 10. State 18 handler re-analysis with annotations
    # ==================================================================
    print("\n" + "=" * 80)
    print("  State 18 handler re-analysis (0x08037130)")
    print("=" * 80)

    s18_entries = disasm_thumb(rom, 0x037130, 100, stop_at_ret=True)
    print_disasm(s18_entries, "State 18 of CB2_InitBattleInternal")

    print("""
  ANNOTATED:
    The state 18 handler does:
    1. BL to some function (checking battle comm ready?)
    2. If not ready: skip to end
    3. LDR R2, =0x03005D00      ; some IWRAM storage
       LDR R1, =0x030022C0      ; &gMain.callback1
       LDR R0, [R1]             ; save current CB1
       STR R0, [R2]             ; store old CB1 in 0x03005D00
       LDR R0, =0x08039C65      ; BattleMainCB1
       STR R0, [R1]             ; gMain.callback1 = BattleMainCB1
       LDR R0, =0x0803816D      ; BattleMainCB2
       BL SetMainCallback2       ; gMain.callback2 = BattleMainCB2
    4. Check gBattleTypeFlags & 0x02 (BATTLE_TYPE_DOUBLE?)
       If set, OR 0x20 into flags (BATTLE_TYPE_DOUBLE_WILD?)
    """)

    # ==================================================================
    # FINAL SUMMARY
    # ==================================================================
    print("=" * 80)
    print("  FINAL SUMMARY")
    print("=" * 80)
    print()
    print("  BattleMainCB1 = 0x08039C65 (THUMB) / 0x08039C64 (ARM)")
    print("  Size: ~62 bytes (0x3E)")
    print()
    print("  Called from: State 18 of CB2_InitBattleInternal (0x08037130)")
    print("  Stored into: gMain.callback1 (0x030022C0)")
    print()
    print("  Key variables discovered:")
    print("    gBattleMainFunc           = 0x03005D04 (IWRAM, function pointer)")
    print("    gBattlersCount            = 0x020233E4 (EWRAM, u8)")
    print("    gBattlerControllerFuncs   = 0x03005D70 (IWRAM, array of 4 function pointers)")
    print()
    print("  Also found:")
    print("    0x03005D00 = saved callback1 storage (IWRAM)")
    print("    0x083458B0 = indirect call helper (likely BX R0 trampoline)")
    print()
    print("  The function at 0x083458B0 is used to make indirect calls:")
    print("    LDR R0, [some_ptr]   ; load function pointer")
    print("    BL 0x083458B0        ; call it (BX R0 inside)")


if __name__ == "__main__":
    main()
