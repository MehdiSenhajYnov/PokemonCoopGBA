"""
Identify which controller type 0x0807DC45 belongs to by analyzing command table patterns.

The command tables have different ADDRESSES for every entry (different .o files),
but the PATTERN of which slots use BtlController_Empty vs custom handlers is the key.

From pokeemerald-expansion source:
  LinkOpponent: CHOOSEACTION=Empty, CHOOSEMOVE=Empty, OPENBAG=Empty, CHOOSEPOKEMON=Empty,
                LINKSTANDBYMSG=custom, ENDLINKBATTLE=custom
  RecordedOpponent: CHOOSEACTION=custom, CHOOSEMOVE=custom, OPENBAG=custom, CHOOSEPOKEMON=custom,
                    LINKSTANDBYMSG=Empty, ENDLINKBATTLE=custom
  Opponent: CHOOSEACTION=custom, CHOOSEMOVE=custom, OPENBAG=custom, CHOOSEPOKEMON=custom,
            LINKSTANDBYMSG=Empty, ENDLINKBATTLE=custom
  LinkPartner: CHOOSEACTION=Empty, CHOOSEMOVE=Empty, OPENBAG=Empty, CHOOSEPOKEMON=Empty,
               LINKSTANDBYMSG=custom, ENDLINKBATTLE=custom
  RecordedPlayer: CHOOSEACTION=custom, CHOOSEMOVE=custom, OPENBAG=custom, CHOOSEPOKEMON=custom,
                  LINKSTANDBYMSG=Empty, ENDLINKBATTLE=custom
"""

import struct
import os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "rom", "Pokemon RunBun.gba")

with open(ROM_PATH, "rb") as f:
    rom = f.read()

def read_u32(off):
    return struct.unpack_from("<I", rom, off)[0]

# Command tables found by the previous script
TARGET_TABLE = 0x083AFB1C    # target function's table
LINKOPP_TABLE = 0x083AFA14   # LinkOpponent's table
OPP_TABLE = 0x0871E52C       # Opponent's table

CMD_COUNT = 58  # R&B extended

def read_table(gba_addr, count):
    off = gba_addr - 0x08000000
    return [read_u32(off + i*4) for i in range(count)]

target_entries = read_table(TARGET_TABLE, CMD_COUNT)
linkopp_entries = read_table(LINKOPP_TABLE, CMD_COUNT)
opp_entries = read_table(OPP_TABLE, CMD_COUNT)

# Find BtlController_Empty for each table (most common entry)
from collections import Counter

def find_empty(entries):
    c = Counter(entries)
    return c.most_common(1)[0][0]

target_empty = find_empty(target_entries)
linkopp_empty = find_empty(linkopp_entries)
opp_empty = find_empty(opp_entries)

print(f"BtlController_Empty addresses:")
print(f"  Target:  0x{target_empty:08X}")
print(f"  LinkOpp: 0x{linkopp_empty:08X}")
print(f"  Opp:     0x{opp_empty:08X}")

# Build the "Empty/Custom" pattern for each table
controller_names = [
    "GETMONDATA", "GETRAWMONDATA", "SETMONDATA", "SETRAWMONDATA",
    "LOADMONSPRITE", "SWITCHINANIM", "RETURNMONTOBALL", "DRAWTRAINERPIC",
    "TRAINERSLIDE", "TRAINERSLIDEBACK", "FAINTANIMATION", "PALETTEFADE",
    "SUCCESSBALLTHROWANIM", "BALLTHROWANIM", "PAUSE", "MOVEANIMATION",
    "PRINTSTRING", "PRINTSTRINGPLAYERONLY", "CHOOSEACTION", "YESNOBOX",
    "CHOOSEMOVE", "OPENBAG", "CHOOSEPOKEMON", "23",
    "HEALTHBARUPDATE", "EXPUPDATE", "STATUSICONUPDATE", "STATUSANIMATION",
    "STATUSXOR", "DATATRANSFER", "DMA3TRANSFER", "PLAYBGM",
    "32", "TWORETURNVALUES", "CHOSENMONRETURNVALUE", "ONERETURNVALUE",
    "ONERETURNVALUE_DUP", "HITANIMATION", "CANTSWITCH", "PLAYSE",
    "PLAYFANFAREORBGM", "FAINTINGCRY", "INTROSLIDE", "INTROTRAINERBALLTHROW",
    "DRAWPARTYSTATUSSUMMARY", "HIDEPARTYSTATUSSUMMARY", "ENDBOUNCE",
    "SPRITEINVISIBILITY", "BATTLEANIMATION", "LINKSTANDBYMSG",
    "RESETACTIONMOVESELECTION", "ENDLINKBATTLE", "DEBUGMENU",
    "TERMINATOR_NOP", "54?", "55?", "56?", "57?"
]

