-- Wrapper that catches and reports errors from run_battle_test.lua
console:log("[WRAPPER] Loading run_battle_test.lua...")

local ok, err = pcall(function()
  dofile("scripts/ToUse/run_battle_test.lua")
end)

if not ok then
  console:log("[WRAPPER] ERROR: " .. tostring(err))
  -- Try to write error to file
  pcall(function()
    local f = io.open("battle_test_error.txt", "w")
    if f then
      f:write("ERROR: " .. tostring(err) .. "\n")
      f:close()
    end
  end)
end
