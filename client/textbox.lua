--[[
  Native GBA Textbox Module

  Provides native Pokemon GBA textboxes via PokéScript injection.
  Uses the same gScriptLoad/gScriptData mechanism as GBA-PK.

  Bytecode pattern (from GBA-PK decoding):
    lock + loadword 0,textAddr + callstd N + closemessage + release + end

  STD_MSGBOX_YESNO (callstd 5) = message + waitmsg + yesnobox + return
    → sets VAR_RESULT (1=Yes, 0=No), returns to caller
  STD_MSGBOX_DEFAULT (callstd 2) = message + waitmsg + return
    → returns to caller after player presses A

  Text encoding: Pokemon Gen 3 Western character set.
]]

local Textbox = {}

-- Addresses (set by init)
local ADDR = {
  gScriptLoad = nil,     -- IWRAM: script trigger struct
  gScriptData = nil,     -- cart0: bytecode area
  gTextData = nil,       -- cart0: text area (after bytecodes)
  gSpecialVar_Result = nil, -- EWRAM: VAR_RESULT (0x800D)
  gSpecialVar_8001 = nil,   -- EWRAM: VAR_0x8001 (completion signal)
  cb2Overworld = nil,    -- ROM: CB2_Overworld address (busy check)
  callback2Addr = nil,   -- IWRAM: gMain.callback2 address
}

-- State
local active = false        -- Is a textbox currently showing?
local activeType = nil      -- "yesno" or "message"
local pollReady = false     -- Has the script had time to start?
local triggerFrame = 0      -- Frame when script was triggered
local STARTUP_DELAY = 6     -- Frames to wait before polling result
local SCRIPT_SETTLE_FRAMES = 2 -- Let script run closemessage/release before cleanup
local currentFrame = 0
local pendingYesNoResult = nil
local pendingMessageDismiss = false
local finalizeFrame = 0

-- Pokemon Gen 3 Western text encoding table (ASCII -> GBA byte)
local CHAR_MAP = {}
CHAR_MAP[string.byte(" ")] = 0x00
for i = 0, 9 do CHAR_MAP[string.byte("0") + i] = 0xA1 + i end
for i = 0, 25 do CHAR_MAP[string.byte("A") + i] = 0xBB + i end
for i = 0, 25 do CHAR_MAP[string.byte("a") + i] = 0xD5 + i end
CHAR_MAP[string.byte("!")] = 0xAB
CHAR_MAP[string.byte("?")] = 0xAC
CHAR_MAP[string.byte(".")] = 0xAD
CHAR_MAP[string.byte("-")] = 0xAE
CHAR_MAP[string.byte(",")] = 0xB8
CHAR_MAP[string.byte("/")] = 0xBA
CHAR_MAP[string.byte(":")] = 0xF0
CHAR_MAP[string.byte("'")] = 0xB3
local CHAR_NEWLINE = 0xFE
local CHAR_EOS = 0xFF

-- Reverse mapping: GBA byte → ASCII char (for decoding names from SaveBlock2)
local GBA_TO_ASCII = {}
GBA_TO_ASCII[0x00] = " "
for i = 0, 9 do GBA_TO_ASCII[0xA1 + i] = string.char(string.byte("0") + i) end
for i = 0, 25 do GBA_TO_ASCII[0xBB + i] = string.char(string.byte("A") + i) end
for i = 0, 25 do GBA_TO_ASCII[0xD5 + i] = string.char(string.byte("a") + i) end
GBA_TO_ASCII[0xAB] = "!"
GBA_TO_ASCII[0xAC] = "?"
GBA_TO_ASCII[0xAD] = "."
GBA_TO_ASCII[0xAE] = "-"
GBA_TO_ASCII[0xB3] = "'"
GBA_TO_ASCII[0xB8] = ","
GBA_TO_ASCII[0xBA] = "/"
GBA_TO_ASCII[0xF0] = ":"

local VAR_SENTINEL = 0x007F  -- sentinel for VAR_RESULT (positive non-boolean, matching diagnostic)

-- ========== Logging ==========
local function log(msg)
  console:log("[Textbox] " .. msg)
end

local function clearPendingState()
  pendingYesNoResult = nil
  pendingMessageDismiss = false
  finalizeFrame = 0
end

-- ========== Init ==========

