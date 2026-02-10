"""
Find LinkOpponentBufferExecCompleted, PlayerBufferExecCompleted,
PrepareBufferDataTransferLink, and related functions in the Run & Bun ROM.

Strategy:
- Scan ROM literal pools for known address constants
- LinkOpponentBufferExecCompleted references:
  - LinkOpponentBufferRunCommand = 0x0807DC45
  - gBattlerControllerFuncs = 0x03005D70
  - gBattleTypeFlags = 0x02023364
- PlayerBufferExecCompleted references:
  - PlayerBufferRunCommand = 0x0806F151
  - gBattlerControllerFuncs = 0x03005D70
  - gBattleTypeFlags = 0x02023364
- Both call GetMultiplayerId and PrepareBufferDataTransferLink in the LINK path
- Both reference gBattleControllerExecFlags = 0x020233E0 and gBitTable

Also find OpponentBufferExecCompleted (AI version):
  - OpponentBufferRunCommand = 0x081BAD85
  - gBattlerControllerFuncs = 0x03005D70
  - gBattleControllerExecFlags = 0x020233E0
"""

import struct
import sys
import os

ROM_PATH = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"

# Known addresses from config
KNOWN = {
    "LinkOpponentBufferRunCommand": 0x0807DC45,
    "PlayerBufferRunCommand": 0x0806F151,
    "OpponentBufferRunCommand": 0x081BAD85,
    "LinkPartnerBufferRunCommand": 0x0807793D,
    "gBattlerControllerFuncs": 0x03005D70,
    "gBattleTypeFlags": 0x02023364,
    "gBattleControllerExecFlags": 0x020233E0,
    "gBitTable": None,  # Will find
    "GetMultiplayerId": 0x0800A4B1,
    "PrepareBufferDataTransferLink": 0x080330F5,
    "PrepareBufferDataTransfer": 0x08032FA9,
    "gBattleResources": 0x02023A18,
    "gActiveBattler": 0x020233DC,
    "BattleControllerDummy": 0x0806F0A1,
}

def read_rom(path):
    with open(path, "rb") as f:
        return f.read()

def find_all_u32(rom, value):
    """Find all occurrences of a 32-bit value in ROM (little-endian)."""
    needle = struct.pack("<I", value)
    results = []
    offset = 0
    while True:
        idx = rom.find(needle, offset)
        if idx == -1:
            break
        results.append(idx)
        offset = idx + 1
    return results

def decode_bl(rom, addr):
    """Decode a THUMB BL instruction at ROM offset addr. Returns target ROM address or None."""
    if addr + 4 > len(rom):
        return None
    hw1 = struct.unpack_from("<H", rom, addr)[0]
    hw2 = struct.unpack_from("<H", rom, addr + 2)[0]
    # BL: hw1 = 11110 + offset_hi(11), hw2 = 11111 + offset_lo(11)
    if (hw1 & 0xF800) != 0xF000:
        return None
    if (hw2 & 0xF800) != 0xF800:
        return None
    offset_hi = hw1 & 0x07FF
    offset_lo = hw2 & 0x07FF
    # Sign extend offset_hi
    if offset_hi & 0x400:
        offset_hi |= 0xFFFFF800
        offset_hi = offset_hi - 0x100000000 if offset_hi >= 0x80000000 else offset_hi
        # Actually: sign extend 11-bit to 32-bit
        offset_hi = offset_hi | (~0x7FF)  # This is wrong, let me redo
    # Proper sign extension for 11-bit
    offset_hi_signed = offset_hi if offset_hi < 0x400 else offset_hi - 0x800
    target = (0x08000000 + addr + 4) + (offset_hi_signed << 12) + (offset_lo << 1)
    return target & 0xFFFFFFFF

