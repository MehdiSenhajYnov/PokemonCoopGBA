# Phase 1 - Tests Bout en Bout

> **Statut:** ✅ COMPLÉTÉ (2026-02-03)
> **Type:** Testing — Validation intégration client-serveur
> **Objectif:** Vérifier que deux clients mGBA peuvent se connecter au serveur et échanger leurs positions en temps réel.

---

## Prérequis

- [x] Serveur Node.js fonctionnel (`server/server.js`)
- [x] Module `client/network.lua` implémenté
- [x] Intégration TCP dans `client/main.lua` complète
- [x] ROM Pokémon Émeraude US (.gba)
- [x] mGBA 0.10.0+ installé

---

## Vue d'ensemble

Cette tâche valide que la Phase 1 est entièrement fonctionnelle en testant le système complet avec deux clients simultanés. Les tests vérifient la connexion, l'enregistrement, la synchronisation des positions et la robustesse face aux déconnexions.

**Success Criteria:**
1. Deux clients peuvent se connecter simultanément
2. Chaque client voit l'autre dans State.otherPlayers
3. Positions se synchronisent en < 2 secondes
4. Pas de freeze ou crash
5. Déconnexion d'un client ne crash pas l'autre

---

## Plan de test

### Test 1 - Démarrage serveur

**Objectif:** Vérifier que le serveur démarre correctement

- [ ] **1.1** Ouvrir terminal dans `server/`
- [ ] **1.2** Exécuter:
  ```bash
  node server.js
  ```
- [ ] **1.3** Vérifier output console:
  ```
  ╔═══════════════════════════════════════════════════════╗
  ║   Pokémon Co-op Framework - TCP Server               ║
  ╚═══════════════════════════════════════════════════════╝
  [Server] Listening on port 8080
  [Server] Protocol: TCP with JSON line-delimited messages
  [Server] Connect to: 8080
  [Server] Ready to accept connections
  ```

- [ ] **1.4** Vérifier qu'aucune erreur n'apparaît

**Critère de succès:** ✅ Serveur écoute sur port 8080

---

### Test 2 - Premier client (connexion simple)

**Objectif:** Un client se connecte et envoie ses positions

- [ ] **2.1** Lancer mGBA
- [ ] **2.2** Charger ROM Pokémon Émeraude US
- [ ] **2.3** Ouvrir console Lua: `Tools > Scripting...`
- [ ] **2.4** Charger script: `File > Load script... > client/main.lua`
- [ ] **2.5** Vérifier logs mGBA console:
  ```
  [PokéCoop] ======================================
  [PokéCoop] Pokémon Co-op Framework v0.1.0
  [PokéCoop] ======================================
  [PokéCoop] Initializing Pokémon Co-op Framework...
  [PokéCoop] Detected ROM: BPEE
  [PokéCoop] Player ID: player_123456_abc
  [PokéCoop] Connecting to server 127.0.0.1:8080...
  [PokéCoop] Connected to server!
  [PokéCoop] Registered with ID: player_123456_abc
  [PokéCoop] Joined room: default
  [PokéCoop] Initialization complete!
  [PokéCoop] Script loaded successfully!
  ```

- [ ] **2.6** Vérifier logs serveur:
  ```
  [Connect] New client connected from 127.0.0.1:xxxxx
  [Register] Client registered: player_123456_abc
  [Room] Client player_123456_abc joined room default
  ```

- [ ] **2.7** Dans le jeu, déplacer le personnage
- [ ] **2.8** Vérifier overlay mGBA affiche position (coin bas-gauche):
  ```
  X:10 Y:15
  Map:3:1
  ```

- [ ] **2.9** Après ~3 secondes, vérifier logs serveur reçoit positions:
  ```
  [Position] Received from player_123456_abc: {x:10, y:15, ...}
  ```

**Critère de succès:** ✅ Client connecté, enregistré, envoie positions

---

### Test 3 - Deuxième client (synchronisation)

**Objectif:** Deux clients voient leurs positions mutuelles

- [ ] **3.1** Lancer une **seconde instance** de mGBA
  - Windows: Copier dossier mGBA ou lancer depuis différents chemins
  - Linux/Mac: `mgba &` deux fois

- [ ] **3.2** Dans la 2ème instance:
  - Charger **même ROM** Pokémon Émeraude
  - Charger **même script** `client/main.lua`

- [ ] **3.3** Vérifier logs 2ème client:
  ```
  [PokéCoop] Player ID: player_789012_def
  [PokéCoop] Connected to server!
  [PokéCoop] Registered with ID: player_789012_def
  [PokéCoop] Joined room: default
  ```