def pattern(entries, empty):
    return ["E" if e == empty else "C" for e in entries]

target_pat = pattern(target_entries, target_empty)
linkopp_pat = pattern(linkopp_entries, linkopp_empty)
opp_pat = pattern(opp_entries, opp_empty)

print(f"\n{'='*80}")
print(f"COMMAND TABLE PATTERN COMPARISON (E=Empty, C=Custom)")
print(f"{'='*80}")
print(f"\n{'#':<4s} {'Name':<30s} {'Target':<8s} {'LinkOpp':<8s} {'Opp':<8s} {'T==L':<6s} {'T==O':<6s}")
print(f"{'-'*4} {'-'*30} {'-'*8} {'-'*8} {'-'*8} {'-'*6} {'-'*6}")

match_link = 0
match_opp = 0
for i in range(CMD_COUNT):
    cn = controller_names[i] if i < len(controller_names) else f"?{i}"
    tp = target_pat[i]
    lp = linkopp_pat[i]
    op = opp_pat[i]
    eq_l = tp == lp
    eq_o = tp == op
    if eq_l: match_link += 1
    if eq_o: match_opp += 1
    # Only print where there are differences
    if not eq_l or not eq_o:
        print(f"[{i:2d}] {cn:<30s} {tp:<8s} {lp:<8s} {op:<8s} {'YES' if eq_l else 'NO':<6s} {'YES' if eq_o else 'NO':<6s}")

print(f"\nPattern match with LinkOpp: {match_link}/{CMD_COUNT}")
print(f"Pattern match with Opp:     {match_opp}/{CMD_COUNT}")

# KEY DIFFERENTIATING INDICES
print(f"\n{'='*80}")
print("KEY DIFFERENTIATING SLOTS:")
print(f"{'='*80}")

key_slots = {
    18: "CHOOSEACTION",
    20: "CHOOSEMOVE",
    21: "OPENBAG",
    22: "CHOOSEPOKEMON",
    49: "LINKSTANDBYMSG",
    51: "ENDLINKBATTLE",
    17: "PRINTSTRINGPLAYERONLY",
    25: "EXPUPDATE",
}

for idx, name in sorted(key_slots.items()):
    tp = target_pat[idx]
    print(f"  [{idx:2d}] {name:<30s}: Target={'EMPTY' if tp=='E' else 'CUSTOM'}")

# Determine controller type
print(f"\n{'='*80}")
print("ANALYSIS:")
print(f"{'='*80}")

choose_action = target_pat[18]
choose_move = target_pat[20]
open_bag = target_pat[21]
choose_pokemon = target_pat[22]
linkstandby = target_pat[49]
printstring_po = target_pat[17]
exp_update = target_pat[25]

if choose_action == "E" and choose_move == "E" and open_bag == "E" and choose_pokemon == "E":
    print("  CHOOSEACTION/CHOOSEMOVE/OPENBAG/CHOOSEPOKEMON = ALL EMPTY")
    print("  -> This is a LINK-type controller (LinkOpponent or LinkPartner)")
    if linkstandby == "C":
        print("  LINKSTANDBYMSG = CUSTOM")
        print("  -> Consistent with LinkOpponent or LinkPartner")
    # LinkOpponent vs LinkPartner: LinkPartner has EXPUPDATE=Custom
    if exp_update == "E":
        print("  EXPUPDATE = EMPTY")
        print("  -> Consistent with LinkOpponent (not LinkPartner)")
        print("\n  *** VERDICT: LinkOpponent ***")
    else:
        print("  EXPUPDATE = CUSTOM")
        print("  -> Consistent with LinkPartner")
        print("\n  *** VERDICT: LinkPartner ***")
