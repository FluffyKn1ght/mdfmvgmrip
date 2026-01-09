**NOTE:** This project is still a work in progress! There are a lot of bugs and broken/unimplemented features.

# mdfmvgmrip
A collection of Python scripts for extracting data from Sega MegaDrive/Genesis VGMs

# Prerequisites
- Python **3.14.0** or later
- Either one of the following:
  - The `mido` library
  - The `pip` package manager in your `PATH`

# Usage
1. Clone the repository:
```
git clone https://github.com/fluffykn1ght/mdfmvgmrip.git
```
2. Install the required libraries (if they aren't already installed):
```
pip install -r requirements.txt
```
3. Run `mdfmvgmrip.py` (`-h` flag can be used to view help)
```
py mdfmvgmrip.py --fm-inst-out FM SickTunez.vgm
```

`vgm.py`, `segapsg.py` and `ym2612.py` are side modules that load and parse .VGM files as well as handle sound chip commands. They are *required* for the main script to work. (You *can* use them in your own projects, but they probably won't be of much help)

Other scripts include:
- `dblkpad.py`: Pads the datablock data so that it can be imported as raw uncompressed 16-bit signed PCM data in an audio editor (like Audacity)

# Features
- .VGM *and* .VGZ support
- Data block extraction (they usually contain samples)
- FM instrument extraction (into .JSON files), with usage times
- MIDI file and note data generation (WIP)
