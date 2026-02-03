# Phase 2 - Optimisation Performance

> **Statut:** En attente
> **Type:** Optimization — Profilage et amélioration performance
> **Objectif:** Mesurer et optimiser les performances pour atteindre < 100ms latency et < 5% CPU overhead.

---

## Objectifs de performance

**Cibles:**
- Latency localhost: < 100ms
- CPU overhead client: < 5%
- CPU overhead serveur: < 5%
- Support 10+ clients simultanés
- Framerate stable 60fps

---

## Mesures et optimisations

### 1. Profiling

- [ ] **1.1** Mesurer latency réseau:
  ```lua
  local sentTime = os.time()
  -- Send position
  -- Receive echo
  local latency = os.time() - sentTime
  ```

- [ ] **1.2** Mesurer CPU avec htop/Task Manager
- [ ] **1.3** Profiler mGBA avec frame timing

### 2. Optimisations réseau

- [ ] **2.1** Limiter fréquence envoi positions (UPDATE_RATE configurable)
- [ ] **2.2** Envoyer seulement si position changée (déjà implémenté)
- [ ] **2.3** Compression JSON (retirer champs inutiles)

### 3. Optimisations rendu

- [ ] **3.1** Culling: ne render que ghosts visibles à l'écran
- [ ] **3.2** Limiter appels gui.draw* par frame
- [ ] **3.3** Cacher noms si trop de joueurs

### 4. Tests stress

- [ ] **4.1** Tester avec 10 clients
- [ ] **4.2** Tester avec 20 clients
- [ ] **4.3** Mesurer dégradation performance

---

## Documentation

Créer `docs/performance.md` avec:
- Benchmarks
- Résultats tests
- Recommandations config

---

## Prochaine étape

Après cette tâche → **PHASE2_FINAL_TESTING.md**
