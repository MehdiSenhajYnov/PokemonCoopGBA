import struct, os

ROM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), chr(114)+chr(111)+chr(109), chr(80)+chr(111)+chr(107)+chr(101)+chr(109)+chr(111)+chr(110)+chr(32)+chr(82)+chr(117)+chr(110)+chr(66)+chr(117)+chr(110)+chr(46)+chr(103)+chr(98)+chr(97))

KNOWN = {}
KNOWN[0x020233EE] = str(chr(103)+chr(66)+chr(97)+chr(116)+chr(116)+chr(108)+chr(101)+chr(114)+chr(80)+chr(111)+chr(115)+chr(105)+chr(116)+chr(105)+chr(111)+chr(110)+chr(115))