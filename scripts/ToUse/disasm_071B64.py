#!/usr/bin/env python3
"""
Disassemble THUMB code at ROM offset 0x71B64 (address 0x08071B65)
from Pokemon Run & Bun ROM.

Context: This is a battle controller function (likely in battle_controller_player.c).
The master player gets stuck here during DoBattleIntro with exec flag=0x01 for battler 0.

Key things to check:
1. Does it check gBattleTypeFlags (0x02023364) for BATTLE_TYPE_LINK (bit 2)?
2. Does it call PrepareBufferDataTransferLink?
3. Does it read GetBlockReceivedStatus?
4. Does it check gReceivedRemoteLinkPlayers?
5. What are the BL (branch-link) calls?
"""

import struct
import sys
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses for cross-referencing
KNOWN_ADDRESSES = {
    0x02023364: "gBattleTypeFlags",
    0x020233E0: "gBattleControllerExecFlags",
    0x020233FC: "gBattleMons",
    0x0202370E: "gBattleCommunication",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x02023A0C: "gBattleStruct (ptr)",
    0x0201604C: "GetBlockReceivedStatus?",
    0x03005D70: "gBattlerControllerFuncs (IWRAM)",
    0x030022C0: "gMain (IWRAM)",
    0x030022C4: "gMain.callback2 (IWRAM)",
    0x080363C1: "CB2_InitBattle",
    0x0803648D: "CB2_InitBattleInternal",
    0x08037B45: "CB2_HandleStartBattle",
    0x0803816D: "BattleMainCB2",
    0x08094815: "CB2_BattleMain(?)",
    0x08000544: "SetMainCallback2",
}

