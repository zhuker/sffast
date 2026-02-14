#!/usr/bin/env python3
"""
figure_parts_map.py - Extract figure image, find applicable parts, draw callout boxes.

1. Looks up VIN -> model spec -> vehicle codes
2. Extracts CCITT G4 figure image as PNG
3. Loads applicable parts (CatalogApplicabilityRecord466) filtered by VIN spec
4. Loads callout coordinates from PartGroupRecord185 (main parts) and InventoryRecord199 (fasteners)
5. Prints part-to-coordinate map
6. Draws bounding boxes around callouts on the figure image

Usage: .venv/bin/python figure_parts_map.py [FIG] [PAGE] [VIN]
       .venv/bin/python figure_parts_map.py 940 01
       .venv/bin/python figure_parts_map.py 940 01 JF1GD70655L510047
"""

import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from wand.image import Image as WandImage

from sffastus_parser import (
    SffastusBlockParser,
    InventoryRecord199,
    PartGroupRecord185,
    FIGIllustrationPage89,
    parse_figname_txt,
    parse_itca_data,
    ItcaPartsCatalog,
    is_valid_subaru_vin,
)

from vin_figures import (
    lookup_vin,
    find_model_spec,
    get_vehicle_codes,
    eval_spec_logic,
    date_in_range,
)

SFCDUS2_PATH = Path("SFCDUS2/sffastus")
FIGNAME_PATH = "SFCDUS2/sffastpg/win/figname.txt"
ITCA_DATA = ["SFCDUS1/ITCA_DATA.TXT", "SFCDUS2/itca_data.txt", "SFCDUS3/itca_data.txt"]
BLOCK_SIZE = 2048
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 640


def create_parser():
    figure_codes = set()
    if Path(FIGNAME_PATH).exists():
        figure_codes = {r.figure_code for r in parse_figname_txt(FIGNAME_PATH)}
    itca_records = []
    for itca_path in ITCA_DATA:
        if Path(itca_path).exists():
            itca_records.extend(parse_itca_data(itca_path))
    parts_catalog = ItcaPartsCatalog(itca_records)
    return SffastusBlockParser(figure_codes=figure_codes, parts_catalog=parts_catalog)


def make_g4_tiff(raw_data, width, height):
    ifd_offset = 8 + len(raw_data)
    header = struct.pack('<2sHI', b'II', 42, ifd_offset)
    entries = [
        (256, 3, 1, width),
        (257, 3, 1, height),
        (258, 3, 1, 1),
        (259, 3, 1, 4),
        (262, 3, 1, 0),
        (273, 4, 1, 8),
        (278, 3, 1, height),
        (279, 4, 1, len(raw_data)),
        (292, 4, 1, 0),
    ]
    ifd = struct.pack('<H', len(entries))
    for tag, typ, count, val in entries:
        ifd += struct.pack('<HHII', tag, typ, count, val)
    ifd += struct.pack('<I', 0)
    return header + raw_data + ifd


def extract_figure_png(f, fig89_rec):
    fig_offset = fig89_rec.get_figure_offset()
    size = fig89_rec.image_size
    if size == 0 or fig_offset == 0:
        return None
    f.seek(fig_offset)
    raw_data = f.read(size)
    tiff_data = make_g4_tiff(raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)
    with WandImage(blob=tiff_data, format='tiff') as img:
        png_blob = img.make_blob('png')
    return png_blob


