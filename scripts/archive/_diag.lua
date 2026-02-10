-- Diagnostic: identify why --script doesn't produce output
-- Step 1: pure Lua file write (no mGBA API)
local marker = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_diag_step1.txt", "w")
if marker then
  marker:write("step1_ok\n")
  marker:close()
end

-- Step 2: check if mGBA APIs exist
local apis = {}
apis.console = type(console) ~= "nil"
apis.emu = type(emu) ~= "nil"
apis.callbacks = type(callbacks) ~= "nil"
apis.script = type(script) ~= "nil"
apis.script_dir = type(script) ~= "nil" and type(script.dir) ~= "nil"

local f2 = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_diag_step2.txt", "w")
if f2 then
  for k, v in pairs(apis) do
    f2:write(k .. " = " .. tostring(v) .. "\n")
  end
  if apis.script_dir then
    f2:write("script.dir = " .. tostring(script.dir) .. "\n")
  end
  f2:close()
end

-- Step 3: try mGBA console
if apis.console then
  console:log("DIAG: mGBA console works")
end

-- Step 4: try reading memory (needs ROM loaded)
if apis.emu then
  local ok, val = pcall(function() return emu.memory.wram:read8(0) end)
  local f4 = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_diag_step4.txt", "w")
  if f4 then
    f4:write("mem_read_ok = " .. tostring(ok) .. "\n")
    if ok then f4:write("value = " .. tostring(val) .. "\n") end
    f4:close()
  end
end

-- Step 5: try frame callback (delayed execution)
if apis.callbacks then
  local frameCb
  local count = 0
  frameCb = callbacks:add("frame", function()
    count = count + 1
    if count == 60 then
      frameCb:remove()
      local f5 = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_diag_step5.txt", "w")
      if f5 then
        f5:write("frame_callback_ok\n")
        f5:write("frames = " .. count .. "\n")
        -- try reading player X
        local ok2, px = pcall(function() return emu.memory.wram:read16(0x24CBC) end)
        f5:write("playerX_ok = " .. tostring(ok2) .. "\n")
        if ok2 then f5:write("playerX = " .. tostring(px) .. "\n") end
        f5:close()
      end
    end
  end)
end