def find_literal_pool_refs(rom, value, max_rom_offset=None):
    """Find literal pool entries containing value and identify which function loads them."""
    if max_rom_offset is None:
        max_rom_offset = len(rom)

    needle = struct.pack("<I", value)
    results = []
    offset = 0
    while True:
        idx = rom.find(needle, offset)
        if idx == -1 or idx >= max_rom_offset:
            break
        # Literal pools are word-aligned
        if idx % 4 == 0:
            # Search backward for LDR instructions that reference this pool entry
            # THUMB LDR Rd, [PC, #imm] format: 0100 1RRR iiii iiii
            # The PC-relative offset is imm * 4, and PC is (current_addr + 4) & ~2
            for back in range(4, 1024, 2):  # Search up to 1024 bytes before the literal
                ldr_addr = idx - back
                if ldr_addr < 0:
                    break
                hw = struct.unpack_from("<H", rom, ldr_addr)[0]
                if (hw & 0xF800) == 0x4800:  # LDR Rd, [PC, #imm]
                    imm = (hw & 0xFF) * 4
                    pc = (0x08000000 + ldr_addr + 4) & ~2
                    target = pc + imm
                    rom_target = target - 0x08000000
                    if rom_target == idx:
                        rd = (hw >> 8) & 0x07
                        results.append({
                            "pool_offset": idx,
                            "ldr_offset": ldr_addr,
                            "ldr_addr": 0x08000000 + ldr_addr,
                            "register": f"R{rd}",
                            "value": value,
                        })
        offset = idx + 1
    return results

def find_function_start(rom, offset, max_search=512):
    """Try to find the start of a THUMB function by looking for a PUSH instruction."""
    # PUSH {Rlist, LR}: 1011 0101 xxxx xxxx (0xB5xx)
    # PUSH {Rlist}:      1011 0100 xxxx xxxx (0xB4xx)
    for back in range(0, max_search, 2):
        addr = offset - back
        if addr < 0:
            break
        hw = struct.unpack_from("<H", rom, addr)[0]
        if (hw & 0xFF00) == 0xB500:  # PUSH {Rlist, LR}
            return addr
        # Also check for function alignment markers (0x0000 before PUSH)
        if back > 0 and (hw & 0xFF00) == 0xB500:
            return addr
    return None

def disasm_function_simple(rom, start_offset, max_bytes=512):
    """Extract basic info about a THUMB function: BL targets, literal loads, STR instructions."""
    bls = []
    ldrs = []
    strs = []
    end_offset = min(start_offset + max_bytes, len(rom))

    offset = start_offset
    while offset < end_offset:
        hw = struct.unpack_from("<H", rom, offset)[0]

        # BL instruction (2 halfwords)
        if (hw & 0xF800) == 0xF000 and offset + 2 < end_offset:
            hw2 = struct.unpack_from("<H", rom, offset + 2)[0]
            if (hw2 & 0xF800) == 0xF800:
                target = decode_bl(rom, offset)
                if target:
                    bls.append({"offset": offset, "target": target})
                offset += 4
                continue

        # LDR Rd, [PC, #imm]
        if (hw & 0xF800) == 0x4800:
            rd = (hw >> 8) & 0x07
            imm = (hw & 0xFF) * 4
            pc = (0x08000000 + offset + 4) & ~2
            pool_addr = pc + imm
            pool_rom = pool_addr - 0x08000000
            if 0 <= pool_rom < len(rom) - 3:
                val = struct.unpack_from("<I", rom, pool_rom)[0]
                ldrs.append({"offset": offset, "register": f"R{rd}", "pool_rom": pool_rom, "value": val})

        # STR Rd, [Rn, #imm] — 0110 0xxx xxxx xxxx
        if (hw & 0xF800) == 0x6000:
            imm5 = ((hw >> 6) & 0x1F) * 4
            rn = (hw >> 3) & 0x07
            rd = hw & 0x07
            strs.append({"offset": offset, "rd": f"R{rd}", "rn": f"R{rn}", "imm": imm5})

        # POP {Rlist, PC} — return
        if (hw & 0xFF00) == 0xBD00:
            # Possible function end
            pass

        # BX LR
        if hw == 0x4770:
            pass

        offset += 2

    return {"bls": bls, "ldrs": ldrs, "strs": strs}

