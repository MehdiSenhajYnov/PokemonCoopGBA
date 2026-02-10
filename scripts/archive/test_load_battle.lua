-- Test: verify battle.lua loads without syntax errors
-- Uses mGBA's console:log for output and screenshot for visual confirm

-- Setup package path
local scriptPath = debug.getinfo(1, "S").source:sub(2)
local scriptDir = scriptPath:match("(.*/)")
if not scriptDir then scriptDir = scriptPath:match("(.*\\)") end
if scriptDir then
  package.path = package.path .. ";" .. scriptDir .. "?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../client/?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../config/?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../?.lua"
end

console:log("=== battle.lua load test ===")

-- Try loading battle module
local ok, result = pcall(require, "battle")
if ok then
  console:log("PASS: battle.lua loaded successfully")
  console:log("Type: " .. type(result))
else
  console:log("FAIL: " .. tostring(result))
end

-- Try loading hal module
local ok2, result2 = pcall(require, "hal")
if ok2 then
  console:log("PASS: hal.lua loaded successfully")
else
  console:log("FAIL hal: " .. tostring(result2))
end

-- Write test result as screenshot filename
local msg = ok and "PASS" or "FAIL"
pcall(function()
  emu:screenshot("battle_load_" .. msg .. ".png")
end)

-- Write results to global for debugging
_G._testResult = { battle = ok, hal = ok2, error = not ok and tostring(result) or nil }

console:log("=== Test complete: " .. msg .. " ===")
