-- Minimal test to verify mGBA scripting works
console:log("[TEST] Script loaded successfully!")
console:log("[TEST] Attempting screenshot...")

local frameCount = 0
callbacks:add("frame", function()
  frameCount = frameCount + 1
  if frameCount == 30 then
    console:log("[TEST] Frame 30 reached, taking screenshot...")
    pcall(function()
      emu:screenshot("test_script_works.png")
    end)
    console:log("[TEST] Screenshot attempted")
  end
  if frameCount == 60 then
    console:log("[TEST] Frame 60, trying io.open...")
    pcall(function()
      local f = io.open("test_script_works.txt", "w")
      if f then
        f:write("Script works! Frame 60 reached.\n")
        f:close()
        console:log("[TEST] File written!")
      else
        console:log("[TEST] io.open returned nil")
      end
    end)
  end
end)
