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

import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

from sffastus_parser import (
    SffastusBlockParser,
    SffastusHeader,
    CatalogApplicabilityRecord466,
    EngineSpecRecord230,
    FIGGroupCategoryRecord184,
    FIGIllustrationPage89,
    FIGIllustrationRecord183,
    ModelSpecRecord103,
    VINModelRecord,
    decode_block_pointer,
    parse_figname_txt,
    parse_itca_data,
    ItcaPartsCatalog,
    is_valid_subaru_vin,
)

SFCDUS2_PATH = Path("SFCDUS2/sffastus")
FIGNAME_PATH = "SFCDUS2/sffastpg/win/figname.txt"
ITCA_DATA = ["SFCDUS1/ITCA_DATA.TXT", "SFCDUS2/itca_data.txt", "SFCDUS3/itca_data.txt"]
BLOCK_SIZE = 2048


# --- Spec Logic Expression Evaluator ---

def tokenize_spec(expr: str) -> list:
    """Tokenize a spec logic expression into tokens."""
    tokens = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch in ' \t':
            i += 1
        elif ch in '()+.*':
            tokens.append(ch)
            i += 1
        else:
            # Alphanumeric token (may contain #, /)
            j = i
            while j < len(expr) and expr[j] not in '()+. \t':
                if expr[j] == '*' and j > i:
                    break  # * is NOT operator, not part of token
                j += 1
            tokens.append(expr[i:j])
            i = j
    return tokens


def match_code(pattern: str, codes: set) -> bool:
    """Check if a pattern matches any code in the set. '#' is single-char wildcard."""
    if pattern == 'ALL':
        return True
    if '#' in pattern:
        regex = '^' + re.escape(pattern).replace(r'\#', '.') + '$'
        return any(re.match(regex, code) for code in codes)
    return pattern in codes


def eval_spec_logic(expr: str, codes: set) -> bool:
    """Evaluate a spec logic expression against a set of vehicle codes.

    Syntax:
        + separates OR alternatives
        . separates AND requirements
        * negation (NOT)
        # single-char wildcard
        () grouping
        ALL matches everything
    """
    if not expr or expr.isspace():
        return True  # empty = universal

    # Strip trailing part numbers from "ALL    partnum" patterns
    # and from other expressions that have embedded part numbers
    # Part numbers are 40+ chars into the applicable_model field
    # Just take the spec expression part (strip trailing part-number-like data)
    expr = expr.strip()

    tokens = tokenize_spec(expr)
    if not tokens:
        return True

    pos = [0]  # mutable index

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def consume(expected=None):
        tok = tokens[pos[0]] if pos[0] < len(tokens) else None
        if expected and tok != expected:
            return None
        pos[0] += 1
        return tok

    def parse_expr():
        """expr = and_expr ('+' and_expr)*"""
        result = parse_and_expr()
        while peek() == '+':
            consume('+')
            right = parse_and_expr()
            result = result or right
        return result

    def parse_and_expr():
        """and_expr = atom ('.' atom)*"""
        result = parse_atom()
        while peek() == '.':
            consume('.')
            right = parse_atom()
            result = result and right
        return result

    def parse_atom():
        """atom = '(' expr ')' | '*' atom | TERM"""
        tok = peek()
        if tok == '(':
            consume('(')
            result = parse_expr()
            consume(')')
            return result
        elif tok == '*':
            consume('*')
            return not parse_atom()
        elif tok is not None and tok not in '()+.*':
            consume()
            return match_code(tok, codes)
        return False

    try:
        result = parse_expr()
        return result
    except (IndexError, TypeError):
        # Parse error - be permissive, include the record
        return True


def date_in_range(vehicle_yyyymm: str, start_yyyymm: str, end_yyyymm: str) -> bool:
    """Check if vehicle production date falls within the spec date range."""
    if start_yyyymm and vehicle_yyyymm < start_yyyymm:
        return False
    if end_yyyymm and vehicle_yyyymm > end_yyyymm:
        return False
    return True


# --- VIN Lookup ---

