function Decode-Script {
    param([string]$Name, [array]$Words)

    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host "SCRIPT: $Name"
    Write-Host ("=" * 70)
    Write-Host ""

    $opcodeMaps = @{
        0x0F = "loadword"
        0x09 = "callstd"
        0x02 = "end"
        0x6A = "lock"
        0x6C = "release"
        0x16 = "setvar"
        0x21 = "compare"
        0x06 = "goto_if"
        0x25 = "special"
    }

    for ($i = 0; $i -lt $Words.Count; $i++) {
        $word = [uint32]$Words[$i]
        $hexVal = "0x{0:X8}" -f $word

        # Extract bytes (little-endian: LSB first)
        $b0 = ($word -band 0xFF)
        $b1 = (($word -shr 8) -band 0xFF)
        $b2 = (($word -shr 16) -band 0xFF)
        $b3 = (($word -shr 24) -band 0xFF)

        $bytesStr = "{0:X2} {1:X2} {2:X2} {3:X2}" -f $b0, $b1, $b2, $b3

        Write-Host "Word[$i]:"
        Write-Host "  Hex:   $hexVal"
        Write-Host "  Bytes: $bytesStr (LE: b0={0:X2}, b1={1:X2}, b2={2:X2}, b3={3:X2})" -f $b0, $b1, $b2, $b3

        $opcode = $b0
        $opcodeName = if ($opcodeMaps.ContainsKey($opcode)) { $opcodeMaps[$opcode] } else { "???" }
        Write-Host "  First byte (opcode):  0x{0:X2} = $opcodeName" -f $opcode

        # Decode specific opcodes
        if ($opcode -eq 0x0F) {
            Write-Host "    → loadword: reg=0x{0:X2}, addr_lo=0x{1:X2}{2:X2}" -f $b1, $b2, $b3
        } elseif ($opcode -eq 0x09) {
            Write-Host "    → callstd: id=0x{0:X2}" -f $b1
        } elseif ($opcode -eq 0x02) {
            Write-Host "    → end"
        } elseif ($opcode -eq 0x6A) {
            Write-Host "    → lock"
        } elseif ($opcode -eq 0x6C) {
            Write-Host "    → release"
        } elseif ($opcode -eq 0x16) {
            Write-Host "    → setvar: var_lo=0x{0:X2}, var_hi=0x{1:X2}, val_lo=0x{2:X2}" -f $b1, $b2, $b3
        } elseif ($opcode -eq 0x21) {
            Write-Host "    → compare: var_lo=0x{0:X2}, var_hi=0x{1:X2}, val_lo=0x{2:X2}" -f $b1, $b2, $b3
        } elseif ($opcode -eq 0x06) {
            $addrLo = ($b2 -shl 8) -bor $b3
            Write-Host "    → goto_if: cond=0x{0:X2}, addr_lo=0x{1:X4}" -f $b1, $addrLo
        } elseif ($opcode -eq 0x25) {
            Write-Host "    → special: id_lo=0x{0:X2}, id_hi=0x{1:X2}" -f $b1, $b2
        }

        Write-Host ""
    }
}

# Script 1
$script1 = @(983146, 145227920, 18220553, 1811940736, 4294967042)
Decode-Script "Simple script (5 words)" $script1

# Script 2
$script2 = @(983146, 145227920, 220267785, 100663680, 2818579456, 2147554824, 40632322, 25166102, 4278348800)
Decode-Script "Longer script (9 words)" $script2
