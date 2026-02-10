"""
Identify the function at THUMB address 0x0807DC45 (ROM offset 0x07DC44) in Run & Bun ROM.

This script:
1. Disassembles the function at 0x07DC44 (first 100+ bytes)
2. Checks for BufferRunCommand patterns (gBattleControllerExecFlags, gBattleResources, CMP #N)
3. Scans the literal pool for the command table pointer
4. Compares structure with known LinkOpponentBufferRunCommand at 0x0807793C
5. Searches ROM for references to 0x0807DC45 (SetControllerTo... functions)
6. Compares command tables to identify which controller type this is

Known controller types from pokeemerald-expansion:
  - Player, Opponent, LinkOpponent, LinkPartner
  - RecordedOpponent, RecordedPlayer, RecordedPartner
  - Wally, Safari
"""

import struct
import os
import sys

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

# Known addresses in Run & Bun
KNOWN_SYMBOLS = {
    0x020233E0: "gBattleControllerExecFlags",
    0x02023364: "gBattleTypeFlags",
    0x0202370E: "gBattleCommunication",
    0x020233FC: "gBattleMons",
    0x03005D70: "gBattlerControllerFuncs",
    0x020233DC: "gActiveBattler_or_similar",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x02023A18: "gBattleResources_ptr",
    0x02023A40: "gBattleResources_ptr_alt",
    0x081BAD85: "OpponentBufferRunCommand",
    0x0807793D: "LinkOpponentBufferRunCommand (confirmed)",
    0x0807DC45: "TARGET FUNCTION (0x0807DC45)",
    0x08078789: "LinkOpponentBufferExecCompleted",
    0x08000544: "SetMainCallback2",
    0x080363C1: "CB2_InitBattle",
    0x0803648D: "CB2_InitBattleInternal",
    0x08094815: "CB2_BattleMain",
    0x0803816D: "BattleMainCB2",
    0x083458B0: "function_call_trampoline",
}

# All known BufferRunCommand addresses for cross-reference
KNOWN_BUFFER_RUN_COMMANDS = {
    0x081BAD85: "OpponentBufferRunCommand",
    0x0807793D: "LinkOpponentBufferRunCommand",
    0x0806F151: "PlayerBufferRunCommand",
}


def read_u32(rom, file_offset):
    return struct.unpack_from("<I", rom, file_offset)[0]


def read_u16(rom, file_offset):
    return struct.unpack_from("<H", rom, file_offset)[0]


def annotate(val):
    if val in KNOWN_SYMBOLS:
        return KNOWN_SYMBOLS[val]
    # THUMB address (clear bit 0)
    if (val | 1) in KNOWN_SYMBOLS:
        return KNOWN_SYMBOLS[val | 1]
    if (val & ~1) in KNOWN_SYMBOLS:
        return KNOWN_SYMBOLS[val & ~1]
    return ""


def resolve_literal(rom, rom_addr):
    """Read 32-bit value from ROM at the given GBA address."""
    off = rom_addr - 0x08000000
    if 0 <= off < len(rom) - 3:
        return read_u32(rom, off)
    return None