def lookup_vin(f, parser, vin: str) -> VINModelRecord | None:
    """Look up a VIN using the range index -> detail record."""
    f.seek(0)
    header = SffastusHeader.parse(f.read(50))

    # Determine which VIN section to search
    if vin.startswith('4S3') or vin.startswith('4S4'):
        vin_offset = header.us_vin_start_block * BLOCK_SIZE
        vin_blocks = header.us_vin_count
    else:
        vin_offset = header.jdm_vin_start_block * BLOCK_SIZE
        vin_blocks = header.jdm_vin_count

    # Search VIN range blocks
    for bi in range(vin_blocks):
        bo = vin_offset + bi * BLOCK_SIZE
        ranges = parser.parse_vin_blocks(f, start_offset=bo, max_records=60)
        if not ranges:
            continue

        if ranges[0].vin_start > vin:
            break
        if ranges[-1].vin_end < vin:
            continue

        for r in ranges:
            if r.vin_start <= vin <= r.vin_end:
                ptr_bytes = struct.pack('<HH', r.section, r.index)
                bp = decode_block_pointer(ptr_bytes)
                detail_offset = bp * BLOCK_SIZE
                detail_recs = parser.parse_vin_model_records(f, start_offset=detail_offset)
                for dr in detail_recs:
                    if dr.vin == vin:
                        return dr
                return None

    return None


def body_model_matches_applied(body_model: str, applied_model: str) -> bool:
    """Check if a 7-char body model matches an applied model like 'GDF-YEH'.

    Body model GDFDYEH = GDF + D + YEH (7 chars)
    Applied model GDF-YEH = GDF + '-' + YEH
    Character 3 of body model is dropped, replaced with dash in applied model.
    """
    if '-' in applied_model:
        prefix, suffix = applied_model.split('-', 1)
        return body_model[:len(prefix)] == prefix and body_model[len(prefix)+1:] == suffix
    # No dash - try direct match
    return applied_model.replace(' ', '') == body_model


def find_model_spec(f, parser, ranges, model_code: str, body_model: str) -> ModelSpecRecord103 | None:
    """Find the ModelSpecRecord103 matching the body model."""
    ms_ranges = [r for r in ranges if r[3] == 'model_spec_103']
    for rs, re_, rc, rt in ms_ranges:
        f.seek(rs)
        test = f.read(6).decode('cp437', errors='replace').strip()
        if test != model_code:
            continue

        specs = []
        for bi in range(rc):
            bo = rs + bi * BLOCK_SIZE
            recs = parser.parse_model_spec_records_103(f, bo)
            specs.extend(recs)

        for s in specs:
            if body_model_matches_applied(body_model, s.applied_model):
                return s

    return None


def get_vehicle_codes(spec: ModelSpecRecord103) -> set:
    """Extract the set of spec codes from a model specification record."""
    codes = set()

    # Body config
    if spec.body_config:
        codes.add(spec.body_config)

    # Engine code (e.g., "257", "EJ257", "205")
    if spec.engine:
        codes.add(spec.engine)
        # Also add short form if engine is like "EJ257"
        if spec.engine.startswith('EJ') and len(spec.engine) >= 5:
            codes.add(spec.engine[2:])

    # Transmission
    if spec.transmission:
        codes.add(spec.transmission)

    # Trim level
    if spec.trim_level:
        codes.add(spec.trim_level)

    # Drivetrain
    if spec.drivetrain:
        codes.add(spec.drivetrain)

    # Spec option
    if spec.spec_option:
        codes.add(spec.spec_option)

    return codes