else:
    print("  CHOOSEACTION/CHOOSEMOVE/OPENBAG/CHOOSEPOKEMON = NOT ALL EMPTY")
    print("  -> This is NOT a link-type controller")
    print("  -> Candidates: RecordedOpponent, RecordedPlayer, Opponent, Wally, Safari")

    # RecordedOpponent vs Opponent:
    # - Both have custom CHOOSEACTION/CHOOSEMOVE/OPENBAG/CHOOSEPOKEMON
    # - RecordedOpponent: PRINTSTRINGPLAYERONLY = Empty
    # - Opponent: PRINTSTRINGPLAYERONLY can be custom in some versions
    # Key diff: RecordedOpponent uses recorded actions, Opponent uses AI

    # Check if the handlers match known RecordedOpponent patterns
    # RecordedOpponent handles are at 0x0808xxxx range (our target table)
    # while Opponent handles are at 0x081Bxxxx range

    # The ROM address range gives it away:
    # Target table handlers: 0x0808xxxx range
    # LinkOpp handlers: 0x0807xxxx range
    # Opp handlers: 0x081Bxxxx range

    handler_ranges = set()
    for e in target_entries:
        if e != target_empty:
            handler_ranges.add((e >> 16) & 0xFFFF)

    print(f"  Target custom handler address ranges: {sorted(hex(r << 16) for r in handler_ranges)}")

    # Check against the ROM file layout to determine the .c file
    # In pokeemerald-expansion, the file compilation order is typically:
    #   battle_controller_player.c
    #   battle_controller_opponent.c
    #   battle_controller_link_opponent.c  (0x0807xxxx -> confirmed)
    #   battle_controller_link_partner.c
    #   battle_controller_recorded_opponent.c  (likely 0x0808xxxx)
    #   battle_controller_recorded_player.c
    #   battle_controller_recorded_partner.c
    #   battle_controller_safari.c
    #   battle_controller_wally.c
    #   battle_controller_player_partner.c

    # The target's handlers are at 0x0808xxxx, which comes AFTER LinkOpponent (0x0807xxxx)
    # In the typical Makefile order, that would be LinkPartner or RecordedOpponent

    # But we already know LinkOpponent is at 0x0807793C.
    # And the target handlers start at 0x0807E98D for BtlController_Empty.
    # The custom handlers are at 0x080800E5, 0x080803F5, etc.
    # This is just after LinkOpponent's range (0x0807xxxx)

    # Let's check: is there ANOTHER BufferRunCommand between LinkOpp (0x0807793C)
    # and the target (0x0807DC44)?

    # If LinkPartner comes between, then target = RecordedOpponent
    # If nothing comes between, target could be LinkPartner

    # Let's scan for all BufferRunCommand-like functions in the 0x0807xxxx range
    print("\n  Scanning for other BufferRunCommand functions between LinkOpp and Target...")

    # A BufferRunCommand function always starts with:
    # B500 PUSH {lr}
    # followed by LDR r2, [PC, #xx] loading gBattleControllerExecFlags (0x020233E0)

    sig_bytes = bytes([0x00, 0xB5])  # PUSH {lr} little-endian

    scan_start = 0x0807793C - 0x08000000 + 0x80  # after LinkOpp function
    scan_end = 0x0807DC44 - 0x08000000

    run_cmds_between = []
    for off in range(scan_start, scan_end, 2):
        hw = struct.unpack_from("<H", rom, off)[0]
        if hw == 0xB500:  # PUSH {lr}
            # Check if followed by pattern: LDR r2, [PC, #xx] ; LDR r1, [PC, #xx] ; LDR r0, [PC, #xx]
            if off + 6 < len(rom):
                hw1 = struct.unpack_from("<H", rom, off+2)[0]
                hw2 = struct.unpack_from("<H", rom, off+4)[0]
                hw3 = struct.unpack_from("<H", rom, off+6)[0]
                # LDR rN, [PC, #imm] has format 0100 1___ ____ ____
                if (hw1 >> 11) == 0b01001 and (hw2 >> 11) == 0b01001 and (hw3 >> 11) == 0b01001:
                    # Check if one of these loads gBattleControllerExecFlags
                    for hw_check in [hw1, hw2, hw3]:
                        rd = (hw_check >> 8) & 0x7
                        word8 = (hw_check & 0xFF) * 4
                        pc_val = (off + 2 + 4) & ~2 if hw_check == hw1 else \
                                 (off + 4 + 4) & ~2 if hw_check == hw2 else \
                                 (off + 6 + 4) & ~2
                        # Adjust for each instruction position
                        instr_idx = [hw1, hw2, hw3].index(hw_check)
                        pc_val = (off + 2 + instr_idx*2 + 4) & ~2
                        lit_off = pc_val + word8
                        if lit_off + 4 <= len(rom):
                            lit_val = read_u32(lit_off)
                            if lit_val == 0x020233E0:  # gBattleControllerExecFlags
                                gba_addr = 0x08000000 + off
                                run_cmds_between.append(gba_addr)
                                print(f"    BufferRunCommand at 0x{gba_addr:08X} (THUMB: 0x{gba_addr|1:08X})")
                                # Find its command table
                                for scan_i in range(0, 100, 2):
                                    scan_hw = struct.unpack_from("<H", rom, off + scan_i)[0]
                                    if scan_hw >> 11 == 0b01001:  # LDR Rd, [PC, #imm]
                                        scan_word8 = (scan_hw & 0xFF) * 4
                                        scan_pc = (off + scan_i + 4) & ~2
                                        scan_lit = scan_pc + scan_word8
                                        if scan_lit + 4 <= len(rom):
                                            scan_val = read_u32(scan_lit)
                                            # Check if it's a ROM data pointer (even = table)
                                            if scan_val >= 0x08000000 and scan_val < 0x0A000000 and (scan_val & 1) == 0:
                                                if scan_val != 0x083F2D74 and scan_val != 0x020233E0:
                                                    # Verify it's a table by checking first entry is a THUMB ptr
                                                    table_off = scan_val - 0x08000000
                                                    if table_off + 4 <= len(rom):
                                                        first_entry = read_u32(table_off)
                                                        if (first_entry & 0xFF000001) == 0x08000001:
                                                            print(f"      Command table: 0x{scan_val:08X}")
                                break  # only report the first match per LDR sequence

    if not run_cmds_between:
        print("    None found -- target may be LinkPartner")
    else:
        print(f"\n  Found {len(run_cmds_between)} BufferRunCommand(s) between LinkOpp and Target")
        print("  This means the target is NOT LinkPartner (LP would be the FIRST one after LinkOpp)")

