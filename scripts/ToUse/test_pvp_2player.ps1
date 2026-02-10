# Test PvP 2-player battle with move synchronization
# Uses ss1 for player 1 (master/requester) and ss2 for player 2 (slave/accepter)
# Requires server running: node server/server.js

$mgba = "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\mgba\mGBA.exe"
$rom = "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba"
$ss1 = "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.ss1"
$ss2 = "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.ss2"
$mainLua = "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\client\main.lua"

# Kill any existing mGBA
Stop-Process -Name mGBA -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Set AUTO_DUEL = "request" for player 1
$content = Get-Content $mainLua -Raw
$content = $content -replace '_G\.AUTO_DUEL = _G\.AUTO_DUEL or nil', '_G.AUTO_DUEL = "request"'
$content | Set-Content $mainLua -NoNewline
Write-Host "[Test] Launching Player 1 (master, ss1=Chimchar, requester)..."
& $mgba -t $ss1 --script $mainLua $rom &
Start-Sleep -Seconds 3

# Set AUTO_DUEL = "accept" for player 2
$content = Get-Content $mainLua -Raw
$content = $content -replace '_G\.AUTO_DUEL = "request"', '_G.AUTO_DUEL = "accept"'
$content | Set-Content $mainLua -NoNewline
Write-Host "[Test] Launching Player 2 (slave, ss2=Piplup, accepter)..."
& $mgba -t $ss2 --script $mainLua $rom &
Start-Sleep -Seconds 2

# Restore AUTO_DUEL to nil
$content = Get-Content $mainLua -Raw
$content = $content -replace '_G\.AUTO_DUEL = "accept"', '_G.AUTO_DUEL = _G.AUTO_DUEL or nil'
$content | Set-Content $mainLua -NoNewline
Write-Host "[Test] AUTO_DUEL restored to nil in main.lua"

Write-Host ""
Write-Host "[Test] Both players launched. Watch server output for duel flow."
Write-Host "[Test] Expected: both connect, duel triggered, parties exchanged, battle starts"
Write-Host "[Test] Kill both after test: Stop-Process -Name mGBA -Force"
