Set WshShell = CreateObject("WScript.Shell")

WshShell.Run """C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\mgba\mGBA.exe"" -t ""C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.ss1"" --script ""C:\Users\mehdi\Desktop\Dev\PokemonCoopGBABranches\PokemonCoopGBA_NewMovementBranch\client\main.lua"" ""C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba""", 0, False
