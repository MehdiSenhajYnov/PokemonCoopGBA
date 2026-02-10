# Mission : Réparer le système PvP Battle de bout en bout

## Objectif final
Deux joueurs lancent mGBA côte à côte. L'un invite l'autre au duel, l'autre accepte. Un vrai combat PvP se lance (chacun choisit son attaque, il y a une attente pendant que l'autre n'a pas choisi, les animations jouent). Quand le combat se termine, les deux joueurs reviennent là où ils étaient avant le duel.

## Flow attendu complet
```
Joueur A appuie sur A près du ghost → duel_request
Joueur B voit le prompt, appuie A → duel_accept
Serveur envoie duel_warp aux deux → les deux échangent leur party (duel_party)
waiting_party → preparing_battle → in_battle (PvP réel avec sync des attaques) → returning → retour overworld
```

## Contexte technique critique

### Référence qui MARCHE : GBA-PK
Le projet `refs/GBA-PK-multiplayer-main/` contient une implémentation PvP **fonctionnelle** pour FRLG/RS/Emerald vanilla. NOTRE projet doit s'en inspirer mais l'adapter pour **Run & Bun** (basé sur pokeemerald-expansion, pas vanilla Emerald).

**LIRE EN PREMIER :**
1. `refs/GBA-PK-multiplayer-main/BRIEFING.md` — architecture complète GBA-PK
2. `refs/GBA-PK-multiplayer-main/client/12_battle_trade.lua` — le battle system complet qui MARCHE (InitiateBattle, Battlescript, ClearBattle)
3. `refs/GBA-PK-multiplayer-main/client/10_network.lua` — le protocol réseau (chercher BAT, BAT2, BAT3, BATT dans ReceiveData)

### Notre code actuel (CASSÉ)
La dernière session a introduit du code incohérent. Il faut **tout auditer** avant de toucher quoi que ce soit :
- `client/battle.lua` — le module battle, probablement le plus problématique
- `client/main.lua` — le flow de duel (phases warpPhase)
- `client/hal.lua` — abstraction mémoire (normalement OK)
- `client/duel.lua` — système request/accept (normalement OK)
- `server/server.js` — relais réseau (messages duel_*)
- `config/run_and_bun.lua` — adresses mémoire (normalement OK, déjà validées)

### Différences clés GBA-PK vs notre projet
| GBA-PK | Notre projet |
|--------|-------------|
| Paquets 64B fixes binaires | JSON sur TCP |
| FRLG/RS/E vanilla | Run & Bun (pokeemerald-expansion) |
| Script monolithique 15K lignes | Architecture modulaire (battle.lua, hal.lua, etc.) |
| `gBattleTypeFlags` multi-version | `0x02023364` (Run & Bun) |
| `gBattleCommunication` multi-version | `0x0202370E` (Run & Bun) |
| Tables d'adresses par ROM ID | Adresses statiques dans config |

### Adresses confirmées Run & Bun
```
gPlayerParty           = 0x02023A98
gEnemyParty            = 0x02023CF0
gBattleTypeFlags       = 0x02023364
gBattleCommunication   = 0x0202370E
gBattleOutcome         = 0x02023716
gBattleControllerExecFlags = 0x020233E0
gBattlerControllerFuncs = 0x03005D70 (IWRAM!)
gBattleMons            = 0x020233FC
CB2_InitBattle         = 0x080363C1
PlayerBufferRunCommand = 0x0806F151
OpponentBufferRunCommand = 0x081BAD85
```

## Comment tester

### Scripts de lancement (TOUJOURS utiliser ceux-ci, JAMAIS lancer mGBA manuellement)
```powershell
# Terminal 1 : Serveur
powershell -File "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\launch_server.ps1"

# Terminal 2 : Instance 1 (Master/Requester) — Chimchar Lv12
powershell -File "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\launch_client1.ps1"

# Terminal 3 : Instance 2 (Slave/Accepter) — Piplup Lv5, lancer 3s après
powershell -File "C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\launch_client2.ps1"
```

Les scripts auto_duel (`client/auto_duel_requester.lua` et `client/auto_duel_accepter.lua`) automatisent la partie request/accept. `launch_client1.ps1` utilise le requester, `launch_client2.ps1` utilise l'accepter.

### Vérification par screenshots
mGBA génère des screenshots dans `rom/` ou la racine du projet. Après chaque test :
1. Attendre ~20 secondes que le duel s'initie et le combat démarre
2. Prendre des screenshots via le script ou vérifier `rom/Pokemon RunBun-*.png` ou ca peut etre a la racine du projet
3. Analyser visuellement : voit-on l'écran de combat ? Les menus ? Les Pokemon ?

### Vérification par logs
- `update_errors.txt` — erreurs Lua fatales
- Console mGBA — logs détaillés du battle system
- `server_log.txt` / `server_err.txt` — logs serveur

### Critères de succès
1. Les deux instances se connectent au serveur
2. Le requester envoie une demande de duel automatiquement
3. L'accepter accepte automatiquement
4. L'écran de combat apparaît sur LES DEUX instances (sprites Pokemon, HP bars, menus Fight/Bag/Pokemon/Run)
5. Les attaques sont synchronisées (quand un joueur choisit, l'autre attend)
6. Le combat se termine normalement (un Pokemon tombe KO)
7. Les deux joueurs reviennent à l'overworld à leur position d'origine

## Méthodologie recommandée

### Phase 1 : Audit
1. Lire le code actuel (battle.lua, main.lua, server.js)
2. Lire la référence GBA-PK (BRIEFING.md + 12_battle_trade.lua)
3. Identifier les incohérences, le code mort, les bugs évidents
4. Comprendre EXACTEMENT ce que fait GBA-PK qui fonctionne et ce que notre code fait différemment

### Phase 2 : Fix
1. Corriger/réécrire battle.lua si nécessaire en s'inspirant de GBA-PK
2. S'assurer que la state machine est propre et complète
3. Vérifier que le serveur relay correctement les messages
4. Vérifier que main.lua gère toutes les phases correctement

### Phase 3 : Test itératif
1. Lancer les 3 scripts (serveur + 2 clients)
2. Attendre 30s
3. Vérifier les screenshots et logs
4. Si ça ne marche pas, analyser pourquoi, fixer, et relancer
5. Boucler jusqu'à ce que TOUS les critères de succès soient remplis

## Leçons apprises (NE PAS IGNORER)
- `gBattlerControllerFuncs` est en IWRAM (0x03005D70), PAS en EWRAM
- Il faut clear BATTLE_TYPE_LINK + swap BOTH controllers après BattleMainCB2
- NE PAS enforcer les controllers pendant DoBattleIntro (ça casse les animations)
- Auto-press A pendant DoBattleIntro pour dismiss le texte coincé
- `localPartyBackup` est nécessaire car les cases 4 & 6 overwrite gPlayerParty
- `remoteAction` DOIT être reset à chaque nouveau tour
- `BATTLE_TYPE_IS_MASTER` doit être set sur les DEUX joueurs
- OpponentBufferExecCompleted vérifie BATTLE_TYPE_LINK → doit être cleared
- CB2_ReturnToField ou équivalent pour le retour overworld
