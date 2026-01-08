import warnings
import struct
from typing import Any
import io


class VGMError(Exception):
  def __init__(self, info: str, *args: object) -> None:
    super().__init__(*args)
    self.info : str = info

  def __str__(self) -> str:
    return f"{self.__class__.__name__}: {self.info}"


class VGM:
  def __init__(self) -> None:
    # SEGA PSG, YM2612
    self.version : int = -1
    self.commands : list[dict[str, Any]] = []
    self.psg_clock : int = 0
    self.ym2612_clock : int = 0
    self.gd3_tag : dict[str, str] | None = None
    self.data : dict = {}

  @staticmethod
  def from_data(file_data: bytes, *args, dump_cmds_to: str | None = None) -> VGM:
    vgm = VGM()

    data : io.BytesIO = io.BytesIO(file_data)

    if data.read(4) != b"Vgm ":
      raise VGMError("Invalid ident in header")
    
    data.seek(0x08)
    vgm.version = struct.unpack("<I", data.read(4))[0]

    data.seek(0x2C)
    ym2612_clock : int = struct.unpack("<I", data.read(4))[0]
    if ym2612_clock > 5000000:
      if vgm.version <= 0x00000101:
        data.seek(0x30)
        ym2612_clock = struct.unpack("<I", data.read(4))[0]

    if ym2612_clock == 0:
      warnings.warn("YM2612 is not used in this file")
    elif ym2612_clock & 0x80 == 0x80:
      warnings.warn("YM3438 is used (bit 31 is set in YM2612 clock rate)")

    data.seek(0x28)
    psg_clock : int = struct.unpack("<I", data.read(4))[0]
    if psg_clock == 0:
      warnings.warn("SEGA PSG (TI SN76489) is not used in this file")

    if ym2612_clock == 0 and psg_clock == 0:
      raise VGMError("Not a Sega MegaDrive/Genesis .VGM (PSG&YM2612 are not used)")
    
    data_offset : int = 0x0C
    if vgm.version >= 0x00000150:
      data.seek(0x34)
      data_offset = struct.unpack("<I", data.read(4))[0]
    
    data.seek(0x34 + data_offset)
    i = 0x34 + data_offset - 1

    cmddump : io.TextIOWrapper | None = None
    if type(dump_cmds_to) is str:
      cmddump = open(dump_cmds_to, "w")

    while True:
      i += 1
      cmd = data.read(1)[0]

      if cmd == 0x66: # end of VGM data stream
        if cmddump: 
          cmddump.write("End of VGM data stream [0x66]\n")
        break
      elif cmd == 0x67: # data block
        data_block = VGM.parse_data_block(data, i)
        if not data_block["type"] in vgm.data.keys():
          vgm.data[data_block["type"]] = {
            "data": data_block["data"], 
            "sections": [{
              "start": 0, "end": len(data_block["data"])
            }]
          }
        else:
          vgm.data[data_block["type"]]["data"] += data_block["data"]
          vgm.data[data_block["type"]]["sections"].append({
            "start": len(vgm.data[data_block["type"]]["data"]) + 1,
            "end": len(vgm.data[data_block["type"]]["data"]) + 1 + len(data_block["data"])
          })
        i += 2 + 4 + len(vgm.data)
        
        if cmddump: 
          cmddump.write(f"Data block [0x67]: size {len(data_block["data"])}, type {data_block["type"]}\n")
      elif cmd == 0x68: # pcm ram write (stub)
        raise VGMError(f"At byte {i}: PCM RAM write (unimplemented)")
      elif 0x90 <= cmd <= 0x95: # dac stream control (stub)
        if cmddump: 
          cmddump.write(f"DAC stream control command [0x90-0x95, {cmd}] - UNIMPLEMENTED\n")
          cmddump.close()
        raise VGMError(f"At byte {i}: DAC stream control write (unimplemented)")
      elif 0x80 <= cmd <= 0x8F: # YM2612 port 0 addr 2a write from databank
        wait_time : int = cmd - 0x80
        if cmddump:
          cmddump.write(f"YM2612 write from databank and wait {wait_time} samples [0x8n, {cmd}]\n")
        vgm.commands.append({"cmd": "ym_dbank_write", "wait": wait_time})
      elif cmd == 0x52 or cmd == 0x53: # YM2612 write
        port : int = max(0, cmd - 0x52)
        register : int = data.read(1)[0]
        value : int = data.read(1)[0]
        if cmddump:
          cmddump.write(f"YM2612 write [0x52/0x53] - port {port}, reg {register}, val {value} ({bin(value)})\n")
        i += 2
        vgm.commands.append({"cmd": "ym_write", "port": port, "reg": register, "val": value})
      elif cmd == 0x4F: # PSG port 0x06 write
        value : int = data.read(1)[0]
        if cmddump:
          cmddump.write(f"SEGA PSG (SN76489) stereo write - port 0x06, val {value} ({bin(value)})\n")
        i += 1
        vgm.commands.append({"cmd": "psg_stereo_write", "val": value})
      elif cmd == 0x50: # PSG write
        value : int = data.read(1)[0]
        if cmddump:
          cmddump.write(f"SEGA PSG (SN76489) write - val {value} ({bin(value)})\n")
        i += 1
        vgm.commands.append({"cmd": "psg_write", "val": value})
      elif (0x61 <= cmd <= 0x63) or (0x70 <= cmd <= 0x7F): # wait...
        wait_time : int = -1
        if cmd == 0x61: # nnnn samples
          wait_time = struct.unpack("<H", data.read(2))[0]
        elif cmd == 0x62: # 1/60 of a second (735 samples)
          wait_time = 735
        elif cmd == 0x63: # 1/50 of a second (882 samples)
          wait_time = 882
        else: # n+1 samples, where n is the lower nibble of the command
          wait_time = cmd - 0x70 + 1
        
        if cmddump:
          cmddump.write(f"Wait {wait_time} samples [{cmd}]\n")
        vgm.commands.append({"cmd": "wait", "wait": wait_time})
      elif cmd == 0xE0: # seek to offset dddddddd in YM2612 (type 0x00) databank
        dbank_offset : int = struct.unpack("<I", data.read(4))[0]
        if cmddump:
          cmddump.write(f"Seek to offset {dbank_offset} in YM2612 PCM databank [0xE0]\n")
        vgm.commands.append({"cmd": "ym_dbank_seek", "seek": dbank_offset})
      else: # unknown cmds
        if cmddump:
          cmddump.write(f"UNKNOWN COMMAND {cmd} (unimplemented)\n")
          cmddump.close()
        raise VGMError(f"At byte {i}: Unknown command - wat da hell is {cmd}?!?!?!?")
        
    if cmddump:
      print(f"Commands dumped to {dump_cmds_to}")
      cmddump.close()      

    return vgm
  
  @staticmethod
  def parse_data_block(data: io.BytesIO, start: int) -> dict[str, Any]:
    data.read(1)
    
    db_type : int = data.read(1)[0]
    db_size : int = struct.unpack("<I", data.read(4))[0]
    db_data : bytes = data.read(db_size)

    if db_type != 0x00:
      warnings.warn(f"Data block of non-0x00 (YM2612 PCM data) type detected")

    return {"data": db_data, "type": db_type}