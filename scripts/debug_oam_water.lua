-- Debug script: dump all 16x32 OAM entries near screen center
-- Run while standing on a water puddle to identify reflection vs player

local SIZE_TABLE = {
  [0] = { [0] = {8,8},   [1] = {16,16}, [2] = {32,32}, [3] = {64,64} },
  [1] = { [0] = {16,8},  [1] = {32,8},  [2] = {32,16}, [3] = {64,32} },
  [2] = { [0] = {8,16},  [1] = {8,32},  [2] = {16,32}, [3] = {32,64} },
}

local function dump()
  console:log("=== OAM DUMP (16x32 near center) ===")
  local count = 0
  for i = 0, 127 do
    local base = 0x07000000 + i * 8
    local attr0 = emu:read16(base)
    local attr1 = emu:read16(base + 2)
    local attr2 = emu:read16(base + 4)

    local affineMode = (attr0 >> 8) & 0x3
    if affineMode ~= 2 then
      local shape = (attr0 >> 14) & 0x3
      local sizeCode = (attr1 >> 14) & 0x3
      local sizeEntry = SIZE_TABLE[shape] and SIZE_TABLE[shape][sizeCode]

      if sizeEntry and sizeEntry[1] == 16 and sizeEntry[2] == 32 then
        local yPos = attr0 & 0xFF
        local xPos = attr1 & 0x1FF
        if xPos >= 256 then xPos = xPos - 512 end
        local ey = yPos
        if ey > 160 then ey = ey - 256 end

        local cx = xPos + 8
        local cy = ey + 16
        local dist = math.abs(cx - 120) + math.abs(cy - 88)

        if dist <= 60 then
          local tileIndex = attr2 & 0x3FF
          local priority = (attr2 >> 10) & 0x3
          local palBank = (attr2 >> 12) & 0xF
          local hFlip = ((attr1 >> 12) & 0x1) == 1
          local vFlip = ((attr1 >> 13) & 0x1) == 1
          local objMode = (attr0 >> 10) & 0x3

          count = count + 1
          console:log(string.format(
            "#%d OAM[%d] pos=(%d,%d) center=(%d,%d) dist=%d tile=%d pal=%d pri=%d hFlip=%s vFlip=%s objMode=%d attr0=%04X attr1=%04X attr2=%04X",
            count, i, xPos, ey, cx, cy, dist,
            tileIndex, palBank, priority,
            tostring(hFlip), tostring(vFlip),
            objMode,
            attr0, attr1, attr2
          ))
        end
      end
    end
  end
  console:log("=== Total: " .. count .. " candidates ===")
end

-- Run 3 dumps with 30 frame gaps
local frame = 0
local dumps = 0
callbacks:add("frame", function()
  frame = frame + 1
  if frame == 1 or frame == 30 or frame == 60 then
    dumps = dumps + 1
    console:log("\n--- Dump #" .. dumps .. " (frame " .. frame .. ") ---")
    dump()
  end
end)

console:log("Water reflection debug: will dump 3 times over 1 second")
console:log("Stand on a water puddle NOW")
