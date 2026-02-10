"""
Compare Pokemon party data between two mGBA save states.

mGBA save states are PNG files with a 'gbAs' chunk containing zlib-compressed
GBASerializedState data (0x61000 bytes). EWRAM starts at offset 0x21000.

gPlayerParty is at EWRAM address 0x02023A98, which is EWRAM offset 0x23A98.
Each Pokemon in the party is 100 bytes. There are 6 slots.

Party struct layout (100 bytes per Pokemon):
  - Bytes 0-3:   Personality value (u32)
  - Bytes 4-7:   OT ID (u32)
  - Bytes 8-17:  Nickname (10 bytes)
  - Bytes 18-19: Language, padding
  - Bytes 20-29: OT Name (7 bytes + padding)
  - Bytes 30-31: Markings, checksum (u16)
  - Bytes 32-79: Encrypted substructs (48 bytes, XOR with otId ^ personality)
  - Bytes 80-83: Status condition (u32)
  - Bytes 84:    Level (u8)
  - Bytes 85:    Pokerus remaining (u8)
  - Bytes 86-87: Current HP (u16)
  - Bytes 88-89: Max HP (u16)
  - Bytes 90-91: Attack (u16)
  - Bytes 92-93: Defense (u16)
  - Bytes 94-95: Speed (u16)
  - Bytes 96-97: Sp.Atk (u16)
  - Bytes 98-99: Sp.Def (u16)

Encrypted substructs (48 bytes total, 4 substructs of 12 bytes each):
  Order determined by personality % 24 (see SUBSTRUCTS_ORDER table).
  Decrypted via XOR each u32 with (otId ^ personality).

  Growth substruct (12 bytes):
    - u16 species (offset 0)
    - u16 heldItem (offset 2)
    - u32 experience (offset 4)
    - u8  ppBonuses (offset 8)
    - u8  friendship (offset 9)
    - u16 filler (offset 10) -- in R&B: hidden nature bits

  Attacks substruct (12 bytes):
    - u16 move1 (offset 0)
    - u16 move2 (offset 2)
    - u16 move3 (offset 4)
    - u16 move4 (offset 6)
    - u8  pp1, pp2, pp3, pp4 (offsets 8-11)
"""

import struct
import zlib
import sys
import os

# Substruct order permutation table (personality % 24)
# Format: SUBSTRUCT_ORDERS[i][type] = position
# type: 0=Growth, 1=Attacks, 2=EVs, 3=Misc
# This matches pokeemerald's sBoxMonSubstructOrder and the R&B exporter's table.
SUBSTRUCT_ORDERS = [
    [0, 1, 2, 3], [0, 1, 3, 2], [0, 2, 1, 3], [0, 3, 1, 2],
    [0, 2, 3, 1], [0, 3, 2, 1], [1, 0, 2, 3], [1, 0, 3, 2],
    [2, 0, 1, 3], [3, 0, 1, 2], [2, 0, 3, 1], [3, 0, 2, 1],
    [1, 2, 0, 3], [1, 3, 0, 2], [2, 1, 0, 3], [3, 1, 0, 2],
    [2, 3, 0, 1], [3, 2, 0, 1], [1, 2, 3, 0], [1, 3, 2, 0],
    [2, 1, 3, 0], [3, 1, 2, 0], [2, 3, 1, 0], [3, 2, 1, 0],
]

EWRAM_OFFSET_IN_STATE = 0x21000
PARTY_EWRAM_OFFSET = 0x23A98  # gPlayerParty - 0x02000000
PARTY_COUNT_EWRAM_OFFSET = 0x23A95  # gPlayerPartyCount - 0x02000000
POKEMON_SIZE = 100
PARTY_SLOTS = 6


