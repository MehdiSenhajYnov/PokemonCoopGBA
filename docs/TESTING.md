# Testing Guide

How to test and verify the Pokémon Co-op Framework components.

## Phase 1: Foundation Testing

### Test 1: Server Startup

```bash
cd server
node server.js
```

**Expected output:**
```
╔═══════════════════════════════════════════════════════╗
║   Pokémon Co-op Framework - TCP Relay Server          ║
╚═══════════════════════════════════════════════════════╝
[Server] Listening on port 8080
[Server] Ready to accept TCP connections
```

### Test 2: Server Connection Test

**In a new terminal** (keep server running):

```bash
cd server
node test-connection.js
```

**Expected output:**
```
===========================================
TCP Connection Test
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

### Test 3: Lua Script Loading

1. Start mGBA (dev build 0.11+)
2. Load Pokémon Run & Bun (or Emerald US) ROM
3. Go to **Tools → Scripting**
4. Click **File → Load Script...**
5. Select `client/main.lua`

**Expected output in console:**
```
======================================
Pokémon Co-op Framework v0.2.0
======================================
[PokéCoop] Initializing Pokémon Co-op Framework...
[PokéCoop] Detected ROM ID: BPEE
[PokéCoop] Detected ROM Title: POKEMON EMER (or RUN & BUN)
[PokéCoop] Loading Run & Bun config (BPEE detected)
[HAL] Initialized with config: Pokémon Run & Bun
[PokéCoop] Using config: Pokémon Run & Bun
[PokéCoop] Player ID: player_1
[PokéCoop] Connecting to server 127.0.0.1:8080...
```

### Test 4: Full 2-Player Test (Direct TCP)

**Terminal - Server:**
```bash
cd server
node server.js
```

**mGBA Instance 1:**
- Load ROM → Tools → Scripting → Load `client/main.lua`

**mGBA Instance 2:**
- Load ROM → Tools → Scripting → Load `client/main.lua`

**Expected:**
- Both clients connect directly to server (no proxy needed)
- Each client gets a unique auto-generated player ID
- Position updates appear in server logs
- Each player sees the other's ghost on screen

### Test 5: Position Reading

With script loaded and game running:

1. Load a save file or start new game
2. Walk around in-game
3. Check the screen for overlay text

**Expected on-screen display:**
- Top bar: `Players: 1  ONLINE  X:10 Y:15 M:0:3`

**Expected console output** (every 3 seconds):
```
[PokéCoop] Position: X=10 Y=15 Map=0:3 Facing=1
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
[HAL] Config loaded: Pokémon Run & Bun
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
   ├── hal.lua
   ├── network.lua
   ├── render.lua
   ├── interpolate.lua
   └── config/
       ├── emerald_us.lua
       └── run_and_bun.lua
   ```
2. Ensure you're loading from the correct working directory
3. Check that Lua paths are relative from `client/main.lua`

### No position data

**Issue:** Coordinates show as nil or don't update

**Checks:**
1. Verify ROM is loaded (Run & Bun or Emerald US)
2. Check ROM header in console - should show `BPEE`
3. Try loading a save file (new game might have unstable coordinates)
4. Walk around - coordinates update on movement

**Debug command:**
```lua
-- In mGBA console (Run & Bun offsets)
print(string.format("X: %d", emu.memory.wram:read16(0x00024CBC)))
print(string.format("Y: %d", emu.memory.wram:read16(0x00024CBE)))
```

### ROM Detection Fails

**Issue:** `Failed to detect ROM`

**Solution:**
1. Verify ROM is loaded in mGBA
2. Check ROM header at 0x080000AC
3. Try reloading the script (Ctrl+R)

---

## Verification Checklist

Phase 1 (Complete):

- [x] Server starts and listens on port 8080 (TCP)
- [x] test-connection.js completes all tests
- [x] Lua script loads without errors
- [x] ROM detection shows "BPEE"
- [x] Position coordinates display on screen overlay
- [x] Position logs appear in console
- [x] HAL memory reads work (Run & Bun offsets)
- [x] Direct TCP socket connects Lua client to server (no proxy)
- [x] 2 clients can connect simultaneously

Phase 2 (In Progress):

- [x] Ghost sprite renders on screen (semi-transparent green rectangle)
- [x] Two clients see each other's ghost on the map
- [x] Ghost position correct on all maps (relative screen-center positioning)
- [x] Movement interpolation smooth
- [ ] Disconnection handled gracefully

Phase 3 (Future):

- [ ] Duel request sends to server
- [ ] Duel accept triggers warp
- [ ] Both players teleport simultaneously
- [ ] Link battle initiates

---

## Performance Benchmarks

### Server Performance

```bash
node server.js
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

## Bug Reporting

When reporting issues, include:

1. **Environment:**
   - OS and version
   - Node.js version (`node --version`)
   - mGBA version (dev build number)
   - ROM version (check header)

2. **Logs:**
   - Server console output
   - Server console output (connections, messages)
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
