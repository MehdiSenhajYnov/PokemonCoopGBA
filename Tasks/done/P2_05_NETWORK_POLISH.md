# Phase 2 - Polish Réseau (Déconnexion/Reconnexion)

> **Statut:** Completed (2026-02-03)
> **Type:** Feature — Gestion robuste des erreurs réseau
> **Objectif:** Implémenter la gestion automatique des déconnexions, reconnexions avec backoff, et nettoyage des ghosts déconnectés.

---

## Vue d'ensemble

Gérer proprement les cas d'erreur réseau:
- Déconnexion serveur
- Perte de connexion Internet
- Timeout
- Auto-reconnexion avec backoff exponentiel
- Nettoyage des ghosts obsolètes
- Indicateur UI statut connexion

---

## Implémentation

### 1. Améliorer network.lua

- [x] **1.1** Ajouter détection déconnexion (via socket "error" callback + receive error + send pcall)

- [x] **1.2** Ajouter fonction reconnexion avec backoff (`Network.tryReconnect()` avec backoff exponentiel, max 10 attempts, cap 30s)

### 2. Indicateur UI statut connexion

- [x] **2.1** Dans `main.lua`, afficher statut ONLINE/RECONNECTING #N/OFFLINE avec couleurs (vert/jaune/rouge)

### 3. Nettoyage ghosts déconnectés

- [x] **3.1** Géré par le serveur : broadcast `player_disconnected` à la déconnexion
- ~~**3.2-3.3** Ghost timeout client retiré — incompatible avec `SEND_RATE_IDLE = 0` (les joueurs idle ne sendant rien, le timeout les supprimait à tort)~~

### 4. Server-side (bonus)

- [x] **4.1** Server broadcasts `player_disconnected` to room on client disconnect/timeout

- [x] **4.2** Guard against double-disconnect (end + close both fire)

---

## Fichiers modifiés

| Fichier | Modifications |
|---------|--------------|
| `client/network.lua` | Disconnection detection (error callback, receive error, send pcall), reconnection with exponential backoff, state query functions |
| `client/main.lua` | Reconnection logic in update loop, enhanced UI status (RECONNECTING), always-visible status bar on disconnect |
| `server/server.js` | Broadcast `player_disconnected` on disconnect/heartbeat timeout, double-disconnect guard |

---

## Prochaine étape

Après cette tâche → **PHASE2_OPTIMIZATION.md**
