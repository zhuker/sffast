#!/usr/bin/env python3
"""
figure_parts_map.py - Extract figure image, find applicable parts, draw callout boxes.

1. Looks up VIN -> model spec -> vehicle codes
2. Extracts CCITT G4 figure image as PNG
3. Loads callout coordinates with part numbers via SffastDatabase
4. Prints part-to-coordinate map
5. Draws bounding boxes around callouts on the figure image

Usage: .venv/bin/python figure_parts_map.py [FIG] [PAGE] [VIN]
       .venv/bin/python figure_parts_map.py 940 01
       .venv/bin/python figure_parts_map.py 940 01 JF1GD70655L510047
"""

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from sffastus_parser import is_valid_subaru_vin
from sffastus_database import SffastDatabase


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

    with SffastDatabase.open() as db:
        # --- VIN resolution ---
        print("Resolving VIN...")
        try:
            vehicle = db.resolve_vin(vin)
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

        # --- Extract figure image ---
        print("Finding figure image...")
        wand_img = db.get_fig_img(model_rec, fig_target, page_target)
        if not wand_img:
            print(f"  Figure {fig_target}-{page_target} not found for {model_code}")
            sys.exit(1)

        with wand_img:
            png_blob = wand_img.make_blob('png')

        base_png = Path(f"output/fig{fig_target}_{page_target}_base.png")
        base_png.parent.mkdir(exist_ok=True)
        base_png.write_bytes(png_blob)
        print(f"  Saved base image: {base_png}")

        # --- Load callout coordinates ---
        print("\nLoading callout coordinates...")
        callouts = db.get_fig_callouts(model_rec, fig_target, page_target, vehicle=vehicle)

        pg_count = sum(1 for c in callouts if c.source == 'part_group')
        inv_count = sum(1 for c in callouts if c.source == 'inventory')
        print(f"  PartGroup185 callouts: {pg_count}")
        print(f"  Inventory199 callouts: {inv_count}")
        print(f"  Total callouts with coordinates: {len(callouts)}")

        # --- Print parts map ---
        print()
        print("=" * 110)
        print(f"PARTS MAP: FIG {fig_target}-{page_target}  VIN {vin}  ({model_code})")
        print("=" * 110)
        print(f"{'Callout':<10} {'Part Number':<16} {'Px X':>5} {'Px Y':>5}  Description")
        print("-" * 110)

        for c in sorted(callouts, key=lambda c: (c.code, c.px_y)):
            pn_str = c.part_number if c.part_number else '--'
            print(f"{c.code:<10}   {pn_str:<16} {c.px_x:5d} {c.px_y:5d}  {c.description}")

        matched_count = sum(1 for c in callouts if c.part_number)
        print()
        print(f"Callouts on figure: {len(callouts)}  (matched to VIN: {matched_count}, other: {len(callouts) - matched_count})")

        # --- Load figure cross-references ---
        xrefs = db.get_fig_xrefs(model_rec, fig_target, page_target)

        if xrefs:
            print()
            print(f"Figure cross-references: {len(xrefs)}")
            for xr in xrefs:
                print(f"  -> FIG {xr.ref_figure}  px=({xr.px_x},{xr.px_y})")

        # --- Draw bounding boxes ---
        print(f"\nDrawing callout boxes...")
        img = Image.open(io.BytesIO(png_blob)).convert('RGB')
        draw = ImageDraw.Draw(img)

        BOX_W, BOX_H = 100, 14

        for c in callouts:
            x0 = c.px_x
            y0 = c.px_y - 2
            x1 = c.px_x - 2 + BOX_W
            y1 = c.px_y - 2 + BOX_H

            color = 'red' if c.part_number else 'blue'
            draw.rectangle([x0, y0, x1, y1], outline=color, width=1)
            draw.text((x0 + 2, y1 + 1), c.code, fill=color)

        for xr in xrefs:
            x0 = xr.px_x
            y0 = xr.px_y - 2
            x1 = xr.px_x - 2 + BOX_W
            y1 = xr.px_y - 2 + BOX_H
            label = f"-> FIG {xr.ref_figure}"
            draw.rectangle([x0, y0, x1, y1], outline='green', width=1)
            draw.text((x0 + 2, y1 + 1), label, fill='green')

        out_path = Path(f"output/fig{fig_target}_{page_target}_annotated.png")
        img.save(out_path)
        print(f"Saved annotated image: {out_path}")


if __name__ == "__main__":
    main()
