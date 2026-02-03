--[[
  Auto Camera Offset Scanner

  Finds gSpriteCoordOffsetX/Y in IWRAM automatically.

  USAGE:
    1. Load this script in mGBA (Tools > Scripting > Load)
    2. Walk around in-game (any direction, any distance)
    3. Wait for "FOUND!" message

  That's it. The script detects your movements and narrows down
  candidates automatically. Usually takes 3-5 movements per axis.

  HOW IT WORKS:
    - Uses known Run & Bun player position offsets to detect tile changes
    - Snapshots all IWRAM 16-bit values when you're standing still
    - After you move N tiles, finds values that changed by N * 16
    - Intersects results across movements until 1 candidate remains
]]

-- === CONFIGURATION ===
-- Change these if using a different ROM profile

-- Run & Bun player offsets (relative to EWRAM base 0x02000000)
local PLAYER_X_OFFSET = 0x00024CBC
local PLAYER_Y_OFFSET = 0x00024CBE

-- How many stable frames before considering "stopped" (~0.33s at 60fps)
local STABLE_THRESHOLD = 20

-- === IWRAM CONSTANTS ===
local IWRAM_SIZE = 0x8000  -- 32KB (0x03000000 - 0x03007FFF)

-- === STATE ===
local S = {
  phase       = "init",     -- init | ready | moving
  snapshot    = {},         -- IWRAM offset -> u16 value
  lastX       = 0,
  lastY       = 0,
  moveStartX  = 0,
  moveStartY  = 0,
  stableCount = 0,
  xCandidates = nil,        -- nil = no scan yet, table = set of offsets
  yCandidates = nil,
  xScans      = 0,
  yScans      = 0,
  moves       = 0,
  done        = false,
  foundX      = nil,        -- final IWRAM offset for camera X
  foundY      = nil,        -- final IWRAM offset for camera Y
  statusText  = "Loading..."
}

-- === OVERLAY ===
local overlay = nil
local painter = nil

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

local function drawOverlay()
  if not painter or not overlay then return end

  painter:setBlend(false)
  painter:setFillColor(0x00000000)
  painter:drawRectangle(0, 0, 240, 160)
  painter:setBlend(true)

  -- Background
  local barH = S.done and 40 or 52
  painter:setFillColor(0xCC000000)
  painter:drawRectangle(0, 0, 240, barH)

  -- Title + status
  painter:setFillColor(0xFF00FFFF)
  painter:drawText("CAMERA SCANNER", 4, 1)
  painter:setFillColor(0xFFFFFF00)
  painter:drawText(S.statusText, 110, 1)

  if S.done then
    -- Show final results
    painter:setFillColor(0xFF00FF00)
    painter:drawText(string.format("CameraX: IWRAM+0x%04X  (0x%08X)",
      S.foundX, 0x03000000 + S.foundX), 4, 14)
    painter:drawText(string.format("CameraY: IWRAM+0x%04X  (0x%08X)",
      S.foundY, 0x03000000 + S.foundY), 4, 26)
  else
    -- Progress
    local xN = S.xCandidates and countSet(S.xCandidates) or -1
    local yN = S.yCandidates and countSet(S.yCandidates) or -1
    painter:setFillColor(0xFFFFFFFF)
    painter:drawText(string.format("Pos: %d,%d   Moves: %d", S.lastX, S.lastY, S.moves), 4, 13)

    painter:setFillColor(xN <= 3 and xN > 0 and 0xFF00FF00 or 0xFFFF8800)
    painter:drawText(string.format("X: %s candidates (%d scans)",
      xN < 0 and "?" or tostring(xN), S.xScans), 4, 25)

    painter:setFillColor(yN <= 3 and yN > 0 and 0xFF00FF00 or 0xFFFF8800)
    painter:drawText(string.format("Y: %s candidates (%d scans)",
      yN < 0 and "?" or tostring(yN), S.yScans), 4, 37)

    -- Show top candidates if few
    if xN > 0 and xN <= 3 then
      painter:setFillColor(0xFF88FF88)
      painter:drawText("  X -> " .. formatCandidates(S.xCandidates), 4, 49)
    end
  end

  overlay:update()
