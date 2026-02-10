-- Minimal test to see if mGBA scripting works
console:log("[TEST] Script loaded!")

local count = 0
callbacks:add("frame", function()
  count = count + 1
  if count == 30 then
    console:log("[TEST] Taking screenshot at frame 30")
    -- Try both path formats
    local ok1, err1 = pcall(function() emu:screenshot("test_alive.png") end)
    console:log("[TEST] emu:screenshot result: " .. tostring(ok1) .. " " .. tostring(err1))
  end
end)
