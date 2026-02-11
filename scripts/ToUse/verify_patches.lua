-- Verify ROM patches are applied correctly
-- Run during battle to check if patches stuck

local function hexfmt(v) return string.format("0x%08X", v) end

local patches = {
  { name = "isLinkTaskFinished",         off = 0x0A568, expect = 0x47702001, sz = 4 },
  { name = "getBlockReceivedStatus",     off = 0x0A598, expect = 0x4770200F, sz = 4 },
  { name = "playerBufExecSkip",          off = 0x06F0F0, expect = 0xE01C, sz = 2 },
  { name = "linkOpponentBufExecSkip",    off = 0x07E92C, expect = 0xE01C, sz = 2 },
  { name = "prepBufDataTransferLocal",   off = 0x032FC0, expect = 0xE008, sz = 2 },
  { name = "markBattlerExecLocal",       off = 0x040F50, expect = 0xE010, sz = 2 },
  { name = "isBattlerExecLocal",         off = 0x040EFC, expect = 0xE00E, sz = 2 },
  { name = "markAllBattlersExecLocal",   off = 0x040E88, expect = 0xE018, sz = 2 },
  -- REMOVED: patch no longer applied (CLIENT follows slave path)
  -- { name = "initBtlControllersBeginIntro", off = 0x032ACE, expect = 0x46C0, sz = 2 },
  { name = "nopHandleLinkSetup_SetUpBV_hi", off = 0x032494, expect = 0x46C0, sz = 2 },
  { name = "nopHandleLinkSetup_SetUpBV_lo", off = 0x032496, expect = 0x46C0, sz = 2 },
  { name = "nopHandleLinkSetup_CB2Init_hi", off = 0x036456, expect = 0x46C0, sz = 2 },
  { name = "nopHandleLinkSetup_CB2Init_lo", off = 0x036458, expect = 0x46C0, sz = 2 },
  { name = "nopTryRecvLinkBattleData_hi",  off = 0x0007BC, expect = 0x46C0, sz = 2 },
  { name = "nopTryRecvLinkBattleData_lo",  off = 0x0007BE, expect = 0x46C0, sz = 2 },
}

local frameCount = 0
local checked = false

callbacks:add("frame", function()
  frameCount = frameCount + 1
  if frameCount == 300 and not checked then
    checked = true
    console:log("=== ROM PATCH VERIFICATION (frame 300) ===")

    local allOk = true
    for _, p in ipairs(patches) do
      local ok, val
      if p.sz == 4 then
        ok, val = pcall(function() return emu.memory.cart0:read32(p.off) end)
      else
        ok, val = pcall(function() return emu.memory.cart0:read16(p.off) end)
      end

      if not ok then
        console:log(string.format("  FAIL: %s @ 0x%06X -- read error", p.name, p.off))
        allOk = false
      elseif val == p.expect then
        console:log(string.format("  OK:   %s @ 0x%06X = 0x%X", p.name, p.off, val))
      else
        console:log(string.format("  MISS: %s @ 0x%06X = 0x%X (expected 0x%X)", p.name, p.off, val, p.expect))
        allOk = false
      end
    end

    -- Also check gBattleTypeFlags value
    local btfOk, btf = pcall(function() return emu.memory.wram:read32(0x02023364 - 0x02000000) end)
    if btfOk then
      console:log(string.format("  gBattleTypeFlags = 0x%08X", btf))
    end

    -- Check GetMultiplayerId
    local gmOk, gmVal = pcall(function() return emu.memory.cart0:read16(0x0A4B0) end)
    if gmOk then
      console:log(string.format("  GetMultiplayerId[0] = 0x%04X", gmVal))
    end

    if allOk then
      console:log("=== ALL PATCHES VERIFIED OK ===")
    else
      console:log("=== SOME PATCHES MISSING ===")
    end
  end
end)

console:log("[verify_patches] Will check at frame 300")
