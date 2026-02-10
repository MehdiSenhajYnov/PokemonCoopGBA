--[[
  assertions.lua — Assertion library for mGBA test framework
  Provides assertEqual, assertRange, assertTrue, assertNotNil, screenshot helpers
]]

local Assertions = {}

-- Internal: format value for display
local function fmt(v)
  if v == nil then return "nil" end
  if type(v) == "number" then
    if v > 0xFFFF then return string.format("0x%08X", v) end
    if v > 0xFF then return string.format("0x%04X", v) end
    return tostring(v)
  end
  return tostring(v)
end

-- Create assertion context bound to a test result collector
function Assertions.create(addResult, screenshotFn)
  local ctx = {}

  function ctx.assertEqual(actual, expected, msg)
    local pass = (actual == expected)
    local details = fmt(actual) .. (pass and " == " or " != ") .. fmt(expected)
    addResult(msg or "assertEqual", pass, details, actual)
    return pass
  end

  function ctx.assertRange(actual, min, max, msg)
    local pass = (actual ~= nil and type(actual) == "number" and actual >= min and actual <= max)
    local details = fmt(actual) .. " in [" .. fmt(min) .. "," .. fmt(max) .. "]"
    addResult(msg or "assertRange", pass, details, actual)
    return pass
  end

  function ctx.assertTrue(condition, msg)
    local pass = (condition == true)
    addResult(msg or "assertTrue", pass, pass and "true" or "false", condition)
    return pass
  end

  function ctx.assertNotNil(value, msg)
    local pass = (value ~= nil)
    addResult(msg or "assertNotNil", pass, pass and fmt(value) or "nil", value)
    return pass
  end

  function ctx.assertBytes(data, minLen, msg)
    local pass = (data ~= nil and type(data) == "string" and #data >= minLen)
    local details = data and (#data .. " bytes") or "nil"
    addResult(msg or "assertBytes", pass, details, data and #data or nil)
    return pass
  end

  function ctx.screenshot(name)
    if screenshotFn then screenshotFn(name) end
  end

  return ctx
end

return Assertions