- [ ] **3.4** Vérifier logs serveur:
  ```
  [Connect] New client connected from 127.0.0.1:yyyyy
  [Register] Client registered: player_789012_def
  [Room] Client player_789012_def joined room default
  ```

- [ ] **3.5** Dans **Client 1**, vérifier overlay affiche:
  ```
  Players: 2
  player_789012_def: X=5 Y=8
  ```

- [ ] **3.6** Dans **Client 2**, vérifier overlay affiche:
  ```
  Players: 2
  player_123456_abc: X=10 Y=15
  ```

- [ ] **3.7** Déplacer personnage dans Client 1
- [ ] **3.8** Vérifier que Client 2 voit les nouvelles coordonnées dans < 2 secondes

- [ ] **3.9** Déplacer personnage dans Client 2
- [ ] **3.10** Vérifier que Client 1 voit les nouvelles coordonnées dans < 2 secondes

**Critère de succès:** ✅ Les deux clients voient les positions de l'autre en temps réel

---

### Test 4 - Maps différentes

**Objectif:** Vérifier que les positions sont envoyées même sur maps différentes

- [ ] **4.1** Dans Client 1, utiliser code Action Replay ou warp pour changer de map
  - Exemple: Route 101 → Littleroot Town
  - MapGroup/MapId devrait changer

- [ ] **4.2** Vérifier overlay Client 1 affiche nouvelle map:
  ```
  X:8 Y:12
  Map:3:2
  ```

- [ ] **4.3** Vérifier que Client 2 reçoit toujours les positions de Client 1
  ```
  player_123456_abc: X=8 Y=12
  ```

- [ ] **4.4** Vérifier logs serveur relay les positions même avec maps différentes

**Critère de succès:** ✅ Positions synchronisées indépendamment des maps

---

### Test 5 - Déconnexion gracieuse

**Objectif:** Tester comportement quand un client se déconnecte

- [ ] **5.1** Avec deux clients connectés, fermer mGBA Client 1
- [ ] **5.2** Vérifier logs serveur:
  ```
  [Disconnect] Client player_123456_abc disconnected
  [Room] Client player_123456_abc left room default
  ```

- [ ] **5.3** Vérifier que Client 2 **ne crash pas**
- [ ] **5.4** Vérifier que Client 2 n'affiche plus player_123456_abc après ~30s (heartbeat timeout)
- [ ] **5.5** Reconnecter Client 1 (relancer mGBA + script)
- [ ] **5.6** Vérifier que Client 2 voit à nouveau Client 1

**Critère de succès:** ✅ Déconnexion gérée proprement, pas de crash

---

### Test 6 - Arrêt/redémarrage serveur

**Objectif:** Vérifier robustesse face à perte serveur

- [ ] **6.1** Avec deux clients connectés, arrêter serveur (Ctrl+C)
- [ ] **6.2** Vérifier que les clients **ne crashent pas**
- [ ] **6.3** Vérifier logs clients (devraient afficher erreur connexion)
- [ ] **6.4** Redémarrer serveur:
  ```bash
  node server.js
  ```

- [ ] **6.5** Recharger scripts dans les deux clients (Ctrl+L dans console Lua)
- [ ] **6.6** Vérifier reconnexion réussie

**Critère de succès:** ✅ Clients survivent à la perte serveur

---

### Test 7 - Performance (pas de freeze)

**Objectif:** Vérifier que le mode non-bloquant fonctionne

- [ ] **7.1** Avec deux clients connectés, jouer normalement pendant 5 minutes
- [ ] **7.2** Surveiller:
  - Framerate mGBA (doit rester ~60fps)
  - Pas de micro-freezes
  - Pas de lag input
  - Son du jeu fluide

- [ ] **7.3** Vérifier usage CPU:
  - mGBA: < 30% CPU par instance
  - Node.js: < 5% CPU

- [ ] **7.4** Déplacer rapidement le personnage (maintenir direction)
- [ ] **7.5** Vérifier que l'autre client reçoit toutes les positions

**Critère de succès:** ✅ Aucun impact perceptible sur performance

---

### Test 8 - Heartbeat (maintien connexion)

**Objectif:** Vérifier que le heartbeat maintient la connexion

- [ ] **8.1** Connecter un client
- [ ] **8.2** **Ne rien faire** pendant 2 minutes (AFK)
- [ ] **8.3** Surveiller logs serveur toutes les 30s:
  ```
  [Heartbeat] Sending ping to player_123456_abc
  ```

- [ ] **8.4** Vérifier que le client **reste connecté** (pas de timeout)
- [ ] **8.5** Après 2 min, déplacer personnage
- [ ] **8.6** Vérifier que les positions sont toujours envoyées

