# Ghidra headless script — Find battle-related symbols in Pokemon Run & Bun ROM
# Searches for EWRAM variable addresses by scanning ROM literal pools for known
# anchor addresses and then finding nearby cross-references.
#
# Run via: analyzeHeadless <project_dir> <project_name> -import <rom.gba> \
#          -processor ARM:LE:32:v4t -postScript find_battle_symbols.py
#
# @category PokemonCoop

from ghidra.program.model.address import AddressSet
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit
from ghidra.program.model.mem import MemoryAccessException
import struct

# Known anchors (verified addresses)
KNOWN = {
    "gPlayerParty":      0x02023A98,
    "gPlayerPartyCount": 0x02023A95,
    "gEnemyParty":       0x02023CF0,
    "gBattleTypeFlags":  0x020090E8,
    "gMainAddr":         0x02020648,
    "gMainCallback2":    0x0202064C,
    "gMainInBattle":     0x020206AE,
    "gPokemonStorage":   0x02028848,
    "sWarpDestination":  0x020318A8,
    "gRngValue_IWRAM":   0x03005D90,
}

# Target symbols to find
TARGETS = [
    "gBattleResources",
    "gWirelessCommType",
    "gReceivedRemoteLinkPlayers",
    "gLinkPlayers",
    "gBlockReceivedStatus",
    "gBattleCommunication",
    "gBattleControllerExecFlags",
    "gBattleBufferA",
    "gBattleBufferB",
    "gBattleMons",
    "gBattleResults",
    "gBattleStruct",
    "gBattleOutcome",
    "gChosenMoveByBattler",
    "gHitMarker",
    "gBattleMoveDamage",
    "gBattlescriptCurrInstr",
    "gActiveBattler",
    "gBattlerAttacker",
    "gBattlerTarget",
    "gBattlerFainted",
    "gBattleExecBuffer",
    "gActionsByTurnOrder",
    "gCurrentTurnActionNumber",
    "gBattlerPositions",
    "gBattlerPartyIndexes",
    "gMultiplayerId",
]

ROM_BASE = 0x08000000
ROM_SIZE = 0x00800000  # 8MB
EWRAM_BASE = 0x02000000
EWRAM_END  = 0x02040000

def getMemory():
    return currentProgram.getMemory()

def readInt(addr):
    """Read a 32-bit little-endian integer from the program."""
    try:
        mem = getMemory()
        a = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(addr)
        b = [0, 0, 0, 0]
        for i in range(4):
            b[i] = mem.getByte(a.add(i)) & 0xFF
        return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
    except:
        return None

def readShort(addr):
    """Read a 16-bit little-endian integer from the program."""
    try:
        mem = getMemory()
        a = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(addr)
        b0 = mem.getByte(a) & 0xFF
        b1 = mem.getByte(a.add(1)) & 0xFF
        return b0 | (b1 << 8)
    except:
        return None

def findLiteralPoolRefs(targetValue):
    """Scan ROM for all 4-byte aligned occurrences of a value (literal pool entries)."""
    refs = []
    mem = getMemory()
    space = currentProgram.getAddressFactory().getDefaultAddressSpace()

    b0 = targetValue & 0xFF
    b1 = (targetValue >> 8) & 0xFF
    b2 = (targetValue >> 16) & 0xFF
    b3 = (targetValue >> 24) & 0xFF

    for offset in range(0, ROM_SIZE, 4):
        romAddr = ROM_BASE + offset
        try:
            a = space.getAddress(romAddr)
            v0 = mem.getByte(a) & 0xFF
            v1 = mem.getByte(a.add(1)) & 0xFF
            v2 = mem.getByte(a.add(2)) & 0xFF
            v3 = mem.getByte(a.add(3)) & 0xFF
            if v0 == b0 and v1 == b1 and v2 == b2 and v3 == b3:
                refs.append(romAddr)
        except:
            pass

    return refs

def findFunctionStart(addr):
    """Walk backward from addr to find PUSH {LR} or PUSH {Rx..., LR}."""
    space = currentProgram.getAddressFactory().getDefaultAddressSpace()
    mem = getMemory()

    for back in range(2, 1024, 2):
        checkAddr = addr - back
        try:
            a = space.getAddress(checkAddr)
            instr = (mem.getByte(a) & 0xFF) | ((mem.getByte(a.add(1)) & 0xFF) << 8)
            # PUSH {LR} = 0xB500, PUSH {Rx, LR} = 0xB5xx
            if (instr & 0xFF00) == 0xB500 or (instr & 0xFF00) == 0xB400:
                return checkAddr
        except:
            pass

    return None

def scanNearbyLiterals(anchorRomAddr, radius=256):
    """Given a ROM address of a literal pool entry, scan nearby literal pool
    entries for EWRAM addresses. Returns list of (romOffset, ewramAddr)."""
    results = []
    space = currentProgram.getAddressFactory().getDefaultAddressSpace()
    mem = getMemory()

    startAddr = max(ROM_BASE, anchorRomAddr - radius)
    endAddr = min(ROM_BASE + ROM_SIZE, anchorRomAddr + radius)

    for addr in range(startAddr, endAddr, 4):
        val = readInt(addr)
        if val and val >= EWRAM_BASE and val < EWRAM_END:
            results.append((addr, val))

    return results


# =============================================================================
# MAIN ANALYSIS
# =============================================================================

println("=" * 60)
println("  POKEMON RUN & BUN — BATTLE SYMBOL FINDER")
println("=" * 60)
println("")

