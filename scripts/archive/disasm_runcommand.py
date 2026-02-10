"""
Disassemble LinkOpponentBufferRunCommand and OpponentBufferRunCommand from Pokemon Run & Bun ROM.
Reads raw bytes from the .gba file and produces THUMB (16-bit) disassembly.
Resolves literal pool values for PC-relative loads.
"""

import struct
import sys
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "rom", "Pokemon RunBun.gba")


def read_u32(rom, file_offset):
    return struct.unpack_from("<I", rom, file_offset)[0]


def read_u16(rom, file_offset):
    return struct.unpack_from("<H", rom, file_offset)[0]


# Known symbols for annotation
KNOWN_SYMBOLS = {
    0x020233E0: "gBattleControllerExecFlags",
    0x02023364: "gBattleTypeFlags",
    0x0202370E: "gBattleCommunication",
    0x020233FC: "gBattleMons",
    0x03005D70: "gBattlerControllerFuncs",
    0x020233DC: "gBattlerAttacker/gActiveBattler",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x02020630: "gMain.callback2_area",
    0x0202064C: "gMain.callback2",
    0x08007441: "CB2_LoadMap",
    0x080363C1: "CB2_InitBattle",
    0x0803648D: "CB2_InitBattleInternal",
    0x08094815: "CB2_BattleMain",
    0x0803816D: "BattleMainCB2",
    0x081BAD85: "OpponentBufferRunCommand",
    0x0807DC45: "LinkOpponentBufferRunCommand",
    0x083458B0: "possible_jump_table_dispatch",
    0x02023A40: "gBattleResources_ptr",
    0x0202356C: "gBattlerSpriteIds_or_similar",
    0x08000544: "SetMainCallback2",
    0x03005D80: "gBattlerControllerFuncs+0x10",
}


def resolve_literal(rom, pc_addr):
    """Read 32-bit value from ROM at a PC-relative address."""
    file_offset = pc_addr - 0x08000000
    if 0 <= file_offset < len(rom) - 3:
        return read_u32(rom, file_offset)
    return None


def annotate_value(val):
    """Return symbol name if known."""
    if val in KNOWN_SYMBOLS:
        return KNOWN_SYMBOLS[val]
    # Check nearby
    for k, v in KNOWN_SYMBOLS.items():
        if abs(val - k) <= 4 and val != k:
            return f"~{v}+{val-k}"
    return ""


