$rom = [System.IO.File]::ReadAllBytes('C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba')

function Decode-BL {
    param([byte[]]$ROM, [int]$RomOffset)
    $hw1 = [BitConverter]::ToUInt16($ROM, $RomOffset)
    $hw2 = [BitConverter]::ToUInt16($ROM, $RomOffset + 2)
    $offset_hi = $hw1 -band 0x7FF
    $offset_lo = $hw2 -band 0x7FF
    $full_offset = ($offset_hi -shl 12) + ($offset_lo -shl 1)
    if ($full_offset -band 0x400000) { $full_offset = $full_offset - 0x800000 }
    $romAddr = 0x08000000 + $RomOffset
    $target = $romAddr + 4 + $full_offset
    return $target
}

# ============================================================
# 1. What is 0x08004810? (BL #1 from 0x08071B64)
# ============================================================
Write-Host "=== What is 0x08004810? (called from 0x08071B64 with r0=0) ==="
Write-Host "Reading bytes at 0x004810..."
for ($i = 0; $i -lt 64; $i += 2) {
    $addr = 0x08004810 + $i
    $hw = [BitConverter]::ToUInt16($rom, 0x004810 + $i)
    $desc = ""
    $top5 = ($hw -shr 11) -band 0x1F
    if ($top5 -eq 9) {
        $rd = ($hw -shr 8) -band 7
        $imm = ($hw -band 0xFF) * 4
        $pc_val = ($addr + 4) -band ([uint32]::MaxValue - 3)
        $litAddr = $pc_val + $imm
        $litOff = $litAddr - 0x08000000
        if ($litOff -ge 0 -and $litOff -lt ($rom.Length - 3)) {
            $lit = [BitConverter]::ToUInt32($rom, $litOff)
            $desc = "  ; LDR r$rd, =0x$("{0:X8}" -f $lit)"
        }
    }
    elseif (($hw -band 0xFE00) -eq 0xB400) { $desc = "  ; PUSH" }
    elseif (($hw -band 0xFE00) -eq 0xBC00) { $desc = "  ; POP" }
    elseif ($top5 -eq 4) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; MOV r$rd, #$imm" }
    elseif ($top5 -eq 5) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; CMP r$rd, #$imm" }
    Write-Host ("  0x{0:X8}: {1:X4}{2}" -f $addr, $hw, $desc)
}

# ============================================================
# 2. What is 0x0806F0D4? (BL #2 from 0x08071B64 - likely PlayerBufferExecCompleted or BtlController_Complete)
# ============================================================
Write-Host ""
Write-Host "=== What is 0x0806F0D4? ==="
Write-Host "Reading bytes at 0x06F0D4..."
for ($i = 0; $i -lt 64; $i += 2) {
    $addr = 0x0806F0D4 + $i
    $hw = [BitConverter]::ToUInt16($rom, 0x06F0D4 + $i)
    $desc = ""
    $top5 = ($hw -shr 11) -band 0x1F
    if ($top5 -eq 9) {
        $rd = ($hw -shr 8) -band 7
        $imm = ($hw -band 0xFF) * 4
        $pc_val = ($addr + 4) -band ([uint32]::MaxValue - 3)
        $litAddr = $pc_val + $imm
        $litOff = $litAddr - 0x08000000
        if ($litOff -ge 0 -and $litOff -lt ($rom.Length - 3)) {
            $lit = [BitConverter]::ToUInt32($rom, $litOff)
            $desc = "  ; LDR r$rd, =0x$("{0:X8}" -f $lit)"
        }
    }
    elseif (($hw -band 0xFE00) -eq 0xB400) { $desc = "  ; PUSH" }
    elseif (($hw -band 0xFE00) -eq 0xBC00) { $desc = "  ; POP" }
    elseif ($top5 -eq 4) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; MOV r$rd, #$imm" }
    Write-Host ("  0x{0:X8}: {1:X4}{2}" -f $addr, $hw, $desc)
}

# ============================================================
# 3. Wider function pointer table search
# ============================================================
Write-Host ""
Write-Host "=== Searching for sPlayerBufferCommands table ==="
Write-Host "Looking for a table containing known Player handler addresses..."
Write-Host "Known addresses: SetControllerToPlayer=0x0806F0A5, PlayerBufferRunCommand=0x0806F151"

# The sPlayerBufferCommands table contains addresses like:
# BtlController_HandleGetMonData, PlayerHandleLoadMonSprite, etc.
# These are in the 0x0806xxxx - 0x0807xxxx range typically
# Let's look for a contiguous block of ~50 function pointers

$bestStart = 0
$bestLen = 0

