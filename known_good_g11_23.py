#!/usr/bin/env python3
"""
known_good_g11_23.py - Extract all 23 G11 figure illustrations from sffastus.

Parses 89-byte FIG illustration page records, extracts raw G4 data at each
ptr3 offset, wraps in TIFF, decodes via Wand (ImageMagick), saves as PNG.

89-byte record layout (relevant fields):
  [0:6]   model code ("G11   ")
  [6:9]   figure code ("001", "002", etc.)
  [11:13]  page index ("01", "02", etc.)
  [13:53]  label/description
  [69:73]  ptr3: 4-byte figure data pointer
           byte 0 = 0x2A (marker)
           bytes 1-3 = position in 8-byte units:
             position = (byte1 - 0x1A) * 19200 + byte2 * 256 + byte3
             file_offset = G11_BASE + position * 8
  [85:87]  s2: 2-byte big-endian compressed data size (bytes)

ptr3 encoding:
  - Byte 0 (0x2A) is a constant marker for G11
  - Byte 1 increments when byte2:byte3 would overflow (sections):
    0x1A -> 0x1B -> 0x1C
  - Each byte1 section covers 19200 * 8 = 153,600 bytes of image data
  - 19200 = 75 * 256 (same factor 75 used in section-level block pointers)
  - Figure data is packed contiguously, each aligned to 8-byte boundaries

All figures are 1280x640 CCITT Group 4 with T.6 uncompressed mode extensions.

Requires: wand (pip install wand), ImageMagick

Usage: .venv/bin/python known_good_g11_23.py
"""

import struct
from pathlib import Path
from wand.image import Image as WandImage

SFFASTUS = Path(__file__).parent / "SFCDUS2" / "sffastus"
OUTPUT_DIR = Path(__file__).parent / "g11_figures"
RECORDS_OFFSET = 0x1725E800  # G11 89-byte records start
G11_BASE = 0x1745D000        # base for G11 figure data pointers
G11_REF_BYTE1 = 0x1A         # reference byte1 value for G11
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 640
RECORD_SIZE = 89


def make_g4_tiff(raw_data, width, height):
    """Build minimal TIFF container around raw G4 data."""
    ifd_offset = 8 + len(raw_data)
    header = struct.pack('<2sHI', b'II', 42, ifd_offset)
    strip_offset = 8
    strip_size = len(raw_data)
    entries = [
        (256, 3, 1, width),
        (257, 3, 1, height),
        (258, 3, 1, 1),
        (259, 3, 1, 4),
        (262, 3, 1, 0),
        (273, 4, 1, strip_offset),
        (278, 3, 1, height),
        (279, 4, 1, strip_size),
        (292, 4, 1, 0),
    ]
    ifd = struct.pack('<H', len(entries))
    for tag, typ, count, val in entries:
        ifd += struct.pack('<HHII', tag, typ, count, val)
    ifd += struct.pack('<I', 0)
    return header + raw_data + ifd


def decode_fig_ptr(ptr3_bytes):
    """Decode 4-byte figure data pointer to file offset.

    Format: [0x2A] [byte1] [byte2] [byte3]
    position = (byte1 - ref) * 19200 + byte2 * 256 + byte3
    offset = base + position * 8

    19200 = 75 * 256 (same factor 75 as section-level block pointers).
    """
    byte1, byte2, byte3 = ptr3_bytes[1], ptr3_bytes[2], ptr3_bytes[3]
    position = (byte1 - G11_REF_BYTE1) * 19200 + byte2 * 256 + byte3
    return G11_BASE + position * 8


def parse_g11_records(f):
    """Parse all G11 89-byte records from the known offset."""
    records = []
    f.seek(RECORDS_OFFSET)

    while True:
        data = f.read(RECORD_SIZE)
        if len(data) < RECORD_SIZE:
            break

        model = data[0:6].decode('cp437', errors='replace').strip()
        if not model:
            break

        if not all(c.isalnum() or c == ' ' for c in model):
            break

        if model != "G11":
            break

        fig = data[6:9].decode('cp437', errors='replace').strip()
        page = data[11:13].decode('cp437', errors='replace').strip()
        label = data[13:53].decode('cp437', errors='replace').strip()

        ptr3_offset = decode_fig_ptr(data[69:73])

        s2 = (data[85] << 8) | data[86]

        records.append({
            'fig': fig,
            'page': page,
            'label': label,
            'offset': ptr3_offset,
            's2': s2,
        })

    return records


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    with open(SFFASTUS, "rb") as f:
        records = parse_g11_records(f)
        print(f"Found {len(records)} G11 figure records")

        ok = 0
        fail = 0
        for i, rec in enumerate(records):
            fig = rec['fig']
            page = rec['page']
            label = rec['label']
            offset = rec['offset']
            size = rec['s2']

            if size == 0 or offset == 0:
                print(f"  {fig}/{page}: skip (offset=0x{offset:08X} s2={size})")
                continue

            f.seek(offset)
            raw_data = f.read(size)

            tiff_data = make_g4_tiff(raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)
            filename = f"fig{fig}_{page}.png"
            out_path = OUTPUT_DIR / filename

            try:
                with WandImage(blob=tiff_data, format='tiff') as img:
                    img.save(filename=str(out_path))
                print(f"  {fig}/{page}: 0x{offset:08X} ({size:6d} bytes) -> {filename}  {label}")
                ok += 1
            except Exception as e:
                print(f"  {fig}/{page}: 0x{offset:08X} ({size:6d} bytes) FAILED: {e}")
                fail += 1

    print(f"\nDone: {ok} extracted, {fail} failed, {len(records)} total")
    print(f"Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
