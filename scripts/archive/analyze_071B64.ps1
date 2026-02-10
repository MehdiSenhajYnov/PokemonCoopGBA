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

Write-Host "=== Function at 0x08071B64 (THUMB 0x08071B65) ==="
Write-Host "Structure: PUSH {LR}; MOV r0,#0; BL ???; LSL r0,#16; CMP r0,#0; BNE skip; BL ???; POP {r0}; BX r0"
Write-Host ""

$bl1 = Decode-BL -ROM $rom -RomOffset 0x071B68
Write-Host ("  BL #1 at 0x08071B68 -> 0x{0:X8}" -f $bl1)

$bl2 = Decode-BL -ROM $rom -RomOffset 0x071B72
Write-Host ("  BL #2 at 0x08071B72 -> 0x{0:X8}" -f $bl2)

Write-Host ""
Write-Host "=== Function at 0x08071B7C ==="
Write-Host "Literal pool:"
Write-Host "  0x02037594 - gBattleSpritesDataPtr"
Write-Host "  0x03005D70 - gBattlerControllerFuncs"
Write-Host "  0x020233DC - gActiveBattler"
Write-Host "  0x08071BD9 - next function ptr (written to gBattlerControllerFuncs)"
Write-Host "  0x03005E10 - ?"
Write-Host "  0x03005D8C - gBattlerSpriteIds?"

$bl3 = Decode-BL -ROM $rom -RomOffset 0x071BAC
$bl4 = Decode-BL -ROM $rom -RomOffset 0x071BB0
$bl5 = Decode-BL -ROM $rom -RomOffset 0x071BB6

Write-Host ("  BL at 0x08071BAC -> 0x{0:X8}" -f $bl3)
Write-Host ("  BL at 0x08071BB0 -> 0x{0:X8}" -f $bl4)
Write-Host ("  BL at 0x08071BB6 -> 0x{0:X8}" -f $bl5)

Write-Host ""
Write-Host "=== Function at 0x08071BD8 (0x08071BD9 THUMB) ==="
Write-Host "This is what gets WRITTEN to gBattlerControllerFuncs[activeBattler]"
Write-Host "Literal pool:"
Write-Host "  0x030022C0 - gMain"
Write-Host "  0x0803816D - BattleMainCB2"
Write-Host "  0x02037594 - gBattleSpritesDataPtr"
Write-Host "  0x0203C534 - ?"
Write-Host "  0x0203C535 - ?"
Write-Host "  0x0203C54C - ?"

# Decode BLs in 0x08071BD8
$blAddrs2 = @(0x071C00, 0x071C26, 0x071C42, 0x071C46)
foreach ($ba in $blAddrs2) {
    $target = Decode-BL -ROM $rom -RomOffset $ba
    $romAddr = 0x08000000 + $ba
    Write-Host ("  BL at 0x{0:X8} -> 0x{1:X8}" -f $romAddr, $target)
}

Write-Host ""
Write-Host "=== Searching for 0x08071B65 in ROM (function pointer references) ==="
$searchBytes = @(0x65, 0x1B, 0x07, 0x08)
$foundCount = 0
for ($i = 0; $i -lt ($rom.Length - 3); $i++) {
    if ($rom[$i] -eq $searchBytes[0] -and $rom[$i+1] -eq $searchBytes[1] -and $rom[$i+2] -eq $searchBytes[2] -and $rom[$i+3] -eq $searchBytes[3]) {
        $addr = 0x08000000 + $i
        Write-Host ("  Found 0x08071B65 at ROM offset 0x{0:X6} (addr 0x{1:X8})" -f $i, $addr)

        # Show surrounding 4-byte values for context
        $start = [Math]::Max(0, $i - 20)
        $end = [Math]::Min($rom.Length - 4, $i + 20)
        Write-Host "    Surrounding pointers:"
        for ($j = $start; $j -le $end; $j += 4) {
            $val = [BitConverter]::ToUInt32($rom, $j)
            $marker = if ($j -eq $i) { " <-- THIS" } else { "" }
            Write-Host ("      0x{0:X8}: 0x{1:X8}{2}" -f (0x08000000 + $j), $val, $marker)
        }
        $foundCount++
    }
}
Write-Host ("  Total references found: {0}" -f $foundCount)

