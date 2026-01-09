from typing import Any
import sys
import warnings
import copy

DEBUG : bool = "--debug" in sys.argv


def get_channel_number_from_keyonoff_bits(chn: int) -> int: # WHY, YAMAHA.
  LOOKUP : dict[int, int] = {
    0b000: 0,
    0b001: 1,
    0b010: 2,
    0b100: 3,
    0b101: 4,
    0b110: 5,
    0b111: 6 # used for DAC writes in some VGMs?
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

    self.ch3_spmode_freq : int = 0
    self.ch3_spmode_octave : int = 0

    self.attack : int = 0
    self.delay : int = 0
    self.sustain : int = 0
    self.sust_lvl : int = 0
    self.release : int = 0

  @staticmethod
  def compare(a: YM2612Operator, b: YM2612Operator) -> bool:
    return a.detune == b.detune and \
    a.multiplier == b.multiplier and \
    a.level == b.level and \
    a.key_scaling == b.key_scaling and \
    a.amplitude_mod == b.amplitude_mod and \
    a.ssg_eg == b.ssg_eg and \
    a.attack == b.attack and \
    a.delay == b.delay and \
    a.sustain == b.sustain and \
    a.sust_lvl == b.sust_lvl and \
    a.release == b.release

  def serialize(self) -> dict[str, Any]:
    return {
      "detune": self.detune,
      "multiplier": max(self.multiplier, 0.5),
      "level": self.level,
      "key_scaling": self.key_scaling,
      "amplitude_mod": self.amplitude_mod,
      "ssg_eg": self.ssg_eg,
      "envelope": {
        "a": self.attack,
        "d": self.delay,
        "s": self.sustain,
        "s_lvl": self.sust_lvl & 0xF,
        "r": self.release & 0xF
      },
      "ch3_spmode": {
        "freq": self.ch3_spmode_freq,
        "octave": self.ch3_spmode_octave
      }
    }


class YM2612Channel:
  def __init__(self) -> None:
    self.operators : list[YM2612Operator] = [YM2612Operator() for _ in range(4)]
    self.ch3_special_mode : bool = False
    self.frequency : int = 0
    self.octave : int = 0
    self.algorithm : int = 0
    self.op1_feedback : int = 0
    self.pan = 0
    self.ams : int = 0
    self.fms : int = 0
    self.key_on : bool = False


class YM2612Instrument:
  def __init__(self) -> None:
    self.lfo_freq : int = -1
    self.operators : list[YM2612Operator] = [YM2612Operator() for _ in range(4)]
    self.algorithm : int = 0
    self.op1_feedback : int = 0
    self.pan = 0
    self.ams : int = 0
    self.fms : int = 0
    self.metadata : dict[str, Any] = {}

  @staticmethod
  def compare(a: YM2612Instrument, b: YM2612Instrument) -> bool:
    ops_are_equal : bool = True

    for i in range(4):
      if not YM2612Operator.compare(a.operators[i], b.operators[i]):
        ops_are_equal = False
        break

    return a.algorithm == b.algorithm and \
    a.lfo_freq == b.lfo_freq and \
    a.op1_feedback == b.op1_feedback and \
    a.pan == b.pan and \
    a.ams == b.ams and \
    a.fms == b.fms and \
    ops_are_equal

  @staticmethod
  def from_channel(channel: YM2612Channel, lfo_freq: int) -> YM2612Instrument:
    inst : YM2612Instrument = YM2612Instrument()

    inst.operators = copy.deepcopy(channel.operators)
    inst.algorithm = channel.algorithm
    inst.op1_feedback = channel.op1_feedback
    inst.pan = channel.pan
    inst.ams = channel.ams
    inst.fms = channel.fms
    inst.lfo_freq = lfo_freq

    return inst

  def serialize(self) -> dict[str, Any]:
    serialized_ops : list[dict[str, Any]] = []
    for operator in self.operators:
      serialized_ops.append(operator.serialize())
    return {
      "operators": serialized_ops,
      "lfo": None if self.lfo_freq == -1 else self.lfo_freq,
      "algorithm": self.algorithm,
      "op1_feedback": self.op1_feedback,
      "pan": {
        "l": self.pan & 0b10 == 0b10,
        "r": self.pan & 0b01 == 0b01
      },
      "ams": self.ams,
      "fms": self.fms,
      "metadata": self.metadata
    }

class YM2612:
  def __init__(self) -> None:
    self.channels : list[YM2612Channel] = [YM2612Channel() for _ in range(6)]
    self.lfo_freq : int = -1 # -1 = disabled
    self.dac_enable : bool = False
    self.dac : int = 0

  def handle_write_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
    advance : int = 1
    notes : list[str] = ["n" for _ in range(6)]

    if cmd["reg"] == 0x28: # Key on/off
      channel : int = get_channel_number_from_keyonoff_bits(cmd["val"] & 0x07)
      operators : int = (cmd["val"] & 0xF0) >> 4
      key_on : bool = operators != 0

      if channel == 6:
        return {"advance": advance, "notes": notes}

      prev_key_on = self.channels[channel].key_on
      if prev_key_on != key_on:
        notes[channel] = "d" if key_on else "u"

      self.channels[channel].key_on = key_on

      if DEBUG:
        print(f"YM2612: Key On/Off: Ch={channel} Ops={bin(operators)} S={"Down" if key_on else "Up"}")

      if channel > 6:
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
      if DEBUG:
        print(f"YM2612: Timer/Ch3 SpMode Control: Ch3SpMode={self.channels[2].ch3_special_mode} ({bin(cmd["val"])})")
    elif 0x24 <= cmd["reg"] <= 0x26: # Timer A/B
      # we DO NOT care :3
      if DEBUG:
        print(f"YM2612: Timer register write (unimplemented): P={cmd["port"]} R={cmd["reg"]} V={cmd["val"]} ({bin(cmd["val"])})")
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
        #raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        return {"advance": advance, "notes": notes}
      if DEBUG:
        print(f"YM2612: Ch{channel+1} OP{operator+1} - Detune and Multiplier: Dtn={(cmd["val"] & 0b01110000) >> 4} Mul={cmd["val"] & 0xF}")
      self.channels[channel].operators[operator].detune = (cmd["val"] & 0b01110000) >> 4
      self.channels[channel].operators[operator].multiplier = cmd["val"] & 0xF
    elif 0x40 <= cmd["reg"] <= 0x4F: # OP: Total level
      channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
      if channel == -1:
        #raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        return {"advance": advance, "notes": notes}
      self.channels[channel].operators[operator].level = cmd["val"] & 0x7F
      if DEBUG:
        print(f"YM2612: Ch{channel+1} OP{operator+1} - Total level: TL={cmd["val"] & 0x40}")
    elif 0x50 <= cmd["reg"] <= 0x5F: # OP: Rate scaling and attack rate
      channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
      if channel == -1:
        #raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        return {"advance": advance, "notes": notes}
      self.channels[channel].operators[operator].key_scaling = (cmd["val"] & 0xC0) >> 6
      self.channels[channel].operators[operator].attack = cmd["val"] & 0x1F
      if DEBUG:
        print(f"YM2612: Ch{channel+1} OP{operator+1} - Rate scaling & attack: RS={(cmd["val"] & 0xC0) >> 6} A={cmd["val"] & 0x1F}")
    elif 0x60 <= cmd["reg"] <= 0x6F: # OP: Decay 1 and AM
      channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
      if channel == -1:
        #raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        return {"advance": advance, "notes": notes}
      self.channels[channel].operators[operator].amplitude_mod = cmd["val"] & 0x80 == 0x80
      self.channels[channel].operators[operator].delay = cmd["val"] & 0x1F
      if DEBUG:
        print(f"YM2612: Ch{channel+1} OP{operator+1} - Delay & AM: AM={cmd["val"] & 0x80 == 0x80} D={cmd["val"] & 0x1F}")
    elif 0x70 <= cmd["reg"] <= 0x7F: # OP: Sustain
      channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
      if channel == -1:
        raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
      self.channels[channel].operators[operator].sustain = cmd["val"] & 0x1F
      if DEBUG:
        print(f"YM2612: Ch{channel+1} OP{operator+1} - Sustain: S={cmd["val"] & 0x1F}")
    elif 0x80 <= cmd["reg"] <= 0x8F: # OP: Sustain level and release
      channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
      if channel == -1:
        #raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        return {"advance": advance, "notes": notes}
      self.channels[channel].operators[operator].sust_lvl = ((cmd["val"] & 0xF0) >> 4) | 0x10
      self.channels[channel].operators[operator].release = (cmd["val"] & 0xF) | 0x10
      if DEBUG:
        print(f"YM2612: Ch{channel+1} OP{operator+1} - Sustain level & release: SL={((cmd["val"] & 0xF0) >> 4) | 0x10} R={(cmd["val"] & 0xF) | 0x10}")
    elif 0x90 <= cmd["reg"] <= 0x9F: # OP: SSG Envelope Generation (SSG-EG)
      channel, operator = get_channel_and_operator_number_from_reg(cmd["port"], cmd["reg"])
      if channel == -1:
        #raise YM2612Error(f"Unable to get channel number from register byte {cmd["reg"]}")
        return {"advance": advance, "notes": notes}
      self.channels[channel].operators[operator].ssg_eg = cmd["val"] & 0xF
      if DEBUG:
        print(f"YM2612: Ch{channel+1} OP{operator+1} - SSG-EG (envelope gen.): SSG-EG={cmd["val"] & 0xF} ({bin(cmd["val"] & 0xF)})")
    elif 0xA0 <= cmd["reg"] <= 0xAF: # Ch: Frequency
      if 0xA0 <= cmd["reg"] <= 0xA2: # Ch1-3/4-6 frequency LSB
        channel : int = cmd["reg"] - 0xA0 + (3 * cmd["port"])
        if DEBUG:
          print(f"YM2612: Ch{channel+1} - Frequency LSB: FL={cmd["val"]}")
        if (channel == 2 or channel == 5) and self.channels[2].ch3_special_mode:
          self.channels[2].operators[0].ch3_spmode_freq = (self.channels[2].operators[0].ch3_spmode_freq & 0xFF00) | cmd["val"]
        else:
          self.channels[channel].frequency = (self.channels[channel].frequency & 0xFF00) | cmd["val"]
      elif 0xA4 <= cmd["reg"] <= 0xA6: #Ch1-3/4-6 frequency MSB and octave
        channel : int = cmd["reg"] - 0xA4 + (3 * cmd["port"])
        if DEBUG:
          print(f"YM2612: Ch{channel+1} - Frequency MSB & octave: FH={cmd["val"] & 0x07} O={(cmd["val"] >> 3) & 0x07}")
        if (channel == 2 or channel == 5) and self.channels[2].ch3_special_mode:
          self.channels[2].operators[0].ch3_spmode_freq = (self.channels[2].operators[0].ch3_spmode_freq & 0xFF) | (cmd["val"] & 0x07)
          self.channels[2].operators[0].ch3_spmode_octave = (cmd["val"] >> 3) & 0x07
        else:
          self.channels[channel].frequency = (self.channels[channel].frequency & 0xFF) | cmd["val"] & 0x07
          self.channels[channel].octave = (cmd["val"] >> 3) & 0x07
      elif 0xA8 <= cmd["reg"] <= 0xAA: # Ch3(S) OP2-OP4 frequency LSB
        if self.channels[2].ch3_special_mode:
          operator : int = cmd["reg"] - 0xA7
          if DEBUG:
            print(f"YM2612: Ch2 special mode - OP{operator} frequency LSB: FL={cmd["val"]}")
          self.channels[2].operators[operator].ch3_spmode_freq = (self.channels[2].operators[operator].ch3_spmode_freq & 0xFF00) | cmd["val"]
        else:
          if DEBUG:
            warnings.warn(f"YM2612: Write to channel 3 special mode frequency register while channel 3 special mode is off: R={cmd["reg"]} V={cmd["val"]} ({bin(cmd["val"])}")
      elif 0xAC <= cmd["reg"] <= 0xAE: # Ch3(S) OP2-OP4 frequency MSB and octave
        if self.channels[2].ch3_special_mode:
          operator : int = cmd["reg"] - 0xA7
          if DEBUG:
            print(f"YM2612: Ch2 special mode - OP{operator} frequency MSB & octave: FH={cmd["val"] & 0x07} O={(cmd["val"] >> 3) & 0x07}")
          self.channels[2].operators[operator].ch3_spmode_freq = (self.channels[2].operators[0].ch3_spmode_freq & 0xFF) | (cmd["val"] & 0x07)
          self.channels[2].operators[operator].ch3_spmode_octave = (cmd["val"] >> 3) & 0x07
        else:
          if DEBUG:
            warnings.warn(f"YM2612: Write to channel 3 special mode frequency register while channel 3 special mode is off: R={cmd["reg"]} V={cmd["val"]} ({bin(cmd["val"])}")
      else:
        raise YM2612Error(f"Write to invalid frequency register: R={cmd["reg"]} V={cmd['val']} ({bin(cmd["val"])})")
    elif 0xB0 <= cmd["reg"] <= 0xB3: # Ch: Feedback and algorithm
      channel : int = cmd["reg"] - 0xB0 + (3 * cmd["port"])
      self.channels[channel].algorithm = cmd["val"] & 0x07
      self.channels[channel].op1_feedback = (cmd["val"] >> 3) & 0x07
      if DEBUG:
        print(f"YM2612: Ch{channel+1} - Feedback & algorithm: FB={(cmd["val"] >> 3) & 0x07} AL={cmd["val"] & 0x07}")
    elif 0xB4 <= cmd["reg"] <= 0xB6: # Ch: Stereo and LFO sensitivity
      channel : int = cmd["reg"] - 0xB4 + (3 * cmd["port"])
      self.channels[channel].pan = (cmd["val"] >> 6) & 0x03
      self.channels[channel].ams = (cmd["val"] >> 3) & 0x07
      self.channels[channel].fms = cmd["val"] & 0x02
      if DEBUG:
        print(f"YM2612: Ch{channel+1} - Stereo & LFO: PN={(cmd["val"] >> 6) & 0x02} AMS={(cmd["val"] >> 3) & 0x07} FMS={cmd["val"] & 0x02}")
    else:
      if DEBUG:
        raise YM2612Error(f"(debug) Unknown register: P={cmd["port"]} R={cmd["reg"]} V={cmd["val"]} ({bin(cmd["val"])})")


    return {"advance": advance, "notes": notes}
