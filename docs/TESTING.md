# Testing Guide

How to test and verify the Pokémon Co-op Framework components.

## Phase 1: Foundation Testing (Current)

### Test 1: Server Installation

```bash
cd server
npm install
```

**Expected output:**
```
added 2 packages
```

### Test 2: Server Startup

```bash
npm start
```

**Expected output:**
```
╔═══════════════════════════════════════════════════════╗
║   Pokémon Co-op Framework - WebSocket Server         ║
╚═══════════════════════════════════════════════════════╝
[Server] Listening on port 8080
[Server] WebSocket URL: ws://localhost:8080
[Server] Ready to accept connections
```

### Test 3: Server Connection Test

**In a new terminal** (keep server running):

```bash
cd server
node test-connection.js
```

**Expected output:**
```
===========================================
WebSocket Connection Test
===========================================

✅ Connected to server

[Test 1] Registering player...
📥 Received: {
  "type": "registered",
  "playerId": "test_player_1"
}

[Test 2] Joining default room...
📥 Received: {
  "type": "joined",
  "roomId": "default"
}

[Test 3] Sending position update...

[Test 4] Sending ping...
📥 Received: {
  "type": "pong"
}

===========================================
✅ All tests completed successfully!
===========================================

🔌 Connection closed
```

### Test 4: Lua Script Loading

1. Start mGBA
2. Load Pokémon Emerald (US) ROM
3. Go to **Tools → Scripting**
4. Click **File → Load Script...**
5. Select `client/main.lua`

**Expected output in console:**
```
======================================
Pokémon Co-op Framework v0.1.0
======================================
[PokéCoop] Initializing Pokémon Co-op Framework...
[HAL] Initialized with config: Pokémon Emerald (US)
[PokéCoop] Detected ROM: BPEE
[PokéCoop] Player ID: player_12345_abc
[PokéCoop] WebSocket connection not yet implemented
[PokéCoop] Server URL: ws://localhost:8080
[PokéCoop] Initialization complete!
[PokéCoop] Script loaded successfully!
[PokéCoop] Press Ctrl+L to reload this script
```

### Test 5: Position Reading

With script loaded and game running:

1. Load a save file or start new game
2. Walk around in-game
3. Check the screen for overlay text

**Expected on-screen display:**
- Bottom-left corner: `X:10 Y:15` (your coordinates)
- Below that: `Map:3:1` (your current map)

**Expected console output** (every 3 seconds):
```
[PokéCoop] Position: X=10 Y=15 Map=3:1 Facing=1
```

### Test 6: HAL Memory Safety

In mGBA scripting console, type:

```lua
HAL.testMemoryAccess()
```

**Expected output:**
```
[HAL] Testing memory access...
[HAL] WRAM access: OK
[HAL] Invalid address protection: OK
[HAL] Config loaded: Pokémon Emerald (US)
[HAL] PlayerX offset: 0x02024844
```

---

## Troubleshooting Tests

### Server won't start

**Error:** `EADDRINUSE: address already in use`

**Solution:**
```bash
# Windows
netstat -ano | findstr :8080
taskkill /PID <PID> /F

# Linux/Mac
lsof -ti:8080 | xargs kill -9
```

### Script won't load

**Error:** `Cannot find module 'hal'`

**Check:**
1. Verify directory structure:
   ```
   client/
   ├── main.lua
   └── hal.lua
   config/
   └── emerald_us.lua
   ```
2. Ensure you're loading from the correct working directory
3. Check that Lua paths are relative from `client/main.lua`

### No position data

**Issue:** Coordinates show as `X:nil Y:nil`

**Checks:**
1. Verify ROM is Pokémon Emerald **US version** (not UK/JP)
2. Check ROM header in console - should show `BPEE`
3. Try loading a save file (new game might have unstable coordinates)
4. Walk around - coordinates update on movement

**Debug command:**
```lua
-- In mGBA console
print(string.format("0x%08X", memory.read32(0x02024844)))
```

### ROM Detection Fails

**Issue:** `Failed to detect ROM`

**Solution:**
1. Verify ROM is loaded in mGBA
2. Check ROM header at 0x080000AC
3. Try reloading the script (Ctrl+L)

---

## Verification Checklist

Phase 1 (Current):

- [ ] Server installs without errors
- [ ] Server starts and listens on port 8080
- [ ] test-connection.js completes all tests
- [ ] Lua script loads without errors
- [ ] ROM detection shows "BPEE"
- [ ] Position coordinates display on screen
- [ ] Position logs appear in console
- [ ] HAL memory test passes
- [ ] Can reload script with Ctrl+L

Phase 2 (Future):

- [ ] WebSocket connects from Lua
- [ ] Position updates reach server
- [ ] Ghost sprite renders on screen
- [ ] Two clients see each other

Phase 3 (Future):

- [ ] Duel request sends to server
- [ ] Duel accept triggers warp
- [ ] Both players teleport simultaneously
- [ ] Link battle initiates

---

## Performance Benchmarks

### Server Performance

```bash
# Measure memory usage
node --expose-gc server.js
```

**Expected:**
- Idle: ~30 MB RAM
- 10 clients: ~50 MB RAM
- 100 messages/sec: ~60 MB RAM

### Client Performance

**Expected FPS:**
- Without script: 60 FPS
- With script: 59-60 FPS (minimal impact)

**Expected position read time:**
- < 0.1ms per read
- HAL overhead: < 1% CPU

---

## Automated Testing (Future)

```bash
# Run all server tests
npm test

# Run integration tests
npm run test:integration

# Run Lua unit tests
lua test/test_hal.lua
```

---

## Bug Reporting

When reporting issues, include:

1. **Environment:**
   - OS and version
   - Node.js version (`node --version`)
   - mGBA version
   - ROM version (check header)

2. **Logs:**
   - Server console output
   - mGBA scripting console output
   - Error messages

3. **Steps to reproduce:**
   - What you did
   - What you expected
   - What actually happened

4. **Screenshots:**
   - Error messages
   - Console output
   - In-game display (if relevant)

---

**Next:** See [QUICKSTART.md](QUICKSTART.md) for initial setup guide.
