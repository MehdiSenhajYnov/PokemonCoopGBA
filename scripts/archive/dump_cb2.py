import struct

def decode_thumb_range(data, func_start, start_off, end_off, f):
    i = start_off
    while i < min(end_off, len(data)-1):
        instr = struct.unpack_from('<H', data, i)[0]
        desc = ''
        skip_next = False

        if instr == 0x46C0: desc = 'NOP'
        elif (instr >> 11) == 0b11100:
            off11 = instr & 0x7FF
            if off11 & 0x400: off11 -= 0x800
            target = func_start + i + 4 + off11 * 2
            desc = f'B -> +0x{target-func_start:04X}'
        elif (instr >> 12) == 0b1101:
            cond = (instr >> 8) & 0xF
            off8 = instr & 0xFF
            if off8 & 0x80: off8 -= 0x100
            target = func_start + i + 4 + off8 * 2
            conds = ['BEQ','BNE','BCS','BCC','BMI','BPL','BVS','BVC','BHI','BLS','BGE','BLT','BGT','BLE']
            cn = conds[cond] if cond < len(conds) else f'Bcond'
            desc = f'{cn} -> +0x{target-func_start:04X}'
        elif (instr >> 8) & 0xF8 == 0x20:
            rd = (instr >> 8) & 7
            desc = f'MOVS R{rd}, #{instr & 0xFF} (0x{instr & 0xFF:02X})'
        elif (instr >> 8) & 0xF8 == 0x28:
            rd = (instr >> 8) & 7
            val = instr & 0xFF
            desc = f'CMP R{rd}, #{val} (0x{val:02X})'
        elif (instr >> 13) == 0b01001:
            rd = (instr >> 8) & 7
            imm = (instr & 0xFF) * 4
            pool_addr = ((func_start + i + 4) & ~3) + imm
            save = f.tell()
            f.seek(pool_addr)
            pool_val = struct.unpack('<I', f.read(4))[0]
            f.seek(save)
            desc = f'LDR R{rd}, [PC] => 0x{pool_val:08X}'
        elif (instr >> 9) == 0b01110:
            rd = instr & 7; rn = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            desc = f'STRB R{rd}, [R{rn}, #{imm5}]'
        elif (instr >> 9) == 0b01111:
            rd = instr & 7; rn = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            desc = f'LDRB R{rd}, [R{rn}, #{imm5}]'
        elif (instr >> 11) == 0b01101:
            rd = instr & 7; rn = (instr >> 3) & 7; imm5 = ((instr >> 6) & 0x1F) * 4
            desc = f'LDR R{rd}, [R{rn}, #0x{imm5:02X}]'
        elif (instr >> 11) == 0b01100:
            rd = instr & 7; rn = (instr >> 3) & 7; imm5 = ((instr >> 6) & 0x1F) * 4
            desc = f'STR R{rd}, [R{rn}, #0x{imm5:02X}]'
        elif (instr >> 11) == 0b11110:
            if i+2 < len(data):
                instr2 = struct.unpack_from('<H', data, i+2)[0]
                if (instr2 >> 11) == 0b11111:
                    off_hi = instr & 0x7FF
                    off_lo = instr2 & 0x7FF
                    offset = (off_hi << 12) | (off_lo << 1)
                    if offset & 0x400000: offset -= 0x800000
                    target = 0x08000000 + func_start + i + 4 + offset
                    desc = f'BL 0x{target:08X}'
                    print(f'  +0x{i:04X}: {instr:04X} {instr2:04X}  {desc}')
                    i += 4
                    continue
        elif (instr >> 9) == 0b00110:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f'ADD R{rd}, #{imm}'
        elif (instr >> 9) == 0b00111:
            rd = (instr >> 8) & 7; imm = instr & 0xFF
            desc = f'SUB R{rd}, #{imm}'
        elif (instr >> 8) == 0b01000110:
            d = (instr >> 7) & 1; rm = (instr >> 3) & 0xF; rd = (instr & 7) | (d << 3)
            desc = f'MOV R{rd}, R{rm}'
        elif instr == 0x4770: desc = 'BX LR'
        elif (instr >> 9) == 0b00000 and instr != 0:
            imm5 = (instr >> 6) & 0x1F
            desc = f'LSL #{imm5}'
        elif (instr >> 10) == 0b010000:
            op = (instr >> 6) & 0xF
            ops = ['AND','EOR','LSL','LSR','ASR','ADC','SBC','ROR','TST','NEG','CMP','CMN','ORR','MUL','BIC','MVN']
            desc = ops[op]
        elif (instr >> 8) == 0b10110101: desc = 'PUSH+LR'
        elif (instr >> 8) == 0b10110100: desc = 'PUSH'
        elif (instr >> 8) == 0b10111101: desc = 'POP+PC'
        elif (instr >> 8) == 0b10111100: desc = 'POP'
        else:
            desc = f'(0x{instr:04X})'

        print(f'  +0x{i:04X}: {instr:04X}  {desc}')
        i += 2

with open('C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/rom/Pokemon RunBun.gba', 'rb') as f:
    func_start = 0x037B44
    f.seek(func_start)
    data = f.read(1600)

    print("=== CASE 1 DETAIL (+0xC8 - +0x110) ===")
    decode_thumb_range(data, func_start, 0xC8, 0x110, f)

    print("\n=== CASE 3/5/7 area (+0x140 - +0x1C0) ===")
    decode_thumb_range(data, func_start, 0x140, 0x1C0, f)

    print("\n=== CASE 12 memcpy area (+0x02F0 - +0x0340) ===")
    decode_thumb_range(data, func_start, 0x02F0, 0x0340, f)

    print("\n=== Switch dispatch (+0x30 - +0xA0) ===")
    decode_thumb_range(data, func_start, 0x30, 0xA0, f)
