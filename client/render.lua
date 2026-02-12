--[[
  Render Module
  Handles ghost player rendering and coordinate conversion.

  Hybrid OAM renderer:
  - Ghost sprites are injected directly into OBJ VRAM + OAM
  - Painter overlay is used only for fallback debug rectangles
]]

local HAL = require("hal")

local Sprite -- forward declaration, set via Render.setSprite()

local Render = {}

-- Configuration
local TILE_SIZE = 16
local GHOST_SIZE = 14 -- fallback rectangle size when no sprite data/OAM slot
local OAM_PRIORITY_BACK = 2
local OAM_PRIORITY_FRONT = 1
local MAX_GHOSTS = HAL.getGhostMaxSlots() or 6
local ACTIVE_GHOST_SLOTS = MAX_GHOSTS
local OAM_STRATEGY = "fixed"
local USE_REMOTE_CONNECTION_FALLBACK = false
local META_HASH_MISMATCH_THRESHOLD = 2
local CAMERA_WARMUP_FRAMES = 2
local VRAM_REFRESH_INTERVAL_FRAMES = 8
local PROJECTION_SETTLE_GRACE_FRAMES = 12
local OAM_MISS_GRACE_FRAMES = 10
local PREFER_NATIVE_PALBANK = true
local ENABLE_FORCE_OVERLAY_FRONT = true
local OVERLAY_FRONT_ENABLE_CONFIRM_FRAMES = 2
local OVERLAY_FRONT_RELEASE_GRACE_FRAMES = 6
local FORCE_ZERO_SUBTILE_OFFSET = false -- Test mode: keep ST fixed to 0,0

local RESERVED_PALETTE_SLOTS = { 13, 14, 15 }

-- Debug fallback colors (ARGB)
local GHOST_COLOR = 0x8000FF00
local GHOST_OUTLINE = 0xFF00CC00
local STATE_COLORS = {
    interpolating = 0x8000FF00,
    idle = 0x8000FF00,
}
local STATE_OUTLINES = {
    interpolating = 0xFF00CC00,
    idle = 0xFF00CC00,
}

local SCREEN_WIDTH = 240
local SCREEN_HEIGHT = 160

-- Player tile top-left on screen (screen center minus half tile)
local PLAYER_SCREEN_X = 112
local PLAYER_SCREEN_Y = 72

-- OAM shape/size encoding lookup
local SHAPE_SIZE_LOOKUP = {
    ["8x8"] = { shape = 0, size = 0 },
    ["16x16"] = { shape = 0, size = 1 },
    ["32x32"] = { shape = 0, size = 2 },
    ["64x64"] = { shape = 0, size = 3 },
    ["16x8"] = { shape = 1, size = 0 },
    ["32x8"] = { shape = 1, size = 1 },
    ["32x16"] = { shape = 1, size = 2 },
    ["64x32"] = { shape = 1, size = 3 },
    ["8x16"] = { shape = 2, size = 0 },
    ["8x32"] = { shape = 2, size = 1 },
    ["16x32"] = { shape = 2, size = 2 },
    ["32x64"] = { shape = 2, size = 3 },
}

-- Sub-tile camera tracking state
local prevCamX, prevCamY
local prevTileX, prevTileY
local subTileX, subTileY = 0, 0
local stepDirX, stepDirY = 0, 0
local lastCameraMapKey = nil
local cameraWarmupFrames = 0

-- Injection state
local slotByPlayer = {}                -- playerId -> vram slot
local ownerBySlot = {}                 -- vram slot -> playerId
local slotSpriteHash = {}              -- vram slot -> sprite hash
local slotLastVRAMWriteTick = {}       -- vram slot -> last write tick
local paletteHashBySlot = {}           -- palette slot -> hash
local previousOAM = {}                 -- OAM indices written during previous frame
local ownedGhostOAM = {}               -- oamIndex -> true (only slots written by us)
local oamLastWriteTick = {}            -- oamIndex -> renderTick of last successful write
local activeGhostOAMIndices = {}       -- slot+1 -> oamIndex (dynamic/fixed strategy)
local lastRenderedGhostByPlayer = {}   -- playerId -> last successful ghost render snapshot
local overlayFrontTracker = {}         -- playerId -> {isFront, desiredCount, releaseTick}
local projectionMetaState = {}         -- playerId -> {lastRev, lastHash, mismatchCount, ignoreRev}
local transitionProjectionOffsets = {} -- legacy debug cache (kept for compatibility)
local projectedPosCache = {}           -- playerId -> {x, y, crossMap, tick}
local renderTick = 0
local PROJECTED_POS_CACHE_TTL = 2      -- frames, anti-flash fallback when projection blips

local function oamShapeSizeForDimensions(width, height)
    return SHAPE_SIZE_LOOKUP[string.format("%dx%d", width, height)]
end

local function isSameMap(pos, currentMap)
    return pos.mapId == currentMap.mapId and pos.mapGroup == currentMap.mapGroup
end

local function buildMapKey(mapGroup, mapId)
    if mapGroup == nil or mapId == nil then
        return nil
    end
    return string.format("%d:%d", tonumber(mapGroup) or -1, tonumber(mapId) or -1)
end

local function buildMapPairKey(localPos, remotePos)
    local localKey = buildMapKey(localPos and localPos.mapGroup, localPos and localPos.mapId)
    local remoteKey = buildMapKey(remotePos and remotePos.mapGroup, remotePos and remotePos.mapId)
    if not localKey or not remoteKey then
        return nil
    end
    return localKey .. "|" .. remoteKey
end

local function resetCameraTrackingState(warmupFrames)
    prevCamX, prevCamY = nil, nil
    prevTileX, prevTileY = nil, nil
    subTileX, subTileY = 0, 0
    stepDirX, stepDirY = 0, 0
    lastCameraMapKey = nil
    cameraWarmupFrames = math.max(0, tonumber(warmupFrames) or 0)
end

local function clampInt(value, minValue, maxValue, fallback)
    local n = math.floor(tonumber(value) or fallback or 0)
    if n < minValue then n = minValue end
    if n > maxValue then n = maxValue end
    return n
end

