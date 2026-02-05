# Phase 3 - Systeme Duel Warp

> **Statut:** Completed (2026-02-03)
> **Type:** Feature — Teleportation synchronisee pour combat
> **Objectif:** Implementer le systeme de "Duel Warp" permettant a deux joueurs de se teleporter dans une salle de combat Link.

---

## Vue d'ensemble

Le **Duel Warp** est la feature signature du framework. Deux joueurs peuvent initier un duel en appuyant sur A pres du ghost de l'autre, accepter l'invitation, puis se teleporter simultanement dans une salle de combat.

**Reference:** `CLAUDE.md` section 4.C

---

## Workflow complet

```
1. Joueur A pres du ghost de Joueur B
2. Joueur A appuie sur bouton A
3. -> Envoi duel_request au serveur
4. -> Serveur forward a Joueur B uniquement
5. Joueur B voit prompt "Duel [PlayerA]?"
6. Joueur B appuie sur A pour accepter (B pour refuser)
7. -> Envoi duel_accept au serveur
8. -> Serveur coordonne teleportation
9. Les deux joueurs ecrivent en RAM (mapId, X, Y) via HAL.writePlayerPosition
10. Lock inputs pendant 3 secondes (180 frames)
11. Teleportation effective
12. Unlock inputs dans MAP_BATTLE_COLOSSEUM_2P
```

---

## Partie 1 - Module duel.lua (Trigger)

**Fichier cree:** `client/duel.lua`

- [x] **1.1** Detection proximite (Manhattan distance <= 2 tiles, same map, A button edge detect)
- [x] **1.2** UI prompt duel (Painter API overlay, accept [A] / decline [B])
- [x] **1.3** Cooldown anti-spam (120 frames between requests)
- [x] **1.4** Request timeout (600 frames = ~10s)
- [x] **1.5** State reset on disconnect/map change/warp

---

## Partie 2 - Teleportation (HAL + Serveur)

- [x] **2.1** Server: duel_request unicast to target (not broadcast)
- [x] **2.2** Server: duel_accept coordination with pendingDuel verification + room check
- [x] **2.3** Server: duel_warp envoi aux deux joueurs avec coords differentes (A/B)
- [x] **2.4** Server: duel_decline handler + duel_declined notification
- [x] **2.5** Server: disconnect cleanup (pendingDuel + duel_cancelled)
- [x] **2.6** Client: HAL.readButtons() for A/B via KEYINPUT register
- [x] **2.7** Client: duel_warp handler with HAL.writePlayerPosition + input lock 180 frames
- [x] **2.8** Client: input lock at top of update() with early return + overlay draw
- [x] **2.9** Client: duel_cancelled message handler

---

## Partie 3 - Coordonnees Duel Room

- [x] **3.1** Recherche pokeemerald decomp: MAP_BATTLE_COLOSSEUM_2P
  - mapGroup = 28, mapId = 24
  - Player1: (3, 5), Player2: (10, 5)
  - Link Receptionist NPC at (9, 3)
- [x] **3.2** Config emerald_us.lua: duelRoom added
- [x] **3.3** Config run_and_bun.lua: duelRoom added
- [x] **3.4** Server: DUEL_ROOM constant with correct coords

---

## Tests

- [x] **Test 1:** Detection proximite fonctionne (edge detect + Manhattan distance)
- [x] **Test 2:** Prompt duel s'affiche (Painter API overlay)
- [x] **Test 3:** Acceptation envoie message serveur (duel_accept with requesterId)
- [x] **Test 4:** Les deux joueurs se teleportent (duel_warp with different coords)
- [x] **Test 5:** Teleportation synchronisee (server sends both warps atomically)
- [x] **Test 6:** Inputs lockes pendant warp (180 frames, early return in update)
- [x] **Test 7:** Positionnement correct dans Battle Colosseum 2P
- [x] **Test 8:** Refus de duel fonctionne (duel_decline + duel_declined)

---

## Fichiers crees

| Fichier | Description |
|---------|-------------|
| `client/duel.lua` | Module gestion trigger, request/accept/decline, UI duel |

## Fichiers modifies

| Fichier | Modifications |
|---------|--------------|
| `server/server.js` | Duel coordination (request/accept/decline/warp/disconnect cleanup) |
| `client/main.lua` | Duel integration, message handling, input lock, HAL.readButtons |
| `client/hal.lua` | +readButtons() for A/B via KEYINPUT register |
| `config/emerald_us.lua` | +duelRoom coords, updated battleColosseum map reference |
| `config/run_and_bun.lua` | +duelRoom coords |

---

## Prochaine etape

Apres cette tache -> **P4_10_MULTI_ROM.md**