function Textbox.init(config)
  if not config then return false end
  local bl = config.battle_link
  if not bl then return false end

  ADDR.gScriptLoad = bl.gScriptLoad
  ADDR.gScriptData = bl.gScriptData
  ADDR.gTextData = bl.gTextData or (bl.gScriptData and bl.gScriptData + 0x40)
  ADDR.gSpecialVar_Result = bl.gSpecialVar_Result
  ADDR.gSpecialVar_8001 = bl.gSpecialVar_8001

  if config.warp then
    ADDR.cb2Overworld = config.warp.cb2Overworld
    ADDR.callback2Addr = config.warp.callback2Addr
  end

  return ADDR.gScriptLoad ~= nil and ADDR.gScriptData ~= nil
end

function Textbox.isConfigured()
  return ADDR.gScriptLoad ~= nil
     and ADDR.gScriptData ~= nil
     and ADDR.gSpecialVar_Result ~= nil
     and ADDR.gSpecialVar_8001 ~= nil
end

-- ========== Internal helpers ==========

local function encodeText(str)
  local bytes = {}
  local i = 1
  while i <= #str do
    local c = str:byte(i)
    if c == string.byte("\\") and i < #str and str:byte(i+1) == string.byte("n") then
      bytes[#bytes + 1] = CHAR_NEWLINE
      i = i + 2
    elseif CHAR_MAP[c] then
      bytes[#bytes + 1] = CHAR_MAP[c]
      i = i + 1
    else
      bytes[#bytes + 1] = 0x00
      i = i + 1
    end
  end
  bytes[#bytes + 1] = CHAR_EOS
  return bytes
end

local function writeCart8(romAddr, value)
  local off = romAddr - 0x08000000
  emu.memory.cart0:write8(off, value)
end

local function writeCart32(romAddr, value)
  local off = romAddr - 0x08000000
  emu.memory.cart0:write32(off, value)
end

local function writeTextToCart(textAddr, encodedBytes)
  for i, b in ipairs(encodedBytes) do
    writeCart8(textAddr + (i - 1), b)
  end
end

local function writeEWRAM16(addr, value)
  emu.memory.wram:write16(addr - 0x02000000, value)
end

local function readEWRAM16(addr)
  return emu.memory.wram:read16(addr - 0x02000000)
end

local function readIWRAM32(addr)
  return emu.memory.iwram:read32(addr - 0x03000000)
end

--[[
  Trigger gScriptLoad to run bytecodes at gScriptData.
  GBA-PK "Data" mode: {0, 0, 513, 0, gScriptData+1, 0, ...}
]]
local function triggerScript()
  if not ADDR.gScriptLoad or not ADDR.gScriptData then return false end
  local loadData = {0, 0, 513, 0, ADDR.gScriptData + 1, 0, 0, 0, 0, 0, 0, 0}
  local slOff = ADDR.gScriptLoad - 0x03000000
  for i, w in ipairs(loadData) do
    emu.memory.iwram:write32(slOff + (i-1)*4, w)
  end
  return true
end

-- ========== Public API ==========

--[[
  Show a Yes/No prompt using native GBA textbox.
  Bytecodes (GBA-PK pattern):
    [0] 0x6A  lock
    [1] 0x0F  loadword
    [2] 0x00  register 0
    [3-6]     textAddr (LE u32)
    [7] 0x09  callstd
    [8] 0x05  STD_MSGBOX_YESNO (message + waitmsg + yesnobox + return)
    [9] 0x68  closemessage
    [10] 0x6C release
    [11] 0x02 end
  Total: 12 bytes = 3 u32 words
]]
function Textbox.showYesNo(text)
  if active then
    log("showYesNo blocked: already active")
    return false
  end
  if not Textbox.isConfigured() then
    log("showYesNo blocked: not configured")
    return false
  end

  local ok, err = pcall(function()
    local encoded = encodeText(text)
    local textAddr = ADDR.gTextData
    local sd = ADDR.gScriptData

    -- Write text
    writeTextToCart(textAddr, encoded)

    -- Set VAR_RESULT to sentinel (0x007F instead of 0xFFFF)
    writeEWRAM16(ADDR.gSpecialVar_Result, VAR_SENTINEL)

    -- Build bytecodes
    local ta0 = textAddr & 0xFF
    local ta1 = (textAddr >> 8) & 0xFF
    local ta2 = (textAddr >> 16) & 0xFF
    local ta3 = (textAddr >> 24) & 0xFF

    -- Word 0: lock(6A) + loadword(0F) + reg(00) + ta0
    local w0 = 0x6A + 0x0F * 0x100 + 0x00 * 0x10000 + ta0 * 0x1000000
    -- Word 1: ta1 + ta2 + ta3 + callstd(09)
    local w1 = ta1 + ta2 * 0x100 + ta3 * 0x10000 + 0x09 * 0x1000000
    -- Word 2: STD_YESNO(05) + closemessage(68) + release(6C) + end(02)
    local w2 = 0x05 + 0x68 * 0x100 + 0x6C * 0x10000 + 0x02 * 0x1000000

    writeCart32(sd, w0)
    writeCart32(sd + 4, w1)
    writeCart32(sd + 8, w2)

    -- Trigger
    triggerScript()
    log(string.format("showYesNo triggered: text='%s' sd=0x%08X td=0x%08X", text, sd, textAddr))
  end)

  if ok then
    active = true
    activeType = "yesno"
    pollReady = false
    triggerFrame = 0
    clearPendingState()
    return true
  else
    log("showYesNo ERROR: " .. tostring(err))
    return false
  end
end

--[[
  Show a blocking message using native GBA textbox.
  Bytecodes:
    [0]  0x6A  lock
    [1]  0x0F  loadword
    [2]  0x00  register 0
    [3-6]      textAddr (LE u32)
    [7]  0x09  callstd
    [8]  0x02  STD_MSGBOX_DEFAULT (message + waitmsg + return)
    [9]  0x68  closemessage
    [10] 0x16  setvar
    [11] 0x01  var 0x8001 low
    [12] 0x80  var 0x8001 high
    [13] 0x01  value 1 low
    [14] 0x00  value 1 high
    [15] 0x6C  release
    [16] 0x02  end
    [17] 0x00  pad
  Total: 18 bytes = 5 u32 words (rounded up)
]]
function Textbox.showMessage(text)
  if active then
    log("showMessage blocked: already active")
    return false
  end
  if not Textbox.isConfigured() then
    log("showMessage blocked: not configured")
    return false
  end

  local ok, err = pcall(function()
    local encoded = encodeText(text)
    local textAddr = ADDR.gTextData
    local sd = ADDR.gScriptData

    -- Write text
    writeTextToCart(textAddr, encoded)

    -- Set completion signal to 0
    writeEWRAM16(ADDR.gSpecialVar_8001, 0)

    -- Build bytecodes
    local ta0 = textAddr & 0xFF
    local ta1 = (textAddr >> 8) & 0xFF
    local ta2 = (textAddr >> 16) & 0xFF
    local ta3 = (textAddr >> 24) & 0xFF

    -- Word 0: lock(6A) + loadword(0F) + reg(00) + ta0
    local w0 = 0x6A + 0x0F * 0x100 + 0x00 * 0x10000 + ta0 * 0x1000000
    -- Word 1: ta1 + ta2 + ta3 + callstd(09)
    local w1 = ta1 + ta2 * 0x100 + ta3 * 0x10000 + 0x09 * 0x1000000
    -- Word 2: STD_DEFAULT(02) + closemessage(68) + setvar(16) + var_lo(01)
    local w2 = 0x02 + 0x68 * 0x100 + 0x16 * 0x10000 + 0x01 * 0x1000000
    -- Word 3: var_hi(80) + val_lo(01) + val_hi(00) + release(6C)
    local w3 = 0x80 + 0x01 * 0x100 + 0x00 * 0x10000 + 0x6C * 0x1000000
    -- Word 4: end(02) + pad
    local w4 = 0x02

    writeCart32(sd, w0)
    writeCart32(sd + 4, w1)
    writeCart32(sd + 8, w2)
    writeCart32(sd + 12, w3)
    writeCart32(sd + 16, w4)

    -- Trigger
    triggerScript()
    log(string.format("showMessage triggered: text='%s'", text))
  end)

  if ok then
    active = true
    activeType = "message"
    pollReady = false
    triggerFrame = 0
    clearPendingState()
    return true
  else
    log("showMessage ERROR: " .. tostring(err))
    return false
  end
end

--[[
  Poll Yes/No result.
  @return nil (still waiting), true (Yes), or false (No)
]]
function Textbox.pollYesNo()
  if not active or activeType ~= "yesno" then return nil end
  if not pollReady then return nil end

  if pendingYesNoResult ~= nil then
    if currentFrame < finalizeFrame then
      return nil
    end

    -- Finalize after a short delay so script can close the native textbox cleanly.
    local result = pendingYesNoResult
    active = false
    activeType = nil
    pollReady = false
    clearPendingState()
    log(string.format("pollYesNo result: %d (%s)", result and 1 or 0, result and "Yes" or "No"))
    return result
  end

  local ok, val = pcall(readEWRAM16, ADDR.gSpecialVar_Result)
  if not ok then return nil end

  if val == VAR_SENTINEL then
    return nil  -- Script hasn't written result yet
  end

  -- callstd 5 sets VAR_RESULT: 1 = Yes, 0 = No.
  -- Defer completion slightly to avoid leaving the textbox visually stuck.
  pendingYesNoResult = (val == 1)
  finalizeFrame = currentFrame + SCRIPT_SETTLE_FRAMES
  return nil
end

--[[
  Poll message dismissed.
  @return nil (still waiting) or true (dismissed)
]]
function Textbox.pollMessage()
  if not active or activeType ~= "message" then return nil end
  if not pollReady then return nil end

  if pendingMessageDismiss then
    if currentFrame < finalizeFrame then
      return nil
    end

    active = false
    activeType = nil
    pollReady = false
    clearPendingState()
    log("pollMessage: dismissed")
    return true
  end

  local ok, val = pcall(readEWRAM16, ADDR.gSpecialVar_8001)
  if not ok then return nil end

  if val == 0 then return nil end

  pendingMessageDismiss = true
  finalizeFrame = currentFrame + SCRIPT_SETTLE_FRAMES
  return nil
end

--[[
  Tick — called once per frame.
]]
function Textbox.tick(frameCounter)
  currentFrame = frameCounter
  if not active then return end
  if triggerFrame == 0 then
    triggerFrame = frameCounter
  end
  if not pollReady and (frameCounter - triggerFrame) >= STARTUP_DELAY then
    pollReady = true
  end
end

function Textbox.isActive()
  return active
end

function Textbox.getActiveType()
  return activeType
end

function Textbox.clear()
  if active then
    -- Unblock any waiting script path first; hard-clearing while active
    -- can leave native windows visually stuck on some ROM builds.
    if activeType == "yesno" and ADDR.gSpecialVar_Result then
      pcall(writeEWRAM16, ADDR.gSpecialVar_Result, 0)
    elseif activeType == "message" and ADDR.gSpecialVar_8001 then
      pcall(writeEWRAM16, ADDR.gSpecialVar_8001, 1)
    end
  end
  active = false
  activeType = nil
  pollReady = false
  triggerFrame = 0
  clearPendingState()
end

function Textbox.reset()
  Textbox.clear()
end

function Textbox.isInOverworld()
  if not ADDR.callback2Addr or not ADDR.cb2Overworld then return true end
  local ok, cb2 = pcall(readIWRAM32, ADDR.callback2Addr)
  if not ok then return true end
  return cb2 == ADDR.cb2Overworld
end

function Textbox.isPollReady()
  return pollReady
end

function Textbox.readVarResult()
  if not ADDR.gSpecialVar_Result then return nil end
  local ok, val = pcall(readEWRAM16, ADDR.gSpecialVar_Result)
  return ok and val or nil
end

function Textbox.readVar8001()
  if not ADDR.gSpecialVar_8001 then return nil end
  local ok, val = pcall(readEWRAM16, ADDR.gSpecialVar_8001)
  return ok and val or nil
end

function Textbox.setVarResult(value)
  if ADDR.gSpecialVar_Result then
    pcall(writeEWRAM16, ADDR.gSpecialVar_Result, value)
  end
end

function Textbox.setVar8001(value)
  if ADDR.gSpecialVar_8001 then
    pcall(writeEWRAM16, ADDR.gSpecialVar_8001, value)
  end
end

--[[
  Decode GBA text bytes (from SaveBlock2 name) to ASCII string.
  Stops at 0xFF (EOS) or end of array.
  @param bytes  table  Array of GBA-encoded bytes
  @return string  ASCII text
]]
function Textbox.decodeGBAText(bytes)
  local result = ""
  for _, b in ipairs(bytes) do
    if b == 0xFF then break end
    result = result .. (GBA_TO_ASCII[b] or "")
  end
  return result
end

return Textbox
