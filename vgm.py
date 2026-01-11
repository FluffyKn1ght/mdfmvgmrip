import io
import struct
import warnings
from typing import Any
from abc import ABC, abstractmethod
from enum import Enum


class Chip(Enum):
    UNKNOWN = 0
    YM2612 = 1
    SEGA_PSG = 2


class WriteType(Enum):
    REGULAR = 0
    SEGA_PSG_STEREO = 1


class VGMError(Exception):
    def __init__(self, info: str, *args: object) -> None:
        super().__init__(*args)
        self.info: str = info

    def __str__(self) -> str:
        return f"{self.__class__.__name__}: {self.info}"


class VGMCommand(ABC):
    def __init__(self) -> None:
        pass


class WriteCommand(VGMCommand):
    def __init__(
        self,
        *args,
        chip: Chip = Chip.UNKNOWN,
        port: int = -1,
        register: int = -1,
        value: int = -1,
        type: WriteType = WriteType.REGULAR,
    ) -> None:
        super().__init__()
        self.chip: Chip = chip
        self.port: int = port
        self.register: int = register
        self.value: int = value


class WaitCommand(VGMCommand):
    def __init__(self, wait_time: int) -> None:
        super().__init__()
        self.wait_time: int = wait_time


class YM2612DatabankWriteCommand(WaitCommand):
    def __init__(self, wait_time: int) -> None:
        super().__init__(wait_time)


class DataBlockSection:
    def __init__(self, start: int, end: int) -> None:
        self.start: int = start
        self.end: int = end


class YM2612DatabankSeekCommand(VGMCommand):
    def __init__(self, seek_address: int) -> None:
        super().__init__()
        self.seek_address: int = seek_address


class VGM:
    def __init__(self) -> None:
        self.version: int = -1
        self.commands: list[VGMCommand] = []
        self.gd3_tag: dict[str, str] | None = None
        self.dblock_data: dict[int, bytes] = {}
        self.dblock_sections: list[DataBlockSection] = []

        self._clock_rates: dict[Chip, int] = {}

    def get_clock_rate(self, for_chip: Chip) -> int:
        try:
            return self._clock_rates[for_chip]
        except KeyError:
            return 0

    def is_a_genesis_vgm(self) -> bool:
        return (
            self.get_clock_rate(Chip.SEGA_PSG) != 0
            and self.get_clock_rate(Chip.YM2612) != 0
        )

    @staticmethod
    def from_data(file_data: bytes) -> VGM:
        vgm = VGM()

        data: io.BytesIO = io.BytesIO(file_data)

        if data.read(4) != b"Vgm ":
            raise VGMError("Invalid ident in header")

        data.seek(0x08)
        vgm.version = struct.unpack("<I", data.read(4))[0]

        data.seek(0x2C)
        vgm._clock_rates[Chip.YM2612] = struct.unpack("<I", data.read(4))[0]
        if vgm._clock_rates[Chip.YM2612] > 5000000:
            if vgm.version <= 0x00000101:
                data.seek(0x30)
                vgm._clock_rates[Chip.YM2612] = struct.unpack("<I", data.read(4))[0]

        data.seek(0x28)
        vgm._clock_rates[Chip.SEGA_PSG] = struct.unpack("<I", data.read(4))[0]

        data_offset: int = 0x0C
        if vgm.version >= 0x00000150:
            data.seek(0x34)
            data_offset = struct.unpack("<I", data.read(4))[0]

        data.seek(0x34 + data_offset)
        i = 0x34 + data_offset - 1

        while True:
            i += 1
            cmd = data.read(1)[0]

            if cmd == 0x66:  # end of VGM data stream
                break
            elif cmd == 0x67:  # data block
                data_block = VGM.parse_data_block(data, i)
                vgm.dblock_sections.append(
                    DataBlockSection(
                        len(vgm.dblock_data),
                        len(vgm.dblock_data) + len(data_block["data"]),
                    )
                )
                if data_block["type"] in vgm.dblock_data.keys():
                    vgm.dblock_data[data_block["type"]] += data_block["data"]
                else:
                    vgm.dblock_data[data_block["type"]] = data_block["data"]
                i += 2 + 4 + len(data_block["data"])
            elif cmd == 0x68:  # pcm ram write (stub)
                raise VGMError(f"At byte {i}: PCM RAM write (unimplemented)")
            elif 0x90 <= cmd <= 0x95:  # dac stream control (stub)
                raise VGMError(f"At byte {i}: DAC stream control write (unimplemented)")
            elif 0x80 <= cmd <= 0x8F:  # YM2612 port 0 addr 2a write from databank
                wait_time: int = cmd - 0x80
                vgm.commands.append(YM2612DatabankWriteCommand(wait_time))
            elif cmd == 0x52 or cmd == 0x53:  # YM2612 write
                port: int = max(0, cmd - 0x52)
                register: int = data.read(1)[0]
                value: int = data.read(1)[0]
                i += 2
                vgm.commands.append(
                    WriteCommand(
                        chip=Chip.YM2612, port=port, register=register, value=value
                    )
                )
            elif cmd == 0x4F:  # PSG port 0x06 write
                value: int = data.read(1)[0]
                i += 1
                vgm.commands.append(
                    WriteCommand(
                        chip=Chip.SEGA_PSG,
                        type=WriteType.SEGA_PSG_STEREO,
                        port=0x06,
                        value=value,
                    )
                )
            elif cmd == 0x50:  # PSG write
                value: int = data.read(1)[0]
                i += 1
                vgm.commands.append(WriteCommand(chip=Chip.SEGA_PSG, value=value))
            elif (0x61 <= cmd <= 0x63) or (0x70 <= cmd <= 0x7F):  # wait...
                wait_time: int = -1
                if cmd == 0x61:  # nnnn samples
                    wait_time = struct.unpack("<H", data.read(2))[0]
                elif cmd == 0x62:  # 1/60 of a second (735 samples)
                    wait_time = 735
                elif cmd == 0x63:  # 1/50 of a second (882 samples)
                    wait_time = 882
                else:  # n+1 samples, where n is the lower nibble of the command
                    wait_time = cmd - 0x70 + 1

                vgm.commands.append(WaitCommand(wait_time))
            elif cmd == 0xE0:  # seek to offset dddddddd in YM2612 (type 0x00) databank
                dbank_offset: int = struct.unpack("<I", data.read(4))[0]
                vgm.commands.append(YM2612DatabankSeekCommand(dbank_offset))
            else:  # unknown cmds
                raise VGMError(f"At byte {i}: Unknown command {cmd}")

        return vgm

    @staticmethod
    def parse_data_block(data: io.BytesIO, start: int) -> dict[str, Any]:
        data.read(1)

        db_type: int = data.read(1)[0]
        db_size: int = struct.unpack("<I", data.read(4))[0]
        db_data: bytes = data.read(db_size)

        if db_type != 0x00:
            warnings.warn(f"Data block of non-0x00 (YM2612 PCM data) type detected")

        return {"data": db_data, "type": db_type}
