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
from pathlib import Path

from sffastus_parser import (
    SffastusBlockParser,
    SffastusHeader,
    EngineSpecRecord230,
    FIGIllustrationPage89,
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

        # Group by figure
        from collections import defaultdict
        by_figure = defaultdict(list)
        for rec in applicable:
            by_figure[rec.figure].append(rec)

        total_with_image = 0
        total_without_image = 0

        for fig in sorted(by_figure.keys()):
            pages = by_figure[fig]
            pages.sort(key=lambda r: r.figure_page)

            fig_name = ""
            for fn_rec in parse_figname_txt(FIGNAME_PATH):
                if fn_rec.figure_code == fig:
                    fig_name = fn_rec.description
                    break

            page_strs = []
            for p in pages:
                key = (p.figure, p.figure_page)
                has_image = key in fig89_lookup
                if has_image:
                    fig89 = fig89_lookup[key]
                    if fig89.image_size > 0:
                        page_strs.append(p.figure_page)
                        total_with_image += 1
                    else:
                        page_strs.append(f"{p.figure_page}(no data)")
                        total_without_image += 1
                else:
                    page_strs.append(f"{p.figure_page}(no img)")
                    total_without_image += 1

            print(f"  Fig {fig}  {fig_name}")
            print(f"         pages: {', '.join(page_strs)}")

        print()
        print(f"Total: {len(by_figure)} figures, "
              f"{total_with_image} pages with images, "
              f"{total_without_image} pages without images")

        if bulletins:
            print(f"\nI&S Bulletins (page 40+): {len(bulletins)} entries across "
                  f"{len(set(b.figure for b in bulletins))} figures (not shown above)")


if __name__ == "__main__":
    main()
