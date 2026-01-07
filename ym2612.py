from typing import Any
import sys
import warnings

DEBUG : bool = "--debug" in sys.argv


def get_channel_number_from_keyonoff_bits(chn: int) -> int: # WHY, YAMAHA.
  LOOKUP : dict[int, int] = {
    0b000: 0,
    0b001: 1,
    0b010: 2,
    0b100: 3,
    0b101: 4,
    0b110: 5
  }
  
  try:
    return LOOKUP[chn]
  except KeyError:
    return 0b111

def get_channel_number_and_high_from_freq_reg(reg: int) -> tuple[int, bool | None]:
  LOOKUP : dict[int, tuple[int, bool]] = {
    0xA0: (0, False),
    0xA1: (1, False),
    0xA2: (2, False),
    0xA8: (3, False),
    0xA9: (4, False),
    0xAA: (5, False),

    0xA4: (0, True),
    0xA5: (1, True),
    0xA6: (2, True),
    0xAC: (3, True),
    0xAD: (4, True),
    0xAE: (5, True)
  }
  
  try:
    return LOOKUP[reg]
  except KeyError:
    return (-1, None)

def get_channel_and_operator_number_from_reg(port: int, reg: int) -> tuple[int, int]:
  LOOKUP : dict[int, tuple[int, int]] = {
    0x00: (0, 0),
    0x01: (1, 0),
    0x02: (2, 0),
    
    0x04: (0, 1),
    0x05: (1, 1),
    0x06: (2, 1),
    
    0x08: (0, 2),
    0x09: (1, 2),
    0x0A: (2, 2),

    0x0C: (0, 3),
    0x0D: (1, 3),
    0x0E: (2, 3)
  }
  
  while reg >= 0x10:
    reg -= 0x10

  try:
    o = LOOKUP[reg]
    return (o[0] + (3 * port), o[1])
  except KeyError:
    return (-1, -1)
  


class YM2612Error(Exception):
  def __init__(self, info: str, *args: object) -> None:
    super().__init__(*args)
    self.info : str = info

  def __str__(self) -> str:
    return f"{self.__class__.__name__}: {self.info}"


class YM2612Operator:
  def __init__(self) -> None:
    self.detune : int = 0
    self.multiplier : int = 0
    self.level : int = 0
    self.key_scaling : int = 0
    self.amplitude_mod : bool = False
    self.ssg_eg : int = 0
    self.op1_feedback : int = 0
    
    self.attack : int = 0
    self.delay : int = 0
    self.sustain : int = 0
    self.sust_lvl : int = 0
    self.release : int = 0


class YM2612Channel:
  def __init__(self) -> None:
    self.operators : list[YM2612Operator] = [YM2612Operator() for _ in range(4)]
    self.ch3_special_mode : bool = False
    self.frequency : int = 0
    self.algorithm : int = 0
    self.pan = 0 # 0 = off, 1 = r, -1 = l, 2 = on
    self.ams : int = 0
    self.fms : int = 0


