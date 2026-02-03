--[[
  Ghost Position Diagnostic v3 - Screen Center Test

  The camera in Pokemon GBA always centers on the player.
  So the player sprite should always be near screen center (120, 80).

  This diagnostic draws FIXED screen position markers (independent of map)
  to find exactly where the player sprite renders on screen.

  Load: Tools > Scripting > File > Load Script
]]

local W = canvas:screenWidth()
local H = canvas:screenHeight()
local overlay = canvas:newLayer(W, H)
overlay:setPosition(0, 0)
local p = image.newPainter(overlay.image)

pcall(function()
  p:loadFont("C:/Windows/Fonts/consola.ttf")
  p:setFontSize(9)
end)

callbacks:add("frame", function()
  -- Clear
  p:setFill(true)
  p:setStrokeWidth(0)
  p:setBlend(false)
  p:setFillColor(0x00000000)
  p:drawRectangle(0, 0, W, H)
  p:setBlend(true)

  -- === SCREEN CENTER CROSSHAIR ===
  -- Thin white lines at exact center (120, 80)
  p:setFillColor(0x60FFFFFF)
  p:drawRectangle(120, 0, 1, H)   -- Vertical line at x=120
  p:drawRectangle(0, 80, W, 1)    -- Horizontal line at y=80

  -- === TEST TILES (16x16 each, fixed screen positions) ===

  -- A (Red): top-left at (112, 72) = center minus half-tile
  -- If camera centers on tile center, this is the player's feet tile
  p:setFillColor(0x55FF0000)
  p:drawRectangle(112, 72, 16, 16)

  -- B (Green): top-left at (112, 56) = one tile above A
  -- This would be the player's head tile
  p:setFillColor(0x5500FF00)
  p:drawRectangle(112, 56, 16, 16)

  -- Small bright dot at exact center (120, 80)
  p:setFillColor(0xFFFF00FF)
  p:drawRectangle(119, 79, 3, 3)

  -- === DEBUG PANEL ===
  p:setFillColor(0xDD000000)
  p:drawRectangle(0, 0, W, 44)

  p:setFillColor(0xFFFFFFFF)
  p:drawText("v3: FIXED screen positions (map-independent)", 4, 2)

  p:setFillColor(0xFFFF6666)
  p:drawText("A RED:   feet tile (112,72)-(128,88)", 4, 14)
  p:setFillColor(0xFF66FF66)
  p:drawText("B GREEN: head tile (112,56)-(128,72)", 4, 26)
  p:setFillColor(0xFFFF66FF)
  p:drawText("PINK DOT: exact center (120,80)", 4, 38)

  overlay:update()
end)

console:log("=== Ghost Diagnostic v3 - Screen Center ===")
console:log("These markers are at FIXED screen positions.")
console:log("They should overlap your character on ANY map.")
console:log("RED = feet tile area, GREEN = head tile area")
console:log("PINK DOT = exact screen center (120,80)")
console:log("")
console:log("Question: Est-ce que les carres sont SUR ton perso")
console:log("sur TOUTES les cartes? (dehors, maison, chambre)")
