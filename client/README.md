# Pokémon Co-op Client (Lua)

mGBA Lua script for the Pokémon Co-op Framework.

## Requirements

- **mGBA 0.11+ dev build** (required for canvas overlay API + built-in TCP sockets)
- Lua scripting enabled in mGBA

## Installation

1. Place all `.lua` files in a directory accessible by mGBA
2. Ensure the `config/` folder is in the same parent directory
3. Start the Node.js server (`node server/server.js`)
4. Load `main.lua` in mGBA via Tools > Scripting

## File Structure

- `main.lua` - Main entry point and game loop
- `hal.lua` - Hardware Abstraction Layer (WRAM, IWRAM, VRAM, OAM, Palette, BG I/O registers)
- `network.lua` - Direct TCP client (mGBA built-in socket API, auto-reconnect with backoff)
- `render.lua` - Ghost player rendering (Painter API, camera correction, occlusion integration)
- `sprite.lua` - VRAM sprite extraction (OAM scan, 4bpp tile decode, palette, cache, network sync)
- `occlusion.lua` - BG layer occlusion (reads BG1 tilemap, redraws cover tiles over ghosts via Painter)
- `interpolate.lua` - Smooth ghost movement (animate-toward-target interpolation)
- `duel.lua` - Duel system (proximity trigger, request/accept UI, A button edge detect)
- `battle.lua` - PvP battle system (Link Battle Emulation: buffer relay with per-frame re-write, ROM patching, state machine)
- `core.lua` - (Future) Core engine

## Configuration

Edit these values in `main.lua`:

```lua
local SERVER_HOST = "127.0.0.1"  -- TCP server address
local SERVER_PORT = 8080          -- TCP server port
local ENABLE_DEBUG = true         -- Show debug info overlay
```

## Usage

### Loading the Script

In mGBA:
1. Tools > Scripting
2. File > Load Script...
3. Select `main.lua`

### What Happens

- ROM is auto-detected (Run & Bun / Emerald)
- Connects to TCP server automatically
- Other players appear as ghost sprites on screen
- Ghosts are hidden behind buildings/trees (BG occlusion)
- Auto-reconnects if server connection drops

### Debug Overlay

When `ENABLE_DEBUG = true`, the top bar shows:
- Player count
- Connection status (ONLINE / RECONNECTING / OFFLINE)
- Current tile coordinates and map ID

## Architecture

### HAL (Hardware Abstraction Layer)

Safe memory access with `pcall` protection:

```lua
-- Player data (WRAM/EWRAM)
HAL.readPlayerX()      -- Returns X tile coordinate
HAL.readPlayerY()      -- Returns Y tile coordinate
HAL.readMapId()        -- Returns map ID
HAL.readMapGroup()     -- Returns map group
HAL.readFacing()       -- Returns facing direction (1-4)

-- Camera (IWRAM)
HAL.readCameraX()      -- gSpriteCoordOffsetX (signed s16)
HAL.readCameraY()      -- gSpriteCoordOffsetY (signed s16)

-- OAM/VRAM/Palette (sprite extraction)
HAL.readOAMEntry(index)              -- Read OAM entry (attr0, attr1, attr2)
HAL.readSpriteTiles(tileIndex, n)    -- Read sprite tile data from VRAM
HAL.readSpritePalette(bank)          -- Read 16-color sprite palette

-- BG layer I/O (occlusion)
HAL.readIOReg16(offset)              -- Read 16-bit I/O register
HAL.readBGControl(bgIndex)           -- Parse BGnCNT register
HAL.readBGScroll(bgIndex)            -- Read BGnHOFS/VOFS
HAL.readBGTilemapEntry(sb, tx, ty, size)  -- Read tilemap entry from VRAM
HAL.readBGTileData(charBase, tileId) -- Read 4bpp tile pixel data
HAL.readBGPalette(palBank)           -- Read 16-color BG palette
```

### Occlusion System

The overlay canvas draws ON TOP of all GBA output. Without occlusion, ghosts appear above buildings/trees. The occlusion module fixes this:

1. Each frame, reads BG1 control register + scroll offsets
2. For each ghost, identifies BG1 tiles overlapping the ghost bounding box
3. Decodes 4bpp tile pixel data + BG palette (BGR555 to ARGB)
4. Redraws non-transparent cover pixels on the overlay using Painter API
5. Result: ghosts are hidden behind rooftops, trees, and other foreground scenery

Tile pixel data is cached (max 256 tiles, grouped by color for efficient Painter calls). Cache is cleared on map change.

## Supported ROMs

- **Pokémon Run & Bun** (primary target, Emerald engine)
- **Pokémon Emerald US** (BPEE, vanilla reference)

Planned:
- Pokémon Radical Red
- Pokémon Unbound

## Troubleshooting

### Script doesn't load
- Ensure mGBA is a **dev build** (0.11+) — stable releases don't have canvas API
- Check mGBA console for error messages

### No ghost appears
- Ensure both clients are connected to the same server
- Check both players are on the same map
- Verify server is running (`node server/server.js`)

### "Connection lost" / OFFLINE
- Server may have stopped — restart it
- Auto-reconnection will attempt up to 10 times with exponential backoff