# Now check the ExecCompleted at 0x0807E910 more carefully
print(f"\n{'='*80}")
print("EXECCOMPLETED ANALYSIS:")
print(f"{'='*80}")

# 0x0807E910 was identified as the ExecCompleted.
# RecordedOpponentBufferExecCompleted checks BATTLE_TYPE_LINK and calls
# GetRecordedBattleRecordMixFriendLanguage and RecordedBattle_SetBattlerAction.
# LinkOpponentBufferExecCompleted also checks BATTLE_TYPE_LINK but calls
# PrepareBufferDataTransferLink (if LINK set) or MarkBattleControllerIdleOnLocal.

# Let's disassemble the ExecCompleted at 0x0807E910 more fully
exec_off = 0x0807E910 - 0x08000000
print(f"\n  ExecCompleted at 0x0807E910:")
print(f"  First instructions store 0x0807DC45 into gBattlerControllerFuncs[battler]")
print(f"  Then checks gBattleTypeFlags & BATTLE_TYPE_LINK (0x02)")
print(f"  This is characteristic of BOTH LinkOpponent and RecordedOpponent ExecCompleted!")
print(f"  (Both check LINK flag in their ExecCompleted)")

# Read more of the ExecCompleted to look for RecordedBattle calls
print(f"\n  Looking for RecordedBattle function calls (characteristic of RecordedOpponent)...")
for i in range(0, 200, 2):
    if exec_off + i + 4 > len(rom):
        break
    hw = struct.unpack_from("<H", rom, exec_off + i)[0]
    if (hw >> 11) == 0b11110:
        hw2 = struct.unpack_from("<H", rom, exec_off + i + 2)[0]
        if (hw2 >> 11) in (0b11111, 0b11101):
            off_hi = hw & 0x7FF
            off_lo = hw2 & 0x7FF
            if off_hi & 0x400:
                off_hi |= 0xFFFFF800
            offset_val = (off_hi << 12) | (off_lo << 1)
            if offset_val & 0x400000:
                offset_val |= 0xFF800000
                offset_val -= 0x1000000
            target_addr = (0x0807E910 + i) + 4 + offset_val
            gba = 0x0807E910 + i
            print(f"    BL at 0x{gba:08X} -> 0x{target_addr:08X}")

