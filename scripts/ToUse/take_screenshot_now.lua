-- Take a screenshot and save to file
-- Run via: mGBA --script scripts/ToUse/take_screenshot_now.lua "rom/..."

local frameCount = 0

callbacks:add("frame", function()
  frameCount = frameCount + 1
  if frameCount == 5 then
    -- Take screenshot
    local ok, err = pcall(function()
      local img = emu:screenshot()
      if img then
        img:savePNG("buffer_relay_test_screenshot.png")
        console:log("Screenshot saved!")
      end
    end)
    if not ok then
      console:log("Screenshot error: " .. tostring(err))
    end
  end
  if frameCount >= 10 then
    -- Exit
    console:log("Done, exiting")
  end
end)
