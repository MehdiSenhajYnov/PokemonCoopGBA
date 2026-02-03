# Phase 2: Ghosting System - Implementation Plan

**Status**: Planning
**Prerequisites**: Phase 1 Complete ✅
**Estimated Effort**: 2-3 weeks

## Overview

Implement real-time position synchronization and ghost player rendering. Players will see each other's positions on their respective screens.

## Technical Challenges

### Challenge 1: Lua TCP Client

**Problem**: mGBA Lua doesn't have built-in WebSocket support.

**Solution Chosen**: TCP Sockets (Raw)
   - Use `socket.tcp()` available in mGBA
   - JSON line-delimited protocol (simpler than WebSocket)
   - Server uses Node.js `net` module for TCP
   - Messages terminated by `\n` character

**Why not WebSocket?**
- mGBA Lua has no WebSocket library
- Manual WebSocket handshake too complex
- TCP is simpler and works out of the box

**Implementation**: Both server and client use raw TCP with JSON messages.

### Challenge 2: Ghost Rendering

**Problem**: Draw other player sprites on screen without affecting game state.

**Solution**:
```lua
-- Use gui API (overlays don't affect game)
gui.drawImage(x, y, spriteData)  -- If sprite loading supported
-- OR
gui.drawRectangle(x, y, width, height, color)  -- Simple placeholder
```

**Sprite Extraction**:
- Extract player sprites from ROM VRAM
- Convert to format mGBA can render
- Cache for performance

### Challenge 3: Coordinate Translation

**Problem**: GBA coordinates vs screen pixels.

**Solution**:
```lua
-- Game uses tile coordinates (16x16 pixels per tile)
local screenX = (playerX - cameraX) * 16
local screenY = (playerY - cameraY) * 16

-- Camera position needs to be read from memory
-- Emerald: 0x02024??? (TBD - needs research)
```

## Implementation Steps

### Step 1: Research & Prototyping (3-4 days)

**Tasks**:
- [ ] Test LuaSocket availability in mGBA
- [ ] Create proof-of-concept TCP connection
- [ ] Research camera position offsets
- [ ] Test `gui.drawRectangle()` performance

**Deliverables**:
- Document: `docs/lua_networking_options.md`
- Prototype: `client/prototype_network.lua`
- Updated config with camera offsets

### Step 2: TCP Implementation (2-3 days)

**Lua-side TCP** (using mGBA socket.tcp())
```lua
-- client/network.lua
local socket = require("socket")

local Network = {}
local client = nil

function Network.connect(url, port)
  client = socket.tcp()
  client:connect(url, port)
  client:settimeout(0)  -- Non-blocking
  return client ~= nil
end

function Network.send(message)
  if client then
    client:send(json.encode(message) .. "\n")
  end
end

function Network.receive()
  if client then
    local data, err = client:receive()
    if data then
      return json.decode(data)
    end
  end
  return nil
end

return Network
```

**Server-side TCP** (Node.js net module)
```javascript
// server/server.js (adapted for TCP)
const net = require('net');

const server = net.createServer((socket) => {
  console.log('Client connected');

  socket.on('data', (data) => {
    const lines = data.toString().split('\n');
    lines.forEach(line => {
      if (line.trim()) {
        const message = JSON.parse(line);
        handleMessage(socket, message);
      }
    });
  });

  socket.on('end', () => {
    console.log('Client disconnected');
  });
});

server.listen(8080);
```

**Deliverables**:
- File: `client/network.lua`
- Updated `server/server.js` for TCP
- Updated `main.lua` with network integration

### Step 3: Position Synchronization (2-3 days)

**Client Changes**:
```lua
-- In main.lua update loop
local function update()
  local currentPos = readPlayerPosition()

  if positionChanged(currentPos, State.lastPosition) then
    Network.send({
      type = "position",
      data = currentPos
    })
    State.lastPosition = currentPos
  end

  -- Receive other players
  local message = Network.receive()
  if message and message.type == "position" then
    State.otherPlayers[message.playerId] = message.data
  end
end
```

**Server Changes**:
- Already implemented! ✅
- Just need to connect Lua client

**Deliverables**:
- Updated `client/main.lua`
- Test script for 2-client sync

