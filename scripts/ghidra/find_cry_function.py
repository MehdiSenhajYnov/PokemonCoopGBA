#!/usr/bin/env python3
"""
Find IsCryPlayingOrClearCrySongs() in Run & Bun ROM.

The function pattern (from pokeemerald-expansion/src/sound.c):
    bool8 IsCryPlayingOrClearCrySongs(void) {
        if (IsPokemonCryPlaying(gMPlay_PokemonCry))
            return TRUE;
        else {
            ClearPokemonCrySongs();
            return FALSE;
        }
    }

Assembly pattern (THUMB):
    PUSH {LR}          or PUSH {R4,LR}
    LDR R0, =gMPlay_PokemonCry    ; IWRAM/EWRAM pointer
    BL IsPokemonCryPlaying
    CMP R0, #0          or CBNZ R0, ...
    BNE .return_true
    BL ClearPokemonCrySongs
    MOV R0, #0
    POP {PC}            or BX LR
  .return_true:
    MOV R0, #1
    POP {PC}

Strategy:
1. Find callers of this function from Intro_TryShinyAnimShowHealthbox
2. Or find the function by its internal BL pattern (2 BLs, returns 0 or 1)
3. Or find gMPlay_PokemonCry references

Alternative: Find it by searching from known battle controller code.
Intro_TryShinyAnimShowHealthbox calls IsCryPlayingOrClearCrySongs.
We know Intro_TryShinyAnimShowHealthbox is one of the controller callbacks set by
Task_StartSendOutAnim, which is called from BtlController_HandleIntroTrainerBallThrow.

Let's use a simpler approach: scan for small functions (< 30 bytes) that:
- Have exactly 2 BL instructions
- Return 0 or 1 (MOV R0,#0 / MOV R0,#1)
- One of the BL targets loads an IWRAM pointer argument (gMPlay_PokemonCry is in IWRAM)
"""

import struct
import sys

ROM_PATH = "rom/Pokemon RunBun.gba"

def read_rom():
    with open(ROM_PATH, "rb") as f:
        return f.read()

def decode_bl(rom, offset):
    """Decode a THUMB BL instruction pair at offset. Returns target address or None."""
    if offset + 4 > len(rom):
        return None
    h1 = struct.unpack_from("<H", rom, offset)[0]
    h2 = struct.unpack_from("<H", rom, offset + 2)[0]
    if (h1 & 0xF800) != 0xF000:
        return None
    if (h2 & 0xF800) != 0xF800:
        return None
    # Decode offset
    imm11 = h2 & 0x7FF
    imm10 = h1 & 0x7FF
    # Sign extend imm10
    if imm10 & 0x400:
        imm10 |= 0xFFFFF800
    target_offset = (imm10 << 12) | (imm11 << 1)
    pc = 0x08000000 + offset + 4  # PC is instruction + 4
    target = pc + target_offset
    return target & 0xFFFFFFFF

