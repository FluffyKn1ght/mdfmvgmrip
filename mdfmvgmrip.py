import gzip
import argparse
from typing import Any
import warnings
import os
import pathlib
import sys
import json

from vgm import *
from ym2612 import YM2612, YM2612Error, YM2612Instrument, YM2612State

import mido


DEBUG: bool = "--debug" in sys.argv

SAMPLE_RATE: int = 44100
PPQN: int = 480


def dump_datablocks(data: dict, sections: list[DataBlockSection], out_dir: str) -> None:
    try:
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise IOError(f"Unable to create FM instrument output folder: {e}")

    i = 0
    for section in sections:
        with open(os.path.join(out_dir, f"DATABLK{i}.bin"), "wb") as f:
            f.write(data[0x00][section.start : section.end + 1])

    print(f"Saved all data blocks to {out_dir} :3")


def dump_fm_instruments(vgm: VGM, out_dir: str) -> None:
    ym: YM2612 = YM2612(vgm.get_clock_rate(Chip.YM2612))

    NO_CHANGE: list[str] = ["n" for _ in range(6)]

    instruments: list[YM2612Instrument] = []
    i: int = 0
    c: int = 0
    for cmd in vgm.commands:
        if type(cmd) is WriteCommand:
            if cmd.chip == Chip.YM2612:
                result: YM2612State = ym.handle_write_command(cmd)

                if result.notes != NO_CHANGE:
                    for channel in range(6):
                        if result.notes[channel] == "d":
                            inst: YM2612Instrument = YM2612Instrument.from_channel(
                                ym.channels[channel], ym.lfo_freq
                            )
                            idx: int = -1
                            j: int = 0
                            for inst2 in instruments:
                                if YM2612Instrument.compare(inst, inst2):
                                    idx = j
                                    break
                                j += 1

                            if idx == -1:
                                key_on_ops: dict[str, bool] | None = None

                                if cmd.register == 0x28:
                                    key_on_ops = {
                                        "0": cmd.value & 0x80 == 0x80,
                                        "1": cmd.value & 0x40 == 0x40,
                                        "2": cmd.value & 0x20 == 0x20,
                                        "3": cmd.value & 0x10 == 0x10,
                                    }

                                inst.metadata = {
                                    "all_uses": [
                                        {
                                            "at_command": c,
                                            "at_sample": i,
                                            "key_on_ops": key_on_ops,
                                        }
                                    ]
                                }
                                instruments.append(inst)
                            else:
                                key_on_ops: dict[str, bool] | None = None

                                if cmd.register == 0x28:
                                    key_on_ops = {
                                        "0": cmd.value & 0x80 == 0x80,
                                        "1": cmd.value & 0x40 == 0x40,
                                        "2": cmd.value & 0x20 == 0x20,
                                        "3": cmd.value & 0x10 == 0x10,
                                    }

                                instruments[idx].metadata["all_uses"].append(
                                    {
                                        "at_command": c,
                                        "at_sample": i,
                                        "key_on_ops": key_on_ops,
                                    }
                                )

                i += result.advance
                c += 1

    print(f"Found {len(instruments)} unique used FM instruments")

    try:
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise IOError(f"Unable to create FM instrument output folder: {e}")

    i: int = -1
    for inst in instruments:
        i += 1
        with open(os.path.join(out_dir, f"INST{i}.json"), "w", encoding="utf-8") as f:
            json.dump(inst.serialize(), f, indent="\t")

    print(f"Saved all FM instruments as JSON files to {out_dir} :3")


def dump_midi_notes(vgm: VGM, out_file: str) -> None:
    ym: YM2612 = YM2612(vgm.get_clock_rate(Chip.YM2612))

    instruments: list[YM2612Instrument] = []
    ym_note_events: list[dict[str, Any]] = []
    i: int = 0
    for cmd in vgm.commands:
        if type(cmd) is WriteCommand:
            # TODO: Handle Chip.SEGA_PSG writes
            if cmd.chip == Chip.YM2612:
                ym_result: YM2612State = ym.handle_write_command(cmd)

                for j in range(len(ym_result.notes)):
                    if ym_result.notes[j] != "n":
                        cur_inst: YM2612Instrument = YM2612Instrument.from_channel(
                            ym.channels[j], ym.lfo_freq
                        )

                        k: int = -1
                        for inst2 in instruments:
                            k += 1
                            if YM2612Instrument.compare(cur_inst, inst2):
                                break

                        if k == -1:
                            instruments.append(cur_inst)
                            k = len(instruments) - 1

                        ym_note_events.append(
                            {
                                "type": "down" if ym_result.notes[j] == "d" else "up",
                                "at": i,
                                "channel": j,
                                "instrutment": k,
                                "frequency": ym.channels[j].frequency,
                            }
                        )

                i += ym_result.advance
        elif type(cmd) is WaitCommand:
            i += cmd.wait_time

    for note in ym_note_events:
        pass


def main():
    argparser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="mdfmvgmrip.py",
        description="Sega MegaDrive/Genesis FM Instrument (and more) .VGM Ripper",
    )
    argparser.add_argument("filename", help="Path to MegaDrive/Genesis .VGM/.VGZ file")
    argparser.add_argument(
        "--fm-inst-out", help="Name of folder to save FM instument data to"
    )
    argparser.add_argument("--midi-out", help="Name of file to save MIDI note data to")
    argparser.add_argument(
        "--data-out", help="Name of folder to save data block info to (usually samples)"
    )
    argparser.add_argument("--debug", action="store_true", help="Enable debug stuff")

    args: argparse.Namespace = argparser.parse_args()

    if not args.data_out and not args.midi_out and not args.fm_inst_out:
        argparser.error('No outputs specified: run "mdfmvgmrip.py -h" for help')

    file_data: bytes = b""
    try:
        with open(args.filename, "rb") as f:
            file_data = f.read()
    except FileNotFoundError:
        argparser.error(f'File "{args.filename}" not found')
    except Exception as e:
        argparser.error(f'Error opening/reading file "{args.filename}": {e}')

    if args.filename.split(".")[-1] == "vgz":
        file_data = gzip.decompress(file_data)

    warnings.simplefilter("always")

    try:
        vgm: VGM = VGM.from_data(file_data)

        if not vgm.is_a_genesis_vgm():
            raise VGMError("Not a Sega Genesis/MegaDrive .VGM")

        # TODO: GD3 tag stuff
        print(f"Read {len(vgm.commands)} commands from .VGM file")

        if args.data_out:
            try:
                print(f"Found {len(vgm.dblock_sections)} data blocks")
                dump_datablocks(vgm.dblock_data, vgm.dblock_sections, args.data_out)
            except KeyError:
                print(".VGM file doesn't contain any dumpable data blocks")
            except Exception as e:
                argparser.error(
                    f"Could not save data blocks: {e.__class__.__name__}: {e}"
                )

        if args.fm_inst_out:
            dump_fm_instruments(vgm, args.fm_inst_out)

        if args.midi_out:
            dump_midi_notes(vgm, args.midi_out)
    except VGMError as e:
        argparser.error(f"Error parsing VGM file: {e.info}")
    except YM2612Error as e:
        argparser.error(f"YM2612 error occured: {e.info}")
    except IOError as e:
        argparser.error(f"Unable to create file/folder: {e}")


if __name__ == "__main__":
    main()