# Step 1: Verify known anchors exist in ROM literal pools
println("--- STEP 1: Verifying known anchors in ROM ---")
println("")

anchorLitPools = {}  # anchorName -> list of ROM addresses where the anchor value appears

for name, addr in sorted(KNOWN.items()):
    refs = findLiteralPoolRefs(addr)
    anchorLitPools[name] = refs
    println("  %s (0x%08X): %d ROM refs" % (name, addr, len(refs)))

println("")

# Step 2: For each known anchor with ROM refs, scan nearby literal pool entries
# for unknown EWRAM addresses. These are likely other battle globals.
println("--- STEP 2: Scanning near known anchors for unknown EWRAM addresses ---")
println("")

# Collect all EWRAM addresses found near anchors
knownSet = set(KNOWN.values())
nearbyEwram = {}  # ewramAddr -> set of anchor names that reference it nearby

for name, refs in sorted(anchorLitPools.items()):
    if not refs:
        continue

    for litAddr in refs:
        nearby = scanNearbyLiterals(litAddr, 512)
        for romOff, ewramAddr in nearby:
            if ewramAddr not in knownSet:
                if ewramAddr not in nearbyEwram:
                    nearbyEwram[ewramAddr] = set()
                nearbyEwram[ewramAddr].add(name)

# Sort by number of anchor co-references (more = more likely to be battle-related)
sortedEwram = sorted(nearbyEwram.items(), key=lambda x: (-len(x[1]), x[0]))

println("  Found %d unknown EWRAM addresses near known anchors:" % len(sortedEwram))
println("")

# Group by EWRAM region
battleRegion = []  # 0x02008000-0x0200B000 (near gBattleTypeFlags)
mainRegion = []    # 0x02020000-0x02025000 (near gMain, party)
warpRegion = []    # 0x02030000+ (near sWarpDestination)
otherRegion = []

for addr, anchors in sortedEwram:
    entry = (addr, anchors)
    if 0x02008000 <= addr < 0x0200B000:
        battleRegion.append(entry)
    elif 0x02020000 <= addr < 0x02025000:
        mainRegion.append(entry)
    elif 0x02030000 <= addr:
        warpRegion.append(entry)
    else:
        otherRegion.append(entry)

def printRegion(name, entries, limit=40):
    if not entries:
        return
    println("  [%s] (%d addresses)" % (name, len(entries)))
    for i, (addr, anchors) in enumerate(entries[:limit]):
        anchorStr = ", ".join(sorted(anchors))
        println("    0x%08X  (near: %s)" % (addr, anchorStr))
    if len(entries) > limit:
        println("    ... and %d more" % (len(entries) - limit))
    println("")

printRegion("BATTLE REGION (0x02008xxx-0x0200Axxx)", battleRegion)
printRegion("MAIN/PARTY REGION (0x02020xxx-0x02024xxx)", mainRegion)
printRegion("WARP REGION (0x02030xxx+)", warpRegion)
printRegion("OTHER REGIONS", otherRegion, 20)

# Step 3: Try to identify specific targets
println("--- STEP 3: Identifying specific battle variables ---")
println("")

# gBattleResources: pointer to heap struct, should be near gBattleTypeFlags or gEnemyParty
# Look for addresses near those anchors
println("  Searching for gBattleResources candidates...")
battleResRefsNearBTF = [addr for addr, anchors in sortedEwram
                        if "gBattleTypeFlags" in anchors and 0x02008000 <= addr < 0x0200C000]
println("    Near gBattleTypeFlags: %d candidates" % len(battleResRefsNearBTF))
for addr, _ in [(a, nearbyEwram[a]) for a in battleResRefsNearBTF[:20]]:
    println("      0x%08X" % addr)

battleResRefsNearEP = [addr for addr, anchors in sortedEwram
                       if "gEnemyParty" in anchors and 0x02020000 <= addr < 0x02025000]
println("    Near gEnemyParty: %d candidates" % len(battleResRefsNearEP))
for addr, _ in [(a, nearbyEwram[a]) for a in battleResRefsNearEP[:20]]:
    println("      0x%08X" % addr)
println("")

# GetMultiplayerId: already found at 0x0833D67F
println("  GetMultiplayerId: 0x0833D67F (found via mGBA scanner)")
println("")

# gBattleOutcome: scan for address near gBattleTypeFlags
println("  gBattleOutcome candidates (single byte near gBattleTypeFlags):")
for addr in battleResRefsNearBTF[:30]:
    println("    0x%08X" % addr)
println("")

# Step 4: Summarize all found EWRAM addresses for the config
println("=" * 60)
println("  SUMMARY — All unique EWRAM addresses found near battle globals")
println("=" * 60)
println("")

# Print all addresses in the battle region sorted by address
allBattle = sorted(set([addr for addr, _ in sortedEwram if 0x02008000 <= addr < 0x0200C000]))
println("  Battle region (0x02008xxx - 0x0200Bxxx): %d addresses" % len(allBattle))
for addr in allBattle:
    anchors = nearbyEwram[addr]
    println("    0x%08X  (near: %s)" % (addr, ", ".join(sorted(anchors))))

println("")

allMain = sorted(set([addr for addr, _ in sortedEwram if 0x02020000 <= addr < 0x02025000]))
println("  Main/Party region (0x02020xxx - 0x02024xxx): %d addresses" % len(allMain))
for addr in allMain:
    anchors = nearbyEwram[addr]
    println("    0x%08X  (near: %s)" % (addr, ", ".join(sorted(anchors))))

println("")
println("=" * 60)
println("  ANALYSIS COMPLETE")
println("=" * 60)