def disasm_annotated(rom, rom_addr, size, label):
    """Produce annotated THUMB disassembly."""
    file_offset = rom_addr - 0x08000000
    data = rom[file_offset:file_offset + size]

    print(f"\n{'='*78}")
    print(f"  {label}")
    print(f"  ROM: 0x{rom_addr:08X} - 0x{rom_addr+size-1:08X} ({size} bytes)")
    print(f"{'='*78}")

    # Raw hex
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        print(f"  0x{rom_addr+i:08X}: {hex_str}")
    print()

    # Disassembly
    i = 0
    while i < len(data) - 1:
        addr = rom_addr + i
        hw = struct.unpack_from("<H", data, i)[0]

        # Check for BL/BLX (32-bit)
        if (hw >> 11) == 0b11110 and (i + 2) < len(data):
            hw2 = struct.unpack_from("<H", data, i + 2)[0]
            if (hw2 >> 11) in (0b11111, 0b11101):
                offset_hi = hw & 0x7FF
                offset_lo = hw2 & 0x7FF
                if offset_hi & 0x400:
                    offset_hi |= 0xFFFFF800
                offset_val = (offset_hi << 12) | (offset_lo << 1)
                if offset_val & 0x400000:
                    offset_val |= 0xFF800000
                    offset_val = offset_val - 0x1000000
                target = addr + 4 + offset_val
                is_blx = (hw2 >> 11) == 0b11101
                mnemonic = "BLX" if is_blx else "BL"
                sym = annotate_value(target) or annotate_value(target | 1)
                annotation = f"  ; {sym}" if sym else ""
                print(f"  0x{addr:08X}:  {hw:04X} {hw2:04X}  {mnemonic} 0x{target:08X}{annotation}")
                i += 4
                continue

        # Decode single 16-bit instruction
        annotation = ""

        # PC-relative load
        if (hw >> 11) == 0b01001:
            rd = (hw >> 8) & 0x7
            word8 = hw & 0xFF
            pc_target = (addr & ~2) + 4 + word8 * 4
            lit_val = resolve_literal(rom, pc_target)
            if lit_val is not None:
                sym = annotate_value(lit_val)
                sym_str = f" ({sym})" if sym else ""
                mnemonic = f"LDR r{rd}, [PC, #0x{word8*4:X}]"
                annotation = f"  ; =0x{lit_val:08X}{sym_str} @pool[0x{pc_target:08X}]"
            else:
                mnemonic = f"LDR r{rd}, [PC, #0x{word8*4:X}]"
                annotation = f"  ; @0x{pc_target:08X}"

        # PUSH
        elif (hw >> 12) == 0b1011 and ((hw >> 9) & 0x3) == 0b10 and ((hw >> 11) & 1) == 0:
            r = (hw >> 8) & 1
            rlist = hw & 0xFF
            regs = [f"r{j}" for j in range(8) if rlist & (1 << j)]
            if r:
                regs.append("lr")
            mnemonic = f"PUSH {{{', '.join(regs)}}}"

        # POP
        elif (hw >> 12) == 0b1011 and ((hw >> 9) & 0x3) == 0b10 and ((hw >> 11) & 1) == 1:
            r = (hw >> 8) & 1
            rlist = hw & 0xFF
            regs = [f"r{j}" for j in range(8) if rlist & (1 << j)]
            if r:
                regs.append("pc")
            mnemonic = f"POP {{{', '.join(regs)}}}"

        # Format 1: Shift by immediate
        elif (hw >> 13) == 0b000 and (hw >> 11) & 0x3 != 0b11:
            sub_op = (hw >> 11) & 0x3
            offset5 = (hw >> 6) & 0x1F
            rs = (hw >> 3) & 0x7
            rd = hw & 0x7
            if sub_op == 0b00:
                if offset5 == 0:
                    mnemonic = f"MOV r{rd}, r{rs}"
                else:
                    mnemonic = f"LSL r{rd}, r{rs}, #{offset5}"
                    if offset5 == 28:
                        annotation = "  ; *** SHIFT BY 28 = bits 28-31 check ***"
                    elif offset5 == 2:
                        annotation = "  ; *4 (word index)"
            elif sub_op == 0b01:
                mnemonic = f"LSR r{rd}, r{rs}, #{offset5 if offset5 else 32}"
                if offset5 == 28:
                    annotation = "  ; *** SHIFT BY 28 = bits 28-31 check ***"
            elif sub_op == 0b10:
                mnemonic = f"ASR r{rd}, r{rs}, #{offset5 if offset5 else 32}"

        # Format 2: Add/sub register/immediate
        elif (hw >> 11) == 0b00011:
            i_bit = (hw >> 10) & 1
            op_bit = (hw >> 9) & 1
            rn_imm = (hw >> 6) & 0x7
            rs = (hw >> 3) & 0x7
            rd = hw & 0x7
            op_name = "SUB" if op_bit else "ADD"
            if i_bit:
                mnemonic = f"{op_name} r{rd}, r{rs}, #{rn_imm}"
            else:
                mnemonic = f"{op_name} r{rd}, r{rs}, r{rn_imm}"

        # Format 3: Immediate operations
        elif (hw >> 13) == 0b001:
            sub_op = (hw >> 11) & 0x3
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            ops = ["MOV", "CMP", "ADD", "SUB"]
            mnemonic = f"{ops[sub_op]} r{rd}, #0x{imm8:02X}"
            if imm8 == 0x24:
                annotation = "  ; 36 = offset to bufferA in gBattleResources"
            elif imm8 == 0x39:
                annotation = "  ; 57 = max command index"

        # Format 4: ALU
        elif (hw >> 10) == 0b010000:
            alu_op = (hw >> 6) & 0xF
            rs = (hw >> 3) & 0x7
            rd = hw & 0x7
            alu_names = ["AND", "EOR", "LSL", "LSR", "ASR", "ADC", "SBC", "ROR",
                         "TST", "NEG", "CMP", "CMN", "ORR", "MUL", "BIC", "MVN"]
            mnemonic = f"{alu_names[alu_op]} r{rd}, r{rs}"

        # Format 5: Hi register / BX
        elif (hw >> 10) == 0b010001:
            sub_op = (hw >> 8) & 0x3
            h1 = (hw >> 7) & 1
            h2 = (hw >> 6) & 1
            rs = ((h2 << 3) | ((hw >> 3) & 0x7))
            rd = ((h1 << 3) | (hw & 0x7))
            if sub_op == 0b00:
                mnemonic = f"ADD r{rd}, r{rs}"
            elif sub_op == 0b01:
                mnemonic = f"CMP r{rd}, r{rs}"
            elif sub_op == 0b10:
                mnemonic = f"MOV r{rd}, r{rs}"
            elif sub_op == 0b11:
                mnemonic = f"BX r{rs}" if h1 == 0 else f"BLX r{rs}"

        # Format 7: Load/store register offset
        elif (hw >> 12) == 0b0101 and ((hw >> 9) & 1) == 0:
            lb = (hw >> 10) & 0x3
            ro = (hw >> 6) & 0x7
            rb = (hw >> 3) & 0x7
            rd = hw & 0x7
            ops = ["STR", "STRB", "LDR", "LDRB"]
            mnemonic = f"{ops[lb]} r{rd}, [r{rb}, r{ro}]"

        # Format 8: Load/store sign-extended
        elif (hw >> 12) == 0b0101 and ((hw >> 9) & 1) == 1:
            sub = (hw >> 10) & 0x3
            ro = (hw >> 6) & 0x7
            rb = (hw >> 3) & 0x7
            rd = hw & 0x7
            ops = ["STRH", "LDSB", "LDRH", "LDSH"]
            mnemonic = f"{ops[sub]} r{rd}, [r{rb}, r{ro}]"

        # Format 9: Load/store immediate offset
        elif (hw >> 13) == 0b011:
            bl = (hw >> 12) & 1
            l = (hw >> 11) & 1
            offset5 = (hw >> 6) & 0x1F
            rb = (hw >> 3) & 0x7
            rd = hw & 0x7
            if bl == 0:
                off = offset5 * 4
                op_name = "LDR" if l else "STR"
                mnemonic = f"{op_name} r{rd}, [r{rb}, #0x{off:X}]"
            else:
                op_name = "LDRB" if l else "STRB"
                mnemonic = f"{op_name} r{rd}, [r{rb}, #0x{offset5:X}]"

        # Format 10: Halfword load/store
        elif (hw >> 12) == 0b1000:
            l = (hw >> 11) & 1
            offset5 = (hw >> 6) & 0x1F
            rb = (hw >> 3) & 0x7
            rd = hw & 0x7
            off = offset5 * 2
            op_name = "LDRH" if l else "STRH"
            mnemonic = f"{op_name} r{rd}, [r{rb}, #0x{off:X}]"

        # Format 11: SP-relative
        elif (hw >> 12) == 0b1001:
            l = (hw >> 11) & 1
            rd = (hw >> 8) & 0x7
            word8 = hw & 0xFF
            off = word8 * 4
            op_name = "LDR" if l else "STR"
            mnemonic = f"{op_name} r{rd}, [SP, #0x{off:X}]"

        # Format 12: Load address
        elif (hw >> 12) == 0b1010:
            sp = (hw >> 11) & 1
            rd = (hw >> 8) & 0x7
            word8 = hw & 0xFF
            off = word8 * 4
            src = "SP" if sp else "PC"
            mnemonic = f"ADD r{rd}, {src}, #0x{off:X}"

        # Format 13: SP adjust
        elif (hw >> 8) == 0b10110000:
            s = (hw >> 7) & 1
            imm7 = hw & 0x7F
            off = imm7 * 4
            op_name = "SUB" if s else "ADD"
            mnemonic = f"{op_name} SP, #0x{off:X}"

        # Format 16: Conditional branch
        elif (hw >> 12) == 0b1101:
            cond = (hw >> 8) & 0xF
            if cond == 0xF:
                mnemonic = f"SWI #0x{hw & 0xFF:02X}"
            elif cond == 0xE:
                mnemonic = f".hword 0x{hw:04X}  ; UNDEFINED"
            else:
                soff8 = hw & 0xFF
                if soff8 & 0x80:
                    soff8 -= 256
                target = addr + 4 + soff8 * 2
                cond_names = ["BEQ", "BNE", "BCS", "BCC", "BMI", "BPL", "BVS", "BVC",
                              "BHI", "BLS", "BGE", "BLT", "BGT", "BLE"]
                mnemonic = f"{cond_names[cond]} 0x{target:08X}"

        # Format 18: Unconditional branch
        elif (hw >> 11) == 0b11100:
            soff11 = hw & 0x7FF
            if soff11 & 0x400:
                soff11 -= 2048
            target = addr + 4 + soff11 * 2
            mnemonic = f"B 0x{target:08X}"

        else:
            mnemonic = f".hword 0x{hw:04X}"

        print(f"  0x{addr:08X}:  {hw:04X}       {mnemonic}{annotation}")
        i += 2

    print()


