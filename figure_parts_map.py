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

import math
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from wand.image import Image as WandImage

from sffastus_parser import (
    SffastusBlockParser,
    InventoryRecord199,
    PartGroupRecord185,
    FigureIndexRecord22,
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
        # Same callout code can appear multiple times with different coordinates
        print("\nLoading callout coordinates...")
        coord_list = []  # [(code, x, y, description), ...]
        coord_codes = set()
        callout_descs = {}  # code -> description (from PartGroup185 / Inventory199, regardless of coords)

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
                    if r.model_code == model_code and r.figure.strip() == fig_target:
                        code = r.part_code.strip()
                        if code:
                            if code not in callout_descs:
                                callout_descs[code] = r.desc_en
                            if r.figure_page.strip() == page_target and r.x > 0 and r.y > 0:
                                coord_list.append((code, r.x, r.y, r.desc_en))
                                coord_codes.add(code)

        pg_count = len(coord_list)

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
                    if r.model_code == model_code and r.figure.strip() == fig_target:
                        code = r.part_code.strip()
                        if code:
                            if code not in callout_descs:
                                callout_descs[code] = r.name_en
                            if r.figure_page.strip() == page_target and r.x > 0 and r.y > 0:
                                coord_list.append((code, r.x, r.y, r.name_en))
                                coord_codes.add(code)

        inv_count = len(coord_list) - pg_count
        print(f"  PartGroup185 callouts: {pg_count}")
        print(f"  Inventory199 callouts: {inv_count}")
        print(f"  Total callouts with coordinates: {len(coord_list)}")

        # --- Build part number lookup from Cat466 (callout -> part_id) ---
        part_lookup = {}  # callout_code -> (part_id, variant)
        for rec, variant in unique_parts:
            callout = rec.group_category.strip()
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
        for code, cx, cy, desc in sorted(coord_list, key=lambda t: (t[0], t[2])):
            px_x = math.floor(cx / 2)
            px_y = math.floor(cy / 2)
            part_info = part_lookup.get(code)
            matched = code in part_lookup
            if part_info:
                part_id, variant = part_info
                v_str = f"*{variant}" if variant else ""
                print(f"{code:<10}{v_str:3s}{part_id:<16} {px_x:5d} {px_y:5d}  {desc}")
            else:
                print(f"{code:<10}   {'--':16s} {px_x:5d} {px_y:5d}  {desc}")
            all_callouts.append((px_x, px_y, code, desc, matched))

        # Cat466 parts with no coordinates (not drawn on this figure page)
        no_coord_parts = [(rec, v) for rec, v in unique_parts if rec.group_category.strip() not in coord_codes]
        if no_coord_parts:
            print()
            print("Parts without callout on this page:")
            for rec, variant in no_coord_parts:
                v_str = f"*{variant}" if variant else ""
                # Look up part name from ITCA catalog
                desc = ""
                if parser.parts_catalog:
                    itca = parser.parts_catalog.lookup(rec.part_id)
                    if itca:
                        desc = itca[0].description
                if not desc:
                    # Fall back to PartGroup185/Inventory199 description
                    desc = callout_descs.get(rec.group_category.strip(), "")
                if not desc:
                    # Fall back to usage_notes / part_spec from the Cat466 record
                    notes = rec.usage_notes.strip()
                    spec = rec.part_spec.strip()
                    desc = notes or spec
                print(f"  {rec.group_category.strip():<10}{v_str:3s}{rec.part_id:<16} {desc}")

        matched = sum(1 for _, _, _, _, m in all_callouts if m)
        print()
        print(f"Callouts on figure: {len(all_callouts)}  (matched to VIN: {matched}, other: {len(all_callouts) - matched})")

        # --- Load figure cross-references (FigureIndexRecord22) ---
        xref_ranges = [r for r in ranges if r[3] == 'figure_index_22']
        fig_xrefs = []
        for rs, re_, rc, rt in xref_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_figure_index_records_22(f, bo)
                for r in recs:
                    if r.model_code == model_code and r.figure.strip() == fig_target and r.page.strip() == page_target:
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