def disasm_thumb(rom, rom_addr, size, label):
    """Full annotated THUMB disassembly."""
    file_off = rom_addr - 0x08000000
    data = rom[file_off:file_off + size]

    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"  Address: 0x{rom_addr:08X} (THUMB: 0x{rom_addr|1:08X}), ROM offset: 0x{file_off:06X}")
    print(f"  Size: {size} bytes")
    print(f"{'='*80}")

    # Raw hex dump
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        print(f"  0x{rom_addr+i:08X}: {hex_str}")
    print()

    # Instruction-by-instruction
    ldr_pool_refs = []  # (addr, rd, pool_addr, pool_val)
    i = 0
    while i < len(data) - 1:
        addr = rom_addr + i
        hw = struct.unpack_from("<H", data, i)[0]
        note = ""

        # BL/BLX (32-bit)
        if (hw >> 11) == 0b11110 and (i + 2) < len(data):
            hw2 = struct.unpack_from("<H", data, i + 2)[0]
            if (hw2 >> 11) in (0b11111, 0b11101):
                off_hi = hw & 0x7FF
                off_lo = hw2 & 0x7FF
                if off_hi & 0x400:
                    off_hi |= 0xFFFFF800
                offset_val = (off_hi << 12) | (off_lo << 1)
                if offset_val & 0x400000:
                    offset_val |= 0xFF800000
                    offset_val -= 0x1000000
                target = addr + 4 + offset_val
                is_blx = (hw2 >> 11) == 0b11101
                mn = "BLX" if is_blx else "BL"
                sym = annotate(target)
                note = f"  ; {sym}" if sym else ""
                print(f"  0x{addr:08X}:  {hw:04X} {hw2:04X}  {mn} 0x{target:08X}{note}")
                i += 4
                continue

        # PC-relative LDR
        if (hw >> 11) == 0b01001:
            rd = (hw >> 8) & 0x7
            word8 = hw & 0xFF
            pc_target = (addr & ~2) + 4 + word8 * 4
            lit_val = resolve_literal(rom, pc_target)
            if lit_val is not None:
                sym = annotate(lit_val)
                sym_str = f" ({sym})" if sym else ""
                mn = f"LDR r{rd}, [PC, #0x{word8*4:X}]"
                note = f"  ; =0x{lit_val:08X}{sym_str}"
                ldr_pool_refs.append((addr, rd, pc_target, lit_val))
            else:
                mn = f"LDR r{rd}, [PC, #0x{word8*4:X}]"

        # PUSH
        elif (hw >> 12) == 0b1011 and ((hw >> 9) & 0x3) == 0b10 and ((hw >> 11) & 1) == 0:
            r = (hw >> 8) & 1
            rlist = hw & 0xFF
            regs = [f"r{j}" for j in range(8) if rlist & (1 << j)]
            if r: regs.append("lr")
            mn = f"PUSH {{{', '.join(regs)}}}"

        # POP
        elif (hw >> 12) == 0b1011 and ((hw >> 9) & 0x3) == 0b10 and ((hw >> 11) & 1) == 1:
            r = (hw >> 8) & 1
            rlist = hw & 0xFF
            regs = [f"r{j}" for j in range(8) if rlist & (1 << j)]
            if r: regs.append("pc")
            mn = f"POP {{{', '.join(regs)}}}"

        # Format 3: Immediate ops
        elif (hw >> 13) == 0b001:
            sub_op = (hw >> 11) & 0x3
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            ops = ["MOV", "CMP", "ADD", "SUB"]
            mn = f"{ops[sub_op]} r{rd}, #0x{imm8:02X}"
            if sub_op == 1:  # CMP
                note = f"  ; CMP with {imm8} (0x{imm8:X})"
                if imm8 == 0x39:
                    note += " = 57 (CONTROLLER_CMDS_COUNT in expansion)"
                elif imm8 == 0x33:
                    note += " = 51 (CONTROLLER_CMDS_COUNT in vanilla)"
                elif imm8 == 0x38:
                    note += " = 56"

        # Format 1: Shift by imm
        elif (hw >> 13) == 0b000 and (hw >> 11) & 0x3 != 0b11:
            sub_op = (hw >> 11) & 0x3
            offset5 = (hw >> 6) & 0x1F
            rs = (hw >> 3) & 0x7
            rd = hw & 0x7
            if sub_op == 0:
                mn = f"{'MOV' if offset5==0 else 'LSL'} r{rd}, r{rs}, #{offset5}" if offset5 else f"MOV r{rd}, r{rs}"
            elif sub_op == 1:
                mn = f"LSR r{rd}, r{rs}, #{offset5 if offset5 else 32}"
            else:
                mn = f"ASR r{rd}, r{rs}, #{offset5 if offset5 else 32}"

        # Format 2: Add/sub reg/imm
        elif (hw >> 11) == 0b00011:
            i_bit = (hw >> 10) & 1
            op_bit = (hw >> 9) & 1
            rn_imm = (hw >> 6) & 0x7
            rs = (hw >> 3) & 0x7
            rd = hw & 0x7
            op_name = "SUB" if op_bit else "ADD"
            if i_bit:
                mn = f"{op_name} r{rd}, r{rs}, #{rn_imm}"
            else:
                mn = f"{op_name} r{rd}, r{rs}, r{rn_imm}"

        # Format 4: ALU
        elif (hw >> 10) == 0b010000:
            alu_op = (hw >> 6) & 0xF
            rs = (hw >> 3) & 0x7
            rd = hw & 0x7
            alu_names = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                         "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
            mn = f"{alu_names[alu_op]} r{rd}, r{rs}"

        # Format 5: Hi reg / BX
        elif (hw >> 10) == 0b010001:
            sub_op = (hw >> 8) & 0x3
            h1 = (hw >> 7) & 1
            h2 = (hw >> 6) & 1
            rs = ((h2 << 3) | ((hw >> 3) & 0x7))
            rd = ((h1 << 3) | (hw & 0x7))
            if sub_op == 0: mn = f"ADD r{rd}, r{rs}"
            elif sub_op == 1: mn = f"CMP r{rd}, r{rs}"
            elif sub_op == 2: mn = f"MOV r{rd}, r{rs}"
            elif sub_op == 3: mn = f"BX r{rs}" if h1 == 0 else f"BLX r{rs}"

        # Format 7: Load/store reg offset
        elif (hw >> 12) == 0b0101 and ((hw >> 9) & 1) == 0:
            lb = (hw >> 10) & 0x3
            ro = (hw >> 6) & 0x7
            rb = (hw >> 3) & 0x7
            rd = hw & 0x7
            ops = ["STR","STRB","LDR","LDRB"]
            mn = f"{ops[lb]} r{rd}, [r{rb}, r{ro}]"

        # Format 8: sign-extended
        elif (hw >> 12) == 0b0101 and ((hw >> 9) & 1) == 1:
            sub = (hw >> 10) & 0x3
            ro = (hw >> 6) & 0x7
            rb = (hw >> 3) & 0x7
            rd = hw & 0x7
            ops = ["STRH","LDSB","LDRH","LDSH"]
            mn = f"{ops[sub]} r{rd}, [r{rb}, r{ro}]"

        # Format 9: imm offset
        elif (hw >> 13) == 0b011:
            bl = (hw >> 12) & 1
            l = (hw >> 11) & 1
            offset5 = (hw >> 6) & 0x1F
            rb = (hw >> 3) & 0x7
            rd = hw & 0x7
            if bl == 0:
                off = offset5 * 4
                op_name = "LDR" if l else "STR"
                mn = f"{op_name} r{rd}, [r{rb}, #0x{off:X}]"
            else:
                op_name = "LDRB" if l else "STRB"
                mn = f"{op_name} r{rd}, [r{rb}, #0x{offset5:X}]"

        # Format 10: halfword
        elif (hw >> 12) == 0b1000:
            l = (hw >> 11) & 1
            offset5 = (hw >> 6) & 0x1F
            rb = (hw >> 3) & 0x7
            rd = hw & 0x7
            off = offset5 * 2
            op_name = "LDRH" if l else "STRH"
            mn = f"{op_name} r{rd}, [r{rb}, #0x{off:X}]"

        # Format 11: SP-relative
        elif (hw >> 12) == 0b1001:
            l = (hw >> 11) & 1
            rd = (hw >> 8) & 0x7
            word8 = hw & 0xFF
            off = word8 * 4
            op_name = "LDR" if l else "STR"
            mn = f"{op_name} r{rd}, [SP, #0x{off:X}]"

        # Format 12: Load address
        elif (hw >> 12) == 0b1010:
            sp = (hw >> 11) & 1
            rd = (hw >> 8) & 0x7
            word8 = hw & 0xFF
            off = word8 * 4
            src = "SP" if sp else "PC"
            mn = f"ADD r{rd}, {src}, #0x{off:X}"

        # Format 13: SP adjust
        elif (hw >> 8) == 0b10110000:
            s = (hw >> 7) & 1
            imm7 = hw & 0x7F
            off = imm7 * 4
            op_name = "SUB" if s else "ADD"
            mn = f"{op_name} SP, #0x{off:X}"

        # Format 16: Cond branch
        elif (hw >> 12) == 0b1101:
            cond = (hw >> 8) & 0xF
            if cond < 0xE:
                soff8 = hw & 0xFF
                if soff8 & 0x80: soff8 -= 256
                target = addr + 4 + soff8 * 2
                cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                              "BHI","BLS","BGE","BLT","BGT","BLE"]
                mn = f"{cond_names[cond]} 0x{target:08X}"
            elif cond == 0xF:
                mn = f"SWI #0x{hw & 0xFF:02X}"
            else:
                mn = f".hword 0x{hw:04X}"

        # Format 18: Unconditional branch
        elif (hw >> 11) == 0b11100:
            soff11 = hw & 0x7FF
            if soff11 & 0x400: soff11 -= 2048
            target = addr + 4 + soff11 * 2
            mn = f"B 0x{target:08X}"

        else:
            mn = f".hword 0x{hw:04X}"

        print(f"  0x{addr:08X}:  {hw:04X}       {mn}{note}")
        i += 2

    return ldr_pool_refs