def compare_functions(rom):
    """Side-by-side comparison of the two functions."""
    print("\n" + "="*78)
    print("  SIDE-BY-SIDE: LinkOpponentBufferRunCommand vs OpponentBufferRunCommand")
    print("="*78)

    addr_link = 0x0807DC44
    addr_opp = 0x081BAD84

    print(f"\n  {'Offset':>6s}  {'Link (0x0807DC44)':>22s}  {'Opp (0x081BAD84)':>22s}  {'Match?':>6s}")
    print(f"  {'-'*6}  {'-'*22}  {'-'*22}  {'-'*6}")

    for i in range(0, 64, 2):
        hw_link = read_u16(rom, addr_link - 0x08000000 + i)
        hw_opp = read_u16(rom, addr_opp - 0x08000000 + i)
        match = "YES" if hw_link == hw_opp else "NO"
        print(f"  +{i:4d}   0x{hw_link:04X}                  0x{hw_opp:04X}                  {match}")

    # Resolve literal pools for both
    print(f"\n  Literal pool comparison:")
    link_pools = [0x0807DC7C, 0x0807DC80, 0x0807DC84, 0x0807DC88, 0x0807DC8C]
    opp_pools = [0x081BADBC, 0x081BADC0, 0x081BADC4, 0x081BADC8, 0x081BADCC]
    pool_names = ["r2 (execFlags)", "r1 (flagMasks)", "r0 (activeBattler)", "r0 (battleResources)", "r0 (jumpTable)"]

    for j, (lp, op, name) in enumerate(zip(link_pools, opp_pools, pool_names)):
        lv = resolve_literal(rom, lp)
        ov = resolve_literal(rom, op)
        lsym = annotate_value(lv) if lv else ""
        osym = annotate_value(ov) if ov else ""
        match = "SAME" if lv == ov else "DIFF"
        print(f"  Pool[{j}] {name}:")
        print(f"    Link: 0x{lv:08X} {lsym}")
        print(f"    Opp:  0x{ov:08X} {osym}")
        print(f"    -> {match}")


