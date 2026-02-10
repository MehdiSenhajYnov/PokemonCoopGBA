"""
Split GBA-PK Client/Server ALPHA 4 monolithic Lua files into logical modules.
Both files are identical except line 3 (ServerType = "c" vs "h").
All output files are <=1600 lines to fit in Claude Code's Read limit (2000 lines).
"""
import os
import shutil

BASE = r"C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\refs\GBA-PK-multiplayer"
CLIENT_SRC = os.path.join(BASE, "GBA-PK_Client ALPHA 4.lua")
SERVER_SRC = os.path.join(BASE, "GBA-PK_Server ALPHA 4.lua")
CLIENT_DIR = os.path.join(BASE, "Client")
SERVER_DIR = os.path.join(BASE, "Server")

# Sections defined by (start_line, end_line, filename, description)
# Lines are 1-indexed, end_line is inclusive
# MAX ~1600 lines per file (header adds ~5 lines, Read tool limit is 2000)
SECTIONS = [
    # Config & globals
    (1,    380,  "01_config.lua",              "Configuration, globals, language tables, palettes, objects"),

    # Game templates — split into FRLG+base (1-1032) and Emerald+RSE (1033-2060)
    (381,  1412, "02a_templates_base_frlg.lua", "copyTemplate, createMetatable, FRLG/LG templates"),
    (1413, 2440, "02b_templates_rse_emerald.lua","RSE/Emerald/Ruby/Sapphire templates"),

    # Map + callbacks (small)
    (2441, 2689, "03_map_database.lua",         "MapBanks lookup table"),
    (2690, 2930, "04_callbacks.lua",            "Callback address tables by game version"),

    # Sprite data — split at sprite [4] boundary (line 4140 in original = ~1210 in chunk)
    (2931, 4140, "05a_sprite_data_1.lua",       "spriteData sprites [1]-[3] (Male/Female FRLG, Male RSE)"),
    (4141, 5574, "05b_sprite_data_2.lua",       "spriteData sprites [4]-[6],[1000]-[1005] (Female RSE, Emerald, specials)"),

    # Utils, Player, NPC, Memory
    (5575, 5880, "06_utils.lua",                "Utility functions, ConsoleTest class, SimuSocket class"),
    (5881, 6551, "07_player_class.lua",         "Player class (constructor, 60+ getter/setter methods)"),
    (6552, 6841, "08_npc_class.lua",            "NPC class, FindNPC/Player helpers, AddPlayer/RemovePlayer"),
    (6842, 7279, "09_memory_ops.lua",           "LoadPalette, GetGameVersion, createChars, WriteBuffers, WriteRom, ReadBuffers"),

    # Position, Animation, Network
    (7280, 8529, "10_position.lua",             "GetPosition (main position reader), IsInMenu"),
    (8530, 10133,"11_animation.lua",            "AnimatePlayerMovement, HandleSprite, CalculateRelative, Draw/Erase functions"),
    (10134,11383,"12_network.lua",              "StartScript, StopScript, CreateNetwork, Connection, ReceiveData, SendData"),

    # Pokemon, Battle/Trade, Interaction, Main
    (11384,12047,"13_pokemon.lua",              "DecryptPokemon, EncryptPokemon, GetPokemonTeam, HealPokemon, stats"),
    (12048,13292,"14_battle_trade.lua",         "ClearTrade, Tradescript, ClearBattle, InitiateBattle, Battlescript"),
    (13293,14598,"15_interaction.lua",          "Interaction handler, GetNicknameBuffer, Loadscript, script memory ops"),
    (14599,99999,"16_main_loop.lua",            "MainLogic, Render, GetCurrentFPS, console commands, callbacks"),
]


def split_file(src_path, out_dir):
    # Clean output dir
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    with open(src_path, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()

    total = len(all_lines)
    print(f"\n  Source: {os.path.basename(src_path)} ({total} lines)")
    print(f"  Output: {out_dir}\n")

    # Write an index file
    index_lines = [f"# {os.path.basename(src_path)} — Split Modules\n\n"]
    index_lines.append(f"Original file: {total} lines\n\n")
    index_lines.append("| # | File | Lines | Count | Description |\n")
    index_lines.append("|---|------|-------|-------|-------------|\n")

    warnings = []
    for i, (start, end, filename, desc) in enumerate(SECTIONS):
        actual_end = min(end, total)
        chunk = all_lines[start - 1 : actual_end]  # convert to 0-indexed
        count = len(chunk)

        # Add header comment to each chunk
        header = f"-- ============================================================\n"
        header += f"-- {filename} — {desc}\n"
        header += f"-- Lines {start}-{actual_end} from original file\n"
        header += f"-- ============================================================\n\n"

        total_with_header = count + 5  # 4 header lines + 1 blank

        out_path = os.path.join(out_dir, filename)
        with open(out_path, "w", encoding="utf-8") as out:
            out.write(header)
            out.writelines(chunk)

        status = "OK" if total_with_header <= 1800 else "WARNING: >1800 lines!"
        if total_with_header > 1800:
            warnings.append(filename)
        print(f"  {filename:35s}  lines {start:5d}-{actual_end:5d}  ({count:4d} + 5 header = {total_with_header:4d})  {status}")
        index_lines.append(f"| {i+1} | `{filename}` | {start}-{actual_end} | {count} | {desc} |\n")

    # Write index
    index_path = os.path.join(out_dir, "INDEX.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.writelines(index_lines)
    print(f"\n  Index written: {index_path}")

    if warnings:
        print(f"\n  *** FILES OVER 1800 LINES: {', '.join(warnings)} ***")
    else:
        print(f"\n  All files under 1800 lines - OK for Claude Code Read tool")


if __name__ == "__main__":
    print("=" * 60)
    print("Splitting GBA-PK ALPHA 4 files into logical modules")
    print("=" * 60)

    split_file(CLIENT_SRC, CLIENT_DIR)
    split_file(SERVER_SRC, SERVER_DIR)

    print("\nDone!")
