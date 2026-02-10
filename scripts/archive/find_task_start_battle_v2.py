#!/usr/bin/env python3
"""
Verify Task_StartWiredCableClubBattle = 0x080D1655 by finding CreateTask calls with this address.
Also investigate 0x080D18A5 (saved callback after battle).
Also find the exact literal pool values for gMain, gLinkPlayers etc.
"""

import struct

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
ROM_BASE = 0x08000000

TASK_FUNC_CANDIDATE = 0x080D1655  # Task_StartWiredCableClubBattle (THUMB)
POST_BATTLE_CB = 0x080D18A5  # saved callback found in LP
CREATE_TASK = 0x080C1544  # CreateTask without THUMB bit


def read_rom(path):
    with open(path, 'rb') as f:
        return f.read()


def decode_bl(rom, offset):
    if offset + 3 >= len(rom):
        return None
    hi = struct.unpack_from('<H', rom, offset)[0]
    lo = struct.unpack_from('<H', rom, offset + 2)[0]
    if (hi & 0xF800) != 0xF000:
        return None
    if (lo & 0xF800) != 0xF800:
        return None
    offset_hi = hi & 0x7FF
    offset_lo = lo & 0x7FF
    combined = (offset_hi << 12) | (offset_lo << 1)
    if combined & 0x400000:
        combined -= 0x800000
    addr_of_hi = ROM_BASE + offset
    target = addr_of_hi + 4 + combined
    return target


def find_lp_refs(rom, value):
    refs = []
    for off in range(0, len(rom) - 3, 4):
        v = struct.unpack_from('<I', rom, off)[0]
        if v == value:
            refs.append(off)
    return refs


def find_function_start(rom, offset):
    for back in range(0, min(offset, 2048), 2):
        pos = offset - back
        if pos < 0:
            break
        hw = struct.unpack_from('<H', rom, pos)[0]
        if (hw & 0xFF00) == 0xB500:
            return pos, ROM_BASE + pos
    return None, None


