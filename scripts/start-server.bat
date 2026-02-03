@echo off
REM Pokémon Co-op Framework - Server Startup Script
REM Run this to quickly start the WebSocket server

echo ========================================
echo Pokemon Co-op Framework - Server
echo ========================================
echo.

cd server

if not exist node_modules (
    echo Installing dependencies...
    call npm install
    echo.
)

echo Starting server...
echo Press Ctrl+C to stop
echo.

call npm start

pause