def main():
    vin = sys.argv[1] if len(sys.argv) > 1 else "JF1GD70655L510047"

    if not is_valid_subaru_vin(vin):
        print(f"Error: '{vin}' is not a valid Subaru VIN")
        sys.exit(1)

    print(f"VIN: {vin}")
    print()

    # Create parser
    figure_codes = set()
    if Path(FIGNAME_PATH).exists():
        figure_codes = {r.figure_code for r in parse_figname_txt(FIGNAME_PATH)}

    itca_records = []
    for itca_path in ITCA_DATA:
        if Path(itca_path).exists():
            itca_records.extend(parse_itca_data(itca_path))
    parts_catalog = ItcaPartsCatalog(itca_records)

    parser = SffastusBlockParser(figure_codes=figure_codes, parts_catalog=parts_catalog)

    with open(SFCDUS2_PATH, 'rb') as f:
        # Step 1: Look up VIN
        print("Looking up VIN...")
        vin_rec = lookup_vin(f, parser, vin)
        if not vin_rec:
            print(f"VIN {vin} not found in database")
            sys.exit(1)

        print(f"  Model:       {vin_rec.model_code}")
        print(f"  Body Model:  {vin_rec.body_model}")
        print(f"  Color:       {vin_rec.color_code}")
        print(f"  Trim:        {vin_rec.trim_code}")
        print(f"  Option:      {vin_rec.option_code}")
        print(f"  Destination: {vin_rec.destination_code}")
        print(f"  Date:        {vin_rec.date1}")
        print()

        # Step 2: Scan block types
        print("Scanning blocks...")
        ranges = parser.scan_block_types(f)

        # Step 3: Find model spec for body model
        print("Finding model spec...")
        spec = find_model_spec(f, parser, ranges, vin_rec.model_code, vin_rec.body_model)
        if not spec:
            print(f"Warning: No model spec found for body model {vin_rec.body_model}")
            print("         Using VIN record fields as fallback")
            # Build codes from VIN record fields
            codes = set()
        else:
            print(f"  Applied Model: {spec.applied_model}")
            print(f"  Body:          {spec.body_config}")
            print(f"  Engine:        {spec.engine}")
            print(f"  Transmission:  {spec.transmission}")
            print(f"  Trim:          {spec.trim_level}")
            print(f"  Drivetrain:    {spec.drivetrain}")
            codes = get_vehicle_codes(spec)
            print(f"  Codes:         {sorted(codes)}")
        print()

        # Vehicle production date in YYYYMM format
        vehicle_date = vin_rec.date1[:6]  # e.g., "200406"
        print(f"Production date: {vehicle_date}")
        print()

        # Step 4: Find engine spec 230 records for this model
        print("Loading figure applicability records...")
        es_ranges = [r for r in ranges if r[3] == 'engine_spec_230']
        all_es_records = []
        for rs, re_, rc, rt in es_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != vin_rec.model_code:
                continue

            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_engine_spec_records_230(f, bo)
                all_es_records.extend(recs)

        model_records = [r for r in all_es_records if r.model_code == vin_rec.model_code]
        print(f"  Total figure applicability records: {len(model_records)}")
        print()

        # Step 5: Filter by spec logic and date range
        applicable = []
        bulletins = []
        for rec in model_records:
            # Extract just the spec expression (strip trailing part numbers)
            spec_expr = rec.applicable_model
            # Part numbers appear after ~40 chars of spaces
            # Split on multiple spaces to separate spec from part number
            parts = re.split(r'\s{3,}', spec_expr, maxsplit=1)
            spec_only = parts[0].strip()

            if not eval_spec_logic(spec_only, codes):
                continue

            if not date_in_range(vehicle_date, rec.start_date, rec.end_date):
                continue

            # Pages 40+ are I&S Bulletins (installation & service), not illustrations
            page_num = int(rec.figure_page) if rec.figure_page.isdigit() else 0
            if page_num >= 40:
                bulletins.append(rec)
            else:
                applicable.append(rec)

        print(f"Applicable figure pages: {len(applicable)} (+{len(bulletins)} I&S bulletins)")
        print()

        # Step 6: Load FIG illustration page 89 records for this model
        print("Loading figure illustration pages...")
        fig89_ranges = [r for r in ranges if r[3] == 'fig_illustration_page_89']
        all_fig89 = []
        for rs, re_, rc, rt in fig89_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != vin_rec.model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_fig_illustration_page_records_89(f, bo)
                all_fig89.extend(recs)

        model_fig89 = [r for r in all_fig89 if r.model_code == vin_rec.model_code]
        print(f"  Total figure pages with images: {len(model_fig89)}")

        # Build lookup: (fig_index, page_index) -> FIGIllustrationPage89
        fig89_lookup = {}
        for r in model_fig89:
            fig89_lookup[(r.fig_index, r.page_index)] = r

        # Step 6.1: Load FIG group category records (184) for this model
        print("\nLoading figure group categories...")
        fig184_ranges = [r for r in ranges if r[3] == 'fig_group_category_184']
        all_fig184 = []
        for rs, re_, rc, rt in fig184_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != vin_rec.model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_fig_group_category_records_184(f, bo)
                all_fig184.extend(recs)

        model_fig184 = [r for r in all_fig184 if r.model_code == vin_rec.model_code]

        # Build lookup: group_code (e.g., "0A") -> FIGGroupCategoryRecord184
        fig184_lookup = {}
        for r in model_fig184:
            fig184_lookup[r.fig_group_code] = r
        print(f"  Group categories: {len(fig184_lookup)}")

        # Step 6.2: Load FIG illustration records (183) for this model
        print("Loading figure illustration descriptions...")
        fig183_ranges = [r for r in ranges if r[3] == FIGIllustrationRecord183.ID]
        all_fig183 = []
        for rs, re_, rc, rt in fig183_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != vin_rec.model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_fig_illustration_records_183(f, bo)
                all_fig183.extend(recs)

        model_fig183 = [r for r in all_fig183 if r.model_code == vin_rec.model_code]

        # Build lookup: fig_code (e.g., "004") -> FIGIllustrationRecord183
        # Each figure appears twice (by-system 0A-9B and by-binder A1-D3);
        # prefer the "by system" record that has a matching 184 category
        fig183_by_fig = defaultdict(list)
        for r in model_fig183:
            fig183_by_fig[r.fig_group_code2].append(r)

        fig183_lookup = {}
        for fig_code, records in fig183_by_fig.items():
            best = records[0]
            for r in records:
                if r.fig_group_code in fig184_lookup:
                    best = r
                    break
            fig183_lookup[fig_code] = best
        print(f"  Figure descriptions: {len(fig183_lookup)}")

        # Step 6.5: Load part group descriptions (PartGroupRecord185)
        print("\nLoading part group descriptions...")
        pg_ranges = [r for r in ranges if r[3] == 'part_group_185']
        all_pg_records = []
        for rs, re_, rc, rt in pg_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != vin_rec.model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_part_group_records_185(f, bo)
                all_pg_records.extend(recs)

        # Build description lookup: (figure, part_code) -> desc_en
        # part_code may have variant suffix like "11021  A", strip it for matching
        part_desc_lookup = {}
        for r in all_pg_records:
            if r.model_code == vin_rec.model_code:
                code = r.part_code.split()[0]  # strip variant suffix
                key = (r.figure, code)
                if key not in part_desc_lookup:
                    part_desc_lookup[key] = r.desc_en
        print(f"  Part descriptions loaded: {len(part_desc_lookup)}")

        # Step 6.6: Load catalog applicability records (parts) for this model
        print("Loading parts catalog records...")
        cat_ranges = [r for r in ranges if r[3] == 'catalog_applicability_466']
        all_cat_records = []
        for rs, re_, rc, rt in cat_ranges:
            f.seek(rs)
            test = f.read(6).decode('cp437', errors='replace').strip()
            if test != vin_rec.model_code:
                continue
            for bi in range(rc):
                bo = rs + bi * BLOCK_SIZE
                recs = parser.parse_catalog_applicability_records_466(f, bo)
                all_cat_records.extend(recs)

        model_parts = [r for r in all_cat_records if r.model_code == vin_rec.model_code]
        print(f"  Total parts records for model: {len(model_parts)}")

        # Filter parts by spec logic and date range
        applicable_parts = []
        for rec in model_parts:
            sl = rec.spec_logic
            matched = eval_spec_logic(sl, codes)
            # ~7.4% of records have a variant prefix (A-H) prepended to the spec
            # e.g. "AS +W.WRX" = variant A + spec "S +W.WRX"
            if not matched and len(sl) >= 2 and sl[0] in 'ABCDEFGH':
                matched = eval_spec_logic(sl[1:], codes)
            if not matched:
                continue
            # Date field is YYYYMMDDYYYYMMDD (16 chars)
            start_date = rec.date[:6] if len(rec.date) >= 6 else ''
            end_date = rec.date[8:14] if len(rec.date) >= 14 else ''
            if not date_in_range(vehicle_date, start_date, end_date):
                continue
            applicable_parts.append(rec)

        print(f"  Applicable parts: {len(applicable_parts)}")

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

        # Build figure name lookup
        figname_lookup = {}
        for fn_rec in parse_figname_txt(FIGNAME_PATH):
            figname_lookup[fn_rec.figure_code] = fn_rec.description

        # Group applicable figure pages by (figure, page)
        by_fig_page = defaultdict(list)
        for rec in applicable:
            by_fig_page[(rec.figure, rec.figure_page)].append(rec)

        # Group parts by (figure, page) — parts with empty page are figure-wide
        parts_by_fig_page = defaultdict(list)
        parts_by_fig_all = defaultdict(list)  # parts with no page (apply to all pages)
        for rec in applicable_parts:
            if rec.figure_ref and len(rec.figure_ref) >= 4:
                fig_code = rec.figure_ref[1:]  # "A081" -> "081"
                if rec.figure_page.strip():
                    parts_by_fig_page[(fig_code, rec.figure_page)].append(rec)
                else:
                    parts_by_fig_all[fig_code].append(rec)

        def lookup_desc(fig, group_category, part_id):
            # Primary: PartGroupRecord185 keyed by (figure, callout code)
            code = group_category.split()[0]
            desc = part_desc_lookup.get((fig, code), '')
            if desc:
                return desc
            # Fallback: ITCA parts catalog by part number
            if parts_catalog and part_id:
                recs = parts_catalog.lookup(part_id)
                if not recs:
                    base = part_id[:10].strip()
                    if base:
                        recs = parts_catalog.lookup(base)
                if recs:
                    return recs[0].description
            return ''

        def dedup_parts(parts_list):
            seen = set()
            unique = []
            for p in parts_list:
                key = (p.group_category, p.part_id)
                if key not in seen:
                    seen.add(key)
                    unique.append(p)
            unique.sort(key=lambda r: r.group_category)
            return unique

        total_with_image = 0
        total_without_image = 0
        total_parts = 0

        # Group figures by category (184 → 183 hierarchy)
        category_figures = defaultdict(list)  # group_code -> [(fig, page), ...]
        uncategorized = []

        for fig, page in sorted(by_fig_page.keys()):
            fig183 = fig183_lookup.get(fig)
            if fig183:
                category_figures[fig183.fig_group_code].append((fig, page))
            else:
                uncategorized.append((fig, page))

        # Sort categories by group code
        sorted_cats = sorted(category_figures.keys())

        def print_figure(fig, page):
            nonlocal total_with_image, total_without_image, total_parts
            fig183 = fig183_lookup.get(fig)
            fig_desc = fig183.desc_en if fig183 else figname_lookup.get(fig, "")

            has_image = (fig, page) in fig89_lookup
            if has_image and fig89_lookup[(fig, page)].image_size > 0:
                total_with_image += 1
            else:
                total_without_image += 1

            img_flag = "" if has_image else "  (no img)"
            raw_label = fig89_lookup[(fig, page)].label if has_image else ""
            label = " ".join(raw_label.split()) if raw_label else ""
            label_str = f"  ({label})" if label else ""
            print(f"  FIG {fig}-{page} {fig_desc}{label_str}{img_flag}")

            # Merge page-specific parts + figure-wide parts
            combined = (parts_by_fig_page.get((fig, page), [])
                        + parts_by_fig_all.get(fig, []))
            unique_parts = dedup_parts(combined)

            for p in unique_parts:
                desc = lookup_desc(fig, p.group_category, p.part_id)
                extra = []
                if p.usage_notes:
                    extra.append(p.usage_notes)
                if p.part_spec:
                    extra.append(p.part_spec)
                extra_str = f"  [{', '.join(extra)}]" if extra else ""
                print(f"    {p.group_category:8s} {p.part_id:14s} {desc}{extra_str}")
            total_parts += len(unique_parts)

        for cat_code in sorted_cats:
            cat184 = fig184_lookup.get(cat_code)
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