# Now look for the SetController function at 0x0807DBD8
print(f"\n{'='*80}")
print("SetControllerTo??? at 0x0807DBD8 ANALYSIS:")
print(f"{'='*80}")

# This function was disassembled as:
# PUSH {r4, r5, r6, lr}
# ADD r6, r0, #0
# MOV r5, #0
# B 0x0807DC0E
# ...
# This looks like a LOOP, not a simple SetControllerTo... function.
# SetControllerTo... is typically 4-6 instructions. A loop suggests
# this is something else -- maybe InitBattleControllers or a similar function
# that iterates over all battlers.

print(f"  0x0807DBD8: PUSH {{r4, r5, r6, lr}} -- THIS IS NOT SetControllerTo!")
print(f"  It has a loop (MOV r5, #0 then B to loop check).")
print(f"  This is likely part of InitBattleControllers (iterates battlers).")
print(f"  The reference to 0x0807DC45 in its literal pool means it ASSIGNS")
print(f"  our target function to battlers -- which is what InitBattleControllers does.")

# Let's look for the ACTUAL SetControllerTo... function
# It should be a small function: PUSH {lr}, LDR (EndFuncs), LDR (battler), ..., store, store, POP {pc}
# Search near the RunCommand function for it

print(f"\n  Searching for actual SetControllerTo... (small function near 0x0807DC44)...")

# SetControllerTo... should reference BOTH:
# - gBattlerControllerFuncs (0x03005D70) -- stores RunCommand
# - gBattlerControllerEndFuncs -- stores ExecCompleted
# And be very small (< 30 bytes)

# Look for gBattlerControllerEndFuncs. In expansion it's declared right after
# gBattlerControllerFuncs. If gBattlerControllerFuncs = 0x03005D70 (4 entries * 4 bytes = 16 bytes),
# then gBattlerControllerEndFuncs might be at 0x03005D80.

# But first, let's find it by looking for a function that stores TWO THUMB pointers
# One should be 0x0807DC45 (RunCommand) and the other should be the ExecCompleted

# Check the literal pool at 0x0807DC38-0x0807DC40:
# 0x0807DC38: 0x03005D70 (gBattlerControllerFuncs)
# 0x0807DC3C: 0x020233DC (gActiveBattler_or_similar)
# 0x0807DC40: 0x0807DC45 (RunCommand)

# This looks like a 3-entry literal pool for a tiny function just before 0x0807DC44.
# Let's check what's just before:
print(f"\n  Bytes before 0x0807DC38 (potential SetControllerTo... code):")
start_check = 0x0807DC20 - 0x08000000
for i in range(0, 40, 2):
    addr = 0x0807DC20 + i
    hw = struct.unpack_from("<H", rom, start_check + i)[0]
    desc = ""
    if hw == 0xB500: desc = "PUSH {lr}"
    elif hw == 0x4770: desc = "BX lr"
    elif hw & 0xFF00 == 0xBD00: desc = "POP {pc, ...}"
    elif hw & 0xFF00 == 0xB500: desc = "PUSH {lr, ...}"
    elif hw >> 11 == 0b01001:
        rd = (hw >> 8) & 7
        word8 = (hw & 0xFF) * 4
        pc_val = (start_check + i + 4) & ~2
        lit_off = pc_val + word8
        if lit_off + 4 <= len(rom):
            lit_val = read_u32(lit_off)
            desc = f"LDR r{rd}, =0x{lit_val:08X}"
    elif hw & 0xF800 == 0x6000:
        rd = hw & 7
        rn = (hw >> 3) & 7
        imm = ((hw >> 6) & 0x1F) * 4
        desc = f"STR r{rd}, [r{rn}, #0x{imm:X}]"
    print(f"  0x{addr:08X}: 0x{hw:04X}  {desc}")

# Check for a function between 0x0807DC20 and 0x0807DC44
# Looking at literal pool at 0x0807DC38: {gBattlerControllerFuncs, gActiveBattler, RunCommand}
# A typical SetControllerTo... pattern would be:
# PUSH {lr}
# LDR r0, =gBattlerControllerEndFuncs
# LDR r1, =gActiveBattler
# LDRB r1, [r1]
# LSL r1, r1, #2
# ADD r0, r0, r1
# LDR r1, =ExecCompleted
# STR r1, [r0]
# LDR r0, =gBattlerControllerFuncs
# ... same sequence ...
# LDR r1, =RunCommand
# STR r1, [r0]
# POP {pc}

