-- Syntax check for battle.lua rewrite
-- Run via: mGBA.exe --script scripts/ToUse/syntax_check_battle.lua "rom/Pokemon RunBun.gba"

local scriptPath = debug.getinfo(1, "S").source:sub(2)
local scriptDir = scriptPath:match("(.*/)")
if not scriptDir then scriptDir = scriptPath:match("(.*\\)") end

-- Add client dir to path
if scriptDir then
  local clientDir = scriptDir .. "../../client/"
  package.path = package.path .. ";" .. clientDir .. "?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../../?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../../config/?.lua"
end

console:log("=== SYNTAX CHECK: battle.lua ===")

-- Try loading battle module
local ok, err = pcall(function()
  local Battle = require("battle")
  console:log("battle.lua loaded OK")

  -- Check key functions exist
  assert(Battle.init, "Battle.init missing")
  assert(Battle.startLinkBattle, "Battle.startLinkBattle missing")
  assert(Battle.tick, "Battle.tick missing")
  assert(Battle.reset, "Battle.reset missing")
  assert(Battle.isActive, "Battle.isActive missing")
  assert(Battle.isFinished, "Battle.isFinished missing")
  assert(Battle.onRemoteBuffer, "Battle.onRemoteBuffer missing")
  assert(Battle.onRemoteStage, "Battle.onRemoteStage missing")
  assert(Battle.applyPatches, "Battle.applyPatches missing")
  assert(Battle.restorePatches, "Battle.restorePatches missing")
  assert(Battle.readLocalParty, "Battle.readLocalParty missing")
  assert(Battle.injectEnemyParty, "Battle.injectEnemyParty missing")
  assert(Battle.getOutcome, "Battle.getOutcome missing")
  assert(Battle.getOriginPos, "Battle.getOriginPos missing")
  assert(Battle.STAGE, "Battle.STAGE missing")
  assert(Battle.setSendFn, "Battle.setSendFn missing")
  assert(Battle.onRemoteChoice, "Battle.onRemoteChoice missing (legacy stub)")
  assert(Battle.setAutoFight, "Battle.setAutoFight missing (legacy stub)")
  assert(Battle.stopPvPSync, "Battle.stopPvPSync missing (legacy stub)")

  console:log("All function checks passed!")
end)

if not ok then
  console:log("ERROR: " .. tostring(err))
end

-- Also try loading main.lua dependencies to check no import errors
local ok2, err2 = pcall(function()
  local config = dofile(scriptDir .. "../../config/run_and_bun.lua")
  console:log("run_and_bun.lua loaded OK")

  -- Check new config entries
  assert(config.battle_link, "battle_link section missing")
  assert(config.battle_link.InitBtlControllersInternal_BEQ, "InitBtlControllersInternal_BEQ missing")
  assert(config.battle_link.SetControllerToPlayer, "SetControllerToPlayer missing")
  assert(config.battle_link.SetControllerToLinkOpponent, "SetControllerToLinkOpponent missing")
  -- REMOVED: patch no longer in active patches table (CLIENT follows slave path)
  -- assert(config.battle_link.patches.initBtlControllersBeginIntro, "initBtlControllersBeginIntro patch missing")

  console:log("Config checks passed!")
end)

if not ok2 then
  console:log("CONFIG ERROR: " .. tostring(err2))
end

-- Write result file
local f = io.open("syntax_check_done.txt", "w")
if f then
  f:write("battle.lua: " .. (ok and "OK" or ("ERROR: " .. tostring(err))) .. "\n")
  f:write("config: " .. (ok2 and "OK" or ("ERROR: " .. tostring(err2))) .. "\n")
  f:close()
end

console:log("=== SYNTAX CHECK COMPLETE ===")