def extract_ewram_from_savestate(filepath):
    """Extract EWRAM data from an mGBA save state (PNG with gbAs chunk)."""
    with open(filepath, 'rb') as f:
        # Skip PNG signature (8 bytes)
        sig = f.read(8)
        if sig[:4] != b'\x89PNG':
            raise ValueError(f"Not a PNG file: {filepath}")

        while True:
            chunk_header = f.read(8)
            if len(chunk_header) < 8:
                raise ValueError("gbAs chunk not found")

            length = struct.unpack('>I', chunk_header[:4])[0]
            chunk_type = chunk_header[4:8]

            if chunk_type == b'gbAs':
                compressed_data = f.read(length)
                f.read(4)  # CRC
                state_data = zlib.decompress(compressed_data)
                if len(state_data) != 0x61000:
                    raise ValueError(f"Unexpected state size: {len(state_data)}")
                # Extract EWRAM (256KB starting at 0x21000)
                ewram = state_data[EWRAM_OFFSET_IN_STATE:]
                return ewram
            else:
                f.seek(length + 4, 1)

            if chunk_type == b'IEND':
                raise ValueError("gbAs chunk not found before IEND")


def decrypt_substructs(encrypted_data, personality, otid):
    """Decrypt the 48-byte substruct block."""
    key = personality ^ otid
    decrypted = bytearray(48)
    for i in range(0, 48, 4):
        val = struct.unpack_from('<I', encrypted_data, i)[0]
        val ^= key
        struct.pack_into('<I', decrypted, i, val)
    return bytes(decrypted)


def get_substruct(decrypted_data, personality, substruct_index):
    """Get a specific substruct (0=growth, 1=attacks, 2=EVs/condition, 3=misc).

    SUBSTRUCT_ORDERS[i][type] = position, so order[substruct_index] gives
    the position directly.
    """
    order = SUBSTRUCT_ORDERS[personality % 24]
    position = order[substruct_index]
    return decrypted_data[position * 12: (position + 1) * 12]


def parse_pokemon(data, index):
    """Parse a single Pokemon from 100-byte party data."""
    offset = index * POKEMON_SIZE
    poke = data[offset:offset + POKEMON_SIZE]

    if len(poke) < POKEMON_SIZE:
        return None

    personality = struct.unpack_from('<I', poke, 0)[0]
    otid = struct.unpack_from('<I', poke, 4)[0]

    # If personality is 0, slot is empty
    if personality == 0 and otid == 0:
        return None

    # Nickname (bytes 8-17)
    nickname_raw = poke[8:18]

    # Decrypt substructs
    encrypted = poke[32:80]
    decrypted = decrypt_substructs(encrypted, personality, otid)

    # Growth substruct
    growth = get_substruct(decrypted, personality, 0)
    species = struct.unpack_from('<H', growth, 0)[0]
    held_item = struct.unpack_from('<H', growth, 2)[0]
    experience = struct.unpack_from('<I', growth, 4)[0]

    # Attacks substruct
    attacks = get_substruct(decrypted, personality, 1)
    moves = [
        struct.unpack_from('<H', attacks, 0)[0],
        struct.unpack_from('<H', attacks, 2)[0],
        struct.unpack_from('<H', attacks, 4)[0],
        struct.unpack_from('<H', attacks, 6)[0],
    ]
    pps = [attacks[8], attacks[9], attacks[10], attacks[11]]

    # Party data (unencrypted)
    status = struct.unpack_from('<I', poke, 80)[0]
    level = poke[84]
    pokerus = poke[85]
    current_hp = struct.unpack_from('<H', poke, 86)[0]
    max_hp = struct.unpack_from('<H', poke, 88)[0]
    attack = struct.unpack_from('<H', poke, 90)[0]
    defense = struct.unpack_from('<H', poke, 92)[0]
    speed = struct.unpack_from('<H', poke, 94)[0]
    sp_atk = struct.unpack_from('<H', poke, 96)[0]
    sp_def = struct.unpack_from('<H', poke, 98)[0]

    return {
        'personality': personality,
        'otid': otid,
        'nickname_raw': nickname_raw.hex(),
        'species': species,
        'held_item': held_item,
        'experience': experience,
        'moves': moves,
        'pps': pps,
        'status': status,
        'level': level,
        'pokerus': pokerus,
        'current_hp': current_hp,
        'max_hp': max_hp,
        'attack': attack,
        'defense': defense,
        'speed': speed,
        'sp_atk': sp_atk,
        'sp_def': sp_def,
    }