def analyze_exec_flag_check(rom):
    """Deep analysis of how exec flags are checked."""
    print("\n" + "="*78)
    print("  DEEP ANALYSIS: Exec Flag Check Logic")
    print("="*78)

    # Both functions have identical code for the first ~50 bytes
    # Let's trace the logic:
    addr = 0x0807DC44

    # Resolve literal pool entries
    pool_r2 = resolve_literal(rom, 0x0807DC7C)  # LDR r2
    pool_r1 = resolve_literal(rom, 0x0807DC80)  # LDR r1
    pool_r0 = resolve_literal(rom, 0x0807DC84)  # LDR r0

    print(f"""
  Function entry: PUSH {{lr}}

  Step 1: Load addresses
    LDR r2, [pool] = 0x{pool_r2:08X}  ({annotate_value(pool_r2)})
    LDR r1, [pool] = 0x{pool_r1:08X}  ({annotate_value(pool_r1)})
    LDR r0, [pool] = 0x{pool_r0:08X}  ({annotate_value(pool_r0)})

  Step 2: Get active battler and compute mask
    LDRB r3, [r0]          ; r3 = *0x{pool_r0:08X} = gActiveBattler
    LSL r0, r3, #2         ; r0 = battler * 4  (index into 32-bit array)
    ADD r0, r0, r1         ; r0 = &flagMasks[battler]  (0x{pool_r1:08X} + battler*4)

  Step 3: Check exec flags
    LDR r1, [r2]           ; r1 = *0x{pool_r2:08X} = gBattleControllerExecFlags
    LDR r0, [r0]           ; r0 = flagMasks[battler]
    AND r1, r0             ; r1 = execFlags & mask
    CMP r1, #0
    BEQ exit               ; if (execFlags & mask) == 0: skip to exit (function end)
""")

    # Now check what's at pool_r1 (the flag masks table)
    print(f"  Flag Masks Table at 0x{pool_r1:08X}:")
    for battler in range(4):
        mask_addr = pool_r1 + battler * 4
        mask_val = resolve_literal(rom, mask_addr)
        if mask_val is not None:
            print(f"    flagMasks[{battler}] = 0x{mask_val:08X}  (bits: {mask_val:032b})")
        else:
            print(f"    flagMasks[{battler}] = ??? (address 0x{mask_addr:08X} out of ROM range)")

    # Check the LSL #28 in the nearby IsBattleControllerActiveOnLocal function
    print(f"""
  CRITICAL OBSERVATION:
  ---------------------
  The exec flag check in LinkOpponentBufferRunCommand (and OpponentBufferRunCommand)
  does NOT use LSL/LSR #28.  Instead it:
    1. Loads gBattleControllerExecFlags (32-bit value at 0x{pool_r2:08X})
    2. Loads a per-battler mask from a table at 0x{pool_r1:08X}
    3. ANDs them together
    4. Checks if result is non-zero

  This means the exec flag bits depend on the MASK TABLE values.
  If mask[0]=0x1, mask[1]=0x2, mask[2]=0x4, mask[3]=0x8, then it checks bits 0-3.
  If mask[0]=0x10000000, etc., then it checks bits 28-31.

  Let's look at the mask table to determine which bits are used.
""")

    # Also check: the LSL #28 at 0x08040F08
    print(f"  Nearby function at ~0x08040EFC (part of exec flag handling):")
    print(f"  At 0x08040F08: LSL r0, r0, #28")
    print(f"  This function appears to be a DIFFERENT exec flag check that uses LSL #28")
    print(f"  to isolate bits 0-3 (shift left 28, which pushes bits 4-31 off the top,")
    print(f"  leaving only bits 0-3 in bits 28-31).")

    # Let's also check what's after the exec flag check (the dispatch)
    pool_res = resolve_literal(rom, 0x0807DC88)
    pool_jt = resolve_literal(rom, 0x0807DC8C)
    print(f"""
  Step 4: Dispatch to command handler (if exec flags set):
    LDR r0, [pool] = 0x{pool_res:08X}  ({annotate_value(pool_res)})
    LDR r0, [r0]           ; r0 = *gBattleResources (pointer to struct)
    LSL r1, r3, #9         ; r1 = battler * 512  (bufferA is 256 bytes per battler? => 512)
    ADD r0, #0x24           ; r0 = gBattleResources + 0x24  (offset to bufferA pointer)
    ADD r1, r0, r1         ; r1 = &(gBattleResources->bufferA) + battler*512
    LDRB r0, [r1]          ; r0 = bufferA[battler][0]  (command byte)
    CMP r0, #0x39           ; compare with max command (57)
    BHI default_handler    ; if > 57: go to default

    LDR r0, [pool] = 0x{pool_jt:08X}  ({annotate_value(pool_jt)})
    LDRB r1, [r1]          ; r1 = command byte again
    LSL r1, r1, #2         ; r1 = command * 4
    ADD r1, r1, r0         ; r1 = &jumpTable[command]
    LDR r0, [r1]           ; r0 = jumpTable[command]  (function pointer)
    BL 0x083458B0           ; call via helper (function pointer call trampoline)
""")

    # Check jump table difference
    print(f"  Jump Table Comparison:")
    print(f"    Link: 0x{pool_jt:08X}")
    opp_jt = resolve_literal(rom, 0x081BADCC)
    print(f"    Opp:  0x{opp_jt:08X}")
    if pool_jt != opp_jt:
        print(f"    DIFFERENT! These functions use different jump tables.")
        # Read first few entries
        print(f"\n    Link jump table (first 10 entries):")
        for j in range(10):
            entry = resolve_literal(rom, pool_jt + j * 4)
            if entry:
                sym = annotate_value(entry) or annotate_value(entry & ~1)
                print(f"      [{j:2d}] = 0x{entry:08X}  {sym}")
        print(f"\n    Opp jump table (first 10 entries):")
        for j in range(10):
            entry = resolve_literal(rom, opp_jt + j * 4)
            if entry:
                sym = annotate_value(entry) or annotate_value(entry & ~1)
                print(f"      [{j:2d}] = 0x{entry:08X}  {sym}")


