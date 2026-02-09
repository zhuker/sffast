#!/usr/bin/env python3
"""
known_good_figures.py - Extract verified figure images from sffastus.

Extracts CCITT Group 4 compressed monochrome images from the binary data
regions of the sffastus file. Image dimensions and offsets determined by
iterative reverse engineering and visual verification against the running
Subaru FAST 2 application.

Usage: python3 known_good_figures.py
"""

import struct
import io
from pathlib import Path
from PIL import Image

SFFASTUS = Path(__file__).parent / "SFCDUS2" / "sffastus"
OUTPUT_DIR = Path(__file__).parent / "known_good"

# G11 binary region start in sffastus
G11_REGION_START = 0x1745F800

# Verified image parameters
IMAGE_WIDTH = 1280   # pixels
IMAGE_HEIGHT = 640   # pixels (all figures use this height)


def make_g4_tiff(raw_data, width, height):
    """Build a minimal TIFF file wrapping raw CCITT Group 4 compressed data.

    The raw G4 bitstream is placed as a single strip in the TIFF container.
    The TIFF IFD is placed after the image data.
    """
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


def extract_g11_index_table():
    """Extract the G11 illustration index table from region start.

    The index table is stored as raw CCITT G4 data starting at the G11
    binary region start (0x1745F800). It occupies approximately 35 blocks
    (71,680 bytes) and decodes to a 1280 x 640 pixel monochrome image
    showing figure group names and page ranges.
    """
    f = open(SFFASTUS, "rb")
    f.seek(G11_REGION_START)
    raw_data = f.read(35 * 2048)  # 35 blocks = 71,680 bytes
    f.close()

    tiff_data = make_g4_tiff(raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)
    img = Image.open(io.BytesIO(tiff_data))
    img.load()

    return img


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Extracting G11 illustration index table...")
    img = extract_g11_index_table()
    outpath = OUTPUT_DIR / "g11_index_table.png"
    img.save(outpath)
    print(f"  Saved {img.size[0]}x{img.size[1]} -> {outpath}")

    print("\nDone.")


if __name__ == "__main__":
    main()
