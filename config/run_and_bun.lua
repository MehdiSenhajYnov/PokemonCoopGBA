--[[
  Pokémon Run & Bun Configuration

  ROM hack based on Pokémon Emerald, built on pokeemerald-expansion (RHH)
  Game ID: BPEE (same as Emerald)
  Creator: dekzeh

  Offsets found via mGBA memory scanning on: 2026-02-02
  Camera offsets found on: 2026-02-03
  Party addresses corrected on: 2026-02-05 (cross-referenced with pokemon-run-bun-exporter)
  Method: STATIC (player in EWRAM, camera in IWRAM)

  Reference repos (cloned in refs/):
  - refs/pokemon-run-bun-exporter  — Lua exporter with validated party addresses
  - refs/runandbundex               — Official data tables (species, moves, abilities)
  - refs/pokeemerald-expansion      — Source structs and battle constants
]]

return {
  name = "Pokémon Run & Bun",
  gameId = "BPEE",
  version = "1.0",

  -- Renderer metadata (GBAPK-style injection into engine OAM buffer)
  -- gMain is in IWRAM at 0x030022C0, oamBuffer starts at +0x38.
  render = {
    gMainAddr = 0x030022C0,
    oamBufferOffset = 0x38,
    oamBaseIndex = 110, -- GBAPK-style high OAM reservation to avoid engine churn
  },

  offsets = {
    playerX = 0x02024CBC,     -- 16-bit
    playerY = 0x02024CBE,     -- 16-bit
    mapGroup = 0x02024CC0,    -- 8-bit
    mapId = 0x02024CC1,       -- 8-bit
    facing = 0x02036934,      -- 8-bit, EWRAM

    -- Camera offsets (IWRAM 0x03000000 region - read via emu.memory.iwram)
    cameraX = 0x03005DFC,     -- s16, IWRAM (gSpriteCoordOffsetX)
    cameraY = 0x03005DF8,     -- s16, IWRAM (gSpriteCoordOffsetY)
  },

  -- Overworld map context for deterministic connected-map projection.
  -- If this fixed address is invalid in a ROM variant, HAL falls back to
  -- runtime EWRAM scan and caches the detected address.
  overworld = {
    gMapHeaderAddr = 0x02036FB8, -- vanilla Emerald BPEE reference
  },

  -- Warp system addresses
  -- CORRECTED 2026-02-07: gMain is in IWRAM at 0x030022C0 (found via SetMainCallback2 disassembly)
  -- The old EWRAM address 0x0202064C was a DIFFERENT variable, NOT gMain.callback2
  warp = {
    callback2Addr = 0x030022C4,  -- gMain.callback2 (IWRAM, gMain+0x04) — CORRECTED from 0x0202064C
    cb2LoadMap    = 0x080A3FDD,  -- CB2_LoadMap ROM (CORRECTED: 0x08007441 was SpriteCallbackDummy!)
    cb2Overworld  = 0x080A89A5,  -- CB2_Overworld ROM function pointer (for completion detect)

    -- gMain.state offset from gMain base (vanilla expansion layout: +0x438)
    -- Previously thought R&B had custom offsets, but gMain is actually vanilla layout in IWRAM
    gMainStateOffset = 0x438,    -- CORRECTED: vanilla expansion layout (was 0x65 — WRONG)

    -- sWarpData address: auto-detected at runtime by HAL.trackCallback2()
    -- After initial game load (CB2_LoadMap → CB2_Overworld), sWarpDestination matches
    -- SaveBlock1->location in EWRAM. HAL scans for this pattern automatically.
    -- Set a fixed address here only if auto-detection fails.
    sWarpDataAddr = nil,         -- AUTO-DETECTED at runtime (no manual scan needed)

    -- WarpIntoMap ROM address: auto-detected by HAL.scanROMForWarpFunction()
    -- Used by EWRAM trampoline: writes THUMB code to EWRAM that calls WarpIntoMap + CB2_LoadMap.
    -- GBA has no MMU — EWRAM is executable. This avoids needing SetCB2WarpAndLoadMap.
    -- Set manually only if auto-detection fails.
    warpIntoMapAddr = nil,       -- AUTO-DETECTED via ROM scan (Phase 1-3 or fallback)

    -- Legacy: SetCB2WarpAndLoadMap ROM address (if known, used as Priority 2)
    setCB2WarpAddr = nil,        -- Manual override only
  },

  -- Duel room coordinates (MAP_BATTLE_COLOSSEUM_2P — same as vanilla Emerald)
  duelRoom = {
    mapGroup = 28,
    mapId = 24,
    playerAX = 3,
    playerAY = 5,
    playerBX = 10,
    playerBY = 5
  },

  -- Pokemon structure constants (from pokeemerald-expansion + run-bun-exporter)
  pokemon = {
    PARTY_SIZE = 6,
    PARTY_MON_SIZE = 100,     -- sizeof(struct Pokemon) = BoxPokemon(80) + battle stats(20)
    BOX_MON_SIZE = 80,        -- sizeof(struct BoxPokemon) = header(32) + encrypted(48)
    FULL_PARTY_BYTES = 600,   -- 6 * 100

    -- PartyMon offsets from mon base address
    HP_OFFSET = 86,           -- +0x56: u16 current HP
    MAX_HP_OFFSET = 88,       -- +0x58: u16 max HP
    LEVEL_OFFSET = 84,        -- +0x54: u8 level
    STATUS_OFFSET = 80,       -- +0x50: u32 status condition
    ATTACK_OFFSET = 90,       -- +0x5A: u16
    DEFENSE_OFFSET = 92,      -- +0x5C: u16
    SPEED_OFFSET = 94,        -- +0x5E: u16
    SP_ATTACK_OFFSET = 96,    -- +0x60: u16
    SP_DEFENSE_OFFSET = 98,   -- +0x62: u16

    -- BoxMon header offsets
    PERSONALITY_OFFSET = 0,   -- +0x00: u32
    OT_ID_OFFSET = 4,         -- +0x04: u32
    NICKNAME_OFFSET = 8,      -- +0x08: 10 bytes
    ENCRYPTED_OFFSET = 32,    -- +0x20: 48 bytes (4 substructs x 12 bytes, XOR encrypted)

    -- Run & Bun specific
    NUM_SPECIES = 1234,       -- Gen 1-8 + forms (species IDs 0-1233)
    NUM_MOVES = 782,          -- Through Gen 8 "Take Heart"
    HAS_HIDDEN_NATURE = true, -- bits 16-20 of growth substruct word 2 (value 26 = use PID)
    HAS_3_ABILITIES = true,   -- altAbility uses 2 bits (0=primary, 1=secondary, 2=hidden)
  },

  -- Battle system addresses (for PvP combat)
  battle = {
    -- Party data — CORRECTED from pokemon-run-bun-exporter (community-validated)
    gPlayerParty      = 0x02023A98,  -- VERIFIED: from run-bun-exporter (was 0x020233D0 from scanner)
    gPlayerPartyCount = 0x02023A95,  -- VERIFIED: from run-bun-exporter (3 bytes before gPlayerParty)
    gEnemyParty       = 0x02023CF0,  -- DERIVED: gPlayerParty + 0x258 (600 bytes = 6 * 100)
    gEnemyPartyCount  = 0x02023A96,  -- CORRECTED: gPlayerPartyCount+1 (contiguous EWRAM_DATA in pokemon.c), NOT gEnemyParty-3
    gPokemonStorage   = 0x02028848,  -- VERIFIED: from run-bun-exporter (PC box storage)

    -- Battle state
    gBattleTypeFlags = 0x02023364,  -- CORRECTED: found via CB2_InitBattle disassembly (was 0x020090E8 — WRONG)
    gBattleOutcome = 0x02023716,    -- FOUND: u8, 0=ongoing, 1=won, 2=lost (after gBattleCommunication[8])

    -- gMain struct fields (IWRAM! CORRECTED 2026-02-07 via SetMainCallback2 disasm)
    gMainAddr = 0x030022C0,         -- gMain base address (IWRAM) — was 0x02020648 (WRONG, EWRAM)
    gMainInBattle = 0x03002AF9,     -- gMain+0x439 (IWRAM), bitfield bit 1 — was 0x020206AE (WRONG)

    -- RNG (IWRAM)
    gRngValue = 0x03005D90,         -- FOUND (changes every frame)

    -- ROM function pointers
    CB2_BattleMain = 0x0803816D,    -- CORRECTED: was 0x08094815 (sprite anim, NOT BattleMainCB2). Real BattleMainCB2 found via state 18 jump table.
    gBattlersCount = 0x020233E4,    -- u8, number of active battlers (2 for singles, 4 for doubles)

    -- ROM data tables (read-only, for display/validation)
    speciesNameTable = 0x003185C8,  -- From run-bun-exporter (ROM address, not WRAM)
  },

  -- Link Battle Emulation addresses
  -- Found via find_getmultiplayerid.py, find_rom_patch_targets.py, ROM literal pool scan
  battle_link = {
    -- ROM functions — battle initialization chain (found via Python ROM scanner 2026-02-07)
    CB2_InitBattle = 0x080363C1,                      -- FOUND: 204 bytes, 8 literal pool refs (callers use SetMainCallback2)
    CB2_InitBattleInternal = 0x0803648D,              -- FOUND: big function (~4KB, 143 BLs), called by CB2_InitBattle
    CB2_ReturnToField = 0x080A40D9,                    -- FOUND: return-to-overworld callback (52 LP refs as savedCallback)
    SetMainCallback2 = 0x08000544,                    -- FOUND: sets gMain.callback2 + gMain.state=0
    savedCallbackOffset = 0x08,                       -- gMain.savedCallback at gMain+0x08 (confirmed in expansion struct)

    -- ROM functions — patching targets
    GetMultiplayerId = 0x0800A4B1,                  -- CONFIRMED: 40 bytes, refs gWirelessCommType+REG_SIOCNT, cart0 offset 0x00A4B0
    IsLinkTaskFinished = 0x0800A569,                -- FOUND: called 4x in CB2_HandleStartBattle, gates link sync progression
    GetBlockReceivedStatus = 0x0800A599,            -- FOUND: called 4x, returns bitmask of received blocks (needs 0x0F)
    CB2_HandleStartBattle = 0x08037B45,             -- FOUND: switch on gBattleCommunication[0], 11 cases (0-10)
    SetUpBattleVars = 0x0806F1D9,                   -- FOUND: 674 bytes, 24 BLs, refs gBattleResources, CreateTask at +0x7C
    PlayerBufferExecCompleted = 0x0806F0D5,         -- FOUND: 114 bytes, 2 BLs (GetMultiplayerId + link fn), paired with LinkOpponent
    LinkOpponentBufferExecCompleted = 0x0807E911,   -- CORRECTED: real LinkOpponent ExecCompleted (was 0x08078789 = LinkPartner!)
    LinkPartnerBufferExecCompleted = 0x08078789,    -- Was misidentified as LinkOpponent
    PrepareBufferDataTransfer = 0x08032FA9,          -- CORRECTED: THIS is PrepareBufferDataTransfer (not Link!). 142 bytes, checks LINK flag, calls Link or memcpy
    PrepareBufferDataTransferLink = 0x080330F5,     -- FOUND: actual link transfer function called by PrepareBufferDataTransfer at +0x20
    InitBtlControllersInternal_BEQ = 0x08032ACE,    -- BEQ that skips BeginBattleIntro for non-master (patch to NOP for slave)
    SetControllerToPlayer = 0x0806F0A5,             -- Sets battler controller to Player
    SetControllerToLinkOpponent = 0x0807DC29,       -- Sets battler controller to LinkOpponent

    -- EWRAM variables (found via ROM literal pool scan)
    gBattleStruct = 0x02023A0C,           -- EWRAM pointer to heap-allocated BattleStruct (found via DoBattleIntro LDR)
    gBattleStructEventStateBattleIntroOffset = 0x2F9, -- offset within *gBattleStruct for eventState.battleIntro (u8)
    gBattleResources = 0x02023A18,        -- EWRAM pointer to heap-allocated battle data (650 ROM refs, confirmed)

    -- BattleResources struct offsets (R&B has 9 ptr fields vs vanilla's 4)
    bufferA_offset = 0x024,               -- bufferA[0] at *gBattleResources + 0x024 (vanilla: +0x010)
    bufferB_offset = 0x824,               -- bufferB[0] at *gBattleResources + 0x824 (vanilla: +0x810)
    battlerBufferSize = 0x200,            -- 512 bytes per battler slot

    -- IWRAM variables (confirmed same as vanilla Emerald via ROM literal pool scan)
    gWirelessCommType = 0x030030FC,       -- IWRAM: u8, 0=wired, 1=wireless — 132 ROM refs, same as vanilla
    gReceivedRemoteLinkPlayers = 0x03003124, -- IWRAM: u8, set to 1 to skip link handshake — same as vanilla
    gBlockReceivedStatus = 0x0300307C,    -- IWRAM: u8[4], set to 1 for data available — same as vanilla

    -- Link status byte: BattleMainCB2 checks *(u8*)0x0203C300 == 0 before allowing fade transition
    linkStatusByte = 0x0203C300,

    -- gBlockRecvBuffer: 4 slots × 0x100 bytes each — link party exchange copies from here to gEnemyParty
    -- CB2_HandleStartBattle Cases 4/8/12 do: memcpy(gEnemyParty+offset, gBlockRecvBuffer[enemy], 200)
    -- We must write opponent party data HERE so the engine's own memcpy populates gEnemyParty correctly
    gBlockRecvBuffer = 0x020226C4,        -- FOUND: 4 slots, each 0x100 (256) bytes apart
    gBlockRecvBufferStride = 0x100,       -- Stride between slots

    -- EWRAM battle variables (CORRECTED 2026-02-07: gActiveBattler and gBattleControllerExecFlags SWAPPED)
    -- ROM disassembly shows 0x020233DC is accessed via STRB/LDRB (byte) = gActiveBattler
    -- and 0x020233E0 is accessed via LDR (32-bit) and checked == 0 = gBattleControllerExecFlags
    gActiveBattler = 0x020233DC,             -- CORRECTED: u8 (byte access pattern in ROM), was 0x020233E0
    gBattleControllerExecFlags = 0x020233E0, -- CORRECTED: u32 (32-bit polling in state machine), was 0x020233DC
    gBattleCommunication = 0x0202370E,       -- FOUND: u8[8], gBattleCommunication[MULTIUSE_STATE] at 0x0202370E (written to 0 in CB2_InitBattle)
    gLinkPlayers = 0x02022CE8,               -- CORRECTED: vanilla+0x300 shift (was 0x020229E8), 132 LP refs, confirmed in 59 GetMultiplayerId callers
    gBattlersCount = 0x020233E4,             -- FOUND: u8, number of active battlers (2 for singles, 4 for doubles)
    gBattlerPositions = 0x020233EE,          -- FOUND: u8[], battler position array
    gBattleMons = 0x020233FC,                -- FOUND: struct array, 0x5C (92) bytes per battler
    gBattleMainFunc = 0x03005D04,            -- FOUND: IWRAM function pointer driving battle logic each tick
    gBattlerControllerFuncs = 0x03005D70,    -- FOUND: IWRAM u32[4], per-battler controller function pointers
    gBattlerControllerEndFuncs = 0x03005D80, -- FOUND: IWRAM u32[4], per-battler end callback pointers
    gPreBattleCallback1 = 0x03005D00,        -- FOUND: IWRAM, saved CB1 before battle

    -- Controller function ROM addresses (for swapping link opponent → regular opponent)
    BattleControllerDummy = 0x0806F0A1,        -- Idle/dummy controller
    PlayerBufferRunCommand = 0x0806F151,       -- Player controller (handles input, animations locally)
    PlayerBufferExecCompleted = 0x0806F0D5,    -- Player exec completed callback
    LinkOpponentRunCommand = 0x0807DC45,       -- CORRECTED: real LinkOpponentBufferRunCommand (0x0807793D was LinkPartner!)
    LinkPartnerRunCommand = 0x0807793D,        -- Was misidentified as LinkOpponent
    OpponentBufferRunCommand = 0x081BAD85,     -- Regular AI opponent controller (handles all anims locally)
    OpponentBufferExecCompleted = 0x081BB945,  -- FOUND: AI opponent exec completed callback (clears exec flags locally)

    -- Battle variables synced by GBA-PK protocol
    -- NOTE: These MUST be found via ROM scanner for R&B (vanilla offsets DON'T apply
    -- due to expansion adding vars in same TU). Set to nil until verified.
    gBattlerAttacker = 0x0202358C,      -- u8, layout: gBattlescriptCurrInstr(0x02023594) - 8
    gBattlerTarget = 0x0202358D,        -- u8, gBattlerAttacker + 1
    gEffectBattler = 0x0202358F,        -- u8, gBattlerAttacker + 3 (gBattlerFainted at +2)
    gAbsentBattlerFlags = 0x02023591,   -- u8, gBattlerAttacker + 5 (gPotentialItemEffectBattler at +4)

    -- Turn order and action tracking (found via Python ROM scanner find_turn_vars.py + find_turn_counter_v12.py)
    gBattlerByTurnOrder = 0x020233F6,        -- FOUND: u8[4], 39 ROM refs — order battlers act each turn
    gChosenActionByBattler = 0x02023598,     -- FOUND: u8[MAX_BATTLERS_COUNT], 31 ROM refs — selected action per battler
    gChosenMoveByBattler = 0x020235FA,       -- FOUND: u16[MAX_BATTLERS_COUNT], 22 ROM refs — selected move per battler
    gActionsByTurnOrder = 0x020233F2,        -- FOUND: u8[4], 18 ROM refs — maps turn order slot to action function ID
    gBattleTurnCounter = 0x02023708,         -- FOUND: u16, 3 ROM refs — incremented each turn, reset to 0 at battle start
    gBattleOutcome = 0x02023716,            -- FOUND: u8, 0=ongoing, 1=won, 2=lost (after gBattleCommunication[8])

    -- Battle phase function pointers (for context-aware exec safety)
    BeginBattleIntro = 0x08039C31,                 -- from literal pool at 0x032AF4 in InitBtlControllersInternal
    DoBattleIntro = 0x0803ACB1,                    -- Intro animation (send-out Pokemon sprites, health boxes)
    HandleTurnActionSelectionState = 0x0803BE39,   -- Action selection (Fight/Bag/Pokemon/Run menu)
    RunTurnActionsFunctions = 0x0803E371,          -- Turn execution (animations, damage)
    SetActionsAndBattlersTurnOrder = 0x0803D8F1,   -- Turn setup after action selection

    -- Post-battle cleanup addresses (found via Python ROM scanner 2026-02-10)
    gSendBuffer = 0x02022BC4,                -- EWRAM: link send buffer (vanilla+0x300, 32 LP refs)
    sBlockSend = 0x03000D10,                 -- IWRAM: block send struct (vanilla match, 5 LP refs)
    gLinkCallback = 0x03003140,              -- IWRAM: link callback fn ptr (vanilla match, 25 LP refs)
    gSaveBlock2Ptr = 0x03005DA0,             -- IWRAM: pointer to SaveBlock2 in EWRAM (confirmed via scan: name/gender/trainerId valid)

    -- Script system addresses (Loadscript 37 — found via Python ROM scanner 2026-02-10)
    CreateTask = 0x080C1544,                 -- ROM: task creation function (896 callers)
    DestroyTask = 0x080C1AA5,               -- ROM: task destruction function (271 callers)
    Task_StartWiredCableClubBattle = 0x080D1655, -- ROM: task callback for cable club battle (BL→IsLinkTaskFinished + CB2_InitBattle LP)
    gLocalLinkPlayer = 0x02022D74,           -- EWRAM: local link player struct (28 bytes), copied to gLinkPlayers by 0x0800AA4C
    gSpecialVar_8000 = 0x02036BB0,           -- EWRAM: script special variables base (from CB2_HandleStartBattle LP)
    gSpecialVar_Result = 0x02036BCA,        -- EWRAM: VAR_RESULT (0x800D = gSpecialVar_8000 + 0x1A)
    gSpecialVar_8001 = 0x02036BB2,          -- EWRAM: VAR_0x8001 (gSpecialVar_8000 + 0x02, textbox completion signal)
    gScriptLoad = 0x03000E38,               -- IWRAM: script trigger struct (vanilla match, 6 LP refs)
    gScriptData = 0x096E0000,               -- cart0: safe area for script bytecode (past ROM data at 0x16D2983)
    gTextData = 0x096E0040,                 -- cart0: text area after script bytecodes (gScriptData + 0x40)
    gNativeData = 0x096F0000,               -- cart0: safe area for ASM code (64KB after gScriptData)
    -- NOTE: InitLocalLinkPlayer does NOT exist as a standalone function in R&B (inlined by compiler).
    -- Our Lua initLocalLinkPlayer() in battle.lua reads SaveBlock2 directly and writes gLinkPlayers[0].

    -- ROM patches for link battle emulation
    -- Each patch: { romOffset = cart0_offset, value = new_instruction, size = bytes }
    -- PK-GBA reference: 8 patches to skip link hardware and force battle progression
    patches = {
      -- GetMultiplayerId is patched separately in battle.lua applyPatches() (MOV R0,#n; BX LR)

      -- IsLinkTaskFinished: MOV R0, #1; BX LR (always returns TRUE)
      -- CB2_HandleStartBattle calls this 5x in R&B — states 1,3,5,8,10 (gates on link completion)
      -- Without this patch, link sync states never advance
      isLinkTaskFinished = { romOffset = 0x0A568, value = 0x47702001, size = 4 },

      -- GetBlockReceivedStatus: MOV R0, #15; BX LR (always returns 0x0F = all received)
      -- CB2_HandleStartBattle calls this 4x in R&B — states 2,4,6,9 (gates on link data receipt)
      getBlockReceivedStatus = { romOffset = 0x0A598, value = 0x4770200F, size = 4 },

      -- PlayerBufferExecCompleted +0x1C: BEQ → B (skip link check)
      -- Original: 0xD01C (BEQ +0x1C), Patch: 0xE01C (B +0x1C — unconditional skip)
      playerBufExecSkip = { romOffset = 0x06F0D4 + 0x1C, value = 0xE01C, size = 2 },

      -- LinkOpponentBufferExecCompleted +0x1C: BEQ → B (skip link check)
      -- CORRECTED: was 0x078788 (LinkPartner!). Real LinkOpponent ExecCompleted = 0x07E910
      linkOpponentBufExecSkip = { romOffset = 0x07E910 + 0x1C, value = 0xE01C, size = 2 },

      -- PrepareBufferDataTransfer: BEQ→B at +0x18 to ALWAYS use local memcpy path
      -- GBA-PK: patches at +0x16 with 0xE009 (vanilla Emerald offsets differ)
      -- R&B: the LINK check is at +0x18 (BEQ 0xD008). Patch to B 0xE008 = always local.
      -- Without this patch, LINK active → calls PrepareBufferDataTransferLink instead of
      -- memcpy to gBattleBufferA → commands never written → exec flags never cleared!
      prepBufDataTransferLocal = { romOffset = 0x032FC0, value = 0xE008, size = 2 },

      -- initBtlControllersBeginIntro: REMOVED (2026-02-11)
      -- BEQ at 0x032ACE skips ENTIRE master path (controllers+positions), not just BeginBattleIntro.
      -- CLIENT follows slave path (reversed positions). gBattleMainFunc written by Lua instead.

      -- NOP the BL to HandleLinkBattleSetup (GBA-PK critical patch!)
      -- HandleLinkBattleSetup() at 0x0803240C creates link buffer tasks:
      --   Task_WaitForLinkPlayerConnection, Task_HandleSendLinkBuffersData,
      --   Task_HandleCopyReceivedLinkBuffersData.
      -- These tasks call SendBlock(), GetLinkPlayerCount_2(), CheckShouldAdvanceLinkState() etc.
      -- Without real link hardware, these tasks corrupt gBattleTypeFlags and other memory.
      -- GBA-PK NOPs this at SetUpBattleVars+0x42 (vanilla Emerald).
      -- R&B: SetUpBattleVars at 0x08032454, BL HandleLinkBattleSetup at +0x040 (ROM 0x032494).
      -- Also: CB2_InitBattleInternal calls HandleLinkBattleSetup at ROM 0x036456.
      -- NOP = 0x46C0 (MOV R8,R8) for each halfword of the BL pair.
      nopHandleLinkSetup_SetUpBV_hi = { romOffset = 0x032494, value = 0x46C0, size = 2 },
      nopHandleLinkSetup_SetUpBV_lo = { romOffset = 0x032496, value = 0x46C0, size = 2 },
      nopHandleLinkSetup_CB2Init_hi = { romOffset = 0x036456, value = 0x46C0, size = 2 },
      nopHandleLinkSetup_CB2Init_lo = { romOffset = 0x036458, value = 0x46C0, size = 2 },

      -- NOP the BL to TryReceiveLinkBattleData in VBlankIntrHandler.
      -- TryReceiveLinkBattleData (0x08033448) is called every VBlank from 0x080007BC.
      -- When LINK_IN_BATTLE is set and gReceivedRemoteLinkPlayers=1, it processes
      -- gBlockRecvBuffer using GetBlockReceivedStatus() — our patch makes that return 0x0F,
      -- so it reads garbage dataSize from gBlockRecvBuffer[i][2] and copies huge amounts of
      -- data to gLinkBattleRecvBuffer, corrupting gBattleTypeFlags and other memory.
      -- We use TCP relay, not link hardware, so this function is never needed.
      nopTryRecvLinkBattleData_hi = { romOffset = 0x0007BC, value = 0x46C0, size = 2 },
      nopTryRecvLinkBattleData_lo = { romOffset = 0x0007BE, value = 0x46C0, size = 2 },

      -- NOP memcpy calls in CB2_HandleStartBattle that copy from gBlockRecvBuffer (garbage).
      -- R&B has 11 states (0-10). States 4 and 6 copy link-received data into party arrays.
      -- We inject parties via TCP, so these memcpy calls overwrite correct data with garbage.
      -- States 3-6 are skipped by comm advancement (2->7), but NOP'd as defense-in-depth.
      -- State 4 (+0x031C, +0x032E): memcpy 200 bytes each (gPlayerParty/gEnemyParty batches)
      -- State 6 (+0x0434, +0x0446): memcpy 100 bytes each (individual Pokemon copies)
      -- State 9 (+0x05AA): memcpy 4 bytes only (RNG seed, harmless — not NOP'd)
      -- func_start = 0x037B44 (CB2_HandleStartBattle)
      nopMemcpyHSB_s4a_hi = { romOffset = 0x037E60, value = 0x46C0, size = 2 },
      nopMemcpyHSB_s4a_lo = { romOffset = 0x037E62, value = 0x46C0, size = 2 },
      nopMemcpyHSB_s4b_hi = { romOffset = 0x037E72, value = 0x46C0, size = 2 },
      nopMemcpyHSB_s4b_lo = { romOffset = 0x037E74, value = 0x46C0, size = 2 },
      nopMemcpyHSB_s6a_hi = { romOffset = 0x037F78, value = 0x46C0, size = 2 },
      nopMemcpyHSB_s6a_lo = { romOffset = 0x037F7A, value = 0x46C0, size = 2 },
      nopMemcpyHSB_s6b_hi = { romOffset = 0x037F8A, value = 0x46C0, size = 2 },
      nopMemcpyHSB_s6b_lo = { romOffset = 0x037F8C, value = 0x46C0, size = 2 },
    },
  },

  -- Battle type flag constants (from pokeemerald-expansion include/constants/battle.h)
  battleFlags = {
    DOUBLE       = 0x00000001,  -- 1 << 0
    LINK         = 0x00000002,  -- 1 << 1
    IS_MASTER    = 0x00000004,  -- 1 << 2
    TRAINER      = 0x00000008,  -- 1 << 3
    FIRST_BATTLE = 0x00000010,  -- 1 << 4
    SAFARI       = 0x00000080,  -- 1 << 7
    BATTLE_TOWER = 0x00000100,  -- 1 << 8
    RECORDED     = 0x01000000,  -- 1 << 24 (also used as RECORDED_LINK gate in BattleMainCB2)
    LINK_IN_BATTLE = 0x00000020, -- 1 << 5 (auto-set by engine when LINK battle starts)
    SECRET_BASE  = 0x08000000,  -- 1 << 27
  },

  -- Battle outcome constants (from pokeemerald-expansion)
  battleOutcome = {
    WON       = 1,
    LOST      = 2,
    DREW      = 3,
    RAN       = 4,
    CAUGHT    = 7,
    FORFEITED = 9,
  },

  facing = {
    NONE = 0,
    DOWN = 1,
    UP = 2,
    LEFT = 3,
    RIGHT = 4
  },

  validation = {
    minX = 0,
    maxX = 2048,
    minY = 0,
    maxY = 2048,
    minMapGroup = 0,
    maxMapGroup = 50,
    minMapId = 0,
    maxMapId = 255
  },

  validatePosition = function(self, x, y, mapGroup, mapId)
    local v = self.validation
    if x < v.minX or x > v.maxX then return false end
    if y < v.minY or y > v.maxY then return false end
    if mapGroup < v.minMapGroup or mapGroup > v.maxMapGroup then return false end
    if mapId < v.minMapId or mapId > v.maxMapId then return false end
    return true
  end,
}
