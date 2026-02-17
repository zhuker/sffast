#!/usr/bin/env python3
"""
check_shopping_list.py - Verify shopping list parts against a VIN.

Reads part numbers from shopping_list.txt and checks each one against
the FAST2 catalog for the given VIN by walking all applicable figure pages
and their callouts (same approach as vin_figures.py).

Usage: .venv/bin/python check_shopping_list.py [VIN] [shopping_list.txt]
       Default VIN: JF1GD70655L510047 (2005 STI)
"""

import sys
from collections import defaultdict

from sffastus_parser import is_valid_subaru_vin
from sffastus_database import SffastDatabase


def load_shopping_list(path: str) -> list[str]:
    """Load part numbers from a text file (one per line, stripped)."""
    parts = []
    with open(path) as f:
        for line in f:
            pn = line.strip()
            if pn:
                parts.append(pn)
    return parts


def main():
    vin = sys.argv[1] if len(sys.argv) > 1 else "JF1GD70655L510047"
    shopping_file = sys.argv[2] if len(sys.argv) > 2 else "shopping_list.txt"

    if not is_valid_subaru_vin(vin):
        print(f"Error: '{vin}' is not a valid Subaru VIN")
        sys.exit(1)

    shopping_parts = load_shopping_list(shopping_file)
    if not shopping_parts:
        print(f"Error: no parts found in {shopping_file}")
        sys.exit(1)

    print(f"VIN:           {vin}")
    print(f"Shopping list: {shopping_file} ({len(shopping_parts)} parts)")
    print()

    with SffastDatabase.open() as db:
        # Resolve VIN
        try:
            vehicle = db.resolve_vin(vin)
        except LookupError as e:
            print(str(e))
            sys.exit(1)

        model_rec = vehicle.model_rec
        spec = vehicle.spec
        print(f"  Model:   {vehicle.vin_rec.model_code}")
        print(f"  Body:    {vehicle.vin_rec.body_model}")
        if spec:
            print(f"  Engine:  {spec.engine}")
            print(f"  Trans:   {spec.transmission}")
            print(f"  Trim:    {spec.trim_level}")
        print(f"  Date:    {vehicle.vehicle_date}")
        model_year = db.get_model_year(vehicle)
        if model_year:
            print(f"  MY:      {model_year}")
        print()

        # Build part_number -> [(fig, page, callout, desc), ...] by walking
        # all applicable figure pages (same as vin_figures.py)
        print("Loading applicable figures and callouts...")
        all_pages = db.get_vin_figures(vehicle)
        applicable_figs = [p for p in all_pages if p.type == 'figure']

        # Dedup figure pages
        fig_pages = sorted(set((p.figure, p.page) for p in applicable_figs))
        print(f"  Applicable figure pages: {len(fig_pages)}")

        part_to_figs = defaultdict(list)  # part_number -> [(fig, page, callout, desc), ...]
        for fig, page in fig_pages:
            callouts = db.get_fig_callouts(model_rec, fig, page, vehicle=vehicle)
            for c in callouts:
                for p in c.parts:
                    pn = p.part_number.strip()
                    if pn:
                        part_to_figs[pn].append({
                            'figure': fig,
                            'page': page,
                            'callout': c.callout_code,
                            'desc': p.description or c.description,
                        })

        print(f"  Unique parts across all figures: {len(part_to_figs)}")
        print()

        # ITCA catalog for supersession checks
        catalog = db.parts_catalog

        # Check each shopping list part
        print("=" * 90)
        print("SHOPPING LIST VERIFICATION")
        print("=" * 90)
        print()

        matched = []
        superseded = []
        not_found = []

        for i, shop_pn in enumerate(shopping_parts, 1):
            # Direct match in figure callouts
            if shop_pn in part_to_figs:
                entries = part_to_figs[shop_pn]
                desc = entries[0]['desc']
                figs = sorted(set(f"{e['figure']}-{e['page']}" for e in entries))
                fig_str = ', '.join(figs)
                matched.append((shop_pn, desc, fig_str))
                print(f"  {i:2d}. {shop_pn:14s}  OK            FIG {fig_str:20s}  {desc}")
                continue

            # Check ITCA: maybe shopping list part supersedes a catalog part
            # or a catalog part supersedes to the shopping list part
            itca_hits = catalog.lookup(shop_pn)
            found_via_itca = False
            for ir in itca_hits:
                orig = ir.part_number.strip()
                sup_to = ir.supersedes_to.strip()

                # Case 1: shop_pn is the original, supersedes_to is in our figures
                if orig == shop_pn and sup_to in part_to_figs:
                    entries = part_to_figs[sup_to]
                    desc = ir.description or entries[0]['desc']
                    figs = sorted(set(f"{e['figure']}-{e['page']}" for e in entries))
                    fig_str = ', '.join(figs)
                    superseded.append((shop_pn, sup_to, desc, fig_str, 'catalog has newer'))
                    print(f"  {i:2d}. {shop_pn:14s}  SUPERSEDED    catalog has {sup_to} instead  {desc}")
                    found_via_itca = True
                    break

                # Case 2: shop_pn is the supersedes_to target, original is in our figures
                if sup_to == shop_pn and orig in part_to_figs:
                    entries = part_to_figs[orig]
                    desc = ir.description or entries[0]['desc']
                    figs = sorted(set(f"{e['figure']}-{e['page']}" for e in entries))
                    fig_str = ', '.join(figs)
                    superseded.append((shop_pn, orig, desc, fig_str, 'replaces catalog part'))
                    print(f"  {i:2d}. {shop_pn:14s}  SUPERSEDES    replaces {orig} in catalog  FIG {fig_str}  {desc}")
                    found_via_itca = True
                    break

            if found_via_itca:
                continue

            # Check if part exists in ITCA at all (known part, just not for this VIN)
            if itca_hits:
                desc = itca_hits[0].description
                not_found.append((shop_pn, desc, 'in ITCA but not matched to VIN'))
                print(f"  {i:2d}. {shop_pn:14s}  NOT MATCHED   known part, not for this VIN  {desc}")
            else:
                not_found.append((shop_pn, '', 'unknown'))
                print(f"  {i:2d}. {shop_pn:14s}  NOT FOUND     not in catalog or ITCA")

        # Summary
        print()
        print("=" * 90)
        print("SUMMARY")
        print("=" * 90)
        print(f"  Total parts:      {len(shopping_parts)}")
        print(f"  Direct match:     {len(matched)}")
        print(f"  Superseded/chain: {len(superseded)}")
        print(f"  Not matched:      {len(not_found)}")

        if superseded:
            print()
            print("SUPERSEDED PARTS:")
            for shop_pn, other_pn, desc, fig_str, note in superseded:
                print(f"  {shop_pn:14s} <-> {other_pn:14s}  FIG {fig_str}  ({note})  {desc}")

        if not_found:
            print()
            print("UNMATCHED PARTS:")
            for shop_pn, desc, note in not_found:
                print(f"  {shop_pn:14s}  {note}  {desc}")


if __name__ == "__main__":
    main()
