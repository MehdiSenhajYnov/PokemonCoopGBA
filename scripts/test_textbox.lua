--[[
  Standalone test for native GBA textbox via PokéScript injection.
  Run with: mGBA.exe -t "save.ss1" --script "scripts/test_textbox.lua" "rom.gba"

  Tests:
  1. Shows a Yes/No prompt: "Test textbox?\nSelect Yes or No."
  2. Polls VAR_RESULT until player selects
  3. Shows a blocking message with the result
  4. Polls VAR_0x8001 until dismissed
  5. Logs success
]]

-- Add paths
local scriptPath = debug.getinfo(1, "S").source:sub(2)
local scriptDir = scriptPath:match("(.*/)")
if not scriptDir then scriptDir = scriptPath:match("(.*\\)") end
if scriptDir then
  package.path = package.path .. ";" .. scriptDir .. "../client/?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../config/?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../?.lua"
end

local Textbox = require("textbox")

-- Load config
local config = dofile(scriptDir .. "../config/run_and_bun.lua")

console:log("[TestTextbox] Initializing...")
local ok = Textbox.init(config)
console:log("[TestTextbox] init: " .. tostring(ok))
console:log("[TestTextbox] configured: " .. tostring(Textbox.isConfigured()))

if not Textbox.isConfigured() then
  console:log("[TestTextbox] ERROR: Textbox not configured! Check battle_link addresses.")
  return
end

-- State machine
local phase = "start"
local frameCount = 0
local DELAY_FRAMES = 60  -- Wait 1 second for game to be ready

callbacks:add("frame", function()
  frameCount = frameCount + 1
  Textbox.tick(frameCount)

  if phase == "start" then
    if frameCount >= DELAY_FRAMES then
      console:log("[TestTextbox] Showing Yes/No prompt...")
      local shown = Textbox.showYesNo("Test textbox?\\nSelect Yes or No.")
      if shown then
        phase = "polling_yesno"
        console:log("[TestTextbox] Yes/No prompt triggered, polling...")
      else
        console:log("[TestTextbox] ERROR: showYesNo failed!")
        phase = "done"
      end
    end

  elseif phase == "polling_yesno" then
    local result = Textbox.pollYesNo()
    if result ~= nil then
      local answer = result and "Yes" or "No"
      console:log("[TestTextbox] Player selected: " .. answer)
      -- Show result message
      local msg = "You chose " .. answer .. "!"
      console:log("[TestTextbox] Showing message: " .. msg)
      Textbox.showMessage(msg)
      phase = "polling_message"
    end

  elseif phase == "polling_message" then
    local dismissed = Textbox.pollMessage()
    if dismissed then
      console:log("[TestTextbox] Message dismissed!")
      console:log("[TestTextbox] ===== TEST PASSED =====")
      phase = "done"
    end

  elseif phase == "done" then
    -- Nothing
  end
end)

console:log("[TestTextbox] Script loaded. Waiting " .. DELAY_FRAMES .. " frames before test...")
