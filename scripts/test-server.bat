@echo off
REM Pokémon Co-op Framework - Server Test Script
REM Run this to test the WebSocket server connection

echo ========================================
echo Pokemon Co-op Framework - Server Test
echo ========================================
echo.

cd server

if not exist node_modules (
    echo ERROR: Dependencies not installed!
    echo Please run: start-server.bat first
    echo.
    pause
    exit /b 1
)

echo Running connection test...
echo Make sure the server is running in another window!
echo.

node test-connection.js

pause
