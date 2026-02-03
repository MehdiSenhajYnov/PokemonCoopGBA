--[[
  Camera Offset Verifier v3

  Verifies camera IWRAM offsets with ONE definitive test:
    Does camera change by exactly ±16 per tile moved?

  Also tracks K = tileX*16 + cameraX per map (resets on map change).

  USAGE: Load, walk around, check console.
]]

-- Run & Bun offsets
local PLAYER_X   = 0x00024CBC   -- EWRAM (wram relative)
local PLAYER_Y   = 0x00024CBE
local MAP_GROUP   = 0x00024CC0
local MAP_ID      = 0x00024CC1
local CAMERA_X   = 0x5DFC       -- IWRAM offset
local CAMERA_Y   = 0x5DF8

local STABLE_THRESHOLD = 25     -- frames to consider "stopped"

-- State
local lastFrameX, lastFrameY = nil, nil       -- previous frame position
local stableFrames = 0                         -- consecutive frames without tile change
local refX, refY = nil, nil                    -- reference position (last stable point)
local refCamX, refCamY = nil, nil              -- reference camera (last stable point)
local refMapGroup, refMapId = nil, nil         -- reference map
local kSamples = {}                            -- K values on current map
local deltaLog = {}                            -- recorded delta checks
local phase = "init"                           -- init | ready | moved

-- Overlay
local overlay, painter = nil, nil

local function readS16_IWRAM(off)
  local ok, v = pcall(function() return emu.memory.iwram:read16(off) end)
  if not ok then return nil end
  if v > 32767 then v = v - 65536 end
  return v
end

local function readU8_WRAM(off)
  local ok, v = pcall(function() return emu.memory.wram:read8(off) end)
  if ok then return v end
  return nil
end

local function readU16_WRAM(off)
  local ok, v = pcall(function() return emu.memory.wram:read16(off) end)
  if ok then return v end
  return nil
end

local function initOverlay()
  if not canvas then return end
  overlay = canvas:newLayer(240, 160)
  overlay:setPosition(0, 0)
  painter = image.newPainter(overlay.image)
  painter:setFill(true)
  painter:setStrokeWidth(0)
  painter:setBlend(true)
  pcall(function()
    painter:loadFont("C:/Windows/Fonts/consola.ttf")
    painter:setFontSize(9)
  end)
end

