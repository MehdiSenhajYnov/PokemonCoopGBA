#!/usr/bin/env python3
"""
Find IsCryPlayingOrClearCrySongs() in Run & Bun ROM - v2 (relaxed constraints).

Pattern: small function with 2 BLs that returns 0 or 1.
Relaxed: no requirement for IWRAM ref or CMP R0,#0 (compiler may optimize differently).

Also try: search from known callers. We know Intro_TryShinyAnimShowHealthbox calls it.
That function is a controller callback set by Task_StartSendOutAnim.
"""

import struct

ROM_PATH = "rom/Pokemon RunBun.gba"

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_bl(rom, offset):
    """Decode THUMB BL at offset. Returns target address or None."""
    if offset + 4 > len(rom):
        return None
    h1 = struct.unpack_from("<H", rom, offset)[0]
    h2 = struct.unpack_from("<H", rom, offset + 2)[0]
    if (h1 & 0xF800) != 0xF000:
        return None
    if (h2 & 0xF800) != 0xF800:
        return None
    imm11 = h2 & 0x7FF
    imm10 = h1 & 0x7FF
    if imm10 & 0x400:
        imm10 |= 0xFFFFF800
    target_offset = (imm10 << 12) | (imm11 << 1)
    pc = 0x08000000 + offset + 4
    target = pc + target_offset
    return target & 0xFFFFFFFF

def scan_small_bool_functions(rom):
    """Find all small functions with 2 BLs that return 0/1."""
    results = []

    for off in range(0, min(len(rom) - 40, 0x01000000), 2):
        hw = struct.unpack_from("<H", rom, off)[0]
        # PUSH with LR bit set (0xB5xx)
        if (hw & 0xFF00) != 0xB500:
            continue

        bl_targets = []
        has_mov_r0_0 = False
        has_mov_r0_1 = False
        func_size = 0
        pool_refs = []
        has_bne = False
        has_beq = False

        for i in range(2, 50, 2):
            if off + i + 2 > len(rom):
                break
            instr = struct.unpack_from("<H", rom, off + i)[0]

            # POP with PC
            if (instr & 0xFF00) == 0xBD00:
                # Check if there's another POP+PC shortly after (two return paths)
                func_size = i + 2
                # Look for second return up to 8 bytes after
                for j in range(i + 2, min(i + 10, 50), 2):
                    if off + j + 2 > len(rom):
                        break
                    instr2 = struct.unpack_from("<H", rom, off + j)[0]
                    if (instr2 & 0xFF00) == 0xBD00:
                        func_size = j + 2
                        break
                    # Also check for literal pool (stop scanning)
                    if off + j + 4 <= len(rom):
                        word = struct.unpack_from("<I", rom, off + j)[0]
                        if 0x02000000 <= word < 0x04000000 or 0x08000000 <= word < 0x0A000000:
                            break
                break

            # BL
            if (instr & 0xF800) == 0xF000 and off + i + 4 <= len(rom):
                next_hw = struct.unpack_from("<H", rom, off + i + 2)[0]
                if (next_hw & 0xF800) == 0xF800:
                    target = decode_bl(rom, off + i)
                    if target:
                        bl_targets.append((i, target))

            if instr == 0x2000: has_mov_r0_0 = True
            if instr == 0x2001: has_mov_r0_1 = True
            if (instr & 0xFF00) == 0xD100: has_bne = True  # BNE
            if (instr & 0xFF00) == 0xD000: has_beq = True  # BEQ

            # LDR from pool
            if (instr & 0xF800) == 0x4800:
                rd = (instr >> 8) & 0x07
                imm8 = instr & 0xFF
                pool_off = ((off + i + 4) & ~3) + imm8 * 4
                if pool_off + 4 <= len(rom):
                    val = struct.unpack_from("<I", rom, pool_off)[0]
                    pool_refs.append((rd, val, i))

        if func_size == 0:
            continue
        if len(bl_targets) != 2:
            continue
        if not (has_mov_r0_0 and has_mov_r0_1):
            continue

        # Score the candidate
        score = 0
        if func_size <= 30: score += 30
        elif func_size <= 40: score += 15
        if has_bne or has_beq: score += 10

        # Check if any pool ref is IWRAM
        has_iwram = any(0x03000000 <= v < 0x03008000 for _, v, _ in pool_refs)
        if has_iwram: score += 50

        # Check if any pool ref is EWRAM
        has_ewram = any(0x02000000 <= v < 0x02040000 for _, v, _ in pool_refs)
        if has_ewram: score += 10

        # Check the two BL targets — if they're close to each other, more likely helpers
        if len(bl_targets) == 2:
            bl1_target = bl_targets[0][1]
            bl2_target = bl_targets[1][1]
            dist = abs(bl1_target - bl2_target)
            if dist < 0x200: score += 20  # Close together = same module

        addr = 0x08000000 + off
        results.append({
            "addr": addr,
            "thumb": addr | 1,
            "offset": off,
            "size": func_size,
            "bl_targets": bl_targets,
            "pool_refs": pool_refs,
            "has_iwram": has_iwram,
            "score": score,
        })

    return results

def main():
    print("=== IsCryPlayingOrClearCrySongs Scanner v2 ===")
    rom = read_rom()
    print(f"ROM size: {len(rom)} bytes")

    results = scan_small_bool_functions(rom)
    print(f"\nFound {len(results)} small bool functions with 2 BLs")

    # Sort by score
    results.sort(key=lambda r: r["score"], reverse=True)

    # Show top candidates
    print("\n=== Top candidates (with IWRAM ref + small + returns 0/1) ===\n")
    shown = 0
    for r in results:
        if r["has_iwram"]:
            shown += 1
            if shown > 15: break
            addr = r["addr"]
            print(f"0x{addr:08X} (size={r['size']}, score={r['score']})")
            for bl_off, bl_target in r["bl_targets"]:
                print(f"  BL +{bl_off}: -> 0x{bl_target:08X}")
            for rd, val, instr_off in r["pool_refs"]:
                print(f"  LDR R{rd}, =0x{val:08X} at +{instr_off}")
            # Show bytes
            raw = rom[r["offset"]:r["offset"]+r["size"]]
            print(f"  Bytes: {' '.join(f'{b:02X}' for b in raw)}")

            # Count callers
            callers = 0
            for off2 in range(0, min(len(rom), 0x01000000), 2):
                t = decode_bl(rom, off2)
                if t and t == addr:
                    callers += 1
            print(f"  Callers: {callers}")
            print()

    # If no IWRAM candidates, show top non-IWRAM
    if shown == 0:
        print("No IWRAM candidates. Top overall:")
        for r in results[:10]:
            addr = r["addr"]
            print(f"0x{addr:08X} (size={r['size']}, score={r['score']})")
            for bl_off, bl_target in r["bl_targets"]:
                print(f"  BL +{bl_off}: -> 0x{bl_target:08X}")
            for rd, val, instr_off in r["pool_refs"]:
                print(f"  LDR R{rd}, =0x{val:08X} at +{instr_off}")
            raw = rom[r["offset"]:r["offset"]+r["size"]]
            print(f"  Bytes: {' '.join(f'{b:02X}' for b in raw)}")
            print()

if __name__ == "__main__":
    main()
