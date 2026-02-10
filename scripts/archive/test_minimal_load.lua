console:log("Step 1: script started")
pcall(function() emu:screenshot("test_step1.png") end)

console:log("Step 2: setting up path")
local scriptPath = debug.getinfo(1, "S").source:sub(2)
local scriptDir = scriptPath:match("(.*/)")
if not scriptDir then scriptDir = scriptPath:match("(.*\\)") end
if scriptDir then
  package.path = package.path .. ";" .. scriptDir .. "../client/?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../config/?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../?.lua"
end

console:log("Step 3: trying require battle")
local ok, err = pcall(require, "battle")
console:log("Step 4: require returned: " .. tostring(ok))
if not ok then
  console:log("ERROR: " .. tostring(err))
end

pcall(function() emu:screenshot("test_step4.png") end)
console:log("Step 5: done")
