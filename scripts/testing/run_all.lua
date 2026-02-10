--[[
  run_all.lua — Entry point for the autonomous test framework

  Launch with:
    mGBA.exe --script scripts/testing/run_all.lua "rom/Pokemon RunBun.gba"

  Loads runner + all test suites + executes.
  Results written to test_results.json, screenshots to test_screenshots/
]]

-- Set up package path to find our modules
local testingDir = script.dir
local projectDir = testingDir .. "/../.."

package.path = testingDir .. "/?.lua;" .. testingDir .. "/suites/?.lua;" .. package.path

-- Load the runner
local Runner = require("runner")

-- Load all test suites (each registers itself via Runner.suite/Runner.asyncSuite)
require("memory")
require("rom_patches")
require("warp")
require("network")

-- Battle suite is loaded but the async battle_trigger test is commented out
-- by default since it modifies game state. Uncomment in suites/battle.lua to enable.
require("battle")

console:log("=== AUTONOMOUS TEST FRAMEWORK ===")
console:log("Project dir: " .. projectDir)
console:log("Testing dir: " .. testingDir)

-- Run all registered suites
Runner.run({
  saveStateSlot = 1,
  stabilizationFrames = 120,
  screenshotDir = projectDir .. "/test_screenshots",
  resultsFile = projectDir .. "/test_results.json",
})
