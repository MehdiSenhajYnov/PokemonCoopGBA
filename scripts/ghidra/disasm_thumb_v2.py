#!/usr/bin/env python3
"""
THUMB disassembler v2 - fixed literal pool resolution + targeted analysis.
"""

import struct
import sys

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
    0x02023A18: "gBattleResources",
    0x02023A95: "gPlayerPartyCount",
    0x02023A98: "gPlayerParty",
    0x02023CF0: "gEnemyParty",
    0x020229E8: "gLinkPlayers",
    0x030030FC: "gWirelessCommType",
    0x03003124: "gReceivedRemoteLinkPlayers",
    0x0300307C: "gBlockReceivedStatus",
    0x03005D90: "gRngValue",
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
    0x0800A4B0: "GetMultiplayerId",
}


def read_rom(path):
    with open(path, "rb") as f:
        return f.read()


def u16(rom, offset):
    if offset < 0 or offset + 1 >= len(rom):
        return 0
    return struct.unpack_from("<H", rom, offset)[0]


def u32(rom, offset):
    if offset < 0 or offset + 3 >= len(rom):
        return 0
    return struct.unpack_from("<I", rom, offset)[0]


def gba_to_rom(addr):
    """Convert GBA address to ROM file offset."""
    if 0x08000000 <= addr < 0x0A000000:
        return addr - 0x08000000
    return None


def lookup_addr(val):
    for a in [val, val | 1, val & ~1]:
        if a in KNOWN_ADDRS:
            return KNOWN_ADDRS[a]
    # Check common memory regions
    if 0x02000000 <= val < 0x02040000:
        return f"EWRAM+0x{val-0x02000000:05X}"
    if 0x03000000 <= val < 0x03008000:
        return f"IWRAM+0x{val-0x03000000:04X}"
    if 0x04000000 <= val < 0x04000400:
        return f"IO_REG+0x{val-0x04000000:03X}"
    if 0x05000000 <= val < 0x05000400:
        return f"PALETTE"
    if 0x06000000 <= val < 0x06018000:
        return f"VRAM+0x{val-0x06000000:05X}"
    if 0x07000000 <= val < 0x07000400:
        return f"OAM"
    if 0x08000000 <= val < 0x0A000000:
        return f"ROM+0x{val-0x08000000:06X}"
    return None


def resolve_literal_pool(rom, pc, imm8):
    """Resolve LDR Rd,[PC,#imm] - the actual value loaded."""
    # PC = current instruction address + 4, word-aligned
    aligned_pc = (pc + 4) & ~3
    load_addr = aligned_pc + imm8 * 4
    rom_off = gba_to_rom(load_addr)
    if rom_off is not None and 0 <= rom_off < len(rom) - 3:
        val = u32(rom, rom_off)
        return load_addr, val
    # Try EWRAM addresses - we can't resolve at static analysis time
    return load_addr, None