def find_cry_function(rom):
    """
    Scan for IsCryPlayingOrClearCrySongs pattern:
    Small function with PUSH, 2 BLs, returns 0/1, accesses IWRAM pointer.
    """
    candidates = []

    # Scan entire ROM for function prologues
    for off in range(0, min(len(rom) - 30, 0x01000000), 2):
        hw = struct.unpack_from("<H", rom, off)[0]

        # Look for PUSH {LR} (0xB500) or PUSH {R4,LR} (0xB510) or PUSH {R3,LR} (0xB508)
        if (hw & 0xFF00) != 0xB500:
            continue

        # Check function is small (< 40 bytes)
        # Look for return within 40 bytes
        func_size = 0
        has_return = False
        bl_targets = []
        has_mov_r0_0 = False
        has_mov_r0_1 = False
        has_cmp_r0_0 = False
        ldr_pool_refs = []

        for i in range(2, 40, 2):
            if off + i + 2 > len(rom):
                break
            instr = struct.unpack_from("<H", rom, off + i)[0]

            # POP {PC} or POP {Rx,PC}
            if (instr & 0xFF00) == 0xBD00:
                func_size = i + 2
                has_return = True
                break

            # BL instruction (first half)
            if (instr & 0xF800) == 0xF000 and off + i + 4 <= len(rom):
                next_instr = struct.unpack_from("<H", rom, off + i + 2)[0]
                if (next_instr & 0xF800) == 0xF800:
                    target = decode_bl(rom, off + i)
                    if target:
                        bl_targets.append(target)

            # MOV R0, #0 (0x2000)
            if instr == 0x2000:
                has_mov_r0_0 = True

            # MOV R0, #1 (0x2001)
            if instr == 0x2001:
                has_mov_r0_1 = True

            # CMP R0, #0 (0x2800)
            if instr == 0x2800:
                has_cmp_r0_0 = True

            # LDR Rd, [PC, #imm] — literal pool load
            if (instr & 0xF800) == 0x4800:
                rd = (instr >> 8) & 0x07
                imm8 = instr & 0xFF
                pool_offset = ((off + i + 4) & ~3) + imm8 * 4
                if pool_offset + 4 <= len(rom):
                    pool_val = struct.unpack_from("<I", rom, pool_offset)[0]
                    ldr_pool_refs.append((rd, pool_val))

        if not has_return:
            continue

        # Filter: must have exactly 2 BLs and return 0/1
        if len(bl_targets) != 2:
            continue
        if not (has_mov_r0_0 and has_mov_r0_1):
            continue
        if not has_cmp_r0_0:
            continue

        # Check if any literal pool ref is IWRAM (0x03xxxxxx) - gMPlay_PokemonCry
        has_iwram_ref = False
        iwram_ref = None
        for rd, val in ldr_pool_refs:
            if 0x03000000 <= val < 0x03008000:
                has_iwram_ref = True
                iwram_ref = val
                break

        if not has_iwram_ref:
            continue

        score = 100
        # Bonus for small size
        if func_size <= 24:
            score += 20

        addr = 0x08000000 + off
        candidates.append({
            "addr": addr,
            "thumb": addr | 1,
            "offset": off,
            "size": func_size,
            "bl_targets": bl_targets,
            "iwram_ref": iwram_ref,
            "pool_refs": ldr_pool_refs,
            "score": score,
        })

    return candidates

def main():
    print("=== IsCryPlayingOrClearCrySongs ROM Scanner ===")
    rom = read_rom()
    print(f"ROM size: {len(rom)} bytes ({len(rom)/1024/1024:.1f} MB)")

    candidates = find_cry_function(rom)

    # Sort by score
    candidates.sort(key=lambda c: c["score"], reverse=True)

    print(f"\nFound {len(candidates)} candidates")
    print()

    for i, c in enumerate(candidates[:20]):
        print(f"#{i+1}: 0x{c['addr']:08X} (THUMB 0x{c['thumb']:08X})")
        print(f"    ROM offset: 0x{c['offset']:06X}, size: {c['size']} bytes")
        print(f"    IWRAM ref: 0x{c['iwram_ref']:08X}")
        print(f"    BL targets: {', '.join(f'0x{t:08X}' for t in c['bl_targets'])}")
        print(f"    Pool refs: {', '.join(f'R{r}=0x{v:08X}' for r,v in c['pool_refs'])}")
        print(f"    Score: {c['score']}")

        # Disassemble for verification
        raw = rom[c['offset']:c['offset']+c['size']]
        hex_bytes = ' '.join(f'{b:02X}' for b in raw)
        print(f"    Bytes: {hex_bytes}")
        print()

    # Also search for the BL callers of the top candidates
    if candidates:
        top = candidates[0]
        print(f"\n=== Searching for callers of top candidate 0x{top['thumb']:08X} ===")
        callers = []
        for off in range(0, min(len(rom) - 4, 0x01000000), 2):
            target = decode_bl(rom, off)
            if target and (target == top['addr'] or target == top['thumb']):
                caller_addr = 0x08000000 + off
                callers.append(caller_addr)
        print(f"Found {len(callers)} callers:")
        for c in callers[:30]:
            print(f"  0x{c:08X}")

if __name__ == "__main__":
    main()
