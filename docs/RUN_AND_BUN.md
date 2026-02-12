# Run & Bun Profile Notes

Source of truth: `config/run_and_bun.lua`.

This file summarizes only the key addresses that are actively used by client/server logic.

## Profile Overview

- Name: `Pokémon Run & Bun`
- Game ID: `BPEE`
- Mode: static addresses (plus battle/link function/patch map)
- Base assumptions: Emerald-engine ROM hack with heavily shifted symbols

## Ghost Rendering Reservation (Hybrid OAM)

Run & Bun profile exposes a render block used by `HAL`/`render.lua`:

```lua
render.gMainAddr      = 0x030022C0
render.oamBufferOffset = 0x38
render.oamBaseIndex    = 110
```

Runtime renderer then reserves 6 ghost sprite slots in OBJ resources:
- OAM indices: `110..115`
- OBJ VRAM slots: 6 blocks of `0x600` bytes (descending from `0x06013C00`)

Depth handling in current code:
- fixed OAM priority (`2`) for injected ghosts,
- overlap-front correction via overlay fallback when needed.

## Core Overworld Offsets

```lua
playerX  = 0x02024CBC  -- u16
playerY  = 0x02024CBE  -- u16
mapGroup = 0x02024CC0  -- u8
mapId    = 0x02024CC1  -- u8
facing   = 0x02036934  -- u8
cameraX  = 0x03005DFC  -- s16 (IWRAM)
cameraY  = 0x03005DF8  -- s16 (IWRAM)
```

## Warp / Overworld Callback Anchors

```lua
gMainAddr      = 0x030022C0
callback2Addr  = 0x030022C4
cb2LoadMap     = 0x080A3FDD
cb2Overworld   = 0x080A89A5
gMainStateOffset = 0x438
```

Duel room constants:

```lua
mapGroup = 28
mapId    = 24
playerA  = (3, 5)
playerB  = (10, 5)
```

## Battle Core Addresses

```lua
gPlayerParty      = 0x02023A98
gPlayerPartyCount = 0x02023A95
gEnemyParty       = 0x02023CF0
gEnemyPartyCount  = 0x02023A96
gBattleTypeFlags  = 0x02023364
gBattleOutcome    = 0x02023716
gMainInBattle     = 0x03002AF9
CB2_BattleMain    = 0x0803816D
gRngValue         = 0x03005D90
```

## Battle Link Layer

`battle_link` contains:
- callback/function anchors (`CB2_InitBattle`, `CB2_HandleStartBattle`, `SetMainCallback2`, ...)
- key globals (`gBattleResources`, `gBattleControllerExecFlags`, `gBattleCommunication`, ...)
- ROM patch table used by `client/battle.lua`

Do not duplicate this entire section in docs; validate/edit directly in `config/run_and_bun.lua`.

## Quick Runtime Verification

mGBA Lua console:

```lua
print(string.format("X=%d Y=%d", emu.memory.wram:read16(0x00024CBC), emu.memory.wram:read16(0x00024CBE)))
print(string.format("Map=%d:%d", emu.memory.wram:read8(0x00024CC0), emu.memory.wram:read8(0x00024CC1)))
print(string.format("InBattle=%d", emu.memory.iwram:read8(0x00002AF9)))
```

## Maintenance Rules

- Update profile first, then update docs.
- Keep this document as a stable summary, not a full symbol dump.
- For test flow, see `docs/TESTING.md`.

Last updated: 2026-02-12
