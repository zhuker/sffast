#!/usr/bin/env python3
"""
vin_figures.py - Find applicable figures for a specific VIN.

1. Looks up VIN in the JDM/US VIN range index -> VIN detail record
2. Gets model code, body model -> model spec (engine, body, trans, trim)
3. Parses EngineSpecRecord230 for the model -> figure applicability rules
4. Evaluates spec logic expressions + date ranges against the VIN's specs
5. Prints applicable (figure, page) pairs

Usage: .venv/bin/python vin_figures.py [VIN]
       Default VIN: JF1GD70655L510047 (2005 STI)
"""

import sys
from collections import defaultdict

from sffastus_parser import is_valid_subaru_vin

from sffastus_database import SffastDatabase


def main():
    vin = sys.argv[1] if len(sys.argv) > 1 else "JF1GD70655L510047"

    if not is_valid_subaru_vin(vin):
        print(f"Error: '{vin}' is not a valid Subaru VIN")
        sys.exit(1)

    print(f"VIN: {vin}")
    print()

    with SffastDatabase.open() as db:
        # Steps 1-3: VIN lookup + model index + model spec
        print("Resolving VIN...")
        try:
            vehicle = db.resolve_vin(vin)
        except LookupError as e:
            print(str(e))
            sys.exit(1)

        vin_rec = vehicle.vin_rec
        model_rec = vehicle.model_rec
        spec = vehicle.spec
        codes = vehicle.codes
        vehicle_date = vehicle.vehicle_date

        print(f"  Model:       {vin_rec.model_code}")
        print(f"  Body Model:  {vin_rec.body_model}")
        print(f"  Color:       {vin_rec.color_code}")
        print(f"  Trim:        {vin_rec.trim_code}")
        print(f"  Option:      {vin_rec.option_code}")
        print(f"  Destination: {vin_rec.destination_code}")
        print(f"  Date:        {vin_rec.date1}")
        if spec:
            print(f"  Applied Model: {spec.applied_model}")
            print(f"  Body:          {spec.body_config}")
            print(f"  Engine:        {spec.engine}")
            print(f"  Transmission:  {spec.transmission}")
            print(f"  Trim:          {spec.trim_level}")
            print(f"  Drivetrain:    {spec.drivetrain}")
            print(f"  Codes:         {sorted(codes)}")
        else:
            print("  Warning: No model spec found")
        print()

        # Vehicle production date in YYYYMM format
        print(f"Production date: {vehicle_date}")
        print()

        # Step 4-5: Find applicable figure pages
        print("Loading figure applicability records...")
        total_specs = len(db.get_engine_specs(model_rec))
        print(f"  Total figure applicability records: {total_specs}")
        print()

        all_pages = db.get_vin_figures(vehicle)
        applicable_figs = [p for p in all_pages if p.type == 'figure']
        bulletins = [p for p in all_pages if p.type == 'bulletin']

        print(f"Applicable figure pages: {len(applicable_figs)} (+{len(bulletins)} I&S bulletins)")
        print()

        # Step 6: Load FIG illustration page 89 records for this model
        print("Loading figure illustration pages...")
        print(f"  Total figure pages with images: {len(db.get_fig_illustration_pages(model_rec))}")

        # Step 6.1: Load FIG group category records (184) for this model
        print("\nLoading figure group categories...")
        print(f"  Group categories: {len(db.get_fig_group_categories(model_rec))}")

        # Step 6.2: Load FIG illustration descriptions (183)
        print("Loading figure illustration descriptions...")
        print(f"  Figure descriptions: {len(db.get_fig_illustrations(model_rec))}")

        # Step 6.5: Preload part/inventory/catalog data (lazy-cached in db)
        print("\nLoading part & inventory data...")
        print(f"  Part groups: {len(db.get_part_groups(model_rec))}")
        print(f"  Inventory records: {len(db.get_inventory_records(model_rec))}")
        print(f"  Parts catalog: {len(db.get_catalog_parts(model_rec))}")

        # Step 7: Print results
        print()
        print("=" * 80)
        print(f"APPLICABLE FIGURES FOR VIN {vin}")
        print(f"  {vin_rec.model_code} / {spec.applied_model if spec else vin_rec.body_model}"
              f" / {spec.engine if spec else '?'} / {spec.transmission if spec else '?'}"
              f" / {spec.trim_level if spec else '?'}")
        print(f"  Production: {vehicle_date}")
        print("=" * 80)
        print()

        # Group applicable figure pages by (figure, page)
        by_fig_page = defaultdict(list)
        for p in applicable_figs:
            by_fig_page[(p.figure, p.page)].append(p)

        total_with_image = 0
        total_without_image = 0
        total_parts = 0

        # Group figures by category (184 -> 183 hierarchy)
        category_figures = defaultdict(list)  # group_code -> [(fig, page), ...]
        uncategorized = []

        for fig, page in sorted(by_fig_page.keys()):
            fig183 = db.get_fig_info(model_rec, fig)
            if fig183:
                category_figures[fig183.fig_group_code].append((fig, page))
            else:
                uncategorized.append((fig, page))

        # Sort categories by group code
        sorted_cats = sorted(category_figures.keys())

        def print_figure(fig, page):
            nonlocal total_with_image, total_without_image, total_parts
            fig183 = db.get_fig_info(model_rec, fig)
            fig_desc = fig183.desc_en if fig183 else db.get_figname(fig)

            fig89 = db.get_fig_page(model_rec, fig, page)
            if fig89 and fig89.image_size > 0:
                total_with_image += 1
            else:
                total_without_image += 1

            img_flag = "" if fig89 else "  (no img)"
            raw_label = fig89.label if fig89 else ""
            label = " ".join(raw_label.split()) if raw_label else ""
            label_str = f"  ({label})" if label else ""
            print(f"  FIG {fig}-{page} {fig_desc}{label_str}{img_flag}")

            callouts = db.get_fig_callouts(model_rec, fig, page, vehicle=vehicle)
            pg_callouts = sorted([c for c in callouts if c.source == 'part_group'],
                                 key=lambda c: c.code)
            inv_callouts = sorted([c for c in callouts if c.source == 'inventory'],
                                  key=lambda c: c.code)
            pg_bases = set(c.code.split()[0] for c in pg_callouts)

            count = 0
            for c in pg_callouts:
                base = c.code.split()[0]
                if c.parts:
                    for i, p in enumerate(c.parts):
                        extra = []
                        if p.usage_notes:
                            extra.append(p.usage_notes)
                        if p.part_spec:
                            extra.append(p.part_spec)
                        extra_str = f"  [{', '.join(extra)}]" if extra else ""
                        vstr = f"*{p.variant}" if p.variant else "  "
                        chain_str = ""
                        if p.itca_chain:
                            parts_str = []
                            for link in p.itca_chain:
                                if link.bulletin_figure:
                                    parts_str.append(
                                        f"{link.part_number}({link.code.label}"
                                        f" FIG {link.bulletin_figure}-{link.bulletin_page}"
                                        f" {link.bulletin_label})")
                                else:
                                    parts_str.append(f"{link.part_number}({link.code.label})")
                            chain_str = " -> " + " -> ".join(parts_str)
                        if p.bulletin_figure:
                            bltn = f"FIG {p.bulletin_figure}-{p.bulletin_page} {p.bulletin_label}"
                            if chain_str:
                                chain_str = f" [{bltn}]{chain_str}"
                            else:
                                chain_str = f" [{bltn}]"
                        indent_ = "" if i == 0 else "\t"
                        print(f"{indent_}    {base:8s}{vstr} {p.part_number:14s} {p.description}{extra_str}{chain_str}")
                        count += 1
                else:
                    print(f"    {base:8s}   {'--':14s} {c.description}")
                    count += 1

            for c in inv_callouts:
                if c.code.split()[0] in pg_bases:
                    continue
                if not c.parts:
                    continue
                base = c.code.split()[0]
                pn = c.parts[0].part_number
                print(f"    {base:8s}   {pn:14s} {c.description}")
                count += 1

            total_parts += count

        for cat_code in sorted_cats:
            cat184 = db.get_fig_category(model_rec, cat_code)
            cat_desc = cat184.desc_en if cat184 else cat_code
            print(f"--- {cat_code}: {cat_desc} ---")
            for fig, page in category_figures[cat_code]:
                print_figure(fig, page)
            print()

        if uncategorized:
            print("--- Uncategorized ---")
            for fig, page in uncategorized:
                print_figure(fig, page)
            print()

        print(f"Total: {len(by_fig_page)} figure pages, "
              f"{total_with_image} with images, "
              f"{total_without_image} without")
        print(f"       {total_parts} applicable parts")

        if bulletins:
            print(f"\nI&S Bulletins (page 40+): {len(bulletins)} entries across "
                  f"{len(set(b.figure for b in bulletins))} figures (not shown above)")


if __name__ == "__main__":
    main()
