#!/usr/bin/env python3
"""
extract_g11_from_parser.py - Extract G11 figure illustrations using the parser.

1. Creates parser (with figure codes + ITCA catalog)
2. Scans all blocks to find block types
3. Finds FIGIllustrationPage89 blocks
4. Filters for G11 figures only
5. Decodes ptr3 to file offsets, extracts raw G4 data, saves as PNG

Usage: .venv/bin/python extract_g11_from_parser.py
"""

import struct
import sys
from pathlib import Path

from wand.image import Image as WandImage

from sffastus_parser import (
    SffastusBlockParser,
    parse_figname_txt,
    parse_itca_data,
    ItcaPartsCatalog,
)

SFCDUS2_PATH = Path("SFCDUS2/sffastus")
FIGNAME_PATH = "SFCDUS2/sffastpg/win/figname.txt"
ITCA_DATA = ["SFCDUS1/ITCA_DATA.TXT", "SFCDUS2/itca_data.txt", "SFCDUS3/itca_data.txt"]
OUTPUT_DIR = Path("g11_figures_parsed")

# G11-specific constants for ptr3 decoding
G11_BASE = 0x1745D000
G11_REF_BYTE1 = 0x1A

IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 640


def create_parser():
    """Create parser with figure codes and ITCA catalog."""
    figure_codes = set()
    if Path(FIGNAME_PATH).exists():
        figure_codes = {r.figure_code for r in parse_figname_txt(FIGNAME_PATH)}

    itca_records = []
    for itca_path in ITCA_DATA:
        if Path(itca_path).exists():
            itca_records.extend(parse_itca_data(itca_path))
    parts_catalog = ItcaPartsCatalog(itca_records)

    return SffastusBlockParser(figure_codes=figure_codes, parts_catalog=parts_catalog)


def decode_fig_ptr(ptr3_bytes):
    """Decode 4-byte figure data pointer to file offset.

    Format: [marker] [byte1] [byte2] [byte3]
    position = (byte1 - ref) * 19200 + byte2 * 256 + byte3
    offset = base + position * 8
    """
    byte1, byte2, byte3 = ptr3_bytes[1], ptr3_bytes[2], ptr3_bytes[3]
    position = (byte1 - G11_REF_BYTE1) * 19200 + byte2 * 256 + byte3
    return G11_BASE + position * 8


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


def main():
    # 1. Create parser
    print("Creating parser...")
    parser = create_parser()
    print(f"  Figure codes: {len(parser.figure_codes)}")

    # 2. Scan all block types
    print("Scanning all blocks (this takes a while)...")
    with open(SFCDUS2_PATH, 'rb') as f:
        ranges = parser.scan_block_types(f)
        print(f"  Found {len(ranges)} block ranges")

        # 3. Find FIGIllustrationPage89 blocks
        fig89_ranges = [r for r in ranges if r[3] == 'fig_illustration_page_89']
        total_blocks = sum(r[2] for r in fig89_ranges)
        print(f"  FIG illustration page 89 blocks: {len(fig89_ranges)} ranges, {total_blocks} blocks")

        # 4. Parse all 89-byte records block-by-block, filter for G11
        BLOCK_SIZE = 2048
        all_records = []
        for r_start, r_end, num_blocks, block_type in fig89_ranges:
            for block_idx in range(num_blocks):
                block_offset = r_start + block_idx * BLOCK_SIZE
                records = parser.parse_fig_illustration_page_records_89(f, block_offset)
                all_records.extend(records)

        print(f"  Total FIG89 records: {len(all_records)}")

        # Group by model
        models = {}
        for rec in all_records:
            models.setdefault(rec.model_code, []).append(rec)

        print(f"  Models: {', '.join(f'{m}({len(recs)})' for m, recs in sorted(models.items()))}")

        g11_records = models.get('G11', [])
        print(f"\n  G11 records: {len(g11_records)}")

        if not g11_records:
            print("No G11 records found!")
            sys.exit(1)

        # 5. Extract images
        OUTPUT_DIR.mkdir(exist_ok=True)
        ok = 0
        fail = 0

        for rec in g11_records:
            fig_offset = decode_fig_ptr(rec.ptr3)
            size = rec.image_size

            if size == 0 or fig_offset == 0:
                print(f"  {rec.fig_index}/{rec.page_index}: skip (offset=0x{fig_offset:08X} size={size})")
                continue

            f.seek(fig_offset)
            raw_data = f.read(size)

            tiff_data = make_g4_tiff(raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)
            filename = f"fig{rec.fig_index}_{rec.page_index}.png"
            out_path = OUTPUT_DIR / filename

            try:
                with WandImage(blob=tiff_data, format='tiff') as img:
                    img.save(filename=str(out_path))
                print(f"  {rec.fig_index}/{rec.page_index}: 0x{fig_offset:08X} ({size:6d} bytes) -> {filename}  {rec.label}")
                ok += 1
            except Exception as e:
                print(f"  {rec.fig_index}/{rec.page_index}: 0x{fig_offset:08X} ({size:6d} bytes) FAILED: {e}")
                fail += 1

    print(f"\nDone: {ok} extracted, {fail} failed, {len(g11_records)} total")
    print(f"Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