end

-- === HELPERS ===

function countSet(s)
  if not s then return 0 end
  local n = 0
  for _ in pairs(s) do n = n + 1 end
  return n
end

function sortedKeys(s)
  local t = {}
  for k in pairs(s) do t[#t + 1] = k end
  table.sort(t)
  return t
end

function formatCandidates(s)
  local keys = sortedKeys(s)
  local parts = {}
  for i = 1, math.min(#keys, 4) do
    local o = keys[i]
    local ok, v = pcall(function() return emu.memory.iwram:read16(o) end)
    if ok then
      if v > 32767 then v = v - 65536 end
      parts[#parts + 1] = string.format("0x%04X(%d)", o, v)
    end
  end
  return table.concat(parts, " ")
end

-- Read player tile position from known offsets
local function readPos()
  local okx, x = pcall(function() return emu.memory.wram:read16(PLAYER_X_OFFSET) end)
  local oky, y = pcall(function() return emu.memory.wram:read16(PLAYER_Y_OFFSET) end)
  if okx and oky then return x, y end
  return nil, nil
end

-- Snapshot all 16-bit values in IWRAM
local function takeSnapshot()
  local snap = {}
  for off = 0, IWRAM_SIZE - 2, 2 do
    local ok, v = pcall(function() return emu.memory.iwram:read16(off) end)
    if ok then snap[off] = v end
  end
  return snap
end

-- Find offsets where value changed by exactly `delta` since snapshot
local function findDelta(snap, delta)
  local hits = {}
  for off, oldVal in pairs(snap) do
    local ok, newVal = pcall(function() return emu.memory.iwram:read16(off) end)
    if ok then
      local diff = newVal - oldVal
      if diff > 32767 then diff = diff - 65536 end
      if diff < -32768 then diff = diff + 65536 end
      if diff == delta then
        hits[off] = true
      end
    end
  end
  return hits
end

-- Intersect: keep only offsets present in both sets
local function intersect(a, b)
  if a == nil then return b end
  local result = {}
  for off in pairs(a) do
    if b[off] then result[off] = true end
  end
  return result
end

-- === ANALYSIS ===

local function analyze()
  local dx = S.lastX - S.moveStartX
  local dy = S.lastY - S.moveStartY
  S.moves = S.moves + 1

  -- Analyze X movement
  if dx ~= 0 then
    local delta = dx * -16
    local hits = findDelta(S.snapshot, delta)
    S.xCandidates = intersect(S.xCandidates, hits)
    S.xScans = S.xScans + 1

    local n = countSet(S.xCandidates)
    console:log(string.format("[Scan] X: moved %+d tiles, delta=%d, hits=%d, remaining=%d",
      dx, delta, countSet(hits), n))

    if n > 0 and n <= 3 then
      for _, o in ipairs(sortedKeys(S.xCandidates)) do
        console:log(string.format("  -> X candidate: IWRAM+0x%04X (0x%08X)", o, 0x03000000 + o))
      end
    end

    if n == 0 then
      console:log("[Scan] X: zero candidates, resetting scan")
      S.xCandidates = nil
      S.xScans = 0
    end
  end

  -- Analyze Y movement
  if dy ~= 0 then
    local delta = dy * -16
    local hits = findDelta(S.snapshot, delta)
    S.yCandidates = intersect(S.yCandidates, hits)
    S.yScans = S.yScans + 1

    local n = countSet(S.yCandidates)
    console:log(string.format("[Scan] Y: moved %+d tiles, delta=%d, hits=%d, remaining=%d",
      dy, delta, countSet(hits), n))

    if n > 0 and n <= 3 then
      for _, o in ipairs(sortedKeys(S.yCandidates)) do
        console:log(string.format("  -> Y candidate: IWRAM+0x%04X (0x%08X)", o, 0x03000000 + o))
      end
    end

    if n == 0 then
      console:log("[Scan] Y: zero candidates, resetting scan")
      S.yCandidates = nil
      S.yScans = 0
    end
  end

  -- Check if done
  local xN = countSet(S.xCandidates)
  local yN = countSet(S.yCandidates)

  if xN == 1 and yN == 1 then
    S.foundX = sortedKeys(S.xCandidates)[1]
    S.foundY = sortedKeys(S.yCandidates)[1]
    S.done = true
    S.statusText = "FOUND!"

    console:log("============================================")
    console:log("CAMERA OFFSETS FOUND!")
    console:log(string.format("  CameraX: IWRAM+0x%04X  (full: 0x%08X)", S.foundX, 0x03000000 + S.foundX))
    console:log(string.format("  CameraY: IWRAM+0x%04X  (full: 0x%08X)", S.foundY, 0x03000000 + S.foundY))
    console:log("")
    console:log("Add these to config/run_and_bun.lua:")
    console:log(string.format("  cameraX = 0x%08X,  -- IWRAM, s16", 0x03000000 + S.foundX))
    console:log(string.format("  cameraY = 0x%08X,  -- IWRAM, s16", 0x03000000 + S.foundY))
    console:log("============================================")
  else
    S.statusText = string.format("X:%s Y:%s",
      xN == 0 and "?" or tostring(xN),
      yN == 0 and "?" or tostring(yN))
  end

  -- Fresh snapshot for next movement
  S.snapshot = takeSnapshot()
  S.phase = "ready"
end

-- === MAIN FRAME CALLBACK ===

local function onFrame()
  local x, y = readPos()
  if not x then return end

  -- Init: wait until player is stable
  if S.phase == "init" then
    S.lastX = x
    S.lastY = y
    S.stableCount = S.stableCount + 1
    S.statusText = "Stand still..."
    if S.stableCount >= STABLE_THRESHOLD then
      S.snapshot = takeSnapshot()
      S.phase = "ready"
      S.statusText = "Walk around!"
      console:log("[Scan] Ready. Walk in any direction.")
    end
    drawOverlay()
    return
  end

  -- Already done - just show results
  if S.done then
    drawOverlay()
    return
  end

  -- Detect movement
  local moved = (x ~= S.lastX or y ~= S.lastY)

  if moved then
    if S.phase == "ready" then
      S.phase = "moving"
      S.moveStartX = S.lastX
      S.moveStartY = S.lastY
    end
    S.stableCount = 0
    S.lastX = x
    S.lastY = y
    S.statusText = "Moving..."
  else
    S.stableCount = S.stableCount + 1
  end

  -- Settled after movement -> analyze
  if S.phase == "moving" and S.stableCount >= STABLE_THRESHOLD then
    S.statusText = "Analyzing..."
    analyze()
  end

  drawOverlay()
end

-- === STARTUP ===

console:log("============================================")
console:log("  Camera Offset Auto-Scanner v1.0")
console:log("============================================")
console:log("")

-- Test IWRAM access
local testOk, testVal = pcall(function() return emu.memory.iwram:read16(0) end)
if not testOk then
  console:log("ERROR: Cannot read IWRAM!")
  console:log("  emu.memory.iwram not available in this mGBA build.")
  console:log("  Requires mGBA 0.11+ dev build.")
else
  console:log("IWRAM access: OK")
  console:log("")
  console:log("Instructions:")
  console:log("  1. Stand still for 1 second (snapshot)")
  console:log("  2. Walk around (any direction, any distance)")
  console:log("  3. Stop, walk again in a different direction")
  console:log("  4. Repeat until FOUND! (usually 3-5 moves per axis)")
  console:log("")
  console:log("Tips:")
  console:log("  - Move horizontally AND vertically")
  console:log("  - Wait until fully stopped between moves")
  console:log("  - Different distances help narrow down faster")
  console:log("")

  initOverlay()
  callbacks:add("frame", onFrame)
end
