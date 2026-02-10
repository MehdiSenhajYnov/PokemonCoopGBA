-- Diagnostic: test package path from run_all.lua perspective
console:log("[DIAG2] Starting")

local testingDir = script.dir
local projectDir = testingDir .. "/../.."

console:log("[DIAG2] script.dir = " .. tostring(testingDir))
console:log("[DIAG2] projectDir = " .. tostring(projectDir))

package.path = testingDir .. "/?.lua;" .. testingDir .. "/suites/?.lua;" .. package.path

console:log("[DIAG2] package.path = " .. package.path)

local f = io.open("diag_result2.txt", "w")
if f then
  f:write("script.dir=" .. tostring(testingDir) .. "\n")
  f:write("projectDir=" .. tostring(projectDir) .. "\n")
  f:write("package.path=" .. package.path .. "\n")
end

-- Try to load runner
local ok1, Runner = pcall(require, "runner")
console:log("[DIAG2] runner: " .. tostring(ok1))
if f then f:write("runner=" .. tostring(ok1) .. "\n") end
if not ok1 then
  console:log("[DIAG2] runner err: " .. tostring(Runner))
  if f then f:write("runner_err=" .. tostring(Runner) .. "\n") end
end

-- Try to load suites
local suiteNames = {"memory", "rom_patches", "warp", "network", "battle"}
for _, name in ipairs(suiteNames) do
  local ok, err = pcall(require, name)
  console:log("[DIAG2] suite " .. name .. ": " .. tostring(ok))
  if f then f:write("suite_" .. name .. "=" .. tostring(ok) .. (ok and "" or ("_err=" .. tostring(err))) .. "\n") end
end

if f then
  f:write("step=DONE\n")
  f:close()
end

console:log("[DIAG2] ALL DONE - check diag_result2.txt")