def print_pokemon(poke, slot):
    """Pretty-print a Pokemon's data."""
    if poke is None:
        print(f"  Slot {slot + 1}: [Empty]")
        return

    print(f"  Slot {slot + 1}:")
    print(f"    Species ID:    {poke['species']}")
    print(f"    Personality:   0x{poke['personality']:08X}")
    print(f"    OT ID:         0x{poke['otid']:08X}")
    print(f"    Level:         {poke['level']}")
    print(f"    HP:            {poke['current_hp']}/{poke['max_hp']}")
    print(f"    Stats:         ATK={poke['attack']} DEF={poke['defense']} "
          f"SPD={poke['speed']} SPA={poke['sp_atk']} SPD={poke['sp_def']}")
    print(f"    Moves:         {poke['moves']} (PP: {poke['pps']})")
    print(f"    Held Item:     {poke['held_item']}")
    print(f"    Experience:    {poke['experience']}")
    print(f"    Status:        0x{poke['status']:08X}")
    if poke['pokerus']:
        print(f"    Pokerus:       {poke['pokerus']}")


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    rom_dir = os.path.join(base_dir, 'rom')

    ss1_path = os.path.join(rom_dir, 'Pokemon RunBun.ss1')
    ss2_path = os.path.join(rom_dir, 'Pokemon RunBun.ss2')

    if not os.path.exists(ss1_path):
        print(f"ERROR: {ss1_path} not found")
        sys.exit(1)
    if not os.path.exists(ss2_path):
        print(f"ERROR: {ss2_path} not found")
        sys.exit(1)

    print("=" * 60)
    print("  mGBA Save State Party Comparison")
    print("=" * 60)

    for label, path in [("Save State 1 (ss1)", ss1_path), ("Save State 2 (ss2)", ss2_path)]:
        print(f"\n--- {label} ---")
        print(f"  File: {os.path.basename(path)} ({os.path.getsize(path)} bytes)")

        ewram = extract_ewram_from_savestate(path)
        party_count = ewram[PARTY_COUNT_EWRAM_OFFSET]
        print(f"  Party count: {party_count}")

        party_data = ewram[PARTY_EWRAM_OFFSET:PARTY_EWRAM_OFFSET + PARTY_SLOTS * POKEMON_SIZE]

        for i in range(min(party_count, PARTY_SLOTS)):
            poke = parse_pokemon(party_data, i)
            print_pokemon(poke, i)

    # Compare
    print("\n" + "=" * 60)
    print("  COMPARISON")
    print("=" * 60)

    ewram1 = extract_ewram_from_savestate(ss1_path)
    ewram2 = extract_ewram_from_savestate(ss2_path)

    party1_data = ewram1[PARTY_EWRAM_OFFSET:PARTY_EWRAM_OFFSET + PARTY_SLOTS * POKEMON_SIZE]
    party2_data = ewram2[PARTY_EWRAM_OFFSET:PARTY_EWRAM_OFFSET + PARTY_SLOTS * POKEMON_SIZE]

    count1 = ewram1[PARTY_COUNT_EWRAM_OFFSET]
    count2 = ewram2[PARTY_COUNT_EWRAM_OFFSET]

    if party1_data == party2_data:
        print("\n  WARNING: Party data is IDENTICAL between the two save states!")
    else:
        print("\n  Party data DIFFERS between the two save states.")

    for i in range(max(count1, count2)):
        p1 = parse_pokemon(party1_data, i) if i < count1 else None
        p2 = parse_pokemon(party2_data, i) if i < count2 else None

        if p1 is None and p2 is None:
            continue

        s1 = p1['species'] if p1 else '-'
        s2 = p2['species'] if p2 else '-'
        pid1 = f"0x{p1['personality']:08X}" if p1 else '-'
        pid2 = f"0x{p2['personality']:08X}" if p2 else '-'
        lv1 = p1['level'] if p1 else '-'
        lv2 = p2['level'] if p2 else '-'

        same = "SAME" if (p1 and p2 and p1['species'] == p2['species'] and
                          p1['personality'] == p2['personality']) else "DIFFERENT"

        print(f"\n  Slot {i + 1}: {same}")
        print(f"    SS1: Species={s1}, PID={pid1}, Lv={lv1}")
        print(f"    SS2: Species={s2}, PID={pid2}, Lv={lv2}")


if __name__ == '__main__':
    main()