# THUMB instruction decoding helpers
def decode_thumb(hw, pc):
    """Decode a single 16-bit THUMB instruction at the given PC."""
    op = (hw >> 11) & 0x1F

    # Format 1: Move shifted register
    if op in (0, 1, 2):
        opnames = {0: "LSL", 1: "LSR", 2: "ASR"}
        offset5 = (hw >> 6) & 0x1F
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        return f"{opnames[op]} r{rd}, r{rs}, #{offset5}"

    # Format 2: Add/subtract
    if op == 3:
        sub_op = (hw >> 9) & 0x3
        rn_imm = (hw >> 6) & 0x7
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        if sub_op == 0:
            return f"ADD r{rd}, r{rs}, r{rn_imm}"
        elif sub_op == 1:
            return f"SUB r{rd}, r{rs}, r{rn_imm}"
        elif sub_op == 2:
            return f"ADD r{rd}, r{rs}, #{rn_imm}"
        else:
            return f"SUB r{rd}, r{rs}, #{rn_imm}"

    # Format 3: Move/compare/add/subtract immediate
    if op in (4, 5, 6, 7):
        opnames = {4: "MOV", 5: "CMP", 6: "ADD", 7: "SUB"}
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        return f"{opnames[op]} r{rd}, #0x{imm8:02X} (={imm8})"

    # Format 4: ALU operations
    if (hw >> 10) == 0x10:
        alu_op = (hw >> 6) & 0xF
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        alu_names = {
            0: "AND", 1: "EOR", 2: "LSL", 3: "LSR",
            4: "ASR", 5: "ADC", 6: "SBC", 7: "ROR",
            8: "TST", 9: "NEG", 10: "CMP", 11: "CMN",
            12: "ORR", 13: "MUL", 14: "BIC", 15: "MVN"
        }
        return f"{alu_names[alu_op]} r{rd}, r{rs}"

    # Format 5: Hi register operations / BX
    if (hw >> 10) == 0x11:
        sub_op = (hw >> 8) & 0x3
        h1 = (hw >> 7) & 1
        h2 = (hw >> 6) & 1
        rs = ((hw >> 3) & 0x7) | (h2 << 3)
        rd = (hw & 0x7) | (h1 << 3)
        if sub_op == 0:
            return f"ADD r{rd}, r{rs}"
        elif sub_op == 1:
            return f"CMP r{rd}, r{rs}"
        elif sub_op == 2:
            return f"MOV r{rd}, r{rs}"
        else:
            if rs == 14:
                return f"BX lr"
            return f"BX r{rs}"

    # Format 6: PC-relative load
    if op == 9:
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        target = ((pc + 4) & ~2) + imm8 * 4
        return f"LDR r{rd}, [PC, #0x{imm8*4:X}] ; =>[0x{target:08X}]"

    # Format 7: Load/store with register offset
    if (hw >> 12) == 5 and not ((hw >> 9) & 1):
        opcode = (hw >> 10) & 0x3
        ro = (hw >> 6) & 0x7
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        if opcode == 0:
            return f"STR r{rd}, [r{rb}, r{ro}]"
        elif opcode == 1:
            return f"STRB r{rd}, [r{rb}, r{ro}]"
        elif opcode == 2:
            return f"LDR r{rd}, [r{rb}, r{ro}]"
        else:
            return f"LDRB r{rd}, [r{rb}, r{ro}]"

    # Format 8: Load/store sign-extended byte/halfword
    if (hw >> 12) == 5 and ((hw >> 9) & 1):
        opcode = (hw >> 10) & 0x3
        ro = (hw >> 6) & 0x7
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        names = {0: "STRH", 1: "LDSB", 2: "LDRH", 3: "LDSH"}
        return f"{names[opcode]} r{rd}, [r{rb}, r{ro}]"

    # Format 9: Load/store with immediate offset
    if op in (0xC, 0xD, 0xE, 0xF):
        bl = (hw >> 11) & 1
        byte_flag = (hw >> 12) & 1
        offset5 = (hw >> 6) & 0x1F
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        if byte_flag:
            off = offset5
            if bl:
                return f"LDRB r{rd}, [r{rb}, #0x{off:X}]"
            else:
                return f"STRB r{rd}, [r{rb}, #0x{off:X}]"
        else:
            off = offset5 * 4
            if bl:
                return f"LDR r{rd}, [r{rb}, #0x{off:X}]"
            else:
                return f"STR r{rd}, [r{rb}, #0x{off:X}]"

    # Format 10: Load/store halfword
    if (hw >> 12) == 8:
        bl = (hw >> 11) & 1
        offset5 = (hw >> 6) & 0x1F
        off = offset5 * 2
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        if bl:
            return f"LDRH r{rd}, [r{rb}, #0x{off:X}]"
        else:
            return f"STRH r{rd}, [r{rb}, #0x{off:X}]"

    # Format 11: SP-relative load/store
    if (hw >> 12) == 9:
        bl = (hw >> 11) & 1
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        off = imm8 * 4
        if bl:
            return f"LDR r{rd}, [SP, #0x{off:X}]"
        else:
            return f"STR r{rd}, [SP, #0x{off:X}]"

    # Format 12: Load address (ADD rd, PC/SP, #imm)
    if (hw >> 12) == 0xA:
        sp = (hw >> 11) & 1
        rd = (hw >> 8) & 0x7
        imm8 = hw & 0xFF
        off = imm8 * 4
        if sp:
            return f"ADD r{rd}, SP, #0x{off:X}"
        else:
            target = ((pc + 4) & ~2) + off
            return f"ADD r{rd}, PC, #0x{off:X} ; =0x{target:08X}"

    # Format 13: Add offset to stack pointer
    if (hw & 0xFF00) == 0xB000:
        sign = (hw >> 7) & 1
        imm7 = hw & 0x7F
        off = imm7 * 4
        if sign:
            return f"SUB SP, #0x{off:X}"
        else:
            return f"ADD SP, #0x{off:X}"

    # Format 14: Push/pop registers
    if (hw & 0xF600) == 0xB400:
        pop = (hw >> 11) & 1
        r = (hw >> 8) & 1
        rlist = hw & 0xFF
        regs = []
        for i in range(8):
            if rlist & (1 << i):
                regs.append(f"r{i}")
        if r:
            regs.append("lr" if not pop else "pc")
        regstr = ", ".join(regs)
        if pop:
            return f"POP {{{regstr}}}"
        else:
            return f"PUSH {{{regstr}}}"

    # Format 15: Multiple load/store
    if (hw >> 12) == 0xC:
        load = (hw >> 11) & 1
        rb = (hw >> 8) & 0x7
        rlist = hw & 0xFF
        regs = []
        for i in range(8):
            if rlist & (1 << i):
                regs.append(f"r{i}")
        regstr = ", ".join(regs)
        if load:
            return f"LDMIA r{rb}!, {{{regstr}}}"
        else:
            return f"STMIA r{rb}!, {{{regstr}}}"

    # Format 16: Conditional branch
    if (hw >> 12) == 0xD:
        cond = (hw >> 8) & 0xF
        if cond == 0xF:
            return f"SWI #0x{hw & 0xFF:02X}"
        if cond < 0xE:
            cond_names = {
                0: "BEQ", 1: "BNE", 2: "BCS", 3: "BCC",
                4: "BMI", 5: "BPL", 6: "BVS", 7: "BVC",
                8: "BHI", 9: "BLS", 10: "BGE", 11: "BLT",
                12: "BGT", 13: "BLE"
            }
            offset = hw & 0xFF
            if offset & 0x80:
                offset = offset - 256
            target = pc + 4 + offset * 2
            name = KNOWN_ADDRESSES.get(target | 1, "")
            extra = f"  ; {name}" if name else ""
            return f"{cond_names[cond]} 0x{target:08X}{extra}"

    # Format 17: Undefined / SWI already handled above

    # Format 18: Unconditional branch
    if (hw >> 11) == 0x1C:
        offset = hw & 0x7FF
        if offset & 0x400:
            offset = offset - 2048
        target = pc + 4 + offset * 2
        name = KNOWN_ADDRESSES.get(target | 1, "")
        extra = f"  ; {name}" if name else ""
        return f"B 0x{target:08X}{extra}"

    # Format 19: BL/BLX (two-instruction sequence) - first half
    if (hw >> 11) == 0x1E:
        offset_hi = hw & 0x7FF
        if offset_hi & 0x400:
            offset_hi = offset_hi | 0xFFFFF800  # sign extend
        return f"BL_HI offset_hi=0x{offset_hi & 0x7FF:03X} (sign={1 if offset_hi < 0 else 0})", offset_hi

    # Format 19: BL second half
    if (hw >> 11) == 0x1F:
        offset_lo = hw & 0x7FF
        return f"BL_LO offset_lo=0x{offset_lo:03X}", None

    return f"??? (0x{hw:04X})", None


