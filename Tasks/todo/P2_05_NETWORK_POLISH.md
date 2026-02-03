# Phase 2 - Polish Réseau (Déconnexion/Reconnexion)

> **Statut:** En attente
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

- [ ] **1.1** Ajouter détection déconnexion dans `Network.receive()`:
  ```lua
  if err == "closed" then
    connected = false
    return nil, "disconnected"
  end
  ```

- [ ] **1.2** Ajouter fonction reconnexion avec backoff:
  ```lua
  local reconnectAttempts = 0
  local maxReconnectAttempts = 10
  local reconnectDelay = 1000  -- ms

  function Network.reconnect(host, port)
    if reconnectAttempts >= maxReconnectAttempts then
      return false
    end

    reconnectAttempts = reconnectAttempts + 1
    local delay = reconnectDelay * (2 ^ (reconnectAttempts - 1))  -- Exponentiel

    -- Wait delay
    -- Attempt connection
    local success = Network.connect(host, port)

    if success then
      reconnectAttempts = 0
      return true
    end

    return false
  end
  ```

### 2. Indicateur UI statut connexion

- [ ] **2.1** Dans `main.lua`, afficher statut:
  ```lua
  function drawConnectionStatus()
    local status = State.connected and "ONLINE" or "OFFLINE"
    local color = State.connected and 0x00FF00 or 0xFF0000

    gui.drawText(200, 5, status, color, 0x000000)
  end
  ```

### 3. Nettoyage ghosts déconnectés

- [ ] **3.1** Ajouter timeout dans State:
  ```lua
  otherPlayersTimeout = {}  -- {playerId: lastSeenFrame}
  ```

- [ ] **3.2** Update timeout à chaque position reçue
- [ ] **3.3** Supprimer si inactif > 120 frames (2 secondes)

---

## Fichiers à modifier

| Fichier | Modifications |
|---------|--------------|
| `client/network.lua` | Ajouter reconnexion avec backoff |
| `client/main.lua` | UI statut connexion, nettoyage timeouts |

---

## Prochaine étape

Après cette tâche → **PHASE2_OPTIMIZATION.md**
