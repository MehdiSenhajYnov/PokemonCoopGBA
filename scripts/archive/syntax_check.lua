-- Quick syntax check: try to load battle.lua
console:log("=== SYNTAX CHECK ===")

-- Set up package path
local projectDir = script.dir .. "/../.."
package.path = projectDir .. "/client/?.lua;" .. projectDir .. "/config/?.lua;" .. package.path

-- Try loading config first
local ok1, configOrErr = pcall(require, "run_and_bun")
if ok1 then
  console:log("OK: config/run_and_bun.lua loaded")
else
  console:log("FAIL: config/run_and_bun.lua: " .. tostring(configOrErr))
end

-- Try loading battle module
local ok2, battleOrErr = pcall(require, "battle")
if ok2 then
  console:log("OK: client/battle.lua loaded")
else
  console:log("FAIL: client/battle.lua: " .. tostring(battleOrErr))
end

-- Try loading hal module
local ok3, halOrErr = pcall(require, "hal")
if ok3 then
  console:log("OK: client/hal.lua loaded")
else
  console:log("FAIL: client/hal.lua: " .. tostring(halOrErr))
end

-- Write result to file
local f = io.open(projectDir .. "/syntax_check_done.txt", "w")
if f then
  f:write("config: " .. tostring(ok1) .. "\n")
  f:write("battle: " .. tostring(ok2) .. "\n")
  f:write("hal: " .. tostring(ok3) .. "\n")
  if not ok1 then f:write("config err: " .. tostring(configOrErr) .. "\n") end
  if not ok2 then f:write("battle err: " .. tostring(battleOrErr) .. "\n") end
  if not ok3 then f:write("hal err: " .. tostring(halOrErr) .. "\n") end
  f:close()
  console:log("Results written to syntax_check_done.txt")
end