def analyze_flag_mask_table(rom):
    """Analyze the flag mask table in detail."""
    print("\n" + "="*78)
    print("  FLAG MASK TABLE ANALYSIS")
    print("="*78)

    # The mask table address from LinkOpponentBufferRunCommand
    # pool_r1 at 0x0807DC80
    mask_table_addr = resolve_literal(rom, 0x0807DC80)
    print(f"\n  Mask table address: 0x{mask_table_addr:08X}")

    if mask_table_addr >= 0x08000000 and mask_table_addr < 0x0A000000:
        # It's in ROM, read it
        print(f"  (In ROM, reading directly)\n")
        for battler in range(4):
            file_off = (mask_table_addr + battler * 4) - 0x08000000
            if file_off + 4 <= len(rom):
                mask = read_u32(rom, file_off)
                print(f"  flagMasks[{battler}] = 0x{mask:08X}")
                print(f"    Binary: {mask:032b}")
                # Identify which bits are set
                bits = []
                for b in range(32):
                    if mask & (1 << b):
                        bits.append(b)
                print(f"    Set bits: {bits}")
                if bits:
                    if max(bits) <= 3:
                        print(f"    -> Uses bits 0-3 (low nibble)")
                    elif min(bits) >= 28:
                        print(f"    -> Uses bits 28-31 (high nibble)")
                    else:
                        print(f"    -> Uses mixed bit positions")
    else:
        print(f"  Address 0x{mask_table_addr:08X} is in RAM - cannot read from ROM file.")
        print(f"  This would need to be read at runtime.")

    # Also check the OpponentBufferRunCommand's mask table
    opp_mask_table = resolve_literal(rom, 0x081BADC0)
    print(f"\n  OpponentBufferRunCommand mask table: 0x{opp_mask_table:08X}")
    if mask_table_addr == opp_mask_table:
        print(f"  SAME table as LinkOpponentBufferRunCommand.")
    else:
        print(f"  DIFFERENT table! (Link=0x{mask_table_addr:08X}, Opp=0x{opp_mask_table:08X})")