def find_all_refs(rom, target_u32, description):
    """Find all word-aligned occurrences of a 32-bit value in ROM."""
    pattern = struct.pack("<I", target_u32)
    results = []
    pos = 0
    while True:
        p = rom.find(pattern, pos)
        if p == -1:
            break
        if p % 4 == 0:  # word-aligned (literal pool entries)
            results.append(p)
        pos = p + 1
    return results


def identify_setcontroller_function(rom, pool_offset):
    """Given a literal pool offset containing our target, try to find the function start."""
    # Walk backwards from pool_offset to find the function that references it.
    # Literal pools follow POP/BX instructions. The function code is BEFORE the pool.
    # Search backwards for PUSH {lr} or PUSH {r4, lr} etc.

    # First, scan the LDR instructions in the code before this pool
    # to find which function uses this literal pool entry.
    # LDR Rd, [PC, #imm] -> pc_target = (current_addr & ~2) + 4 + imm*4

    # The pool is at rom offset `pool_offset`. GBA address = 0x08000000 + pool_offset.
    pool_gba = 0x08000000 + pool_offset

    # Search backwards up to 200 bytes for LDR instructions referencing this pool entry
    for back in range(2, 200, 2):
        instr_off = pool_offset - back
        if instr_off < 0:
            break
        hw = read_u16(rom, instr_off)
        # Check if this is LDR Rd, [PC, #imm]
        if (hw >> 11) == 0b01001:
            word8 = hw & 0xFF
            instr_gba = 0x08000000 + instr_off
            pc_target = (instr_gba & ~2) + 4 + word8 * 4
            if pc_target == pool_gba:
                # This instruction references our pool entry!
                # Now find the function start (search backwards for PUSH)
                for fb in range(0, 200, 2):
                    check_off = instr_off - fb
                    if check_off < 0:
                        break
                    check_hw = read_u16(rom, check_off)
                    # PUSH {... lr}
                    if (check_hw & 0xFF00) == 0xB500:
                        return check_off
    return None


def read_command_table(rom, table_gba_addr, count):
    """Read a command dispatch table (array of function pointers)."""
    entries = []
    off = table_gba_addr - 0x08000000
    for i in range(count):
        if off + i*4 + 4 <= len(rom):
            val = read_u32(rom, off + i*4)
            entries.append(val)
        else:
            entries.append(None)
    return entries


