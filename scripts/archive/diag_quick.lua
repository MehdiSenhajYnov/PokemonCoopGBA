-- Quick diagnostic: dump battle sprite pointers after battle starts
-- Loads save state, triggers battle, dumps key pointers via screenshot names

local function r32(a)
  if a >= 0x03000000 and a < 0x03008000 then
    return emu.memory.iwram:read32(a - 0x03000000)
  else
    return emu.memory.wram:read32(a - 0x02000000)
  end
end
local function r8(a)
  if a >= 0x03000000 and a < 0x03008000 then
    return emu.memory.iwram:read8(a - 0x03000000)
  else
    return emu.memory.wram:read8(a - 0x02000000)
  end
end
local function sr32(a) local ok,v = pcall(r32,a) return ok and v or nil end
local function sr8(a) local ok,v = pcall(r8,a) return ok and v or nil end
local function hex(v) return v and string.format("%08X", v) or "nil" end

local count = 0
local phase = "wait"

callbacks:add("frame", function()
  count = count + 1

  if phase == "wait" and count == 60 then
    pcall(function() emu:loadStateSlot(1) end)
    phase = "loaded"
  end

  if phase == "loaded" and count == 180 then
    -- Trigger battle
    local gBattleTypeFlags = 0x02023364
    local callback2Addr = 0x030022C4
    local callback1Addr = 0x030022C0
    local savedCallbackAddr = 0x030022C8
    local CB2_InitBattle = 0x080363C1
    local cb2Overworld = 0x080A89A5
    local gMainStateAddr = 0x03002AF8
    local gPlayerParty = 0x02023A98
    local gEnemyParty = 0x02023CF0
    local gPlayerPartyCount = 0x02023A95
    local gEnemyPartyCount = 0x02023A96
    local gWirelessCommType = 0x030030FC
    local gReceivedRemoteLinkPlayers = 0x03003124
    local gBlockReceivedStatus = 0x0300307C

    -- Copy party
    local pp = gPlayerParty - 0x02000000
    local ep = gEnemyParty - 0x02000000
    pcall(function()
      for i = 0, 599 do emu.memory.wram:write8(ep+i, emu.memory.wram:read8(pp+i)) end
    end)
    pcall(function() emu.memory.wram:write8(gEnemyPartyCount - 0x02000000, r8(gPlayerPartyCount)) end)

    -- ROM patches
    pcall(function()
      emu.memory.cart0:write16(0x00A4B0, 0x2000)  -- GetMultiplayerId MOV R0,#0
      emu.memory.cart0:write16(0x00A4B2, 0x4770)  -- BX LR
      emu.memory.cart0:write32(0x0A568, 0x47702001)  -- IsLinkTaskFinished
      emu.memory.cart0:write32(0x0A598, 0x4770200F)  -- GetBlockReceivedStatus
      emu.memory.cart0:write16(0x06F0D4 + 0x1C, 0xE01C)  -- playerBufExecSkip
      emu.memory.cart0:write16(0x078788 + 0x1C, 0xE01C)  -- linkOpponentBufExecSkip
      emu.memory.cart0:write16(0x032FA8 + 0x18, 0xE008)  -- prepBufTransferSkip
      emu.memory.cart0:write16(0x040F40 + 0x10, 0xE010)  -- markBattlerExecLocal
      emu.memory.cart0:write16(0x040EFC, 0xE00E)  -- isBattlerExecLocal
      emu.memory.cart0:write16(0x040E88, 0xE018)  -- markAllBattlersExecLocal
    end)

    -- Set flags
    local flags = 0x02 | 0x08 | 0x04 | 0x01000000  -- LINK | TRAINER | MASTER | RECORDED_LINK
    pcall(function()
      emu.memory.wram:write32(gBattleTypeFlags - 0x02000000, flags)
      emu.memory.iwram:write8(gWirelessCommType - 0x03000000, 0)
      emu.memory.iwram:write8(gReceivedRemoteLinkPlayers - 0x03000000, 1)
      for i = 0, 3 do emu.memory.iwram:write8(gBlockReceivedStatus - 0x03000000 + i, 0x0F) end
      emu.memory.iwram:write32(savedCallbackAddr - 0x03000000, cb2Overworld)
      emu.memory.iwram:write32(callback1Addr - 0x03000000, 0)
      emu.memory.iwram:write8(gMainStateAddr - 0x03000000, 0)
      emu.memory.iwram:write32(callback2Addr - 0x03000000, CB2_InitBattle)
    end)

    -- Block recv buffer health flags
    local gBlockRecvBuffer = 0x020226C4
    pcall(function()
      emu.memory.wram:write8(gBlockRecvBuffer - 0x02000000 + 0x100 + 2, 0x01)
      emu.memory.wram:write8(gBlockRecvBuffer - 0x02000000 + 0x100 + 3, 0x00)
    end)

    console:log("[DIAG] Battle triggered!")
    phase = "battle"
  end

  if phase == "battle" then
    local f = count - 180

    -- Maintain IWRAM
    if f % 10 == 0 then
      pcall(function()
        emu.memory.iwram:write8(0x30FC, 0)
        emu.memory.iwram:write8(0x3124, 1)
        for i = 0,3 do emu.memory.iwram:write8(0x307C+i, 0x0F) end
        emu.memory.wram:write8(0x0233E4, 2)  -- gBattlersCount
        emu.memory.wram:write8(0x03C300, 0)  -- linkStatusByte
      end)
    end

    -- Re-inject enemy party
    if f % 10 == 0 then
      pcall(function()
        local pp = 0x023A98 - 0x020000
        local ep = 0x023CF0 - 0x020000
        for i = 0, 599 do emu.memory.wram:write8(ep+i, emu.memory.wram:read8(pp+i)) end
      end)
    end

    -- Strip stray exec flag bits (keep only local bits 0-3)
    pcall(function()
      local ef = emu.memory.wram:read32(0x0233E0)
      local localBits = ef & 0x0F
      if ef ~= localBits then
        emu.memory.wram:write32(0x0233E0, localBits)
      end
    end)

    -- Dump diagnostics at key frames
    if f == 60 or f == 120 or f == 200 or f == 300 or f == 400 or f == 500 or f == 600 then
      local parts = {"D" .. f}

      -- Read all candidate addresses FULL 32-bit values
      for _, addr in ipairs({0x02023A0C, 0x02023A40, 0x02023A10, 0x02023A14, 0x02023A44, 0x02023A08}) do
        local v = sr32(addr) or 0
        table.insert(parts, string.format("_%X_%s", addr & 0xFFFF, hex(v)))
      end

      -- Read gBattleMainFunc
      local bmf = sr32(0x03005D04) or 0
      table.insert(parts, "_bmf_" .. hex(bmf))

      -- Read exec flags
      local ef = sr32(0x020233E0) or 0
      table.insert(parts, "_ef_" .. hex(ef))

      -- Read callback2
      local cb2 = sr32(0x030022C4) or 0
      table.insert(parts, "_cb2_" .. hex(cb2))

      local name = table.concat(parts)
      pcall(function() emu:screenshot(name .. ".png") end)
      console:log("[DIAG] " .. name)
    end

    -- Also dump healthbox data when found
    if f == 250 or f == 350 or f == 450 then
      local parts = {"H" .. f}

      -- Check gBattleSpritesDataPtr candidates
      local found = false
      for _, ptrAddr in ipairs({0x02023A0C, 0x02023A40}) do
        local ptr = sr32(ptrAddr)
        if ptr and ptr >= 0x02000000 and ptr < 0x02040000 then
          -- Read sub-pointers
          local sub0 = sr32(ptr) or 0
          local sub1 = sr32(ptr + 4) or 0
          local sub2 = sr32(ptr + 8) or 0
          local sub3 = sr32(ptr + 12) or 0
          table.insert(parts, string.format("_%X_p%s_s%s_%s_%s_%s",
            ptrAddr & 0xFFFF, hex(ptr), hex(sub0), hex(sub1), hex(sub2), hex(sub3)))

          -- If sub1 looks like a valid healthBoxesData pointer, read it
          if sub1 and sub1 >= 0x02000000 and sub1 < 0x02040000 then
            for b = 0, 1 do
              local base = sub1 + b * 0x0C
              local b0 = sr8(base) or 0xFF
              local b1 = sr8(base + 1) or 0xFF
              local b10 = sr8(base + 0x0A) or 0xFF
              table.insert(parts, string.format("_hb%d_%02X_%02X_%02X", b, b0, b1, b10))
            end
            found = true
          end
        end
      end

      if not found then
        table.insert(parts, "_NOFOUND")
      end

      local name = table.concat(parts)
      pcall(function() emu:screenshot(name .. ".png") end)
      console:log("[DIAG] " .. name)
    end

    -- SCAN for ROM function pointers (0x08xxxxxx) in EWRAM range 0x02023500-0x02023800
    -- gBattlerControllerFuncs should contain 2+ ROM function pointers during battle
    if f == 200 then
      local romPtrAddrs = {}
      for addr = 0x02023500, 0x020237FF, 4 do
        local v = sr32(addr) or 0
        if v >= 0x08000000 and v < 0x0A000000 and (v & 1) == 1 then  -- THUMB ROM ptr
          table.insert(romPtrAddrs, {addr = addr, val = v})
        end
      end
      -- Build screenshot name with found ROM ptrs
      local parts = {"ROMPTRS_f" .. f}
      for i, rp in ipairs(romPtrAddrs) do
        if i <= 12 then  -- Limit filename length
          table.insert(parts, string.format("_%X_%s", rp.addr & 0xFFF, hex(rp.val)))
        end
      end
      table.insert(parts, "_total" .. #romPtrAddrs)
      local name = table.concat(parts)
      pcall(function() emu:screenshot(name .. ".png") end)
      console:log("[DIAG] " .. name)
    end

    -- Also scan 0x02023200-0x02023400 range
    if f == 210 then
      local romPtrAddrs = {}
      for addr = 0x02023200, 0x020233FF, 4 do
        local v = sr32(addr) or 0
        if v >= 0x08000000 and v < 0x0A000000 and (v & 1) == 1 then
          table.insert(romPtrAddrs, {addr = addr, val = v})
        end
      end
      local parts = {"ROMPTRS2_f" .. f}
      for i, rp in ipairs(romPtrAddrs) do
        if i <= 12 then
          table.insert(parts, string.format("_%X_%s", rp.addr & 0xFFF, hex(rp.val)))
        end
      end
      table.insert(parts, "_total" .. #romPtrAddrs)
      local name = table.concat(parts)
      pcall(function() emu:screenshot(name .. ".png") end)
      console:log("[DIAG] " .. name)
    end

    -- Scan 0x02023800-0x02023A00
    if f == 220 then
      local romPtrAddrs = {}
      for addr = 0x02023800, 0x020239FF, 4 do
        local v = sr32(addr) or 0
        if v >= 0x08000000 and v < 0x0A000000 and (v & 1) == 1 then
          table.insert(romPtrAddrs, {addr = addr, val = v})
        end
      end
      local parts = {"ROMPTRS3_f" .. f}
      for i, rp in ipairs(romPtrAddrs) do
        if i <= 12 then
          table.insert(parts, string.format("_%X_%s", rp.addr & 0xFFF, hex(rp.val)))
        end
      end
      table.insert(parts, "_total" .. #romPtrAddrs)
      local name = table.concat(parts)
      pcall(function() emu:screenshot(name .. ".png") end)
      console:log("[DIAG] " .. name)
    end

    if f > 700 then
      console:log("[DIAG] Done")
      phase = "done"
    end
  end
end)

console:log("[DIAG] Quick diagnostic script loaded")
