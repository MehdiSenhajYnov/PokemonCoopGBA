#!/bin/bash
# Pokémon Co-op Framework - Server Startup Script (Linux/Mac)
# Run this to quickly start the WebSocket server

echo "========================================"
echo "Pokémon Co-op Framework - Server"
echo "========================================"
echo ""

cd server || exit 1

if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
    echo ""
fi

echo "Starting server..."
echo "Press Ctrl+C to stop"
echo ""

npm start