def main():
    print(f"ROM path: {ROM_PATH}")
    if not os.path.exists(ROM_PATH):
        print(f"ERROR: ROM not found!")
        sys.exit(1)

    with open(ROM_PATH, "rb") as f:
        rom = f.read()

    print(f"ROM size: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)")
    print()

    TARGET_THUMB = 0x0807DC45
    TARGET_ROM = 0x0807DC44  # without THUMB bit
    TARGET_FILEOFF = TARGET_ROM - 0x08000000

    LINK_OPP_THUMB = 0x0807793D
    LINK_OPP_ROM = 0x0807793C
    LINK_OPP_FILEOFF = LINK_OPP_ROM - 0x08000000

    OPP_THUMB = 0x081BAD85
    OPP_ROM = 0x081BAD84
    OPP_FILEOFF = OPP_ROM - 0x08000000

    # ========================================================================
    # PART 1: Disassemble the target function at 0x0807DC44
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 1: DISASSEMBLE TARGET FUNCTION AT 0x0807DC44")
    print("#"*80)

    target_pools = disasm_thumb(rom, TARGET_ROM, 120, "Target Function at 0x0807DC44 (THUMB: 0x0807DC45)")

    # ========================================================================
    # PART 2: Disassemble LinkOpponentBufferRunCommand for comparison
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 2: DISASSEMBLE LinkOpponentBufferRunCommand (0x0807793C) FOR COMPARISON")
    print("#"*80)

    link_opp_pools = disasm_thumb(rom, LINK_OPP_ROM, 120, "LinkOpponentBufferRunCommand (0x0807793D)")

    # ========================================================================
    # PART 3: Disassemble OpponentBufferRunCommand for comparison
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 3: DISASSEMBLE OpponentBufferRunCommand (0x081BAD84) FOR COMPARISON")
    print("#"*80)

    opp_pools = disasm_thumb(rom, OPP_ROM, 120, "OpponentBufferRunCommand (0x081BAD85)")

    # ========================================================================
    # PART 4: Compare literal pool values across all three functions
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 4: LITERAL POOL COMPARISON")
    print("#"*80)

    print(f"\n  {'Pool Entry':<20s} {'Target (0x0807DC44)':<28s} {'LinkOpp (0x0807793C)':<28s} {'Opp (0x081BAD84)':<28s}")
    print(f"  {'-'*20} {'-'*28} {'-'*28} {'-'*28}")

    # Extract pool values by register
    def pool_by_reg(pools):
        d = {}
        for addr, rd, pool_addr, pool_val in pools:
            if rd not in d:
                d[rd] = (pool_addr, pool_val)
        return d

    t_pools = pool_by_reg(target_pools)
    l_pools = pool_by_reg(link_opp_pools)
    o_pools = pool_by_reg(opp_pools)

    all_regs = sorted(set(list(t_pools.keys()) + list(l_pools.keys()) + list(o_pools.keys())))

    for reg in all_regs:
        t_str = f"0x{t_pools[reg][1]:08X}" if reg in t_pools else "N/A"
        l_str = f"0x{l_pools[reg][1]:08X}" if reg in l_pools else "N/A"
        o_str = f"0x{o_pools[reg][1]:08X}" if reg in o_pools else "N/A"

        # Annotations
        if reg in t_pools:
            sym = annotate(t_pools[reg][1])
            if sym: t_str += f" ({sym[:20]})"
        if reg in l_pools:
            sym = annotate(l_pools[reg][1])
            if sym: l_str += f" ({sym[:20]})"
        if reg in o_pools:
            sym = annotate(o_pools[reg][1])
            if sym: o_str += f" ({sym[:20]})"

        print(f"  LDR r{reg:<14d} {t_str:<28s} {l_str:<28s} {o_str:<28s}")

    # ========================================================================
    # PART 5: Identify the command table
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 5: COMMAND TABLE ANALYSIS")
    print("#"*80)

    # Find the command table pointer in the target's literal pool
    # It's typically the last LDR before the dispatch BL
    target_cmd_table = None
    link_cmd_table = None
    opp_cmd_table = None

    for addr, rd, pool_addr, pool_val in target_pools:
        if pool_val >= 0x08000000 and pool_val < 0x0A000000:
            # Check if it looks like a table (not a function - even address = data)
            if (pool_val & 1) == 0:
                target_cmd_table = pool_val
            # Also check: if the value at this ROM address looks like a table of THUMB pointers
    for addr, rd, pool_addr, pool_val in link_opp_pools:
        if pool_val >= 0x08000000 and pool_val < 0x0A000000 and (pool_val & 1) == 0:
            link_cmd_table = pool_val
    for addr, rd, pool_addr, pool_val in opp_pools:
        if pool_val >= 0x08000000 and pool_val < 0x0A000000 and (pool_val & 1) == 0:
            opp_cmd_table = pool_val

    print(f"\n  Target command table:  {f'0x{target_cmd_table:08X}' if target_cmd_table else 'NOT FOUND'}")
    print(f"  LinkOpp command table: {f'0x{link_cmd_table:08X}' if link_cmd_table else 'NOT FOUND'}")
    print(f"  Opp command table:     {f'0x{opp_cmd_table:08X}' if opp_cmd_table else 'NOT FOUND'}")

    # Compare first 52 entries (CONTROLLER_CMDS_COUNT in expansion = 52)
    CMD_COUNT = 58  # might be higher in R&B
    controller_names = [
        "GETMONDATA", "GETRAWMONDATA", "SETMONDATA", "SETRAWMONDATA",
        "LOADMONSPRITE", "SWITCHINANIM", "RETURNMONTOBALL", "DRAWTRAINERPIC",
        "TRAINERSLIDE", "TRAINERSLIDEBACK", "FAINTANIMATION", "PALETTEFADE",
        "SUCCESSBALLTHROWANIM", "BALLTHROWANIM", "PAUSE", "MOVEANIMATION",
        "PRINTSTRING", "PRINTSTRINGPLAYERONLY", "CHOOSEACTION", "YESNOBOX",
        "CHOOSEMOVE", "OPENBAG", "CHOOSEPOKEMON", "23",
        "HEALTHBARUPDATE", "EXPUPDATE", "STATUSICONUPDATE", "STATUSANIMATION",
        "STATUSXOR", "DATATRANSFER", "DMA3TRANSFER", "PLAYBGM",
        "32", "TWORETURNVALUES", "CHOSENMONRETURNVALUE", "ONERETURNVALUE",
        "ONERETURNVALUE_DUP", "HITANIMATION", "CANTSWITCH", "PLAYSE",
        "PLAYFANFAREORBGM", "FAINTINGCRY", "INTROSLIDE", "INTROTRAINERBALLTHROW",
        "DRAWPARTYSTATUSSUMMARY", "HIDEPARTYSTATUSSUMMARY", "ENDBOUNCE",
        "SPRITEINVISIBILITY", "BATTLEANIMATION", "LINKSTANDBYMSG",
        "RESETACTIONMOVESELECTION", "ENDLINKBATTLE", "DEBUGMENU",
        "TERMINATOR_NOP", "54?", "55?", "56?", "57?"
    ]

    if target_cmd_table and link_cmd_table:
        target_entries = read_command_table(rom, target_cmd_table, CMD_COUNT)
        link_entries = read_command_table(rom, link_cmd_table, CMD_COUNT)
        opp_entries = read_command_table(rom, opp_cmd_table, CMD_COUNT) if opp_cmd_table else [None]*CMD_COUNT

        print(f"\n  Command table comparison (first {CMD_COUNT} entries):")
        print(f"  {'#':<4s} {'Controller':<30s} {'Target':<14s} {'LinkOpp':<14s} {'Opp':<14s} {'T==L?':<6s} {'T==O?':<6s}")
        print(f"  {'-'*4} {'-'*30} {'-'*14} {'-'*14} {'-'*14} {'-'*6} {'-'*6}")

        diff_from_link = 0
        diff_from_opp = 0
        for j in range(CMD_COUNT):
            t = target_entries[j] if j < len(target_entries) else None
            l = link_entries[j] if j < len(link_entries) else None
            o = opp_entries[j] if j < len(opp_entries) else None
            cn = controller_names[j] if j < len(controller_names) else f"?{j}"

            t_str = f"0x{t:08X}" if t else "N/A"
            l_str = f"0x{l:08X}" if l else "N/A"
            o_str = f"0x{o:08X}" if o else "N/A"

            eq_l = "YES" if t == l else "NO"
            eq_o = "YES" if t == o else "NO"

            if t != l: diff_from_link += 1
            if t != o: diff_from_opp += 1

            # Only print differences
            if t != l or t != o:
                print(f"  [{j:2d}] {cn:<30s} {t_str:<14s} {l_str:<14s} {o_str:<14s} {eq_l:<6s} {eq_o:<6s}")

        print(f"\n  Total differences from LinkOpp: {diff_from_link}/{CMD_COUNT}")
        print(f"  Total differences from Opp:     {diff_from_opp}/{CMD_COUNT}")

        # Determine the closest match
        if diff_from_link == 0 and diff_from_opp == 0:
            print("\n  *** IDENTICAL to both LinkOpp and Opp command tables ***")
        elif diff_from_link < diff_from_opp:
            print(f"\n  *** CLOSER to LinkOpponent ({diff_from_link} diffs) than Opponent ({diff_from_opp} diffs) ***")
        elif diff_from_opp < diff_from_link:
            print(f"\n  *** CLOSER to Opponent ({diff_from_opp} diffs) than LinkOpponent ({diff_from_link} diffs) ***")
        else:
            print(f"\n  *** EQUIDISTANT from both ({diff_from_link} diffs each) ***")

    # ========================================================================
    # PART 6: Search for references to 0x0807DC45 in ROM literal pools
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 6: SEARCH FOR REFERENCES TO 0x0807DC45 IN ROM")
    print("#"*80)

    refs = find_all_refs(rom, TARGET_THUMB, "0x0807DC45")
    print(f"\n  Found {len(refs)} word-aligned references to 0x{TARGET_THUMB:08X} in ROM:")
    for ref_off in refs:
        ref_gba = 0x08000000 + ref_off
        print(f"\n  --- Reference at ROM 0x{ref_off:06X} (0x{ref_gba:08X}) ---")
        # Show surrounding literal pool
        for delta in range(-16, 20, 4):
            check_off = ref_off + delta
            if 0 <= check_off < len(rom) - 4:
                val = read_u32(rom, check_off)
                marker = ""
                if val == TARGET_THUMB:
                    marker = " <-- TARGET (0x0807DC45)"
                else:
                    sym = annotate(val)
                    if sym:
                        marker = f" ({sym})"
                    elif (val & 0xFF000001) == 0x08000001:
                        marker = " (THUMB ptr)"
                    elif (val & 0xFF000000) == 0x02000000:
                        marker = " (EWRAM)"
                    elif (val & 0xFF000000) == 0x03000000:
                        marker = " (IWRAM)"
                print(f"    0x{0x08000000+check_off:08X}: 0x{val:08X}{marker}")

        # Find the function that uses this literal pool
        func_start = identify_setcontroller_function(rom, ref_off)
        if func_start:
            func_gba = 0x08000000 + func_start
            print(f"\n    -> Function using this pool starts at 0x{func_gba:08X} (THUMB: 0x{func_gba|1:08X})")
            # Disassemble the SetController function (small, ~20 bytes)
            disasm_thumb(rom, func_gba, 40, f"SetControllerTo??? at 0x{func_gba:08X}")

    # ========================================================================
    # PART 7: Cross-reference with known ExecCompleted functions
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 7: FIND ASSOCIATED ExecCompleted FUNCTION")
    print("#"*80)

    # The ExecCompleted function stores the RunCommand pointer back.
    # Search for 0x0807DC45 in ROM — any reference that's NOT in a SetController
    # function is likely in the ExecCompleted function.
    print(f"\n  Looking for ExecCompleted that restores 0x{TARGET_THUMB:08X}...")

    for ref_off in refs:
        # Check if this is in a different function than SetController
        func_start = identify_setcontroller_function(rom, ref_off)
        if func_start:
            # Read the function to see if it also stores gBattlerControllerFuncs
            # and references gBattleTypeFlags (characteristic of ExecCompleted)
            region = rom[func_start:func_start + 100]
            # Check literal pool for gBattleTypeFlags
            has_btf = False
            has_ctrl = False
            for j in range(0, 100, 4):
                if func_start + j + 4 <= len(rom):
                    val = read_u32(rom, func_start + j)
                    if val == 0x02023364:  # gBattleTypeFlags
                        has_btf = True
                    if val == 0x03005D70:  # gBattlerControllerFuncs
                        has_ctrl = True

            if has_btf and has_ctrl:
                print(f"    ExecCompleted candidate at 0x{0x08000000+func_start:08X}")
                print(f"      (has gBattleTypeFlags AND gBattlerControllerFuncs references)")

    # ========================================================================
    # PART 8: Compare with ALL known controller types
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 8: IDENTIFY CONTROLLER TYPE BY COMPARING ALL KNOWN RunCommands")
    print("#"*80)

    # Search for ALL functions that have the RunCommand pattern:
    # PUSH, LDR (execFlags), LDR (masks), LDR (activeBattler), ..., CMP #N, BHI, LDR (table)
    # Key signature: the CMP immediate tells us CONTROLLER_CMDS_COUNT
    # and the table pointer tells us which controller.

    print("\n  Scanning ROM for all BufferRunCommand-pattern functions...")
    print("  Pattern: PUSH {r4, lr} followed by LDR series + CMP #imm + jump table dispatch")

    # Get the CMP value from our target
    target_cmp = None
    for i in range(0, 100, 2):
        hw = read_u16(rom, TARGET_FILEOFF + i)
        if (hw >> 11) == 0b001 and ((hw >> 11) & 0x3) == 1:  # CMP Rn, #imm
            if (hw & 0xF800) == 0x2800:
                target_cmp = hw & 0xFF
                print(f"  Target CMP value: #0x{target_cmp:02X} ({target_cmp})")
                break

    # ========================================================================
    # PART 9: Check all SetControllerTo... functions referencing this address
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 9: IDENTIFY BY SetControllerTo... CONTEXT")
    print("#"*80)

    # In pokeemerald-expansion, the controller assignment is done in InitBattleControllers().
    # The pattern is:
    #   if (GetBattlerSide(i) == B_SIDE_PLAYER)
    #       SetControllerToPlayer/RecordedPlayer/LinkPartner(i)
    #   else
    #       SetControllerToOpponent/RecordedOpponent/LinkOpponent(i)
    #
    # The SetControllerTo... functions are small: they store RunCommand and ExecCompleted.
    # If we find SetControllerToX that stores 0x0807DC45, we know the type.

    # Look for SetControllerTo... that store BOTH 0x0807DC45 and an ExecCompleted.
    # These functions have a very specific pattern:
    #   LDR r0, =gBattlerControllerEndFuncs  (or similar)
    #   LDR r1, =ExecCompleted
    #   STR r1, [r0, ...]
    #   LDR r1, =RunCommand (0x0807DC45)
    #   STR r1, [r0, ...]
    #   BX lr (or POP {pc})

    # We already found refs. For each ref, find the function and look for ANOTHER THUMB
    # pointer in the same literal pool — that's the ExecCompleted.
    for ref_off in refs:
        ref_gba = 0x08000000 + ref_off
        print(f"\n  Analyzing reference at 0x{ref_gba:08X}:")

        # Read surrounding pool entries
        other_thumb_ptrs = []
        other_ewram = []
        other_iwram = []
        for delta in range(-16, 20, 4):
            check_off = ref_off + delta
            if 0 <= check_off < len(rom) - 4 and check_off != ref_off:
                val = read_u32(rom, check_off)
                if (val & 0xFF000001) == 0x08000001:
                    other_thumb_ptrs.append((check_off, val))
                elif (val & 0xFF000000) == 0x02000000:
                    other_ewram.append((check_off, val))
                elif (val & 0xFF000000) == 0x03000000:
                    other_iwram.append((check_off, val))

        print(f"    Other THUMB pointers in nearby pool:")
        for off, val in other_thumb_ptrs:
            sym = annotate(val)
            sym_str = f" ({sym})" if sym else ""
            print(f"      0x{0x08000000+off:08X}: 0x{val:08X}{sym_str}")

        print(f"    EWRAM refs in nearby pool:")
        for off, val in other_ewram:
            sym = annotate(val)
            sym_str = f" ({sym})" if sym else ""
            print(f"      0x{0x08000000+off:08X}: 0x{val:08X}{sym_str}")

        print(f"    IWRAM refs in nearby pool:")
        for off, val in other_iwram:
            sym = annotate(val)
            sym_str = f" ({sym})" if sym else ""
            print(f"      0x{0x08000000+off:08X}: 0x{val:08X}{sym_str}")

    # ========================================================================
    # PART 10: Compare with other controller RunCommand addresses nearby
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 10: NEARBY FUNCTIONS — MAP THE CONTROLLER FILE LAYOUT")
    print("#"*80)

    # In pokeemerald-expansion, the source files are compiled in a specific order.
    # The controller files produce functions in this ROM order:
    #   battle_controller_link_opponent.c -> LinkOpponent functions
    #   battle_controller_link_partner.c -> LinkPartner functions
    #   battle_controller_recorded_opponent.c -> RecordedOpponent functions
    #   battle_controller_recorded_player.c -> RecordedPlayer functions
    #   ...
    # The EXACT order depends on the Makefile/linker script.

    # Let's find all PUSH-starting functions between LinkOpp (0x077xxx) and the target (0x07DC44)
    # to understand the layout.

    print(f"\n  Known functions in this ROM region:")
    print(f"    0x0807793C: LinkOpponentBufferRunCommand (confirmed)")
    print(f"    0x08078788: LinkOpponentBufferExecCompleted (confirmed)")
    print(f"    0x0807DC44: TARGET FUNCTION")
    print(f"    0x081BAD84: OpponentBufferRunCommand")

    # Search for SetControllerTo... functions that reference the known function tables
    # Look for functions storing to gBattlerControllerFuncs (0x03005D70)
    print(f"\n  Searching for ALL SetControllerTo... functions (store to gBattlerControllerFuncs)...")

    # Find all literal pool entries pointing to gBattlerControllerFuncs
    ctrl_refs = find_all_refs(rom, 0x03005D70, "gBattlerControllerFuncs")
    print(f"  Found {len(ctrl_refs)} references to gBattlerControllerFuncs (0x03005D70)")

    # For each, check if there's a nearby THUMB pointer that we can identify
    controller_map = {}  # thumb_addr -> (set_controller_addr, exec_completed_addr)

    for ctrl_ref_off in ctrl_refs:
        # Check nearby pool entries for THUMB pointers
        nearby_thumbs = []
        for delta in range(-16, 20, 4):
            check_off = ctrl_ref_off + delta
            if 0 <= check_off < len(rom) - 4:
                val = read_u32(rom, check_off)
                if (val & 0xFF000001) == 0x08000001:
                    nearby_thumbs.append(val)

        # If one of the THUMB pointers is our target
        if TARGET_THUMB in nearby_thumbs:
            other = [t for t in nearby_thumbs if t != TARGET_THUMB]
            func_start = identify_setcontroller_function(rom, ctrl_ref_off)
            sc_addr = 0x08000000 + func_start if func_start else None
            sc_str = f"0x{sc_addr:08X}" if sc_addr else "UNKNOWN"
            print(f"\n  *** SetControllerTo??? at {sc_str} ***")
            print(f"      RunCommand = 0x{TARGET_THUMB:08X} (our target)")
            for o in other:
                sym = annotate(o)
                print(f"      ExecCompleted = 0x{o:08X} {f'({sym})' if sym else ''}")

    # ========================================================================
    # PART 11: DEFINITIVE IDENTIFICATION
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 11: DEFINITIVE IDENTIFICATION")
    print("#"*80)

    # The command table is the KEY differentiator between controller types.
    # Let's compare the target's command table entries at the DIFFERENTIATING indices:
    #
    # Key differences between controller types:
    # [7]  DRAWTRAINERPIC   — each controller has its own handler
    # [8]  TRAINERSLIDE     — LinkOpp has custom, RecordedOpp uses Opponent's
    # [9]  TRAINERSLIDEBACK  — varies
    # [18] CHOOSEACTION      — LinkOpp=Empty, RecordedOpp=custom, Opponent=custom
    # [20] CHOOSEMOVE        — LinkOpp=Empty, RecordedOpp=custom, Opponent=custom
    # [21] OPENBAG           — LinkOpp=Empty, RecordedOpp=custom, Opponent=custom
    # [22] CHOOSEPOKEMON     — LinkOpp=Empty, RecordedOpp=custom, Opponent=custom
    # [43] INTROTRAINERBALLTHROW — each has its own
    # [44] DRAWPARTYSTATUSSUMMARY — varies
    # [49] LINKSTANDBYMSG    — LinkOpp=custom, others=Empty
    # [51] ENDLINKBATTLE     — each has its own handler

    if target_cmd_table:
        print(f"\n  Analyzing key command table entries for target at 0x{target_cmd_table:08X}:")
        t_entries = read_command_table(rom, target_cmd_table, CMD_COUNT)
        l_entries = read_command_table(rom, link_cmd_table, CMD_COUNT) if link_cmd_table else None
        o_entries = read_command_table(rom, opp_cmd_table, CMD_COUNT) if opp_cmd_table else None

        key_indices = [7, 8, 9, 18, 20, 21, 22, 43, 44, 49, 51]
        for idx in key_indices:
            if idx < len(t_entries) and t_entries[idx]:
                cn = controller_names[idx] if idx < len(controller_names) else f"?{idx}"
                t_val = t_entries[idx]
                print(f"\n  [{idx:2d}] {cn}:")
                print(f"    Target:  0x{t_val:08X}")
                if l_entries and idx < len(l_entries):
                    l_val = l_entries[idx]
                    match = "SAME" if t_val == l_val else "DIFFERENT"
                    print(f"    LinkOpp: 0x{l_val:08X}  [{match}]")
                if o_entries and idx < len(o_entries):
                    o_val = o_entries[idx]
                    match = "SAME" if t_val == o_val else "DIFFERENT"
                    print(f"    Opp:     0x{o_val:08X}  [{match}]")

        # Check CHOOSEACTION (index 18) specifically:
        # LinkOpponent: BtlController_Empty (no choice — link opponent is remote)
        # RecordedOpponent: RecordedOpponentHandleChooseAction (replay recorded action)
        # Opponent: OpponentHandleChooseAction (AI picks action)
        # RecordedPlayer: RecordedPlayerHandleChooseAction (replay)
        # LinkPartner: BtlController_Empty
        # Wally: WallyHandleChooseAction

        # Find BtlController_Empty address
        # It's the most common entry in all tables
        from collections import Counter
        if t_entries:
            entry_counts = Counter(t_entries[:54])
            most_common_val = entry_counts.most_common(1)[0][0]
            print(f"\n  Most common entry in target table (=BtlController_Empty): 0x{most_common_val:08X}")

            # Check CHOOSEACTION
            choose_action = t_entries[18] if 18 < len(t_entries) else None
            if choose_action == most_common_val:
                print(f"  CHOOSEACTION = BtlController_Empty")
                print(f"    -> This is consistent with: LinkOpponent, LinkPartner")
                print(f"    -> NOT consistent with: RecordedOpponent, Opponent, Wally")
            else:
                print(f"  CHOOSEACTION = 0x{choose_action:08X} (custom handler)")
                print(f"    -> NOT LinkOpponent, NOT LinkPartner (they use Empty)")
                print(f"    -> Consistent with: RecordedOpponent, Opponent, Wally, RecordedPlayer")

            # Check CHOOSEMOVE
            choose_move = t_entries[20] if 20 < len(t_entries) else None
            if choose_move == most_common_val:
                print(f"  CHOOSEMOVE = BtlController_Empty")
                print(f"    -> Consistent with: LinkOpponent, LinkPartner")
            else:
                print(f"  CHOOSEMOVE = 0x{choose_move:08X} (custom handler)")
                print(f"    -> NOT LinkOpponent, NOT LinkPartner")

            # Check LINKSTANDBYMSG (49)
            linkstandby = t_entries[49] if 49 < len(t_entries) else None
            if linkstandby == most_common_val:
                print(f"  LINKSTANDBYMSG = BtlController_Empty")
                print(f"    -> NOT LinkOpponent (LinkOpp has custom handler)")
                print(f"    -> Consistent with: RecordedOpponent, Opponent, RecordedPlayer, Wally, Safari")
            else:
                print(f"  LINKSTANDBYMSG = 0x{linkstandby:08X} (custom handler)")
                print(f"    -> Consistent with: LinkOpponent (has custom LinkStandbyMsg handler)")

    # ========================================================================
    # PART 12: FINAL VERDICT
    # ========================================================================
    print("\n" + "#"*80)
    print("#  PART 12: FINAL VERDICT")
    print("#"*80)

    print(f"""
  The function at THUMB address 0x0807DC45 (ROM offset 0x07DC44) needs to be
  identified based on:

  1. Its COMMAND TABLE — which handlers are custom vs BtlController_Empty
  2. Its LITERAL POOL — which data addresses it references
  3. Its REFERENCES — which SetControllerTo... function stores it
  4. Its ROM LOCATION — relative to other known controller functions

  Key differentiators:
  - CHOOSEACTION/CHOOSEMOVE/OPENBAG/CHOOSEPOKEMON = Empty -> Link-type controller
  - CHOOSEACTION = custom -> AI/Recorded controller
  - LINKSTANDBYMSG = custom -> LinkOpponent or LinkPartner
  - ENDLINKBATTLE handler -> unique per controller type
  - DRAWTRAINERPIC handler -> unique per controller type

  The config/run_and_bun.lua already notes:
    "CORRECTED: real LinkOpponentBufferRunCommand (was 0x0807DC45 = RecordedOpponent)"

  This script verifies whether that identification is correct.
""")

    # Quick byte-for-byte comparison of the first N instruction halfwords
    print("  Byte-level comparison (first 32 halfwords):")
    print(f"  {'Offset':<8s} {'Target':<8s} {'LinkOpp':<8s} {'Opp':<8s} {'T==L':<6s} {'T==O':<6s}")
    t_match = 0
    l_match = 0
    o_match = 0
    total = 32
    for j in range(total):
        t_hw = read_u16(rom, TARGET_FILEOFF + j*2)
        l_hw = read_u16(rom, LINK_OPP_FILEOFF + j*2)
        o_hw = read_u16(rom, OPP_FILEOFF + j*2)
        eq_l = t_hw == l_hw
        eq_o = t_hw == o_hw
        if eq_l: t_match += 1
        if eq_o: o_match += 1
        print(f"  +{j*2:<6d} 0x{t_hw:04X}   0x{l_hw:04X}   0x{o_hw:04X}   {'YES' if eq_l else 'NO':<6s} {'YES' if eq_o else 'NO':<6s}")

    print(f"\n  Instruction match with LinkOpp: {t_match}/{total}")
    print(f"  Instruction match with Opp:     {o_match}/{total}")


if __name__ == "__main__":
    main()
