--[[
  Debug OAM Player Detection
  Run this in mGBA to see what 16x32 sprites are near screen center.
  Logs every 60 frames (once per second).
  Walk around, then get on bike, and compare the output.
]]

local SIZE_TABLE = {
  [0] = { [0] = {8,8},   [1] = {16,16}, [2] = {32,32}, [3] = {64,64} },
  [1] = { [0] = {16,8},  [1] = {32,8},  [2] = {32,16}, [3] = {64,32} },
  [2] = { [0] = {8,16},  [1] = {8,32},  [2] = {16,32}, [3] = {32,64} },
}

local frameCount = 0

callbacks:add("frame", function()
  frameCount = frameCount + 1
  if frameCount % 60 ~= 0 then return end

  local candidates = {}
  for i = 0, 127 do
    local attr0 = emu.memory.oam:read16(i * 8)
    local attr1 = emu.memory.oam:read16(i * 8 + 2)
    local attr2 = emu.memory.oam:read16(i * 8 + 4)

    local affineMode = (attr0 >> 8) & 0x3
    if affineMode ~= 2 then
      local shape = (attr0 >> 14) & 0x3
      local sizeCode = (attr1 >> 14) & 0x3
      local sizeEntry = SIZE_TABLE[shape] and SIZE_TABLE[shape][sizeCode]

      if sizeEntry then
        local w, h = sizeEntry[1], sizeEntry[2]
        local yPos = attr0 & 0xFF
        local xPos = attr1 & 0x1FF
        if xPos >= 256 then xPos = xPos - 512 end
        if yPos > 160 then yPos = yPos - 256 end

        local tileIndex = attr2 & 0x3FF
        local priority = (attr2 >> 10) & 0x3
        local palBank = (attr2 >> 12) & 0xF
        local hFlip = ((attr1 >> 12) & 0x1) == 1

        local cx = xPos + w / 2
        local cy = yPos + h / 2
        local dist = math.abs(cx - 120) + math.abs(cy - 88)

        -- Show all sprites near center (wide radius to see everything)
        if dist <= 60 and h >= 16 then
          candidates[#candidates + 1] = {
            oam = i,
            tile = tileIndex,
            pri = priority,
            pal = palBank,
            x = xPos,
            y = yPos,
            w = w,
            h = h,
            dist = dist,
            hFlip = hFlip,
            vramAddr = string.format("0x%08X", 0x06010000 + tileIndex * 32),
          }
        end
      end
    end
  end

  -- Sort by tileIndex
  table.sort(candidates, function(a, b) return a.tile < b.tile end)

  console:log("=== OAM near center (frame " .. frameCount .. ") ===")
  for _, c in ipairs(candidates) do
    console:log(string.format(
      "  OAM#%03d  tile=%3d  pri=%d  pal=%2d  pos=(%4d,%4d)  size=%dx%d  dist=%2d  vram=%s  flip=%s",
      c.oam, c.tile, c.pri, c.pal, c.x, c.y, c.w, c.h, c.dist, c.vramAddr, tostring(c.hFlip)
    ))
  end
  console:log("  Total: " .. #candidates .. " sprites near center")
end)

console:log("OAM debug loaded — logging every 1 sec. Walk, then bike.")