def main():
    print(f"Loading ROM: {ROM_PATH}")
    rom = read_rom(ROM_PATH)
    print(f"ROM size: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)")
    print()

    # ====================================================================
    # Strategy 1: Find functions that load LinkOpponentBufferRunCommand
    # ====================================================================
    print("=" * 80)
    print("FINDING LinkOpponentBufferExecCompleted")
    print("=" * 80)
    print()

    # Find all literal pool refs to LinkOpponentBufferRunCommand
    link_opp_run_cmd = KNOWN["LinkOpponentBufferRunCommand"]
    print(f"Scanning for literal pool refs to LinkOpponentBufferRunCommand (0x{link_opp_run_cmd:08X})...")
    refs = find_literal_pool_refs(rom, link_opp_run_cmd)
    print(f"  Found {len(refs)} LDR references:")
    for r in refs:
        print(f"    ROM 0x{r['ldr_offset']:06X} (0x{r['ldr_addr']:08X}): LDR {r['register']}, =0x{r['value']:08X}")
    print()

    # For each ref, find the function start and analyze
    for r in refs:
        func_start = find_function_start(rom, r["ldr_offset"])
        if func_start is None:
            continue
        func_addr = 0x08000000 + func_start
        func_size = r["ldr_offset"] - func_start

        # Analyze the function
        info = disasm_function_simple(rom, func_start, max_bytes=300)

        # Check if this function also references gBattlerControllerFuncs and gBattleTypeFlags
        has_ctrl_funcs = any(l["value"] == KNOWN["gBattlerControllerFuncs"] for l in info["ldrs"])
        has_btl_flags = any(l["value"] == KNOWN["gBattleTypeFlags"] for l in info["ldrs"])
        has_exec_flags = any(l["value"] == KNOWN["gBattleControllerExecFlags"] for l in info["ldrs"])

        # Check for BL to GetMultiplayerId or PrepareBufferDataTransferLink
        bl_targets = [bl["target"] for bl in info["bls"]]
        has_get_mp = KNOWN["GetMultiplayerId"] in bl_targets
        has_prep_link = KNOWN["PrepareBufferDataTransferLink"] in bl_targets
        has_prep_buf = KNOWN["PrepareBufferDataTransfer"] in bl_targets

        print(f"  Function at ROM 0x{func_start:06X} (0x{func_addr:08X} | THUMB 0x{func_addr|1:08X}):")
        print(f"    References LinkOpponentBufferRunCommand: YES")
        print(f"    References gBattlerControllerFuncs:      {'YES' if has_ctrl_funcs else 'no'}")
        print(f"    References gBattleTypeFlags:             {'YES' if has_btl_flags else 'no'}")
        print(f"    References gBattleControllerExecFlags:   {'YES' if has_exec_flags else 'no'}")
        print(f"    BL to GetMultiplayerId:                  {'YES' if has_get_mp else 'no'}")
        print(f"    BL to PrepareBufferDataTransferLink:     {'YES' if has_prep_link else 'no'}")
        print(f"    BL to PrepareBufferDataTransfer:         {'YES' if has_prep_buf else 'no'}")

        # List all LDR values
        print(f"    All LDR values:")
        for l in info["ldrs"]:
            print(f"      0x{l['offset']:06X}: LDR {l['register']}, =0x{l['value']:08X}")

        # List all BL targets
        print(f"    All BL targets:")
        for bl in info["bls"]:
            print(f"      0x{bl['offset']:06X}: BL 0x{bl['target']:08X}")

        if has_ctrl_funcs and (has_btl_flags or has_exec_flags):
            print(f"    >>> LIKELY LinkOpponentBufferExecCompleted at 0x{func_addr|1:08X}")
        print()

    # ====================================================================
    # Strategy 2: Find PlayerBufferExecCompleted
    # ====================================================================
    print("=" * 80)
    print("FINDING PlayerBufferExecCompleted")
    print("=" * 80)
    print()

    player_run_cmd = KNOWN["PlayerBufferRunCommand"]
    print(f"Scanning for literal pool refs to PlayerBufferRunCommand (0x{player_run_cmd:08X})...")
    refs = find_literal_pool_refs(rom, player_run_cmd)
    print(f"  Found {len(refs)} LDR references:")
    for r in refs:
        print(f"    ROM 0x{r['ldr_offset']:06X} (0x{r['ldr_addr']:08X}): LDR {r['register']}, =0x{r['value']:08X}")
    print()

    for r in refs:
        func_start = find_function_start(rom, r["ldr_offset"])
        if func_start is None:
            continue
        func_addr = 0x08000000 + func_start
        info = disasm_function_simple(rom, func_start, max_bytes=300)

        has_ctrl_funcs = any(l["value"] == KNOWN["gBattlerControllerFuncs"] for l in info["ldrs"])
        has_btl_flags = any(l["value"] == KNOWN["gBattleTypeFlags"] for l in info["ldrs"])
        has_exec_flags = any(l["value"] == KNOWN["gBattleControllerExecFlags"] for l in info["ldrs"])

        bl_targets = [bl["target"] for bl in info["bls"]]
        has_get_mp = KNOWN["GetMultiplayerId"] in bl_targets
        has_prep_link = KNOWN["PrepareBufferDataTransferLink"] in bl_targets
        has_prep_buf = KNOWN["PrepareBufferDataTransfer"] in bl_targets

        print(f"  Function at ROM 0x{func_start:06X} (0x{func_addr:08X} | THUMB 0x{func_addr|1:08X}):")
        print(f"    References PlayerBufferRunCommand:       YES")
        print(f"    References gBattlerControllerFuncs:      {'YES' if has_ctrl_funcs else 'no'}")
        print(f"    References gBattleTypeFlags:             {'YES' if has_btl_flags else 'no'}")
        print(f"    References gBattleControllerExecFlags:   {'YES' if has_exec_flags else 'no'}")
        print(f"    BL to GetMultiplayerId:                  {'YES' if has_get_mp else 'no'}")
        print(f"    BL to PrepareBufferDataTransferLink:     {'YES' if has_prep_link else 'no'}")
        print(f"    BL to PrepareBufferDataTransfer:         {'YES' if has_prep_buf else 'no'}")

        print(f"    All LDR values:")
        for l in info["ldrs"]:
            print(f"      0x{l['offset']:06X}: LDR {l['register']}, =0x{l['value']:08X}")
        print(f"    All BL targets:")
        for bl in info["bls"]:
            print(f"      0x{bl['offset']:06X}: BL 0x{bl['target']:08X}")

        if has_ctrl_funcs and (has_btl_flags or has_exec_flags):
            print(f"    >>> LIKELY PlayerBufferExecCompleted at 0x{func_addr|1:08X}")
        print()

    # ====================================================================
    # Strategy 3: Find OpponentBufferExecCompleted (AI)
    # ====================================================================
    print("=" * 80)
    print("FINDING OpponentBufferExecCompleted (AI)")
    print("=" * 80)
    print()

    opp_run_cmd = KNOWN["OpponentBufferRunCommand"]
    print(f"Scanning for literal pool refs to OpponentBufferRunCommand (0x{opp_run_cmd:08X})...")
    refs = find_literal_pool_refs(rom, opp_run_cmd)
    print(f"  Found {len(refs)} LDR references:")
    for r in refs:
        print(f"    ROM 0x{r['ldr_offset']:06X} (0x{r['ldr_addr']:08X}): LDR {r['register']}, =0x{r['value']:08X}")
    print()

    for r in refs:
        func_start = find_function_start(rom, r["ldr_offset"])
        if func_start is None:
            continue
        func_addr = 0x08000000 + func_start
        info = disasm_function_simple(rom, func_start, max_bytes=300)

        has_ctrl_funcs = any(l["value"] == KNOWN["gBattlerControllerFuncs"] for l in info["ldrs"])
        has_btl_flags = any(l["value"] == KNOWN["gBattleTypeFlags"] for l in info["ldrs"])
        has_exec_flags = any(l["value"] == KNOWN["gBattleControllerExecFlags"] for l in info["ldrs"])

        bl_targets = [bl["target"] for bl in info["bls"]]
        has_get_mp = KNOWN["GetMultiplayerId"] in bl_targets

        print(f"  Function at ROM 0x{func_start:06X} (0x{func_addr:08X} | THUMB 0x{func_addr|1:08X}):")
        print(f"    References OpponentBufferRunCommand:     YES")
        print(f"    References gBattlerControllerFuncs:      {'YES' if has_ctrl_funcs else 'no'}")
        print(f"    References gBattleTypeFlags:             {'YES' if has_btl_flags else 'no'}")
        print(f"    References gBattleControllerExecFlags:   {'YES' if has_exec_flags else 'no'}")
        print(f"    BL to GetMultiplayerId:                  {'YES' if has_get_mp else 'no'}")

        print(f"    All LDR values:")
        for l in info["ldrs"]:
            print(f"      0x{l['offset']:06X}: LDR {l['register']}, =0x{l['value']:08X}")
        print(f"    All BL targets:")
        for bl in info["bls"]:
            print(f"      0x{bl['offset']:06X}: BL 0x{bl['target']:08X}")

        if has_ctrl_funcs and has_exec_flags and not has_btl_flags:
            print(f"    >>> LIKELY OpponentBufferExecCompleted (AI, no LINK check) at 0x{func_addr|1:08X}")
        elif has_ctrl_funcs and (has_btl_flags or has_exec_flags):
            print(f"    >>> LIKELY OpponentBufferExecCompleted at 0x{func_addr|1:08X}")
        print()

    # ====================================================================
    # Strategy 4: Find LinkPartnerBufferExecCompleted
    # ====================================================================
    print("=" * 80)
    print("FINDING LinkPartnerBufferExecCompleted")
    print("=" * 80)
    print()

    link_partner_run_cmd = KNOWN["LinkPartnerBufferRunCommand"]
    print(f"Scanning for literal pool refs to LinkPartnerBufferRunCommand (0x{link_partner_run_cmd:08X})...")
    refs = find_literal_pool_refs(rom, link_partner_run_cmd)
    print(f"  Found {len(refs)} LDR references:")
    for r in refs:
        print(f"    ROM 0x{r['ldr_offset']:06X} (0x{r['ldr_addr']:08X}): LDR {r['register']}, =0x{r['value']:08X}")
    print()

    for r in refs:
        func_start = find_function_start(rom, r["ldr_offset"])
        if func_start is None:
            continue
        func_addr = 0x08000000 + func_start
        info = disasm_function_simple(rom, func_start, max_bytes=300)

        has_ctrl_funcs = any(l["value"] == KNOWN["gBattlerControllerFuncs"] for l in info["ldrs"])
        has_btl_flags = any(l["value"] == KNOWN["gBattleTypeFlags"] for l in info["ldrs"])
        has_exec_flags = any(l["value"] == KNOWN["gBattleControllerExecFlags"] for l in info["ldrs"])

        bl_targets = [bl["target"] for bl in info["bls"]]
        has_get_mp = KNOWN["GetMultiplayerId"] in bl_targets

        print(f"  Function at ROM 0x{func_start:06X} (0x{func_addr:08X} | THUMB 0x{func_addr|1:08X}):")
        print(f"    References LinkPartnerBufferRunCommand:  YES")
        print(f"    References gBattlerControllerFuncs:      {'YES' if has_ctrl_funcs else 'no'}")
        print(f"    References gBattleTypeFlags:             {'YES' if has_btl_flags else 'no'}")
        print(f"    References gBattleControllerExecFlags:   {'YES' if has_exec_flags else 'no'}")
        print(f"    BL to GetMultiplayerId:                  {'YES' if has_get_mp else 'no'}")

        print(f"    All LDR values:")
        for l in info["ldrs"]:
            print(f"      0x{l['offset']:06X}: LDR {l['register']}, =0x{l['value']:08X}")
        print(f"    All BL targets:")
        for bl in info["bls"]:
            print(f"      0x{bl['offset']:06X}: BL 0x{bl['target']:08X}")

        if has_ctrl_funcs and (has_btl_flags or has_exec_flags):
            print(f"    >>> LIKELY LinkPartnerBufferExecCompleted at 0x{func_addr|1:08X}")
        print()

    # ====================================================================
    # Strategy 5: Find PrepareBufferDataTransferLink by scanning callers
    # ====================================================================
    print("=" * 80)
    print("FINDING PrepareBufferDataTransferLink (verify known address)")
    print("=" * 80)
    print()

    prep_link = KNOWN["PrepareBufferDataTransferLink"]
    print(f"Scanning for literal pool refs to PrepareBufferDataTransferLink (0x{prep_link:08X})...")
    refs = find_literal_pool_refs(rom, prep_link)
    print(f"  Found {len(refs)} LDR references to function pointer")
    print()

    # Also find where it's called as BL target
    print(f"Scanning for BL instructions targeting 0x{prep_link:08X}...")
    bl_callers = []
    # BL target = prep_link, so for each possible BL instruction, check if decode matches
    # More efficient: iterate through ROM looking for BL instructions
    for offset in range(0, min(len(rom) - 4, 0x200000), 2):
        hw1 = struct.unpack_from("<H", rom, offset)[0]
        if (hw1 & 0xF800) != 0xF000:
            continue
        hw2 = struct.unpack_from("<H", rom, offset + 2)[0]
        if (hw2 & 0xF800) != 0xF800:
            continue
        target = decode_bl(rom, offset)
        if target == prep_link:
            bl_callers.append(offset)
    print(f"  Found {len(bl_callers)} BL callers:")
    for caller in bl_callers:
        func_start = find_function_start(rom, caller)
        func_info = ""
        if func_start:
            func_info = f" (in function at 0x{0x08000000+func_start:08X})"
        print(f"    ROM 0x{caller:06X} (0x{0x08000000+caller:08X}): BL 0x{prep_link:08X}{func_info}")
    print()

    # ====================================================================
    # Strategy 6: Verify existing config addresses
    # ====================================================================
    print("=" * 80)
    print("VERIFICATION: Compare with config addresses")
    print("=" * 80)
    print()

    config_addrs = {
        "PlayerBufferExecCompleted": 0x0806F0D5,
        "LinkOpponentBufferExecCompleted": 0x0807E911,
        "LinkPartnerBufferExecCompleted": 0x08078789,
        "OpponentBufferExecCompleted": 0x081BB945,
        "PrepareBufferDataTransferLink": 0x080330F5,
        "PrepareBufferDataTransfer": 0x08032FA9,
    }

    for name, addr in config_addrs.items():
        rom_offset = (addr & ~1) - 0x08000000  # Strip THUMB bit
        if rom_offset < 0 or rom_offset >= len(rom):
            print(f"  {name}: 0x{addr:08X} — OUT OF ROM RANGE")
            continue

        hw = struct.unpack_from("<H", rom, rom_offset)[0]
        is_push = (hw & 0xFF00) == 0xB500
        print(f"  {name}: 0x{addr:08X} (ROM 0x{rom_offset:06X})")
        print(f"    First halfword: 0x{hw:04X} {'(PUSH — valid function start)' if is_push else ''}")

        # Analyze the function
        info = disasm_function_simple(rom, rom_offset, max_bytes=200)
        print(f"    BL targets ({len(info['bls'])}):")
        for bl in info["bls"]:
            # Try to identify known targets
            known_name = ""
            for kn, kv in KNOWN.items():
                if kv == bl["target"]:
                    known_name = f" = {kn}"
                    break
            for kn, kv in config_addrs.items():
                if kv == bl["target"]:
                    known_name = f" = {kn}"
                    break
            print(f"      0x{bl['offset']:06X}: BL 0x{bl['target']:08X}{known_name}")
        print(f"    LDR pool values ({len(info['ldrs'])}):")
        for l in info["ldrs"]:
            known_name = ""
            for kn, kv in KNOWN.items():
                if kv is not None and kv == l["value"]:
                    known_name = f" = {kn}"
                    break
            print(f"      0x{l['offset']:06X}: LDR {l['register']}, =0x{l['value']:08X}{known_name}")
        print()

    # ====================================================================
    # Strategy 7: Hex dump of known ExecCompleted functions
    # ====================================================================
    print("=" * 80)
    print("HEX DUMP: ExecCompleted functions (first 128 bytes)")
    print("=" * 80)
    print()

    for name, addr in [
        ("LinkOpponentBufferExecCompleted", 0x0807E911),
        ("PlayerBufferExecCompleted", 0x0806F0D5),
        ("OpponentBufferExecCompleted", 0x081BB945),
    ]:
        rom_offset = (addr & ~1) - 0x08000000
        print(f"  {name} at 0x{addr:08X} (ROM 0x{rom_offset:06X}):")
        for i in range(0, 128, 16):
            if rom_offset + i + 16 > len(rom):
                break
            hex_str = " ".join(f"{rom[rom_offset+i+j]:02X}" for j in range(16))
            print(f"    +0x{i:03X}: {hex_str}")
        print()

    # ====================================================================
    # Strategy 8: Find the BEQ instruction in each ExecCompleted
    # that checks BATTLE_TYPE_LINK — this is what gets patched
    # ====================================================================
    print("=" * 80)
    print("PATCH POINT ANALYSIS: Finding BEQ (LINK check) in ExecCompleted functions")
    print("=" * 80)
    print()

    for name, addr in [
        ("LinkOpponentBufferExecCompleted", 0x0807E911),
        ("PlayerBufferExecCompleted", 0x0806F0D5),
    ]:
        rom_offset = (addr & ~1) - 0x08000000
        print(f"  {name} at 0x{addr:08X}:")

        # Scan for BEQ instructions in the first 64 bytes
        for i in range(0, 64, 2):
            hw = struct.unpack_from("<H", rom, rom_offset + i)[0]
            # BEQ: 1101 0000 xxxx xxxx (0xD0xx)
            if (hw & 0xFF00) == 0xD000:
                branch_offset = hw & 0xFF
                if branch_offset >= 0x80:
                    branch_offset -= 0x100
                target = rom_offset + i + 4 + branch_offset * 2
                print(f"    +0x{i:03X} (ROM 0x{rom_offset+i:06X}): BEQ +{branch_offset} (-> ROM 0x{target:06X})")
                print(f"    Instruction: 0x{hw:04X}")
                print(f"    Patch to B (unconditional): 0x{0xE000 | (hw & 0xFF):04X}")
            # BNE: 1101 0001 xxxx xxxx (0xD1xx)
            if (hw & 0xFF00) == 0xD100:
                branch_offset = hw & 0xFF
                if branch_offset >= 0x80:
                    branch_offset -= 0x100
                target = rom_offset + i + 4 + branch_offset * 2
                print(f"    +0x{i:03X} (ROM 0x{rom_offset+i:06X}): BNE +{branch_offset} (-> ROM 0x{target:06X})")
            # TST: 0100 0010 0000 1xxx (TST Rn, Rm)
            if (hw & 0xFFC0) == 0x4200:
                rn = hw & 0x07
                rm = (hw >> 3) & 0x07
                print(f"    +0x{i:03X}: TST R{rn}, R{rm}")
        print()

if __name__ == "__main__":
    main()
