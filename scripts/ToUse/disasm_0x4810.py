import struct
ROM_PATH = r'C:\Users\mehdi\Desktop\Dev\PokemonCoopGBA\rom\Pokemon RunBun.gba'
with open(ROM_PATH, 'rb') as f:
    rom = f.read()
print('ROM loaded:', len(rom), 'bytes')
