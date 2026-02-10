# Test Buffer Relay PvP Battle — 2-player automated test
# Usage: powershell -File scripts/ToUse/test_buffer_relay.ps1

$ErrorActionPreference = "Stop"
$projectDir = "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA"
$mgba = "$projectDir\mgba\mGBA.exe"
$rom = "$projectDir\rom\Pokemon RunBun.gba"
$ss1 = "$projectDir\rom\Pokemon RunBun.ss1"
$ss2 = "$projectDir\rom\Pokemon RunBun.ss2"
$server = "$projectDir\server\server.js"

Write-Host "=== Buffer Relay PvP Test ===" -ForegroundColor Cyan

# Kill any stale processes
Stop-Process -Name mGBA -Force -ErrorAction SilentlyContinue
Stop-Process -Name node -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Step 1: Start server
Write-Host "[1/3] Starting server..." -ForegroundColor Yellow
$serverProc = Start-Process -FilePath "node" -ArgumentList $server -PassThru -NoNewWindow
Start-Sleep -Seconds 2

if ($serverProc.HasExited) {
    Write-Host "ERROR: Server failed to start" -ForegroundColor Red
    exit 1
}
Write-Host "Server PID: $($serverProc.Id)" -ForegroundColor Green

# Step 2: Launch Player 1 (master, ss1=Chimchar, requester)
Write-Host "[2/3] Launching Player 1 (master)..." -ForegroundColor Yellow
$p1 = Start-Process -FilePath $mgba -ArgumentList "-t `"$ss1`" --script `"$projectDir\client\auto_duel_requester.lua`" `"$rom`"" -PassThru
Start-Sleep -Seconds 3

# Step 3: Launch Player 2 (slave, ss2=Piplup, accepter)
Write-Host "[3/3] Launching Player 2 (slave)..." -ForegroundColor Yellow
$p2 = Start-Process -FilePath $mgba -ArgumentList "-t `"$ss2`" --script `"$projectDir\client\auto_duel_accepter.lua`" `"$rom`"" -PassThru
Start-Sleep -Seconds 2

Write-Host "Both instances running. Waiting for auto-duel + battle..." -ForegroundColor Cyan
Write-Host "Player 1 PID: $($p1.Id), Player 2 PID: $($p2.Id)" -ForegroundColor Green

# Wait for battle to progress (give it time for duel request + accept + battle init + a few turns)
Write-Host "Waiting 60 seconds for battle to complete..." -ForegroundColor Yellow
Start-Sleep -Seconds 60

# Cleanup
Write-Host "Cleaning up..." -ForegroundColor Yellow
Stop-Process -Id $p1.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $p2.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $serverProc.Id -Force -ErrorAction SilentlyContinue

Write-Host "=== Test Complete ===" -ForegroundColor Cyan
Write-Host "Check mGBA console output for battle logs" -ForegroundColor White
