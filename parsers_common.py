"""Shared constants, parser creation, and VIN resolution for FAST2 tools."""

from ast import List
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from sffastus_parser import (
    CatalogApplicabilityRecord466,
    SffastusBlockParser,
    SffastusHeader,
    ModelIndexRecord288,
    ModelSpecRecord103,
    VINModelRecord,
    decode_block_pointer,
    parse_figname_txt,
    parse_itca_data,
    ItcaPartsCatalog,
    is_valid_subaru_vin,
    parse_model_index,
    iter_model_blocks,
)

SFCDUS2_PATH = Path("SFCDUS2/sffastus")
FIGNAME_PATH = "SFCDUS2/sffastpg/win/figname.txt"
ITCA_DATA = ["SFCDUS1/ITCA_DATA.TXT", "SFCDUS2/itca_data.txt", "SFCDUS3/itca_data.txt"]
BLOCK_SIZE = 2048


def create_parser():
    """Create a SffastusBlockParser with figure codes and ITCA parts catalog."""
    figure_codes = set()
    if Path(FIGNAME_PATH).exists():
        figure_codes = {r.figure_code for r in parse_figname_txt(FIGNAME_PATH)}
    itca_records = []
    for itca_path in ITCA_DATA:
        if Path(itca_path).exists():
            itca_records.extend(parse_itca_data(itca_path))
    parts_catalog = ItcaPartsCatalog(itca_records)
    return SffastusBlockParser(figure_codes=figure_codes, parts_catalog=parts_catalog)


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
    """Check if a pattern matches any code in the set. '#' is zero-or-one-char wildcard."""
    if pattern == 'ALL':
        return True
    if '#' in pattern:
        regex = '^' + re.escape(pattern).replace(r'\#', '.?') + '$'
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


@dataclass
class Vehicle:
    """Result of resolving a VIN: the vehicle identity and its spec codes."""
    vin_rec: VINModelRecord
    model_rec: ModelIndexRecord288
    spec: ModelSpecRecord103 | None
    codes: set
    vehicle_date: str


def get_vehicle_by_vin(f, parser, vin) -> Vehicle:
    """Look up VIN -> model index -> model spec -> vehicle codes.

    Returns Vehicle with all fields populated.
    Raises LookupError if VIN or model not found.
    """
    vin_rec = lookup_vin(f, parser, vin)
    if not vin_rec:
        raise LookupError(f"VIN {vin} not found in database")

    f.seek(0)
    header = SffastusHeader.parse(f.read(50))
    models = parse_model_index(f, header)
    model_rec = models.get(vin_rec.model_code)
    if not model_rec:
        raise LookupError(f"Model {vin_rec.model_code} not found in index")

    spec = None
    for bo in iter_model_blocks(model_rec, ModelSpecRecord103.ID):
        for s in parser.parse_model_spec_records_103(f, bo):
            if body_model_matches_applied(vin_rec.body_model, s.applied_model):
                spec = s
                break
        if spec:
            break

    codes = get_vehicle_codes(spec) if spec else set()
    vehicle_date = vin_rec.date1[:6]

    return Vehicle(vin_rec=vin_rec, model_rec=model_rec, spec=spec,
                       codes=codes, vehicle_date=vehicle_date)


def filter_cat466_parts(parts: List[CatalogApplicabilityRecord466], vehicle: Vehicle) -> List[tuple[CatalogApplicabilityRecord466, str]]:
    """Filter CatalogApplicabilityRecord466 records by vehicle spec and date.

    Returns list of (record, variant) tuples where variant is '' or 'A'-'H'.
    """
    result = []
    for rec in parts:
        sl = rec.spec_logic
        matched = eval_spec_logic(sl, vehicle.codes)
        variant = ''
        if not matched and len(sl) >= 2 and sl[0] in 'ABCDEFGH':
            if eval_spec_logic(sl[1:], vehicle.codes):
                matched = True
                variant = sl[0]
        if not matched:
            continue
        start_date = rec.date[:6] if len(rec.date) >= 6 else ''
        end_date = rec.date[8:14] if len(rec.date) >= 14 else ''
        if not date_in_range(vehicle.vehicle_date, start_date, end_date):
            continue
        result.append((rec, variant))
    return result