def disassemble_thumb(rom, start_off, end_off):
    lines = []
    off = start_off
    while off < end_off:
        addr = ROM_BASE + off
        hw = struct.unpack_from('<H', rom, off)[0]
        bl_target = decode_bl(rom, off)
        if bl_target is not None:
            lo = struct.unpack_from('<H', rom, off + 2)[0]
            label = ""
            t = bl_target & ~1
            if t == 0x080C1544: label = " (CreateTask)"
            elif t == 0x08000544: label = " (SetMainCallback2)"
            elif t == 0x080C1AA4: label = " (DestroyTask)"
            elif t == 0x0800A568: label = " (IsLinkTaskFinished)"
            lines.append(f"  0x{addr:08X}: {hw:04X} {lo:04X}  BL 0x{bl_target:08X}{label}")
            off += 4
            continue
        if (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 7
            imm = (hw & 0xFF) * 4
            pc_val = (addr + 4) & ~3
            lp_addr = pc_val + imm
            lp_off = lp_addr - ROM_BASE
            val = "????????"
            if 0 <= lp_off < len(rom) - 3:
                val = f"0x{struct.unpack_from('<I', rom, lp_off)[0]:08X}"
            lines.append(f"  0x{addr:08X}: {hw:04X}       LDR R{rd}, [PC, #0x{imm:X}]  ; ={val} @0x{lp_addr:08X}")
        elif (hw & 0xFF00) == 0xB500:
            regs = []
            for i in range(8):
                if hw & (1 << i): regs.append(f"R{i}")
            if hw & 0x100: regs.append("LR")
            lines.append(f"  0x{addr:08X}: {hw:04X}       PUSH {{{', '.join(regs)}}}")
        elif (hw & 0xFF00) == 0xBD00:
            regs = []
            for i in range(8):
                if hw & (1 << i): regs.append(f"R{i}")
            if hw & 0x100: regs.append("PC")
            lines.append(f"  0x{addr:08X}: {hw:04X}       POP {{{', '.join(regs)}}}")
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: {hw:04X}       MOV R{rd}, #0x{imm:X}")
        elif (hw & 0xF800) == 0x2800:
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            lines.append(f"  0x{addr:08X}: {hw:04X}       CMP R{rd}, #0x{imm:X}")
        elif (hw & 0xF000) == 0xD000:
            cond = (hw >> 8) & 0xF
            soff = hw & 0xFF
            if soff & 0x80: soff -= 0x100
            target = addr + 4 + soff * 2
            conds = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC","BHI","BLS","BGE","BLT","BGT","BLE","??","SWI"]
            lines.append(f"  0x{addr:08X}: {hw:04X}       {conds[cond]} 0x{target:08X}")
        elif (hw & 0xF800) == 0xE000:
            soff = hw & 0x7FF
            if soff & 0x400: soff -= 0x800
            target = addr + 4 + soff * 2
            lines.append(f"  0x{addr:08X}: {hw:04X}       B 0x{target:08X}")
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            lines.append(f"  0x{addr:08X}: {hw:04X}       BX R{rm}")
        else:
            lines.append(f"  0x{addr:08X}: {hw:04X}       .hword 0x{hw:04X}")
        off += 2
    return "\n".join(lines)


def main():
    rom = read_rom(ROM_PATH)
    print(f"ROM size: 0x{len(rom):X}")

    # 1. Verify: find LP refs to 0x080D1655 (Task_StartWiredCableClubBattle THUMB addr)
    print("\n" + "="*70)
    print(f"Looking for LP refs to 0x{TASK_FUNC_CANDIDATE:08X} (Task_StartWiredCableClubBattle)")
    print("="*70)

    refs = find_lp_refs(rom, TASK_FUNC_CANDIDATE)
    print(f"Found {len(refs)} LP refs")
    for r in refs:
        addr = ROM_BASE + r
        fstart, faddr = find_function_start(rom, r)
        print(f"  LP at 0x{addr:08X}, in function starting at 0x{faddr:08X}")

        # Check if this function has a BL->CreateTask nearby that uses R0=this value
        if fstart is not None:
            fend = min(fstart + 2048, len(rom) - 3)
            for off in range(fstart, fend - 3, 2):
                target = decode_bl(rom, off)
                if target is not None and (target & ~1) == CREATE_TASK:
                    print(f"    BL CreateTask at 0x{ROM_BASE+off:08X}")
                    # Check what LDR R0 precedes it
                    for back in range(2, 40, 2):
                        pos = off - back
                        hw = struct.unpack_from('<H', rom, pos)[0]
                        if (hw & 0xF800) == 0x4800 and ((hw >> 8) & 7) == 0:
                            imm = (hw & 0xFF) * 4
                            pc_val = (ROM_BASE + pos + 4) & ~3
                            lp_addr = pc_val + imm
                            lp_off = lp_addr - ROM_BASE
                            if 0 <= lp_off < len(rom) - 3:
                                val = struct.unpack_from('<I', rom, lp_off)[0]
                                print(f"    R0 = 0x{val:08X} (from LDR at 0x{ROM_BASE+pos:08X})")
                                if val == TASK_FUNC_CANDIDATE:
                                    print(f"    *** CONFIRMED: CreateTask(Task_StartWiredCableClubBattle, ...)")
                            break

    # 2. Investigate 0x080D18A5 (post-battle callback)
    print("\n" + "="*70)
    print(f"Disassembling function at 0x{POST_BATTLE_CB & ~1:08X} (post-battle saved callback)")
    print("="*70)

    cb_off = (POST_BATTLE_CB & ~1) - ROM_BASE
    fstart, faddr = find_function_start(rom, cb_off)
    if fstart:
        # Find end (look for POP PC or next PUSH)
        fend = fstart
        for off in range(fstart + 2, min(fstart + 512, len(rom) - 1), 2):
            hw = struct.unpack_from('<H', rom, off)[0]
            if (hw & 0xFF00) == 0xBD00:
                fend = off + 2
                break
            if off > fstart + 4 and (hw & 0xFF00) == 0xB500:
                fend = off
                break
        # Extend to include LP
        disasm_end = min(fend + 64, len(rom))
        print(f"Function: 0x{faddr:08X} - 0x{ROM_BASE+fend:08X}")
        print(disassemble_thumb(rom, fstart, disasm_end))
    else:
        print(f"Could not find function start for 0x{POST_BATTLE_CB:08X}")
        print(disassemble_thumb(rom, cb_off, min(cb_off + 128, len(rom))))

    # 3. Extract key literal pool values from the main function
    print("\n" + "="*70)
    print("Key addresses from Task_StartWiredCableClubBattle LP")
    print("="*70)

    func_off = 0x080D1654 - ROM_BASE
    # Scan LP area (after function body, aligned 4-byte values)
    lp_start = 0x080D17D0 - ROM_BASE  # First LP entry area
    lp_end = lp_start + 64
    print("Literal pool entries:")
    for off in range(lp_start, min(lp_end, len(rom) - 3), 4):
        val = struct.unpack_from('<I', rom, off)[0]
        addr = ROM_BASE + off
        label = ""
        if val == 0x02022CE8: label = " (gLinkPlayers)"
        elif val == 0x00002211: label = " (link player ID pattern)"
        elif val == 0x02036BA0: label = " (gSpecialVar_Result?)"
        elif val == 0x020381AE: label = " (???)"
        elif val == 0x080363C1: label = " (CB2_InitBattle)"
        elif val == 0x030022C0: label = " (gMain)"
        elif val == 0x080D18A5: label = " (post-battle callback / savedCallback)"
        print(f"  0x{addr:08X}: 0x{val:08X}{label}")

    # Also scan earlier LP areas
    for lp_area_start, lp_area_end in [(0x080D16BC - ROM_BASE, 0x080D16C4 - ROM_BASE),
                                        (0x080D16D8 - ROM_BASE, 0x080D16E0 - ROM_BASE),
                                        (0x080D16EC - ROM_BASE, 0x080D16F0 - ROM_BASE),
                                        (0x080D1708 - ROM_BASE, 0x080D1710 - ROM_BASE),
                                        (0x080D1744 - ROM_BASE, 0x080D174C - ROM_BASE)]:
        for off in range(lp_area_start, min(lp_area_end, len(rom) - 3), 4):
            val = struct.unpack_from('<I', rom, off)[0]
            addr = ROM_BASE + off
            label = ""
            if val == 0x02022CC6: label = " (gLinkPlayers - 0x22 = gLinkStatus?)"
            elif val == 0x02022CE8: label = " (gLinkPlayers)"
            elif val == 0x02037594: label = " (???)"
            elif val == 0x02022CCC: label = " (gLinkPlayers + 4?)"
            elif val == 0x020226C4: label = " (gRecvCmds?)"
            print(f"  0x{addr:08X}: 0x{val:08X}{label}")

    # 4. Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Task_StartWiredCableClubBattle = 0x080D1655 (THUMB)")
    print(f"  ROM offset: 0x{0x0D1654:06X}")
    print(f"  Function body: 0x080D1654 - 0x080D17CE (~378 bytes)")
    print(f"  Cases 0-7 switch on gTask[taskId].data[0]")
    print(f"  Case 6 (0x080D1766): BL IsLinkTaskFinished → wait for link")
    print(f"  Case 7 (0x080D1776): Set CB2_InitBattle, save gMain.savedCallback, DestroyTask")
    print(f"  Post-battle callback: 0x080D18A5")
    print(f"  Key LP values:")
    print(f"    gLinkPlayers = 0x02022CE8")
    print(f"    gMain = 0x030022C0")
    print(f"    CB2_InitBattle = 0x080363C1")
    print(f"    0x020381AE = ??? (written with 0x0100 pattern)")
    print(f"    0x02036BA0 = gSpecialVar_Result?")


if __name__ == "__main__":
    main()
