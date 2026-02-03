# Occlusion / Profondeur Ghost derriere les Batiments

> **Statut:** TERMINE (2026-02-03) — Toutes les phases completees
> **Type:** Bug Fix / Feature — Le ghost s'affiche toujours au-dessus de tout
> **Priorite:** Haute (impact visuel majeur, casse l'immersion)
> **Objectif:** Quand un joueur distant est derriere un batiment, son ghost doit etre partiellement ou totalement cache, pas dessine par-dessus.

---

## Probleme

Actuellement, le ghost est dessine sur un **canvas overlay** (`canvas:newLayer()`) qui se superpose a l'image du jeu. Il n'y a aucune notion de profondeur/Z-order.

**Fichier:** `client/render.lua:201-205`
```lua
if spriteImg and overlayImage then
    local drawY = screenY - (spriteH - TILE_SIZE)
    pcall(overlayImage.drawImage, overlayImage, spriteImg, screenX, drawY)
```

**Fichier:** `client/main.lua:276-278`
```lua
overlay = canvas:newLayer(W, H)
overlay:setPosition(0, 0)
painter = image.newPainter(overlay.image)
```

Le layer overlay est dessine **au-dessus** de tout le rendu GBA. Resultat visible:
- Si le joueur distant est derriere une maison, on voit quand meme son sprite complet "sur le toit"
- Si le joueur est derriere un arbre, pas d'occlusion partielle
- Casse completement l'illusion de co-presence dans le monde

---

## Analyse de la difficulte

C'est un **probleme fondamentalement difficile** sur GBA car:

1. **Pas d'acces au Z-buffer** — Le GBA utilise des layers BG (Background 0-3) avec des priorites, pas un Z-buffer pixel par pixel
2. **L'overlay mGBA est au-dessus de tout** — `canvas:newLayer()` ne peut pas s'inserer entre les layers BG du jeu
3. **Les batiments sont des tiles BG**, pas des sprites OAM — on ne peut pas juste comparer les priorites OAM

### Approches possibles (par difficulte croissante)

---

## Approche A : Occlusion par Y-sorting simple (Recommandee)

**Principe:** Dans les jeux Pokemon overworld, la "profondeur" est directement liee a la coordonnee Y du personnage. Un personnage avec un Y plus petit (plus haut sur l'ecran) est "derriere" un personnage avec un Y plus grand.

**Limitation:** Ne gere PAS l'occlusion par les batiments/arbres (qui sont des tiles BG, pas des sprites). Mais gere correctement:
- Ghost derriere le joueur local (Y plus petit) → ghost dessine avant
- Ghost devant le joueur local (Y plus grand) → ghost dessine apres

**Implementation:**
- [x] **A.1** Trier les ghosts par Y avant de les dessiner dans `drawAllGhosts()` (`render.lua:249-268`)
- [x] **A.2** Le joueur local n'est pas dessine par nous (c'est le jeu qui le dessine), donc le ghost sera toujours au-dessus du joueur local. Accepter cette limitation pour l'instant.

**Fichiers:**
| Fichier | Modification |
|---------|-------------|
| `client/render.lua` | `drawAllGhosts()` — trier par Y avant rendu |

---

## Approche B : Occlusion par lecture des BG priority layers (Intermediaire)

**Principe:** Lire les layers BG du GBA pour determiner quels pixels sont des "obstacles hauts" (toits, arbres) et masquer le ghost a ces endroits.

**Comment ca marche sur GBA:**
- Les layers BG0-BG3 ont chacun une priorite (0=plus haut, 3=plus bas)
- Les sprites OAM ont aussi une priorite (champ dans attr2)
- Le jeu place les toits/arbres sur un layer BG de haute priorite
- Les sprites personnages sont rendus avec une priorite plus basse → occultes par les toits

**Ce qu'on pourrait faire:**
- Lire la priorite du layer BG aux coordonnees du ghost
- Si le BG a une priorite plus haute que les sprites personnages, ne pas dessiner le ghost a cet endroit
- En pratique: lire les BG control registers (REG_BGxCNT) et les tile maps pour determiner la priorite par pixel

**Problemes:**
- Complexe: il faut decoder les tile maps BG pour chaque position pixel
- Les BG scrollent (REG_BGxHOFS/VOFS) → faut prendre en compte le scroll
- Tres couteux en performance (lecture VRAM extensive chaque frame)

---

## Approche C : Masque par echantillonnage du framebuffer (Avancee)

**Principe:** Comparer le rendu avec et sans le ghost pour creer un masque d'occlusion.

**Probleme:** mGBA n'expose pas directement le framebuffer final pour lecture pixel par pixel depuis Lua. L'API `canvas` est un overlay, pas un acces au framebuffer.

**Variante possible:** Utiliser `emu:screenshot()` (si disponible dans l'API mGBA dev) pour capturer le rendu du jeu, puis verifier quels pixels du ghost seraient caches.

**Evaluation:** Probablement trop lent et trop complexe pour le moment.

---

## Approche D : Semi-transparence universelle (Compromise simple)

**Principe:** Au lieu de tenter l'occlusion parfaite, rendre les ghosts **semi-transparents** pour que le decor soit toujours visible a travers.

**Implementation:**
- [x] **D.1** Modifier `buildImage()` dans `sprite.lua:167-224` pour appliquer une alpha < 255 a tous les pixels non-transparents
  - Actuellement les couleurs sont `0xFF000000 | ...` (alpha=255, opaque)
  - Changer en `0xB0000000 | ...` (alpha~70%, semi-transparent)
- [x] **D.2** Ajouter un parametre configurable `GHOST_ALPHA` constant (0x00-0xFF)

**Avantage:** Tres simple a implementer, ameliore significativement le rendu
**Limitation:** Le ghost est visible a travers les murs (pas d'occlusion reelle), mais c'est moins choquant visuellement car on voit le decor a travers

**Fichiers:**
| Fichier | Modification |
|---------|-------------|
| `client/sprite.lua` | `buildImage()` — alpha configurable sur les pixels |
| `client/sprite.lua` | `bgr555ToARGB()` — parametre alpha optionnel |
| `client/sprite.lua` | `updateFromNetwork()` — appliquer meme alpha a la reception |

---

## Plan d'implementation recommande

### Phase 1 : Semi-transparence (Approche D) — Quick win

- [x] **1.1** Ajouter constante `GHOST_ALPHA = 0xB0` dans `sprite.lua` (ajustable)
- [x] **1.2** Modifier `buildImage()` pour accepter un parametre alpha optionnel (applique dans le pixel loop, pas dans bgr555ToARGB)
- [x] **1.3** Appliquer `GHOST_ALPHA` dans `captureLocalPlayer()` lors de la conversion palette (pas besoin — c'est le receveur qui applique l'alpha)
- [x] **1.4** Appliquer `GHOST_ALPHA` dans `updateFromNetwork()` lors de `buildImage()` pour les ghosts recus
- [x] **1.5** Le sprite local envoye reste opaque (pour que le receveur puisse choisir son propre alpha)

### Phase 2 : Y-sorting entre ghosts (Approche A)

- [x] **2.1** Trier `otherPlayers` par Y croissant dans `drawAllGhosts()` (`render.lua:249-281`)
- [x] **2.2** Les ghosts avec Y plus petit sont dessines en premier (derriere)

### Phase 3 : Occlusion BG (Approche B — Overdraw Method)

- [x] **3.1** Recherche: BG1 est le cover layer dans le moteur Pokemon Emeraude
- [x] **3.2** HAL: 6 nouvelles fonctions (readIOReg16, readBGControl, readBGScroll, readBGTilemapEntry, readBGTileData, readBGPalette)
- [x] **3.3** Module `occlusion.lua`: lit la tilemap BG1, decode les tiles 4bpp, redessine les pixels opaques par-dessus les ghosts via Painter API
- [x] **3.4** Integration dans render.lua (appel apres chaque ghost) et main.lua (init, beginFrame, clearCache)
- Note: utilise Painter drawRectangle(x,y,1,1) car canvas layer image ne supporte ni setPixel ni drawImage avec image.new (erreur C-level "Invalid object")

### Phase 4 : Suppression semi-transparence

- [x] **4.1** `GHOST_ALPHA` change de `0xB0` (69%) a `0xFF` (100% opaque) — l'occlusion gere la profondeur

---

## Fichiers concernes

| Fichier | Modifications |
|---------|--------------|
| `client/sprite.lua` | `GHOST_ALPHA` 0xB0 → 0xFF (opaque), `buildImage()` alpha param |
| `client/render.lua` | Y-sorting, `setOcclusion()`, appel occlusion apres chaque ghost |
| `client/hal.lua` | 6 nouvelles fonctions BG: readIOReg16, readBGControl, readBGScroll, readBGTilemapEntry, readBGTileData, readBGPalette |
| `client/occlusion.lua` | **NOUVEAU** — module complet d'occlusion BG layer |
| `client/main.lua` | require occlusion, init, beginFrame, clearCache on map change |

---

## Criteres de succes

### Phase 1 (Semi-transparence)
- [x] Les ghosts sont semi-transparents (on voit le decor a travers)
- [x] L'opacite est configurable via une constante
- [x] Les sprites envoyes sur le reseau restent en donnees completes (opaques)

### Phase 2 (Y-sorting)
- [x] Si deux ghosts se chevauchent, celui avec Y plus grand est dessine devant
- [x] Le tri n'impacte pas la performance (< 10 ghosts typiquement)

### Phase 3 (Occlusion BG)
- [x] Le ghost est cache quand il est derriere un batiment
- [x] Le ghost est partiellement visible quand seule la tete depasse (occlusion partielle)
