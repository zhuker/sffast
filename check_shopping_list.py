#!/usr/bin/env python3
"""
check_shopping_list.py - Verify shopping list parts against a VIN.

Reads part numbers from shopping_list.txt and checks each one against
the FAST2 catalog for the given VIN by walking all applicable figure pages
and their callouts (same approach as vin_figures.py).

Output is grouped by figure, with figure name, label, and category
(like vin_figures.py).  Parts appearing in multiple figures are shown
in each figure.

Usage: .venv/bin/python check_shopping_list.py [VIN] [shopping_list.txt]
       Default VIN: JF1GD70655L510047 (2005 STI)
"""

import sys
from collections import defaultdict
from dataclasses import dataclass

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


@dataclass
class ShopPartHit:
    """A shopping list part found on a specific figure page."""
    shop_pn: str       # part number from shopping list
    catalog_pn: str    # part number in catalog (same or superseded original)
    callout: str       # callout code on figure
    desc: str          # part description
    status: str        # 'OK' | 'SUPERSEDES'


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

    shop_set = set(shopping_parts)

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

        # ITCA catalog for supersession checks
        catalog = db.parts_catalog

        # Build supersession map for shopping list parts:
        # shop_pn -> catalog_pn it replaces (or is replaced by)
        supersession = {}  # shop_pn -> (catalog_pn, note)
        for shop_pn in shopping_parts:
            for ir in catalog.lookup(shop_pn):
                orig = ir.part_number.strip()
                sup_to = ir.supersedes_to.strip()
                if orig == shop_pn and sup_to:
                    supersession[shop_pn] = (sup_to, 'catalog has newer')
                    break
                if sup_to == shop_pn and orig:
                    supersession[shop_pn] = (orig, 'replaces catalog part')
                    break

        # Walk all applicable figure pages, collect hits for shopping list parts
        print("Loading applicable figures and callouts...")
        all_pages = db.get_vin_figures(vehicle)
        applicable_figs = [p for p in all_pages if p.type == 'figure']
        fig_pages = sorted(set((p.figure, p.page) for p in applicable_figs))
        print(f"  Applicable figure pages: {len(fig_pages)}")

        # (fig, page) -> [ShopPartHit, ...]
        fig_hits = defaultdict(list)
        direct_match_pns = set()
        supersede_match_pns = set()

        # Reverse supersession map: catalog_pn -> shop_pn
        cat_to_shop = {}
        for shop_pn, (cat_pn, note) in supersession.items():
            cat_to_shop[cat_pn] = shop_pn

        for fig, page in fig_pages:
            seen_on_page = set()  # (shop_pn,) dedup per figure page
            callouts = db.get_fig_callouts(model_rec, fig, page, vehicle=vehicle)
            for c in callouts:
                for p in c.parts:
                    pn = p.part_number.strip()
                    if not pn:
                        continue
                    desc = p.description or c.description

                    # Direct match
                    if pn in shop_set and pn not in seen_on_page:
                        seen_on_page.add(pn)
                        fig_hits[(fig, page)].append(ShopPartHit(
                            shop_pn=pn, catalog_pn=pn,
                            callout=c.callout_code, desc=desc,
                            status='OK',
                        ))
                        direct_match_pns.add(pn)

                    # Supersession match: a shopping list part replaces this catalog part
                    if pn in cat_to_shop:
                        shop_pn = cat_to_shop[pn]
                        if shop_pn not in seen_on_page:
                            seen_on_page.add(shop_pn)
                            fig_hits[(fig, page)].append(ShopPartHit(
                                shop_pn=shop_pn, catalog_pn=pn,
                                callout=c.callout_code, desc=desc,
                                status='SUPERSEDES',
                            ))
                            supersede_match_pns.add(shop_pn)

        matched_pns = direct_match_pns | supersede_match_pns
        print(f"  Shopping list parts found: {len(matched_pns)}/{len(shopping_parts)}")
        print()

        # Group figures by category (184 -> 183 hierarchy) — same as vin_figures.py
        category_figures = defaultdict(list)
        uncategorized = []
        fig_pages_with_hits = sorted(fig_hits.keys())

        for fig, page in fig_pages_with_hits:
            fig183 = db.get_fig_info(model_rec, fig)
            if fig183:
                category_figures[fig183.fig_group_code].append((fig, page))
            else:
                uncategorized.append((fig, page))

        # Print grouped by figure
        print("=" * 90)
        print(f"SHOPPING LIST PARTS BY FIGURE — VIN {vin}")
        if spec:
            print(f"  {vehicle.vin_rec.model_code} / {spec.applied_model}"
                  f" / {spec.engine} / {spec.transmission} / {spec.trim_level}")
        print(f"  Production: {vehicle.vehicle_date}  Model year: {model_year}")
        print("=" * 90)
        print()

        def print_figure(fig, page):
            fig183 = db.get_fig_info(model_rec, fig)
            fig_desc = fig183.desc_en if fig183 else db.get_figname(fig)

            fig89 = db.get_fig_page(model_rec, fig, page)
            raw_label = fig89.label if fig89 else ""
            label = " ".join(raw_label.split()) if raw_label else ""
            label_str = f"  ({label})" if label else ""

            print(f"  FIG {fig}-{page} {fig_desc}{label_str}")

            hits = fig_hits[(fig, page)]
            for h in sorted(hits, key=lambda h: h.callout):
                if h.status == 'OK':
                    print(f"{h.shop_pn:14s}  {h.desc}")
                else:
                    print(f"{h.shop_pn:14s}  {h.desc}  (supersedes {h.catalog_pn})")

        for cat_code in sorted(category_figures.keys()):
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

        # Unmatched parts
        unmatched = [pn for pn in shopping_parts if pn not in matched_pns]
        if unmatched:
            print("--- NOT MATCHED ---")
            for pn in unmatched:
                itca_hits = catalog.lookup(pn)
                if itca_hits:
                    desc = itca_hits[0].description
                    print(f"    {pn:14s}  known part, not for this VIN  {desc}")
                else:
                    print(f"    {pn:14s}  not in catalog or ITCA")
            print()

        # Summary
        print("=" * 90)
        print("SUMMARY")
        print("=" * 90)
        n_ok = len(direct_match_pns)
        n_sup = len(supersede_match_pns - direct_match_pns)
        print(f"  Total parts:      {len(shopping_parts)}")
        print(f"  Direct match:     {n_ok}")
        print(f"  Superseded/chain: {n_sup}")
        print(f"  Not matched:      {len(unmatched)}")


if __name__ == "__main__":
    main()
