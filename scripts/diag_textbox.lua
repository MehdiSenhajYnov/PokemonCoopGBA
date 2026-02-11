--[[
  Diagnostic script for textbox mechanism.
  Run with: & "mgba/mGBA.exe" -t "rom/Pokemon RunBun.ss1" --script "scripts/diag_textbox.lua" "rom/Pokemon RunBun.gba"

  Tests each step individually with logging:
  1. Write bytecodes to cart0
  2. Read them back to verify
  3. Write text to cart0
  4. Write gScriptLoad trigger
  5. Monitor VAR_RESULT
]]

-- Addresses (from run_and_bun.lua config)
local gScriptLoad = 0x03000E38
local gScriptData = 0x096E0000
local gTextData = 0x096E0040
local gSpecialVar_Result = 0x02036BCA
local gSpecialVar_8001 = 0x02036BB2
local callback2Addr = 0x030022C4
local cb2Overworld = 0x080A89A5

local frame = 0
local phase = "wait"
local started = false

local function log(msg)
  console:log("[DiagTB] " .. msg)
end

-- Pokemon text encoding
local function encodeChar(c)
  local b = string.byte(c)
  if b == 32 then return 0x00 end  -- space
  if b >= 48 and b <= 57 then return 0xA1 + (b - 48) end  -- 0-9
  if b >= 65 and b <= 90 then return 0xBB + (b - 65) end  -- A-Z
  if b >= 97 and b <= 122 then return 0xD5 + (b - 97) end -- a-z
  if b == 33 then return 0xAB end  -- !
  if b == 63 then return 0xAC end  -- ?
  return 0x00  -- fallback space
end

