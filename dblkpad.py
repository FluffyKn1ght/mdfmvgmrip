import sys
import struct

if len(sys.argv) < 2:
  print("USAGE: dblkpad.py <datablock file>")
  exit(1)

data : bytes = b""
with open(sys.argv[1], "rb") as f:
  data = f.read()

exploded_bits : list[int] = []
for byte in data:
  byte = struct.unpack("<b", bytes([byte]))[0]
  exploded_bits.append(byte & 0b10000000)
  exploded_bits.append(byte & 0b01000000)
  exploded_bits.append(byte & 0b00100000)
  exploded_bits.append(byte & 0b00010000)
  exploded_bits.append(byte & 0b00001000)
  exploded_bits.append(byte & 0b00000100)
  exploded_bits.append(byte & 0b00000010)
  exploded_bits.append(byte & 0b00000001)

with open(f"{sys.argv[1]}-pad.bin", "wb") as f:
  i : int = 0
  while i < len(exploded_bits):
    x = exploded_bits[i] | exploded_bits[i+1] | exploded_bits[i+2] | exploded_bits[i+3] | exploded_bits[i+4] | exploded_bits[i+5] | exploded_bits[i+6] | exploded_bits[i+7]
    i += 8
    x |= (exploded_bits[i] | exploded_bits[i+1] | exploded_bits[i+2] | exploded_bits[i+3] | exploded_bits[i+4] | exploded_bits[i+5] | exploded_bits[i+6] | exploded_bits[i+7]) << 7
    i += 8
    x -= 0xFFFF // 4
    f.write(struct.pack("<h", x * 2))