def main():
    rom = read_rom(ROM_PATH)
    print(f"ROM: {ROM_PATH} ({len(rom)} bytes)\n")

    regions = [
        (0x0803816C, 110, "stuck_callback2 (0x0803816D)"),
        (0x08036D00, 256, "cb2_during_comm_processing (0x08036D01)"),
        (0x08094814, 48, "BattleMainCB2 (0x08094815) prologue check"),
        (0x08037B44, 200, "CB2_HandleStartBattle (0x08037B45) - start"),
    ]

    all_bl_targets = {}

    for base_addr, size, label in regions:
        print(f"\n{'='*90}")
        print(f"  {label}")
        print(f"  Address: 0x{base_addr:08X}  Cart0: 0x{base_addr-0x08000000:06X}  Size: {size} bytes")
        print(f"{'='*90}\n")

        pc = base_addr
        end_pc = base_addr + size
        bl_targets = []
        ldr_loads = []

        while pc < end_pc:
            rom_off = gba_to_rom(pc)
            if rom_off is None or rom_off >= len(rom) - 1:
                break
            hw = u16(rom, rom_off)
            hex_str = f"{hw:04X}"
            instr = ""
            comment = ""

            # BL (32-bit)
            if (hw >> 11) == 0x1E and rom_off + 2 < len(rom):
                hw2 = u16(rom, rom_off + 2)
                if (hw2 >> 11) in (0x1F, 0x1D):
                    offset_hi = hw & 0x7FF
                    if offset_hi & 0x400:
                        offset_hi -= 0x800
                    offset_lo = hw2 & 0x7FF
                    target = (pc + 4) + (offset_hi << 12) + (offset_lo << 1)
                    target &= 0xFFFFFFFF
                    is_blx = (hw2 >> 11) == 0x1D
                    if is_blx:
                        target &= 0xFFFFFFFC
                    name = lookup_addr(target)
                    name_str = f"  ; {name}" if name else ""
                    prefix = "BLX" if is_blx else "BL "
                    instr = f"{prefix}     0x{target:08X}{name_str}"
                    hex_str = f"{hw:04X} {hw2:04X}"
                    bl_targets.append((pc, target, name))
                    print(f"  0x{pc:08X}:  {hex_str:12s}  {instr}")
                    pc += 4
                    continue

            # PUSH
            if (hw >> 8) == 0xB4:
                regs = [f"R{i}" for i in range(8) if hw & (1<<i)]
                instr = f"PUSH    {{{', '.join(regs)}}}"
            elif (hw >> 8) == 0xB5:
                regs = [f"R{i}" for i in range(8) if hw & (1<<i)]
                regs.append("LR")
                instr = f"PUSH    {{{', '.join(regs)}}}"

            # POP
            elif (hw >> 8) == 0xBC:
                regs = [f"R{i}" for i in range(8) if hw & (1<<i)]
                instr = f"POP     {{{', '.join(regs)}}}"
            elif (hw >> 8) == 0xBD:
                regs = [f"R{i}" for i in range(8) if hw & (1<<i)]
                regs.append("PC")
                instr = f"POP     {{{', '.join(regs)}}}"
                comment = " <<< RETURN"

            # BX
            elif (hw & 0xFF80) == 0x4700:
                rm = (hw >> 3) & 0xF
                rn = ["R0","R1","R2","R3","R4","R5","R6","R7","R8","R9","R10","R11","R12","SP","LR","PC"][rm]
                instr = f"BX      {rn}"
                if rm == 14: comment = " <<< RETURN (BX LR)"
                if rm == 0: comment = " <<< indirect jump"

            # LDR Rd,[PC,#imm] - LITERAL POOL
            elif (hw >> 11) == 0x09:
                rd = (hw >> 8) & 0x7
                imm8 = hw & 0xFF
                load_addr, val = resolve_literal_pool(rom, pc, imm8)
                if val is not None:
                    name = lookup_addr(val)
                    name_str = f"  ({name})" if name else ""
                    instr = f"LDR     R{rd}, [PC, #0x{imm8*4:X}]  ; [0x{load_addr:08X}] = 0x{val:08X}{name_str}"
                    ldr_loads.append((pc, rd, val, name))
                else:
                    instr = f"LDR     R{rd}, [PC, #0x{imm8*4:X}]  ; [0x{load_addr:08X}]"

            # LDR Rd,[Rn,#imm]
            elif (hw >> 11) == 0x0D:
                imm = ((hw >> 6) & 0x1F) * 4
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"LDR     R{rd}, [R{rn}, #0x{imm:X}]"

            # LDRB Rd,[Rn,#imm]
            elif (hw >> 11) == 0x0F:
                imm = (hw >> 6) & 0x1F
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"LDRB    R{rd}, [R{rn}, #0x{imm:X}]"

            # LDRH Rd,[Rn,#imm]
            elif (hw >> 11) == 0x11:
                imm = ((hw >> 6) & 0x1F) * 2
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"LDRH    R{rd}, [R{rn}, #0x{imm:X}]"

            # STR Rd,[Rn,#imm]
            elif (hw >> 11) == 0x0C:
                imm = ((hw >> 6) & 0x1F) * 4
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"STR     R{rd}, [R{rn}, #0x{imm:X}]"

            # STRB Rd,[Rn,#imm]
            elif (hw >> 11) == 0x0E:
                imm = (hw >> 6) & 0x1F
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"STRB    R{rd}, [R{rn}, #0x{imm:X}]"

            # STRH Rd,[Rn,#imm]
            elif (hw >> 11) == 0x10:
                imm = ((hw >> 6) & 0x1F) * 2
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"STRH    R{rd}, [R{rn}, #0x{imm:X}]"

            # MOV Rd,#imm
            elif (hw >> 11) == 0x04:
                rd = (hw >> 8) & 0x7
                imm = hw & 0xFF
                instr = f"MOV     R{rd}, #0x{imm:X}"

            # CMP Rn,#imm
            elif (hw >> 11) == 0x05:
                rn = (hw >> 8) & 0x7
                imm = hw & 0xFF
                instr = f"CMP     R{rn}, #0x{imm:X}"

            # ADD Rd,#imm
            elif (hw >> 11) == 0x06:
                rd = (hw >> 8) & 0x7
                imm = hw & 0xFF
                instr = f"ADD     R{rd}, #0x{imm:X}"

            # SUB Rd,#imm
            elif (hw >> 11) == 0x07:
                rd = (hw >> 8) & 0x7
                imm = hw & 0xFF
                instr = f"SUB     R{rd}, #0x{imm:X}"

            # ADD/SUB SP
            elif (hw >> 8) == 0xB0:
                imm = (hw & 0x7F) * 4
                if hw & 0x80:
                    instr = f"SUB     SP, #0x{imm:X}"
                else:
                    instr = f"ADD     SP, #0x{imm:X}"

            # Conditional branch
            elif (hw >> 12) == 0xD:
                cond = (hw >> 8) & 0xF
                conds = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                         "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SWI"]
                if cond < 15:
                    offset = hw & 0xFF
                    if offset & 0x80: offset -= 0x100
                    target = pc + 4 + offset * 2
                    instr = f"{conds[cond]:7s} 0x{target & 0xFFFFFFFF:08X}"
                else:
                    instr = f"SWI     #0x{hw & 0xFF:X}"

            # Unconditional branch
            elif (hw >> 11) == 0x1C:
                offset = hw & 0x7FF
                if offset & 0x400: offset -= 0x800
                target = pc + 4 + offset * 2
                instr = f"B       0x{target & 0xFFFFFFFF:08X}"

            # LSL Rd,Rm,#imm
            elif (hw >> 11) == 0x00:
                imm = (hw >> 6) & 0x1F
                rm = (hw >> 3) & 0x7
                rd = hw & 0x7
                if hw == 0:
                    instr = "NOP"
                else:
                    instr = f"LSL     R{rd}, R{rm}, #{imm}"

            # LSR Rd,Rm,#imm
            elif (hw >> 11) == 0x01:
                imm = (hw >> 6) & 0x1F
                if imm == 0: imm = 32
                rm = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"LSR     R{rd}, R{rm}, #{imm}"

            # ALU format 4
            elif (hw >> 10) == 0x10:
                op = (hw >> 6) & 0xF
                rs = (hw >> 3) & 0x7
                rd = hw & 0x7
                ops = ["AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR",
                       "TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN"]
                instr = f"{ops[op]:7s} R{rd}, R{rs}"

            # Hi reg ops
            elif (hw >> 10) == 0x11:
                op = (hw >> 8) & 3
                h1 = (hw >> 7) & 1
                h2 = (hw >> 6) & 1
                rs = (h2 << 3) | ((hw >> 3) & 7)
                rd = (h1 << 3) | (hw & 7)
                rn = ["R0","R1","R2","R3","R4","R5","R6","R7","R8","R9","R10","R11","R12","SP","LR","PC"]
                if op == 0: instr = f"ADD     {rn[rd]}, {rn[rs]}"
                elif op == 1: instr = f"CMP     {rn[rd]}, {rn[rs]}"
                elif op == 2: instr = f"MOV     {rn[rd]}, {rn[rs]}"
                elif op == 3:
                    if h1: instr = f"BLX     {rn[rs]}"
                    else:
                        instr = f"BX      {rn[rs]}"
                        if rs == 14: comment = " <<< RETURN"

            # ADD Rd,Rn,Rm
            elif (hw >> 9) == 0x0C:
                rm = (hw >> 6) & 0x7
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"ADD     R{rd}, R{rn}, R{rm}"

            # ADD Rd,Rn,#imm3
            elif (hw >> 9) == 0x0E:
                imm = (hw >> 6) & 0x7
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"ADD     R{rd}, R{rn}, #{imm}"

            # SUB Rd,Rn,#imm3
            elif (hw >> 9) == 0x0F:
                imm = (hw >> 6) & 0x7
                rn = (hw >> 3) & 0x7
                rd = hw & 0x7
                instr = f"SUB     R{rd}, R{rn}, #{imm}"

            # LDR Rd,[SP,#imm]
            elif (hw >> 11) == 0x13:
                rd = (hw >> 8) & 0x7
                imm = (hw & 0xFF) * 4
                instr = f"LDR     R{rd}, [SP, #0x{imm:X}]"

            # STR Rd,[SP,#imm]
            elif (hw >> 11) == 0x12:
                rd = (hw >> 8) & 0x7
                imm = (hw & 0xFF) * 4
                instr = f"STR     R{rd}, [SP, #0x{imm:X}]"

            # ADD Rd,PC,#imm
            elif (hw >> 11) == 0x14:
                rd = (hw >> 8) & 0x7
                imm = (hw & 0xFF) * 4
                val = ((pc + 4) & ~3) + imm
                instr = f"ADD     R{rd}, PC, #0x{imm:X}  ; =0x{val:08X}"

            else:
                instr = f".hword  0x{hw:04X}"

            if not instr:
                instr = f".hword  0x{hw:04X}"

            print(f"  0x{pc:08X}:  {hex_str:12s}  {instr}{comment}")
            pc += 2

        # Print summary
        print(f"\n  --- BL Targets ---")
        for src, tgt, name in bl_targets:
            n = f" = {name}" if name else ""
            print(f"    0x{src:08X} -> 0x{tgt:08X}{n}")
        print(f"\n  --- Literal Pool Values ---")
        for src, rd, val, name in ldr_loads:
            n = f" = {name}" if name else ""
            print(f"    0x{src:08X}: R{rd} = 0x{val:08X}{n}")

        all_bl_targets[label] = bl_targets

    # ===== CROSS-REFERENCE ANALYSIS =====
    print(f"\n\n{'='*90}")
    print(f"  CROSS-REFERENCE ANALYSIS")
    print(f"{'='*90}\n")

    # 1. Check what SetMainCallback2 is called with at 0x080381CA
    print("--- What does SetMainCallback2 get called with at 0x080381CA? ---")
    print("  Looking at instruction before the BL at 0x080381CA:")
    # The LDR R0 at 0x080381C8 loads from literal pool
    pc_ldr = 0x080381C8
    hw_ldr = u16(rom, gba_to_rom(pc_ldr))
    if (hw_ldr >> 11) == 0x09:
        rd = (hw_ldr >> 8) & 0x7
        imm8 = hw_ldr & 0xFF
        load_addr, val = resolve_literal_pool(rom, pc_ldr, imm8)
        name = lookup_addr(val) if val else None
        print(f"  0x{pc_ldr:08X}: LDR R{rd}, [PC, #0x{imm8*4:X}] => [0x{load_addr:08X}] = 0x{val:08X}")
        if name:
            print(f"  Value name: {name}")
        if val == 0x08094815:
            print(f"  *** THIS IS BattleMainCB2! SetMainCallback2(BattleMainCB2) ***")
        else:
            print(f"  This is NOT BattleMainCB2 (0x08094815)")
            vname = lookup_addr(val) if val else "unknown"
            print(f"  It's 0x{val:08X} = {vname}")
            # Look up what that function is
            if val and 0x08000000 <= val < 0x0A000000:
                foff = gba_to_rom(val & ~1)
                first = u16(rom, foff)
                print(f"  First instruction at target: 0x{first:04X}")

    # 2. Check what SetMainCallback2 is called with at 0x0803825A
    print("\n--- What does SetMainCallback2 get called with at 0x0803825A? ---")
    print("  Context: R0 = [R0, #0x8] loaded at 0x08038258, R0 loaded from [PC] at 0x08038256")
    pc_ldr = 0x08038256
    hw_ldr = u16(rom, gba_to_rom(pc_ldr))
    if (hw_ldr >> 11) == 0x09:
        rd = (hw_ldr >> 8) & 0x7
        imm8 = hw_ldr & 0xFF
        load_addr, val = resolve_literal_pool(rom, pc_ldr, imm8)
        name = lookup_addr(val) if val else None
        print(f"  0x{pc_ldr:08X}: LDR R{rd}, [PC, #0x{imm8*4:X}] => [0x{load_addr:08X}] = 0x{val:08X}")
        if name:
            print(f"  Value: {name}")
        print(f"  Then: LDR R0, [R0, #0x8] => reads *(0x{val:08X} + 8)")
        if val:
            print(f"  This is gMain.savedCallback! (gMain + 0x08)")
            print(f"  So SetMainCallback2 is called with whatever savedCallback was set to before battle")

    # 3. Decode the jump table at 0x08036D34
    print("\n--- Jump table in cb2_during_comm_processing ---")
    print("  At 0x08036D2E: LDR R1, [PC, #0x10]")
    pc_ldr = 0x08036D2E
    hw_ldr = u16(rom, gba_to_rom(pc_ldr))
    imm8 = hw_ldr & 0xFF
    load_addr, val = resolve_literal_pool(rom, pc_ldr, imm8)
    print(f"  Jump table base: [0x{load_addr:08X}] = 0x{val:08X}")
    if val and 0x08000000 <= val < 0x0A000000:
        print(f"  Jump table entries (19 cases, 0x00-0x12):")
        for idx in range(19):
            entry_off = gba_to_rom(val) + idx * 4
            entry_val = u32(rom, entry_off)
            name = lookup_addr(entry_val)
            n = f"  ({name})" if name else ""
            print(f"    case {idx:2d} (0x{idx:02X}): 0x{entry_val:08X}{n}")

    # 4. Decode the jump table in CB2_HandleStartBattle
    print("\n--- Jump table in CB2_HandleStartBattle ---")
    pc_ldr = 0x08037B72
    hw_ldr = u16(rom, gba_to_rom(pc_ldr))
    imm8 = hw_ldr & 0xFF
    load_addr, val = resolve_literal_pool(rom, pc_ldr, imm8)
    print(f"  Jump table base: [0x{load_addr:08X}] = 0x{val:08X}")
    if val and 0x08000000 <= val < 0x0A000000:
        print(f"  Jump table entries (11 cases, 0x00-0x0A):")
        for idx in range(11):
            entry_off = gba_to_rom(val) + idx * 4
            entry_val = u32(rom, entry_off)
            name = lookup_addr(entry_val)
            n = f"  ({name})" if name else ""
            print(f"    case {idx:2d} (0x{idx:02X}): 0x{entry_val:08X}{n}")

    # 5. Check additional literal pools in stuck_callback2
    print("\n--- All literal pool values in stuck_callback2 (0x0803816C) ---")
    for pc_check in range(0x0803816C, 0x080381D4, 2):
        hw_check = u16(rom, gba_to_rom(pc_check))
        if (hw_check >> 11) == 0x09:
            rd = (hw_check >> 8) & 0x7
            imm8 = hw_check & 0xFF
            load_addr, val = resolve_literal_pool(rom, pc_check, imm8)
            name = lookup_addr(val) if val else None
            n = f"  ({name})" if name else ""
            print(f"  0x{pc_check:08X}: LDR R{rd} => 0x{val:08X}{n}" if val else f"  0x{pc_check:08X}: LDR R{rd} => [0x{load_addr:08X}]")

    # 6. Check what 0x081B7724 is (called from stuck callback)
    print("\n--- Function at 0x081B7724 (called from stuck_callback2) ---")
    off = gba_to_rom(0x081B7724)
    print(f"  First 16 bytes:")
    for j in range(0, 16, 2):
        hw_check = u16(rom, off + j)
        print(f"    0x{0x081B7724+j:08X}: {hw_check:04X}")

    # 7. Look for where 0x0803816D is stored in literal pools (who sets this as callback2?)
    print("\n--- Searching for 0x0803816D in ROM literal pools ---")
    target_bytes = struct.pack("<I", 0x0803816D)
    count = 0
    for off in range(0, min(len(rom), 0x200000), 4):
        if rom[off:off+4] == target_bytes:
            gba_addr = 0x08000000 + off
            print(f"  Found at 0x{gba_addr:08X} (cart0: 0x{off:06X})")
            # Find who references it
            for check_off in range(max(0, off - 1024), off, 2):
                hw_check = u16(rom, check_off)
                if (hw_check >> 11) == 0x09:
                    rd = (hw_check >> 8) & 0x7
                    imm8 = hw_check & 0xFF
                    check_pc = 0x08000000 + check_off
                    aligned = (check_pc + 4) & ~3
                    pool_addr = aligned + imm8 * 4
                    if (pool_addr - 0x08000000) == off:
                        print(f"    Referenced by LDR R{rd} at 0x{check_pc:08X}")
                        # Show context
                        for ctx in range(max(0, check_off - 6), min(len(rom), check_off + 10), 2):
                            marker = ">>>" if ctx == check_off else "   "
                            print(f"      {marker} 0x{0x08000000+ctx:08X}: {u16(rom, ctx):04X}")
            count += 1
    print(f"  Total: {count} occurrences")

    # 8. Check what gBattleTypeFlags is (literal pool refs)
    # The state var address loaded at 0x08036D16 and 0x08036D22
    print("\n--- Key addresses loaded by cb2_during_comm_processing ---")
    for pc_check in range(0x08036D00, 0x08036D40, 2):
        hw_check = u16(rom, gba_to_rom(pc_check))
        if (hw_check >> 11) == 0x09:
            rd = (hw_check >> 8) & 0x7
            imm8 = hw_check & 0xFF
            load_addr, val = resolve_literal_pool(rom, pc_check, imm8)
            name = lookup_addr(val) if val else None
            n = f"  ({name})" if name else ""
            print(f"  0x{pc_check:08X}: LDR R{rd} => 0x{val:08X}{n}" if val else f"  0x{pc_check:08X}: LDR R{rd} => [0x{load_addr:08X}]")

    # 9. Disassemble the exit point at 0x0803719C (where all branches go)
    print(f"\n--- Exit code at 0x0803719C ---")
    pc = 0x0803719C
    for j in range(0, 40, 2):
        hw_check = u16(rom, gba_to_rom(pc + j))
        print(f"  0x{pc+j:08X}: {hw_check:04X}", end="")
        # Quick decode
        if (hw_check >> 8) == 0xBD:
            regs = [f"R{i}" for i in range(8) if hw_check & (1<<i)]
            regs.append("PC")
            print(f"  POP {{{', '.join(regs)}}} <<< RETURN", end="")
        elif (hw_check >> 8) == 0xB0 and not (hw_check & 0x80):
            print(f"  ADD SP, #0x{(hw_check & 0x7F)*4:X}", end="")
        elif (hw_check >> 8) == 0xBC:
            regs = [f"R{i}" for i in range(8) if hw_check & (1<<i)]
            print(f"  POP {{{', '.join(regs)}}}", end="")
        print()

    # 10. BattleMainCB2 - check the literal pool value at 0x08094838
    print(f"\n--- BattleMainCB2 literal pool at 0x08094838 ---")
    val = u32(rom, gba_to_rom(0x08094838))
    name = lookup_addr(val)
    n = f"  ({name})" if name else ""
    print(f"  [0x08094838] = 0x{val:08X}{n}")
    print(f"  This is stored into [R2, #0x1C] when [R2, #0x24]==0")
    print(f"  R2 = R0 = first parameter. This looks like a sprite callback that sets its own callback to 0x{val:08X}")

    # 11. Let's find the REAL BattleMainCB2 by searching for it
    print(f"\n--- Searching for the REAL BattleMainCB2 ---")
    print(f"  Looking for 0x08094815 in literal pools (as a callback target)...")
    target_bytes = struct.pack("<I", 0x08094815)
    for off in range(0, min(len(rom), 0x200000), 4):
        if rom[off:off+4] == target_bytes:
            gba_addr = 0x08000000 + off
            print(f"  Found at 0x{gba_addr:08X}")
            for check_off in range(max(0, off - 1024), off, 2):
                hw_check = u16(rom, check_off)
                if (hw_check >> 11) == 0x09:
                    rd = (hw_check >> 8) & 0x7
                    imm8 = hw_check & 0xFF
                    check_pc = 0x08000000 + check_off
                    aligned = (check_pc + 4) & ~3
                    pool_addr = aligned + imm8 * 4
                    if (pool_addr - 0x08000000) == off:
                        print(f"    Referenced by LDR R{rd} at 0x{check_pc:08X}")

    # Check the real CB2_BattleMain address from MEMORY.md: 0x08094815
    # It was found by scanning. Let's verify what's actually at that address
    print(f"\n--- What's REALLY at 0x08094814? Let's read more ---")
    # The function at 0x08094814 is clearly NOT BattleMainCB2 - it's a sprite callback
    # Let's search for the pattern: PUSH + BL AnimateSprites + BL BuildOamBuffer + BL RunTextPrinters...
    # BattleMainCB2 in vanilla calls: AnimateSprites, BuildOamBuffer, RunTextPrinters, UpdatePaletteFade, RunTasks
    # Let's find RunTasks
    print("  Searching for BattleMainCB2 pattern (calls RunTasks + AnimateSprites + UpdatePaletteFade)...")
    print("  Known common game loop functions:")
    print(f"    0x080069D0 - called from stuck_callback2 (AnimateSprites?)")
    print(f"    0x08006A1C - called from stuck_callback2 (BuildOamBuffer?)")
    print(f"    0x08004788 - called from stuck_callback2 (RunTasks?)")
    print(f"    0x080BF858 - called from stuck_callback2 (UpdatePaletteFade?)")
    print(f"    0x080C6F84 - called from stuck_callback2 (RunTextPrinters?)")

    # Actually let's look at what CB2_InitBattle does
    print(f"\n--- CB2_InitBattle (0x080363C0) - first 128 bytes ---")
    pc = 0x080363C0
    for j in range(0, 128, 2):
        addr = pc + j
        hw_check = u16(rom, gba_to_rom(addr))
        prefix = "  "

        # BL detection
        if (hw_check >> 11) == 0x1E and j + 2 < 128:
            hw2 = u16(rom, gba_to_rom(addr + 2))
            if (hw2 >> 11) in (0x1F, 0x1D):
                offset_hi = hw_check & 0x7FF
                if offset_hi & 0x400: offset_hi -= 0x800
                offset_lo = hw2 & 0x7FF
                target = (addr + 4) + (offset_hi << 12) + (offset_lo << 1)
                target &= 0xFFFFFFFF
                name = lookup_addr(target)
                n = f"  ; {name}" if name else ""
                print(f"  0x{addr:08X}: {hw_check:04X} {hw2:04X}  BL 0x{target:08X}{n}")
                j += 2  # skip but loop will add 2 more
                continue

        # LDR PC
        if (hw_check >> 11) == 0x09:
            rd = (hw_check >> 8) & 0x7
            imm8 = hw_check & 0xFF
            la, val = resolve_literal_pool(rom, addr, imm8)
            name = lookup_addr(val) if val else None
            n = f"  ({name})" if name else ""
            extra = f"  ; [0x{la:08X}]=0x{val:08X}{n}" if val else ""
            print(f"  0x{addr:08X}: {hw_check:04X}        LDR R{rd}{extra}")
        else:
            print(f"  0x{addr:08X}: {hw_check:04X}")


if __name__ == "__main__":
    main()
