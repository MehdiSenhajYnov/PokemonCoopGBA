#!/usr/bin/env python3
"""
Battle Address Finder for Pokemon Run & Bun

Finds all remaining addresses needed for Link Battle Emulation:
1. IWRAM literal pool refs (gWirelessCommType, gReceivedRemoteLinkPlayers, gBlockReceivedStatus)
2. GetMultiplayerId code analysis (find exact patch offset)
3. ROM function identification via cross-referencing known anchors
4. EWRAM battle variables via cluster analysis near known addresses

Uses PK-GBA Multiplayer's vanilla Emerald addresses as reference.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# ==========================================
# Known R&B addresses (already confirmed)
# ==========================================
KNOWN_RB = {
    "gPlayerParty":      0x02023A98,
    "gEnemyParty":       0x02023CF0,
    "gBattleTypeFlags":  0x020090E8,
    "gBattleResources":  0x02023A18,
    "gMainCallback2":    0x0202064C,
    "gMainAddr":         0x02020648,
    "sWarpDestination":  0x020318A8,
    "CB2_LoadMap":       0x08007441,
    "CB2_Overworld":     0x080A89A5,
    "CB2_BattleMain":    0x08094815,
    "GetMultiplayerId":  0x0833D67F,
    "SIO_MULTI_CNT":     0x04000120,
}

# ==========================================
# PK-GBA vanilla Emerald addresses (reference)
# ==========================================
VANILLA_EMERALD = {
    # EWRAM battle variables
    "gBattleCommunication":       0x02024332,
    "gBattleControllerExecFlags": 0x02024068,
    "gBattleBufferA":             0x02023064,
    "gBattleBufferB":             0x02023864,
    "gActiveBattler":             0x02024064,
    "gLinkPlayers":               0x020229E8,
    "gBattleTypeFlags":           0x02022FEC,
    "gPlayerParty":               0x020244EC,
    "gEnemyParty":                0x02024744,
    "gSendBuffer":                0x020228C4,
    "gReceiveBuffer":             0x020223C4,
    # IWRAM variables
    "gWirelessCommType":          0x030030FC,
    "gReceivedRemoteLinkPlayers": 0x03003124,
    "gBlockReceivedStatus":       0x0300307C,
    "gBattleMainFunc":            0x03005D04,
    # ROM functions
    "GetMultiplayerId":           0x0800A468,
    "SetUpBattleVars":            0x0803269C,
    "CB2_HandleStartBattle":      0x08036FAC,
    "PlayerBufferExecCompleted":  0x0805748C,
    "LinkOpponentBufferExecCompleted": 0x08065068,
    "PrepareBufferDataTransfer":  0x080331B8,
    "CB2_ReturnToField":          0x080860C8,
}

def read_u16_le(data, offset):
    return struct.unpack_from('<H', data, offset)[0]

def read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]

def find_all_refs(rom_data, target_value):
    """Find all 4-byte aligned positions where target_value appears."""
    target_bytes = struct.pack('<I', target_value)
    refs = []
    for i in range(0, len(rom_data) - 3, 4):
        if rom_data[i:i+4] == target_bytes:
            refs.append(i)
    return refs

def find_function_start(rom_data, offset, max_back=2048):
    """Walk backward from offset to find PUSH {LR} or PUSH {Rx, LR}."""
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        # PUSH {LR} = 0xB500, PUSH {Rx..., LR} = 0xB5xx
        if (instr & 0xFF00) == 0xB500:
            return pos
        # Also match PUSH {R4-R7, LR} variants
        if (instr & 0xFF00) == 0xB500 or (instr & 0xFE00) == 0xB400:
            # Check if bit 8 (LR) is set for B5xx
            if (instr & 0x0100):
                return pos
    return None

def disassemble_thumb(rom_data, start, count=40):
    """Simple THUMB disassembler for key instructions."""
    lines = []
    pos = start
    for _ in range(count):
        if pos + 2 > len(rom_data):
            break
        instr = read_u16_le(rom_data, pos)
        addr = ROM_BASE + pos
        desc = f"0x{addr:08X}: {instr:04X}"

        # MOV Rd, #imm
        if (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  MOV R{rd}, #{imm}"
        # PUSH
        elif (instr & 0xFE00) == 0xB400:
            lr = "LR," if (instr & 0x100) else ""
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            desc += f"  PUSH {{{lr}{','.join(regs)}}}"
        # POP
        elif (instr & 0xFE00) == 0xBC00:
            pc = "PC," if (instr & 0x100) else ""
            regs = [f"R{i}" for i in range(8) if instr & (1 << i)]
            desc += f"  POP {{{pc}{','.join(regs)}}}"
        # BX Rm
        elif (instr & 0xFF80) == 0x4700:
            rm = (instr >> 3) & 0xF
            desc += f"  BX R{rm}"
        # LDR Rd, [PC, #imm]
        elif (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            lit_addr = ((pos + 4) & ~3) + imm
            if lit_addr + 4 <= len(rom_data):
                lit_val = read_u32_le(rom_data, lit_addr)
                desc += f"  LDR R{rd}, =0x{lit_val:08X} (pool @0x{ROM_BASE+lit_addr:08X})"
            else:
                desc += f"  LDR R{rd}, [PC, #{imm}]"
        # LDR Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 4
            desc += f"  LDR R{rd}, [R{rn}, #{imm}]"
        # LDRB Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x7800:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = (instr >> 6) & 0x1F
            desc += f"  LDRB R{rd}, [R{rn}, #{imm}]"
        # LDRH Rd, [Rn, #imm]
        elif (instr & 0xF800) == 0x8800:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 2
            desc += f"  LDRH R{rd}, [R{rn}, #{imm}]"
        # CMP Rn, #imm
        elif (instr & 0xF800) == 0x2800:
            rn = (instr >> 8) & 7
            imm = instr & 0xFF
            desc += f"  CMP R{rn}, #{imm}"
        # BEQ/BNE/etc
        elif (instr & 0xF000) == 0xD000:
            cond = (instr >> 8) & 0xF
            cond_names = ["BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                          "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SVC"]
            offset_val = instr & 0xFF
            if offset_val >= 0x80:
                offset_val -= 0x100
            target = addr + 4 + offset_val * 2
            desc += f"  {cond_names[cond]} 0x{target:08X}"
        # B unconditional
        elif (instr & 0xF800) == 0xE000:
            offset_val = instr & 0x7FF
            if offset_val >= 0x400:
                offset_val -= 0x800
            target = addr + 4 + offset_val * 2
            desc += f"  B 0x{target:08X}"
        # BL (first half)
        elif (instr & 0xF800) == 0xF000:
            if pos + 2 < len(rom_data):
                next_instr = read_u16_le(rom_data, pos + 2)
                if (next_instr & 0xF800) == 0xF800:
                    off_hi = instr & 0x7FF
                    off_lo = next_instr & 0x7FF
                    full = (off_hi << 12) | (off_lo << 1)
                    if full >= 0x400000:
                        full -= 0x800000
                    target = addr + 4 + full
                    desc += f"  BL 0x{target:08X}"
                    lines.append(desc)
                    pos += 4
                    continue
        # NOP
        elif instr == 0x46C0:
            desc += "  NOP (MOV R8, R8)"
        elif instr == 0x0000:
            desc += "  NOP (zero)"
        # STR
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = ((instr >> 6) & 0x1F) * 4
            desc += f"  STR R{rd}, [R{rn}, #{imm}]"
        # STRB
        elif (instr & 0xF800) == 0x7000:
            rd = instr & 7
            rn = (instr >> 3) & 7
            imm = (instr >> 6) & 0x1F
            desc += f"  STRB R{rd}, [R{rn}, #{imm}]"

        lines.append(desc)
        pos += 2

    return lines

def get_function_litpool_values(rom_data, func_offset, max_size=1024):
    """Get all literal pool values referenced by LDR Rd, [PC, #imm] in a function."""
    values = []
    pos = func_offset
    end = min(func_offset + max_size, len(rom_data) - 4)
    while pos < end:
        instr = read_u16_le(rom_data, pos)
        # Check for function end
        if pos > func_offset + 2:
            if (instr & 0xFF00) == 0xBD00 or instr == 0x4770:
                break
        # LDR Rd, [PC, #imm]
        if (instr & 0xF800) == 0x4800:
            imm = (instr & 0xFF) * 4
            lit_addr = ((pos + 4) & ~3) + imm
            if lit_addr + 4 <= len(rom_data):
                val = read_u32_le(rom_data, lit_addr)
                values.append((pos - func_offset, val))
        pos += 2
    return values


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    print(f"ROM loaded: {len(rom_data)} bytes ({len(rom_data)/1024/1024:.1f} MB)")
    print()

    # =====================================================================
    # SECTION 1: Disassemble GetMultiplayerId to find patch offset
    # =====================================================================
    print("=" * 70)
    print("  SECTION 1: GetMultiplayerId Disassembly")
    print("=" * 70)
    print()

    gmi_addr = KNOWN_RB["GetMultiplayerId"]  # 0x0833D67F (THUMB = odd)
    gmi_rom_offset = (gmi_addr & ~1) - ROM_BASE  # 0x0033D67E
    print(f"  GetMultiplayerId = 0x{gmi_addr:08X}")
    print(f"  ROM offset = 0x{gmi_rom_offset:06X}")
    print(f"  Disassembly (first 30 instructions):")
    print()

    lines = disassemble_thumb(rom_data, gmi_rom_offset, 30)
    for line in lines:
        print(f"    {line}")

    # Find the SIO_MULTI_CNT reference and the return value point
    print()
    litpool = get_function_litpool_values(rom_data, gmi_rom_offset, 128)
    print(f"  Literal pool values:")
    for off, val in litpool:
        known = ""
        if val == 0x04000120:
            known = " <-- SIO_MULTI_CNT"
        elif 0x03000000 <= val < 0x03008000:
            known = " <-- IWRAM (gWirelessCommType?)"
        elif 0x02000000 <= val < 0x02040000:
            known = " <-- EWRAM"
        print(f"    +0x{off:02X}: 0x{val:08X}{known}")

    # Identify the patch point (where SIO_MULTI_CNT->id is read)
    print()
    print("  PK-GBA patches at GetMultiplayerId+0x10 in vanilla Emerald.")
    print("  Looking for equivalent in R&B (LDR from SIO_MULTI_CNT, then LDRH for id)...")
    for i, line in enumerate(lines):
        if "SIO_MULTI_CNT" in line or "0x04000120" in line:
            print(f"  >>> SIO_MULTI_CNT ref at instruction {i}: {line}")
            if i + 1 < len(lines):
                print(f"      Next: {lines[i+1]}")
            if i + 2 < len(lines):
                print(f"      Next: {lines[i+2]}")
    print()

    # =====================================================================
    # SECTION 2: Scan ALL IWRAM literal pool references
    # =====================================================================
    print("=" * 70)
    print("  SECTION 2: IWRAM Literal Pool References")
    print("=" * 70)
    print()

    iwram_refs = defaultdict(int)
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if 0x03000000 <= val < 0x03008000:
            iwram_refs[val] += 1

    sorted_iwram = sorted(iwram_refs.items(), key=lambda x: -x[1])
    print(f"  {len(sorted_iwram)} unique IWRAM addresses found in ROM literal pools")
    print()

    # Print top 60
    print("  TOP 60 most-referenced IWRAM addresses:")
    for i, (addr, count) in enumerate(sorted_iwram[:60]):
        known = ""
        for name, kaddr in VANILLA_EMERALD.items():
            if kaddr == addr:
                known = f" <-- VANILLA {name}"
        if addr == KNOWN_RB.get("gRngValue", 0):
            known = " <-- gRngValue (KNOWN)"
        print(f"    {i+1:3d}. 0x{addr:08X}  ({count:3d} refs){known}")
    print()

    # =====================================================================
    # SECTION 3: IWRAM Clusters (find link-related variables)
    # =====================================================================
    print("=" * 70)
    print("  SECTION 3: IWRAM Clusters")
    print("=" * 70)
    print()

    all_iwram = sorted(iwram_refs.keys())
    clusters = []
    current = [all_iwram[0]] if all_iwram else []
    for addr in all_iwram[1:]:
        if addr - current[-1] <= 64:
            current.append(addr)
        else:
            if len(current) >= 3:
                clusters.append(current)
            current = [addr]
    if len(current) >= 3:
        clusters.append(current)

    for cluster in clusters:
        start, end = cluster[0], cluster[-1]
        total = sum(iwram_refs[a] for a in cluster)
        print(f"  Cluster 0x{start:08X}-0x{end:08X} ({len(cluster)} vars, {end-start} bytes, {total} refs)")
        for addr in cluster[:15]:
            refs = iwram_refs[addr]
            print(f"    0x{addr:08X} ({refs:3d} refs)")
        if len(cluster) > 15:
            print(f"    ... and {len(cluster)-15} more")
        print()

    # =====================================================================
    # SECTION 4: Find functions referencing SIO_MULTI_CNT (link functions)
    # =====================================================================
    print("=" * 70)
    print("  SECTION 4: Functions Referencing SIO_MULTI_CNT (0x04000120)")
    print("=" * 70)
    print()

    sio_refs = find_all_refs(rom_data, 0x04000120)
    print(f"  {len(sio_refs)} literal pool references to SIO_MULTI_CNT")
    print()

    sio_functions = []
    seen_funcs = set()
    for lit_off in sio_refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start and func_start not in seen_funcs:
            seen_funcs.add(func_start)
            func_addr = ROM_BASE + func_start + 1
            litvals = get_function_litpool_values(rom_data, func_start, 512)
            # Classify by what else it references
            refs_iwram = [v for _, v in litvals if 0x03000000 <= v < 0x03008000]
            refs_ewram = [v for _, v in litvals if 0x02000000 <= v < 0x02040000]
            refs_io = [v for _, v in litvals if 0x04000000 <= v < 0x05000000]

            sio_functions.append({
                'addr': func_addr,
                'offset': func_start,
                'iwram': refs_iwram,
                'ewram': refs_ewram,
                'io': refs_io,
                'all_litvals': litvals,
            })

            # Check if this is GetMultiplayerId
            is_gmi = func_addr == KNOWN_RB["GetMultiplayerId"]
            marker = " <<<< GetMultiplayerId" if is_gmi else ""

            print(f"  Function 0x{func_addr:08X}{marker}")
            print(f"    IWRAM refs: {[f'0x{v:08X}' for v in refs_iwram]}")
            print(f"    EWRAM refs: {[f'0x{v:08X}' for v in refs_ewram]}")
            print(f"    IO refs:    {[f'0x{v:08X}' for v in refs_io]}")
            print()

    # =====================================================================
    # SECTION 5: Cross-reference analysis — find key ROM functions
    # =====================================================================
    print("=" * 70)
    print("  SECTION 5: Key ROM Function Identification")
    print("=" * 70)
    print()

    # Find functions that reference gBattleResources (0x02023A18)
    br_refs = find_all_refs(rom_data, 0x02023A18)
    print(f"  gBattleResources (0x02023A18): {len(br_refs)} literal pool refs")

    # Find functions referencing BOTH gBattleResources AND IWRAM link variables
    print()
    print("  Functions referencing gBattleResources + IWRAM link vars:")
    br_funcs = set()
    for lit_off in br_refs:
        func_start = find_function_start(rom_data, lit_off)
        if func_start:
            br_funcs.add(func_start)

    for func_start in sorted(br_funcs):
        litvals = get_function_litpool_values(rom_data, func_start, 1024)
        iwram_vals = [v for _, v in litvals if 0x03000000 <= v < 0x03008000]
        if iwram_vals:
            func_addr = ROM_BASE + func_start + 1
            print(f"    0x{func_addr:08X}: IWRAM={[f'0x{v:08X}' for v in iwram_vals]}")
    print()

    # Find CB2_HandleStartBattle candidate:
    # - Large function (>500 bytes)
    # - References gBattleResources
    # - References multiple IWRAM addresses
    # - Has many BL calls (>15)
    print("  CB2_HandleStartBattle candidates (large, refs gBattleResources + IWRAM + many BLs):")
    for func_start in sorted(br_funcs):
        litvals = get_function_litpool_values(rom_data, func_start, 2048)
        iwram_vals = [v for _, v in litvals if 0x03000000 <= v < 0x03008000]
        ewram_vals = [v for _, v in litvals if 0x02000000 <= v < 0x02040000]

        if len(iwram_vals) >= 2 and len(ewram_vals) >= 5:
            func_addr = ROM_BASE + func_start + 1
            # Count BL calls
            bl_count = 0
            pos = func_start
            for _ in range(1024):
                if pos + 4 > len(rom_data):
                    break
                instr = read_u16_le(rom_data, pos)
                next_instr = read_u16_le(rom_data, pos + 2)
                if (instr & 0xF800) == 0xF000 and (next_instr & 0xF800) == 0xF800:
                    bl_count += 1
                    pos += 4
                else:
                    pos += 2

            if bl_count >= 10:
                print(f"    0x{func_addr:08X}: {len(ewram_vals)} EWRAM, {len(iwram_vals)} IWRAM, {bl_count} BLs")
                print(f"      IWRAM: {[f'0x{v:08X}' for v in iwram_vals[:8]]}")
                print(f"      EWRAM: {[f'0x{v:08X}' for v in ewram_vals[:8]]}")
                print()

    # =====================================================================
    # SECTION 6: Find EWRAM battle variables via co-reference with gBattleResources
    # =====================================================================
    print("=" * 70)
    print("  SECTION 6: EWRAM addresses co-referenced with gBattleResources")
    print("=" * 70)
    print()

    # For each gBattleResources literal pool ref, find nearby EWRAM addresses
    coref_addrs = defaultdict(int)
    for lit_off in br_refs:
        # Scan ±512 bytes around this literal pool entry for other EWRAM addresses
        start = max(0, lit_off - 512)
        end = min(len(rom_data) - 3, lit_off + 512)
        start = (start + 3) & ~3
        for pos in range(start, end, 4):
            val = read_u32_le(rom_data, pos)
            if 0x02000000 <= val < 0x02040000 and val != 0x02023A18:
                coref_addrs[val] += 1

    # Sort by frequency, filter for battle-region candidates
    sorted_coref = sorted(coref_addrs.items(), key=lambda x: -x[1])

    # Focus on addresses NOT already known
    known_vals = set(KNOWN_RB.values())
    unknown_coref = [(a, c) for a, c in sorted_coref if a not in known_vals]

    print(f"  {len(unknown_coref)} unknown EWRAM addresses co-referenced with gBattleResources")
    print()
    print("  Top 40 (most co-referenced):")
    for i, (addr, count) in enumerate(unknown_coref[:40]):
        print(f"    {i+1:3d}. 0x{addr:08X}  ({count:3d} co-refs)")
    print()

    # Focus on the 0x02008000-0x0200C000 battle region
    battle_coref = [(a, c) for a, c in unknown_coref if 0x02008000 <= a < 0x0200C000]
    if battle_coref:
        print(f"  Battle region (0x02008xxx-0x0200Bxxx) co-references: {len(battle_coref)}")
        for addr, count in battle_coref[:20]:
            print(f"    0x{addr:08X}  ({count:3d} co-refs)")
        print()

    # Focus on the 0x02020000-0x02025000 party/state region
    party_coref = [(a, c) for a, c in unknown_coref if 0x02020000 <= a < 0x02025000]
    if party_coref:
        print(f"  Party/state region (0x02020xxx-0x02024xxx) co-references: {len(party_coref)}")
        for addr, count in party_coref[:20]:
            print(f"    0x{addr:08X}  ({count:3d} co-refs)")
        print()

    # =====================================================================
    # SECTION 7: Specific pattern searches
    # =====================================================================
    print("=" * 70)
    print("  SECTION 7: Specific Pattern Searches")
    print("=" * 70)
    print()

    # A. Find gBattleControllerExecFlags candidates
    # In vanilla: 0x02024068 — a u32 near gActiveBattler (0x02024064)
    # PK-GBA reads it byte-by-byte: emu:read8(addr+0), emu:read8(addr+1), etc.
    # It should have many ROM refs (read/written frequently during battle)
    # Look for EWRAM addresses with many refs in the 0x02008000-0x020240xx range
    print("  A. gBattleControllerExecFlags candidates")
    print("     (u32, heavily referenced, in battle BSS region)")
    print()

    # Check all EWRAM refs, find those with high ref counts in battle region
    all_ewram_refs = defaultdict(int)
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if 0x02000000 <= val < 0x02040000:
            all_ewram_refs[val] += 1

    # Battle BSS candidates: addresses with >20 refs in 0x02008000-0x0200FFFF
    battle_bss = [(a, c) for a, c in all_ewram_refs.items()
                  if 0x02008000 <= a < 0x02010000 and c >= 10]
    battle_bss.sort(key=lambda x: -x[1])
    print(f"    {len(battle_bss)} addresses with >=10 refs in 0x02008xxx-0x0200Fxxx:")
    for addr, count in battle_bss[:30]:
        known = ""
        if addr == KNOWN_RB.get("gBattleTypeFlags"):
            known = " <-- gBattleTypeFlags (KNOWN, 0 refs expected)"
        print(f"      0x{addr:08X}  ({count:3d} refs){known}")
    print()

    # B. Find gLinkPlayers candidates
    # 140 bytes (5 x 28), EWRAM, referenced by link-related functions
    # Should be near other link variables
    print("  B. gLinkPlayers candidates")
    print("     (140 bytes, EWRAM, referenced by SIO_MULTI_CNT functions)")
    print()

    # Find EWRAM addresses referenced by functions that also reference SIO_MULTI_CNT
    sio_coref = defaultdict(int)
    for func_info in sio_functions:
        for _, val in func_info['all_litvals']:
            if 0x02000000 <= val < 0x02040000:
                sio_coref[val] += 1

    sio_sorted = sorted(sio_coref.items(), key=lambda x: -x[1])
    print(f"    EWRAM addresses co-referenced with SIO_MULTI_CNT functions:")
    for i, (addr, count) in enumerate(sio_sorted[:30]):
        known = ""
        for name, kaddr in KNOWN_RB.items():
            if kaddr == addr:
                known = f" <-- {name}"
        print(f"      {i+1:3d}. 0x{addr:08X}  ({count:3d} co-refs){known}")
    print()

    # C. IWRAM addresses co-referenced with SIO_MULTI_CNT functions
    print("  C. IWRAM addresses in SIO_MULTI_CNT functions:")
    sio_iwram = defaultdict(int)
    for func_info in sio_functions:
        for val in func_info['iwram']:
            sio_iwram[val] += 1
    sio_iwram_sorted = sorted(sio_iwram.items(), key=lambda x: -x[1])
    for addr, count in sio_iwram_sorted[:20]:
        print(f"      0x{addr:08X}  ({count:3d} co-refs)")
    print()

    # =====================================================================
    # SECTION 8: Summary — Best candidates for each missing variable
    # =====================================================================
    print("=" * 70)
    print("  SECTION 8: SUMMARY — Best Candidates")
    print("=" * 70)
    print()

    # gWirelessCommType: IWRAM, 1 byte, referenced by GetMultiplayerId
    print("  gWirelessCommType (IWRAM, 1 byte, in GetMultiplayerId):")
    gmi_litvals = get_function_litpool_values(rom_data, gmi_rom_offset, 128)
    for off, val in gmi_litvals:
        if 0x03000000 <= val < 0x03008000:
            print(f"    CANDIDATE: 0x{val:08X} (at GetMultiplayerId+0x{off:02X})")
    print()

    # gReceivedRemoteLinkPlayers: IWRAM, 1 byte, in link battle init functions
    # In vanilla: 0x03003124 — should be near gWirelessCommType
    print("  gReceivedRemoteLinkPlayers (IWRAM, 1 byte, link init):")
    print("    Look in SIO_MULTI_CNT function IWRAM refs above")
    print()

    # gBlockReceivedStatus: IWRAM, 4 bytes, in link data exchange
    print("  gBlockReceivedStatus (IWRAM, 4 bytes, link data exchange):")
    print("    Look in SIO_MULTI_CNT function IWRAM refs above")
    print()

    print("=" * 70)
    print("  SCAN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