**Critère de succès:** ✅ Connexion maintenue pendant inactivité

---

### Test 9 - Messages JSON malformés

**Objectif:** Vérifier robustesse du parsing JSON

- [ ] **9.1** Modifier temporairement `client/network.lua` pour envoyer JSON invalide:
  ```lua
  client:send("{invalid json\n")
  ```

- [ ] **9.2** Vérifier logs serveur:
  ```
  [Error] Failed to parse message: ...
  ```

- [ ] **9.3** Vérifier que le serveur **ne crash pas**
- [ ] **9.4** Vérifier que les autres clients restent connectés
- [ ] **9.5** Restaurer code correct

**Critère de succès:** ✅ Erreurs JSON gérées sans crash

---

### Test 10 - Multiple rooms

**Objectif:** Tester isolation des rooms

- [ ] **10.1** Modifier `client/main.lua` ligne 20 pour Client 1:
  ```lua
  roomId = "room_a"
  ```

- [ ] **10.2** Modifier pour Client 2:
  ```lua
  roomId = "room_b"
  ```

- [ ] **10.3** Connecter les deux clients
- [ ] **10.4** Vérifier logs serveur:
  ```
  [Room] Client player_1 joined room room_a
  [Room] Client player_2 joined room room_b
  ```

- [ ] **10.5** Vérifier que Client 1 **ne voit PAS** Client 2 (rooms différentes)
- [ ] **10.6** Vérifier overlay Client 1:
  ```
  (Aucun "Players: 2" affiché)
  ```

- [ ] **10.7** Mettre les deux clients dans "room_a"
- [ ] **10.8** Vérifier qu'ils se voient maintenant

**Critère de succès:** ✅ Rooms isolent correctement les joueurs

---

## Documentation des résultats

Après tous les tests, documenter dans `docs/TESTING.md`:

```markdown
# Tests Phase 1 - Résultats

**Date:** YYYY-MM-DD
**Version:** 0.1.0-alpha
**Testeur:** [Nom]

## Environnement
- OS: Windows 10 / Linux / macOS
- mGBA: 0.10.x
- Node.js: 18.x
- ROM: Pokémon Emerald US (BPEE)

## Résultats

| Test | Statut | Notes |
|------|--------|-------|
| Test 1 - Serveur | ✅ PASS | Démarre sans erreur |
| Test 2 - Premier client | ✅ PASS | Connexion OK |
| Test 3 - Synchronisation | ✅ PASS | Positions synchro < 2s |
| Test 4 - Maps différentes | ✅ PASS | Fonctionne |
| Test 5 - Déconnexion | ✅ PASS | Pas de crash |
| Test 6 - Serveur restart | ✅ PASS | Reconnexion OK |
| Test 7 - Performance | ✅ PASS | 60fps, pas de freeze |
| Test 8 - Heartbeat | ✅ PASS | Connexion maintenue |
| Test 9 - JSON invalide | ✅ PASS | Pas de crash |
| Test 10 - Multiple rooms | ✅ PASS | Isolation OK |

## Bugs trouvés
- [Si applicable, lister bugs rencontrés]

## Notes
- [Observations additionnelles]
```

---

## Fichiers à documenter

| Fichier | Modifications |
|---------|--------------|
| `docs/TESTING.md` | Créer ou mettre à jour avec résultats tests Phase 1 |
| `docs/CHANGELOG.md` | Ajouter entrée "Phase 1 - Testing Complete" |

---

## Critères de succès Phase 1

✅ **Phase 1 est COMPLÈTE** quand:
- [x] Tous les 10 tests passent
- [x] Aucun crash serveur ou client
- [x] Performance acceptable (60fps, < 5% CPU overhead)
- [x] Synchronisation positions < 2 secondes
- [x] Documentation tests à jour

---

## Dépannage

### Problème: "Connection refused"
**Solution:** Vérifier que le serveur est démarré sur port 8080

### Problème: "Module 'socket' not found"
**Solution:** mGBA doit être compilé avec support LuaSocket

### Problème: Positions ne se synchronisent pas
**Solution:**
1. Vérifier logs serveur (messages reçus?)
2. Vérifier `Network.send()` appelé dans `sendPositionUpdate()`
3. Vérifier `Network.receive()` appelé dans `update()`

### Problème: Freeze de l'émulateur
**Solution:** Vérifier `client:settimeout(0)` dans `Network.connect()`

---

## Prochaine étape

Après validation Phase 1 → **PHASE2_GHOSTING_RENDER.md** (Affichage visuel des ghosts)
