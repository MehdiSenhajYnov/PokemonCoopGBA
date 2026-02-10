-- Auto-duel wrapper: ACCEPTER mode + file logging
_G.AUTO_DUEL = "accept"

local logFile = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/diag_slave.txt", "w")
_G._diagLog = function(msg)
  if logFile then
    logFile:write(tostring(msg) .. "\n")
    logFile:flush()
  end
end

_G._diagFrame = 0

dofile("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/client/main.lua")

callbacks:add("frame", function()
  _G._diagFrame = _G._diagFrame + 1
  local f = _G._diagFrame

  if f == 200 or f == 400 or f == 600 or f == 900 or f == 1200 or f == 1500 or f == 1800 then
    pcall(function()
      local img = emu:screenshot()
      if img then
        img:savePNG(string.format("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/relay_slave_f%04d.png", f))
      end
    end)
  end
end)
