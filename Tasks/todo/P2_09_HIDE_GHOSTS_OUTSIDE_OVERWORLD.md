# Hide Ghosts Outside Overworld

> **Statut:** En attente d'implementation
> **Type:** Fix — Ghosts visibles dans les menus, sac, combat
> **Objectif:** Ne dessiner les ghosts que lorsque le jeu est en mode overworld (callback2 == CB2_Overworld)
> **Priorite:** Haute

---

## Probleme

Actuellement, l'overlay Painter dessine les ghosts **par-dessus tout** : sac a dos, menus, ecran de combat, ecran de PC, etc. C'est parce que le canvas overlay de mGBA est une couche independante du jeu — il ne sait pas dans quel etat le jeu se trouve.

## Cause

`drawOverlay()` dans `client/main.lua:429-450` appelle `Render.drawAllGhosts()` sans verifier si le jeu est en mode overworld. La seule protection existante est le check `State.warpPhase == "in_battle"` (ligne 556) qui skip le rendu pendant les combats PvP, mais pas pendant :
- Le sac a dos
- Le menu Start
- Les combats sauvages / dresseurs
- L'ecran PC
- Les cinematiques / dialogues

## Fix

Ajouter un check `callback2 == CB2_Overworld` avant de dessiner les ghosts.

### Implementation

**Fichier:** `client/main.lua`

Dans `drawOverlay()` (lignes 429-450), ajouter une condition avant le rendu des ghosts :

```lua
-- Avant de dessiner les ghosts, verifier qu'on est en overworld
local cb2 = HAL.readCallback2()
local isOverworld = (cb2 == config.warp.cb2Overworld)  -- 0x080A89A5

if State.showGhosts and playerCount > 0 and currentPos and isOverworld then
    -- ... rendu ghosts existant
end
```

`HAL.readCallback2()` existe deja (`client/hal.lua:1430-1438`) et retourne la valeur u32 du callback2.
`config.warp.cb2Overworld` = `0x080A89A5` est deja defini dans `config/run_and_bun.lua`.

### Details

- [ ] Ajouter `local cb2 = HAL.readCallback2()` au debut de `drawOverlay()` dans `client/main.lua:429`
- [ ] Ajouter la condition `isOverworld` au check de la ligne 433 : `if State.showGhosts and playerCount > 0 and currentPos and isOverworld then`
- [ ] Verifier que les labels/noms des joueurs sont aussi masques (ils sont dessines dans `Render.drawGhost()` lignes 235-248, donc OK — ils sont sous la meme condition)
- [ ] Verifier que `Occlusion.beginFrame()` (ligne 430) ne cause pas de probleme si appele hors overworld (lecture BG1 en mode menu = donnees differentes mais pas de crash)
- [ ] Tester : ouvrir le sac, le menu Start, entrer en combat sauvage — les ghosts ne doivent plus apparaitre

## Fichiers a modifier

| Fichier | Modification |
|---------|-------------|
| `client/main.lua` | Ajouter check `cb2 == CB2_Overworld` dans `drawOverlay()` (~3 lignes) |

## Notes

- `HAL.readCallback2()` lit depuis `config.warp.callback2Addr` (IWRAM 0x030022C4 pour gMain.callback2)
- CB2_Overworld = `0x080A89A5` (deja dans config comme `config.warp.cb2Overworld`)
- Implementation estimee : ~5 minutes, ~3 lignes de code
- Pas de risque de regression : on ajoute une condition supplementaire sans modifier le rendu