for ($start = 0x06E000; $start -lt 0x075000; $start += 4) {
    $consecutive = 0
    for ($j = 0; $j -lt 200; $j++) {
        $off = $start + $j * 4
        if ($off + 3 -ge $rom.Length) { break }
        $val = [BitConverter]::ToUInt32($rom, $off)
        # Check if it's a plausible THUMB function pointer in the battle controller range
        if (($val -band 0xFF000001) -eq 0x08000001) {
            $funcOff = $val -band 0x00FFFFFE
            if ($funcOff -ge 0x060000 -and $funcOff -lt 0x200000) {
                $consecutive++
            } else {
                break
            }
        } else {
            break
        }
    }
    if ($consecutive -gt $bestLen) {
        $bestLen = $consecutive
        $bestStart = $start
    }
}

Write-Host ("Best function pointer table: 0x{0:X8}, {1} entries" -f (0x08000000 + $bestStart), $bestLen)
if ($bestLen -ge 30) {
    Write-Host "Table entries:"
    for ($j = 0; $j -lt $bestLen; $j++) {
        $off = $bestStart + $j * 4
        $val = [BitConverter]::ToUInt32($rom, $off)
        $marker = ""
        if ($val -eq 0x08071B65) { $marker = " <-- 0x08071B65 TARGET" }
        if ($val -eq 0x0806F0A5) { $marker = " <-- SetControllerToPlayer?" }
        if ($val -eq 0x0806F151) { $marker = " <-- PlayerBufferRunCommand?" }
        if ($val -eq 0x0806F0D5) { $marker = " <-- PlayerBufferExecCompleted?" }
        Write-Host ("  [{0,2}] 0x{1:X8}{2}" -f $j, $val, $marker)
    }
}

# ============================================================
# 4. Context around where 0x08071B65 is referenced (0x08074698)
# ============================================================
Write-Host ""
Write-Host "=== Context around 0x08074698 where 0x08071B65 is referenced ==="
Write-Host "This is in the literal pool of a function. Let's look at the function above it."
Write-Host "Reading backwards from 0x08074698 to find the function start..."

# Scan backwards for a PUSH instruction
for ($i = 0x074698; $i -gt 0x074600; $i -= 2) {
    $hw = [BitConverter]::ToUInt16($rom, $i)
    if (($hw -band 0xFF00) -eq 0xB500) {
        $addr = 0x08000000 + $i
        Write-Host ("  Found PUSH {LR} at 0x{0:X8}" -f $addr)

        # Disassemble from here
        Write-Host "  Disassembly:"
        for ($j = 0; $j -lt 180; $j += 2) {
            $a = $i + $j
            if ($a -gt 0x0746B0) { break }
            $addr2 = 0x08000000 + $a
            $hw2 = [BitConverter]::ToUInt16($rom, $a)
            $desc = ""
            $top5 = ($hw2 -shr 11) -band 0x1F
            $top8 = ($hw2 -shr 8) -band 0xFF

            if ($top5 -eq 9) {
                $rd = ($hw2 -shr 8) -band 7
                $imm = ($hw2 -band 0xFF) * 4
                $pc_val = ($addr2 + 4) -band ([uint32]::MaxValue - 3)
                $litAddr = $pc_val + $imm
                $litOff = $litAddr - 0x08000000
                if ($litOff -ge 0 -and $litOff -lt ($rom.Length - 3)) {
                    $lit = [BitConverter]::ToUInt32($rom, $litOff)
                    $desc = "  ; LDR r$rd, =0x$("{0:X8}" -f $lit)"
                }
            }
            elseif (($hw2 -band 0xFE00) -eq 0xB400) { $desc = "  ; PUSH" }
            elseif (($hw2 -band 0xFE00) -eq 0xBC00) { $desc = "  ; POP" }
            elseif (($hw2 -band 0xFF87) -eq 0x4700) { $rm = ($hw2 -shr 3) -band 0xF; $desc = "  ; BX r$rm" }
            elseif ($top5 -eq 4) { $rd = ($hw2 -shr 8) -band 7; $imm = $hw2 -band 0xFF; $desc = "  ; MOV r$rd, #$imm" }
            elseif ($top5 -eq 5) { $rd = ($hw2 -shr 8) -band 7; $imm = $hw2 -band 0xFF; $desc = "  ; CMP r$rd, #$imm" }
            elseif ($top8 -eq 0xD0) { $off2 = $hw2 -band 0xFF; if ($off2 -band 0x80) { $off2 -= 256 }; $t = $addr2 + 4 + $off2 * 2; $desc = "  ; BEQ 0x$("{0:X8}" -f $t)" }
            elseif ($top8 -eq 0xD1) { $off2 = $hw2 -band 0xFF; if ($off2 -band 0x80) { $off2 -= 256 }; $t = $addr2 + 4 + $off2 * 2; $desc = "  ; BNE 0x$("{0:X8}" -f $t)" }
            elseif ($top5 -eq 0x1C) { $off2 = $hw2 -band 0x7FF; if ($off2 -band 0x400) { $off2 -= 2048 }; $t = $addr2 + 4 + $off2 * 2; $desc = "  ; B 0x$("{0:X8}" -f $t)" }
            elseif (($hw2 -shr 13) -eq 5 -and (($hw2 -shr 11) -band 3) -eq 2) {
                if (($a + 2) -lt $rom.Length) {
                    $target = Decode-BL -ROM $rom -RomOffset $a
                    $desc = "  ; BL 0x$("{0:X8}" -f $target)"
                }
            }
            elseif (($hw2 -shr 11) -eq 0x1F) { $desc = "  ; (BL lower)" }
            elseif ($top5 -eq 0xD) { $imm = (($hw2 -shr 6) -band 0x1F)*4; $rb = ($hw2 -shr 3) -band 7; $rd = $hw2 -band 7; $desc = "  ; LDR r$rd, [r$rb, #$imm]" }
            elseif ($top5 -eq 0xF) { $imm = ($hw2 -shr 6) -band 0x1F; $rb = ($hw2 -shr 3) -band 7; $rd = $hw2 -band 7; $desc = "  ; LDRB r$rd, [r$rb, #$imm]" }
            elseif ($top5 -eq 0xC) { $imm = (($hw2 -shr 6) -band 0x1F)*4; $rb = ($hw2 -shr 3) -band 7; $rd = $hw2 -band 7; $desc = "  ; STR r$rd, [r$rb, #$imm]" }
            elseif ($top5 -eq 0xE) { $imm = ($hw2 -shr 6) -band 0x1F; $rb = ($hw2 -shr 3) -band 7; $rd = $hw2 -band 7; $desc = "  ; STRB r$rd, [r$rb, #$imm]" }
            elseif ($top5 -eq 0) { $imm = ($hw2 -shr 6) -band 0x1F; $rs = ($hw2 -shr 3) -band 7; $rd = $hw2 -band 7; $desc = "  ; LSL r$rd, r$rs, #$imm" }

            Write-Host ("    0x{0:X8}: {1:X4}{2}" -f $addr2, $hw2, $desc)
        }
        break
    }
}

