import struct

def decode_thumb_range(data, func_start, start_off, end_off, f):
    i = start_off
    while i < min(end_off, len(data)-1):
        instr = struct.unpack_from('<H', data, i)[0]
        desc = ''

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
            desc = f'LDR R{rd}, [PC, #{imm}] => 0x{pool_val:08X}'
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
        elif (instr >> 7) == 0b010001110:
            rm = (instr >> 3) & 0xF
            desc = f'BX R{rm}'
        elif (instr >> 9) == 0b00000 and instr != 0:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            desc = f'LSL R{rd}, R{rm}, #{imm5}'
        elif (instr >> 9) == 0b00001:
            rd = instr & 7; rm = (instr >> 3) & 7; imm5 = (instr >> 6) & 0x1F
            desc = f'LSR R{rd}, R{rm}, #{imm5}'
        elif (instr >> 10) == 0b010000:
            op = (instr >> 6) & 0xF
            rs = (instr >> 3) & 7; rd = instr & 7
            ops = ['AND','EOR','LSL','LSR','ASR','ADC','SBC','ROR','TST','NEG','CMP','CMN','ORR','MUL','BIC','MVN']
            desc = f'{ops[op]} R{rd}, R{rs}'
        elif (instr >> 8) == 0b10110101: desc = 'PUSH {+LR}'
        elif (instr >> 8) == 0b10110100:
            rlist = instr & 0xFF
            regs = [f'R{i}' for i in range(8) if rlist & (1<<i)]
            desc = f'PUSH {{{",".join(regs)}}}'
        elif (instr >> 8) == 0b10111101: desc = 'POP {+PC}'
        elif (instr >> 8) == 0b10111100:
            rlist = instr & 0xFF
            regs = [f'R{i}' for i in range(8) if rlist & (1<<i)]
            desc = f'POP {{{",".join(regs)}}}'
        elif (instr >> 11) == 0b10010:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            desc = f'STR R{rd}, [SP, #0x{imm:02X}]'
        elif (instr >> 11) == 0b10011:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            desc = f'LDR R{rd}, [SP, #0x{imm:02X}]'
        elif (instr >> 11) == 0b10100:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            desc = f'ADD R{rd}, PC, #0x{imm:X}'
        elif (instr >> 11) == 0b10101:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 4
            desc = f'ADD R{rd}, SP, #0x{imm:X}'
        elif (instr >> 7) == 0b101100000:
            imm = (instr & 0x7F) * 4
            desc = f'ADD SP, #{imm}'
        elif (instr >> 7) == 0b101100001:
            imm = (instr & 0x7F) * 4
            desc = f'SUB SP, #{imm}'
        elif (instr >> 12) == 0b1100:
            L = (instr >> 11) & 1; rn = (instr >> 8) & 7
            rlist = instr & 0xFF
            regs = [f'R{i}' for i in range(8) if rlist & (1<<i)]
            op = 'LDMIA' if L else 'STMIA'
            desc = f'{op} R{rn}!, {{{",".join(regs)}}}'
        elif (instr >> 6) == 0b0001100:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            desc = f'ADD R{rd}, R{rn}, R{rm}'
        elif (instr >> 6) == 0b0001101:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            desc = f'SUB R{rd}, R{rn}, R{rm}'
        elif (instr >> 6) == 0b0001110:
            rd = instr & 7; rn = (instr >> 3) & 7; imm3 = (instr >> 6) & 7
            desc = f'ADD R{rd}, R{rn}, #{imm3}'
        elif (instr >> 6) == 0b0001111:
            rd = instr & 7; rn = (instr >> 3) & 7; imm3 = (instr >> 6) & 7
            desc = f'SUB R{rd}, R{rn}, #{imm3}'
        elif (instr >> 11) == 0b01000:
            rd = instr & 7; rn = (instr >> 3) & 7; imm5 = ((instr >> 6) & 0x1F) * 2
            desc = f'STRH R{rd}, [R{rn}, #0x{imm5:02X}]'
        elif (instr >> 11) == 0b01001 and False:  # Already handled by LDR PC-relative
            pass
        elif (instr >> 9) == 0b01010:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            desc = f'STR R{rd}, [R{rn}, R{rm}]'
        elif (instr >> 9) == 0b01011:
            rd = instr & 7; rn = (instr >> 3) & 7; rm = (instr >> 6) & 7
            desc = f'LDR R{rd}, [R{rn}, R{rm}]'
        elif (instr >> 11) == 0b10001:
            rd = (instr >> 8) & 7; imm = (instr & 0xFF) * 2
            desc = f'LDRH R{rd}, [R{rn}, #0x{imm:02X}]'
        # STR/LDR halfword register offset
        elif (instr >> 9) == 0b01010:
            pass  # already handled
        else:
            desc = f'(0x{instr:04X})'

        print(f'  +0x{i:04X}: {instr:04X}  {desc}')
        i += 2

with open('C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/rom/Pokemon RunBun.gba', 'rb') as f:
    func_start = 0x037B44
    f.seek(func_start)
    data = f.read(2048)

    # First, let's look at how the dispatch works from the very start
    print("=== FUNCTION PROLOGUE + DISPATCH (+0x00 - +0x40) ===")
    decode_thumb_range(data, func_start, 0x00, 0x40, f)

    # Case 0 (+0x44 to +0x70)
    print("\n=== CASE 0 (+0x44 - +0x70) ===")
    decode_thumb_range(data, func_start, 0x44, 0x70, f)

    # Case 1 (+0x70 to +0xB4) - SendBlock should be here
    print("\n=== CASE 1 (+0x70 - +0xB4) ===")
    decode_thumb_range(data, func_start, 0x70, 0xB4, f)

    # Case 2 (+0xB4 to +0x15C)
    print("\n=== CASE 2 (+0xB4 - +0x15C) ===")
    decode_thumb_range(data, func_start, 0xB4, 0x15C, f)

    # Now let's look at the area around case 12
    # Cases go 0-11 via jump table. Cases 12+ must be secondary dispatch.
    # Let's look at case 11 (+0x5C4) and beyond
    print("\n=== CASE 11 + beyond (+0x5C4 - +0x640) ===")
    decode_thumb_range(data, func_start, 0x5C4, 0x640, f)

    # Now dump the area that we previously identified as "case 12 memcpy"
    print("\n=== EXTENDED CASE 12 area (+0x260 - +0x340) ===")
    decode_thumb_range(data, func_start, 0x260, 0x340, f)

    # Also look at the GBA-PK equivalent offset: +0xE6 area
    # GBA-PK patches CB2_HandleStartBattle+0xE6 with 0xE006
    # In vanilla Emerald, that's inside case 1's SendBlock path
    print("\n=== GBA-PK +0xE6 equivalent area (+0xD8 - +0x120) ===")
    decode_thumb_range(data, func_start, 0xD8, 0x120, f)