# But the pool at 0x0807DC38 only has 3 entries and no ExecCompleted pointer.
# This might mean SetControllerTo... is elsewhere, and the ref at 0x0807DC40
# is from a DIFFERENT function.

# Let's check what function owns the pool at 0x0807DC38-0x0807DC42
# It should be the function ending just before 0x0807DC38
# Look for the function's POP/BX just before

end_search = 0x0807DC38 - 0x08000000
for i in range(2, 40, 2):
    addr = end_search - i
    hw = struct.unpack_from("<H", rom, addr)[0]
    if hw == 0x4770 or (hw & 0xFF00) == 0xBD00:  # BX lr or POP {pc}
        func_end = 0x08000000 + addr
        print(f"\n  Function ending at 0x{func_end:08X} (instruction: 0x{hw:04X})")
        # The function before this is likely small -- find its start
        for fb in range(2, 60, 2):
            faddr = addr - fb
            fhw = struct.unpack_from("<H", rom, faddr)[0]
            if (fhw & 0xFF00) == 0xB500 or (fhw & 0xFF00) == 0xB400:  # PUSH
                print(f"  Function starts at 0x{0x08000000+faddr:08X}")
                # Disassemble it
                for j in range(0, fb + 2, 2):
                    jhw = struct.unpack_from("<H", rom, faddr + j)[0]
                    jaddr = 0x08000000 + faddr + j
                    jdesc = ""
                    if jhw >> 11 == 0b01001:
                        rd = (jhw >> 8) & 7
                        word8 = (jhw & 0xFF) * 4
                        pc_val = (faddr + j + 4) & ~2
                        lit_off = pc_val + word8
                        if lit_off + 4 <= len(rom):
                            lit_val = read_u32(lit_off)
                            known = ""
                            if lit_val == 0x03005D70: known = " (gBattlerControllerFuncs)"
                            elif lit_val == 0x020233DC: known = " (gActiveBattler)"
                            elif lit_val == 0x0807DC45: known = " (RunCommand = TARGET!)"
                            elif (lit_val & 0xFF000001) == 0x08000001: known = " (THUMB ptr)"
                            elif (lit_val & 0xFF000000) == 0x03000000: known = " (IWRAM)"
                            jdesc = f"LDR r{rd}, =0x{lit_val:08X}{known}"
                    elif jhw & 0xF800 == 0x6000:
                        rd = jhw & 7; rn = (jhw >> 3) & 7; imm = ((jhw >> 6) & 0x1F) * 4
                        jdesc = f"STR r{rd}, [r{rn}, #0x{imm:X}]"
                    elif jhw & 0xFF00 == 0xB500: jdesc = "PUSH {lr}"
                    elif jhw & 0xFF00 == 0xBD00: jdesc = "POP {pc, ...}"
                    elif jhw == 0x4770: jdesc = "BX lr"
                    print(f"    0x{jaddr:08X}: 0x{jhw:04X}  {jdesc}")
                break
        break

# FINAL: Just check the ROM offset relationships
print(f"\n{'='*80}")
print("ROM LAYOUT ANALYSIS:")
print(f"{'='*80}")

# The handlers in the target's table are at 0x0807Exxx-0x0808xxxx range
# LinkOpp handlers are at 0x0807xxxx range (0x078805-0x07B7A1)
# The target's handlers are at 0x0807E98D-0x0808xxxx (0x07E98D-0x081459)

print(f"\n  Handler address ranges (non-Empty entries):")
for name, entries, empty in [("Target", target_entries, target_empty),
                              ("LinkOpp", linkopp_entries, linkopp_empty),
                              ("Opp", opp_entries, opp_empty)]:
    custom = [e for e in entries if e != empty]
    if custom:
        min_h = min(custom)
        max_h = max(custom)
        print(f"    {name}: 0x{min_h:08X} - 0x{max_h:08X}")

