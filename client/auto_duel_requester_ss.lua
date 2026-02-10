-- Auto-duel wrapper: REQUESTER mode + periodic screenshots
_G.AUTO_DUEL = "request"
_G._autoDuelSent = false

-- Screenshot setup
local ssDir = "C:\\Users\\mehdi\\Desktop\\Dev\\PokemonCoopGBA\\pvp_screenshots\\master"
os.execute('mkdir "' .. ssDir .. '" 2>nul')
local ssCount = 0
local logFile = "C:\\Users\\mehdi\\Desktop\\Dev\\PokemonCoopGBA\\pvp_screenshots\\master_log.txt"

-- Clear log file
local lf = io.open(logFile, "w")
if lf then lf:write("MASTER LOG\n"); lf:close() end

local function appendLog(msg)
  local lf2 = io.open(logFile, "a")
  if lf2 then lf2:write(msg .. "\n"); lf2:close() end
end

-- Load main.lua
dofile("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/client/main.lua")

-- Add screenshot callback (runs AFTER main.lua's callbacks)
local ssFrame = 0
callbacks:add("frame", function()
  ssFrame = ssFrame + 1
  -- Take screenshot every 90 frames (~1.5 sec)
  if ssFrame % 90 == 0 then
    ssCount = ssCount + 1
    local filename = string.format("%s\\f%05d_%03d.png", ssDir, ssFrame, ssCount)
    pcall(function() emu:screenshot(filename) end)

    -- Also log game state
    local cb2 = emu.memory.iwram:read32(0x22C4)
    local inBattle = emu.memory.iwram:read8(0x2AF9)
    local btf = emu.memory.wram:read32(0x23364)
    local comm0 = emu.memory.wram:read8(0x2370E)
    local bmf = emu.memory.iwram:read32(0x5D04)
    local ef = emu.memory.wram:read32(0x233E0)
    appendLog(string.format("f=%d cb2=0x%08X bmf=0x%08X inBattle=0x%02X btf=0x%08X comm0=%d ef=0x%X ss=#%d",
      ssFrame, cb2, bmf, inBattle, btf, comm0, ef, ssCount))
  end
end)
