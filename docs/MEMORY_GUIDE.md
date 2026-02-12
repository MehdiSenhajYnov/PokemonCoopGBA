# Memory Guide

Guide pratique pour maintenir les profils ROM (`config/*.lua`) en phase avec le code client.

## Etat Actuel

Profils existants:
- `config/run_and_bun.lua` (profil principal)
- `config/emerald_us.lua` (fallback)

Le client lit directement ces profils via `client/main.lua` + `client/hal.lua`.

## Ce Qu'un Profil Doit Couvrir

Minimum requis:
- `offsets.playerX`
- `offsets.playerY`
- `offsets.mapGroup`
- `offsets.mapId`
- `offsets.facing`

Souvent necessaire ensuite:
- `offsets.cameraX`, `offsets.cameraY`
- bloc `render` (`gMainAddr`, `oamBufferOffset`, `oamBaseIndex`) pour l'injection OAM ghost stable
- bloc `warp` (callback2, CB2_LoadMap, etc.)
- bloc `battle` et `battle_link` pour le PvP relaye

## Workflow Recommande (Nouveau ROM)

1. Duplique un profil proche dans `config/`.
2. Valide les offsets overworld (X/Y/map/facing) en mGBA.
3. Valide camera + callback2 (stabilite rendering/overworld detection).
4. Valide la reservation render (OAM/VRAM ghost) et la superposition locale.
5. Valide addresses battle/duel si le PvP est cible.
6. Mets a jour la doc ROM dediee (`docs/<ROM>.md`) avec seulement les addresses stables.

## Scripts Utiles

- `scripts/scanners/` pour les scans Lua adresses runtime.
- `scripts/ghidra/` et `scripts/ToUse/` pour l'analyse ROM/battle.
- `scripts/discovery/` pour des verifications ciblées.
- `scripts/archive/` pour historique/superseded.

## Verification Rapide en mGBA

Exemple (Run & Bun):

```lua
print(emu.memory.wram:read16(0x00024CBC)) -- X
print(emu.memory.wram:read16(0x00024CBE)) -- Y
print(emu.memory.wram:read8(0x00024CC0))  -- MapGroup
print(emu.memory.wram:read8(0x00024CC1))  -- MapId
```

Health check HAL:

```lua
HAL.testMemoryAccess()
```

## Regles de Maintenance

- La source de verite est `config/*.lua`, pas les docs narratives.
- Si une adresse change, update d'abord le profil, puis les docs associees.
- Evite de recopier toute la table d'adresses dans plusieurs fichiers: preferer un resume + pointeur vers `config/`.

## Checklist de MAJ Profil

- [ ] Overworld offsets verifies en jeu
- [ ] Camera offsets verifies
- [ ] Render block valide (OAM base + VRAM ghost slots)
- [ ] Overworld detection (`HAL.isOverworld`) stable
- [ ] Overlap ghost/local coherent (ordre visuel en contact vertical)
- [ ] Duel flow basique valide
- [ ] Battle addresses/patches verifies si PvP actif
- [ ] `docs/TESTING.md` et doc ROM mis a jour
