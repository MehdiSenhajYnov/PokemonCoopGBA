-- Diagnostic: test if framework loads
console:log("[DIAG] Starting diagnostic test")

local f = io.open("diag_result.txt", "w")
if f then
  f:write("step=0_start\n")
  f:close()
end

console:log("[DIAG] Step 1: require runner")
local ok1, Runner = pcall(function() return require("runner") end)
console:log("[DIAG] Runner loaded: " .. tostring(ok1))

f = io.open("diag_result.txt", "w")
if f then
  f:write("step=1_runner_loaded=" .. tostring(ok1) .. "\n")
  f:close()
end

if not ok1 then
  console:log("[DIAG] Runner error: " .. tostring(Runner))
  f = io.open("diag_result.txt", "w")
  if f then f:write("step=1_error=" .. tostring(Runner) .. "\n"); f:close() end
  return
end

console:log("[DIAG] Step 2: require suites")
local suiteNames = {"memory", "rom_patches", "warp", "network", "battle"}
for _, name in ipairs(suiteNames) do
  local ok, err = pcall(function() require(name) end)
  console:log("[DIAG] Suite " .. name .. ": " .. tostring(ok) .. (ok and "" or (" ERR=" .. tostring(err))))
  f = io.open("diag_result.txt", "a")
  if f then
    f:write("suite_" .. name .. "=" .. tostring(ok) .. (ok and "" or ("_err=" .. tostring(err))) .. "\n")
    f:close()
  end
end

console:log("[DIAG] Step 3: try loadStateSlot")
local ok3, err3 = pcall(function() emu:loadStateSlot(1) end)
console:log("[DIAG] loadStateSlot(1): " .. tostring(ok3) .. (ok3 and "" or (" ERR=" .. tostring(err3))))
f = io.open("diag_result.txt", "a")
if f then
  f:write("loadStateSlot=" .. tostring(ok3) .. (ok3 and "" or ("_err=" .. tostring(err3))) .. "\n")
  f:close()
end

console:log("[DIAG] Step 4: try screenshot")
local ok4, err4 = pcall(function() emu:screenshot("diag_screenshot.png") end)
console:log("[DIAG] screenshot: " .. tostring(ok4) .. (ok4 and "" or (" ERR=" .. tostring(err4))))
f = io.open("diag_result.txt", "a")
if f then
  f:write("screenshot=" .. tostring(ok4) .. (ok4 and "" or ("_err=" .. tostring(err4))) .. "\n")
  f:write("step=DONE\n")
  f:close()
end

console:log("[DIAG] ALL DONE")
