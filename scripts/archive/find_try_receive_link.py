#!/usr/bin/env python3
"""
Find TryReceiveLinkBattleData in Pokemon Run & Bun ROM.

Strategy:
1. Scan ROM for literal pool entries containing gReceivedRemoteLinkPlayers (0x03003124)
   and gBattleTypeFlags (0x02023364)
2. Find pairs within ~100 bytes (same function's literal pool)
3. Walk backwards to find function prologue (PUSH)
4. Find all BL callers of that function
"""

import struct
import sys
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known addresses
GRECEIVEDREMOTE = 0x03003124
GBATTLETYPEFLAGS = 0x02023364
BATTLE_TYPE_LINK_IN_BATTLE = 0x00000020

def read_rom(path):
    with open(path, "rb") as f:
        return f.read()

def find_literal_pool_refs(rom, target_value):
    """Find all 4-byte aligned offsets in ROM where target_value appears (literal pool entries)."""
    results = []
    target_bytes = struct.pack("<I", target_value)
    offset = 0
    while True:
        idx = rom.find(target_bytes, offset)
        if idx == -1:
            break
        # Literal pool entries are word-aligned
        if idx % 4 == 0:
            results.append(idx)
        offset = idx + 1
    return results

def find_ldr_pc_refs(rom, literal_offset):
    """Find THUMB LDR Rd, [PC, #imm] instructions that reference a given literal pool offset.

    THUMB LDR Rd, [PC, #imm8*4]: opcode = 0100 1 Rd(3) imm8(8)
    Format: 0x4800 | (Rd << 8) | imm8
    PC-relative: address = (PC & ~2) + imm8*4, where PC = instruction_addr + 4
    Range: 0 to 1020 bytes forward from (PC & ~2)
    """
    results = []
    # LDR can reach up to 1020 bytes back from literal pool
    search_start = max(0, literal_offset - 1024)
    # Must be halfword aligned, search in THUMB code region
    for instr_off in range(search_start, literal_offset, 2):
        hw = struct.unpack_from("<H", rom, instr_off)[0]
        # Check if it's LDR Rd, [PC, #imm]
        if (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            # PC = instr_off + 4 (in THUMB mode, PC is 4 ahead)
            pc = instr_off + 4
            pc_aligned = pc & ~2
            target = pc_aligned + imm8 * 4
            if target == literal_offset:
                results.append((instr_off, rd))
    return results

def find_function_start(rom, offset, max_search=512):
    """Walk backwards from offset to find PUSH {... lr} instruction.

    THUMB PUSH {Rlist, LR}: 1011 0101 Rlist(8) = 0xB5xx
    Also check for PUSH {Rlist}: 1011 0100 Rlist(8) = 0xB4xx
    """
    candidates = []
    for off in range(offset, max(0, offset - max_search), -2):
        hw = struct.unpack_from("<H", rom, off)[0]
        # PUSH {Rlist, LR}
        if (hw & 0xFF00) == 0xB500:
            rlist = hw & 0xFF
            regs = []
            for i in range(8):
                if rlist & (1 << i):
                    regs.append(f"r{i}")
            regs.append("lr")
            candidates.append((off, regs))
            break  # Take the nearest PUSH with LR
        # Also could be PUSH {Rlist} without LR (less likely for function start)
        if (hw & 0xFF00) == 0xB400:
            rlist = hw & 0xFF
            regs = []
            for i in range(8):
                if rlist & (1 << i):
                    regs.append(f"r{i}")
            # Don't break - keep looking for PUSH with LR
    return candidates

def find_all_bl_callers(rom, target_offset, rom_size):
    """Find all THUMB BL instructions that call target_offset.

    THUMB BL is a 2-instruction sequence (32-bit):
    Instruction 1: 1111 0 offset_hi(11) -> upper = 0xF000 | (offset_hi)
    Instruction 2: 1111 1 offset_lo(11) -> lower = 0xF800 | (offset_lo)

    Combined offset = (offset_hi << 12) | (offset_lo << 1)
    Target = PC + 4 + sign_extend(combined, 23)

    Actually for BL:
    upper: 11110 S imm10     = 0xF000 | (S << 10) | imm10
    lower: 11111 J1 J2 imm11 = 0xF800 | (J1 << 13) | (J2 << 11) | imm11 (but bits 13,12 used differently)

    Simpler: For Thumb BL (ARMv4T / ARMv5):
    First halfword:  1111 0 imm_hi(11)  - sets up high part
    Second halfword: 1111 1 imm_lo(11)  - does the branch
    offset = (imm_hi << 12) | (imm_lo << 1), sign-extended from bit 22
    target = (addr_of_first_hw + 4) + offset
    """
    callers = []
    # Scan every 2 bytes (halfword aligned)
    for off in range(0, min(rom_size - 4, len(rom) - 4), 2):
        upper = struct.unpack_from("<H", rom, off)[0]
        lower = struct.unpack_from("<H", rom, off + 2)[0]

        # Check BL pattern: upper = 1111 0xxx xxxx xxxx, lower = 1111 1xxx xxxx xxxx
        if (upper & 0xF800) == 0xF000 and (lower & 0xF800) == 0xF800:
            imm_hi = upper & 0x7FF
            imm_lo = lower & 0x7FF
            offset_val = (imm_hi << 12) | (imm_lo << 1)
            # Sign extend from bit 22
            if offset_val & 0x400000:
                offset_val |= ~0x7FFFFF  # sign extend
                offset_val &= 0xFFFFFFFF  # keep as 32-bit
                # Convert to signed
                if offset_val >= 0x80000000:
                    offset_val = offset_val - 0x100000000

            target = (off + 4) + offset_val
            if target == target_offset:
                callers.append(off)
    return callers

def disasm_thumb_range(rom, start, length):
    """Simple disassembly of a range for display purposes."""
    lines = []
    off = start
    end = start + length
    while off < end and off < len(rom) - 1:
        hw = struct.unpack_from("<H", rom, off)[0]
        addr = ROM_BASE + off

        # Check for BL (2-instruction)
        if (hw & 0xF800) == 0xF000 and off + 2 < len(rom):
            lower = struct.unpack_from("<H", rom, off + 2)[0]
            if (lower & 0xF800) == 0xF800:
                imm_hi = hw & 0x7FF
                imm_lo = lower & 0x7FF
                offset_val = (imm_hi << 12) | (imm_lo << 1)
                if offset_val & 0x400000:
                    offset_val = offset_val - 0x800000
                target = (off + 4) + offset_val
                lines.append(f"  0x{addr:08X}: BL 0x{ROM_BASE + target:08X}")
                off += 4
                continue

        # PUSH
        if (hw & 0xFF00) == 0xB500:
            rlist = hw & 0xFF
            regs = []
            for i in range(8):
                if rlist & (1 << i):
                    regs.append(f"r{i}")
            regs.append("lr")
            lines.append(f"  0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
        elif (hw & 0xFF00) == 0xB400:
            rlist = hw & 0xFF
            regs = []
            for i in range(8):
                if rlist & (1 << i):
                    regs.append(f"r{i}")
            lines.append(f"  0x{addr:08X}: PUSH {{{', '.join(regs)}}}")
        # POP
        elif (hw & 0xFF00) == 0xBD00:
            rlist = hw & 0xFF
            regs = []
            for i in range(8):
                if rlist & (1 << i):
                    regs.append(f"r{i}")
            regs.append("pc")
            lines.append(f"  0x{addr:08X}: POP {{{', '.join(regs)}}}")
        # LDR Rd, [PC, #imm]
        elif (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            pc = off + 4
            pc_aligned = pc & ~2
            target = pc_aligned + imm8 * 4
            if target < len(rom) - 3:
                val = struct.unpack_from("<I", rom, target)[0]
                lines.append(f"  0x{addr:08X}: LDR r{rd}, [PC, #0x{imm8*4:X}] ; =0x{val:08X}")
            else:
                lines.append(f"  0x{addr:08X}: LDR r{rd}, [PC, #0x{imm8*4:X}]")
        # LDR Rd, [Rn, #imm]
        elif (hw & 0xF800) == 0x6800:
            imm5 = (hw >> 6) & 0x1F
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            lines.append(f"  0x{addr:08X}: LDR r{rd}, [r{rn}, #0x{imm5*4:X}]")
        # LDRB
        elif (hw & 0xF800) == 0x7800:
            imm5 = (hw >> 6) & 0x1F
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            lines.append(f"  0x{addr:08X}: LDRB r{rd}, [r{rn}, #0x{imm5:X}]")
        # CMP Rn, #imm8
        elif (hw & 0xF800) == 0x2800:
            rn = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: CMP r{rn}, #0x{imm8:X}")
        # MOV Rd, #imm8
        elif (hw & 0xF800) == 0x2000:
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: MOV r{rd}, #0x{imm8:X}")
        # TST Rn, Rm
        elif (hw & 0xFFC0) == 0x4200:
            rm = (hw >> 3) & 0x7
            rn = hw & 0x7
            lines.append(f"  0x{addr:08X}: TST r{rn}, r{rm}")
        # BEQ
        elif (hw & 0xFF00) == 0xD000:
            imm8 = hw & 0xFF
            if imm8 & 0x80:
                imm8 = imm8 - 256
            target = off + 4 + imm8 * 2
            lines.append(f"  0x{addr:08X}: BEQ 0x{ROM_BASE + target:08X}")
        # BNE
        elif (hw & 0xFF00) == 0xD100:
            imm8 = hw & 0xFF
            if imm8 & 0x80:
                imm8 = imm8 - 256
            target = off + 4 + imm8 * 2
            lines.append(f"  0x{addr:08X}: BNE 0x{ROM_BASE + target:08X}")
        # B (unconditional)
        elif (hw & 0xF800) == 0xE000:
            imm11 = hw & 0x7FF
            if imm11 & 0x400:
                imm11 = imm11 - 0x800
            target = off + 4 + imm11 * 2
            lines.append(f"  0x{addr:08X}: B 0x{ROM_BASE + target:08X}")
        # BX Rm
        elif (hw & 0xFF80) == 0x4700:
            rm = (hw >> 3) & 0xF
            lines.append(f"  0x{addr:08X}: BX r{rm}")
        # AND, ORR, etc
        elif (hw & 0xFFC0) == 0x4000:
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            lines.append(f"  0x{addr:08X}: AND r{rd}, r{rm}")
        elif (hw & 0xFFC0) == 0x4300:
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            lines.append(f"  0x{addr:08X}: ORR r{rd}, r{rm}")
        # STR Rd, [Rn, #imm]
        elif (hw & 0xF800) == 0x6000:
            imm5 = (hw >> 6) & 0x1F
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            lines.append(f"  0x{addr:08X}: STR r{rd}, [r{rn}, #0x{imm5*4:X}]")
        # STRB
        elif (hw & 0xF800) == 0x7000:
            imm5 = (hw >> 6) & 0x1F
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            lines.append(f"  0x{addr:08X}: STRB r{rd}, [r{rn}, #0x{imm5:X}]")
        # ADD Rd, Rn, #imm3
        elif (hw & 0xFE00) == 0x1C00:
            imm3 = (hw >> 6) & 0x7
            rn = (hw >> 3) & 0x7
            rd = hw & 0x7
            lines.append(f"  0x{addr:08X}: ADD r{rd}, r{rn}, #0x{imm3:X}")
        # ADD Rd, #imm8
        elif (hw & 0xF800) == 0x3000:
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: ADD r{rd}, #0x{imm8:X}")
        # SUB Rd, #imm8
        elif (hw & 0xF800) == 0x3800:
            rd = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            lines.append(f"  0x{addr:08X}: SUB r{rd}, #0x{imm8:X}")
        # LSL
        elif (hw & 0xF800) == 0x0000:
            imm5 = (hw >> 6) & 0x1F
            rm = (hw >> 3) & 0x7
            rd = hw & 0x7
            if imm5 == 0 and rm == rd:
                lines.append(f"  0x{addr:08X}: NOP (MOV r{rd}, r{rd})")
            else:
                lines.append(f"  0x{addr:08X}: LSL r{rd}, r{rm}, #0x{imm5:X}")
        else:
            lines.append(f"  0x{addr:08X}: .hword 0x{hw:04X}")

        off += 2
    return lines

def main():
    print("=" * 70)
    print("TryReceiveLinkBattleData Scanner")
    print("=" * 70)
    print(f"ROM: {ROM_PATH}")
    print(f"Looking for: gReceivedRemoteLinkPlayers = 0x{GRECEIVEDREMOTE:08X}")
    print(f"             gBattleTypeFlags = 0x{GBATTLETYPEFLAGS:08X}")
    print()

    rom = read_rom(ROM_PATH)
    rom_size = len(rom)
    print(f"ROM size: {rom_size} bytes (0x{rom_size:X})")
    print()

    # Step 1: Find all literal pool references to both addresses
    print("Step 1: Scanning literal pools...")
    refs_remote = find_literal_pool_refs(rom, GRECEIVEDREMOTE)
    refs_btflags = find_literal_pool_refs(rom, GBATTLETYPEFLAGS)

    print(f"  gReceivedRemoteLinkPlayers (0x{GRECEIVEDREMOTE:08X}): {len(refs_remote)} literal pool entries")
    for r in refs_remote:
        print(f"    ROM offset 0x{r:06X} (addr 0x{ROM_BASE + r:08X})")

    print(f"  gBattleTypeFlags (0x{GBATTLETYPEFLAGS:08X}): {len(refs_btflags)} literal pool entries")
    for r in refs_btflags[:20]:  # Show first 20
        print(f"    ROM offset 0x{r:06X} (addr 0x{ROM_BASE + r:08X})")
    if len(refs_btflags) > 20:
        print(f"    ... and {len(refs_btflags) - 20} more")
    print()

    # Step 2: Find pairs within proximity (same function)
    print("Step 2: Finding pairs within ~200 bytes (same function literal pool)...")
    pairs = []
    for rr in refs_remote:
        for rb in refs_btflags:
            dist = abs(rr - rb)
            if dist < 200:
                pairs.append((rr, rb, dist))
                print(f"  PAIR: gReceivedRemote @ 0x{rr:06X}, gBattleTypeFlags @ 0x{rb:06X}, distance={dist} bytes")

    if not pairs:
        print("  No pairs found within 200 bytes. Expanding search to 500 bytes...")
        for rr in refs_remote:
            for rb in refs_btflags:
                dist = abs(rr - rb)
                if dist < 500:
                    pairs.append((rr, rb, dist))
                    print(f"  PAIR: gReceivedRemote @ 0x{rr:06X}, gBattleTypeFlags @ 0x{rb:06X}, distance={dist} bytes")

    if not pairs:
        print("  ERROR: No pairs found! The function may use different addressing.")
        # Try alternative: find LDR instructions that reference these
        print()
        print("Step 2b: Looking for LDR instructions referencing these addresses...")
        for rr in refs_remote:
            ldrs = find_ldr_pc_refs(rom, rr)
            for ldr_off, rd in ldrs:
                print(f"  LDR r{rd} -> gReceivedRemote: instr @ 0x{ROM_BASE + ldr_off:08X} -> pool @ 0x{ROM_BASE + rr:08X}")
        for rb in refs_btflags[:10]:
            ldrs = find_ldr_pc_refs(rom, rb)
            for ldr_off, rd in ldrs:
                print(f"  LDR r{rd} -> gBattleTypeFlags: instr @ 0x{ROM_BASE + ldr_off:08X} -> pool @ 0x{ROM_BASE + rb:08X}")
        return

    print()

    # Step 3: For each pair, find the function start
    print("Step 3: Finding function starts...")
    candidates = []
    for rr, rb, dist in pairs:
        # The code using these should be BEFORE the literal pool
        earliest = min(rr, rb)

        # Find LDR instructions referencing both pool entries
        ldrs_remote = find_ldr_pc_refs(rom, rr)
        ldrs_btflags = find_ldr_pc_refs(rom, rb)

        if not ldrs_remote:
            print(f"  No LDR found for gReceivedRemote pool @ 0x{rr:06X}")
            continue
        if not ldrs_btflags:
            print(f"  No LDR found for gBattleTypeFlags pool @ 0x{rb:06X}")
            continue

        # The earliest LDR instruction is closest to function start
        all_ldrs = [(off, "remote", rd) for off, rd in ldrs_remote] + [(off, "btflags", rd) for off, rd in ldrs_btflags]
        all_ldrs.sort(key=lambda x: x[0])
        earliest_ldr = all_ldrs[0][0]

        print(f"  Pair (remote=0x{rr:06X}, btflags=0x{rb:06X}):")
        for ldr_off, which, rd in all_ldrs:
            print(f"    LDR r{rd} ({which}) @ 0x{ROM_BASE + ldr_off:08X}")

        # Walk backwards from earliest LDR to find PUSH
        func_starts = find_function_start(rom, earliest_ldr)
        if func_starts:
            for fs_off, regs in func_starts:
                print(f"    Function start: PUSH {{{', '.join(regs)}}} @ 0x{ROM_BASE + fs_off:08X}")
                candidates.append((fs_off, regs, rr, rb, all_ldrs))
        else:
            print(f"    WARNING: No PUSH found before 0x{ROM_BASE + earliest_ldr:08X}")

    print()

    if not candidates:
        print("ERROR: No candidate functions found!")
        return

    # Step 4: Analyze each candidate
    print("Step 4: Analyzing candidates...")
    for func_off, regs, rr, rb, ldrs in candidates:
        func_addr = ROM_BASE + func_off
        # THUMB address has bit 0 set
        func_thumb = func_addr | 1

        print(f"\n{'='*60}")
        print(f"CANDIDATE: TryReceiveLinkBattleData")
        print(f"  ROM offset: 0x{func_off:06X}")
        print(f"  ROM address: 0x{func_addr:08X}")
        print(f"  THUMB address: 0x{func_thumb:08X}")
        print(f"  Prologue: PUSH {{{', '.join(regs)}}}")
        print(f"  Literal pool refs:")
        print(f"    gReceivedRemoteLinkPlayers @ pool 0x{ROM_BASE + rr:08X}")
        print(f"    gBattleTypeFlags @ pool 0x{ROM_BASE + rb:08X}")

        # Disassemble first ~120 bytes of the function
        print(f"\n  Disassembly (first 120 bytes):")
        disasm = disasm_thumb_range(rom, func_off, 120)
        for line in disasm:
            print(f"  {line}")

        # Find the end of function (POP {... pc})
        func_end = func_off
        for off in range(func_off, min(func_off + 1024, len(rom) - 1), 2):
            hw = struct.unpack_from("<H", rom, off)[0]
            if (hw & 0xFF00) == 0xBD00:
                func_end = off + 2
                break

        func_size = func_end - func_off
        print(f"\n  Function size: ~{func_size} bytes (to first POP {{..., pc}})")

        # Full disassembly if small enough
        if func_size > 120 and func_size < 500:
            print(f"\n  Full disassembly ({func_size} bytes):")
            disasm = disasm_thumb_range(rom, func_off, func_size)
            for line in disasm:
                print(f"  {line}")

        # Step 5: Find all BL callers
        print(f"\n  Scanning for BL callers targeting 0x{func_off:06X}...")
        callers = find_all_bl_callers(rom, func_off, rom_size)
        print(f"  Found {len(callers)} BL caller(s):")
        for caller_off in callers:
            caller_addr = ROM_BASE + caller_off
            print(f"    BL @ 0x{caller_addr:08X} (ROM offset 0x{caller_off:06X})")
            # Show context around the caller
            ctx_start = max(0, caller_off - 8)
            ctx_disasm = disasm_thumb_range(rom, ctx_start, 20)
            for line in ctx_disasm:
                print(f"      {line}")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if candidates:
        for func_off, regs, rr, rb, ldrs in candidates:
            func_addr = ROM_BASE + func_off
            print(f"  TryReceiveLinkBattleData: 0x{func_addr:08X} (THUMB: 0x{func_addr | 1:08X})")
            callers = find_all_bl_callers(rom, func_off, rom_size)
            print(f"  Callers ({len(callers)}):")
            for c in callers:
                print(f"    BL @ 0x{ROM_BASE + c:08X}")
    else:
        print("  No candidates found.")

if __name__ == "__main__":
    main()