Write-Host ""
Write-Host "=== Also searching for 0x08071B7D (the other function at 0x08071B7C) ==="
$searchBytes2 = @(0x7D, 0x1B, 0x07, 0x08)
for ($i = 0; $i -lt ($rom.Length - 3); $i++) {
    if ($rom[$i] -eq $searchBytes2[0] -and $rom[$i+1] -eq $searchBytes2[1] -and $rom[$i+2] -eq $searchBytes2[2] -and $rom[$i+3] -eq $searchBytes2[3]) {
        $addr = 0x08000000 + $i
        Write-Host ("  Found 0x08071B7D at ROM offset 0x{0:X6} (addr 0x{1:X8})" -f $i, $addr)
    }
}

Write-Host ""
Write-Host "=== Searching for 0x08071BD9 (function written to ctrl funcs) ==="
$searchBytes3 = @(0xD9, 0x1B, 0x07, 0x08)
for ($i = 0; $i -lt ($rom.Length - 3); $i++) {
    if ($rom[$i] -eq $searchBytes3[0] -and $rom[$i+1] -eq $searchBytes3[1] -and $rom[$i+2] -eq $searchBytes3[2] -and $rom[$i+3] -eq $searchBytes3[3]) {
        $addr = 0x08000000 + $i
        Write-Host ("  Found 0x08071BD9 at ROM offset 0x{0:X6} (addr 0x{1:X8})" -f $i, $addr)
    }
}

# Let's also look at the command handler table for Player controller
# We know PlayerBufferRunCommand reads from sPlayerBufferCommands table
# Let's find where 0x08071B65 appears as a command handler
Write-Host ""
Write-Host "=== Checking if 0x08071B65 is in the sPlayerBufferCommands table ==="
Write-Host "Looking for the table near SetControllerToPlayer (0x0806F0A5)..."

# The table should be before SetControllerToPlayer, as it's a static const array
# In pokeemerald-expansion, CONTROLLER_CMDS_COUNT is typically ~50
# Let's scan backwards from SetControllerToPlayer for a table of ROM pointers

$tableSearchStart = 0x06F000  # A bit before SetControllerToPlayer
$tableSearchEnd = 0x06F0A4    # Just before SetControllerToPlayer

Write-Host "Scanning 0x0806F000-0x0806F0A4 for function pointer table..."
for ($i = $tableSearchStart; $i -lt $tableSearchEnd; $i += 4) {
    $val = [BitConverter]::ToUInt32($rom, $i)
    if (($val -band 0xFF000001) -eq 0x08000001) {  # THUMB function pointer in ROM
        $addr = 0x08000000 + $i
        Write-Host ("  0x{0:X8}: 0x{1:X8}" -f $addr, $val)
    }
}

# Also look at the entire range near the player controller
Write-Host ""
Write-Host "=== Full scan for sPlayerBufferCommands table ==="
Write-Host "The table has ~50 entries of function pointers, searching for a cluster..."

# Find clusters of ROM function pointers (0x08XXXXXX with bit 0 set for THUMB)
$clusterStart = 0x06E000
$clusterEnd = 0x070000
$consecutive = 0
$clusterAddr = 0

for ($i = $clusterStart; $i -lt $clusterEnd; $i += 4) {
    $val = [BitConverter]::ToUInt32($rom, $i)
    if (($val -band 0xFF000001) -eq 0x08000001 -and ($val -band 0x00FFFFFF) -lt 0x200000) {
        $consecutive++
        if ($consecutive -eq 1) { $clusterAddr = $i }
        if ($consecutive -ge 40) {
            Write-Host ("  Found large function pointer table at 0x{0:X8} ({1} consecutive entries)" -f (0x08000000 + $clusterAddr), $consecutive)
            # Print first 50 entries
            for ($j = 0; $j -lt 200; $j += 4) {
                $entry = [BitConverter]::ToUInt32($rom, $clusterAddr + $j)
                if (($entry -band 0xFF000001) -ne 0x08000001) { break }
                $idx = $j / 4
                $marker = if ($entry -eq 0x08071B65) { " <-- TARGET" } else { "" }
                Write-Host ("    [{0,2}] 0x{1:X8}{2}" -f $idx, $entry, $marker)
            }
            break
        }
    } else {
        $consecutive = 0
    }
}