local function setActiveGhostOAMIndices(indices)
    activeGhostOAMIndices = {}
    if type(indices) ~= "table" then
        return
    end
    for i = 1, #indices do
        local idx = tonumber(indices[i])
        if idx and idx >= 0 and idx <= 127 then
            activeGhostOAMIndices[#activeGhostOAMIndices + 1] = idx
        end
    end
end

local function loadFixedGhostOAMIndices()
    local fixed = {}
    for slot = 0, ACTIVE_GHOST_SLOTS - 1 do
        local idx = HAL.getGhostOAMIndexForSlot and HAL.getGhostOAMIndexForSlot(slot) or nil
        if idx ~= nil then
            fixed[#fixed + 1] = idx
        end
    end
    setActiveGhostOAMIndices(fixed)
end

local function ensureGhostOAMReservation(forceReallocate)
    if OAM_STRATEGY == "dynamic" and HAL.allocateGhostOAMSlots then
        if forceReallocate or #activeGhostOAMIndices ~= ACTIVE_GHOST_SLOTS then
            local allocated = HAL.allocateGhostOAMSlots(ACTIVE_GHOST_SLOTS)
            setActiveGhostOAMIndices(allocated)
        end

        if HAL.validateGhostOAMSlots and not HAL.validateGhostOAMSlots(activeGhostOAMIndices) then
            local reallocated = HAL.allocateGhostOAMSlots(ACTIVE_GHOST_SLOTS)
            setActiveGhostOAMIndices(reallocated)
        end
    end

    if #activeGhostOAMIndices == 0 then
        loadFixedGhostOAMIndices()
    end
end

local function getReservedOAMIndexForSlot(slot)
    local idx = activeGhostOAMIndices[slot + 1]
    if idx ~= nil then
        return idx
    end
    if OAM_STRATEGY ~= "dynamic" then
        return HAL.getGhostOAMIndexForSlot and HAL.getGhostOAMIndexForSlot(slot) or nil
    end
    return nil
end

local function normalizeConnection(conn)
    if type(conn) ~= "table" then
        return nil
    end

    local direction = tonumber(conn.direction)
    local offset = tonumber(conn.offset)
    local mapGroup = tonumber(conn.mapGroup)
    local mapId = tonumber(conn.mapId)

    if not direction or not offset or not mapGroup or not mapId then
        return nil
    end
    if direction < 1 or direction > 4 then
        return nil
    end

    return {
        direction = direction,
        offset = offset,
        mapGroup = mapGroup,
        mapId = mapId,
    }
end

local function findConnectionToMap(connections, targetMap)
    if type(connections) ~= "table" or type(targetMap) ~= "table" then
        return nil
    end

    local targetGroup = tonumber(targetMap.mapGroup)
    local targetId = tonumber(targetMap.mapId)
    if targetGroup == nil or targetId == nil then
        return nil
    end

    for _, rawConn in ipairs(connections) do
        local conn = normalizeConnection(rawConn)
        if conn and conn.mapGroup == targetGroup and conn.mapId == targetId then
            return conn
        end
    end
    return nil
end

local function ensureProjectionState(playerId, remotePos)
    if playerId == nil then
        return nil
    end

    local state = projectionMetaState[playerId]
    if not state then
        state = {
            lastRev = tonumber(remotePos and remotePos.mapRev) or 0,
            lastHash = remotePos and remotePos.metaHash or nil,
            mismatchCount = 0,
            ignoreRev = nil,
            lastTransitionToken = nil,
        }
        projectionMetaState[playerId] = state
    end
    return state
end

local function registerTransitionProjectionOffset(pairKey, tx, ty)
    if not pairKey then
        return false
    end
    if tx == nil or ty == nil then
        return false
    end
    if math.abs(tx) > 512 or math.abs(ty) > 512 then
        return false
    end

    local signature = string.format("%d:%d", tx, ty)
    local entry = transitionProjectionOffsets[pairKey]
    if not entry then
        entry = {
            tx = tx,
            ty = ty,
            votes = {},
            bestVotes = 0,
            samples = 0,
        }
        transitionProjectionOffsets[pairKey] = entry
    end

    entry.samples = (entry.samples or 0) + 1
    entry.votes[signature] = (entry.votes[signature] or 0) + 1
    local votes = entry.votes[signature]
    if votes >= (entry.bestVotes or 0) then
        entry.bestVotes = votes
        entry.tx = tx
        entry.ty = ty
    end

    return true, entry.tx, entry.ty, entry.bestVotes, entry.samples
end

local function shouldTrustRemoteMeta(playerId, remotePos)
    if playerId == nil then
        return remotePos and remotePos.metaStable == true
    end

    local rev = tonumber(remotePos and remotePos.mapRev) or 0
    local hash = remotePos and remotePos.metaHash or nil
    local stable = remotePos and remotePos.metaStable == true

    local state = ensureProjectionState(playerId, remotePos)
    if not state then
        return false
    end

    if state.lastRev ~= rev then
        state.lastRev = rev
        state.lastHash = hash
        state.mismatchCount = 0
        state.ignoreRev = nil
    else
        if stable and hash and state.lastHash and hash ~= state.lastHash then
            state.mismatchCount = state.mismatchCount + 1
            if state.mismatchCount >= META_HASH_MISMATCH_THRESHOLD then
                state.ignoreRev = rev
            end
        elseif stable and hash then
            state.lastHash = hash
            state.mismatchCount = 0
        end
    end

    if not stable then
        return false
    end
    if state.ignoreRev and state.ignoreRev == rev then
        return false
    end
    return true
end

local function projectFromLocalConnection(localPos, remotePos, conn)
    local localBorderX = tonumber(localPos.borderX)
    local localBorderY = tonumber(localPos.borderY)
    local remoteBorderX = tonumber(remotePos.borderX)
    local remoteBorderY = tonumber(remotePos.borderY)
    local remoteX = tonumber(remotePos.x)
    local remoteY = tonumber(remotePos.y)

    if remoteX == nil or remoteY == nil then
        return nil, nil
    end

    if conn.direction == 1 then
        if not localBorderY then return nil, nil end
        return remoteX + conn.offset, remoteY + localBorderY
    elseif conn.direction == 2 then
        if not remoteBorderY then return nil, nil end
        return remoteX + conn.offset, remoteY - remoteBorderY
    elseif conn.direction == 3 then
        if not remoteBorderX then return nil, nil end
        return remoteX - remoteBorderX, remoteY + conn.offset
    elseif conn.direction == 4 then
        if not localBorderX then return nil, nil end
        return remoteX + localBorderX, remoteY + conn.offset
    end

    return nil, nil
end

local function projectFromRemoteConnection(localPos, remotePos, conn)
    local localBorderX = tonumber(localPos.borderX)
    local localBorderY = tonumber(localPos.borderY)
    local remoteBorderX = tonumber(remotePos.borderX)
    local remoteBorderY = tonumber(remotePos.borderY)
    local remoteX = tonumber(remotePos.x)
    local remoteY = tonumber(remotePos.y)

    if remoteX == nil or remoteY == nil then
        return nil, nil
    end

    -- Inverse projection of GBAPK formulas when only remote-side connection metadata is available.
    if conn.direction == 1 then
        if not remoteBorderY then return nil, nil end
        return remoteX - conn.offset, remoteY - remoteBorderY
    elseif conn.direction == 2 then
        if not localBorderY then return nil, nil end
        return remoteX - conn.offset, remoteY + localBorderY
    elseif conn.direction == 3 then
        if not localBorderX then return nil, nil end
        return remoteX + localBorderX, remoteY - conn.offset
    elseif conn.direction == 4 then
        if not remoteBorderX then return nil, nil end
        return remoteX - remoteBorderX, remoteY - conn.offset
    end

    return nil, nil
end

local function projectGhostTilePosition(localPos, remotePos, playerId)
    if type(localPos) ~= "table" or type(remotePos) ~= "table" then
        return nil, nil, nil
    end

    if localPos.mapId == nil or localPos.mapGroup == nil
        or remotePos.mapId == nil or remotePos.mapGroup == nil then
        return nil, nil, nil
    end

    local remoteX = tonumber(remotePos.x)
    local remoteY = tonumber(remotePos.y)
    if remoteX == nil or remoteY == nil then
        return nil, nil, nil
    end

    if isSameMap(remotePos, localPos) then
        return remoteX, remoteY, false
    end

    -- GBAPK behavior: prefer local map connections for cross-map projection.
    -- Use deterministic map border/connection formulas only.
    local localConn = findConnectionToMap(localPos.connections, remotePos)
    if localConn then
        local projectedX, projectedY = projectFromLocalConnection(localPos, remotePos, localConn)
        if projectedX ~= nil and projectedY ~= nil then
            return projectedX, projectedY, true
        end
    end

    local trustRemoteMeta = shouldTrustRemoteMeta(playerId, remotePos)
    if USE_REMOTE_CONNECTION_FALLBACK and trustRemoteMeta then
        local remoteConn = findConnectionToMap(remotePos.connections, localPos)
        if remoteConn then
            local projectedX, projectedY = projectFromRemoteConnection(localPos, remotePos, remoteConn)
            if projectedX ~= nil and projectedY ~= nil then
                return projectedX, projectedY, true
            end
        end
    end

    return nil, nil, nil
end

local function connectionDirectionToDelta(direction)
    if direction == 1 then
        return 0, 1
    elseif direction == 2 then
        return 0, -1
    elseif direction == 3 then
        return -1, 0
    elseif direction == 4 then
        return 1, 0
    end
    return nil, nil
end

local function seamStepDeltaForLocalMap(localPos, fromMapGroup, fromMapId, toMapGroup, toMapId)
    if type(localPos) ~= "table" then
        return nil, nil
    end

    local localGroup = tonumber(localPos.mapGroup)
    local localId = tonumber(localPos.mapId)
    if localGroup == nil or localId == nil then
        return nil, nil
    end

    -- Local map is destination map: movement is opposite of "destination -> from".
    if localGroup == toMapGroup and localId == toMapId then
        local connToFrom = findConnectionToMap(localPos.connections, {
            mapGroup = fromMapGroup,
            mapId = fromMapId,
        })
        if connToFrom then
            local dx, dy = connectionDirectionToDelta(connToFrom.direction)
            if dx ~= nil and dy ~= nil then
                return -dx, -dy
            end
        end
    end

    -- Local map is source map: movement follows "source -> destination".
    if localGroup == fromMapGroup and localId == fromMapId then
        local connToTo = findConnectionToMap(localPos.connections, {
            mapGroup = toMapGroup,
            mapId = toMapId,
        })
        if connToTo then
            return connectionDirectionToDelta(connToTo.direction)
        end
    end

    return nil, nil
end

local function resolveProjectedGhostTilePosition(localPos, remotePos, playerId)
    local projectedToX, projectedToY, isCrossMap = projectGhostTilePosition(localPos, remotePos, playerId)
    local t = tonumber(remotePos and remotePos.transitionProgress)
    if projectedToX == nil or projectedToY == nil then
        -- Graceful fallback during seam interpolation: keep endpoint "from" visible
        -- if "to" projection is temporarily unavailable (prevents one-frame flash).
        if t ~= nil and t < 1 then
            local fromMapGroup = tonumber(remotePos and remotePos.transitionFromMapGroup)
            local fromMapId = tonumber(remotePos and remotePos.transitionFromMapId)
            local transitionFromX = tonumber(remotePos and remotePos.transitionFromX)
            local transitionFromY = tonumber(remotePos and remotePos.transitionFromY)
            if fromMapGroup ~= nil and fromMapId ~= nil and transitionFromX ~= nil and transitionFromY ~= nil then
                local fromPos = {
                    x = transitionFromX,
                    y = transitionFromY,
                    mapGroup = fromMapGroup,
                    mapId = fromMapId,
                    mapRev = remotePos.mapRev,
                    metaStable = remotePos.metaStable,
                    metaHash = remotePos.metaHash,
                }
                local fallbackX, fallbackY = projectGhostTilePosition(localPos, fromPos, playerId)
                if fallbackX ~= nil and fallbackY ~= nil then
                    if playerId ~= nil then
                        projectedPosCache[playerId] = {
                            x = fallbackX,
                            y = fallbackY,
                            crossMap = true,
                            tick = renderTick,
                        }
                    end
                    return fallbackX, fallbackY, true
                end
            end
        end

        -- Anti-flash fallback: keep last projected position while metadata is
        -- settling or seam interpolation is still in flight.
        local holdFrames = PROJECTED_POS_CACHE_TTL
        if (t ~= nil and t < 1) or (remotePos and remotePos.metaStable ~= true) then
            holdFrames = math.max(holdFrames, PROJECTION_SETTLE_GRACE_FRAMES)
        end
        local cached = playerId and projectedPosCache[playerId] or nil
        if cached and tonumber(cached.tick) and (renderTick - cached.tick) <= holdFrames then
            return cached.x, cached.y, cached.crossMap == true
        end
        return nil, nil, nil
    end

    -- Optional seam interpolation payload (produced by interpolate.lua):
    -- blend in projected/local space to avoid mixing coordinates from two maps.
    if t == nil or t <= 0 or t >= 1 then
        if playerId ~= nil then
            projectedPosCache[playerId] = {
                x = projectedToX,
                y = projectedToY,
                crossMap = isCrossMap == true,
                tick = renderTick,
            }
        end
        return projectedToX, projectedToY, isCrossMap
    end

    local fromMapGroup = tonumber(remotePos.transitionFromMapGroup)
    local fromMapId = tonumber(remotePos.transitionFromMapId)
    local toMapGroup = tonumber(remotePos.mapGroup)
    local toMapId = tonumber(remotePos.mapId)
    if fromMapGroup == nil or fromMapId == nil or toMapGroup == nil or toMapId == nil then
        if playerId ~= nil then
            projectedPosCache[playerId] = {
                x = projectedToX,
                y = projectedToY,
                crossMap = isCrossMap == true,
                tick = renderTick,
            }
        end
        return projectedToX, projectedToY, isCrossMap
    end
    if fromMapGroup == toMapGroup and fromMapId == toMapId then
        if playerId ~= nil then
            projectedPosCache[playerId] = {
                x = projectedToX,
                y = projectedToY,
                crossMap = isCrossMap == true,
                tick = renderTick,
            }
        end
        return projectedToX, projectedToY, isCrossMap
    end

    local projectedFromX, projectedFromY = nil, nil

    -- First try direct projection of transitionFrom endpoint.
    local transitionFromX = tonumber(remotePos.transitionFromX)
    local transitionFromY = tonumber(remotePos.transitionFromY)
    if transitionFromX ~= nil and transitionFromY ~= nil then
        local fromPos = {
            x = transitionFromX,
            y = transitionFromY,
            mapGroup = fromMapGroup,
            mapId = fromMapId,
            mapRev = remotePos.mapRev,
            metaStable = remotePos.metaStable,
            metaHash = remotePos.metaHash,
        }
        projectedFromX, projectedFromY = projectGhostTilePosition(localPos, fromPos, playerId)
    end

    -- If metadata is not enough to project from-map endpoint, derive it from
    -- the known seam direction: fromProjected = toProjected - 1 tile along movement.
    if projectedFromX == nil or projectedFromY == nil then
        local stepDx, stepDy = seamStepDeltaForLocalMap(localPos, fromMapGroup, fromMapId, toMapGroup, toMapId)
        if stepDx ~= nil and stepDy ~= nil then
            projectedFromX = projectedToX - stepDx
            projectedFromY = projectedToY - stepDy
        end
    end

    if projectedFromX == nil or projectedFromY == nil then
        if playerId ~= nil then
            projectedPosCache[playerId] = {
                x = projectedToX,
                y = projectedToY,
                crossMap = isCrossMap == true,
                tick = renderTick,
            }
        end
        return projectedToX, projectedToY, isCrossMap
    end

    if t < 0 then t = 0 end
    if t > 1 then t = 1 end
    local blendedX = projectedFromX + (projectedToX - projectedFromX) * t
    local blendedY = projectedFromY + (projectedToY - projectedFromY) * t
    if playerId ~= nil then
        projectedPosCache[playerId] = {
            x = blendedX,
            y = blendedY,
            crossMap = true,
            tick = renderTick,
        }
    end
    return blendedX, blendedY, true
end

local function ghostToScreen(ghostX, ghostY, playerX, playerY, useSubTile)
    local sx = 0
    local sy = 0
    if useSubTile then
        sx = subTileX
        sy = subTileY
    end
    local screenX = math.floor(PLAYER_SCREEN_X + (ghostX - playerX) * TILE_SIZE + sx)
    local screenY = math.floor(PLAYER_SCREEN_Y + (ghostY - playerY) * TILE_SIZE + sy)
    return screenX, screenY
end

local function rectOnScreen(x, y, w, h)
    return x < SCREEN_WIDTH and y < SCREEN_HEIGHT and (x + w) > 0 and (y + h) > 0
end

local function rectsOverlap(ax, ay, aw, ah, bx, by, bw, bh)
    return ax < (bx + bw)
        and ay < (by + bh)
        and (ax + aw) > bx
        and (ay + ah) > by
end

local function clearPreviousInjectedOAM()
    for _, oamIndex in ipairs(previousOAM) do
        HAL.hideOAMEntry(oamIndex)
        ownedGhostOAM[oamIndex] = nil
        oamLastWriteTick[oamIndex] = nil
    end
    previousOAM = {}
end

local function hideReservedGhostOAM()
    local hidden = {}
    for _, oamIndex in ipairs(previousOAM) do
        if oamIndex ~= nil and not hidden[oamIndex] then
            HAL.hideOAMEntry(oamIndex)
            hidden[oamIndex] = true
        end
    end
    previousOAM = {}

    for oamIndex, _ in pairs(ownedGhostOAM) do
        if oamIndex ~= nil and not hidden[oamIndex] then
            HAL.hideOAMEntry(oamIndex)
            hidden[oamIndex] = true
        end
        oamLastWriteTick[oamIndex] = nil
    end
    ownedGhostOAM = {}
end

local function rebuildPreviousOAMFromOwned()
    previousOAM = {}
    for oamIndex, _ in pairs(ownedGhostOAM) do
        previousOAM[#previousOAM + 1] = oamIndex
    end
end

local function reconcileGhostOAMVisibility(currentFrameOAM)
    local keepOwned = {}
    for i = 1, #activeGhostOAMIndices do
        local oamIndex = activeGhostOAMIndices[i]
        if oamIndex ~= nil then
            if currentFrameOAM[oamIndex] then
                keepOwned[oamIndex] = true
            else
                local lastTick = tonumber(oamLastWriteTick[oamIndex]) or -9999
                if (renderTick - lastTick) <= OAM_MISS_GRACE_FRAMES then
                    keepOwned[oamIndex] = true
                else
                    HAL.hideOAMEntry(oamIndex)
                    oamLastWriteTick[oamIndex] = nil
                end
            end
        end
    end
    ownedGhostOAM = keepOwned
    rebuildPreviousOAMFromOwned()
end

local function clearSlotAssignments()
    slotByPlayer = {}
    ownerBySlot = {}
    slotSpriteHash = {}
    slotLastVRAMWriteTick = {}
    paletteHashBySlot = {}
    lastRenderedGhostByPlayer = {}
    overlayFrontTracker = {}
end

local function releaseInactiveSlots(activePlayers)
    for playerId, slot in pairs(slotByPlayer) do
        if not activePlayers[playerId] then
            slotByPlayer[playerId] = nil
            if ownerBySlot[slot] == playerId then
                ownerBySlot[slot] = nil
            end
            slotSpriteHash[slot] = nil
            slotLastVRAMWriteTick[slot] = nil
        end
    end
end

local function allocateVramSlot(playerId, usedSlots)
    local existing = slotByPlayer[playerId]
    if existing ~= nil and not usedSlots[existing] then
        usedSlots[existing] = true
        ownerBySlot[existing] = playerId
        return existing
    end

    for slot = 0, ACTIVE_GHOST_SLOTS - 1 do
        if not usedSlots[slot] and (ownerBySlot[slot] == nil or ownerBySlot[slot] == playerId) then
            if ownerBySlot[slot] ~= playerId then
                slotSpriteHash[slot] = nil
                slotLastVRAMWriteTick[slot] = nil
            end
            slotByPlayer[playerId] = slot
            ownerBySlot[slot] = playerId
            usedSlots[slot] = true
            return slot
        end
    end
    return nil
end

local function assignPaletteSlots(ghosts)
    local paletteMap = {}
    local nextPalette = 1

    for _, ghost in ipairs(ghosts) do
        local renderData = ghost.renderData
        local palBank = renderData and tonumber(renderData.palBank) or nil
        local hasNativePalBank = palBank and palBank >= 0 and palBank <= 15
        local allowNativePalBank = hasNativePalBank and (PREFER_NATIVE_PALBANK or not (renderData and renderData.paletteHash))

        if allowNativePalBank then
            ghost.nativePalBank = palBank
            ghost.paletteSlot = nil
        else
            ghost.nativePalBank = nil
            local hashKey = renderData and tostring(renderData.paletteHash or "") or ""
            if hashKey ~= "" then
                local slot = paletteMap[hashKey]
                if not slot then
                    if nextPalette <= #RESERVED_PALETTE_SLOTS then
                        slot = RESERVED_PALETTE_SLOTS[nextPalette]
                        nextPalette = nextPalette + 1
                        paletteMap[hashKey] = slot
                    end
                end
                ghost.paletteSlot = slot
            else
                ghost.paletteSlot = nil
            end
        end
    end
end

local function rememberRenderedGhost(ghost)
    if not ghost or not ghost.playerId then
        return
    end
    lastRenderedGhostByPlayer[ghost.playerId] = {
        playerId = ghost.playerId,
        drawX = ghost.drawX,
        drawY = ghost.drawY,
        screenX = ghost.screenX,
        screenY = ghost.screenY,
        width = ghost.width,
        height = ghost.height,
        y = ghost.y,
        state = ghost.state,
        crossMap = ghost.crossMap == true,
        forceOverlayFront = ghost.forceOverlayFront == true,
        oamPriority = ghost.oamPriority,
        vramSlot = ghost.vramSlot,
        nativePalBank = ghost.nativePalBank,
        paletteSlot = ghost.paletteSlot,
        renderData = ghost.renderData,
        tick = renderTick,
    }
end

local function appendStaleGhosts(ghosts, otherPlayers)
    if type(ghosts) ~= "table" or type(otherPlayers) ~= "table" then
        return
    end

    local present = {}
    for i = 1, #ghosts do
        local playerId = ghosts[i] and ghosts[i].playerId
        if playerId ~= nil then
            present[playerId] = true
        end
    end

    for playerId, _ in pairs(otherPlayers) do
        if not present[playerId] then
            local snapshot = lastRenderedGhostByPlayer[playerId]
            local lastTick = snapshot and tonumber(snapshot.tick) or nil
            if lastTick ~= nil and (renderTick - lastTick) <= OAM_MISS_GRACE_FRAMES then
                local staleData = (Sprite and Sprite.getGhostRenderData and Sprite.getGhostRenderData(playerId))
                    or snapshot.renderData

                ghosts[#ghosts + 1] = {
                    playerId = playerId,
                    state = snapshot.state or "idle",
                    crossMap = snapshot.crossMap and true or false,
                    renderData = staleData,
                    screenX = snapshot.screenX,
                    screenY = snapshot.screenY,
                    drawX = snapshot.drawX,
                    drawY = snapshot.drawY,
                    width = snapshot.width,
                    height = snapshot.height,
                    y = snapshot.y or 0,
                    distance = 9999,
                    forceOverlayFront = snapshot.forceOverlayFront == true,
                    oamPriority = snapshot.oamPriority,
                    stale = true,
                }
            end
        end
    end
end

local function pruneStaleGhostSnapshots(otherPlayers)
    if type(otherPlayers) ~= "table" then
        lastRenderedGhostByPlayer = {}
        return
    end

    for playerId, snapshot in pairs(lastRenderedGhostByPlayer) do
        if otherPlayers[playerId] == nil then
            lastRenderedGhostByPlayer[playerId] = nil
        else
            local lastTick = tonumber(snapshot and snapshot.tick) or -9999
            if (renderTick - lastTick) > (OAM_MISS_GRACE_FRAMES + 4) then
                lastRenderedGhostByPlayer[playerId] = nil
            end
        end
    end
end

local function resolveForceOverlayFront(playerId, desiredFront)
    if not ENABLE_FORCE_OVERLAY_FRONT or playerId == nil then
        return false
    end

    local tracker = overlayFrontTracker[playerId]
    if not tracker then
        tracker = {
            isFront = false,
            desiredCount = 0,
            releaseTick = -9999,
        }
        overlayFrontTracker[playerId] = tracker
    end

    if desiredFront then
        if tracker.isFront then
            tracker.desiredCount = OVERLAY_FRONT_ENABLE_CONFIRM_FRAMES
            tracker.releaseTick = renderTick + OVERLAY_FRONT_RELEASE_GRACE_FRAMES
            return true
        end

        tracker.desiredCount = (tracker.desiredCount or 0) + 1
        if tracker.desiredCount >= OVERLAY_FRONT_ENABLE_CONFIRM_FRAMES then
            tracker.isFront = true
            tracker.desiredCount = OVERLAY_FRONT_ENABLE_CONFIRM_FRAMES
            tracker.releaseTick = renderTick + OVERLAY_FRONT_RELEASE_GRACE_FRAMES
            return true
        end
        return false
    end

    tracker.desiredCount = 0
    if tracker.isFront and renderTick <= (tracker.releaseTick or -9999) then
        return true
    end

    tracker.isFront = false
    return false
end

local function drawGhostOverlayImage(overlayImage, ghost)
    if not overlayImage or not ghost or not ghost.playerId then
        return false
    end
    if not Sprite or not Sprite.getImageForPlayer then
        return false
    end

    local imgOk, spriteImg, spriteW, spriteH = pcall(Sprite.getImageForPlayer, ghost.playerId)
    if not imgOk or not spriteImg or not spriteW or not spriteH or spriteW <= 0 or spriteH <= 0 then
        return false
    end

    local drawX = ghost.screenX - math.floor((spriteW - TILE_SIZE) / 2)
    local drawY = ghost.screenY - (spriteH - TILE_SIZE)
    local drawOk = pcall(overlayImage.drawImage, overlayImage, spriteImg, drawX, drawY)
    if not drawOk then
        return false
    end

    ghost.drawX = drawX
    ghost.drawY = drawY
    ghost.width = spriteW
    ghost.height = spriteH
    return true
end

local function drawFallbackGhost(painter, overlayImage, ghost)
    if drawGhostOverlayImage(overlayImage, ghost) then
        return
    end

    local fillColor = (ghost.state and STATE_COLORS[ghost.state]) or GHOST_COLOR
    local outlineColor = (ghost.state and STATE_OUTLINES[ghost.state]) or GHOST_OUTLINE

    painter:setFill(true)
    painter:setStrokeWidth(0)
    painter:setFillColor(fillColor)
    painter:drawRectangle(ghost.screenX + 1, ghost.screenY + 1, GHOST_SIZE, GHOST_SIZE)

    painter:setFill(false)
    painter:setStrokeWidth(1)
    painter:setStrokeColor(outlineColor)
    painter:drawRectangle(ghost.screenX + 1, ghost.screenY + 1, GHOST_SIZE, GHOST_SIZE)
    painter:setFill(true)
    painter:setStrokeWidth(0)
end

local function writeGhostOAMEntry(ghost, oamIndex)
    local shapeSize = oamShapeSizeForDimensions(ghost.width, ghost.height)
    if not shapeSize then
        return false
    end

    local tileIndex = HAL.getGhostTileIndex(ghost.vramSlot)
    if tileIndex == nil then
        return false
    end

    local y = ghost.drawY
    local x = ghost.drawX
    if y < 0 then y = y + 256 end
    if x < 0 then x = x + 512 end

    local attr0 = (y & 0xFF) | ((shapeSize.shape & 0x3) << 14)
    local attr1 = (x & 0x1FF) | ((shapeSize.size & 0x3) << 14)
    if ghost.renderData.hFlip then attr1 = attr1 | (1 << 12) end
    if ghost.renderData.vFlip then attr1 = attr1 | (1 << 13) end

    local palBank = ghost.nativePalBank or ghost.paletteSlot or RESERVED_PALETTE_SLOTS[1]
    local priority = tonumber(ghost and ghost.oamPriority)
    if priority == nil then
        priority = OAM_PRIORITY_BACK
    end
    if priority < 0 then priority = 0 end
    if priority > 3 then priority = 3 end
    local attr2 = (tileIndex & 0x3FF) | ((priority & 0x3) << 10) | ((palBank & 0xF) << 12)

    return HAL.writeOAMEntry(oamIndex, attr0, attr1, attr2)
end

local function collectVisibleGhosts(otherPlayers, playerPos)
    local ghostList = {}
    local localW, localH = TILE_SIZE, (TILE_SIZE * 2)
    if Sprite and Sprite.getLocalImage then
        local _, w, h = Sprite.getLocalImage()
        if w and w > 0 then
            localW = w
        end
        if h and h > 0 then
            localH = h
        end
    end
    local localDrawX = PLAYER_SCREEN_X - math.floor((localW - TILE_SIZE) / 2)
    local localDrawY = PLAYER_SCREEN_Y - (localH - TILE_SIZE)

    for playerId, data in pairs(otherPlayers) do
        local position, state
        if data.pos then
            position = data.pos
            state = data.state
        else
            position = data
        end

        local projectedX, projectedY, isCrossMap = resolveProjectedGhostTilePosition(playerPos, position, playerId)
        if projectedX ~= nil and projectedY ~= nil then
            local screenX, screenY = ghostToScreen(
                projectedX,
                projectedY,
                playerPos.x,
                playerPos.y,
                true
            )
            local renderData = Sprite and Sprite.getGhostRenderData and Sprite.getGhostRenderData(playerId) or nil

            local width = (renderData and renderData.width) or TILE_SIZE
            local height = (renderData and renderData.height) or (TILE_SIZE * 2)
            if (not renderData) and Sprite and Sprite.getImageForPlayer then
                local _, cachedW, cachedH = Sprite.getImageForPlayer(playerId)
                if cachedW and cachedW > 0 then
                    width = cachedW
                end
                if cachedH and cachedH > 0 then
                    height = cachedH
                end
            end

            local drawX = screenX - math.floor((width - TILE_SIZE) / 2)
            local drawY = screenY - (height - TILE_SIZE)
            if rectOnScreen(drawX, drawY, width, height) then
                local dx = projectedX - playerPos.x
                local dy = projectedY - playerPos.y
                local overlapsLocal = rectsOverlap(
                    drawX, drawY, width, height,
                    localDrawX, localDrawY, localW, localH
                )
                local desiredOverlayFront = overlapsLocal and (projectedY > playerPos.y)
                local forceOverlayFront = resolveForceOverlayFront(playerId, desiredOverlayFront)
                ghostList[#ghostList + 1] = {
                    playerId = playerId,
                    position = position,
                    state = state,
                    crossMap = isCrossMap and true or false,
                    renderData = renderData,
                    screenX = screenX,
                    screenY = screenY,
                    drawX = drawX,
                    drawY = drawY,
                    width = width,
                    height = height,
                    y = projectedY,
                    distance = math.abs(dx) + math.abs(dy),
                    forceOverlayFront = forceOverlayFront,
                    oamPriority = forceOverlayFront and OAM_PRIORITY_FRONT or OAM_PRIORITY_BACK,
                }
            end
        end
    end

    for trackedId, _ in pairs(projectionMetaState) do
        if otherPlayers[trackedId] == nil then
            projectionMetaState[trackedId] = nil
        end
    end
    for trackedId, _ in pairs(projectedPosCache) do
        if otherPlayers[trackedId] == nil then
            projectedPosCache[trackedId] = nil
        end
    end
    for trackedId, _ in pairs(overlayFrontTracker) do
        if otherPlayers[trackedId] == nil then
            overlayFrontTracker[trackedId] = nil
        end
    end

    table.sort(ghostList, function(a, b)
        if a.distance ~= b.distance then
            return a.distance < b.distance
        end
        return a.y < b.y
    end)

    if #ghostList > ACTIVE_GHOST_SLOTS then
        local trimmed = {}
        for i = 1, ACTIVE_GHOST_SLOTS do
            trimmed[i] = ghostList[i]
        end
        ghostList = trimmed
    end

    table.sort(ghostList, function(a, b) return a.y < b.y end)
    return ghostList
end

function Render.init(config)
    local renderConfig = (type(config) == "table" and type(config.render) == "table") and config.render or {}
    MAX_GHOSTS = HAL.getGhostMaxSlots() or MAX_GHOSTS or 6

    local configuredSlots = HAL.getGhostOAMSlotCount and HAL.getGhostOAMSlotCount() or nil
    if configuredSlots == nil then
        configuredSlots = renderConfig.oamReservedCount
    end
    ACTIVE_GHOST_SLOTS = clampInt(configuredSlots, 1, MAX_GHOSTS, MAX_GHOSTS)

    if HAL.getGhostOAMStrategy then
        OAM_STRATEGY = HAL.getGhostOAMStrategy() or "fixed"
    elseif renderConfig.oamStrategy == "dynamic" then
        OAM_STRATEGY = "dynamic"
    else
        OAM_STRATEGY = "fixed"
    end

    if renderConfig.enableRemoteConnectionFallback ~= nil then
        USE_REMOTE_CONNECTION_FALLBACK = renderConfig.enableRemoteConnectionFallback == true
    end

    if renderConfig.vramRefreshIntervalFrames ~= nil then
        VRAM_REFRESH_INTERVAL_FRAMES = clampInt(renderConfig.vramRefreshIntervalFrames, 0, 600, VRAM_REFRESH_INTERVAL_FRAMES)
    end
    if renderConfig.oamPriorityBack ~= nil then
        OAM_PRIORITY_BACK = clampInt(renderConfig.oamPriorityBack, 0, 3, OAM_PRIORITY_BACK)
    end
    if renderConfig.oamPriorityFront ~= nil then
        OAM_PRIORITY_FRONT = clampInt(renderConfig.oamPriorityFront, 0, 3, OAM_PRIORITY_FRONT)
    end
    if renderConfig.projectionCacheTTLFrames ~= nil then
        PROJECTED_POS_CACHE_TTL = clampInt(renderConfig.projectionCacheTTLFrames, 1, 60, PROJECTED_POS_CACHE_TTL)
    end
    if renderConfig.projectionSettleGraceFrames ~= nil then
        PROJECTION_SETTLE_GRACE_FRAMES = clampInt(renderConfig.projectionSettleGraceFrames, 1, 120, PROJECTION_SETTLE_GRACE_FRAMES)
    end
    if renderConfig.oamMissGraceFrames ~= nil then
        OAM_MISS_GRACE_FRAMES = clampInt(renderConfig.oamMissGraceFrames, 0, 30, OAM_MISS_GRACE_FRAMES)
    end
    if renderConfig.preferNativePalBank ~= nil then
        PREFER_NATIVE_PALBANK = renderConfig.preferNativePalBank == true
    end
    if renderConfig.forceOverlayFront ~= nil then
        ENABLE_FORCE_OVERLAY_FRONT = renderConfig.forceOverlayFront == true
    end
    if renderConfig.forceOverlayFrontConfirmFrames ~= nil then
        OVERLAY_FRONT_ENABLE_CONFIRM_FRAMES = clampInt(renderConfig.forceOverlayFrontConfirmFrames, 1, 8, OVERLAY_FRONT_ENABLE_CONFIRM_FRAMES)
    end
    if renderConfig.forceOverlayFrontReleaseGraceFrames ~= nil then
        OVERLAY_FRONT_RELEASE_GRACE_FRAMES = clampInt(renderConfig.forceOverlayFrontReleaseGraceFrames, 0, 30, OVERLAY_FRONT_RELEASE_GRACE_FRAMES)
    end

    resetCameraTrackingState(0)
    projectionMetaState = {}
    projectedPosCache = {}
    renderTick = 0
    ownedGhostOAM = {}
    activeGhostOAMIndices = {}
    slotLastVRAMWriteTick = {}
    oamLastWriteTick = {}
    clearPreviousInjectedOAM()
    hideReservedGhostOAM()
    clearSlotAssignments()
    ensureGhostOAMReservation(true)
end

--[[
  Update sub-tile camera correction. Call once per frame before drawing.
]]
function Render.updateCamera(playerX, playerY, cameraX, cameraY, mapGroup, mapId)
    if not cameraX or not cameraY then
        resetCameraTrackingState(0)
        return
    end

    local camX = math.floor(tonumber(cameraX) or 0)
    local camY = math.floor(tonumber(cameraY) or 0)
    local prevCamForDeltaX = prevCamX
    local prevCamForDeltaY = prevCamY

    local previousMapKey = lastCameraMapKey
    local currentMapKey = buildMapKey(mapGroup, mapId)
    local mapChangedThisFrame = false
    if currentMapKey and previousMapKey and currentMapKey ~= previousMapKey then
        mapChangedThisFrame = true
    end
    if currentMapKey then
        -- Map-change reset policy is controlled by caller (main.lua) via
        -- Render.clearGhostCache(resetCameraTracking=...).
        -- Do not auto-reset here, otherwise seam transitions force ST=0 mid-step.
        lastCameraMapKey = currentMapKey
    end

    if cameraWarmupFrames > 0 then
        cameraWarmupFrames = cameraWarmupFrames - 1
        subTileX, subTileY = 0, 0
        stepDirX, stepDirY = 0, 0
        prevCamX, prevCamY = camX, camY
        prevTileX, prevTileY = playerX, playerY
        return
    end

    if prevTileX == nil or prevTileY == nil then
        subTileX, subTileY = 0, 0
        stepDirX, stepDirY = 0, 0
        prevCamX, prevCamY = camX, camY
        prevTileX, prevTileY = playerX, playerY
        return
    end

    local deltaTileX = playerX - prevTileX
    local deltaTileY = playerY - prevTileY
    local largeTileDelta = math.abs(deltaTileX) > 2 or math.abs(deltaTileY) > 2
    if largeTileDelta and not mapChangedThisFrame then
        -- Teleport/map churn safety.
        stepDirX, stepDirY = 0, 0
        subTileX, subTileY = 0, 0
        prevCamX, prevCamY = camX, camY
        prevTileX, prevTileY = playerX, playerY
        return
    end

    -- Seam transitions can wrap tile coordinates (e.g. y: 19 -> 0) while the
    -- scrolling step is still in progress. In that case, keep the previous
    -- movement axis instead of deriving it from wrapped tile deltas.
    local keepStepDirX = mapChangedThisFrame and math.abs(deltaTileX) > 2
    local keepStepDirY = mapChangedThisFrame and math.abs(deltaTileY) > 2
    if not keepStepDirX and deltaTileX ~= 0 then
        stepDirX = (deltaTileX > 0) and 1 or -1
    end
    if not keepStepDirY and deltaTileY ~= 0 then
        stepDirY = (deltaTileY > 0) and 1 or -1
    end

    -- GBAPK-style absolute camera sub-tile phase.
    local camXByte = ((camX % 256) + 256) % 256
    local camYByte = ((camY % 256) + 256) % 256
    local phaseX = (256 - camXByte) % TILE_SIZE
    local phaseY = (256 - camYByte) % TILE_SIZE

    -- Fallback for seam crossings with wrapped local tile coords (e.g. y 19 -> 0):
    -- infer movement axis from signed camera byte delta when stepDir was not
    -- recoverable from tile delta in this frame.
    local function signedByteDelta(curr, prev)
        if prev == nil then
            return 0
        end
        local d = (curr - prev) % 256
        if d > 127 then
            d = d - 256
        end
        return d
    end
    local camDeltaX = signedByteDelta(camXByte, prevCamForDeltaX)
    local camDeltaY = signedByteDelta(camYByte, prevCamForDeltaY)
    if stepDirX == 0 and phaseX ~= 0 then
        if camDeltaX > 0 then
            stepDirX = -1
        elseif camDeltaX < 0 then
            stepDirX = 1
        end
    end
    if stepDirY == 0 and phaseY ~= 0 then
        if camDeltaY > 0 then
            stepDirY = -1
        elseif camDeltaY < 0 then
            stepDirY = 1
        end
    end

    -- Local tile coordinates can switch to the destination tile before camera
    -- scrolling completes. In that case we must use the remaining sub-tile
    -- distance (TILE_SIZE - phase), not phase itself, to avoid a one-frame
    -- opposite jump (e.g. 112 -> 97 -> 112).
    local function remainingStepOffset(stepDir, phase)
        if stepDir == 0 or phase == 0 then
            return 0
        end
        -- Directional magnitude:
        --   stepDir > 0 (right/down): use remaining distance (16 - phase)
        --   stepDir < 0 (left/up):   use phase directly
        -- This avoids opposite-direction jumps at step start on negative axes.
        local magnitude
        if stepDir > 0 then
            magnitude = TILE_SIZE - phase
        else
            magnitude = phase
        end
        if magnitude <= 0 or magnitude >= TILE_SIZE then
            return 0
        end
        return stepDir * magnitude
    end

    local effectiveX = remainingStepOffset(stepDirX, phaseX)
    local effectiveY = remainingStepOffset(stepDirY, phaseY)

    if FORCE_ZERO_SUBTILE_OFFSET then
        subTileX = 0
        subTileY = 0
    else
        subTileX = effectiveX
        subTileY = effectiveY
    end

    -- Clear movement axis once the phase returns to zero and tile is stable.
    if deltaTileX == 0 and phaseX == 0 then
        stepDirX = 0
    end
    if deltaTileY == 0 and phaseY == 0 then
        stepDirY = 0
    end

    prevCamX, prevCamY = camX, camY
    prevTileX, prevTileY = playerX, playerY
end

function Render.setSprite(spriteModule)
    Sprite = spriteModule
end

--[[
  Remove all injected ghost OAM entries and clear injection caches.
  Call on map changes or when leaving the overworld.
  options:
    resetCameraTracking=true|false (default true)
    dropProjectionState=true|false (default true)
    preserveCamera=true (legacy alias for resetCameraTracking=false)
]]
function Render.clearGhostCache(options)
    options = options or {}
    local resetCameraTracking = true
    if options.resetCameraTracking ~= nil then
        resetCameraTracking = options.resetCameraTracking == true
    elseif options.preserveCamera == true then
        resetCameraTracking = false
    end
    local dropProjectionState = options.dropProjectionState ~= false

    clearPreviousInjectedOAM()
    hideReservedGhostOAM()
    clearSlotAssignments()
    ensureGhostOAMReservation(OAM_STRATEGY == "dynamic")
    if dropProjectionState then
        projectionMetaState = {}
        projectedPosCache = {}
    end
    if resetCameraTracking then
        resetCameraTrackingState(CAMERA_WARMUP_FRAMES)
    end
end

function Render.getCameraDebugState()
    return {
        subTileX = subTileX,
        subTileY = subTileY,
        prevCamX = prevCamX,
        prevCamY = prevCamY,
        prevTileX = prevTileX,
        prevTileY = prevTileY,
        stepDirX = stepDirX,
        stepDirY = stepDirY,
        mapKey = lastCameraMapKey,
        warmupFrames = cameraWarmupFrames,
    }
end

--[[
  Debug helper: compute projected world position + screen position for a remote
  player using the exact same path as the renderer.
]]
function Render.getDebugProjectionSnapshot(localPos, remotePos, playerId)
    if type(localPos) ~= "table" or type(remotePos) ~= "table" then
        return nil
    end

    local snapshot = {
        crossMap = false,
        subTileX = subTileX,
        subTileY = subTileY,
        projected = nil,
        screen = nil,
    }

    local projectedX, projectedY, isCrossMap = resolveProjectedGhostTilePosition(localPos, remotePos, playerId)
    snapshot.crossMap = (isCrossMap == true)
    if projectedX == nil or projectedY == nil then
        return snapshot
    end

    snapshot.projected = {
        x = projectedX,
        y = projectedY,
        mapGroup = localPos.mapGroup,
        mapId = localPos.mapId,
    }

    local screenX, screenY = ghostToScreen(projectedX, projectedY, localPos.x, localPos.y, true)
    snapshot.screen = {
        x = screenX,
        y = screenY,
    }

    return snapshot
end

function Render.hideGhosts()
    clearPreviousInjectedOAM()
    hideReservedGhostOAM()
    lastRenderedGhostByPlayer = {}
    ensureGhostOAMReservation(OAM_STRATEGY == "dynamic")
    projectionMetaState = {}
    projectedPosCache = {}
end

--[[
  Record an observed local map transition offset.
  fromPos/toPos are the two consecutive local positions around the transition.
  Stores a direction-specific mapping:
    projection(fromMap <- toMap): projected = remote + (from - to)
]]
function Render.recordMapTransitionSample(fromPos, toPos, transitionType)
    return false
end

--[[
  Draw all ghost players:
  - write remote sprites to OBJ VRAM/palette if changed
  - write OAM entries each frame
]]
function Render.drawAllGhosts(painter, overlayImage, otherPlayers, playerPos)
    if not otherPlayers or not painter or not playerPos then
        return 0
    end

    renderTick = renderTick + 1
    pruneStaleGhostSnapshots(otherPlayers)

    ensureGhostOAMReservation(false)

    local ghosts = collectVisibleGhosts(otherPlayers, playerPos)
    appendStaleGhosts(ghosts, otherPlayers)
    table.sort(ghosts, function(a, b)
        return (a.y or 0) < (b.y or 0)
    end)
    local currentFrameOAM = {}
    if #ghosts == 0 then
        reconcileGhostOAMVisibility(currentFrameOAM)
        return 0
    end

    local activePlayers = {}
    for _, ghost in ipairs(ghosts) do
        activePlayers[ghost.playerId] = true
    end
    releaseInactiveSlots(activePlayers)
    assignPaletteSlots(ghosts)

    local usedSlots = {}
    for _, ghost in ipairs(ghosts) do
        local data = ghost.renderData
        if data and data.tileBytes and oamShapeSizeForDimensions(ghost.width, ghost.height) then
            local vramSlot = allocateVramSlot(ghost.playerId, usedSlots)
            if vramSlot ~= nil then
                ghost.vramSlot = vramSlot
            end
        end
    end

    local writtenPaletteThisFrame = {}
    local renderedCount = 0

    for _, ghost in ipairs(ghosts) do
        local rendered = false
        local data = ghost.renderData

        if data and ghost.vramSlot ~= nil then
            local spriteKey = data.spriteHash or tostring(data.revision or 0)
            local needsVramWrite = slotSpriteHash[ghost.vramSlot] ~= spriteKey
            if not needsVramWrite and VRAM_REFRESH_INTERVAL_FRAMES > 0 then
                local lastWriteTick = slotLastVRAMWriteTick[ghost.vramSlot]
                if not lastWriteTick or (renderTick - lastWriteTick) >= VRAM_REFRESH_INTERVAL_FRAMES then
                    needsVramWrite = true
                end
            end

            if needsVramWrite then
                if HAL.writeGhostTilesToVRAM(ghost.vramSlot, data.tileBytes) then
                    slotSpriteHash[ghost.vramSlot] = spriteKey
                    slotLastVRAMWriteTick[ghost.vramSlot] = renderTick
                else
                    slotLastVRAMWriteTick[ghost.vramSlot] = nil
                    ghost.vramSlot = nil
                end
            end

            if ghost.vramSlot ~= nil then
                -- Palette selection is precomputed in assignPaletteSlots():
                -- either a native sender palBank, or one of our reserved slots.
                if not ghost.nativePalBank then
                    local paletteSlot = ghost.paletteSlot
                    if paletteSlot and data.paletteBgr then
                        if not writtenPaletteThisFrame[paletteSlot] then
                            local paletteKey = tostring(data.paletteHash or "")
                            if HAL.writeGhostPalette(paletteSlot, data.paletteBgr) then
                                paletteHashBySlot[paletteSlot] = paletteKey
                                writtenPaletteThisFrame[paletteSlot] = true
                            else
                                ghost.vramSlot = nil
                            end
                        end
                    else
                        ghost.vramSlot = nil
                    end
                end

                local oamIndex = getReservedOAMIndexForSlot(ghost.vramSlot)
                if ghost.vramSlot ~= nil and oamIndex and writeGhostOAMEntry(ghost, oamIndex) then
                    currentFrameOAM[oamIndex] = true
                    ownedGhostOAM[oamIndex] = true
                    oamLastWriteTick[oamIndex] = renderTick
                    -- Do not refresh stale snapshots with stale renders.
                    -- Otherwise a ghost that is no longer projectable (e.g. interior vs exterior)
                    -- can keep itself alive forever through appendStaleGhosts().
                    if not ghost.stale then
                        rememberRenderedGhost(ghost)
                    end
                    rendered = true
                    renderedCount = renderedCount + 1
                end
            end
        end

        if ghost.forceOverlayFront then
            if drawGhostOverlayImage(overlayImage, ghost) then
                rendered = true
            end
        end

        if not rendered and not ghost.stale then
            local keepStaleOAM = false
            if ghost.vramSlot ~= nil then
                local stickyOAMIndex = getReservedOAMIndexForSlot(ghost.vramSlot)
                local stickyLastTick = stickyOAMIndex and tonumber(oamLastWriteTick[stickyOAMIndex]) or nil
                keepStaleOAM = stickyLastTick ~= nil and (renderTick - stickyLastTick) <= OAM_MISS_GRACE_FRAMES
            end
            if not keepStaleOAM then
                drawFallbackGhost(painter, overlayImage, ghost)
            end
        end

    end

    reconcileGhostOAMVisibility(currentFrameOAM)
    return renderedCount
end

return Render