def main():
    fig_target = sys.argv[1] if len(sys.argv) > 1 else "940"
    page_target = sys.argv[2] if len(sys.argv) > 2 else "01"
    vin = sys.argv[3] if len(sys.argv) > 3 else "JF1GD70655L510047"

    fig_target = fig_target.zfill(3)
    page_target = page_target.zfill(2)

    if not is_valid_subaru_vin(vin):
        print(f"Error: '{vin}' is not a valid Subaru VIN")
        sys.exit(1)

    print(f"Figure: {fig_target}-{page_target}")
    print(f"VIN:    {vin}")
    print()

    parser = create_parser()

    with open(SFCDUS2_PATH, 'rb') as f:
        # --- VIN lookup ---
        print("Looking up VIN...")
        vin_rec = lookup_vin(f, parser, vin)
        if not vin_rec:
            print(f"VIN {vin} not found")
            sys.exit(1)

        model_code = vin_rec.model_code
        vehicle_date = vin_rec.date1[:6]
        print(f"  Model: {model_code}  Body: {vin_rec.body_model}  Date: {vehicle_date}")

        # --- Scan block types ---
        print("Scanning blocks...")
        ranges = parser.scan_block_types(f)

        # --- Model spec ---
        spec = find_model_spec(f, parser, ranges, model_code, vin_rec.body_model)
        if spec:
            codes = get_vehicle_codes(spec)
            print(f"  Spec: {spec.body_config}/{spec.engine}/{spec.transmission}/{spec.trim_level}")
            print(f"  Codes: {sorted(codes)}")
        else:
            codes = set()
            print("  Warning: no model spec found")
        print()

        # --- Find FIG89 record for target figure ---
        print("Finding figure image...")
        fig89_ranges = [r for r in ranges if r[3] == 'fig_illustration_page_89']
        fig89_rec = None
        for rs, re_, rc, rt in fig89_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_fig_illustration_page_records_89(f, bo)
                for r in recs:
                    if r.model_code == model_code and r.fig_index == fig_target and r.page_index == page_target:
                        fig89_rec = r
                        break
                if fig89_rec:
                    break
            if fig89_rec:
                break

        if not fig89_rec:
            print(f"  Figure {fig_target}-{page_target} not found for {model_code}")
            sys.exit(1)

        print(f"  Found: offset=0x{fig89_rec.get_figure_offset():08X} size={fig89_rec.image_size}")

        # Extract PNG
        png_blob = extract_figure_png(f, fig89_rec)
        if not png_blob:
            print("  Failed to extract image")
            sys.exit(1)

        base_png = Path(f"output/fig{fig_target}_{page_target}_base.png")
        base_png.parent.mkdir(exist_ok=True)
        base_png.write_bytes(png_blob)
        print(f"  Saved base image: {base_png}")

        # --- Load applicable parts (466-byte) for this figure ---
        print("\nLoading parts...")
        cat_ranges = [r for r in ranges if r[3] == 'catalog_applicability_466']
        fig_parts = []
        for rs, re_, rc, rt in cat_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_catalog_applicability_records_466(f, bo)
                for rec in recs:
                    if rec.model_code != model_code:
                        continue
                    # Match figure_ref (e.g., "A940") -> figure "940"
                    if rec.figure_ref and len(rec.figure_ref) >= 4:
                        ref_fig = rec.figure_ref[1:]
                    else:
                        continue
                    if ref_fig != fig_target:
                        continue
                    # Match page (empty = all pages)
                    rec_page = rec.figure_page.strip()
                    if rec_page and rec_page != page_target:
                        continue
                    # Filter by spec logic
                    sl = rec.spec_logic
                    matched = eval_spec_logic(sl, codes)
                    variant = ''
                    if not matched and len(sl) >= 2 and sl[0] in 'ABCDEFGH':
                        if eval_spec_logic(sl[1:], codes):
                            matched = True
                            variant = sl[0]
                    if not matched:
                        continue
                    # Filter by date
                    start_date = rec.date[:6] if len(rec.date) >= 6 else ''
                    end_date = rec.date[8:14] if len(rec.date) >= 14 else ''
                    if not date_in_range(vehicle_date, start_date, end_date):
                        continue
                    fig_parts.append((rec, variant))

        # Dedup by (group_category, part_id)
        seen = set()
        unique_parts = []
        for rec, variant in fig_parts:
            key = (rec.group_category, rec.part_id)
            if key not in seen:
                seen.add(key)
                unique_parts.append((rec, variant))
        unique_parts.sort(key=lambda x: x[0].group_category)

        print(f"  Applicable parts for fig {fig_target}-{page_target}: {len(unique_parts)}")

        # --- Load callout coordinates ---
        # Source 1: PartGroupRecord185 (main part callouts with x,y)
        print("\nLoading callout coordinates...")
        coord_lookup = {}  # part_code -> (x, y, description)

        pg_ranges = [r for r in ranges if r[3] == PartGroupRecord185.ID]
        for rs, re_, rc, rt in pg_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_part_group_records_185(f, bo)
                for r in recs:
                    if r.model_code == model_code and r.figure.strip() == fig_target and r.figure_page.strip() == page_target:
                        code = r.part_code.strip()
                        if code and r.x > 0 and r.y > 0:
                            coord_lookup[code] = (r.x, r.y, r.desc_en)

        pg_count = len(coord_lookup)

        # Source 2: InventoryRecord199 (fastener/hardware callouts with x,y)
        inv_ranges = [r for r in ranges if r[3] == InventoryRecord199.ID]
        for rs, re_, rc, rt in inv_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_inventory_records_199(f, bo)
                for r in recs:
                    if r.model_code == model_code and r.figure.strip() == fig_target and r.figure_page.strip() == page_target:
                        code = r.part_code.strip()
                        if code and r.x > 0 and r.y > 0 and code not in coord_lookup:
                            coord_lookup[code] = (r.x, r.y, r.name_en)

        inv_count = len(coord_lookup) - pg_count
        print(f"  PartGroup185 callouts: {pg_count}")
        print(f"  Inventory199 callouts: {inv_count}")
        print(f"  Total callouts with coordinates: {len(coord_lookup)}")

        # --- Print part-to-coordinate map ---
        print()
        print("=" * 100)
        print(f"PARTS MAP: FIG {fig_target}-{page_target}  VIN {vin}  ({model_code})")
        print("=" * 100)
        print(f"{'Callout':<10} {'Part Number':<16} {'X':>5} {'Y':>5}  {'Px X':>5} {'Px Y':>5}  Description")
        print("-" * 100)

        callout_positions = []  # (px_x, px_y, callout_code, part_id, name)

        for rec, variant in unique_parts:
            callout = rec.group_category.strip()
            coord = coord_lookup.get(callout)

            if coord:
                cx, cy, name = coord
                # Coordinate space is 2x pixel dimensions
                px_x = cx // 2
                px_y = cy // 2
                v_str = f"*{variant}" if variant else ""
                print(f"{callout:<10}{v_str:3s}{rec.part_id:<16} {cx:5d} {cy:5d}  {px_x:5d} {px_y:5d}  {name}")
                callout_positions.append((px_x, px_y, callout, rec.part_id, name))
            else:
                v_str = f"*{variant}" if variant else ""
                print(f"{callout:<10}{v_str:3s}{rec.part_id:<16}     -     -      -     -  (no coords)")

        print()
        print(f"Total: {len(unique_parts)} parts, {len(callout_positions)} with coordinates")

        # --- Draw bounding boxes ---
        print(f"\nDrawing callout boxes...")
        img = Image.open(base_png).convert('RGB')
        draw = ImageDraw.Draw(img)

        BOX_W, BOX_H = 50, 12  # half-widths for the rectangle

        for px_x, px_y, callout, part_id, name in callout_positions:
            # Clamp to image bounds
            px_x = max(BOX_W, min(IMAGE_WIDTH - BOX_W, px_x))
            px_y = max(BOX_H, min(IMAGE_HEIGHT - BOX_H, px_y))

            x0 = px_x - BOX_W
            y0 = px_y - BOX_H
            x1 = px_x + BOX_W
            y1 = px_y + BOX_H

            draw.rectangle([x0, y0, x1, y1], outline='red', width=2)
            draw.text((x0 + 2, y1 + 1), callout, fill='red')

        out_path = Path(f"output/fig{fig_target}_{page_target}_annotated.png")
        img.save(out_path)
        print(f"Saved annotated image: {out_path}")


if __name__ == "__main__":
    main()
