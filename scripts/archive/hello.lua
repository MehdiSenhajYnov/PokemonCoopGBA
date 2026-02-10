-- Test mGBA script execution
local frameCount = 0

callbacks:add("frame", function()
  frameCount = frameCount + 1
  if frameCount == 30 then
    console:log("Frame 30 reached - taking screenshot")
    emu:screenshot("hello_world.png")
  end
  if frameCount == 60 then
    console:log("Frame 60 - trying to load battle.lua")

    -- Set up path
    local scriptPath = debug.getinfo(1, "S").source:sub(2)
    local scriptDir = scriptPath:match("(.*/)")
    if not scriptDir then scriptDir = scriptPath:match("(.*\\)") end
    if scriptDir then
      package.path = package.path .. ";" .. scriptDir .. "../client/?.lua"
      package.path = package.path .. ";" .. scriptDir .. "../config/?.lua"
      package.path = package.path .. ";" .. scriptDir .. "../?.lua"
    end

    local ok, err = pcall(require, "battle")
    if ok then
      console:log("PASS: battle.lua loaded OK")
      emu:screenshot("battle_load_PASS.png")
    else
      console:log("FAIL: " .. tostring(err))
      emu:screenshot("battle_load_FAIL.png")
    end
  end
end)
