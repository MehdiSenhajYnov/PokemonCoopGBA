-- Auto-duel wrapper: REQUESTER mode + file logging
_G.AUTO_DUEL = "request"
_G._autoDuelSent = false

-- Set up a file logger that main.lua can use
local logFile = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/diag_master.txt", "w")
_G._diagLog = function(msg)
  if logFile then
    logFile:write(tostring(msg) .. "\n")
    logFile:flush()
  end
end

-- Set up screenshot capture at specific frames
_G._diagFrame = 0
_G._diagScreenshots = {}

dofile("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/client/main.lua")

-- Add screenshot callback after main.lua's callbacks are registered
callbacks:add("frame", function()
  _G._diagFrame = _G._diagFrame + 1
  local f = _G._diagFrame

  -- Take screenshots at key moments
  if f == 200 or f == 400 or f == 600 or f == 900 or f == 1200 or f == 1500 or f == 1800 then
    pcall(function()
      local img = emu:screenshot()
      if img then
        img:savePNG(string.format("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/relay_master_f%04d.png", f))
      end
    end)
  end
end)
