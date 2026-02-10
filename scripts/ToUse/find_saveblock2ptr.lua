-- Scan IWRAM for gSaveBlock2Ptr (pointer to SaveBlock2 in EWRAM)
-- SaveBlock2 starts with: playerName[8] (GBA text), gender(u8), unused(u8), trainerId(u32)
-- GBA text: A=0xBB..Z=0xD4, a=0xD5..z=0xEE, 0xFF=terminator

local outFile = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/scan_sb2_results.txt", "w")
local function out(s)
  console:log(s)
  if outFile then outFile:write(s .. "\n") end
end

out("=== Scanning IWRAM for gSaveBlock2Ptr ===")

local function isGbaTextChar(b)
  -- Uppercase A-Z
  if b >= 0xBB and b <= 0xD4 then return true end
  -- Lowercase a-z
  if b >= 0xD5 and b <= 0xEE then return true end
  -- Space, digits, special chars
  if b == 0x00 then return true end  -- space
  if b >= 0xA1 and b <= 0xAA then return true end  -- 0-9
  if b == 0xFF then return true end  -- terminator
  return false
end

local function decodeGbaChar(b)
  if b >= 0xBB and b <= 0xD4 then return string.char(string.byte("A") + (b - 0xBB)) end
  if b >= 0xD5 and b <= 0xEE then return string.char(string.byte("a") + (b - 0xD5)) end
  if b == 0x00 then return " " end
  if b >= 0xA1 and b <= 0xAA then return string.char(string.byte("0") + (b - 0xA1)) end
  if b == 0xFF then return "" end
  return string.format("<%02X>", b)
end

local candidates = {}

-- Scan IWRAM range where SaveBlock pointers likely live
-- Known: gRngValue = 0x03005D90 (16 bytes), gap to gCameraY = 0x03005DF8
-- So scan 0x03005DA0 to 0x03005DF0
for addr = 0x03005DA0, 0x03005DF0, 4 do
  local iwramOff = addr - 0x03000000
  local val = emu.memory.iwram:read32(iwramOff)

  -- Check if value is a valid EWRAM pointer
  if val >= 0x02000000 and val <= 0x0203FFFF then
    -- Read first 12 bytes from the pointed-to address (using absolute addr)
    local bytes = {}
    local allText = true
    local hasTerminator = false

    for i = 0, 7 do
      local b = emu:read8(val + i)
      bytes[i] = b
      if b == 0xFF then
        hasTerminator = true
        -- All remaining should be padding (0x00 or 0xFF)
      elseif hasTerminator then
        -- After terminator, non-zero non-0xFF = not a name
        if b ~= 0x00 and b ~= 0xFF then allText = false end
      elseif not isGbaTextChar(b) then
        allText = false
      end
    end

    -- Read gender (offset 0x08) and trainerId (offset 0x0A)
    local gender = emu:read8(val + 0x08)
    local trainerId = emu:read32(val + 0x0A)

    -- Decode name
    local name = ""
    for i = 0, 7 do
      if bytes[i] == 0xFF then break end
      name = name .. decodeGbaChar(bytes[i])
    end

    local hexDump = ""
    for i = 0, 7 do
      hexDump = hexDump .. string.format("%02X ", bytes[i])
    end

    local isLikely = allText and hasTerminator and #name >= 1 and gender <= 1

    out(string.format(
      "  IWRAM 0x%08X → EWRAM 0x%08X | name=[%s] hex=[%s] gender=%d tid=0x%08X %s",
      addr, val, name, hexDump, gender, trainerId,
      isLikely and "<== LIKELY gSaveBlock2Ptr" or ""
    ))

    table.insert(candidates, { addr = addr, val = val, name = name, likely = isLikely })
  end
end

-- Also check wider range in case it's further away
out("\n=== Extended scan 0x03005D94 to 0x03005D9F (right after gRngValue) ===")
for addr = 0x03005D94, 0x03005D9F, 4 do
  local iwramOff = addr - 0x03000000
  local val = emu.memory.iwram:read32(iwramOff)
  if val >= 0x02000000 and val <= 0x0203FFFF then
    local name = ""
    local hexDump = ""
    for i = 0, 7 do
      local b = emu:read8(val + i)
      hexDump = hexDump .. string.format("%02X ", b)
      if b == 0xFF then break end
      name = name .. decodeGbaChar(b)
    end
    local gender = emu:read8(val + 0x08)
    out(string.format(
      "  IWRAM 0x%08X → EWRAM 0x%08X | name=[%s] hex=[%s] gender=%d",
      addr, val, name, hexDump, gender
    ))
  end
end

out("\n=== Done. Look for 'LIKELY' entries above ===")
out("The correct gSaveBlock2Ptr address should show your player name.")

if outFile then outFile:close() end
