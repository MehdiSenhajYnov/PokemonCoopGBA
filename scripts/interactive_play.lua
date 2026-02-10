--[[
  interactive_play.lua — Interactive play puppet for Claude Code

  This script runs in mGBA and:
  1. Takes screenshots at regular intervals, saving to screenshots/
  2. Reads a command file (play_commands.txt) for input injection
  3. Writes game state to play_state.txt for external analysis

  Command file format (one command per line):
    press A          — press A button for 1 frame
    press B          — press B button for 1 frame
    press UP         — press Up for 1 frame
    press DOWN       — press Down for 1 frame
    press LEFT       — press Left for 1 frame
    press RIGHT      — press Right for 1 frame
    press START      — press Start for 1 frame
    press SELECT     — press Select for 1 frame
    hold A 30        — hold A for 30 frames
    hold UP 60       — hold Up for 60 frames
    release          — release all buttons
    screenshot       — take an extra screenshot immediately
    wait 60          — do nothing for 60 frames
    quit             — stop the script
]]

-- Configuration
local SCREENSHOT_INTERVAL = 90  -- Take screenshot every 90 frames (~1.5 sec)
local COMMAND_FILE = "play_commands.txt"
local STATE_FILE = "play_state.txt"
local SCREENSHOT_DIR = "play_screenshots"

-- Button code map
local BUTTONS = {
  A = 0, B = 1, SELECT = 2, START = 3,
  RIGHT = 4, LEFT = 5, UP = 6, DOWN = 7,
  R = 8, L = 9
}

-- State
local frameCount = 0
local screenshotCount = 0
local lastCommandLine = 0
local holdButton = nil
local holdFramesLeft = 0
local waitFramesLeft = 0
local running = true
local commandQueue = {}

-- Ensure screenshot directory exists (best effort)
os.execute('mkdir "' .. SCREENSHOT_DIR .. '" 2>nul')

-- Write state file
local function writeState(extra)
  local f = io.open(STATE_FILE, "w")
  if not f then return end

  f:write("frame=" .. frameCount .. "\n")
  f:write("screenshot_count=" .. screenshotCount .. "\n")
  f:write("running=" .. tostring(running) .. "\n")

  -- Read some game state
  local ok1, px = pcall(function() return emu.memory.wram:read16(0x24CBC) end)
  local ok2, py = pcall(function() return emu.memory.wram:read16(0x24CBE) end)
  local ok3, mapG = pcall(function() return emu.memory.wram:read8(0x24CC0) end)
  local ok4, mapI = pcall(function() return emu.memory.wram:read8(0x24CC1) end)
  local ok5, cb2 = pcall(function() return emu.memory.iwram:read32(0x22C4) end)
  local ok6, inBattle = pcall(function() return emu.memory.iwram:read8(0x2AF9) end)

  if ok1 then f:write("playerX=" .. px .. "\n") end
  if ok2 then f:write("playerY=" .. py .. "\n") end
  if ok3 then f:write("mapGroup=" .. mapG .. "\n") end
  if ok4 then f:write("mapId=" .. mapI .. "\n") end
  if ok5 then f:write("callback2=0x" .. string.format("%08X", cb2) .. "\n") end
  if ok6 then f:write("inBattle=" .. ((inBattle & 0x02) ~= 0 and "true" or "false") .. "\n") end

  if extra then f:write(extra .. "\n") end

  f:close()
end

-- Take a screenshot
local function takeScreenshot(label)
  screenshotCount = screenshotCount + 1
  local filename = string.format("%s/frame_%05d_%03d%s.png",
    SCREENSHOT_DIR, frameCount, screenshotCount,
    label and ("_" .. label) or "")

  local ok = pcall(function()
    local img = emu:screenshot()
    if img then
      img:savePNG(filename)
    end
  end)

  if ok then
    console:log("[PLAY] Screenshot #" .. screenshotCount .. ": " .. filename)
  end

  return filename
end

-- Read and parse command file
local function readCommands()
  local f = io.open(COMMAND_FILE, "r")
  if not f then return end

  local lineNum = 0
  for line in f:lines() do
    lineNum = lineNum + 1
    if lineNum > lastCommandLine then
      line = line:match("^%s*(.-)%s*$")  -- trim
      if line ~= "" and line:sub(1,1) ~= "#" then
        table.insert(commandQueue, line)
      end
    end
  end
  lastCommandLine = lineNum
  f:close()
end

-- Process a single command
local function processCommand(cmd)
  local parts = {}
  for word in cmd:gmatch("%S+") do
    table.insert(parts, word:upper())
  end

  if #parts == 0 then return end

  local action = parts[1]

  if action == "PRESS" and parts[2] then
    local btnCode = BUTTONS[parts[2]]
    if btnCode ~= nil then
      pcall(function() emu:addKey(btnCode) end)
      -- Auto-release next frame
      holdButton = btnCode
      holdFramesLeft = tonumber(parts[3]) or 2
      console:log("[PLAY] Press " .. parts[2])
    end

  elseif action == "HOLD" and parts[2] then
    local btnCode = BUTTONS[parts[2]]
    local frames = tonumber(parts[3]) or 30
    if btnCode ~= nil then
      holdButton = btnCode
      holdFramesLeft = frames
      pcall(function() emu:addKey(btnCode) end)
      console:log("[PLAY] Hold " .. parts[2] .. " for " .. frames .. "f")
    end

  elseif action == "RELEASE" then
    for _, code in pairs(BUTTONS) do
      pcall(function() emu:clearKey(code) end)
    end
    holdButton = nil
    holdFramesLeft = 0
    console:log("[PLAY] Release all")

  elseif action == "SCREENSHOT" then
    takeScreenshot("manual")

  elseif action == "WAIT" then
    waitFramesLeft = tonumber(parts[2]) or 60
    console:log("[PLAY] Wait " .. waitFramesLeft .. "f")

  elseif action == "QUIT" then
    running = false
    console:log("[PLAY] Quit requested")

  else
    console:log("[PLAY] Unknown command: " .. cmd)
  end
end

-- Clear command file to signal we've processed everything
local function clearCommandFile()
  local f = io.open(COMMAND_FILE, "w")
  if f then
    f:write("# Commands processed. Write new commands here.\n")
    f:close()
  end
end

console:log("[PLAY] Interactive play puppet started")
console:log("[PLAY] Screenshot interval: " .. SCREENSHOT_INTERVAL .. " frames")
console:log("[PLAY] Command file: " .. COMMAND_FILE)

-- Initialize command file
clearCommandFile()

-- Take initial screenshot
takeScreenshot("start")
writeState()

-- Main frame callback
callbacks:add("frame", function()
  if not running then return end

  frameCount = frameCount + 1

  -- Handle button hold
  if holdButton and holdFramesLeft > 0 then
    holdFramesLeft = holdFramesLeft - 1
    if holdFramesLeft <= 0 then
      pcall(function() emu:clearKey(holdButton) end)
      holdButton = nil
    end
  end

  -- Handle wait
  if waitFramesLeft > 0 then
    waitFramesLeft = waitFramesLeft - 1
    return  -- Don't process commands or take screenshots while waiting
  end

  -- Read commands every 30 frames
  if frameCount % 30 == 0 then
    readCommands()
  end

  -- Process one command per frame
  if #commandQueue > 0 then
    local cmd = table.remove(commandQueue, 1)
    processCommand(cmd)
  end

  -- Periodic screenshots
  if frameCount % SCREENSHOT_INTERVAL == 0 then
    takeScreenshot()
    writeState()
  end
end)
