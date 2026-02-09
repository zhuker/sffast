#!/usr/bin/env python3
"""
known_good_fig001.py - Extract verified fig001 illustration from sffastus.

Fig001 (figure 001, page 01) is the first figure page for the G11 (Impreza)
model group. The raw G4 data at ptr3=0x17471000 uses T.6 uncompressed mode
extensions which standard libtiff (Pillow) cannot decode. ImageMagick's
libtiff build handles it and decodes the full 1280x640 image.

Method:
  1. Read 4520 bytes of raw G4 data from sffastus at 0x17471000
  2. Wrap in minimal TIFF container (w=1280, h=640, CCITT Group 4)
  3. Decode via ImageMagick (handles T.6 uncompressed mode)

Requires: ImageMagick (magick command)

Usage: python3 known_good_fig001.py
"""

import struct
import subprocess
from pathlib import Path

SFFASTUS = Path(__file__).parent / "SFCDUS2" / "sffastus"
OUTPUT_DIR = Path(__file__).parent / "known_good"

FIG001_OFFSET = 0x17471000  # ptr3 from 89-byte record
FIG001_SIZE = 4520          # s2 from 89-byte record
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 640


def make_g4_tiff(raw_data, width, height):
    """Build a minimal TIFF file wrapping raw CCITT Group 4 compressed data."""
    ifd_offset = 8 + len(raw_data)
    header = struct.pack('<2sHI', b'II', 42, ifd_offset)
    strip_offset = 8
    strip_size = len(raw_data)
    entries = [
        (256, 3, 1, width),           # ImageWidth
        (257, 3, 1, height),          # ImageLength
        (258, 3, 1, 1),              # BitsPerSample = 1 (bilevel)
        (259, 3, 1, 4),              # Compression = CCITT Group 4
        (262, 3, 1, 0),              # PhotometricInterpretation = WhiteIsZero
        (273, 4, 1, strip_offset),   # StripOffsets
        (278, 3, 1, height),         # RowsPerStrip = all rows in one strip
        (279, 4, 1, strip_size),     # StripByteCounts
        (292, 4, 1, 0),              # Group4Options = 0
    ]
    ifd = struct.pack('<H', len(entries))
    for tag, typ, count, val in entries:
        ifd += struct.pack('<HHII', tag, typ, count, val)
    ifd += struct.pack('<I', 0)  # next IFD = 0 (single image)
    return header + raw_data + ifd


def extract_fig001():
    """Extract fig001 illustration via ImageMagick."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Read raw G4 data
    with open(SFFASTUS, "rb") as f:
        f.seek(FIG001_OFFSET)
        raw_data = f.read(FIG001_SIZE)

    # Wrap in TIFF container with correct dimensions
    tiff_data = make_g4_tiff(raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)

    # Write temporary TIFF
    tiff_path = OUTPUT_DIR / "fig001_raw.tif"
    tiff_path.write_bytes(tiff_data)

    # Decode via ImageMagick (1280x640, matching app display)
    out_path = OUTPUT_DIR / "g11_fig001.png"
    result = subprocess.run(
        ["magick", str(tiff_path), str(out_path)],
        capture_output=True, timeout=30
    )

    # Clean up temporary TIFF
    tiff_path.unlink()

    # Report
    if out_path.exists():
        identify = subprocess.run(
            ["magick", "identify", str(out_path)],
            capture_output=True, timeout=10
        )
        dims = identify.stdout.decode().strip()
        print(f"  Output: {dims}")
    if result.stderr:
        stderr = result.stderr.decode().strip()
        print(f"  Warning: {stderr.split(chr(10))[0]}")


def main():
    print("Extracting G11 fig001 illustration...")
    extract_fig001()
    print("\nDone.")


if __name__ == "__main__":
    main()
