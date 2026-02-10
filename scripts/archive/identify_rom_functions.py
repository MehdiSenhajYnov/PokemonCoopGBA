"""
Identify ROM functions at specific addresses in Pokemon Run & Bun.
Disassembles THUMB code and shows literal pool references.
"""
import struct
import sys
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

# Addresses to investigate (with THUMB bit stripped)
TARGETS = {
    0x08070BB4: "Unknown controller (seen during DoBattleIntro)",
    0x0807DC98: "Unknown controller (LinkOpponent area)",
}

# Known reference points
KNOWN = {
    0x0806F150: "PlayerBufferRunCommand",
    0x081BAD84: "OpponentBufferRunCommand",
    0x0807DC44: "LinkOpponentBufferRunCommand",
    0x080363C0: "CB2_InitBattle",
    0x0803648C: "CB2_InitBattleInternal",
    0x08037B44: "CB2_HandleStartBattle",
    0x0803816C: "BattleMainCB2",
    0x08094814: "CB2_BattleMain (callback2)",
}

DISASM_BYTES = 80  # disassemble more bytes to catch literal pool

def read_rom(path):
    with open(path, "rb") as f:
        return f.read()

def thumb_disasm(rom, rom_offset, count, base_addr):
    """Simple THUMB disassembler for the instructions we care about."""
    lines = []
    i = 0
    while i < count:
        if rom_offset + i + 1 >= len(rom):
            break
        hw = struct.unpack_from("<H", rom, rom_offset + i)[0]
        addr = base_addr + i
        raw = f"{hw:04X}"

        # Decode common THUMB instructions
        mnemonic = f".short 0x{hw:04X}"
        comment = ""

        # Format 1: Move shifted register (LSL/LSR/ASR)
        if (hw >> 13) == 0b000:
            op = (hw >> 11) & 3
            offset5 = (hw >> 6) & 0x1F
            rs = (hw >> 3) & 7
            rd = hw & 7
            ops = ["LSL", "LSR", "ASR"]
            if op < 3:
                mnemonic = f"{ops[op]} R{rd}, R{rs}, #{offset5}"

        # Format 3: Move/Compare/Add/Sub immediate
        if (hw >> 13) == 0b001:
            op = (hw >> 11) & 3
            rd = (hw >> 8) & 7
            imm = hw & 0xFF
            ops = ["MOV", "CMP", "ADD", "SUB"]
            mnemonic = f"{ops[op]} R{rd}, #{imm} (0x{imm:02X})"

        # Format 5: Hi register operations / BX
        if (hw >> 10) == 0b010001:
            op = (hw >> 8) & 3
            h1 = (hw >> 7) & 1
            h2 = (hw >> 6) & 1
            rs = ((hw >> 3) & 7) + (h2 * 8)
            rd = (hw & 7) + (h1 * 8)
            if op == 0:
                mnemonic = f"ADD R{rd}, R{rs}"
            elif op == 1:
                mnemonic = f"CMP R{rd}, R{rs}"
            elif op == 2:
                mnemonic = f"MOV R{rd}, R{rs}"
            elif op == 3:
                if h1 == 0:
                    mnemonic = f"BX R{rs}"
                else:
                    mnemonic = f"BLX R{rs}"

        # PUSH/POP
        if (hw >> 9) == 0b10110101 or (hw >> 9) == 0b10110100:
            is_pop = (hw >> 11) & 1
            r_bit = (hw >> 8) & 1
            rlist = hw & 0xFF
            regs = [f"R{j}" for j in range(8) if rlist & (1 << j)]
            if r_bit:
                regs.append("LR" if not is_pop else "PC")
            op_name = "POP" if is_pop else "PUSH"
            mnemonic = f"{op_name} {{{', '.join(regs)}}}"

        # LDR Rd, [PC, #imm] (Format 6) - LITERAL POOL
        if (hw >> 11) == 0b01001:
            rd = (hw >> 8) & 7
            imm8 = hw & 0xFF
            # PC-relative: (PC & ~2) + 4 + imm8*4
            pc_val = (addr & ~2) + 4
            pool_addr = pc_val + imm8 * 4
            pool_rom_off = pool_addr - 0x08000000
            if 0 <= pool_rom_off < len(rom) - 3:
                lit_val = struct.unpack_from("<I", rom, pool_rom_off)[0]
                known_name = KNOWN.get(lit_val & ~1, KNOWN.get(lit_val, ""))
                if known_name:
                    comment = f"  ; =[0x{pool_addr:08X}] = 0x{lit_val:08X} ({known_name})"
                else:
                    comment = f"  ; =[0x{pool_addr:08X}] = 0x{lit_val:08X}"
                mnemonic = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"
            else:
                mnemonic = f"LDR R{rd}, [PC, #0x{imm8*4:X}]"

        # LDR/STR Rd, [Rn, #imm] (Format 9)
        if (hw >> 13) == 0b011:
            is_byte = (hw >> 12) & 1
            is_load = (hw >> 11) & 1
            imm5 = (hw >> 6) & 0x1F
            rn = (hw >> 3) & 7
            rd = hw & 7
            offset = imm5 if is_byte else imm5 * 4
            op_name = ("LDR" if not is_byte else "LDRB") if is_load else ("STR" if not is_byte else "STRB")
            mnemonic = f"{op_name} R{rd}, [R{rn}, #0x{offset:X}]"

        # LDR/STR Rd, [Rn, Rm] (Format 7)
        if (hw >> 9) == 0b0101000 or (hw >> 9) == 0b0101100:
            is_load = (hw >> 11) & 1
            rm = (hw >> 6) & 7
            rn = (hw >> 3) & 7
            rd = hw & 7
            op_name = "LDR" if is_load else "STR"
            mnemonic = f"{op_name} R{rd}, [R{rn}, R{rm}]"

        # LDRH/STRH (Format 10)
        if (hw >> 13) == 0b100 and ((hw >> 12) & 1) == 0:
            is_load = (hw >> 11) & 1
            imm5 = (hw >> 6) & 0x1F
            rn = (hw >> 3) & 7
            rd = hw & 7
            offset = imm5 * 2
            op_name = "LDRH" if is_load else "STRH"
            mnemonic = f"{op_name} R{rd}, [R{rn}, #0x{offset:X}]"

        # BL/BLX (32-bit instruction)
        if (hw >> 11) == 0b11110:
            # First half of BL
            offset11 = hw & 0x7FF
            if rom_offset + i + 3 < len(rom):
                hw2 = struct.unpack_from("<H", rom, rom_offset + i + 2)[0]
                if (hw2 >> 11) == 0b11111:  # BL second half
                    offset_low = hw2 & 0x7FF
                    # Sign extend high part
                    if offset11 & 0x400:
                        offset11 |= 0xFFFFF800
                    full_offset = (offset11 << 12) | (offset_low << 1)
                    # Sign extend 23-bit
                    if full_offset & 0x400000:
                        full_offset |= 0xFF800000
                        full_offset = full_offset - 0x100000000
                    target = addr + 4 + full_offset
                    known_name = KNOWN.get(target & ~1, KNOWN.get(target, ""))
                    if known_name:
                        mnemonic = f"BL 0x{target & 0xFFFFFFFF:08X} ({known_name})"
                    else:
                        mnemonic = f"BL 0x{target & 0xFFFFFFFF:08X}"
                    raw = f"{hw:04X} {hw2:04X}"
                    lines.append(f"  0x{addr:08X}:  {raw:<12s}  {mnemonic}{comment}")
                    i += 4
                    continue
                elif (hw2 >> 11) == 0b11101:  # BLX second half
                    offset_low = hw2 & 0x7FF
                    if offset11 & 0x400:
                        offset11 |= 0xFFFFF800
                    full_offset = (offset11 << 12) | (offset_low << 1)
                    if full_offset & 0x400000:
                        full_offset |= 0xFF800000
                        full_offset = full_offset - 0x100000000
                    target = ((addr + 4) & ~3) + full_offset
                    mnemonic = f"BLX 0x{target & 0xFFFFFFFF:08X}"
                    raw = f"{hw:04X} {hw2:04X}"
                    lines.append(f"  0x{addr:08X}:  {raw:<12s}  {mnemonic}{comment}")
                    i += 4
                    continue

        # Conditional branch (Format 16)
        if (hw >> 12) == 0b1101:
            cond = (hw >> 8) & 0xF
            if cond < 0xE:
                soff = hw & 0xFF
                if soff & 0x80:
                    soff -= 256
                target = addr + 4 + soff * 2
                conds = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                         "BHI","BLS","BGE","BLT","BGT","BLE"]
                mnemonic = f"{conds[cond]} 0x{target & 0xFFFFFFFF:08X}"
            elif cond == 0xE:
                mnemonic = f".short 0x{hw:04X} (UNDEFINED)"
            elif cond == 0xF:
                mnemonic = f"SWI #{hw & 0xFF}"

        # Unconditional branch (Format 18)
        if (hw >> 11) == 0b11100:
            soff = hw & 0x7FF
            if soff & 0x400:
                soff -= 2048
            target = addr + 4 + soff * 2
            mnemonic = f"B 0x{target & 0xFFFFFFFF:08X}"

        lines.append(f"  0x{addr:08X}:  {raw:<12s}  {mnemonic}{comment}")
        i += 2

    return lines