def main():
    global rom_data_full

    print(f"ROM path: {ROM_PATH}")
    if not os.path.exists(ROM_PATH):
        print(f"ERROR: ROM file not found at {ROM_PATH}")
        sys.exit(1)

    rom_size = os.path.getsize(ROM_PATH)
    print(f"ROM size: {rom_size} bytes (0x{rom_size:X})\n")

    with open(ROM_PATH, "rb") as f:
        rom = f.read()

    # Make available globally for decode_thumb_instruction literal pool lookups
    rom_data_full = rom

    # 1. Disassemble LinkOpponentBufferRunCommand
    disasm_annotated(rom, 0x0807DC44, 96, "LinkOpponentBufferRunCommand (0x0807DC45 with THUMB bit)")

    # 2. Disassemble OpponentBufferRunCommand
    disasm_annotated(rom, 0x081BAD84, 96, "OpponentBufferRunCommand (0x081BAD85 with THUMB bit)")

    # 3. Context: function before LinkOpponent
    disasm_annotated(rom, 0x0807DC28, 28, "Function just before LinkOpponentBufferRunCommand")

    # 4. Context: what's at 0x08040EFC (exec flag checker with LSL #28)
    disasm_annotated(rom, 0x08040EF0, 80, "Exec flag area around 0x08040EFC (has LSL #28)")

    # 5. Side-by-side comparison
    compare_functions(rom)

    # 6. Deep analysis
    analyze_exec_flag_check(rom)

    # 7. Flag mask table
    analyze_flag_mask_table(rom)

    # 8. Default handler (the BL at the end for command > 57)
    print("\n" + "="*78)
    print("  DEFAULT HANDLER (command > 57)")
    print("="*78)
    # Link version branches to 0x0807E910
    disasm_annotated(rom, 0x0807E910, 48, "LinkOpponent default handler (0x0807E910)")
    # Opp version branches to 0x081BB944
    disasm_annotated(rom, 0x081BB944, 48, "Opponent default handler (0x081BB944)")


if __name__ == "__main__":
    main()