# ============================================================
# 5. What calls 0x08071B65? What is BtlController_Complete?
# ============================================================
Write-Host ""
Write-Host "=== Analyzing 0x08071B64 more carefully ==="
Write-Host "Function: PUSH {LR}"
Write-Host "  MOV r0, #0"
Write-Host "  BL 0x08004810  -- IsTextPrinterActive(0)?"
Write-Host "  LSL r0, #16  -- result << 16 (zero-extend 16-bit return)"
Write-Host "  CMP r0, #0  -- if result == 0 (printer NOT active)"
Write-Host "  BNE skip  -- skip if still active"
Write-Host "  BL 0x0806F0D4  -- PlayerBufferExecCompleted / BtlController_Complete"
Write-Host "skip: POP {r0}; BX r0"
Write-Host ""
Write-Host "CONCLUSION: This is a 'wait for text printer to finish, then complete' handler."
Write-Host "This matches CompleteOnInactiveTextPrinter_ or similar."

# ============================================================
# 6. Check what 0x08004810 is (IsTextPrinterActive?)
# ============================================================
Write-Host ""
Write-Host "=== Verifying 0x08004810 identity ==="
# Search for known function name patterns
# IsTextPrinterActive takes a single u8 argument (printer ID, usually 0)
# and returns TRUE if still printing

# Let's look at what literal pool values are near 0x08004810
for ($i = 0; $i -lt 128; $i += 2) {
    $addr = 0x08004810 + $i
    $hw = [BitConverter]::ToUInt16($rom, 0x004810 + $i)
    $top5 = ($hw -shr 11) -band 0x1F
    if ($top5 -eq 9) {
        $rd = ($hw -shr 8) -band 7
        $imm = ($hw -band 0xFF) * 4
        $pc_val = ($addr + 4) -band ([uint32]::MaxValue - 3)
        $litAddr = $pc_val + $imm
        $litOff = $litAddr - 0x08000000
        if ($litOff -ge 0 -and $litOff -lt ($rom.Length - 3)) {
            $lit = [BitConverter]::ToUInt32($rom, $litOff)
            Write-Host ("  LDR at 0x{0:X8} loads 0x{1:X8}" -f $addr, $lit)
        }
    }
}