def scan_for_function_start(rom, rom_offset):
    """Scan backwards from rom_offset to find the PUSH {... LR} that starts the function."""
    for back in range(0, 200, 2):
        off = rom_offset - back
        if off < 0:
            break
        hw = struct.unpack_from("<H", rom, off)[0]
        # PUSH with LR bit set
        if (hw & 0xFF00) == 0xB500 or (hw & 0xFF00) == 0xB510 or \
           (hw & 0xFF00) == 0xB530 or (hw & 0xFF00) == 0xB570 or \
           (hw & 0xFF00) == 0xB5F0 or (hw & 0xFF00) == 0xB580 or \
           (hw & 0xFE00) == 0xB400:
            # More general: PUSH with LR
            pass
        if (hw >> 9) == 0b10110100 and (hw >> 8) & 1:  # PUSH {rlist, LR}
            return off, back
    return rom_offset, 0


def main():
    print(f"Reading ROM: {ROM_PATH}")
    rom = read_rom(ROM_PATH)
    print(f"ROM size: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)\n")

    for target_addr, description in TARGETS.items():
        rom_offset = target_addr - 0x08000000
        print(f"{'='*70}")
        print(f"TARGET: 0x{target_addr:08X} (+1 THUMB = 0x{target_addr|1:08X})")
        print(f"Description: {description}")
        print(f"ROM offset: 0x{rom_offset:06X}")
        print()

        # Find function start
        func_start_off, back_dist = scan_for_function_start(rom, rom_offset)
        func_start_addr = func_start_off + 0x08000000
        if back_dist > 0:
            print(f"Function likely starts at 0x{func_start_addr:08X} ({back_dist} bytes before target)")
        else:
            print(f"Function start = target (or couldn't find PUSH)")

        # Disassemble from function start
        disasm_count = DISASM_BYTES + back_dist
        print(f"\nDisassembly ({disasm_count} bytes from 0x{func_start_addr:08X}):")
        lines = thumb_disasm(rom, func_start_off, disasm_count, func_start_addr)
        for line in lines:
            # Highlight the target address
            if f"0x{target_addr:08X}" in line.split(":")[0]:
                print(f">>> {line}")
            else:
                print(f"    {line}")

        # Also show a wider context: check what's at the exact target
        print(f"\nRaw bytes at 0x{rom_offset:06X}: ", end="")
        for b in range(min(16, len(rom) - rom_offset)):
            print(f"{rom[rom_offset + b]:02X} ", end="")
        print()
        print()

    # Bonus: scan nearby known function table entries
    print(f"{'='*70}")
    print("CONTEXT: Known controller function addresses")
    print(f"{'='*70}")
    for addr, name in sorted(KNOWN.items()):
        rom_off = addr - 0x08000000
        if 0 <= rom_off < len(rom):
            hw = struct.unpack_from("<H", rom, rom_off)[0]
            print(f"  0x{addr:08X} ({name}): first halfword = 0x{hw:04X}")

    print()
    print("Address ordering (controller functions):")
    all_addrs = list(KNOWN.items()) + [(a, d) for a, d in TARGETS.items()]
    for addr, name in sorted(all_addrs):
        print(f"  0x{addr:08X}  {name}")

    # Try to find what references 0x08070BB5 or 0x0807DC99 in the ROM
    print()
    print(f"{'='*70}")
    print("Scanning ROM for references to target addresses...")
    print(f"{'='*70}")
    for target_addr in TARGETS:
        thumb_addr = target_addr | 1
        needle = struct.pack("<I", thumb_addr)
        print(f"\nSearching for 0x{thumb_addr:08X} in ROM literal pools...")
        found = 0
        pos = 0
        while True:
            pos = rom.find(needle, pos)
            if pos == -1:
                break
            rom_addr = pos + 0x08000000
            # Check context: what's around this reference?
            print(f"  Found at ROM offset 0x{pos:06X} (addr 0x{rom_addr:08X})")
            # Show surrounding bytes
            start = max(0, pos - 8)
            print(f"    Context: ", end="")
            for b in range(start, min(pos + 12, len(rom))):
                marker = ">" if b == pos else " "
                print(f"{marker}{rom[b]:02X}", end="")
            print()

            # Check if this is in a literal pool (word-aligned, near code)
            if pos % 4 == 0:
                # Scan backwards to find the LDR that references this pool entry
                for scan_back in range(2, 1026, 2):
                    scan_off = pos - scan_back
                    if scan_off < 0:
                        break
                    hw_scan = struct.unpack_from("<H", rom, scan_off)[0]
                    if (hw_scan >> 11) == 0b01001:  # LDR Rd, [PC, #imm]
                        rd = (hw_scan >> 8) & 7
                        imm8 = hw_scan & 0xFF
                        scan_addr = scan_off + 0x08000000
                        pc_val = (scan_addr & ~2) + 4
                        pool_target = pc_val + imm8 * 4
                        if pool_target == rom_addr:
                            print(f"    Referenced by LDR R{rd} at 0x{scan_addr:08X}")
                            # Show context of that LDR
                            ldr_func_start, _ = scan_for_function_start(rom, scan_off)
                            print(f"    (function starts ~0x{ldr_func_start + 0x08000000:08X})")
                            break

            found += 1
            pos += 4

        if found == 0:
            print(f"  No references found (address might be computed, not in literal pool)")

if __name__ == "__main__":
    main()
