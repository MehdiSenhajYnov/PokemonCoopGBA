--[[
  auto_find_player_sprite.lua
  Runs in background via frame callback. Monitors gSprites entries
  and correlates tileNum changes with player movement to identify
  the player's sprite index automatically.

  Load this script in mGBA, then walk around. After a few seconds
  it will report which gSprites index is your player character.

  Results are printed to the mGBA scripting console.
]]

local WRAM = emu.memory.wram
local IWRAM = emu.memory.iwram

-- Known Run & Bun addresses
local GSPRITES_BASE = 0x020212F0 - 0x02000000  -- WRAM offset
local SPRITE_SIZE = 0x44
local MAX_SPRITES = 64

local PLAYER_X_ADDR = 0x02024CBC - 0x02000000
local PLAYER_Y_ADDR = 0x02024CBE - 0x02000000
local FACING_ADDR = 0x02036934 - 0x02000000

-- Tracking state
local frameCount = 0
local SAMPLE_INTERVAL = 2       -- Sample every 2 frames (30 samples/sec)
local REPORT_INTERVAL = 180     -- Report every 3 seconds
local IDENTIFY_AFTER = 300      -- Confident identification after 5 seconds

local prevPlayerX = nil
local prevPlayerY = nil
local prevFacing = nil
local prevTileNums = {}         -- spriteIdx -> tileNum from last sample

-- Score tracking: how often does a sprite's tileNum change
-- in the SAME frame window as a player movement/facing change?
local moveCorrelation = {}      -- spriteIdx -> count of correlated changes
local totalMoveEvents = 0       -- total player movement events detected
local tileChangeCount = {}      -- spriteIdx -> total tileNum changes (any time)
local activeFrames = {}         -- spriteIdx -> frames seen active

local identified = false
local identifiedIdx = nil

-- Read helpers
local function readPlayerPos()
  local x = WRAM:read16(PLAYER_X_ADDR)
  local y = WRAM:read16(PLAYER_Y_ADDR)
  local facing = WRAM:read8(FACING_ADDR)
  return x, y, facing
end

local function readSpriteEntry(idx)
  local off = GSPRITES_BASE + idx * SPRITE_SIZE
  if off + SPRITE_SIZE > 0x40000 then return nil end

  local flagsWord = WRAM:read16(off + 0x3E)
  local inUse = (flagsWord & 0x01) ~= 0
  if not inUse then return nil end

  local a0 = WRAM:read16(off)
  local a1 = WRAM:read16(off + 0x02)
  local a2 = WRAM:read16(off + 0x04)

  local shape = (a0 >> 14) & 0x3
  local size = (a1 >> 14) & 0x3
  local tileNum = a2 & 0x3FF
  local palNum = (a2 >> 12) & 0xF
  local hFlip = ((a1 >> 12) & 1) ~= 0
  local sheet = WRAM:read16(off + 0x40)

  -- Screen position from Sprite struct
  local posX = WRAM:read16(off + 0x20)
  local posY = WRAM:read16(off + 0x22)
  if posX >= 0x8000 then posX = posX - 0x10000 end
  if posY >= 0x8000 then posY = posY - 0x10000 end

  return {
    idx = idx,
    shape = shape,
    size = size,
    tileNum = tileNum,
    palNum = palNum,
    hFlip = hFlip,
    sheet = sheet,
    posX = posX,
    posY = posY,
  }
end

-- Frame callback
local function onFrame()
  frameCount = frameCount + 1
  if frameCount % SAMPLE_INTERVAL ~= 0 then return end

  -- Already identified? Stop heavy processing.
  if identified then return end

  -- Read player state
  local px, py, facing = readPlayerPos()
  local playerMoved = false

  if prevPlayerX then
    if px ~= prevPlayerX or py ~= prevPlayerY or facing ~= prevFacing then
      playerMoved = true
      totalMoveEvents = totalMoveEvents + 1
    end
  end

  -- Scan all sprite entries
  for idx = 0, MAX_SPRITES - 1 do
    local entry = readSpriteEntry(idx)
    if entry then
      -- Track active frames
      activeFrames[idx] = (activeFrames[idx] or 0) + 1

      -- Check tileNum change
      local prevTile = prevTileNums[idx]
      local tileChanged = prevTile and (prevTile ~= entry.tileNum)

      if tileChanged then
        tileChangeCount[idx] = (tileChangeCount[idx] or 0) + 1

        -- Correlation: did tile change happen near a player movement?
        if playerMoved then
          moveCorrelation[idx] = (moveCorrelation[idx] or 0) + 1
        end
      end

      prevTileNums[idx] = entry.tileNum
    else
      prevTileNums[idx] = nil
    end
  end

  prevPlayerX = px
  prevPlayerY = py
  prevFacing = facing

  -- Periodic report
  if frameCount % REPORT_INTERVAL == 0 then
    printReport(false)
  end

  -- Try to identify after enough data
  if frameCount >= IDENTIFY_AFTER and totalMoveEvents >= 3 then
    tryIdentify()
  end
end

