--[[
  runner.lua — Test runner for mGBA autonomous test framework

  Usage:
    local Runner = require("runner")
    Runner.suite("name", function(t) ... end)
    Runner.run({ saveStateSlot=1, ... })

  Features:
    - Load save state + wait for stabilization
    - Run sync and async (multi-frame) test suites
    - Screenshots (explicit + on failure)
    - JSON results output
    - Frame callback driven (non-blocking)
]]

local Assertions = require("assertions")

local Runner = {}

-- Internal state
local suites = {}
local asyncSuites = {}
local config = {}
local results = {
  timestamp = "",
  saveState = false,
  duration_ms = 0,
  screenshots = {},
  suites = {},
  summary = { total = 0, passed = 0, failed = 0 },
  status = "pending"
}
local startTime = 0
local screenshotIndex = 0

-- Simple JSON encoder (handles nested tables, arrays, strings, numbers, bools, nil)
local function jsonEncode(val)
  local t = type(val)
  if val == nil then return "null"
  elseif t == "boolean" then return tostring(val)
  elseif t == "number" then
    if val ~= val then return "null" end -- NaN
    return tostring(val)
  elseif t == "string" then
    return '"' .. val:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n'):gsub('\r','\\r'):gsub('\t','\\t') .. '"'
  elseif t == "table" then
    -- Detect array vs object
    local isArray = false
    local n = #val
    if n > 0 then
      isArray = true
      for k, _ in pairs(val) do
        if type(k) ~= "number" or k < 1 or k > n or k ~= math.floor(k) then
          isArray = false
          break
        end
      end
    end
    if isArray then
      local parts = {}
      for i = 1, n do
        parts[i] = jsonEncode(val[i])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    else
      local parts = {}
      -- Sort keys for deterministic output
      local keys = {}
      for k in pairs(val) do keys[#keys+1] = k end
      table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
      for _, k in ipairs(keys) do
        parts[#parts+1] = '"' .. tostring(k) .. '":' .. jsonEncode(val[k])
      end
      return "{" .. table.concat(parts, ",") .. "}"
    end
  end
  return '"??"'
end

-- Take a screenshot and register it
local function takeScreenshot(name)
  screenshotIndex = screenshotIndex + 1
  local filename = string.format("%03d_%s.png", screenshotIndex, name:gsub("[^%w_]", "_"))
  local fullPath = config.screenshotDir .. "/" .. filename
  local ok = pcall(function() emu:screenshot(fullPath) end)
  if ok then
    results.screenshots[#results.screenshots+1] = filename
    console:log("[TEST] Screenshot: " .. filename)
  else
    console:log("[TEST] Screenshot FAILED: " .. filename)
  end
  return ok
end

-- Register a synchronous test suite
function Runner.suite(name, fn)
  suites[#suites+1] = { name = name, fn = fn }
end

-- Register an async (multi-frame) test suite
function Runner.asyncSuite(name, fn)
  asyncSuites[#asyncSuites+1] = { name = name, fn = fn }
end

-- Run a single sync suite, returns suite results
local function runSyncSuite(suite)
  local suiteResult = {
    name = suite.name,
    tests = {},
    passed = 0,
    failed = 0
  }

  local function addResult(testName, pass, details, value)
    local entry = {
      name = testName,
      pass = pass,
      details = details or "",
    }
    if value ~= nil and type(value) == "number" then
      entry.value = value
    end
    suiteResult.tests[#suiteResult.tests+1] = entry
    if pass then
      suiteResult.passed = suiteResult.passed + 1
      results.summary.passed = results.summary.passed + 1
    else
      suiteResult.failed = suiteResult.failed + 1
      results.summary.failed = results.summary.failed + 1
      -- Auto-screenshot on failure
      takeScreenshot("fail_" .. testName)
    end
    results.summary.total = results.summary.total + 1
  end

  local t = Assertions.create(addResult, takeScreenshot)

  -- Add test() wrapper for named sub-tests
  function t.test(testName, testFn)
    local ok, err = pcall(testFn)
    if not ok then
      addResult(testName, false, "ERROR: " .. tostring(err))
    end
  end

  local ok, err = pcall(suite.fn, t)
  if not ok then
    addResult(suite.name .. "_ERROR", false, "Suite error: " .. tostring(err))
  end

  return suiteResult
end

-- Write results to JSON file
local function writeResults()
  results.duration_ms = math.floor((os.clock() - startTime) * 1000)
  results.status = "complete"

  local json = jsonEncode(results)
  local f = io.open(config.resultsFile, "w")
  if f then
    f:write(json)
    f:close()
    console:log("[TEST] Results written to: " .. config.resultsFile)
  else
    console:log("[TEST] ERROR: Could not write results to: " .. config.resultsFile)
  end
end

-- Main run function
function Runner.run(opts)
  config = {
    saveStateSlot = opts.saveStateSlot or 1,
    stabilizationFrames = opts.stabilizationFrames or 120,
    screenshotDir = opts.screenshotDir or (script.dir .. "/../../test_screenshots"),
    resultsFile = opts.resultsFile or (script.dir .. "/../../test_results.json"),
  }

  startTime = os.clock()
  results.timestamp = os.date("%Y-%m-%d %H:%M:%S")

  -- Write initial status
  local f = io.open(config.resultsFile, "w")
  if f then
    f:write('{"status":"started","timestamp":"' .. results.timestamp .. '"}')
    f:close()
  end

  console:log("=== TEST RUNNER START ===")
  console:log("Save state slot: " .. config.saveStateSlot)
  console:log("Stabilization: " .. config.stabilizationFrames .. " frames")
  console:log("Sync suites: " .. #suites)
  console:log("Async suites: " .. #asyncSuites)

  -- Load save state
  local ssOk = pcall(function() emu:loadStateSlot(config.saveStateSlot) end)
  results.saveState = ssOk

  if not ssOk then
    console:log("[TEST] FAILED to load save state slot " .. config.saveStateSlot)
    results.status = "error"
    results.error = "save_state_load_failed"
    writeResults()
    return
  end

  console:log("[TEST] Save state loaded, waiting " .. config.stabilizationFrames .. " frames...")

  -- Wait for stabilization then run tests
  local frameCount = 0
  local stabilizeCb
  stabilizeCb = callbacks:add("frame", function()
    frameCount = frameCount + 1
    if frameCount < config.stabilizationFrames then return end
    stabilizeCb:remove()

    console:log("[TEST] Stabilization complete, running tests...")
    takeScreenshot("initial_state")

    -- Run all sync suites
    for _, suite in ipairs(suites) do
      console:log("[TEST] Suite: " .. suite.name)
      local suiteResult = runSyncSuite(suite)
      results.suites[#results.suites+1] = suiteResult
      console:log(string.format("[TEST]   %d passed, %d failed",
        suiteResult.passed, suiteResult.failed))
    end

    -- Run async suites (sequential, frame-driven)
    if #asyncSuites > 0 then
      local asyncIdx = 1
      local currentAsync = nil
      local asyncFrames = 0
      local asyncDone = false
      local asyncSuiteResult = nil

      local function startNextAsync()
        if asyncIdx > #asyncSuites then
          -- All async suites done
          takeScreenshot("final_state")
          writeResults()
          console:log(string.format("=== TEST RUNNER COMPLETE: %d/%d passed ===",
            results.summary.passed, results.summary.total))
          return true
        end

        local suite = asyncSuites[asyncIdx]
        console:log("[TEST] Async suite: " .. suite.name)
        asyncSuiteResult = {
          name = suite.name,
          tests = {},
          passed = 0,
          failed = 0
        }
        asyncDone = false
        asyncFrames = 0

        local function addResult(testName, pass, details, value)
          local entry = { name = testName, pass = pass, details = details or "" }
          if value ~= nil and type(value) == "number" then entry.value = value end
          asyncSuiteResult.tests[#asyncSuiteResult.tests+1] = entry
          if pass then
            asyncSuiteResult.passed = asyncSuiteResult.passed + 1
            results.summary.passed = results.summary.passed + 1
          else
            asyncSuiteResult.failed = asyncSuiteResult.failed + 1
            results.summary.failed = results.summary.failed + 1
            takeScreenshot("fail_" .. testName)
          end
          results.summary.total = results.summary.total + 1
        end

        local t = Assertions.create(addResult, takeScreenshot)
        function t.test(testName, testFn)
          local ok, err = pcall(testFn)
          if not ok then addResult(testName, false, "ERROR: " .. tostring(err)) end
        end

        -- waitFrames: schedule a callback after N frames
        local pendingWaits = {}
        function t.waitFrames(n, fn)
          pendingWaits[#pendingWaits+1] = { target = asyncFrames + n, fn = fn }
        end

        function t.done()
          asyncDone = true
        end

        local ok, err = pcall(suite.fn, t)
        if not ok then
          addResult(suite.name .. "_ERROR", false, "Suite error: " .. tostring(err))
          asyncDone = true
        end

        -- Store pendingWaits for frame processing
        currentAsync = { pendingWaits = pendingWaits, t = t }
        return false
      end

      startNextAsync()

      local asyncCb
      asyncCb = callbacks:add("frame", function()
        asyncFrames = asyncFrames + 1

        -- Process pending waits
        if currentAsync then
          local remaining = {}
          for _, w in ipairs(currentAsync.pendingWaits) do
            if asyncFrames >= w.target then
              local ok, err = pcall(w.fn)
              if not ok then
                console:log("[TEST] waitFrames callback error: " .. tostring(err))
              end
            else
              remaining[#remaining+1] = w
            end
          end
          currentAsync.pendingWaits = remaining
        end

        -- Timeout: 600 frames (10 sec) per async suite
        if asyncFrames > 600 then
          asyncDone = true
          console:log("[TEST] Async suite TIMEOUT after 600 frames")
        end

        if asyncDone then
          results.suites[#results.suites+1] = asyncSuiteResult
          console:log(string.format("[TEST]   %d passed, %d failed",
            asyncSuiteResult.passed, asyncSuiteResult.failed))
          asyncIdx = asyncIdx + 1
          local allDone = startNextAsync()
          if allDone then
            asyncCb:remove()
          end
        end
      end)
    else
      -- No async suites, finish now
      takeScreenshot("final_state")
      writeResults()
      console:log(string.format("=== TEST RUNNER COMPLETE: %d/%d passed ===",
        results.summary.passed, results.summary.total))
    end
  end)
end

return Runner
