#!/usr/bin/env python3
"""
figure_parts_map.py - Extract figure image, find applicable parts, draw callout boxes.

1. Looks up VIN -> model spec -> vehicle codes
2. Extracts CCITT G4 figure image as PNG
3. Loads applicable parts (CatalogApplicabilityRecord466) filtered by VIN spec
4. Loads callout coordinates from PartGroupRecord185 (main parts) and InventoryRecord199 (fasteners)
5. Prints part-to-coordinate map
6. Draws bounding boxes around callouts on the figure image

Uses ModelIndexRecord288 block pointers for direct seeks instead of scanning all blocks.

Usage: .venv/bin/python figure_parts_map.py [FIG] [PAGE] [VIN]
       .venv/bin/python figure_parts_map.py 940 01
       .venv/bin/python figure_parts_map.py 940 01 JF1GD70655L510047
"""

import math
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from wand.image import Image as WandImage

from sffastus_parser import (
    CatalogApplicabilityRecord466,
    FIGIllustrationPage89,
    FigureIndexRecord22,
    InventoryRecord199,
    PartGroupRecord185,
    is_valid_subaru_vin,
    iter_model_blocks,
)

from parsers_common import (
    SFCDUS2_PATH,
    create_parser,
    get_vehicle_by_vin,
    filter_cat466_parts,
)

IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 640


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
        # --- VIN resolution ---
        print("Resolving VIN...")
        try:
            vehicle = get_vehicle_by_vin(f, parser, vin)
        except LookupError as e:
            print(str(e))
            sys.exit(1)

        model_code = vehicle.vin_rec.model_code
        model_rec = vehicle.model_rec
        print(f"  Model: {model_code}  Body: {vehicle.vin_rec.body_model}  Date: {vehicle.vehicle_date}")
        if vehicle.spec:
            spec = vehicle.spec
            print(f"  Spec: {spec.body_config}/{spec.engine}/{spec.transmission}/{spec.trim_level}")
            print(f"  Codes: {sorted(vehicle.codes)}")
        else:
            print("  Warning: no model spec found")
        print()

        # --- Find FIG89 record for target figure (direct seek) ---
        print("Finding figure image...")
        fig89_rec = None
        for bo in iter_model_blocks(model_rec, FIGIllustrationPage89.ID):
            recs = parser.parse_fig_illustration_page_records_89(f, bo)
            for r in recs:
                if r.fig_index == fig_target and r.page_index == page_target:
                    fig89_rec = r
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

        # --- Load applicable parts (466-byte) for this figure (direct seek) ---
        print("\nLoading parts...")
        model_parts = []
        for bo in iter_model_blocks(model_rec, CatalogApplicabilityRecord466.ID):
            model_parts.extend(parser.parse_catalog_applicability_records_466(f, bo))

        # Filter by VIN spec and date
        filtered = filter_cat466_parts(model_parts, vehicle)

        # Filter by target figure and page
        fig_parts = []
        for rec, variant in filtered:
            if rec.figure_ref and len(rec.figure_ref) >= 4:
                ref_fig = rec.figure_ref[1:]
            else:
                continue
            if ref_fig != fig_target:
                continue
            rec_page = rec.figure_page.strip()
            if rec_page and rec_page != page_target:
                continue
            fig_parts.append((rec, variant))

        # Dedup by (group_category, part_id)
        seen = set()
        unique_parts = []
        for rec, variant in fig_parts:
            key = (rec.callout_code, rec.part_id)
            if key not in seen:
                seen.add(key)
                unique_parts.append((rec, variant))
        unique_parts.sort(key=lambda x: x[0].callout_code)

        print(f"  Applicable parts for fig {fig_target}-{page_target}: {len(unique_parts)}")

        # --- Load callout coordinates (direct seek) ---
        # Source 1: PartGroupRecord185 (main part callouts with x,y)
        print("\nLoading callout coordinates...")
        coord_list = []  # [(code, x, y, description, part_number_or_None), ...]

        for bo in iter_model_blocks(model_rec, PartGroupRecord185.ID):
            recs = parser.parse_part_group_records_185(f, bo)
            for r in recs:
                if r.figure.strip() == fig_target and r.figure_page.strip() == page_target:
                    code = r.part_code.strip()
                    if code and r.x > 0 and r.y > 0:
                        coord_list.append((code, r.x, r.y, r.desc_en, None))

        pg_count_coords = len(coord_list)

        # Source 2: InventoryRecord199 (fastener/hardware callouts with x,y)
        for bo in iter_model_blocks(model_rec, InventoryRecord199.ID):
            recs = parser.parse_inventory_records_199(f, bo)
            for r in recs:
                if r.figure.strip() == fig_target and r.figure_page.strip() == page_target:
                    code = r.part_code.strip()
                    if code and r.x > 0 and r.y > 0:
                        coord_list.append((code, r.x, r.y, r.name_en, r.part_number.strip() or None))

        inv_count_coords = len(coord_list) - pg_count_coords
        print(f"  PartGroup185 callouts: {pg_count_coords}")
        print(f"  Inventory199 callouts: {inv_count_coords}")
        print(f"  Total callouts with coordinates: {len(coord_list)}")

        # --- Build part number lookup from Cat466 (callout -> part_id) ---
        part_lookup = {}  # callout_code -> (part_id, variant)
        for rec, variant in unique_parts:
            callout = rec.callout_code.strip()
            if callout not in part_lookup:
                part_lookup[callout] = (rec.part_id, variant)

        # --- Print parts map ---
        print()
        print("=" * 110)
        print(f"PARTS MAP: FIG {fig_target}-{page_target}  VIN {vin}  ({model_code})")
        print("=" * 110)
        print(f"{'Callout':<10} {'Part Number':<16} {'Px X':>5} {'Px Y':>5}  Description")
        print("-" * 110)

        all_callouts = []  # (px_x, px_y, callout, desc, matched)
        for code, cx, cy, desc, inv_part in sorted(coord_list, key=lambda t: (t[0], t[2])):
            px_x = math.floor(cx / 2)
            px_y = math.floor(cy / 2)
            part_info = part_lookup.get(code)
            if part_info:
                part_id, variant = part_info
                v_str = f"*{variant}" if variant else ""
                print(f"{code:<10}{v_str:3s}{part_id:<16} {px_x:5d} {px_y:5d}  {desc}")
                matched = True
            elif inv_part:
                # Inventory199 has part number directly (fasteners not in Cat466 for this figure)
                print(f"{code:<10}   {inv_part:<16} {px_x:5d} {px_y:5d}  {desc}")
                matched = True
            else:
                print(f"{code:<10}   {'--':16s} {px_x:5d} {px_y:5d}  {desc}")
                matched = False
            all_callouts.append((px_x, px_y, code, desc, matched))

        matched = sum(1 for _, _, _, _, m in all_callouts if m)
        print()
        print(f"Callouts on figure: {len(all_callouts)}  (matched to VIN: {matched}, other: {len(all_callouts) - matched})")

        # --- Load figure cross-references (direct seek) ---
        fig_xrefs = []
        for bo in iter_model_blocks(model_rec, FigureIndexRecord22.ID):
            recs = parser.parse_figure_index_records_22(f, bo)
            for r in recs:
                if r.figure.strip() == fig_target and r.page.strip() == page_target:
                    if r.x > 0 and r.y > 0:
                        fig_xrefs.append(r)

        if fig_xrefs:
            print()
            print(f"Figure cross-references: {len(fig_xrefs)}")
            for r in fig_xrefs:
                px_x = math.floor(r.x / 2)
                px_y = math.floor(r.y / 2)
                print(f"  -> FIG {r.ref_figure.strip()}  px=({px_x},{px_y})")

        # --- Draw bounding boxes ---
        print(f"\nDrawing callout boxes...")
        img = Image.open(base_png).convert('RGB')
        draw = ImageDraw.Draw(img)

        BOX_W, BOX_H = 100, 14  # half-widths for the rectangle

        for px_x, px_y, callout, desc, matched in all_callouts:
            x0 = px_x
            y0 = px_y - 2
            x1 = px_x-2+BOX_W
            y1 = px_y-2+BOX_H

            # Red = applicable to VIN, blue = on figure but filtered out
            color = 'red' if matched else 'blue'
            draw.rectangle([x0, y0, x1, y1], outline=color, width=1)
            draw.text((x0 + 2, y1 + 1), callout, fill=color)

        # Green = figure cross-references
        for r in fig_xrefs:
            px_x = math.floor(r.x / 2)
            px_y = math.floor(r.y / 2)
            x0 = px_x
            y0 = px_y - 2
            x1 = px_x - 2 + BOX_W
            y1 = px_y - 2 + BOX_H
            label = f"-> FIG {r.ref_figure.strip()}"
            draw.rectangle([x0, y0, x1, y1], outline='green', width=1)
            draw.text((x0 + 2, y1 + 1), label, fill='green')

        out_path = Path(f"output/fig{fig_target}_{page_target}_annotated.png")
        img.save(out_path)
        print(f"Saved annotated image: {out_path}")


if __name__ == "__main__":
    main()
