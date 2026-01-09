import gzip
import argparse
from typing import Any
import warnings
import os
import pathlib
import sys
import json

from vgm import VGM, VGMError
from ym2612 import YM2612, YM2612Error, YM2612Instrument


DEBUG: bool = "--debug" in sys.argv


def dump_datablocks(data: dict, out_dir: str) -> None:
    try:
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise IOError(f"Unable to create FM instrument output folder: {e}")

    sections: list[bytes] = []

    for section in data[0x00]["sections"]:
        sections.append(data[0x00]["data"][section["start"] : section["end"]])

    i = 0
    for section in sections:
        with open(os.path.join(out_dir, f"DATABLK{i}.bin"), "wb") as f:
            f.write(section)

    print(f"Saved all data blocks to {out_dir} :3")


def dump_fm_instruments(commands: list[dict[str, Any]], out_dir: str) -> None:
    ym: YM2612 = YM2612()

    NO_CHANGE: list[str] = ["n" for _ in range(6)]

    instruments: list[YM2612Instrument] = []
    i: int = 0
    c: int = 0
    for cmd in commands:
        if cmd["cmd"] == "ym_write":
            result: dict[str, Any] = ym.handle_write_command(cmd)

            if result["notes"] != NO_CHANGE:
                if DEBUG:
                    print(result["notes"])
                for channel in range(6):
                    if result["notes"][channel] == "d":
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

                            if cmd["cmd"] == "ym_write":
                                if cmd["reg"] == 0x28:
                                    key_on_ops = {
                                        "0": cmd["val"] & 0x80 == 0x80,
                                        "1": cmd["val"] & 0x40 == 0x40,
                                        "2": cmd["val"] & 0x20 == 0x20,
                                        "3": cmd["val"] & 0x10 == 0x10,
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

                            if cmd["cmd"] == "ym_write":
                                if cmd["reg"] == 0x28:
                                    key_on_ops = {
                                        "0": cmd["val"] & 0x80 == 0x80,
                                        "1": cmd["val"] & 0x40 == 0x40,
                                        "2": cmd["val"] & 0x20 == 0x20,
                                        "3": cmd["val"] & 0x10 == 0x10,
                                    }

                            instruments[idx].metadata["all_uses"].append(
                                {
                                    "at_command": c,
                                    "at_sample": i,
                                    "key_on_ops": key_on_ops,
                                }
                            )

            i += result["advance"]
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
    argparser.add_argument(
        "--dump-commands",
        action="store_true",
        help="Save all commands to a .TXT file (debug)",
    )
    argparser.add_argument("--debug", action="store_true", help="Enable debug prints")

    args: argparse.Namespace = argparser.parse_args()
    # TODO: Check that at least 1 output is specified before reading .VGM

    file_data: bytes = b""
    try:
        with open(args.filename, "rb") as f:
            file_data = f.read()
    except FileNotFoundError:
        argparser.error(f'File "{args.filename}" not found')
        exit(1)
    except Exception as e:
        argparser.error(f'Error opening/reading file "{args.filename}": {e}')
        exit(1)

    if args.filename.split(".")[-1] == "vgz":
        file_data = gzip.decompress(file_data)

    warnings.simplefilter("always")

    try:
        vgm: VGM = VGM.from_data(
            file_data,
            dump_cmds_to=(
                (args.filename + "-writes.txt") if args.dump_commands else None
            ),
        )

        # TODO: GD3 tag stuff
        print(f"Read {len(vgm.commands)} commands from .VGM file")

        if args.data_out:
            try:
                print(f"Found {len(vgm.data[0x00]["sections"])} dumpable data blocks")
                dump_datablocks(vgm.data, args.data_out)
            except KeyError:
                print(".VGM file doesn't contain any dumpable data blocks")
            except Exception as e:
                argparser.error(
                    f"Could not save data blocks: {e.__class__.__name__}: {e}"
                )
                exit(1)

        if args.fm_inst_out:
            dump_fm_instruments(vgm.commands, args.fm_inst_out)
    except VGMError as e:
        argparser.error(f"Error parsing VGM file: {e.info}")
        exit(1)
    except YM2612Error as e:
        argparser.error(f"YM2612 error occured: {e.info}")
        exit(1)
    except IOError as e:
        argparser.error(f"Unable to create file/folder: {e}")


if __name__ == "__main__":
    main()