local function onFrame()
  if not painter or not overlay then return end

  local px = readU16_WRAM(PLAYER_X)
  local py = readU16_WRAM(PLAYER_Y)
  local camX = readS16_IWRAM(CAMERA_X)
  local camY = readS16_IWRAM(CAMERA_Y)
  local mapG = readU8_WRAM(MAP_GROUP)
  local mapI = readU8_WRAM(MAP_ID)
  if not px or not py or not camX or not camY then return end

  -- Detect map change -> reset K samples
  if mapG ~= refMapGroup or mapI ~= refMapId then
    kSamples = {}
    refMapGroup = mapG
    refMapId = mapI
    phase = "init"
    stableFrames = 0
    refX, refY = nil, nil
    lastFrameX, lastFrameY = nil, nil
    console:log(string.format("[Verify] Map changed to %d:%d, resetting", mapG, mapI))
  end

  -- Track frame-to-frame stability (NOT vs reference!)
  local frameMoved = (lastFrameX ~= nil and (px ~= lastFrameX or py ~= lastFrameY))
  lastFrameX = px
  lastFrameY = py

  if frameMoved then
    stableFrames = 0
    if phase == "ready" then
      phase = "moved"
    end
  else
    stableFrames = stableFrames + 1
  end

  -- When player settles
  if stableFrames == STABLE_THRESHOLD then
    -- Record K sample for this map
    local kx = px * 16 + camX
    local ky = py * 16 + camY
    table.insert(kSamples, {kx = kx, ky = ky})

    if phase == "init" then
      -- First stable point on this map
      refX, refY = px, py
      refCamX, refCamY = camX, camY
      phase = "ready"
      console:log(string.format("[Verify] Ready. Tile(%d,%d) Cam(%d,%d) K=(%d,%d)",
        px, py, camX, camY, kx, ky))

    elseif phase == "moved" then
      -- Settled after movement - check delta
      local dtx = px - refX
      local dty = py - refY
      local dcx = camX - refCamX
      local dcy = camY - refCamY

      if dtx ~= 0 then
        local expected = dtx * -16
        local pass = (dcx == expected)
        table.insert(deltaLog, {
          axis = "X", tileDelta = dtx,
          camDelta = dcx, expected = expected, pass = pass
        })
        console:log(string.format("[Delta] X: tile%+d -> cam%+d (expect %+d) %s",
          dtx, dcx, expected, pass and "PASS" or "FAIL"))
      end

      if dty ~= 0 then
        local expected = dty * -16
        local pass = (dcy == expected)
        table.insert(deltaLog, {
          axis = "Y", tileDelta = dty,
          camDelta = dcy, expected = expected, pass = pass
        })
        console:log(string.format("[Delta] Y: tile%+d -> cam%+d (expect %+d) %s",
          dty, dcy, expected, pass and "PASS" or "FAIL"))
      end

      -- Update reference
      refX, refY = px, py
      refCamX, refCamY = camX, camY
      phase = "ready"
    end
  end

  -- === DRAW ===
  painter:setBlend(false)
  painter:setFillColor(0x00000000)
  painter:drawRectangle(0, 0, 240, 160)
  painter:setBlend(true)

  local lineH = 12
  local lines = 5 + math.min(#deltaLog, 5)
  painter:setFillColor(0xCC000000)
  painter:drawRectangle(0, 0, 240, 4 + lines * lineH)

  local y = 1

  -- Line 1: Raw values
  painter:setFillColor(0xFFAAAAAA)
  painter:drawText(string.format("Tile:%d,%d  Cam:%d,%d  Map:%d:%d",
    px, py, camX, camY, mapG, mapI), 4, y)
  y = y + lineH

  -- Line 2: Current K
  local kx = px * 16 + camX
  local ky = py * 16 + camY
  painter:setFillColor(0xFFFFFF00)
  painter:drawText(string.format("K = tile*16+cam: X=%d  Y=%d", kx, ky), 4, y)
  y = y + lineH

  -- Line 3: K stability on this map
  local allSame = true
  if #kSamples >= 2 then
    local r = kSamples[1]
    for i = 2, #kSamples do
      if kSamples[i].kx ~= r.kx or kSamples[i].ky ~= r.ky then
        allSame = false
      end
    end
    painter:setFillColor(allSame and 0xFF00FF00 or 0xFFFF4444)
    painter:drawText(string.format("K stable on this map: %s (%d samples)",
      allSame and "YES" or "NO", #kSamples), 4, y)
  else
    painter:setFillColor(0xFF888888)
    painter:drawText("K stable: waiting for samples...", 4, y)
  end
  y = y + lineH

  -- Line 4: Delta summary
  local allPass = true
  local nDeltas = #deltaLog
  for _, d in ipairs(deltaLog) do
    if not d.pass then allPass = false end
  end

  if nDeltas == 0 then
    painter:setFillColor(0xFF888888)
    painter:drawText("Delta: walk to test...", 4, y)
  else
    painter:setFillColor(allPass and 0xFF00FF00 or 0xFFFF0000)
    painter:drawText(string.format("Delta: %d checks, %s",
      nDeltas, allPass and "ALL PASS" or "SOME FAIL"), 4, y)
  end
  y = y + lineH

  -- Delta details (last 5)
  local start = math.max(1, #deltaLog - 4)
  for i = start, #deltaLog do
    local d = deltaLog[i]
    painter:setFillColor(d.pass and 0xFF88FF88 or 0xFFFF4444)
    painter:drawText(string.format("  %s: tile%+d cam%+d (exp %+d) %s",
      d.axis, d.tileDelta, d.camDelta, d.expected,
      d.pass and "OK" or "FAIL"), 4, y)
    y = y + lineH
  end

  -- Verdict
  if nDeltas >= 2 then
    y = y + 4
    if allPass then
      painter:setFillColor(0xFF00FF00)
      painter:drawText("CAMERA OFFSETS CONFIRMED", 40, y)
    else
      painter:setFillColor(0xFFFF0000)
      painter:drawText("WRONG ADDRESS - DELTA MISMATCH", 30, y)
    end
  end

  -- Crosshair (self-calibrated per map using latest K)
  if #kSamples > 0 then
    local rk = kSamples[#kSamples]
    local chx = kx - rk.kx + 120
    local chy = ky - rk.ky + 80
    if chx >= 2 and chx < 238 and chy >= 2 and chy < 158 then
      painter:setFillColor(0x6000FF00)
      painter:drawRectangle(chx - 4, chy - 1, 9, 3)
      painter:drawRectangle(chx - 1, chy - 4, 3, 9)
    end
  end

  overlay:update()
end

console:log("=== Camera Verifier v3 ===")
console:log("Walk around on the SAME map.")
console:log("Key test: does cam change by ±16 per tile?")
console:log("")

initOverlay()
callbacks:add("frame", onFrame)
