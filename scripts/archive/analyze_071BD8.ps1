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

Write-Host "=== Full disassembly of 0x08071BD8 (0x08071BD9 THUMB) ==="
Write-Host "This function is written into gBattlerControllerFuncs by 0x08071B7C"
Write-Host ""

$start = 0x071BD8
$end = $start + 128

for ($i = $start; $i -lt $end; $i += 2) {
    $addr = 0x08000000 + $i
    $hw = [BitConverter]::ToUInt16($rom, $i)
    $desc = ""
    $top5 = ($hw -shr 11) -band 0x1F
    $top8 = ($hw -shr 8) -band 0xFF

    if (($hw -band 0xFE00) -eq 0xB400) { $desc = "  ; PUSH" }
    elseif (($hw -band 0xFE00) -eq 0xBC00) { $desc = "  ; POP" }
    elseif (($hw -band 0xFF87) -eq 0x4700) { $rm = ($hw -shr 3) -band 0xF; $desc = "  ; BX r$rm" }
    elseif ($top5 -eq 9) {
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
    elseif ($top5 -eq 4) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; MOV r$rd, #$imm" }
    elseif ($top5 -eq 5) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; CMP r$rd, #$imm" }
    elseif ($top5 -eq 6) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; ADD r$rd, #$imm" }
    elseif ($top5 -eq 7) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; SUB r$rd, #$imm" }
    elseif ($top8 -eq 0xD0) { $off2 = $hw -band 0xFF; if ($off2 -band 0x80) { $off2 -= 256 }; $t = $addr + 4 + $off2 * 2; $desc = "  ; BEQ 0x$("{0:X8}" -f $t)" }
    elseif ($top8 -eq 0xD1) { $off2 = $hw -band 0xFF; if ($off2 -band 0x80) { $off2 -= 256 }; $t = $addr + 4 + $off2 * 2; $desc = "  ; BNE 0x$("{0:X8}" -f $t)" }
    elseif ($top5 -eq 0x1C) { $off2 = $hw -band 0x7FF; if ($off2 -band 0x400) { $off2 -= 2048 }; $t = $addr + 4 + $off2 * 2; $desc = "  ; B 0x$("{0:X8}" -f $t)" }
    elseif (($hw -shr 13) -eq 5 -and (($hw -shr 11) -band 3) -eq 2) {
        $target = Decode-BL -ROM $rom -RomOffset $i
        $desc = "  ; BL 0x$("{0:X8}" -f $target)"
    }
    elseif (($hw -shr 11) -eq 0x1F) { $desc = "  ; (BL lower)" }
    elseif ($top5 -eq 0xD) { $imm = (($hw -shr 6) -band 0x1F)*4; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LDR r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0x11) { $imm = (($hw -shr 6) -band 0x1F)*2; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LDRH r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0xF) { $imm = ($hw -shr 6) -band 0x1F; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LDRB r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0xC) { $imm = (($hw -shr 6) -band 0x1F)*4; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; STR r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0xE) { $imm = ($hw -shr 6) -band 0x1F; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; STRB r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0x10) { $imm = (($hw -shr 6) -band 0x1F)*2; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; STRH r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0) { $imm = ($hw -shr 6) -band 0x1F; $rs = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LSL r$rd, r$rs, #$imm" }
    elseif ($top5 -eq 1) { $imm = ($hw -shr 6) -band 0x1F; $rs = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LSR r$rd, r$rs, #$imm" }
    elseif (($hw -band 0xFC00) -eq 0x4000) {
        $op = ($hw -shr 6) -band 0xF
        $ops = @("AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR","TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN")
        $rs = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; $($ops[$op]) r$rd, r$rs"
    }
    elseif (($hw -band 0xFC00) -eq 0x4400) {
        $op = ($hw -shr 8) -band 3
        $h1 = ($hw -shr 7) -band 1
        $h2 = ($hw -shr 6) -band 1
        $rs = (($hw -shr 3) -band 7) + ($h2 * 8)
        $rd = ($hw -band 7) + ($h1 * 8)
        $ops = @("ADD","CMP","MOV","BX")
        if ($op -eq 3) { $desc = "  ; BX r$rs" }
        else { $desc = "  ; $($ops[$op]) r$rd, r$rs (hi)" }
    }
    elseif (($hw -shr 9) -eq 0x0E) { $desc = "  ; ADD (3-reg or imm3)" }
    elseif (($hw -shr 9) -eq 0x0F) { $desc = "  ; SUB (3-reg or imm3)" }
    elseif ($top5 -eq 0x13) { $rd = ($hw -shr 8) -band 7; $imm = ($hw -band 0xFF) * 4; $desc = "  ; LDR r$rd, [SP, #$imm]" }
    elseif (($hw -band 0xFF00) -eq 0x5E00) { $desc = "  ; LDRSH" }

    Write-Host ("  0x{0:X8}: {1:X4}{2}" -f $addr, $hw, $desc)

    # Stop at return (POP PC or BX)
    if (($hw -band 0xFE00) -eq 0xBC00 -and ($hw -band 0x100)) {
        # POP with PC - this is a return
        # But continue a bit more to see literal pool
    }
}

Write-Host ""
Write-Host "=== Now disassembling 0x08071B7C function ==="

$start2 = 0x071B7C
$end2 = $start2 + 100

for ($i = $start2; $i -lt $end2; $i += 2) {
    $addr = 0x08000000 + $i
    $hw = [BitConverter]::ToUInt16($rom, $i)
    $desc = ""
    $top5 = ($hw -shr 11) -band 0x1F
    $top8 = ($hw -shr 8) -band 0xFF

    if (($hw -band 0xFE00) -eq 0xB400) { $desc = "  ; PUSH" }
    elseif (($hw -band 0xFE00) -eq 0xBC00) { $desc = "  ; POP" }
    elseif (($hw -band 0xFF87) -eq 0x4700) { $rm = ($hw -shr 3) -band 0xF; $desc = "  ; BX r$rm" }
    elseif ($top5 -eq 9) {
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
    elseif ($top5 -eq 4) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; MOV r$rd, #$imm" }
    elseif ($top5 -eq 5) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; CMP r$rd, #$imm" }
    elseif ($top5 -eq 6) { $rd = ($hw -shr 8) -band 7; $imm = $hw -band 0xFF; $desc = "  ; ADD r$rd, #$imm" }
    elseif ($top8 -eq 0xD0) { $off2 = $hw -band 0xFF; if ($off2 -band 0x80) { $off2 -= 256 }; $t = $addr + 4 + $off2 * 2; $desc = "  ; BEQ 0x$("{0:X8}" -f $t)" }
    elseif ($top8 -eq 0xD1) { $off2 = $hw -band 0xFF; if ($off2 -band 0x80) { $off2 -= 256 }; $t = $addr + 4 + $off2 * 2; $desc = "  ; BNE 0x$("{0:X8}" -f $t)" }
    elseif ($top5 -eq 0x1C) { $off2 = $hw -band 0x7FF; if ($off2 -band 0x400) { $off2 -= 2048 }; $t = $addr + 4 + $off2 * 2; $desc = "  ; B 0x$("{0:X8}" -f $t)" }
    elseif (($hw -shr 13) -eq 5 -and (($hw -shr 11) -band 3) -eq 2) {
        $target = Decode-BL -ROM $rom -RomOffset $i
        $desc = "  ; BL 0x$("{0:X8}" -f $target)"
    }
    elseif (($hw -shr 11) -eq 0x1F) { $desc = "  ; (BL lower)" }
    elseif ($top5 -eq 0xD) { $imm = (($hw -shr 6) -band 0x1F)*4; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LDR r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0xF) { $imm = ($hw -shr 6) -band 0x1F; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LDRB r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0xC) { $imm = (($hw -shr 6) -band 0x1F)*4; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; STR r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0xE) { $imm = ($hw -shr 6) -band 0x1F; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; STRB r$rd, [r$rb, #$imm]" }
    elseif ($top5 -eq 0) { $imm = ($hw -shr 6) -band 0x1F; $rs = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LSL r$rd, r$rs, #$imm" }
    elseif (($hw -band 0xFC00) -eq 0x4000) {
        $op = ($hw -shr 6) -band 0xF
        $ops = @("AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR","TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN")
        $rs = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; $($ops[$op]) r$rd, r$rs"
    }
    elseif (($hw -shr 9) -eq 0x0E) { $desc = "  ; ADD (3-reg or imm3)" }
    elseif ($top5 -eq 0x11) { $imm = (($hw -shr 6) -band 0x1F)*2; $rb = ($hw -shr 3) -band 7; $rd = $hw -band 7; $desc = "  ; LDRH r$rd, [r$rb, #$imm]" }

    Write-Host ("  0x{0:X8}: {1:X4}{2}" -f $addr, $hw, $desc)
}

# Also check what BL targets do from 0x08071B7C
Write-Host ""
Write-Host "=== BL targets from 0x08071B7C ==="
Write-Host ("  0x080C6F14 - from BL at 0x08071BAC")
Write-Host ("  0x08003614 - from BL at 0x08071BB0")
Write-Host ("  0x081EB1D4 - from BL at 0x08071BB6")

# Check 0x080C6F14
Write-Host ""
Write-Host "=== First few instructions at 0x080C6F14 ==="
for ($i = 0; $i -lt 32; $i += 2) {
    $addr = 0x080C6F14 + $i
    $hw = [BitConverter]::ToUInt16($rom, 0x0C6F14 + $i)
    $top5 = ($hw -shr 11) -band 0x1F
    $desc = ""
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
    Write-Host ("  0x{0:X8}: {1:X4}{2}" -f $addr, $hw, $desc)
}