function printReport(final)
  local label = final and "FINAL REPORT" or string.format("Progress (frame %d, moves=%d)", frameCount, totalMoveEvents)
  console:log("")
  console:log("=== " .. label .. " ===")

  if totalMoveEvents == 0 then
    console:log("  No player movement detected yet. Walk around!")
    console:log("  (Position: X=" .. tostring(prevPlayerX) .. " Y=" .. tostring(prevPlayerY) .. ")")
    return
  end

  -- Sort sprites by correlation score (descending)
  local ranked = {}
  for idx = 0, MAX_SPRITES - 1 do
    local corr = moveCorrelation[idx] or 0
    local changes = tileChangeCount[idx] or 0
    local frames = activeFrames[idx] or 0
    if frames > 0 and changes > 0 then
      local entry = readSpriteEntry(idx)
      table.insert(ranked, {
        idx = idx,
        correlation = corr,
        changes = changes,
        frames = frames,
        entry = entry,
      })
    end
  end

  table.sort(ranked, function(a, b)
    if a.correlation ~= b.correlation then
      return a.correlation > b.correlation
    end
    return a.changes > b.changes
  end)

  console:log(string.format("  idx | corr/moves | tileChanges | shape/size | tileNum | pal | screen(x,y)"))
  console:log(string.format("  ----|------------|-------------|------------|---------|-----|------------"))

  local shown = 0
  for _, r in ipairs(ranked) do
    if shown >= 10 then break end
    shown = shown + 1

    local e = r.entry
    local sizeNames = {
      [0] = {[0]="8x8",[1]="16x16",[2]="32x32",[3]="64x64"},
      [1] = {[0]="16x8",[1]="32x8",[2]="32x16",[3]="64x32"},
      [2] = {[0]="8x16",[1]="8x32",[2]="16x32",[3]="32x64"},
    }
    local sizeName = "?"
    local shape, size = 0, 0
    if e then
      shape = e.shape
      size = e.size
      sizeName = (sizeNames[shape] and sizeNames[shape][size]) or "?"
    end

    local marker = ""
    if r.correlation == totalMoveEvents and totalMoveEvents >= 3 then
      marker = " <-- PLAYER?"
    end
    if e and e.shape == 2 and e.size == 2 and r.correlation > 0 then
      marker = marker .. " [16x32]"
    end

    console:log(string.format("  %3d | %4d/%-5d | %11d | %d/%d %-5s | %7d | %3d | (%4d,%4d)%s",
      r.idx,
      r.correlation, totalMoveEvents,
      r.changes,
      shape, size, sizeName,
      e and e.tileNum or 0,
      e and e.palNum or 0,
      e and e.posX or 0, e and e.posY or 0,
      marker))
  end

  if shown == 0 then
    console:log("  No sprites with tile changes detected yet.")
  end
end

function tryIdentify()
  if identified then return end

  -- Find the sprite with highest correlation that is also 16x32
  local bestIdx = nil
  local bestCorr = 0

  for idx = 0, MAX_SPRITES - 1 do
    local corr = moveCorrelation[idx] or 0
    local entry = readSpriteEntry(idx)

    if entry and corr > bestCorr then
      -- Prefer 16x32 tall sprites (standard character)
      if entry.shape == 2 and entry.size == 2 then
        bestCorr = corr
        bestIdx = idx
      end
    end
  end

  -- Fallback: highest correlation any shape (if no 16x32 found)
  if not bestIdx then
    for idx = 0, MAX_SPRITES - 1 do
      local corr = moveCorrelation[idx] or 0
      if corr > bestCorr then
        bestCorr = corr
        bestIdx = idx
      end
    end
  end

  -- Need decent confidence: correlation > 50% of move events
  if bestIdx and bestCorr >= math.max(2, totalMoveEvents * 0.5) then
    identified = true
    identifiedIdx = bestIdx

    local entry = readSpriteEntry(bestIdx)
    console:log("")
    console:log("=============================================")
    console:log("  PLAYER SPRITE IDENTIFIED!")
    console:log("=============================================")
    console:log(string.format("  gSprites index:   %d", bestIdx))
    console:log(string.format("  Correlation:      %d / %d move events (%.0f%%)",
      bestCorr, totalMoveEvents, bestCorr / totalMoveEvents * 100))
    if entry then
      console:log(string.format("  Shape/Size:       %d/%d", entry.shape, entry.size))
      console:log(string.format("  Current tileNum:  %d", entry.tileNum))
      console:log(string.format("  Palette:          %d", entry.palNum))
      console:log(string.format("  Sheet:            %d", entry.sheet))
      console:log(string.format("  Screen pos:       (%d, %d)", entry.posX, entry.posY))

      local absBase = GSPRITES_BASE + 0x02000000
      console:log("")
      console:log("  For hal.lua / sprite.lua:")
      console:log(string.format("    gSpritesBase    = 0x%08X", absBase))
      console:log(string.format("    playerSpriteIdx = %d", bestIdx))
      console:log(string.format("    spriteStructSize = 0x44"))
      console:log(string.format("    playerSpriteAddr = 0x%08X", absBase + bestIdx * SPRITE_SIZE))
    end
    console:log("=============================================")

    printReport(true)

    console:log("")
    console:log("Monitoring stopped. Reload script to scan again.")
  end
end

-- Start
console:log("=============================================")
console:log("  Auto Player Sprite Finder")
console:log("  gSprites base: 0x020212F0")
console:log("=============================================")
console:log("")
console:log("Walk around with your character.")
console:log("The script will identify which gSprites entry")
console:log("is your player by correlating tile changes")
console:log("with your movement.")
console:log("")

-- Initial position read
prevPlayerX, prevPlayerY, prevFacing = readPlayerPos()
console:log(string.format("Starting position: X=%d Y=%d Facing=%d", prevPlayerX, prevPlayerY, prevFacing))
console:log("")

-- Register frame callback
callbacks:add("frame", onFrame)

console:log("Monitoring active. Move your character now!")
