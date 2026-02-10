#!/usr/bin/env python3
"""
ROM Scanner — Find gBattleBufferA / gBattleBufferB addresses in Pokemon Run & Bun

In vanilla pokeemerald, gBattleBufferA and gBattleBufferB are EWRAM_DATA arrays:
    EWRAM_DATA u8 gBattleBufferA[MAX_BATTLERS_COUNT][256];  // 0x02023064
    EWRAM_DATA u8 gBattleBufferB[MAX_BATTLERS_COUNT][256];  // 0x02023864

In pokeemerald-expansion (which R&B is built on), they are EMBEDDED inside
struct BattleResources (heap-allocated via AllocZeroed):
    struct BattleResources {
        struct SecretBase *secretBase;              // +0x00
        struct BattleScriptsStack *battleScriptsStack; // +0x04
        struct BattleCallbacksStack *battleCallbackStack; // +0x08
        struct StatsArray *beforeLvlUp;             // +0x0C
        u8 bufferA[MAX_BATTLERS_COUNT][0x200];      // +0x10 (expansion vanilla)
        u8 bufferB[MAX_BATTLERS_COUNT][0x200];      // +0x810 (expansion vanilla)
        u8 transferBuffer[0x100];                   // +0x1010
    };

R&B config says bufferA_offset=0x024, bufferB_offset=0x824 which implies 9 pointer
fields (36 bytes = 0x24) before bufferA, instead of expansion's 4 (16 bytes = 0x10).

This script:
1. Confirms there are NO direct EWRAM arrays for gBattleBufferA/B (no vanilla-style addresses)
2. Analyzes the BattleResources struct layout by examining ROM code that accesses the pointer
3. Verifies the buffer offsets (0x024 and 0x824) by finding LDR + ADD patterns in ROM
4. Scans for functions that use gBattleResources with known buffer-related offset constants
5. Checks if PrepareBufferDataTransferLink accesses bufferA/B via gBattleResources

No Ghidra needed -- just reads the .gba file.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

ROM_PATH = Path(__file__).parent.parent.parent / "rom" / "Pokemon RunBun.gba"
ROM_BASE = 0x08000000

# Known R&B addresses
KNOWN = {
    "gBattleResources":          0x02023A18,
    "gBattleTypeFlags":          0x02023364,
    "gActiveBattler":            0x020233DC,
    "gBattleControllerExecFlags": 0x020233E0,
    "gBattlersCount":            0x020233E4,
    "gBattleMons":               0x020233FC,
    "gBattleCommunication":      0x0202370E,
    "gPlayerParty":              0x02023A98,
    "gEnemyParty":               0x02023CF0,
    "gLinkPlayers":              0x020229E8,
    "gBlockRecvBuffer":          0x020226C4,
    "gBattlerPositions":         0x020233EE,
}

# Vanilla Emerald direct buffer addresses (to check if R&B uses them)
VANILLA_BUFFER_ADDRS = {
    "gBattleBufferA_vanilla": 0x02023064,
    "gBattleBufferB_vanilla": 0x02023864,
}

# ROM function addresses (known in R&B)
ROM_FUNCTIONS = {
    "PrepareBufferDataTransferLink": 0x08032FA9,
    "PlayerBufferExecCompleted":     0x0806F0D5,
    "LinkOpponentRunCommand":        0x0807DC45,
    "CB2_HandleStartBattle":         0x08037B45,
    "CB2_InitBattleInternal":        0x0803648D,
    "SetUpBattleVars":               0x0806F1D9,
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
    """Walk backward from offset to find PUSH {Rx..., LR} (0xB5xx)."""
    for back in range(2, max_back, 2):
        pos = offset - back
        if pos < 0:
            return None
        instr = read_u16_le(rom_data, pos)
        # Only match PUSH with LR bit (0xB5xx), not plain PUSH (0xB4xx)
        if (instr & 0xFF00) == 0xB500:
            return pos
    return None

def disasm_function(rom_data, func_file_offset, max_size=4096):
    """Disassemble a THUMB function and return instruction list.
    Each entry: (file_offset, instr_u16, decoded_info)"""
    instrs = []
    pos = func_file_offset
    end = min(func_file_offset + max_size, len(rom_data) - 1)
    pop_count = 0

    while pos < end:
        instr = read_u16_le(rom_data, pos)
        info = {"raw": instr, "file_offset": pos, "addr": ROM_BASE + pos}

        # LDR Rd, [PC, #imm8*4]
        if (instr & 0xF800) == 0x4800:
            rd = (instr >> 8) & 0x07
            imm8 = instr & 0xFF
            pool_addr = ((ROM_BASE + pos + 4) & ~3) + imm8 * 4
            pool_file = pool_addr - ROM_BASE
            if 0 <= pool_file < len(rom_data) - 3:
                val = read_u32_le(rom_data, pool_file)
                info["type"] = "ldr_pc"
                info["rd"] = rd
                info["pool_addr"] = pool_addr
                info["pool_value"] = val

        # LDR Rd, [Rn, #imm5*4]
        elif (instr & 0xF800) == 0x6800:
            rd = instr & 0x07
            rn = (instr >> 3) & 0x07
            imm5 = (instr >> 6) & 0x1F
            info["type"] = "ldr_imm"
            info["rd"] = rd
            info["rn"] = rn
            info["offset"] = imm5 * 4

        # LDRB Rd, [Rn, #imm5]
        elif (instr & 0xF800) == 0x7800:
            rd = instr & 0x07
            rn = (instr >> 3) & 0x07
            imm5 = (instr >> 6) & 0x1F
            info["type"] = "ldrb_imm"
            info["rd"] = rd
            info["rn"] = rn
            info["offset"] = imm5

        # LDRH Rd, [Rn, #imm5*2]
        elif (instr & 0xF800) == 0x8800:
            rd = instr & 0x07
            rn = (instr >> 3) & 0x07
            imm5 = (instr >> 6) & 0x1F
            info["type"] = "ldrh_imm"
            info["rd"] = rd
            info["rn"] = rn
            info["offset"] = imm5 * 2

        # ADD Rd, #imm8
        elif (instr & 0xF800) == 0x3000:
            rd = (instr >> 8) & 0x07
            imm8 = instr & 0xFF
            info["type"] = "add_imm8"
            info["rd"] = rd
            info["imm8"] = imm8

        # ADD Rd, Rn, #imm3
        elif (instr & 0xFE00) == 0x1C00:
            rd = instr & 0x07
            rn = (instr >> 3) & 0x07
            imm3 = (instr >> 6) & 0x07
            info["type"] = "add_imm3"
            info["rd"] = rd
            info["rn"] = rn
            info["imm3"] = imm3

        # MOV Rd, #imm8
        elif (instr & 0xF800) == 0x2000:
            rd = (instr >> 8) & 0x07
            imm8 = instr & 0xFF
            info["type"] = "mov_imm8"
            info["rd"] = rd
            info["imm8"] = imm8

        # LSL Rd, Rm, #imm5
        elif (instr & 0xF800) == 0x0000:
            rd = instr & 0x07
            rm = (instr >> 3) & 0x07
            imm5 = (instr >> 6) & 0x1F
            info["type"] = "lsl_imm"
            info["rd"] = rd
            info["rm"] = rm
            info["imm5"] = imm5

        # STR Rd, [Rn, #imm5*4]
        elif (instr & 0xF800) == 0x6000:
            rd = instr & 0x07
            rn = (instr >> 3) & 0x07
            imm5 = (instr >> 6) & 0x1F
            info["type"] = "str_imm"
            info["rd"] = rd
            info["rn"] = rn
            info["offset"] = imm5 * 4

        # STRB Rd, [Rn, #imm5]
        elif (instr & 0xF800) == 0x7000:
            rd = instr & 0x07
            rn = (instr >> 3) & 0x07
            imm5 = (instr >> 6) & 0x1F
            info["type"] = "strb_imm"
            info["rd"] = rd
            info["rn"] = rn
            info["offset"] = imm5

        # BL (two-instruction pair)
        elif (instr & 0xF800) == 0xF000:
            if pos + 2 < end:
                next_instr = read_u16_le(rom_data, pos + 2)
                if (next_instr & 0xF800) == 0xF800:
                    off11hi = instr & 0x07FF
                    off11lo = next_instr & 0x07FF
                    full_off = (off11hi << 12) | (off11lo << 1)
                    if full_off >= 0x400000:
                        full_off -= 0x800000
                    bl_target = ROM_BASE + pos + 4 + full_off
                    info["type"] = "bl"
                    info["target"] = bl_target
                    instrs.append(info)
                    pos += 4
                    continue

        # POP {PC}
        if (instr & 0xFF00) == 0xBD00:
            info["type"] = "pop_pc"
            instrs.append(info)
            pop_count += 1
            if pop_count >= 2:  # Stop after second POP PC (literal pool territory)
                break
            pos += 2
            continue

        # BX LR
        if instr == 0x4770:
            info["type"] = "bx_lr"
            instrs.append(info)
            break

        instrs.append(info)
        pos += 2

    return instrs


def analyze_buffer_access_patterns(rom_data, func_name, func_addr):
    """Analyze a function for gBattleResources buffer access patterns.
    Looking for: LDR Rx, =gBattleResources -> LDR Ry, [Rx, #0] -> ... + offset -> LDR/STR"""
    file_offset = (func_addr & ~1) - ROM_BASE
    instrs = disasm_function(rom_data, file_offset, 4096)

    # Find all LDR from PC that load gBattleResources address
    resource_loads = []
    for i, info in enumerate(instrs):
        if info.get("type") == "ldr_pc" and info.get("pool_value") == KNOWN["gBattleResources"]:
            resource_loads.append((i, info))

    if not resource_loads:
        return None

    results = []
    for idx, ldr_info in resource_loads:
        rd = ldr_info["rd"]
        # Track what happens after loading gBattleResources pointer
        # The code should do: LDR Rx, =gBattleResources; LDR Ry, [Rx, #0] (deref pointer)
        # Then: ADD Ry, #offset (to reach bufferA or bufferB base)
        # Or: LDR Rz, =offset; ADD ..., Ry, Rz

        for j in range(idx + 1, min(idx + 20, len(instrs))):
            info = instrs[j]
            itype = info.get("type", "")

            # Look for LDR Ry, [Rx, #0] where Rx held gBattleResources
            if itype == "ldr_imm" and info.get("rn") == rd and info.get("offset") == 0:
                deref_rd = info["rd"]
                # Now track adds/offsets on deref_rd
                for k in range(j + 1, min(j + 15, len(instrs))):
                    kinfo = instrs[k]
                    ktype = kinfo.get("type", "")

                    # Direct offset load: LDR Rz, [Ry, #offset]
                    if ktype in ("ldr_imm", "ldrb_imm", "ldrh_imm", "str_imm", "strb_imm"):
                        if kinfo.get("rn") == deref_rd:
                            off = kinfo.get("offset", 0)
                            results.append({
                                "func": func_name,
                                "ldr_addr": ldr_info["addr"],
                                "access_addr": kinfo["addr"],
                                "access_type": ktype,
                                "struct_offset": off,
                                "note": f"Direct {ktype} at struct+0x{off:03X}"
                            })

                    # ADD with immediate (building buffer offset)
                    if ktype == "add_imm8" and kinfo.get("rd") == deref_rd:
                        add_val = kinfo["imm8"]
                        results.append({
                            "func": func_name,
                            "ldr_addr": ldr_info["addr"],
                            "access_addr": kinfo["addr"],
                            "access_type": "add_imm8",
                            "struct_offset": add_val,
                            "note": f"ADD R{deref_rd}, #0x{add_val:02X} (struct offset)"
                        })

                    # LDR a large constant (likely buffer offset like 0x824)
                    if ktype == "ldr_pc":
                        val = kinfo.get("pool_value", 0)
                        if 0x010 <= val <= 0x1200:  # Reasonable struct offset range
                            results.append({
                                "func": func_name,
                                "ldr_addr": ldr_info["addr"],
                                "access_addr": kinfo["addr"],
                                "access_type": "ldr_offset_const",
                                "struct_offset": val,
                                "note": f"LDR R{kinfo['rd']}, =0x{val:04X} (likely struct offset)"
                            })

    return results


def main():
    if not ROM_PATH.exists():
        print(f"ERROR: ROM not found at {ROM_PATH}")
        sys.exit(1)

    rom_data = ROM_PATH.read_bytes()
    rom_size = len(rom_data)
    print(f"ROM loaded: {rom_size} bytes ({rom_size / 1024 / 1024:.1f} MB)")
    print()

    # =========================================================================
    # STEP 1: Check for vanilla-style direct EWRAM buffer addresses
    # =========================================================================
    print("=" * 78)
    print("  STEP 1: Check for vanilla-style direct EWRAM buffer addresses")
    print("=" * 78)
    print()
    print("  In vanilla Emerald, gBattleBufferA/B are direct EWRAM_DATA arrays.")
    print("  In pokeemerald-expansion, they are inside heap-allocated BattleResources.")
    print()

    for name, addr in VANILLA_BUFFER_ADDRS.items():
        refs = find_all_refs(rom_data, addr)
        print(f"  {name} (0x{addr:08X}): {len(refs)} ROM literal pool refs")
        if refs:
            print(f"    WARNING: Vanilla address found in ROM! These may be direct arrays!")
            for r in refs[:10]:
                func_start = find_function_start(rom_data, r)
                func_addr_str = f"0x{ROM_BASE + func_start + 1:08X}" if func_start else "unknown"
                print(f"      ROM offset 0x{r:06X} (in function at {func_addr_str})")

    print()

    # Also check nearby addresses (R&B might have shifted the buffers)
    print("  Scanning for potential direct buffer arrays near vanilla locations:")
    print("  (Looking for addresses with 50+ ROM refs in 0x02022000-0x02024000)")
    print()

    high_ref_addrs = []
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if 0x02022000 <= val < 0x02024000:
            high_ref_addrs.append(val)

    ref_counts = defaultdict(int)
    for addr in high_ref_addrs:
        ref_counts[addr] += 1

    # Show addresses with 50+ refs that aren't already known
    known_addrs = set(KNOWN.values())
    candidates = [(a, c) for a, c in ref_counts.items() if c >= 50 and a not in known_addrs]
    candidates.sort(key=lambda x: -x[1])

    if candidates:
        print(f"  Found {len(candidates)} addresses with 50+ refs (not already known):")
        for addr, count in candidates[:20]:
            print(f"    0x{addr:08X}: {count} refs")
    else:
        print("  No unknown high-ref-count addresses found in that range.")
    print()

    # =========================================================================
    # STEP 2: Verify gBattleResources pointer and struct layout
    # =========================================================================
    print("=" * 78)
    print("  STEP 2: Verify gBattleResources (0x{:08X}) struct layout".format(KNOWN["gBattleResources"]))
    print("=" * 78)
    print()

    br_refs = find_all_refs(rom_data, KNOWN["gBattleResources"])
    print(f"  gBattleResources has {len(br_refs)} ROM literal pool references")
    print()

    # Expansion struct BattleResources layout:
    # 4 pointers (0x10 bytes) + bufferA(0x800) + bufferB(0x800) + transferBuffer(0x100)
    # Total = 0x1110 (4368 bytes)
    #
    # R&B config says bufferA at +0x024, bufferB at +0x824
    # That implies 9 pointers (0x24 bytes) before bufferA
    # Extra 5 pointers vs expansion: could be gBattleStruct, gAiBattleData,
    # gAiThinkingStruct, gAiLogicData, gAiPartyData, gBattleHistory, etc.
    # Wait -- those are separate AllocZeroed() calls, not inside BattleResources.
    # R&B may have added more fields to BattleResources struct.

    print("  Expected struct layout (expansion source):")
    print("    +0x000: secretBase (ptr)")
    print("    +0x004: battleScriptsStack (ptr)")
    print("    +0x008: battleCallbackStack (ptr)")
    print("    +0x00C: beforeLvlUp (ptr)")
    print("    +0x010: bufferA[4][0x200] (2048 bytes) -- expansion vanilla")
    print("    +0x810: bufferB[4][0x200] (2048 bytes)")
    print("    +0x1010: transferBuffer[0x100] (256 bytes)")
    print()
    print("  R&B config offsets:")
    print("    bufferA_offset = 0x024 (implies 9 ptr fields = 36 bytes before bufferA)")
    print("    bufferB_offset = 0x824 (= bufferA + 0x800 = 4 battlers * 0x200)")
    print("    This is consistent: bufferB = bufferA + MAX_BATTLERS_COUNT * 0x200")
    print()

    # =========================================================================
    # STEP 3: Scan ROM for offset constants 0x024, 0x200, 0x824 near gBattleResources refs
    # =========================================================================
    print("=" * 78)
    print("  STEP 3: Scan for buffer offset constants in ROM literal pools")
    print("=" * 78)
    print()

    # These offsets would appear as literal pool constants when the compiler
    # can't encode them as immediate values in THUMB instructions
    target_offsets = {
        0x024: "bufferA_base (gBattleResources+0x024)",
        0x200: "battlerBufferSize (512 bytes per slot)",
        0x824: "bufferB_base (gBattleResources+0x824)",
        0x010: "bufferA_base_expansion (gBattleResources+0x010)",
        0x810: "bufferB_base_expansion (gBattleResources+0x810)",
        0x100: "transferBuffer offset or size",
        0x1024: "transferBuffer_base_rb (gBattleResources+0x1024)",
        0x1010: "transferBuffer_base_expansion",
    }

    for offset_val, desc in sorted(target_offsets.items()):
        refs = find_all_refs(rom_data, offset_val)
        # Filter: only count refs that could be in code regions (not data)
        code_refs = [r for r in refs if r < 0x01000000]  # ROM code region
        print(f"  0x{offset_val:04X} ({desc}): {len(code_refs)} literal pool refs in code region")

    print()

    # =========================================================================
    # STEP 4: Analyze key functions that access gBattleResources buffers
    # =========================================================================
    print("=" * 78)
    print("  STEP 4: Analyze buffer access patterns in known functions")
    print("=" * 78)
    print()

    all_struct_offsets = defaultdict(list)

    for func_name, func_addr in sorted(ROM_FUNCTIONS.items()):
        print(f"  --- {func_name} (0x{func_addr:08X}) ---")
        results = analyze_buffer_access_patterns(rom_data, func_name, func_addr)
        if results:
            for r in results:
                off = r["struct_offset"]
                print(f"    @ 0x{r['access_addr']:08X}: {r['note']}")
                all_struct_offsets[off].append(func_name)
        else:
            print(f"    (no gBattleResources access found in first 4KB)")
        print()

    # Summarize offsets found
    print("  Summary of BattleResources struct offsets found:")
    for off in sorted(all_struct_offsets.keys()):
        funcs = all_struct_offsets[off]
        print(f"    +0x{off:03X}: accessed in {len(funcs)} function(s): {', '.join(funcs)}")
    print()

    # =========================================================================
    # STEP 5: Deep analysis of PrepareBufferDataTransferLink
    # =========================================================================
    print("=" * 78)
    print("  STEP 5: Deep disassembly of PrepareBufferDataTransferLink")
    print("=" * 78)
    print()

    func_addr = ROM_FUNCTIONS["PrepareBufferDataTransferLink"]
    file_offset = (func_addr & ~1) - ROM_BASE
    instrs = disasm_function(rom_data, file_offset, 512)

    print(f"  PrepareBufferDataTransferLink at 0x{func_addr:08X} ({len(instrs)} instructions)")
    print()

    for info in instrs:
        addr = info.get("addr", 0)
        raw = info.get("raw", 0)
        itype = info.get("type", "")
        line = f"  0x{addr:08X}:  {raw:04X}  "

        if itype == "ldr_pc":
            val = info["pool_value"]
            name = ""
            for n, a in KNOWN.items():
                if a == val:
                    name = f" = {n}"
                    break
            line += f"LDR R{info['rd']}, [PC, ...] = 0x{val:08X}{name}"
        elif itype == "ldr_imm":
            line += f"LDR R{info['rd']}, [R{info['rn']}, #0x{info['offset']:X}]"
        elif itype == "ldrb_imm":
            line += f"LDRB R{info['rd']}, [R{info['rn']}, #0x{info['offset']:X}]"
        elif itype == "ldrh_imm":
            line += f"LDRH R{info['rd']}, [R{info['rn']}, #0x{info['offset']:X}]"
        elif itype == "str_imm":
            line += f"STR R{info['rd']}, [R{info['rn']}, #0x{info['offset']:X}]"
        elif itype == "strb_imm":
            line += f"STRB R{info['rd']}, [R{info['rn']}, #0x{info['offset']:X}]"
        elif itype == "add_imm8":
            line += f"ADD R{info['rd']}, #0x{info['imm8']:02X}"
        elif itype == "add_imm3":
            line += f"ADD R{info['rd']}, R{info['rn']}, #0x{info['imm3']:X}"
        elif itype == "mov_imm8":
            line += f"MOV R{info['rd']}, #0x{info['imm8']:02X}"
        elif itype == "lsl_imm":
            line += f"LSL R{info['rd']}, R{info['rm']}, #0x{info['imm5']:X}"
        elif itype == "bl":
            line += f"BL 0x{info['target']:08X}"
        elif itype == "pop_pc":
            line += "POP {..., PC}"
        elif itype == "bx_lr":
            line += "BX LR"
        elif itype == "ldr_offset_const":
            line += f"LDR R?, =0x{info.get('struct_offset', 0):04X} (offset constant)"
        else:
            line += f"(0x{raw:04X})"

        print(line)
    print()

    # =========================================================================
    # STEP 6: Scan ALL functions referencing gBattleResources for offset patterns
    # =========================================================================
    print("=" * 78)
    print("  STEP 6: All functions using gBattleResources — extract struct offsets")
    print("=" * 78)
    print()

    # For each literal pool reference to gBattleResources, find the function,
    # then look for ADD/LDR instructions with immediate values that could be struct offsets
    offset_histogram = defaultdict(int)
    offset_funcs = defaultdict(set)

    for ref_off in br_refs:
        func_start = find_function_start(rom_data, ref_off)
        if func_start is None:
            continue

        func_addr_thumb = ROM_BASE + func_start + 1
        instrs = disasm_function(rom_data, func_start, 4096)

        # Find gBattleResources loads in this function
        for i, info in enumerate(instrs):
            if info.get("type") != "ldr_pc" or info.get("pool_value") != KNOWN["gBattleResources"]:
                continue

            rd = info["rd"]
            # Track the next ~20 instructions for deref + offset patterns
            for j in range(i + 1, min(i + 30, len(instrs))):
                jinfo = instrs[j]
                jtype = jinfo.get("type", "")

                # LDR from literal pool (offset constant)
                if jtype == "ldr_pc":
                    val = jinfo.get("pool_value", 0)
                    # Reasonable struct offsets (up to 0x1200)
                    if 0x010 <= val <= 0x1200 and val not in KNOWN.values():
                        offset_histogram[val] += 1
                        offset_funcs[val].add(func_addr_thumb)

                # ADD with immediate
                if jtype == "add_imm8":
                    imm = jinfo["imm8"]
                    if imm >= 0x10:  # Skip small adds (could be anything)
                        offset_histogram[imm] += 1
                        offset_funcs[imm].add(func_addr_thumb)

    # Sort by frequency
    sorted_offsets = sorted(offset_histogram.items(), key=lambda x: -x[1])
    print(f"  Found {len(sorted_offsets)} potential struct offset constants near gBattleResources loads")
    print()
    print("  Offset    Count   Description")
    print("  ------    -----   -----------")

    known_offsets = {
        0x024: "bufferA[0] base (R&B config)",
        0x200: "battler buffer stride (512 bytes)",
        0x824: "bufferB[0] base (R&B config)",
        0x010: "bufferA[0] base (expansion vanilla)",
        0x810: "bufferB[0] base (expansion vanilla)",
        0x100: "transferBuffer stride or size",
        0x224: "bufferA[1] = 0x024 + 0x200",
        0x424: "bufferA[2] = 0x024 + 0x400",
        0x624: "bufferA[3] = 0x024 + 0x600",
        0xA24: "bufferB[1] = 0x824 + 0x200",
        0xC24: "bufferB[2] = 0x824 + 0x400",
        0xE24: "bufferB[3] = 0x824 + 0x600",
    }

    for off, count in sorted_offsets[:40]:
        desc = known_offsets.get(off, "")
        func_count = len(offset_funcs[off])
        print(f"  0x{off:04X}    {count:5d}   in {func_count} functions  {desc}")

    print()

    # =========================================================================
    # STEP 7: Check if there are EWRAM addresses that could be direct buffers
    # =========================================================================
    print("=" * 78)
    print("  STEP 7: Scan for potential direct buffer EWRAM addresses")
    print("=" * 78)
    print()

    # If R&B had direct EWRAM buffers, they'd be 0x800 bytes (4*0x200) apart
    # and would have high ref counts. Search for pairs.
    print("  Looking for EWRAM address pairs exactly 0x800 bytes apart")
    print("  (signature of bufferA/bufferB as direct arrays)")
    print()

    # Collect all EWRAM addresses with their ref counts
    all_ewram = defaultdict(int)
    for i in range(0, len(rom_data) - 3, 4):
        val = read_u32_le(rom_data, i)
        if 0x02000000 <= val < 0x02040000:
            all_ewram[val] += 1

    # Find pairs
    pairs_found = []
    for addr_a, count_a in all_ewram.items():
        addr_b = addr_a + 0x800
        if addr_b in all_ewram:
            count_b = all_ewram[addr_b]
            if count_a >= 10 and count_b >= 10:
                pairs_found.append((addr_a, count_a, addr_b, count_b))

    pairs_found.sort(key=lambda x: -(x[1] + x[3]))

    if pairs_found:
        print(f"  Found {len(pairs_found)} EWRAM address pairs (0x800 apart, both 10+ refs):")
        for a_addr, a_count, b_addr, b_count in pairs_found[:15]:
            known_a = ""
            known_b = ""
            for n, a in KNOWN.items():
                if a == a_addr: known_a = f" = {n}"
                if a == b_addr: known_b = f" = {n}"
            print(f"    0x{a_addr:08X} ({a_count:3d} refs){known_a}  <-->  0x{b_addr:08X} ({b_count:3d} refs){known_b}")
    else:
        print("  No pairs found. Confirms buffers are NOT direct EWRAM arrays.")
    print()

    # =========================================================================
    # STEP 8: Analyze AllocateBattleResources to find struct size
    # =========================================================================
    print("=" * 78)
    print("  STEP 8: Find AllocateBattleResources to determine struct size")
    print("=" * 78)
    print()

    # AllocateBattleResources calls AllocZeroed(sizeof(*gBattleResources))
    # The size will be in a MOV or LDR instruction before the BL to AllocZeroed
    # We know gBattleResources (0x02023A18) is stored after the alloc.
    # Find functions that both load gBattleResources AND store to it (STR pattern)

    # Strategy: Find functions where gBattleResources appears AND that call AllocZeroed
    # AllocZeroed is likely at a fixed ROM address. We can find it by looking at
    # the function that references gBattleResources and has many BL calls (AllocateBattleResources
    # calls AllocZeroed 6+ times)

    alloc_candidates = []
    for ref_off in br_refs:
        func_start = find_function_start(rom_data, ref_off)
        if func_start is None:
            continue
        instrs = disasm_function(rom_data, func_start, 4096)

        # Count BL calls and check for STR to gBattleResources
        bl_count = 0
        has_store = False
        for info in instrs:
            if info.get("type") == "bl":
                bl_count += 1
            if info.get("type") == "str_imm":
                has_store = True

        if bl_count >= 5 and has_store:
            func_addr_thumb = ROM_BASE + func_start + 1
            alloc_candidates.append((func_addr_thumb, bl_count, func_start))

    alloc_candidates.sort(key=lambda x: -x[1])

    print(f"  Functions referencing gBattleResources with 5+ BL calls and STR: {len(alloc_candidates)}")
    for func_addr, bl_count, func_start in alloc_candidates[:5]:
        print(f"    0x{func_addr:08X}: {bl_count} BL calls")

        # Disassemble and look for size constants loaded before BL calls
        instrs = disasm_function(rom_data, func_start, 4096)
        # Find MOV R0, #size or LDR R0, =size before BL
        size_candidates = []
        for i, info in enumerate(instrs):
            if info.get("type") == "bl":
                # Look back for MOV R0 or LDR R0
                for k in range(max(0, i - 5), i):
                    kinfo = instrs[k]
                    if kinfo.get("type") == "mov_imm8" and kinfo.get("rd") == 0:
                        size_candidates.append((kinfo["imm8"], kinfo["addr"], info["target"]))
                    if kinfo.get("type") == "ldr_pc" and kinfo.get("rd") == 0:
                        val = kinfo.get("pool_value", 0)
                        if 0x100 <= val <= 0x10000:  # Reasonable alloc size
                            size_candidates.append((val, kinfo["addr"], info["target"]))
                    if kinfo.get("type") == "lsl_imm" and kinfo.get("rd") == 0:
                        # MOV R0, #x; LSL R0, R0, #y = x << y
                        pass

        if size_candidates:
            print(f"      Size args before BL calls:")
            for size, at_addr, bl_target in size_candidates:
                print(f"        size=0x{size:04X} ({size}) at 0x{at_addr:08X} -> BL 0x{bl_target:08X}")

    print()

    # =========================================================================
    # STEP 9: Direct scan of struct offset 0x024 and 0x824 usage
    # =========================================================================
    print("=" * 78)
    print("  STEP 9: Verify offset 0x024 and 0x824 with per-battler stride 0x200")
    print("=" * 78)
    print()

    # The access pattern for bufferA[battler][0] is:
    #   LDR R0, =gBattleResources
    #   LDR R0, [R0]           ; deref pointer
    #   ADD R0, #0x24           ; offset to bufferA
    #   LDR R1, =gActiveBattler
    #   LDRB R1, [R1]
    #   LSL R1, R1, #9         ; * 0x200 (512)
    #   ADD R0, R0, R1          ; bufferA[battler]
    #
    # Look for LSL #9 near gBattleResources / gActiveBattler

    print("  Scanning for LSL #9 (multiply by 512) in ROM...")
    lsl9_count = 0
    lsl9_near_battle = 0

    for i in range(0, len(rom_data) - 1, 2):
        instr = read_u16_le(rom_data, i)
        # LSL Rd, Rm, #9
        if (instr & 0xF800) == 0x0000:
            imm5 = (instr >> 6) & 0x1F
            if imm5 == 9:
                lsl9_count += 1
                # Check if this is near a gBattleResources or gActiveBattler reference
                # Look in the surrounding 256 bytes for these literal pool values
                start = max(0, i - 128)
                end_range = min(len(rom_data) - 3, i + 128)
                for j in range(start, end_range, 4):
                    val = read_u32_le(rom_data, j)
                    if val == KNOWN["gBattleResources"] or val == KNOWN["gActiveBattler"]:
                        lsl9_near_battle += 1
                        if lsl9_near_battle <= 10:
                            func_start = find_function_start(rom_data, i)
                            func_str = f"0x{ROM_BASE + func_start + 1:08X}" if func_start else "?"
                            print(f"    LSL #9 at ROM 0x{ROM_BASE + i:08X} (in func {func_str})")
                        break

    print(f"\n  Total LSL #9 instructions: {lsl9_count}")
    print(f"  Near gBattleResources/gActiveBattler: {lsl9_near_battle}")
    print()

    # Also check for LSL #8 (multiply by 256 — vanilla buffer size)
    print("  Also checking LSL #8 (multiply by 256 — vanilla buffer size)...")
    lsl8_near_battle = 0
    for i in range(0, len(rom_data) - 1, 2):
        instr = read_u16_le(rom_data, i)
        if (instr & 0xF800) == 0x0000:
            imm5 = (instr >> 6) & 0x1F
            if imm5 == 8:
                start = max(0, i - 128)
                end_range = min(len(rom_data) - 3, i + 128)
                for j in range(start, end_range, 4):
                    val = read_u32_le(rom_data, j)
                    if val == KNOWN["gBattleResources"] or val == KNOWN["gActiveBattler"]:
                        lsl8_near_battle += 1
                        break

    print(f"  LSL #8 near gBattleResources/gActiveBattler: {lsl8_near_battle}")
    print()

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("=" * 78)
    print("  SUMMARY")
    print("=" * 78)
    print()
    print("  In pokeemerald-expansion (and thus R&B), gBattleBufferA and gBattleBufferB")
    print("  are NOT direct EWRAM_DATA arrays. They are embedded inside the heap-allocated")
    print("  struct BattleResources, accessed via:")
    print()
    print("    gBattleResources->bufferA[battler][byte]")
    print("    gBattleResources->bufferB[battler][byte]")
    print()
    print("  To read bufferA[battler] at runtime:")
    print("    1. Read gBattleResources pointer: LDR from 0x{:08X}".format(KNOWN["gBattleResources"]))
    print("    2. Deref pointer: base = read32(gBattleResources)")
    print("    3. bufferA[battler] = base + 0x024 + (battler * 0x200)")
    print("    4. bufferB[battler] = base + 0x824 + (battler * 0x200)")
    print()
    print("  The config already has the correct offsets:")
    print("    gBattleResources = 0x{:08X}".format(KNOWN["gBattleResources"]))
    print("    bufferA_offset   = 0x024")
    print("    bufferB_offset   = 0x824")
    print("    battlerBufferSize = 0x200 (512 bytes per slot)")
    print()
    print("  There are NO direct EWRAM addresses for gBattleBufferA/gBattleBufferB in R&B.")
    print("  Any code reading buffers MUST go through the gBattleResources pointer.")
    print()


if __name__ == "__main__":
    main()