def decode_bl_pair(hw1, hw2, pc):
    """Decode a THUMB BL instruction pair."""
    offset_hi = hw1 & 0x7FF
    if offset_hi & 0x400:
        offset_hi |= 0xFFFFF800  # sign extend to 32-bit
    offset_lo = hw2 & 0x7FF

    target = pc + 4 + (offset_hi << 12) + (offset_lo << 1)
    target &= 0xFFFFFFFF

    name = KNOWN_ADDRESSES.get(target | 1, "")
    if not name:
        name = KNOWN_ADDRESSES.get(target & ~1, "")
    extra = f"  ; {name}" if name else ""

    return target, extra


def disassemble_range(rom_data, rom_offset, size, base_addr):
    """Disassemble THUMB code from ROM data."""
    print(f"\n{'='*80}")
    print(f"THUMB Disassembly: 0x{base_addr:08X} - 0x{base_addr + size:08X}")
    print(f"ROM offset: 0x{rom_offset:06X} - 0x{rom_offset + size:06X}")
    print(f"{'='*80}\n")

    i = 0
    bl_targets = []
    literal_pool_refs = []

    while i < size:
        pc = base_addr + i
        hw = struct.unpack_from('<H', rom_data, rom_offset + i)[0]

        # Check for BL pair
        is_bl_hi = (hw >> 11) == 0x1E
        is_bl_lo_next = False
        if is_bl_hi and i + 2 < size:
            hw2 = struct.unpack_from('<H', rom_data, rom_offset + i + 2)[0]
            is_bl_lo_next = (hw2 >> 11) == 0x1F

        if is_bl_hi and is_bl_lo_next:
            target, extra = decode_bl_pair(hw, hw2, pc)
            bl_targets.append((pc, target))
            print(f"  0x{pc:08X}:  {hw:04X} {hw2:04X}   BL 0x{target:08X}{extra}")
            i += 4
            continue

        # Check for PC-relative LDR (literal pool reference)
        op = (hw >> 11) & 0x1F
        if op == 9:  # LDR Rd, [PC, #imm]
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            lit_addr = ((pc + 4) & ~2) + imm8 * 4
            lit_rom_offset = (lit_addr & ~0x08000000)
            if lit_rom_offset < len(rom_data) - 3:
                lit_value = struct.unpack_from('<I', rom_data, lit_rom_offset)[0]
                name = KNOWN_ADDRESSES.get(lit_value, "")
                if not name and (lit_value & 1):
                    name = KNOWN_ADDRESSES.get(lit_value & ~1, "")
                extra = f"  ; {name}" if name else ""
                literal_pool_refs.append((pc, lit_addr, lit_value))
                print(f"  0x{pc:08X}:  {hw:04X}       LDR r{rd}, [PC, #0x{imm8*4:X}] ; =>[0x{lit_addr:08X}] = 0x{lit_value:08X}{extra}")
            else:
                result = decode_thumb(hw, pc)
                if isinstance(result, tuple):
                    result = result[0]
                print(f"  0x{pc:08X}:  {hw:04X}       {result}")
            i += 2
            continue

        result = decode_thumb(hw, pc)
        if isinstance(result, tuple):
            result = result[0]

        print(f"  0x{pc:08X}:  {hw:04X}       {result}")
        i += 2

    return bl_targets, literal_pool_refs