callbacks:add("frame", function()
  frame = frame + 1

  if phase == "wait" then
    if frame >= 60 then
      phase = "diagnose"
    end
    return
  end

  if phase == "diagnose" and not started then
    started = true

    -- Step 0: Check callback2 (are we in overworld?)
    local cb2off = callback2Addr - 0x03000000
    local cb2 = emu.memory.iwram:read32(cb2off)
    log(string.format("Step 0: callback2 = 0x%08X (overworld = 0x%08X, match = %s)",
      cb2, cb2Overworld, tostring(cb2 == cb2Overworld)))

    -- Step 1: Write text to cart0
    local text = "Hello World?"
    local textOff = gTextData - 0x08000000
    log(string.format("Step 1: Writing text at cart0 offset 0x%X (addr 0x%08X)", textOff, gTextData))
    for i = 1, #text do
      local gb = encodeChar(text:sub(i,i))
      emu.memory.cart0:write8(textOff + (i-1), gb)
    end
    emu.memory.cart0:write8(textOff + #text, 0xFF) -- EOS

    -- Verify text readback
    local readback = ""
    for i = 0, #text do
      local b = emu.memory.cart0:read8(textOff + i)
      readback = readback .. string.format("%02X ", b)
    end
    log("Step 1 verify: " .. readback)

    -- Step 2: Write YES/NO script bytecodes
    -- lock (0x6A) + nop (0x00) + loadword 0, textAddr + callstd 5 + end
    -- Following GBA-PK pattern exactly
    local scriptOff = gScriptData - 0x08000000
    log(string.format("Step 2: Writing script at cart0 offset 0x%X (addr 0x%08X)", scriptOff, gScriptData))

    -- Build byte stream like GBA-PK
    -- Byte 0: 0x6A (lock)
    -- Byte 1: 0x00 (nop)
    -- Byte 2: 0x0F (loadword)
    -- Byte 3: 0x00 (reg 0)
    -- Byte 4-7: textAddr (LE)
    -- Byte 8: 0x09 (callstd)
    -- Byte 9: 0x05 (STD_MSGBOX_YESNO)
    -- Byte 10: 0x02 (end)
    -- Byte 11: 0x00 (pad)

    local ta = gTextData  -- text address for loadword (GBA address space)
    local ta0 = ta & 0xFF
    local ta1 = (ta >> 8) & 0xFF
    local ta2 = (ta >> 16) & 0xFF
    local ta3 = (ta >> 24) & 0xFF

    -- Pack as u32 words (LE) — with lock+closemessage+release+end
    -- Byte stream: 6A 0F 00 [ta0] [ta1] [ta2] [ta3] 09 05 68 6C 02
    local w0 = 0x6A + 0x0F * 0x100 + 0x00 * 0x10000 + ta0 * 0x1000000
    local w1 = ta1 + ta2 * 0x100 + ta3 * 0x10000 + 0x09 * 0x1000000
    local w2 = 0x05 + 0x68 * 0x100 + 0x6C * 0x10000 + 0x02 * 0x1000000

    log(string.format("  w0 = 0x%08X (lock+nop+loadword+reg)", w0))
    log(string.format("  w1 = 0x%08X (textAddr = 0x%08X)", w1, ta))
    log(string.format("  w2 = 0x%08X (callstd 5 + end)", w2))

    emu.memory.cart0:write32(scriptOff, w0)
    emu.memory.cart0:write32(scriptOff + 4, w1)
    emu.memory.cart0:write32(scriptOff + 8, w2)

    -- Verify script readback
    local r0 = emu.memory.cart0:read32(scriptOff)
    local r1 = emu.memory.cart0:read32(scriptOff + 4)
    local r2 = emu.memory.cart0:read32(scriptOff + 8)
    log(string.format("Step 2 verify: 0x%08X 0x%08X 0x%08X", r0, r1, r2))

    -- Step 3: Set VAR_RESULT sentinel
    local varOff = gSpecialVar_Result - 0x02000000
    emu.memory.wram:write16(varOff, 0xFF)
    local vr = emu.memory.wram:read16(varOff)
    log(string.format("Step 3: VAR_RESULT set to 0x%04X (readback: 0x%04X)", 0xFF, vr))

    -- Step 4: Trigger gScriptLoad
    -- GBA-PK format: {0, 0, 513, 0, gScriptData + 1, 0, 0, 0, 0, 0, 0, 0}
    local scriptPtr = gScriptData + 1  -- +1 from GBA-PK convention
    local loadData = {0, 0, 513, 0, scriptPtr, 0, 0, 0, 0, 0, 0, 0}
    local slOff = gScriptLoad - 0x03000000

    log(string.format("Step 4: Triggering gScriptLoad at IWRAM offset 0x%X", slOff))
    log(string.format("  scriptPtr = 0x%08X (gScriptData+1)", scriptPtr))

    for i, w in ipairs(loadData) do
      emu.memory.iwram:write32(slOff + (i-1)*4, w)
    end

    -- Verify gScriptLoad readback
    local sl0 = emu.memory.iwram:read32(slOff)
    local sl1 = emu.memory.iwram:read32(slOff + 4)
    local sl2 = emu.memory.iwram:read32(slOff + 8)
    local sl3 = emu.memory.iwram:read32(slOff + 12)
    local sl4 = emu.memory.iwram:read32(slOff + 16)
    log(string.format("Step 4 verify: %d %d %d %d %d", sl0, sl1, sl2, sl3, sl4))

    phase = "polling"
    log("Step 5: Polling VAR_RESULT every 30 frames...")
  end

  if phase == "polling" then
    -- Poll every 30 frames
    if frame % 30 == 0 then
      local varOff = gSpecialVar_Result - 0x02000000
      local vr = emu.memory.wram:read16(varOff)

      -- Also check gScriptLoad status
      local slOff = gScriptLoad - 0x03000000
      local sl2 = emu.memory.iwram:read32(slOff + 8)
      local sl4 = emu.memory.iwram:read32(slOff + 16)

      -- Check callback2
      local cb2off = callback2Addr - 0x03000000
      local cb2 = emu.memory.iwram:read32(cb2off)

      log(string.format("  f=%d VAR_RESULT=0x%04X gScriptLoad[2]=%d [4]=0x%08X cb2=0x%08X",
        frame, vr, sl2, sl4, cb2))

      if vr ~= 0xFF then
        log(string.format("===== VAR_RESULT changed to %d (%s) =====", vr, vr == 1 and "YES" or "NO"))
        phase = "done"
      end
    end

    -- Timeout after 600 frames (10 seconds)
    if frame > 660 then
      log("TIMEOUT: VAR_RESULT never changed. Script did not execute.")
      log("Possible causes:")
      log("  1. gScriptLoad address wrong")
      log("  2. gScriptData address wrong (cart0 write failed)")
      log("  3. Player not in overworld (script engine not running)")
      log("  4. Script bytecodes malformed")
      phase = "done"
    end
  end
end)

log("Diagnostic loaded. Waiting 60 frames before test...")
