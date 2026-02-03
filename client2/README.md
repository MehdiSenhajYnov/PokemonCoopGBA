# Pokémon Co-op Client (Lua)

mGBA Lua script for the Pokémon Co-op Framework.

## Installation

1. Place all `.lua` files in a directory accessible by mGBA
2. Ensure the `config/` folder is in the same parent directory
3. Load `main.lua` in mGBA via Tools > Scripting

## File Structure

- `main.lua` - Main entry point and game loop
- `hal.lua` - Hardware Abstraction Layer for safe memory access
- `core.lua` - (Future) Core networking and overlay logic

## Configuration

Edit these values in `main.lua`:

```lua
local SERVER_URL = "ws://localhost:8080"  -- WebSocket server address
local UPDATE_RATE = 60                     -- Frames between updates
local ENABLE_DEBUG = true                  -- Show debug info
```

## Usage

### Loading the Script

In mGBA:
1. Tools → Scripting
2. File → Load Script...
3. Select `main.lua`

### Controls

(To be implemented)
- F1: Connect/Disconnect from server
- F2: Request duel with nearby player
- F3: Toggle ghost visibility

### Debug Info

When `ENABLE_DEBUG = true`, the following is displayed:

- Current X/Y coordinates
- Map Group:ID
- Connected player count
- Console log of position updates

## Memory Safety

The HAL module ensures:
- All reads are validated within WRAM range (0x02000000-0x0203FFFF)
- Protected by `pcall` to prevent crashes
- Pointer chains validated at each step
- Invalid addresses return `nil` gracefully

## Testing

Current phase displays:
- Player coordinates on screen
- Map information
- Position logs in console (every 3 seconds)

Next phase will add:
- WebSocket connection
- Position synchronization
- Ghost rendering

## Troubleshooting

### Script doesn't load
- Ensure mGBA has Lua scripting support (check Tools menu)
- Verify file paths are correct
- Check mGBA console for error messages

### No position data shown
- Verify you're using Pokémon Emerald US ROM
- Try walking around to trigger position updates
- Check console for "Failed to read player position" warnings

### Memory read errors
- ROM may not be Emerald US - check game ID in console
- DMA timing issues - try pausing/resuming the game

## Supported ROMs

Currently configured for:
- ✅ Pokémon Emerald (US) - BPEE

Planned support:
- ⏳ Pokémon Radical Red
- ⏳ Pokémon Unbound
- ⏳ Pokémon Run & Bun

## Development

### Adding New ROM Support

1. Create new config file: `config/newrom.lua`
2. Find memory offsets using tools like Cheat Engine
3. Follow `emerald_us.lua` structure
4. Test with HAL.testMemoryAccess()

### Memory Offset Hunting

Use these tools:
- VBA-SDL-H (memory viewer)
- Cheat Engine (value scanning)
- PokéFinder (RNG analysis)
- No$GBA (debugger)

## API Reference

### HAL Functions

```lua
-- Read player data
HAL.readPlayerX()      -- Returns X coordinate (0-1023)
HAL.readPlayerY()      -- Returns Y coordinate (0-1023)
HAL.readMapId()        -- Returns map ID (0-255)
HAL.readMapGroup()     -- Returns map group (0-34)
HAL.readFacing()       -- Returns facing direction (1-4)

-- Write player data (for warp)
HAL.writePlayerPosition(x, y, mapId, mapGroup)
```

### Config Structure

```lua
{
  name = "Game Name",
  gameId = "ROMID",
  offsets = {
    playerX = 0x02024844,
    playerY = 0x02024846,
    -- ...
  },
  maps = {
    -- Named locations
  }
}
```