def scan_literal_pool(rom_data, rom_offset, size, base_addr):
    """Scan for potential literal pool data (32-bit constants) after code."""
    print(f"\n--- Literal Pool Scan (0x{base_addr:08X} - 0x{base_addr + size:08X}) ---")
    for i in range(0, size, 4):
        if rom_offset + i + 3 >= len(rom_data):
            break
        val = struct.unpack_from('<I', rom_data, rom_offset + i)[0]
        addr = base_addr + i
        name = KNOWN_ADDRESSES.get(val, "")
        if not name and (val & 1):
            name = KNOWN_ADDRESSES.get(val & ~1, "")

        # Show if it looks like a known address or is in interesting range
        interesting = False
        if name:
            interesting = True
        elif 0x02000000 <= val <= 0x0203FFFF:
            interesting = True
            name = "EWRAM"
        elif 0x03000000 <= val <= 0x03007FFF:
            interesting = True
            name = "IWRAM"
        elif 0x08000000 <= val <= 0x09FFFFFF:
            interesting = True
            name = "ROM"

        if interesting:
            print(f"  0x{addr:08X}: 0x{val:08X}  {name}")


def main():
    if not os.path.exists(ROM_PATH):
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    with open(ROM_PATH, 'rb') as f:
        rom = f.read()

    print(f"ROM size: {len(rom)} bytes (0x{len(rom):X})")
    print(f"\nTarget: 0x08071B65 (cart0 offset 0x00071B64)")
    print(f"Context: Battle controller function stuck during DoBattleIntro")

    # =====================================================
    # 1. Disassemble the target function at 0x08071B64
    # =====================================================
    print("\n" + "#"*80)
    print("# SECTION 1: Target function at 0x08071B64 (~192 bytes)")
    print("#"*80)
    bl_targets_1, lit_refs_1 = disassemble_range(rom, 0x71B64, 192, 0x08071B64)

    # Also scan the literal pool area after the function
    print("\n--- Literal pool area after function ---")
    scan_literal_pool(rom, 0x71B64 + 192, 64, 0x08071B64 + 192)

    # =====================================================
    # 2. Wider context: 0x08071B00 - 0x08071C00
    # =====================================================
    print("\n" + "#"*80)
    print("# SECTION 2: Wider context 0x08071B00 - 0x08071C00 (256 bytes)")
    print("#"*80)
    bl_targets_2, lit_refs_2 = disassemble_range(rom, 0x71B00, 256, 0x08071B00)

    # Scan literal pool after this range
    print("\n--- Literal pool area 0x08071C00 - 0x08071C40 ---")
    scan_literal_pool(rom, 0x71C00, 64, 0x08071C00)

    # =====================================================
    # 3. Summary of BL targets
    # =====================================================
    all_bl_targets = list(set(bl_targets_1 + bl_targets_2))
    all_bl_targets.sort(key=lambda x: x[0])

    print("\n" + "#"*80)
    print("# SECTION 3: Summary of BL call targets")
    print("#"*80)
    for call_pc, target in all_bl_targets:
        name = KNOWN_ADDRESSES.get(target | 1, "")
        if not name:
            name = KNOWN_ADDRESSES.get(target & ~1, "")
        if not name:
            name = "UNKNOWN"
        print(f"  BL at 0x{call_pc:08X} -> 0x{target:08X}  ({name})")

    # =====================================================
    # 4. Summary of literal pool references
    # =====================================================
    all_lit_refs = list(set(lit_refs_1 + lit_refs_2))
    all_lit_refs.sort(key=lambda x: x[0])

    print("\n" + "#"*80)
    print("# SECTION 4: Literal pool values referenced")
    print("#"*80)
    for instr_pc, pool_addr, value in all_lit_refs:
        name = KNOWN_ADDRESSES.get(value, "")
        if not name and (value & 1):
            name = KNOWN_ADDRESSES.get(value & ~1, "")
        if not name:
            if 0x02000000 <= value <= 0x0203FFFF:
                name = "EWRAM"
            elif 0x03000000 <= value <= 0x03007FFF:
                name = "IWRAM"
            elif 0x08000000 <= value <= 0x09FFFFFF:
                name = "ROM"
        print(f"  At 0x{instr_pc:08X}: LDR from pool[0x{pool_addr:08X}] = 0x{value:08X}  ({name})")

    # =====================================================
    # 5. Check for BATTLE_TYPE_LINK pattern
    # =====================================================
    print("\n" + "#"*80)
    print("# SECTION 5: Checking for BATTLE_TYPE_LINK (0x02) checks")
    print("#"*80)

    # Check if gBattleTypeFlags is referenced
    btf_found = False
    for instr_pc, pool_addr, value in all_lit_refs:
        if value == 0x02023364:
            btf_found = True
            print(f"  FOUND: gBattleTypeFlags (0x02023364) referenced at 0x{instr_pc:08X}")

    if not btf_found:
        print("  NOT FOUND: gBattleTypeFlags (0x02023364) not directly referenced in this range")
        # Maybe it's loaded via another register - check broader
        print("  Checking if 0x02023364 appears anywhere in 0x71A00-0x71E00...")
        for offset in range(0x71A00, 0x71E00, 4):
            if offset + 3 < len(rom):
                val = struct.unpack_from('<I', rom, offset)[0]
                if val == 0x02023364:
                    print(f"    Found at ROM offset 0x{offset:06X} (addr 0x{0x08000000 + offset:08X})")

    # =====================================================
    # 6. Search for PlayerBufferExecCompleted pattern
    # =====================================================
    print("\n" + "#"*80)
    print("# SECTION 6: Searching for PlayerBufferExecCompleted")
    print("# (checks BATTLE_TYPE_LINK, calls PrepareBufferDataTransferLink)")
    print("#"*80)

    # PlayerBufferExecCompleted:
    # 1. Sets gBattlerControllerFuncs[battler] = PlayerBufferRunCommand
    # 2. Loads gBattleTypeFlags
    # 3. Tests bit 1 (BATTLE_TYPE_LINK = 0x02, but bit 1 in the flags)
    # 4. If set: calls GetMultiplayerId(), PrepareBufferDataTransferLink()
    # 5. If not: calls MarkBattleControllerIdleOnLocal()

    # Search for references to 0x02023364 in a wider area around 0x071B64
    print("\n  Searching for gBattleTypeFlags (0x02023364) references near 0x08071B64...")
    for offset in range(0x71800, 0x72000, 4):
        if offset + 3 < len(rom):
            val = struct.unpack_from('<I', rom, offset)[0]
            if val == 0x02023364:
                print(f"    Literal pool entry at ROM 0x{offset:06X} (addr 0x{0x08000000 + offset:08X})")
                # Find LDR instructions that could reference this
                pool_addr = 0x08000000 + offset
                for check_off in range(max(0, offset - 1024), offset, 2):
                    hw = struct.unpack_from('<H', rom, check_off)[0]
                    if (hw >> 11) == 9:  # LDR Rd, [PC, #imm]
                        pc = 0x08000000 + check_off
                        imm8 = hw & 0xFF
                        ref_addr = ((pc + 4) & ~2) + imm8 * 4
                        if ref_addr == pool_addr:
                            rd = (hw >> 8) & 0x7
                            print(f"      Referenced by LDR r{rd} at 0x{pc:08X}")

    # =====================================================
    # 7. Search for gBattleControllerExecFlags references
    # =====================================================
    print("\n  Searching for gBattleControllerExecFlags (0x020233E0) references near 0x08071B64...")
    for offset in range(0x71800, 0x72000, 4):
        if offset + 3 < len(rom):
            val = struct.unpack_from('<I', rom, offset)[0]
            if val == 0x020233E0:
                print(f"    Literal pool entry at ROM 0x{offset:06X} (addr 0x{0x08000000 + offset:08X})")
                pool_addr = 0x08000000 + offset
                for check_off in range(max(0, offset - 1024), offset, 2):
                    hw = struct.unpack_from('<H', rom, check_off)[0]
                    if (hw >> 11) == 9:
                        pc = 0x08000000 + check_off
                        imm8 = hw & 0xFF
                        ref_addr = ((pc + 4) & ~2) + imm8 * 4
                        if ref_addr == pool_addr:
                            rd = (hw >> 8) & 0x7
                            print(f"      Referenced by LDR r{rd} at 0x{pc:08X}")

    # =====================================================
    # 8. Extended disassembly: function before 0x08071B64
    # =====================================================
    print("\n" + "#"*80)
    print("# SECTION 8: Preceding function area 0x08071A80 - 0x08071B64")
    print("#"*80)
    disassemble_range(rom, 0x71A80, 0xE4, 0x08071A80)

    # =====================================================
    # 9. Check gBattlerControllerFuncs references
    # =====================================================
    print("\n" + "#"*80)
    print("# SECTION 9: gBattlerControllerFuncs (0x03005D70) references near target")
    print("#"*80)
    for offset in range(0x71800, 0x72000, 4):
        if offset + 3 < len(rom):
            val = struct.unpack_from('<I', rom, offset)[0]
            if val == 0x03005D70:
                print(f"  Literal pool entry at ROM 0x{offset:06X} (addr 0x{0x08000000 + offset:08X})")
                pool_addr = 0x08000000 + offset
                for check_off in range(max(0, offset - 1024), offset, 2):
                    hw = struct.unpack_from('<H', rom, check_off)[0]
                    if (hw >> 11) == 9:
                        pc = 0x08000000 + check_off
                        imm8 = hw & 0xFF
                        ref_addr = ((pc + 4) & ~2) + imm8 * 4
                        if ref_addr == pool_addr:
                            rd = (hw >> 8) & 0x7
                            print(f"    Referenced by LDR r{rd} at 0x{pc:08X}")

    # =====================================================
    # 10. Look further ahead: 0x08071C00 - 0x08071E00
    # =====================================================
    print("\n" + "#"*80)
    print("# SECTION 10: Following code 0x08071C00 - 0x08071D00")
    print("#"*80)
    disassemble_range(rom, 0x71C00, 256, 0x08071C00)
    scan_literal_pool(rom, 0x71D00, 64, 0x08071D00)


if __name__ == '__main__':
    main()