### Step 4: Ghost Rendering (3-4 days)

**Simple Version** (MVP):
```lua
-- Draw colored squares for other players
local function drawOtherPlayers()
  for playerId, pos in pairs(State.otherPlayers) do
    -- Skip if on different map
    if pos.mapId == State.lastPosition.mapId and
       pos.mapGroup == State.lastPosition.mapGroup then

      local screenX = (pos.x - cameraX) * 16 + 8
      local screenY = (pos.y - cameraY) * 16 + 8

      -- Draw semi-transparent square
      gui.drawRectangle(screenX, screenY, 14, 14, 0x8000FF00)

      -- Draw player ID
      gui.drawText(screenX, screenY - 8, playerId, 0xFFFFFF)
    end
  end
end
```

**Advanced Version** (Future):
```lua
-- Load and draw actual player sprite
local sprites = loadPlayerSprites()  -- Extract from ROM
gui.drawImage(screenX, screenY, sprites[pos.facing])
```

**Deliverables**:
- Function: `drawOtherPlayers()`
- Updated frame callback with rendering
- Camera position reading

### Step 5: Movement Interpolation (2-3 days)

**Problem**: Network updates are discrete, movement looks choppy.

**Solution**: Linear interpolation between positions
```lua
local function interpolatePosition(from, to, progress)
  return {
    x = from.x + (to.x - from.x) * progress,
    y = from.y + (to.y - from.y) * progress
  }
end

-- Store both current and target positions
State.otherPlayers[id] = {
  current = lastKnownPos,
  target = newPos,
  progress = 0
}

-- In update loop
for id, player in pairs(State.otherPlayers) do
  if player.progress < 1 then
    player.progress = player.progress + 0.1  -- Adjust speed
    player.current = interpolatePosition(
      player.current,
      player.target,
      player.progress
    )
  end
end
```

**Deliverables**:
- Interpolation logic
- Smooth movement rendering
- Configurable interpolation speed

### Step 6: Polish & Testing (2-3 days)

**Features**:
- [ ] Connection status indicator (UI)
- [ ] Disconnection handling
- [ ] Player name display above ghost
- [ ] Toggle ghost visibility (F3 key)
- [ ] Performance optimization
- [ ] Error handling

**Testing**:
- [ ] Test with 2 clients on same machine
- [ ] Test with 2 clients on LAN
- [ ] Test with 10+ clients (stress test)
- [ ] Test different maps
- [ ] Test rapid movement
- [ ] Test connection drops

**Deliverables**:
- Updated [TESTING.md](TESTING.md)
- Performance benchmarks
- Bug fixes

## File Structure After Phase 2

```
client/
├── main.lua           # Entry point (updated)
├── hal.lua            # Hardware abstraction (updated with camera)
├── network.lua        # NEW: Network communication
├── render.lua         # NEW: Ghost rendering
├── interpolate.lua    # NEW: Movement smoothing
└── README.md          # Updated docs

server/
├── server.js          # Existing (minimal changes)
├── lua-bridge.js      # NEW: File bridge (if needed)
└── ...

docs/
├── lua_networking.md  # NEW: Networking research
└── performance.md     # NEW: Optimization notes
```

## Success Criteria

Phase 2 is complete when:

- [x] Two mGBA clients can connect to server
- [x] Position updates sync in real-time
- [x] Ghost players render on screen
- [x] Movement is smooth (interpolated)
- [x] Works on different maps
- [x] Disconnections handled gracefully
- [x] < 100ms latency on localhost
- [x] < 5% CPU overhead

## Known Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| LuaSocket unavailable in mGBA | High | Use file bridge fallback |
| Camera offsets hard to find | Medium | Use memory scanner tools |
| Performance issues with rendering | Medium | Optimize render frequency |
| Network latency causes jitter | Low | Increase interpolation buffer |

## Resources Needed

- GBA memory scanner (Cheat Engine)
- VBA-SDL-H for memory debugging
- 2+ test ROMs (Emerald saves)
- Network debugging tool (Wireshark optional)

## Next Phase

After Phase 2 completes → [Phase 3: Duel Warp System](PHASE3_PLAN.md)

---

**Start Date**: TBD
**Target Completion**: TBD
**Assignee**: TBD