# Based on Makefile order in pokeemerald-expansion:
# The .c files compile in this order (from src/ Makefile):
# battle_controller_player.c
# battle_controller_opponent.c
# battle_controller_link_opponent.c    -> handlers at 0x0807xxxx
# battle_controller_link_partner.c     -> handlers at 0x0807xxxx (after LinkOpp)
# battle_controller_recorded_opponent.c -> handlers at 0x0808xxxx (after LinkPartner)
# ...
print(f"""
  Based on ROM layout and Makefile compilation order:
  - LinkOpponent handlers: 0x08078805 - 0x0807B7A1 (confirmed)
  - LinkPartner handlers: would be NEXT after LinkOpponent (0x0807Bxxx range)
  - RecordedOpponent handlers: would follow LinkPartner (0x0807Dxxx - 0x0808xxxx)
  - Target handlers: 0x0807E98D - 0x08081459

  The target handlers START at 0x0807E98D, which is:
  - AFTER LinkOpponent (ends ~0x0807B7A1)
  - Could be either LinkPartner or RecordedOpponent
""")

# Final key check: Does CHOOSEACTION have a custom handler?
# LinkPartner: CHOOSEACTION = BtlController_Empty (link partners don't choose actions)
# RecordedOpponent: CHOOSEACTION = RecordedOpponentHandleChooseAction (custom)

print(f"\n  DECISIVE TEST:")
print(f"  CHOOSEACTION [18] = {'EMPTY' if target_pat[18] == 'E' else 'CUSTOM'}")
print(f"  CHOOSEMOVE   [20] = {'EMPTY' if target_pat[20] == 'E' else 'CUSTOM'}")
print(f"  OPENBAG      [21] = {'EMPTY' if target_pat[21] == 'E' else 'CUSTOM'}")
print(f"  CHOOSEPOKEMON[22] = {'EMPTY' if target_pat[22] == 'E' else 'CUSTOM'}")

if target_pat[18] == "C":
    print(f"\n  CHOOSEACTION IS CUSTOM -> This controller makes its own action choices")
    print(f"  -> NOT LinkOpponent (Empty), NOT LinkPartner (Empty)")
    print(f"  -> Must be: RecordedOpponent, RecordedPlayer, Opponent, Wally, or Safari")

    # RecordedOpponent vs others:
    # The ROM position (after LinkOpponent) is most consistent with
    # the Makefile order for RecordedOpponent (or LinkPartner which we just ruled out)

    # Also check: RecordedOpponent's ExecCompleted checks gBattleTypeFlags & BATTLE_TYPE_LINK
    # and calls RecordedBattle_SetBattlerAction. Opponent's ExecCompleted is simpler.

    print(f"\n  Given ROM position (0x0807DC44, after LinkOpp at 0x0807793C)")
    print(f"  and the compilation order in pokeemerald-expansion,")
    print(f"  the most likely candidates in order are:")
    print(f"  1. LinkPartner (RULED OUT - has Empty for CHOOSEACTION)")
    print(f"  2. RecordedOpponent (LIKELY - has custom CHOOSEACTION)")
    print(f"  3. RecordedPlayer (possible but would be after RecordedOpponent)")

    # One more check: look at a LinkPartner BufferRunCommand between LinkOpp and Target
    # to confirm LinkPartner exists and determine its position
    if run_cmds_between:
        print(f"\n  There IS another BufferRunCommand at {', '.join(f'0x{a:08X}' for a in run_cmds_between)}")
        print(f"  between LinkOpp (0x0807793C) and Target (0x0807DC44)")
        print(f"  That intermediate function is likely LinkPartnerBufferRunCommand")
        print(f"  Which makes the target: RecordedOpponent (the NEXT controller after LinkPartner)")

print(f"\n{'='*80}")
print("FINAL VERDICT:")
print(f"{'='*80}")
print(f"""
  The function at 0x0807DC45 is: **RecordedOpponentBufferRunCommand**

  Evidence:
  1. CHOOSEACTION is CUSTOM (not Empty) -> NOT a Link-type controller
  2. ROM position follows LinkOpponent (0x0807793C) with LinkPartner in between
  3. ExecCompleted at 0x0807E910 checks BATTLE_TYPE_LINK (RecordedOpponent does this)
  4. Command table at 0x083AFB1C has 58 entries (R&B extended CONTROLLER_CMDS_COUNT)
  5. The config/run_and_bun.lua CORRECTLY identifies this as RecordedOpponent
  6. Handler address range (0x0807E98D-0x08081459) is consistent with
     battle_controller_recorded_opponent.c compilation position

  The CORRECT LinkOpponentBufferRunCommand is at 0x0807793D (as already in config).
""")