class YM2612:
  def __init__(self) -> None:
    self.channels : list[YM2612Channel] = [YM2612Channel() for _ in range(6)]
    self.lfo_freq : int = -1 # -1 = disabled
    self.dac_enable : bool = False

  def handle_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
    advance : int = 1
    
    if cmd["cmd"] == "ym_write":
      if cmd["reg"] == 0x28: # Key on/off
        channel : int = get_channel_number_from_keyonoff_bits(cmd["val"] & 0x07)
        operators : int = (cmd["val"] & 0xF0) >> 4
        key_down : bool = operators != 0

        if DEBUG:
          print(f"YM2612: Key On/Off: Ch={channel} Ops={bin(operators)} S={"Down" if key_down else "Up"}")

        if channel > 5:
          raise YM2612Error(f"Invalid channel for command 0x28 (key on/off): {channel} ({bin(channel - 1)})")
      elif cmd["reg"] == 0x22: # LFO control
        if cmd["val"] & 0x08 == 0x08:
          self.lfo_freq = cmd["val"] & 0x07
        else:
          self.lfo_freq = -1
        
        if DEBUG:
          print(f"YM2612: LFO Control - Freq={self.lfo_freq} ({"off" if self.lfo_freq == -1 else "on"})")
      elif cmd["reg"] == 0x27: # Timer Control (+ch3)
        self.channels[2].ch3_special_mode = cmd["val"] & 0xC0 == 0x40
        if self.channels[2].ch3_special_mode:
          warnings.warn("Channel 3 is in special mode")
          if DEBUG:
            exit()
        print(f"YM2612: Timer/Ch3 SpMode Control: Ch3SpMode={self.channels[2].ch3_special_mode} ({bin(cmd["val"])})")
        # TODO: Timers A and B (Load A, Load B)?
      elif cmd["reg"] == 0x2B: # DAC Enable
        self.dac_enable = cmd["val"] & 0x80 == 0x80
        
        if DEBUG:
          print(f"YM2612: DAC Enable: DA={self.dac_enable}")
      elif cmd["reg"] == 0x2A: # DAC Value
        if DEBUG:
          print(f"YM2612: DAC value write: DA={self.dac_enable} DAC={cmd["val"]} ({bin(cmd['val'])})")
        if not self.dac_enable:
          warnings.warn(f"YM2612: DAC value write when DAC is not enabled")
      elif 0x30 <= cmd["reg"] <= 0x3F: # OP: Detune and multiplier
        channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
        if channel == -1:
          raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        if DEBUG:
          print(f"YM2612: Ch{channel} OP{operator} - Detune and Multiplier: Dtn={cmd["val"] & 0b01110000 >> 4} Mul={cmd["val"] & 0xF}")
        self.channels[channel].operators[operator].detune = cmd["val"] & 0b01110000 >> 4
        self.channels[channel].operators[operator].multiplier = cmd["val"] & 0xF
      elif 0x40 <= cmd["reg"] <= 0x4F: # OP: Total level
        channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
        if channel == -1:
          raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        self.channels[channel].operators[operator].level = cmd["val"] & 0x40
        if DEBUG:
          print(f"YM2612: Ch{channel} OP{operator} - Total level: TL={cmd["val"] & 0x40}")
      elif 0x50 <= cmd["reg"] <= 0x5F: # OP: Rate scaling and attack rate
        channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
        if channel == -1:
          raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        self.channels[channel].operators[operator].key_scaling = cmd["val"] & 0xC0 >> 6
        self.channels[channel].operators[operator].attack = cmd["val"] & 0x1F
        if DEBUG:
          print(f"YM2612: Ch{channel} OP{operator} - Rate scaling & attack: RS={cmd["val"] & 0xC0 >> 6} A={cmd["val"] & 0x1F}")
      elif 0x60 <= cmd["reg"] <= 0x6F: # OP: Decay 1 and AM
        channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
        if channel == -1:
          raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        self.channels[channel].operators[operator].amplitude_mod = cmd["val"] & 0x80 == 0x80
        self.channels[channel].operators[operator].delay = cmd["val"] & 0x1F
        if DEBUG:
          print(f"YM2612: Ch{channel} OP{operator} - Delay & AM: AM={cmd["val"] & 0x80 == 0x80} D={cmd["val"] & 0x1F}")
      elif 0x70 <= cmd["reg"] <= 0x7F: # OP: Sustain
        channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
        if channel == -1:
          raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        self.channels[channel].operators[operator].sustain = cmd["val"] & 0x1F
        if DEBUG:
          print(f"YM2612: Ch{channel} OP{operator} - Sustain: S={cmd["val"] & 0x1F}")   
      elif 0x80 <= cmd["reg"] <= 0x8F: # OP: Sustain level and release
        channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
        if channel == -1:
          raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        self.channels[channel].operators[operator].sust_lvl = ((cmd["val"] & 0xF0) >> 4) | 0x10
        self.channels[channel].operators[operator].release = (cmd["val"] & 0xF) | 0x10
        if DEBUG:
          print(f"YM2612: Ch{channel} OP{operator} - Sustain level & release: SL={((cmd["val"] & 0xF0) >> 4) | 0x10} R={(cmd["val"] & 0xF) | 0x10}")
      elif 0x90 <= cmd["reg"] <= 0x9F: # OP: SSG Envelope Generation (SSG-EG)
        channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
        if channel == -1:
          raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        self.channels[channel].operators[operator].ssg_eg = cmd["val"] & 0xF
        if DEBUG:
          print(f"YM2612: Ch{channel} OP{operator} - SSG-EG (envelope gen.): SSG-EG={cmd["val"] & 0xF} ({bin(cmd["val"] & 0xF)})")
      elif 0xA0 <= cmd["reg"] <= 0xA3: # Ch: Frequency TODO
        channel = cmd["reg"] - 0xA0
      else:
        if DEBUG:
          raise YM2612Error(f"(debug) Unknown register: P={cmd["port"]} R={cmd["reg"]} V={cmd["val"]} ({bin(cmd["val"])})")


    return {"advance": advance}