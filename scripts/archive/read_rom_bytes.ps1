$rom = [System.IO.File]::ReadAllBytes('C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba')
$baseOffset = 0x071B64
$baseAddr = 0x08071B64

Write-Host "=== ROM bytes at 0x071B64 (512 bytes) ==="
for ($i = 0; $i -lt 512; $i += 16) {
    $addr = $baseAddr + $i
    $hex = ""
    for ($j = 0; $j -lt 16; $j++) {
        $hex += "{0:X2} " -f $rom[$baseOffset + $i + $j]
    }
    Write-Host ("  0x{0:X8}: {1}" -f $addr, $hex)
}

Write-Host ""
Write-Host "=== THUMB disassembly ==="
for ($i = 0; $i -lt 256; $i += 2) {
    $addr = $baseAddr + $i
    $hw = [BitConverter]::ToUInt16($rom, $baseOffset + $i)
    $desc = ""

    $top5 = ($hw -shr 11) -band 0x1F
    $top3 = ($hw -shr 13) -band 0x07
    $top8 = ($hw -shr 8) -band 0xFF

    # PUSH/POP
    if (($hw -band 0xFE00) -eq 0xB400) {
        $regs = $hw -band 0xFF
        $lr = if (($hw -band 0x100) -ne 0) { ",LR" } else { "" }
        $desc = "  ; PUSH {mask=0x$("{0:X2}" -f $regs)$lr}"
    }
    elseif (($hw -band 0xFE00) -eq 0xBC00) {
        $regs = $hw -band 0xFF
        $pc = if (($hw -band 0x100) -ne 0) { ",PC" } else { "" }
        $desc = "  ; POP {mask=0x$("{0:X2}" -f $regs)$pc}"
    }
    # LDR Rd, [PC, #imm]
    elseif ($top5 -eq 9) {
        $rd = ($hw -shr 8) -band 7
        $imm = ($hw -band 0xFF) * 4
        $pc_val = ($addr + 4) -band ([uint32]::MaxValue - 3)
        $target = $pc_val + $imm
        $rom_off = $target - 0x08000000
        if ($rom_off -ge 0 -and $rom_off -lt ($rom.Length - 3)) {
            $lit = [BitConverter]::ToUInt32($rom, $rom_off)
            $desc = "  ; LDR r$rd, [PC, #$imm] -> lit=0x$("{0:X8}" -f $lit)"
        } else {
            $desc = "  ; LDR r$rd, [PC, #$imm] -> addr=0x$("{0:X8}" -f $target)"
        }
    }
    # MOV Rd, #imm
    elseif ($top5 -eq 4) {
        $rd = ($hw -shr 8) -band 7
        $imm = $hw -band 0xFF
        $desc = "  ; MOV r$rd, #$imm"
    }
    # CMP Rd, #imm
    elseif ($top5 -eq 5) {
        $rd = ($hw -shr 8) -band 7
        $imm = $hw -band 0xFF
        $desc = "  ; CMP r$rd, #$imm"
    }
    # ADD Rd, #imm
    elseif ($top5 -eq 6) {
        $rd = ($hw -shr 8) -band 7
        $imm = $hw -band 0xFF
        $desc = "  ; ADD r$rd, #$imm"
    }
    # SUB Rd, #imm
    elseif ($top5 -eq 7) {
        $rd = ($hw -shr 8) -band 7
        $imm = $hw -band 0xFF
        $desc = "  ; SUB r$rd, #$imm"
    }
    # B unconditional
    elseif ($top5 -eq 0x1C) {
        $off = $hw -band 0x7FF
        if ($off -band 0x400) { $off = $off - 2048 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; B 0x$("{0:X8}" -f $target)"
    }
    # BEQ
    elseif ($top8 -eq 0xD0) {
        $off = $hw -band 0xFF
        if ($off -band 0x80) { $off = $off - 256 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; BEQ 0x$("{0:X8}" -f $target)"
    }
    # BNE
    elseif ($top8 -eq 0xD1) {
        $off = $hw -band 0xFF
        if ($off -band 0x80) { $off = $off - 256 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; BNE 0x$("{0:X8}" -f $target)"
    }
    # BCS
    elseif ($top8 -eq 0xD2) {
        $off = $hw -band 0xFF
        if ($off -band 0x80) { $off = $off - 256 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; BCS 0x$("{0:X8}" -f $target)"
    }
    # BCC
    elseif ($top8 -eq 0xD3) {
        $off = $hw -band 0xFF
        if ($off -band 0x80) { $off = $off - 256 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; BCC 0x$("{0:X8}" -f $target)"
    }
    # BGE
    elseif ($top8 -eq 0xDA) {
        $off = $hw -band 0xFF
        if ($off -band 0x80) { $off = $off - 256 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; BGE 0x$("{0:X8}" -f $target)"
    }
    # BLT
    elseif ($top8 -eq 0xDB) {
        $off = $hw -band 0xFF
        if ($off -band 0x80) { $off = $off - 256 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; BLT 0x$("{0:X8}" -f $target)"
    }
    # BGT
    elseif ($top8 -eq 0xDC) {
        $off = $hw -band 0xFF
        if ($off -band 0x80) { $off = $off - 256 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; BGT 0x$("{0:X8}" -f $target)"
    }
    # BLE
    elseif ($top8 -eq 0xDD) {
        $off = $hw -band 0xFF
        if ($off -band 0x80) { $off = $off - 256 }
        $target = $addr + 4 + $off * 2
        $desc = "  ; BLE 0x$("{0:X8}" -f $target)"
    }
    # BX Rm
    elseif (($hw -band 0xFF87) -eq 0x4700) {
        $rm = ($hw -shr 3) -band 0xF
        $desc = "  ; BX r$rm"
    }
    # BL upper
    elseif ($top3 -eq 0x1D -and (($hw -shr 11) -band 3) -eq 2) {
        # Read next halfword for full BL
        if (($baseOffset + $i + 2) -lt $rom.Length) {
            $hw2 = [BitConverter]::ToUInt16($rom, $baseOffset + $i + 2)
            if (($hw2 -shr 11) -eq 0x1F) {
                $offset_hi = $hw -band 0x7FF
                $offset_lo = $hw2 -band 0x7FF
                $full_offset = ($offset_hi -shl 12) + ($offset_lo -shl 1)
                if ($full_offset -band 0x400000) { $full_offset = $full_offset - 0x800000 }
                $target = $addr + 4 + $full_offset
                $desc = "  ; BL 0x$("{0:X8}" -f $target)"
            }
        }
    }
    # BL lower (skip, handled above)
    elseif (($hw -shr 11) -eq 0x1F) {
        $desc = "  ; (BL lower half)"
    }
    # LDR Rd, [Rb, #imm]
    elseif ($top5 -eq 0xD) {
        $imm = (($hw -shr 6) -band 0x1F) * 4
        $rb = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; LDR r$rd, [r$rb, #$imm]"
    }
    # LDRH Rd, [Rb, #imm]
    elseif ($top5 -eq 0x11) {
        $imm = (($hw -shr 6) -band 0x1F) * 2
        $rb = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; LDRH r$rd, [r$rb, #$imm]"
    }
    # LDRB Rd, [Rb, #imm]
    elseif ($top5 -eq 0xF) {
        $imm = ($hw -shr 6) -band 0x1F
        $rb = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; LDRB r$rd, [r$rb, #$imm]"
    }
    # STR Rd, [Rb, #imm]
    elseif ($top5 -eq 0xC) {
        $imm = (($hw -shr 6) -band 0x1F) * 4
        $rb = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; STR r$rd, [r$rb, #$imm]"
    }
    # STRB Rd, [Rb, #imm]
    elseif ($top5 -eq 0xE) {
        $imm = ($hw -shr 6) -band 0x1F
        $rb = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; STRB r$rd, [r$rb, #$imm]"
    }
    # STRH Rd, [Rb, #imm]
    elseif ($top5 -eq 0x10) {
        $imm = (($hw -shr 6) -band 0x1F) * 2
        $rb = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; STRH r$rd, [r$rb, #$imm]"
    }
    # LSL
    elseif ($top5 -eq 0) {
        $imm = ($hw -shr 6) -band 0x1F
        $rs = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; LSL r$rd, r$rs, #$imm"
    }
    # LSR
    elseif ($top5 -eq 1) {
        $imm = ($hw -shr 6) -band 0x1F
        $rs = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; LSR r$rd, r$rs, #$imm"
    }
    # ADD reg,reg,reg / ADD reg,reg,#imm3
    elseif (($hw -shr 9) -eq 0x0E) {
        $desc = "  ; ADD (3-reg or imm3)"
    }
    # SUB reg,reg,reg / SUB reg,reg,#imm3
    elseif (($hw -shr 9) -eq 0x0F) {
        $desc = "  ; SUB (3-reg or imm3)"
    }
    # ALU operations (format 4)
    elseif (($hw -band 0xFC00) -eq 0x4000) {
        $op = ($hw -shr 6) -band 0xF
        $ops = @("AND","EOR","LSL","LSR","ASR","ADC","SBC","ROR","TST","NEG","CMP","CMN","ORR","MUL","BIC","MVN")
        $rs = ($hw -shr 3) -band 7
        $rd = $hw -band 7
        $desc = "  ; $($ops[$op]) r$rd, r$rs"
    }
    # Hi register operations (format 5)
    elseif (($hw -band 0xFC00) -eq 0x4400) {
        $op = ($hw -shr 8) -band 3
        $h1 = ($hw -shr 7) -band 1
        $h2 = ($hw -shr 6) -band 1
        $rs = (($hw -shr 3) -band 7) + ($h2 * 8)
        $rd = ($hw -band 7) + ($h1 * 8)
        $ops = @("ADD","CMP","MOV","BX")
        if ($op -eq 3) {
            $desc = "  ; BX r$rs"
        } else {
            $desc = "  ; $($ops[$op]) r$rd, r$rs (hi)"
        }
    }
    # ADD Rd, SP, #imm
    elseif ($top8 -eq 0xAA -or $top8 -eq 0xAB) {
        $rd = ($hw -shr 8) -band 7
        $imm = ($hw -band 0xFF) * 4
        $desc = "  ; ADD r$rd, SP, #$imm"
    }
    # ADD SP, #imm / SUB SP, #imm
    elseif (($hw -band 0xFF00) -eq 0xB000) {
        $imm = ($hw -band 0x7F) * 4
        if ($hw -band 0x80) {
            $desc = "  ; SUB SP, #$imm"
        } else {
            $desc = "  ; ADD SP, #$imm"
        }
    }
    # STR/LDR SP-relative
    elseif ($top5 -eq 0x12) {
        $rd = ($hw -shr 8) -band 7
        $imm = ($hw -band 0xFF) * 4
        $desc = "  ; STR r$rd, [SP, #$imm]"
    }
    elseif ($top5 -eq 0x13) {
        $rd = ($hw -shr 8) -band 7
        $imm = ($hw -band 0xFF) * 4
        $desc = "  ; LDR r$rd, [SP, #$imm]"
    }

    Write-Host ("  0x{0:X8}: {1:X4}{2}" -f $addr, $hw, $desc)
}
