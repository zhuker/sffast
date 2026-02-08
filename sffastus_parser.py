#!/usr/bin/env python3
"""
Subaru FAST2 sffastus File Structure Analyzer
Diagnostic tool to map the complete file structure including:
- VIN cross-reference data
- Potential image/drawing data
- Multilingual text strings
- Unknown binary regions
"""

import struct
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

SFFASTUS_PATH = "sffastus"

CHARSET = 'cp437'

# Valid Subaru VIN prefixes
# 4S3 - US manufactured (Subaru of Indiana Automotive)
# JF1 - Japan manufactured (Fuji Heavy Industries)
# JF2 - Japan manufactured (Fuji Heavy Industries, newer)
SUBARU_VIN_PREFIXES = ('4S3', '4S4', 'JF1', 'JF2')


def is_valid_subaru_vin(vin: str) -> bool:
    """
    Check if a string looks like a valid Subaru VIN.

    Valid Subaru VINs:
    - Start with '4S3' (US manufactured - Indiana)
    - Start with 'JF1' (Japan manufactured)
    - Start with 'JF2' (Japan manufactured, newer)
    - Are 17 characters long (standard VIN length)

    Args:
        vin: String to check

    Returns:
        True if it looks like a valid Subaru VIN
    """
    if not vin or len(vin) < 3:
        return False
    return vin.startswith(SUBARU_VIN_PREFIXES)


def is_valid_subaru_vin_strict(vin: str) -> bool:
    """
    Strict VIN validation - checks length and character set.

    Args:
        vin: String to check (should be 17 chars)

    Returns:
        True if it's a properly formatted Subaru VIN
    """
    if not is_valid_subaru_vin(vin):
        return False
    if len(vin) != 17:
        return False
    # VINs use alphanumeric chars except I, O, Q
    valid_chars = set('0123456789ABCDEFGHJKLMNPRSTUVWXYZ')
    return all(c in valid_chars for c in vin.upper())


def is_printable_text(data, threshold=0.7):
    """Check if data is mostly printable ASCII/extended ASCII text"""
    if not data:
        return False
    printable = sum(1 for b in data if 32 <= b <= 126 or b in (9, 10, 13, 0))
    return printable / len(data) >= threshold

def detect_language(text):
    """Try to detect language from text content"""
    text_lower = text.lower()
    if any(w in text_lower for w in ['the', 'and', 'for', 'assembly', 'complete']):
        return 'EN'
    if any(w in text_lower for w in ['und', 'für', 'der', 'die', 'das']):
        return 'DE'
    if any(w in text_lower for w in ['pour', 'avec', 'les', 'une']):
        return 'FR'
    if any(w in text_lower for w in ['para', 'con', 'los', 'una']):
        return 'ES'
    return 'UNK'

def find_image_signatures(data, offset):
    """Look for common image format signatures"""
    signatures = {
        b'BM': 'BMP',
        b'\x89PNG': 'PNG',
        b'\xff\xd8\xff': 'JPEG',
        b'GIF87a': 'GIF87',
        b'GIF89a': 'GIF89',
        b'\x00\x00\x01\x00': 'ICO',
        b'\x00\x00\x02\x00': 'CUR',
    }
    for sig, fmt in signatures.items():
        if data.startswith(sig):
            return fmt
    return None

def analyze_region(f, start, size, description=""):
    """Analyze a region of the file"""
    f.seek(start)
    data = f.read(min(size, 1024))  # Read up to 1KB for analysis

    result = {
        'start': start,
        'size': size,
        'description': description,
        'type': 'unknown',
        'sample': None,
        'details': {}
    }

    if not data:
        result['type'] = 'empty'
        return result

    # Check for null padding
    if all(b == 0 for b in data):
        result['type'] = 'null_padding'
        return result

    # Check for image signatures
    img_type = find_image_signatures(data, start)
    if img_type:
        result['type'] = f'image_{img_type}'
        return result

    # Check for text
    if is_printable_text(data, 0.8):
        result['type'] = 'text'
        try:
            text = data.decode(CHARSET).replace('\x00', ' ').strip()
            result['sample'] = text[:200]
            result['details']['language'] = detect_language(text)
        except:
            pass
        return result

    # Check for VIN-like patterns
    try:
        text = data.decode(CHARSET, errors='ignore')
        if any(prefix in text for prefix in SUBARU_VIN_PREFIXES):
            result['type'] = 'vin_data'
            return result
    except:
        pass

    # Mixed binary/text
    if is_printable_text(data, 0.3):
        result['type'] = 'mixed_binary_text'
        try:
            # Extract readable strings
            text = data.decode(CHARSET, errors='ignore')
            result['sample'] = text[:200]
        except:
            pass
    else:
        result['type'] = 'binary'

    return result

def scan_for_strings(f, start, end, min_length=10):
    """Scan region for readable strings"""
    strings = []
    f.seek(start)
    chunk_size = 64 * 1024  # 64KB chunks

    current_string = b''
    string_start = start

    while f.tell() < end:
        chunk = f.read(min(chunk_size, end - f.tell()))
        if not chunk:
            break

        for i, b in enumerate(chunk):
            if 32 <= b <= 126:
                if not current_string:
                    string_start = f.tell() - len(chunk) + i
                current_string += bytes([b])
            else:
                if len(current_string) >= min_length:
                    try:
                        s = current_string.decode(CHARSET)
                        strings.append((string_start, s))
                    except:
                        pass
                current_string = b''

    return strings

def scan_for_patterns(f, file_size):
    """Scan the file for repeating patterns that might indicate record structures"""
    patterns = defaultdict(int)

    # Sample at various offsets
    sample_points = [
        0x800,      # Known VIN data start
        0x100000,   # 1MB
        0x500000,   # 5MB
        0x1000000,  # 16MB
        0x5000000,  # 80MB
        0x10000000, # 256MB
        0x15000000, # 336MB
    ]

    print("\n=== Pattern Analysis at Sample Points ===")
    for offset in sample_points:
        if offset >= file_size:
            continue
        f.seek(offset)
        data = f.read(512)

        print(f"\nOffset 0x{offset:08X} ({offset / 1024 / 1024:.1f} MB):")

        # Check data type
        region = analyze_region(f, offset, 512)
        print(f"  Type: {region['type']}")

        if region['sample']:
            sample = region['sample'][:100].replace('\n', '\\n').replace('\r', '\\r')
            print(f"  Sample: {sample}")

        # Hex dump first 64 bytes
        f.seek(offset)
        hex_data = f.read(64)
        hex_str = ' '.join(f'{b:02x}' for b in hex_data[:32])
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in hex_data[:32])
        print(f"  Hex: {hex_str}")
        print(f"  ASCII: {ascii_str}")

def find_section_boundaries(f, file_size):
    """Find boundaries between different data sections"""
    print("\n=== Section Boundary Detection ===")

    boundaries = []
    last_type = None
    chunk_size = 0x10000  # 64KB chunks

    for offset in range(0, min(file_size, 0x20000000), chunk_size):  # Scan up to 512MB
        region = analyze_region(f, offset, chunk_size)

        if region['type'] != last_type:
            boundaries.append({
                'offset': offset,
                'type': region['type'],
                'sample': region.get('sample', '')[:50] if region.get('sample') else ''
            })
            last_type = region['type']

            # Print as we find them
            print(f"  0x{offset:08X} ({offset/1024/1024:6.1f} MB): {region['type']}")

    return boundaries

def parse_model_table(f):
    """Parse the model code table at 0x32"""
    print("\n=== Model Code Table (0x32) ===")

    f.seek(0x32)
    models = []

    for i in range(10):
        entry = f.read(10)
        if len(entry) < 10:
            break

        code = entry[:6].decode(CHARSET).strip()
        pointer = struct.unpack('<I', entry[6:10])[0]

        if code and code[0].isalnum():
            models.append((code, pointer))
            print(f"  {code:6s} -> 0x{pointer:08X}")

    return models

def analyze_vin_section(f, start, count=10):
    """Analyze VIN records at given offset"""
    print(f"\n=== VIN Records at 0x{start:08X} ===")

    f.seek(start)

    for i in range(count):
        record = f.read(38)
        if len(record) < 38:
            break

        try:
            vin1 = record[0:17].decode(CHARSET).strip('\x00')
            vin2 = record[17:34].decode(CHARSET).strip('\x00')
            ptr = struct.unpack('<I', record[34:38])[0]

            if is_valid_subaru_vin(vin1):
                print(f"  Record {i}: {vin1} - {vin2} -> 0x{ptr:08X}")
        except:
            print(f"  Record {i}: <parse error>")

def search_for_images(f, file_size):
    """Search entire file for image signatures"""
    print("\n=== Searching for Embedded Images ===")

    signatures = [
        (b'BM', 'BMP'),
        (b'\x89PNG\r\n\x1a\n', 'PNG'),
        (b'\xff\xd8\xff', 'JPEG'),
    ]

    images_found = []
    chunk_size = 1024 * 1024  # 1MB chunks

    for chunk_start in range(0, file_size, chunk_size):
        f.seek(chunk_start)
        chunk = f.read(chunk_size + 16)  # Overlap for boundary cases

        for sig, fmt in signatures:
            pos = 0
            while True:
                pos = chunk.find(sig, pos)
                if pos == -1:
                    break

                abs_pos = chunk_start + pos
                images_found.append((abs_pos, fmt))
                print(f"  Found {fmt} at 0x{abs_pos:08X} ({abs_pos/1024/1024:.1f} MB)")
                pos += 1

    return images_found

def analyze_text_regions(f, file_size):
    """Find and analyze text regions with multilingual content"""
    print("\n=== Multilingual Text Search ===")

    # Look for known multilingual patterns
    search_terms = [
        b'ENGINE',
        b'MOTOR',  # German
        b'MOTEUR', # French
        b'CLUTCH',
        b'KUPPLUNG', # German
        b'EMBRAYAGE', # French
    ]

    chunk_size = 10 * 1024 * 1024  # 10MB chunks
    found_regions = []

    for chunk_start in range(0, file_size, chunk_size):
        f.seek(chunk_start)
        chunk = f.read(chunk_size)

        for term in search_terms:
            pos = chunk.find(term)
            if pos != -1:
                abs_pos = chunk_start + pos
                # Get context
                context_start = max(0, pos - 50)
                context_end = min(len(chunk), pos + 100)
                context = chunk[context_start:context_end]

                try:
                    context_str = context.decode(CHARSET, errors='replace')
                    # Clean up for display
                    context_str = ''.join(c if 32 <= ord(c) <= 126 else '.' for c in context_str)

                    if abs_pos not in [r[0] for r in found_regions]:
                        found_regions.append((abs_pos, term.decode(), context_str))
                        print(f"  0x{abs_pos:08X}: Found '{term.decode()}' - {context_str[:80]}")
                except:
                    pass

    return found_regions

def extract_record_at_offset(f, offset, record_size=256):
    """Extract and display a record at a given offset"""
    f.seek(offset)
    data = f.read(record_size)

    print(f"\n=== Record at 0x{offset:08X} ===")

    # Hex dump
    for i in range(0, len(data), 16):
        hex_part = ' '.join(f'{b:02x}' for b in data[i:i+16])
        ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data[i:i+16])
        print(f"  {offset+i:08X}: {hex_part:48s} {ascii_part}")

    return data


@dataclass
class VINRecord:
    """Represents a VIN range record from sffastus (38 bytes)

    Used for VIN range lookup - maps VIN ranges to section pointers.
    """
    offset: int
    vin_start: str
    vin_end: str
    section: int
    index: int
    raw_data: bytes


@dataclass
class VINModelRecord:
    """Represents a VIN-Model detail record from sffastus (69 bytes)

    Contains full vehicle specification for a single VIN.

    Structure:
        0x00 (17): VIN
        0x11 (1):  Null terminator
        0x12 (1):  Flag (typically 0x01)
        0x13 (6):  Model Code (e.g., "S12   ")
        0x19 (7):  Body Model (e.g., "SHMDY6S")
        0x20 (9):  Spec/Option Code (e.g., "G1UH20NT ")
        0x29 (2):  Binary flags
        0x2B (8):  Date 1 (YYYYMMDD)
        0x33 (8):  Date 2 (YYYYMMDD)
        0x3B (8):  Date 3 (YYYYMMDD)
        0x43 (2):  Suffix Code (e.g., "U5")
    """
    offset: int
    vin: str
    flag: int
    model_code: str
    body_model: str
    spec_code: str
    binary_flags: bytes
    date1: str
    date2: str
    date3: str
    suffix: str
    raw_data: bytes


@dataclass
class MultilingualPartRecord:
    """Represents a multilingual part name record from sffastus (192 bytes)

    Contains part names in 4 languages: English, German, French, Spanish.
    Encoding: CP437

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (6):  Part Code (e.g., "0951S ")
        0x0C (5):  Figure Code (e.g., " 421 ")
        0x11 (3):  Index (e.g., " 1 ", "11 ")
        0x14 (40): English Name
        0x3C (40): German Name
        0x64 (40): French Name
        0x8C (40): Spanish Name
        0xB4 (12): Trailer (binary flags/metadata)
    """
    offset: int
    model_code: str
    part_code: str
    figure_code: str
    index: str
    name_en: str
    name_de: str
    name_fr: str
    name_es: str
    trailer: bytes
    raw_data: bytes


@dataclass
class CodeIndexRecord33:
    """Represents a code/ID index record from sffastus (33 bytes)

    Located at 0x0DE42800+
    Encoding: CP437

    Structure:
        0x00 (6): Model Code (e.g., "B11   ")
        0x06 (1): Category (single byte, e.g., 0x31='1', 0x30='0')
        0x07 (15): Size/Variant/Modifier Code (e.g., "ASSEMBLY", "RIGHT", "FRONT", "ST")
        0x16 (7): Part Code (e.g., "28391  ", "28491B ")
        0x1D (4): Metadata/Flags

    Total: 33 bytes (6+1+15+7+4)

    Note: The 15-byte size/variant field contains meaningful multilingual data
    such as part qualifiers (ASSEMBLY, CONJUNTO, ENSEMBLE), directional terms
    (RIGHT, LEFT, FRONT), and size codes (ST, 5X20, +)). Only 2.6% of records
    have this field filled with spaces.

    The 7-byte part code field is space-padded when codes are shorter than 7 chars,
    which is why it often ends with a space (92.5% of records).
    """
    offset: int
    model_code: str
    category: int  # 1-byte category
    size_variant: str  # 15 bytes - size/variant/modifier code (NOT padding!)
    code: str  # 7-byte part code (space-padded)
    metadata: bytes  # 4 bytes of metadata
    raw_data: bytes

    @staticmethod
    def parse_33(data: bytes, offset: int = 0):
        """Parse a 33-byte code index record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace')

        # Don't strip the size_variant field to preserve all data
        size_variant_raw = data[7:22].decode(CHARSET, errors='replace')

        return CodeIndexRecord33(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]).strip(),
            category=data[6],  # Single byte
            size_variant=size_variant_raw,  # Keep as-is, don't strip - 15 bytes
            code=clean(data[22:29]).strip(),  # 7 bytes (was 6 + separator)
            metadata=data[29:33],  # 4 bytes
        )


def is_code_index_record_block_33(data: bytes) -> bool:
    """
    Check if data looks like a 33-byte code index record block.

    Detection heuristics:
    - Consistent model codes every 33 bytes.
    """
    if len(data) < 33:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 66:  # 33 * 2
            if not is_valid_model_code(data[33:33+6]):
                return False

        return True
    except:
        return False


@dataclass
class GlossaryRecord28:
    """Represents a glossary/terminology record from sffastus (28 bytes)

    Located at 0x0DE23800+
    Encoding: CP437

    Structure:
        0x00 (6): Model Code (e.g., "B11   ")
        0x06 (1): Category/Type byte
        0x07 (17): Term/Text (e.g., "AUTO", "AXLE", "5X20")
        0x18 (4): Metadata/Flags
    """
    offset: int
    model_code: str
    category: int  # Single byte category
    term: str
    metadata: bytes  # 4 bytes of metadata
    raw_data: bytes

    @staticmethod
    def parse_28(data: bytes, offset: int = 0):
        """Parse a 28-byte glossary record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return GlossaryRecord28(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            category=data[6],  # Single byte
            term=clean(data[7:24]),  # 17 bytes
            metadata=data[24:28],  # 4 bytes
        )


def is_glossary_record_block_28(data: bytes) -> bool:
    """
    Check if data looks like a 28-byte glossary record block.

    Detection heuristics:
    - Consistent model codes every 28 bytes.
    """
    if len(data) < 28:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 56:  # 28 * 2
            if not is_valid_model_code(data[28:28+6]):
                return False

        return True
    except:
        return False


@dataclass
class ColorRecord91:
    """Represents a color/paint code record from sffastus (91 bytes)

    Located at 0x0DE1F800+
    Encoding: CP437

    Structure:
        0x00 (6): Model Code (e.g., "B11   ")
        0x06 (6): Paint Code (e.g., "AC 62 ")
        0x0C (20): Color Name EN (e.g., "SILVER M")
        0x20 (20): Color Name DE (e.g., "SILBER M")
        0x34 (20): Color Name FR (e.g., "ARGENT M")
        0x48 (20): Color Name ES (e.g., "PLATA M")
        0x5C (15): Padding/Reserved
    """
    offset: int
    model_code: str
    paint_code: str
    color_name_en: str
    color_name_de: str
    color_name_fr: str
    color_name_es: str
    raw_data: bytes

    @staticmethod
    def parse_91(data: bytes, offset: int = 0):
        """Parse a 91-byte color record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return ColorRecord91(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            paint_code=clean(data[6:10]),  # 4 bytes
            color_name_en=clean(data[10:30]),  # 20 bytes
            color_name_de=clean(data[30:50]),  # 20 bytes
            color_name_fr=clean(data[50:70]),  # 20 bytes
            color_name_es=clean(data[70:90]),  # 20 bytes
        )


def is_color_record_block_91(data: bytes) -> bool:
    """
    Check if data looks like a 91-byte color record block.

    Detection heuristics:
    - Consistent model codes every 91 bytes.
    """
    if len(data) < 91:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 182:  # 91 * 2
            if not is_valid_model_code(data[91:91+6]):
                return False

        return True
    except:
        return False


@dataclass
class FIGIllustrationRecord183:
    """Represents a FIG illustration description record from sffastus (183 bytes)

    Located at 0x0DF9B000+
    Encoding: CP437

    Contains multilingual descriptions for individual FIG illustrations.
    These are the illustration names shown in the illustrated index.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (2):  FIG Group Code (e.g., "0A", "1B")
        0x08 (40): English Description (often prefixed with index like "010")
        0x30 (40): German Description (Deutsch)
        0x58 (40): French Description (Français)
        0x80 (40): Spanish Description (Español)
        0xA8 (15): Trailer/Metadata
    """
    offset: int
    model_code: str
    fig_group_code: str
    fig_group_code2: str
    desc_en: str
    desc_de: str
    desc_fr: str
    desc_es: str
    trailer: bytes
    raw_data: bytes

    @staticmethod
    def parse_183(data: bytes, offset: int = 0):
        """Parse a 183-byte FIG illustration record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace')

        return FIGIllustrationRecord183(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            fig_group_code=clean(data[6:8]),
            fig_group_code2=clean(data[8:8+5]),
            desc_en=clean(data[8+5:48+5]),
            desc_de=clean(data[48+5:88+5]),
            desc_fr=clean(data[88+5:128+5]),
            desc_es=clean(data[128+5:168+5]),
            trailer=data[168+5:183],
        )


@dataclass
class EngineSpecRecord230:
    """Represents a 230-byte engine specification record from sffastus

    Located at 0x0DFB1000+
    Encoding: CP437

    Contains engine types and production periods.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (2):  Group Code (usually "00")
        0x08 (40): Description (EN)
        0x30 (40): Description (DE)
        0x58 (5):  Padding
        0x5D (6):  Start Date (YYYYMM)
        0x63 (6):  End Date (YYYYMM)
        0x69 (125): Trailer/Metadata
    """
    offset: int
    model_code: str
    figure: str
    figure_page: str
    applicable_model: str
    start_date: str
    end_date: str
    trailer: bytes
    raw_data: bytes

    @staticmethod
    def parse_230(data: bytes, offset: int = 0):
        """Parse a 230-byte engine specification record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return EngineSpecRecord230(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            figure=clean(data[6:9]),
            figure_page=clean(data[9:9 + 4]),
            applicable_model=clean(data[9 + 4:88]),
            start_date=clean(data[93:99]),
            end_date=clean(data[99:105]),
            trailer=data[105:230],
        )


def is_engine_spec_block_230(data: bytes) -> bool:
    """
    Check if data looks like a 230-byte engine specification block.

    Detection heuristics:
    - Consistent model codes every 230 bytes.
    - Numeric date patterns at offset 93.
    """
    if len(data) < 230:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False
            
        # Check first record date fields (offset 93 is Start Date)
        start_date = data[93:99].decode(CHARSET, errors='replace').strip()
        if start_date and not start_date.isdigit():
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 230*2:
            if not is_valid_model_code(data[230:230+6]):
                return False

        return True
    except:
        return False


@dataclass
class FIGIllustrationPage89:
    """Represents a FIG illustration page/sub-index record from sffastus (89 bytes)

    Located at 0x0DFA5000+
    Encoding: CP437

    Contains sub-indexing for FIG illustrations, mapping specific FIG indices 
    to page numbers and labels.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (3):  FIG Index (e.g., "002")
        0x09 (2):  Padding (usually spaces)
        0x0B (2):  Page Index (e.g., "01")
        0x0D (40): Label (e.g., "VALVE")
        0x35 (36): Trailer/Metadata
    """
    offset: int
    model_code: str
    fig_index: str
    page_index: str
    label: str
    trailer: bytes
    raw_data: bytes

    @staticmethod
    def parse_89(data: bytes, offset: int = 0):
        """Parse an 89-byte FIG illustration page record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return FIGIllustrationPage89(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            fig_index=clean(data[6:9]),
            page_index=clean(data[11:13]),
            label=clean(data[13:53]),
            trailer=data[53:89],
        )


@dataclass
class InventoryRecord199:
    """Represents a 199-byte inventory/part name record from sffastus

    Located at 0x0E147000+
    Encoding: CP437

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (7):  Part Code (e.g., "004  02")
        0x0D (10): Extra Code/ID (e.g., "037018200")
        0x17 (40): English Name
        0x3F (40): German Name
        0x67 (40): French Name
        0x8F (40): Spanish Name
        0xB7 (16): Trailer/Metadata
    """
    offset: int
    model_code: str
    figure: str
    figure_page: str
    part_number: str
    unknown: bytes
    part_code: str
    name_en: str
    name_de: str
    name_fr: str
    name_es: str
    trailer: bytes
    raw_data: bytes

    @staticmethod
    def parse_199(data: bytes, offset: int = 0):
        """Parse a 199-byte inventory record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        fix_offset=16
        return InventoryRecord199(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            figure=clean(data[6:6+5]),
            figure_page=clean(data[6+5:13]),
            part_number=clean(data[13:23+5]),
            unknown=data[23+5:23+5+4],
            part_code=clean(data[23+5+4:23+fix_offset]),
            name_en=clean(data[23+fix_offset:63+fix_offset]),
            name_de=clean(data[63+fix_offset:103+fix_offset]),
            name_fr=clean(data[103+fix_offset:143+fix_offset]),
            name_es=clean(data[143+fix_offset:183+fix_offset]),
            trailer=data[183+fix_offset:199],
        )


@dataclass
class MultilingualPartRecord182:
    """Represents a 182-byte multilingual part name record from sffastus

    Located at 0x0E73B000+
    Encoding: CP437

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (7):  Part Code (e.g., "10101  ")
        0x0D (5):  Figure Index (e.g., "010  ")
        0x12 (40): English Name
        0x3A (40): German Name
        0x62 (40): French Name
        0x8A (40): Spanish Name
        0xB2 (4):  Trailer/Metadata (e.g., [0x19, 0x1E, Index, 0x00])
    """
    offset: int
    model_code: str
    part_code: str
    figure: str
    name_en: str
    name_de: str
    name_fr: str
    name_es: str
    trailer: bytes
    raw_data: bytes

    @staticmethod
    def parse_182(data: bytes, offset: int = 0):
        """Parse a 182-byte multilingual part record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return MultilingualPartRecord182(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            part_code=clean(data[6:13]),
            figure=clean(data[13:18]),
            name_en=clean(data[18:58]),
            name_de=clean(data[58:98]),
            name_fr=clean(data[98:138]),
            name_es=clean(data[138:178]),
            trailer=data[178:182],
        )


def is_multilingual_part_block_182(data: bytes) -> bool:
    """
    Check if data looks like a 182-byte multilingual part record block.
    """
    if len(data) < 182:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # Check for the separator pattern nearby (often at +178 or similar)
        # Note: Separators may not be at fixed offsets if record length varies slightly,
        # but for a block-based check we look at the next potential record start.
        if len(data) >= 182*2:
             # Next record might start with signature or model code
             if not is_valid_model_code(data[182:182+6]):
                 return False

        return True
    except:
        return False


def is_inventory_block_199(data: bytes) -> bool:
    """
    Check if data looks like a 199-byte inventory record block.
    """
    if len(data) < 199:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 199*2:
            if not is_valid_model_code(data[199:199+6]):
                return False

        return True
    except:
        return False


@dataclass
class PartGroupRecord185:
    """Represents a 185-byte part group description record from sffastus

    Located at 0x0DFD3000+
    Encoding: CP437

    Contains descriptive names for part groups.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (3):  Group Index (e.g., "001")
        0x09 (40): Description (EN) - 12B code + 28B English label
        0x31 (40): Description (DE)
        0x59 (40): Description (FR)
        0x81 (40): Description (ES)
        0xA9 (16): Trailer/Metadata
    """
    offset: int
    model_code: str
    figure: str
    figure_page: str
    part_code: str
    desc_en: str
    desc_de: str
    desc_fr: str
    desc_es: str
    trailer: bytes
    raw_data: bytes

    @staticmethod
    def parse_185(data: bytes, offset: int = 0):
        """Parse a 185-byte part group description record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return PartGroupRecord185(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            figure=clean(data[6:9]),
            figure_page=clean(data[9:13]),
            part_code=clean(data[13:9+12]),
            desc_en=clean(data[9+12:49+12]),
            desc_de=clean(data[49+12:89+12]),
            desc_fr=clean(data[89+12:129+12]),
            desc_es=clean(data[129+12:169+12]),
            trailer=data[169+12:185],
        )


def is_part_group_block_185(data: bytes) -> bool:
    """
    Check if data looks like a 185-byte part group block.

    Detection heuristics:
    - Consistent model codes every 185 bytes.
    - Sequential numeric patterns in group_index.
    """
    if len(data) < 185:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False
            
        # Check group index is numeric
        idx = data[6:9].decode(CHARSET, errors='replace').strip()
        if idx and not idx.isdigit():
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 185*2:
            if not is_valid_model_code(data[185:185+6]):
                return False

        return True
    except:
        return False


def is_fig_illustration_page_block_89(data: bytes) -> bool:
    """
    Check if data looks like an 89-byte FIG illustration page record block.

    Detection heuristics:
    - Consistent model codes every 89 bytes.
    - Numeric patterns in fig_index and page_index fields.
    """
    if len(data) < 89:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False
            
        # Check first record numeric fields
        fig_idx = data[6:9].decode(CHARSET, errors='replace').strip()
        page_idx = data[11:13].decode(CHARSET, errors='replace').strip()
        if not (fig_idx.isdigit() and page_idx.isdigit()):
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 89*2:
            if not is_valid_model_code(data[89:89+6]):
                return False

        return True
    except:
        return False


def is_fig_illustration_block_183(data: bytes) -> bool:
    """
    Check if data looks like a 183-byte FIG illustration record block.

    Detection heuristics:
    - Consistent model codes every 183 bytes.
    - FIG group code pattern (2 chars: digit + letter/digit)
    """
    if len(data) < 183:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False
        # If we have at least 2 records, check the second one too
        if len(data) >= 183*2:
            if not is_valid_model_code(data[183:183+6]):
                return False

        return True
    except:
        return False


@dataclass
class VariantGlossaryRecord81:
    """Represents a variant glossary record from sffastus (81 bytes)

    Located at 0x0E6E9000+
    Encoding: CP437

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (15): Variant Code (e.g., "2200CC", "SW", "TW")
        0x15 (60): Description (e.g., "ENGINE DISPLACEMENT : 2200CC")
    """
    offset: int
    model_code: str
    variant_code: str
    description: str
    raw_data: bytes

    @staticmethod
    def parse_81(data: bytes, offset: int = 0):
        """Parse an 81-byte variant glossary record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return VariantGlossaryRecord81(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            variant_code=clean(data[6:21]),
            description=clean(data[21:81]),
        )


def is_variant_glossary_block_81(data: bytes) -> bool:
    """
    Check if data looks like an 81-byte variant glossary record block.

    Detection heuristics:
    - Consistent model codes every 81 bytes.
    - Handles potential leading padding at start of block.
    """
    if len(data) < 162:  # Need at least 2 records to verify consistency
        return False

    try:
        # Check common offsets for model code (0, 2, 4...)
        for start_offset in range(10):
            if is_valid_model_code(data[start_offset:start_offset+6]):
                # Verify consistency with next record
                if is_valid_model_code(data[start_offset+81:start_offset+81+6]):
                    return True
        return False
    except:
        return False


@dataclass
class FigureIndexRecord22:
    """Represents a 22-byte figure index record from sffastus

    Located at 0x0E75D800+
    Encoding: CHARSET

    Structure:
        0x00 (6): Model Code (e.g., "B11   ")
        0x06 (5): Figure (e.g., "003  ")
        0x0B (7): Item Index (e.g., "01004  ")
        0x12 (4): Metadata/Flags
    """
    offset: int
    model_code: str
    figure: str
    item_index: str
    metadata: bytes
    raw_data: bytes

    @staticmethod
    def parse_22(data: bytes, offset: int = 0):
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace')

        return FigureIndexRecord22(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            figure=clean(data[6:11]),
            item_index=clean(data[11:18]),
            metadata=data[18:22],
        )


@dataclass
class SpecMappingRecord22:
    """Represents a 22-byte spec mapping record from sffastus

    Located at 0x17BA7000+
    Encoding: CHARSET

    Structure:
        0x00 (6): Model Code (e.g., "G11   ")
        0x06 (5): Code (e.g., "AAICN")
        0x0B (11): Description (e.g., "OFOR A/C   ")
    """
    offset: int
    model_code: str
    option_code: str
    description: str
    raw_data: bytes

    @staticmethod
    def parse_22(data: bytes, offset: int = 0):
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace')

        return SpecMappingRecord22(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            option_code=clean(data[6:11]),
            description=clean(data[11:22]),
        )


def is_figure_index_block_22(data: bytes) -> bool:
    """
    Check if data looks like a 22-byte figure index record block.
    Heuristic: figure field (6-11) contains digits.
    """
    if len(data) < 44:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # First record figure code
        figure = data[6:11].decode(CHARSET, errors='replace')
        if not any(c.isdigit() for c in figure):
            return False

        # Verify second record
        if not is_valid_model_code(data[22:28]):
            return False

        return True
    except:
        return False


def is_spec_mapping_block_22(data: bytes) -> bool:
    """
    Check if data looks like a 22-byte spec mapping record block.
    Heuristic: figure field (6-11) is non-numeric/alpha.
    """
    if len(data) < 44:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # Code field (6-11) should be alpha if it's the spec mapping flavor
        # (Based on "AAICN" example)
        code = data[6:11].decode(CHARSET, errors='replace')
        if any(c.isdigit() for c in code):
            # If it has digits, it might be the numeric FigureIndex type instead
            return False

        # Description should have text
        desc = data[11:22].decode(CHARSET, errors='replace')
        if not any(c.isalpha() for c in desc):
             return False

        # Verify second record
        if not is_valid_model_code(data[22:28]):
            return False

        return True
    except:
        return False


@dataclass
class FIGGroupCategoryRecord184:
    """Represents a FIG group category description record from sffastus (184 bytes)

    Located at 0x0DF9A000+
    Encoding: CP437

    Contains multilingual descriptions for FIG group codes (0A-9B).
    These are the category names shown in the Windows application.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (2):  FIG Group Code (e.g., "0A", "1B", "9B")
        0x08 (40): English Description
        0x30 (40): German Description (Deutsch)
        0x58 (40): French Description (Français)
        0x80 (40): Spanish Description (Español)
        0xA8 (16): Trailer/Metadata
    """
    offset: int
    model_code: str
    fig_group_code: str
    desc_en: str
    desc_de: str
    desc_fr: str
    desc_es: str
    trailer: bytes
    raw_data: bytes

    @staticmethod
    def parse_184(data: bytes, offset: int = 0):
        """Parse a 184-byte FIG group category record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return FIGGroupCategoryRecord184(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            fig_group_code=clean(data[6:8]),
            desc_en=clean(data[8:48]),
            desc_de=clean(data[48:88]),
            desc_fr=clean(data[88:128]),
            desc_es=clean(data[128:168]),
            trailer=data[168:184],
        )


def is_fig_group_category_block_184(data: bytes) -> bool:
    """
    Check if data looks like a 184-byte FIG group category record block.

    Detection heuristics:
    - Consistent model codes every 184 bytes.
    - FIG group code pattern (2 chars: digit + letter)
    - English description contains expected keywords
    """
    if len(data) < 184:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False
        # If we have at least 2 records, check the second one too
        if len(data) >= 184*2:
            if not is_valid_model_code(data[184*2:184*2+6]):
                return False

        return True
    except:
        return False


@dataclass
class CatalogApplicabilityRecord466:
    offset: int

    model_code: str
    group_category: str
    part_id: str

    date_flag: str
    date: str

    spec_logic: str
    usage_notes: str

    internal_flags: str
    unknown: bytes
    raw_data: bytes = field(repr=False)


    @property
    def is_manual_only(self) -> bool:
        """Helper: Checks if spec logic restricts to Manual Transmission."""
        return '.MT' in self.spec_logic or 'MT.' in self.spec_logic

    @staticmethod
    def parse_466(data: bytes, offset: int = 0):
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return CatalogApplicabilityRecord466(
            # Identification
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            group_category=clean(data[6:11]),
            part_id=clean(data[13:23]),

            # Validity Range
            date_flag=clean(data[28:29]),
            date=clean(data[29:46]),

            # The Logic String (Fixed window at 0x40/64 decimal)
            spec_logic=clean(data[64:128]),

            # Notes / Constraints (Fixed window at 0x80/128 decimal)
            usage_notes=clean(data[128:160]),

            # Internal pointers (Text based integers)
            internal_flags=clean(data[160:180]),

            # The rest is the binary feature mask
            unknown=data[180:],
        )

def is_catalog_applicability_block_466(data: bytes) -> bool:
    """
    Check if data looks like a 466-byte catalog applicability record block.

    Detection heuristics:
    - Consistent model codes every 466 bytes.
    """
    if len(data) < 466:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 932:  # 466 * 2
            if not is_valid_model_code(data[466:466+6]):
                return False

        return True
    except:
        return False

@dataclass
class ModelSpecRecord103:
    """
    Parsed representation of a Subaru Applied Model string.
    Handles variable-length fields found in B11, B13, and G11 chassis codes.
    """
    # Metadata
    offset: int
    raw_data: bytes

    # Identification
    model_code: str  # e.g., "B11", "G11"
    production_period: str  # e.g., "0111996..."
    applied_model: str  # e.g., "BD7-Y3M", "GDF-YEH"

    # Specs
    body_config: str  # e.g., "S" (Sedan), "WOBK" (Wagon Outback)
    engine: str  # e.g., "EJ22EZ", "257", "255"
    drivetrain: str  # e.g., "F4WD", "4W"
    transmission: str  # e.g., "MT", "5MT", "6MT"

    # Trim & Options
    trim_level: str  # e.g., "L", "25GT", "STI"
    spec_option: str  # e.g., "N/S" (Non-Sunroof), "YAD"

    # Unused / Reserved (kept for preservation)
    _padding: str

    @property
    def is_turbo(self) -> bool:
        """Heuristic check for turbo engines (EJ255, EJ257, or 'T' code)."""
        turbo_codes = {'255', '257', '205', '207'}
        return self.engine in turbo_codes or 'T' in self.engine

    @property
    def is_manual(self) -> bool:
        return 'MT' in self.transmission

    @staticmethod
    def parse_103(data: bytes, offset: int = 0):
        """
        Parses fixed-width Subaru model data, automatically stripping whitespace padding.
        Uses wider windows to capture variable length fields (e.g. '5MT' vs 'MT').
        """

        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        # Parsing Logic based on observed B11/G11/B13 offsets
        return ModelSpecRecord103(
            offset=offset,
            raw_data=data,

            # Fixed Header
            model_code=clean(data[0:6]),
            production_period=clean(data[6:21]),
            applied_model=clean(data[21:39]),  # Expanded to catch long codes

            # Variable Specs (Offsets adjusted for wider capture)
            body_config=clean(data[39:47]),  # Window for "S", "W", "WOBK"
            engine=clean(data[47:55]),  # Window for "EJ22EZ", "257"
            drivetrain=clean(data[55:63]),  # Window for "F4WD", "4W"
            transmission=clean(data[63:71]),  # Window for "MT", "5MT", "6MT"
            trim_level=clean(data[71:79]),  # Window for "L", "STI", "25GT"
            spec_option=clean(data[79:85]),  # Window for "N/S"

            _padding=clean(data[85:])
        )


def is_model_spec_block_103(data: bytes) -> bool:
    """
    Check if data looks like a 103-byte model spec record block.

    Detection heuristics:
    - Consistent model codes every 103 bytes.
    """
    if len(data) < 103:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 206:
            if not is_valid_model_code(data[103:103+6]):
                return False

        return True
    except:
        return False


@dataclass
class PartRangeRecord24:
    """Represents a part number range record from sffastus (24 bytes)

    Located at 0x0CD42800+
    Encoding: CP437

    Structure:
        0x00 (6): Model Code (e.g., "B11   ")
        0x06 (7): Part Number Start (e.g., "11711  ")
        0x0D (7): Part Number End (e.g., "12024  ")
        0x14 (4): Metadata (e.g., [0x17, 0x19, Index, 0x00])
    """
    offset: int
    model_code: str
    part_start: str
    part_end: str
    metadata: bytes
    raw_data: bytes


def is_part_range_block_24(data: bytes) -> bool:
    """
    Check if data looks like a 24-byte part range record block.

    Detection heuristics:
    - Starts with valid model code (6 bytes)
    - If multiple records, next record also starts with valid model code
    """
    if len(data) < 24:
        return False

    try:
        # Check first record model code
        if not is_valid_model_code(data[0:6]):
            return False

        # If we have at least 2 records, check the second one too
        if len(data) >= 48:
            if not is_valid_model_code(data[24:30]):
                return False

        return True
    except:
        return False


@dataclass
class ModelIndexRecord288:
    """Represents a model index record from sffastus (288 bytes)

    Located at 0x13000+
    Encoding: CP437

    Structure:
        0x00 (6):   Model Code (e.g., "B11   ", "W10   ")
        0x06 (180): Block Index Array (45 entries of 4 bytes each)
        0xBA (2):   Series Code (e.g., "B ", "G ")
        0xBC (15):  Model Name (e.g., "LEGACY         ")
        0xCB (6):   Start Date (YYYYMM, e.g., "199601")
        0xD1 (6):   End Date (YYYYMM, e.g., "199805")
        0xD7 (14):  Features/Flags
        0xE5 (8):   Category 1 (e.g., "BODY    ")
        0xED (8):   Category 2 (e.g., "ENGINE  ")
        0xF5 (8):   Category 3 (e.g., "TRAIN   ")
        0xFD (8):   Category 4 (e.g., "MISSION ")
        0x105 (8):  Category 5 (e.g., "GRADE   ")
        0x10D (8):  Category 6 (e.g., "SUS     ")
        0x115 (11): Trailer/Padding
    """
    offset: int
    model_code: str
    block_index_array: bytes  # 180 bytes - array of 4-byte entries
    series_code: str
    model_name: str
    start_date: str
    end_date: str
    features: str
    category1: str
    category2: str
    category3: str
    category4: str
    category5: str
    category6: str
    trailer: bytes
    raw_data: bytes

    @staticmethod
    def parse_288(data: bytes, offset: int = 0):
        """Parse a 288-byte model index record."""
        def clean(b: bytes) -> str:
            return b.decode(CHARSET, errors='replace').strip()

        return ModelIndexRecord288(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            block_index_array=data[6:186],  # 180 bytes
            series_code=clean(data[186:188]),  # 0xBA
            model_name=clean(data[188:203]),  # 0xBC
            start_date=clean(data[203:209]),  # 0xCB
            end_date=clean(data[209:215]),  # 0xD1
            features=clean(data[215:229]),  # 0xD7
            category1=clean(data[229:237]),  # 0xE5
            category2=clean(data[237:245]),  # 0xED
            category3=clean(data[245:253]),  # 0xF5
            category4=clean(data[253:261]),  # 0xFD
            category5=clean(data[261:269]),  # 0x105
            category6=clean(data[269:277]),  # 0x10D
            trailer=data[277:288],  # 11 bytes padding
        )


def is_model_index_block_288(data: bytes) -> bool:
    if len(data) < 288:
        return False

    # Check first record model code
    if not is_valid_model_code(data[0:6]):
        return False

    if len(data) >= 288*2:
        if not is_valid_model_code(data[288:288+6]):
            return False
    return True


@dataclass
class MultilingualPartRecord167:
    """Represents a multilingual part name record from sffastus (167 bytes)

    Located at 0x0CD41000+
    Encoding: CP437

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (11): Spec Code (e.g., "103TW      ")
        0x11 (25): Description (e.g., "WAGON(STEP ROOF)         ")
        0x2A (125): Trailer/Padding
    """
    offset: int
    model_code: str
    spec_code: str
    description: str
    trailer: bytes
    raw_data: bytes


def is_multilingual_part_block_167(data: bytes) -> bool:
    """
    Check if data looks like a 167-byte multilingual part record block.

    Detection heuristics:
    - Starts with valid model code (6 bytes)
    - Spec code (11 bytes) typically alphanumeric
    """
    if len(data) < 167:
        return False
    if len(data) >= 167 * 2:
        return is_valid_model_code(data[0:6]) and is_valid_model_code(data[167:167 + 6])

    try:
        # Check model code
        if not is_valid_model_code(data[0:6]):
            return False

        # Spec code (offset 6, length 11)
        # Often starts with digits
        spec_code = data[6:17].decode(CHARSET, errors='replace').strip()
        if not spec_code:
            # Allow empty spec? Maybe. But usually present.
            pass
            
        return True
    except:
        return False


@dataclass
class MultilingualPartRecord180:
    """Represents a multilingual part name record from sffastus (180 bytes)

    Contains part names in 4 languages: English, German, French, Spanish.
    Encoding: CP437 (NOT Latin-1)

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (7):  Part Code (e.g., "13028  ")
        0x0D (40): English Name
        0x35 (40): German Name
        0x5D (40): French Name
        0x85 (40): Spanish Name
        0xAD (7):  Trailer (binary flags/metadata)
    """
    offset: int
    model_code: str
    part_code: str
    name_en: str
    name_de: str
    name_fr: str
    name_es: str
    trailer: bytes
    raw_data: bytes


@dataclass
class ItcaRecord:
    """Represents a record in ITCA_DATA.TXT (Parts Catalog)
    
    Structure (87 bytes/rec):
        0-15:   Part number (Current)
        17:     ITCA code (Status)
        19-34:  ITCA part number (Supersedes-to)
        35-37:  Q'ty
        38-45:  Part code
        46-86:  Part name (Description)
    """
    part_number: str
    itca_code: str
    supersedes_to: str
    quantity: int
    part_code: str
    description: str


class ItcaPartsCatalog:
    """Catalog of ITCA records with lookup capability."""
    def __init__(self, records: List[ItcaRecord]):
        self.records = records
        self._build_indexes()
    
    def _build_indexes(self):
        self.primary_index = {r.part_number: r for r in self.records}
        # For supersedes, multiple parts might supersede to the same one
        self.supersedes_index = defaultdict(list)
        for r in self.records:
            if r.supersedes_to and r.supersedes_to.strip():
                self.supersedes_index[r.supersedes_to.strip()].append(r)
    
    def lookup(self, part_number: str) -> List[ItcaRecord]:
        """Lookup record by current part number or supersedes-to part number."""
        part_number = part_number.strip()
        results = []
        if part_number in self.primary_index:
            results.append(self.primary_index[part_number])
        if part_number in self.supersedes_index:
            results.extend(self.supersedes_index[part_number])
        return results


def is_multilingual_part_block_180(data: bytes) -> bool:
    """
    Check if data looks like a 180-byte multilingual part record block.

    Detection heuristics:
    - Starts with valid model code (6 bytes)
    - Has alphanumeric part code at offset 6
    - Has readable text in name fields
    """
    if len(data) < 180:
        return False
    if len(data) >= 180 * 2:
        return is_valid_model_code(data[0:6]) and is_valid_model_code(data[180:180 + 6])


    try:
        # Check model code
        if not is_valid_model_code(data[0:6]):
            return False

        # Check part code - should be alphanumeric
        # Use CP437 as requested by user
        # Part code is 7 bytes in this format
        part_code = data[6:13].decode(CHARSET).strip()
        if not part_code or not part_code.replace(' ', '').isalnum():
            # Allow some flexibility, but usually part codes are alphanumeric
            pass

        # Check that English name area has readable text
        name_area = data[13:53]
        printable = sum(1 for b in name_area if 32 <= b <= 126 or b == 0)
        if printable / len(name_area) < 0.5:
            return False
        
        # Check German/French/Spanish areas too if needed, but EN is usually enough
        return True
    except:
        return False


def is_multilingual_part_block(data: bytes) -> bool:
    """
    Check if data looks like a multilingual part record block (192-byte records).

    Detection heuristics:
    - Starts with valid model code (6 bytes)
    - Has alphanumeric part code at offset 6
    - Has numeric figure code at offset 12
    - Has readable text in name fields
    """
    if len(data) < 192:
        return False
    if len(data) >= 192 * 2:
        return is_valid_model_code(data[0:6]) and is_valid_model_code(data[192:192 + 6])

    try:
        # Check model code
        if not is_valid_model_code(data[0:6]):
            return False

        # Check part code - should be alphanumeric
        part_code = data[6:12].decode(CHARSET).strip()
        if not part_code or not part_code.replace(' ', '').isalnum():
            return False

        # Check figure code - should contain digits
        figure_code = data[12:17].decode(CHARSET).strip()
        if not any(c.isdigit() for c in figure_code):
            return False

        # Check that English name area has readable text
        name_area = data[19:59]
        printable = sum(1 for b in name_area if 32 <= b <= 126 or b == 0)
        if printable / len(name_area) < 0.5:
            return False

        return True
    except:
        return False








def parse_code_index_records_33(f, start_offset, max_records=None, verbose=False):
    """
    Parse code index records (33 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of CodeIndexRecord33 objects
    """
    RECORD_SIZE = 33
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = CodeIndexRecord33.parse_33(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_glossary_records_28(f, start_offset, max_records=None, verbose=False):
    """
    Parse glossary records (28 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of GlossaryRecord28 objects
    """
    RECORD_SIZE = 28
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = GlossaryRecord28.parse_28(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_color_records_91(f, start_offset, max_records=None, verbose=False):
    """
    Parse color records (91 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of ColorRecord91 objects
    """
    RECORD_SIZE = 91
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = ColorRecord91.parse_91(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records




def parse_part_group_records_185(f, start_offset, max_records=None, verbose=False):
    """
    Parse part group description records (185 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of PartGroupRecord185 objects
    """
    RECORD_SIZE = 185
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = PartGroupRecord185.parse_185(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_variant_glossary_records_81(f, start_offset, max_records=None, verbose=False):
    """
    Parse variant glossary records (81 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of VariantGlossaryRecord81 objects
    """
    RECORD_SIZE = 81
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        # Note: can have leading spaces in first record of block
        if not is_valid_model_code(data[0:6]) and not is_valid_model_code(data[0:6].strip().ljust(6)):
            break

        record = VariantGlossaryRecord81.parse_81(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


    return records


def parse_multilingual_part_records_182(f, start_offset, max_records=None, verbose=False):
    """
    Parse multilingual part records (182 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of MultilingualPartRecord182 objects
    """
    f.seek(start_offset)
    records = []
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        # Peek for separator or model code
        pos = f.tell()
        data = f.read(10)
        if len(data) < 10:
            break

        # If it starts with the 19 1e separator, skip it or include it?
        # Based on analysis, the struct might be 182 bytes including the separator.
        if data.startswith(b'\x19\x1e'):
            f.seek(pos)
            data = f.read(182)
        elif is_valid_model_code(data[:6]):
            f.seek(pos)
            data = f.read(182)
        else:
            break

        if len(data) < 182:
            break

        try:
            record = MultilingualPartRecord182.parse_182(data, pos)
            records.append(record)
            if verbose and count % 100 == 0:
                print(f"  Parsed {count} 182-byte records...")
        except:
            break

        count += 1

    return records


def parse_inventory_records_199(f, start_offset, max_records=None, verbose=False):
    """
    Parse inventory records (199 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of InventoryRecord199 objects
    """
    f.seek(start_offset)
    records = []
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        data = f.read(199)
        if len(data) < 199:
            break

        # Check for padding (all zeros in model code field)
        if all(b == 0 for b in data[:6]):
            break

        try:
            record = InventoryRecord199.parse_199(data, start_offset + count * 199)
            records.append(record)
            if verbose and count % 100 == 0:
                print(f"  Parsed {count} inventory records...")
        except:
            break

        count += 1

    return records


def parse_engine_spec_records_230(f, start_offset, max_records=None, verbose=False):
    """
    Parse engine specification records (230 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of EngineSpecRecord230 objects
    """
    RECORD_SIZE = 230
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = EngineSpecRecord230.parse_230(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_figure_index_records_22(f, start_offset, max_records=None, verbose=False):
    """
    Parse figure index records (22 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of FigureIndexRecord22 objects
    """
    RECORD_SIZE = 22
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = FigureIndexRecord22.parse_22(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_spec_mapping_records_22(f, start_offset, max_records=None, verbose=False):
    """
    Parse spec mapping records (22 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of SpecMappingRecord22 objects
    """
    RECORD_SIZE = 22
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = SpecMappingRecord22.parse_22(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_fig_illustration_page_records_89(f, start_offset, max_records=None, verbose=False):
    """
    Parse FIG illustration page/sub-index records (89 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of FIGIllustrationPage89 objects
    """
    RECORD_SIZE = 89
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = FIGIllustrationPage89.parse_89(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_fig_illustration_records_183(f, start_offset, max_records=None, verbose=False):
    """
    Parse FIG illustration description records (183 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of FIGIllustrationRecord183 objects
    """
    RECORD_SIZE = 183
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = FIGIllustrationRecord183.parse_183(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_fig_group_category_records_184(f, start_offset, max_records=None, verbose=False):
    """
    Parse FIG group category description records (184 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of FIGGroupCategoryRecord184 objects
    """
    RECORD_SIZE = 184
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        record = FIGGroupCategoryRecord184.parse_184(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_model_spec_records_103(f, start_offset, max_records=None, verbose=False):
    """
    Parse model spec records (103 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of ModelSpecRecord103 objects
    """
    RECORD_SIZE = 103
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break


        # Parse fields (cp437)
        record = ModelSpecRecord103.parse_103(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_model_index_records_288(f, start_offset, max_records=None, verbose=False):
    """
    Parse model index records (288 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of ModelIndexRecord288 objects
    """
    RECORD_SIZE = 288
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        # Parse fields (cp437)
        record = ModelIndexRecord288.parse_288(data, offset)
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_part_range_records_24(f, start_offset, max_records=None, verbose=False):
    """
    Parse part range records (24 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse
        verbose: Print progress

    Returns:
        List of PartRangeRecord24 objects
    """
    RECORD_SIZE = 24
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        # Parse fields (cp437)
        model_code = data[0:6].decode(CHARSET, errors='replace').strip()
        part_start = data[6:13].decode(CHARSET, errors='replace').strip()
        part_end = data[13:20].decode(CHARSET, errors='replace').strip()
        metadata = data[20:24]

        record = PartRangeRecord24(
            offset=offset,
            model_code=model_code,
            part_start=part_start,
            part_end=part_end,
            metadata=metadata,
            raw_data=data
        )
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_multilingual_part_records_167(f, start_offset, max_records=None, verbose=False):
    """
    Parse multilingual part name records (167 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse (None = until invalid)
        verbose: Print progress during parsing

    Returns:
        List of MultilingualPartRecord167 objects
    """
    RECORD_SIZE = 167
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        # Parse fields (cp437 encoding)
        model_code = data[0:6].decode(CHARSET, errors='replace').strip()
        spec_code = data[6:17].decode(CHARSET, errors='replace').strip()
        description = data[17:42].decode(CHARSET, errors='replace').strip()
        trailer = data[42:167]

        record = MultilingualPartRecord167(
            offset=offset,
            model_code=model_code,
            spec_code=spec_code,
            description=description,
            trailer=trailer,
            raw_data=data
        )
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_multilingual_part_records_180(f, start_offset, max_records=None, verbose=False):
    """
    Parse multilingual part name records (180 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse (None = until invalid)
        verbose: Print progress during parsing

    Returns:
        List of MultilingualPartRecord180 objects
    """
    RECORD_SIZE = 180
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        # Parse fields (cp437 encoding)
        # Structure: model(6) + part(7) + en(40) + de(40) + fr(40) + es(40) + trailer(7)
        model_code = data[0:6].decode(CHARSET, errors='replace').strip()
        part_code = data[6:13].decode(CHARSET, errors='replace').strip()
        # No figure/index in this format
        
        name_en = data[13:53].decode(CHARSET, errors='replace').strip()
        name_de = data[53:93].decode(CHARSET, errors='replace').strip()
        name_fr = data[93:133].decode(CHARSET, errors='replace').strip()
        name_es = data[133:173].decode(CHARSET, errors='replace').strip()
        trailer = data[173:180]

        record = MultilingualPartRecord180(
            offset=offset,
            model_code=model_code,
            part_code=part_code,
            name_en=name_en,
            name_de=name_de,
            name_fr=name_fr,
            name_es=name_es,
            trailer=trailer,
            raw_data=data
        )
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_multilingual_part_records(f, start_offset, max_records=None, verbose=False):
    """
    Parse multilingual part name records (192 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse (None = until invalid)
        verbose: Print progress during parsing

    Returns:
        List of MultilingualPartRecord objects
    """
    RECORD_SIZE = 192
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Check if valid record
        if not is_valid_model_code(data[0:6]):
            break

        # Parse fields (cp437 encoding used by DOS-era Subaru software)
        # Structure: model(6) + part(6) + figure(5) + index(2) + en(40) + de(40) + fr(40) + es(40) + trailer(13)
        model_code = data[0:6].decode(CHARSET, errors='replace').strip()
        part_code = data[6:12].decode(CHARSET, errors='replace').strip()
        figure_code = data[12:17].decode(CHARSET, errors='replace').strip()
        index = data[17:19+1].decode(CHARSET, errors='replace').strip()
        name_en = data[19+1:59+1].decode(CHARSET, errors='replace').strip()
        name_de = data[59+1:99+1].decode(CHARSET, errors='replace').strip()
        name_fr = data[99+1:139+1].decode(CHARSET, errors='replace').strip()
        name_es = data[139+1:179+1].decode(CHARSET, errors='replace').strip()
        trailer = data[179+1:192]

        record = MultilingualPartRecord(
            offset=offset,
            model_code=model_code,
            part_code=part_code,
            figure_code=figure_code,
            index=index,
            name_en=name_en,
            name_de=name_de,
            name_fr=name_fr,
            name_es=name_es,
            trailer=trailer,
            raw_data=data
        )
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def detect_vin_record_type(data: bytes) -> str:
    """
    Detect whether data contains 38-byte VIN range records or 69-byte VIN-Model records.

    Args:
        data: At least 69 bytes of data from a VIN block

    Returns:
        'vin_range' for 38-byte records (VIN start + VIN end + pointer)
        'vin_model' for 69-byte records (single VIN + full model spec)
        'unknown' if neither pattern matches
    """
    if len(data) < 69:
        return 'unknown'

    # Check first record for VIN
    try:
        vin1 = data[0:17].decode(CHARSET, errors='replace').strip('\x00')
        if not is_valid_subaru_vin(vin1):
            return 'unknown'
    except:
        return 'unknown'

    # Check for 38-byte pattern: second VIN at offset 17
    try:
        vin2_38 = data[17:34].decode(CHARSET, errors='replace').strip('\x00')
        if is_valid_subaru_vin(vin2_38):
            return 'vin_range'
    except:
        pass

    # Check for 69-byte pattern: null + flag + model code at offset 17-25
    try:
        if data[17] == 0x00 and data[18] in (0x00, 0x01, 0x02):
            model_code = data[19:25].decode(CHARSET)
            if is_valid_model_code(data[19:25]):
                return 'vin_model'
    except:
        pass

    return 'unknown'


def parse_vin_model_records(f, start_offset, max_records=None, verbose=False):
    """
    Parse VIN-Model detail records (69 bytes each).

    Args:
        f: File handle to sffastus
        start_offset: Where records begin
        max_records: Maximum records to parse (None = until invalid)
        verbose: Print progress during parsing

    Returns:
        List of VINModelRecord objects
    """
    RECORD_SIZE = 69
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Parse VIN
        vin = data[0:17].decode(CHARSET, errors='replace').strip('\x00')

        if not is_valid_subaru_vin(vin):
            break

        # Parse remaining fields
        flag = data[18]
        model_code = data[19:25].decode(CHARSET, errors='replace').strip()
        body_model = data[25:32].decode(CHARSET, errors='replace').strip()
        spec_code = data[32:41].decode(CHARSET, errors='replace').strip()
        binary_flags = data[41:43]
        date1 = data[43:51].decode(CHARSET, errors='replace')
        date2 = data[51:59].decode(CHARSET, errors='replace')
        date3 = data[59:67].decode(CHARSET, errors='replace')
        suffix = data[67:69].decode(CHARSET, errors='replace')

        record = VINModelRecord(
            offset=offset,
            vin=vin,
            flag=flag,
            model_code=model_code,
            body_model=body_model,
            spec_code=spec_code,
            binary_flags=binary_flags,
            date1=date1,
            date2=date2,
            date3=date3,
            suffix=suffix,
            raw_data=data
        )
        records.append(record)

        if verbose and count % 1000 == 0:
            print(f"  Parsed {count} records at 0x{offset:08X}...")

        count += 1

    return records


def parse_itca_data(file_path: str) -> List[ItcaRecord]:
    """Parse ITCA_DATA.TXT and return an ItcaPartsCatalog."""
    records = []
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return records
        
    with open(file_path, 'r', encoding=CHARSET, errors='replace') as f:
        for line_num, line in enumerate(f, 1):
            if len(line) < 86:
                continue
            
            try:
                # Based on empirical analysis of ITCA_DATA.TXT:
                # 0-15: Part number (Current) - 16 bytes
                # 16:   ITCA code (Status)    - 1 byte
                # 18-33: ITCA part number      - 16 bytes
                # 34-35: Q'ty                  - 2 bytes
                # 37-44: Part code             - 8 bytes
                # 45-84: Part name (Description) - 40 bytes
                
                part_number = line[0:16].strip()
                itca_code = line[16:17].strip()
                supersedes_to = line[18:34].strip()
                qty_str = line[34:36].strip()
                quantity = int(qty_str) if qty_str.isdigit() else 0
                part_code = line[37:45].strip()
                description = line[45:85].strip()
                
                records.append(ItcaRecord(
                    part_number=part_number,
                    itca_code=itca_code,
                    supersedes_to=supersedes_to,
                    quantity=quantity,
                    part_code=part_code,
                    description=description
                ))
            except Exception as e:
                print(f"Error parsing line {line_num}: {e}")
                
    return records


def parse_vin_blocks(f, start_offset=0x800, max_records=None, verbose=False):
    """
    Parse VIN range records starting at given offset.

    Each record is 38 bytes:
    - Bytes 0-16: VIN range start (17 chars ASCII)
    - Bytes 17-33: VIN range end (17 chars ASCII)
    - Bytes 34-35: Section number (uint16 LE)
    - Bytes 36-37: Index within section (uint16 LE)

    Args:
        f: File handle to sffastus
        start_offset: Where VIN records begin (default 0x800)
        max_records: Maximum records to parse (None = until invalid)
        verbose: Print progress during parsing

    Returns:
        List of VINRecord objects
    """
    RECORD_SIZE = 38
    records = []

    f.seek(start_offset)
    count = 0

    while True:
        if max_records and count >= max_records:
            break

        offset = f.tell()
        data = f.read(RECORD_SIZE)

        if len(data) < RECORD_SIZE:
            break

        # Parse fields
        vin_start = data[0:17].decode(CHARSET, errors='replace').strip('\x00')
        vin_end = data[17:34].decode(CHARSET, errors='replace').strip('\x00')
        section = struct.unpack('<H', data[34:36])[0]
        index = struct.unpack('<H', data[36:38])[0]

        # Validate - must be a valid Subaru VIN
        if not is_valid_subaru_vin(vin_start):
            # End of VIN records
            break

        record = VINRecord(
            offset=offset,
            vin_start=vin_start,
            vin_end=vin_end,
            section=section,
            index=index,
            raw_data=data
        )
        records.append(record)

        if verbose and count % 100 == 0:
            print(f"  Parsed {count} records at 0x{offset:06X}...")

        count += 1

    return records


def analyze_vin_blocks(f, start_offset=0x800, max_records=2000):
    """
    Analyze VIN block structure and print statistics.

    Returns dict with analysis results.
    """
    print(f"\n=== Analyzing VIN Blocks at 0x{start_offset:X} ===")

    records = parse_vin_blocks(f, start_offset, max_records, verbose=True)

    if not records:
        print("  No valid VIN records found!")
        return {}

    # Collect statistics
    sections = {}
    for rec in records:
        if rec.section not in sections:
            sections[rec.section] = {'count': 0, 'min_idx': rec.index, 'max_idx': rec.index}
        sections[rec.section]['count'] += 1
        sections[rec.section]['min_idx'] = min(sections[rec.section]['min_idx'], rec.index)
        sections[rec.section]['max_idx'] = max(sections[rec.section]['max_idx'], rec.index)

    # Print results
    print(f"\n  Total records: {len(records)}")
    print(f"  Offset range: 0x{records[0].offset:06X} - 0x{records[-1].offset:06X}")
    print(f"  First VIN: {records[0].vin_start}")
    print(f"  Last VIN: {records[-1].vin_end}")

    print(f"\n  Sections found: {len(sections)}")
    for sec in sorted(sections.keys()):
        info = sections[sec]
        print(f"    Section {sec}: {info['count']} records, index {info['min_idx']}-{info['max_idx']}")

    # Sample records
    print(f"\n  First 5 records:")
    for rec in records[:5]:
        print(f"    0x{rec.offset:06X}: {rec.vin_start} - {rec.vin_end} [sec={rec.section}, idx={rec.index}]")

    print(f"\n  Last 5 records:")
    for rec in records[-5:]:
        print(f"    0x{rec.offset:06X}: {rec.vin_start} - {rec.vin_end} [sec={rec.section}, idx={rec.index}]")

    return {
        'records': records,
        'sections': sections,
        'total': len(records)
    }


def scan_vin_blocks_2kb(f, min_contiguous=5):
    """
    Scan file for 2KB VIN blocks.

    VIN data is organized in 2KB (2048 byte) blocks:
    - Each block contains ~53 VIN records (38 bytes each)
    - Blocks end with ~34 bytes of zero padding
    - Uses is_valid_subaru_vin() to detect VIN blocks

    Args:
        f: File handle to sffastus
        min_contiguous: Minimum contiguous blocks to report as region

    Returns:
        List of (start_offset, block_count, estimated_records) tuples
    """
    BLOCK_SIZE = 2048
    RECORDS_PER_BLOCK = 53  # Approximate

    f.seek(0, 2)
    file_size = f.tell()

    regions = []
    current_start = None
    current_count = 0

    for offset in range(0, file_size, BLOCK_SIZE):
        f.seek(offset)
        data = f.read(17)
        if len(data) < 17:
            break

        vin = data.decode(CHARSET, errors='replace')

        if is_valid_subaru_vin(vin):
            if current_start is None:
                current_start = offset
                current_count = 1
            else:
                current_count += 1
        else:
            # print(f"0x{offset:08X} - non vin '{vin}'")
            if current_start is not None and current_count >= min_contiguous:
                regions.append((current_start, current_count, current_count * RECORDS_PER_BLOCK))
            current_start = None
            current_count = 0

    # Handle last region
    if current_start is not None and current_count >= min_contiguous:
        regions.append((current_start, current_count, current_count * RECORDS_PER_BLOCK))

    return regions


def analyze_vin_blocks_2kb(f, min_contiguous=5):
    """
    Analyze 2KB VIN block structure and print report.
    """
    f.seek(0, 2)
    file_size = f.tell()

    print(f"\n=== 2KB VIN Block Analysis ===")
    print(f"File size: {file_size:,} bytes ({file_size/1024/1024:.1f} MB)")

    regions = scan_vin_blocks_2kb(f, min_contiguous)

    if not regions:
        print("No VIN block regions found!")
        return []

    total_blocks = sum(r[1] for r in regions)
    total_records = sum(r[2] for r in regions)

    print(f"\nFound {len(regions)} contiguous VIN regions (>= {min_contiguous} blocks):")
    print(f"{'Start':>12} {'End':>12} {'Blocks':>8} {'Records':>10}")
    print("-" * 46)

    for start, blocks, records in regions:
        end = start + blocks * 2048
        print(f"0x{start:08X}  0x{end:08X}  {blocks:8d}  ~{records:9d}")

    print("-" * 46)
    print(f"{'Total':>26}  {total_blocks:8d}  ~{total_records:9d}")
    print(f"\nTotal VIN data: {total_blocks * 2048 / 1024 / 1024:.2f} MB")

    return regions


# Valid model codes from WINDOWS_APP_GUIDE.md
VALID_MODEL_CODES = (
    'A10', 'A11',
    'B10', 'B11', 'B12', 'B13', 'B14', 'B15',
    'C10', 'C11', 'C12',
    'G10', 'G11', 'G12', 'G13', 'G14', 'G23', 'G24', 'G33',
    'J10',
    'S10', 'S11', 'S12', 'S13',
    'V10',
    'W10',
    'Z10'
)


def is_valid_model_code(data: bytes) -> bool:
    """
    Check if 6 bytes look like a valid model code from the official list.
    Model codes are 3 chars followed by spaces in the records.
    """
    if len(data) < 6:
        return False
    try:
        text = data[:6].decode(CHARSET).rstrip()
        return text in VALID_MODEL_CODES
    except:
        return False


def detect_block_type(data: bytes, offset: int = 0) -> str:
    """
    Detect the type of a 2KB block.

    Args:
        data: 2048 bytes of block data
        offset: File offset of this block (used for header detection)

    Returns:
        Block type string: 'header', 'vin', 'model_index',
        'body_model', 'text', 'binary', 'padding', 'unknown'
    """
    BLOCK_SIZE = 2048

    if len(data) < BLOCK_SIZE:
        return 'incomplete'

    # 1. Header block (first 2KB contains header + model table + padding)
    if offset < 0x800:
        return 'header'

    # 2. All zeros = padding
    if all(b == 0 for b in data):
        return 'padding'

    # 3. VIN block - first 17 bytes are a valid Subaru VIN
    # Distinguish between 38-byte VIN range records and 69-byte VIN-Model records
    try:
        vin = data[0:17].decode(CHARSET, errors='replace')
        if is_valid_subaru_vin(vin):
            vin_type = detect_vin_record_type(data)
            if vin_type == 'vin_range':
                return 'vin_range'
            elif vin_type == 'vin_model':
                return 'vin_model'
            else:
                return 'vin'  # Fallback for unknown VIN format
    except:
        pass

    if is_part_range_block_24(data):
        return 'part_range_24'

    if is_multilingual_part_block(data):
        return 'multilingual_part'

    if is_multilingual_part_block_180(data):
        return 'multilingual_part_180'

    if is_multilingual_part_block_167(data):
        return 'multilingual_part_167'

    if is_model_spec_block_103(data):
        return 'model_spec_103'

    # 4f. Catalog applicability block (466-byte) - NEW
    if is_catalog_applicability_block_466(data):
        return 'catalog_applicability_466'

    # 4g. Color record block (91-byte) - NEW
    if is_color_record_block_91(data):
        return 'color_record_91'

    # 4h. Glossary record block (28-byte) - NEW
    if is_glossary_record_block_28(data):
        return 'glossary_record_28'

    # 4i. Code index record block (33-byte) - NEW
    if is_code_index_record_block_33(data):
        return 'code_index_record_33'

    # 4j. Model index block (288-byte) - NEW
    if is_model_index_block_288(data):
        return 'model_index_288'

    # 4k. FIG group category block (184-byte) - NEW
    if is_fig_group_category_block_184(data):
        return 'fig_group_category_184'

    # 4l. FIG illustration block (183-byte) - NEW
    if is_fig_illustration_block_183(data):
        return 'fig_illustration_183'

    # 4m. FIG illustration page block (89-byte) - NEW
    if is_fig_illustration_page_block_89(data):
        return 'fig_illustration_page_89'

    # 4n. Engine spec block (230-byte) - NEW
    if is_engine_spec_block_230(data):
        return 'engine_spec_230'

    # 4o. Part group block (185-byte) - NEW
    if is_part_group_block_185(data):
        return 'part_group_185'

    # 4p. Variant glossary block (81-byte) - NEW
    if is_variant_glossary_block_81(data):
        return 'variant_glossary_81'

    # 4q. Inventory record block (199-byte) - NEW
    if is_inventory_block_199(data):
        return 'inventory_199'

    # 4r. Multilingual part block (182-byte) - NEW
    if is_multilingual_part_block_182(data):
        return 'multilingual_part_182'

    # 4s. Figure index block (22-byte) - NEW
    if is_figure_index_block_22(data):
        return 'figure_index_22'

    # 4t. Spec mapping block (22-byte) - NEW
    if is_spec_mapping_block_22(data):
        return 'spec_mapping_22'

    # 5. Body model block - 17-byte records with 7-char body code + model code
    # Body codes are 7 alphanumeric chars like "BD6AY1G"
    try:
        # Check first record pattern: 7-char body code + 2 bytes + 6-char model code
        body_code = data[0:7].decode(CHARSET)
        if (len(body_code) == 7 and
            body_code.isalnum() and
            body_code[0].isalpha() and
            is_valid_model_code(data[9:15])):
            return 'body_model'
    except:
        pass

    # 6. Text block - mostly printable ASCII
    printable_count = sum(1 for b in data if 32 <= b <= 126 or b in (9, 10, 13))
    printable_ratio = printable_count / len(data)

    if printable_ratio >= 0.8:
        return 'text'

    # 7. Binary block - low printable ratio, has content
    non_zero = sum(1 for b in data if b != 0)
    if non_zero > 0 and printable_ratio < 0.4:
        return 'binary'

    # 8. Mixed content
    if printable_ratio >= 0.4:
        return 'mixed'

    return 'unknown'


def scan_block_types(f, max_blocks=None):
    """
    Scan entire file block by block and return map of ranges to types.

    Args:
        f: File handle to sffastus
        max_blocks: Maximum blocks to scan (None = entire file)

    Returns:
        List of (start_offset, end_offset, block_count, block_type) tuples.
        Consecutive blocks of same type are merged into ranges.
    """
    BLOCK_SIZE = 2048

    f.seek(0, 2)
    file_size = f.tell()

    total_blocks = file_size // BLOCK_SIZE
    if max_blocks:
        total_blocks = min(total_blocks, max_blocks)

    ranges = []
    current_type = None
    current_start = 0
    current_count = 0

    for block_idx in range(total_blocks):
        offset = block_idx * BLOCK_SIZE
        f.seek(offset)
        data = f.read(BLOCK_SIZE)

        if len(data) < BLOCK_SIZE:
            break

        block_type = detect_block_type(data, offset)
        # print(f"Scanned block {block_idx:5d}/{total_blocks:5d} at 0x{offset:08X}: {block_type}")

        if block_type == current_type:
            current_count += 1
        else:
            # Save previous range if exists
            if current_type is not None:
                end_offset = current_start + current_count * BLOCK_SIZE
                ranges.append((current_start, end_offset, current_count, current_type))

            # Start new range
            current_type = block_type
            current_start = offset
            current_count = 1

    # Save last range
    if current_type is not None:
        end_offset = current_start + current_count * BLOCK_SIZE
        ranges.append((current_start, end_offset, current_count, current_type))

    return ranges


def print_block_type_map(ranges):
    """
    Print a formatted block type map.

    Args:
        ranges: List from scan_block_types()
    """
    print(f"\n{'Start':>12} {'End':>12} {'Blocks':>8} {'Type':<15}")
    print("-" * 50)

    total_blocks = 0
    type_counts = {}

    for start, end, count, block_type in ranges:
        print(f"0x{start:08X}  0x{end:08X}  {count:8d}  {block_type:<15}")
        total_blocks += count
        type_counts[block_type] = type_counts.get(block_type, 0) + count

    print("-" * 50)
    print(f"{'Total':>26}  {total_blocks:8d}")

    print(f"\nBlock type summary:")
    for block_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / total_blocks if total_blocks > 0 else 0
        print(f"  {block_type:<15} {count:8d} blocks ({pct:5.1f}%)")


def main():
    if not os.path.exists(SFFASTUS_PATH):
        print(f"Error: {SFFASTUS_PATH} not found")
        print(f"Current directory: {os.getcwd()}")
        sys.exit(1)

    file_size = os.path.getsize(SFFASTUS_PATH)
    print(f"=== Subaru FAST2 sffastus Analyzer ===")
    print(f"File: {SFFASTUS_PATH}")
    print(f"Size: {file_size:,} bytes ({file_size/1024/1024:.1f} MB)")

    with open(SFFASTUS_PATH, 'rb') as f:
        # 1. Parse known structures
        print("\n" + "="*60)
        print("PHASE 1: Known Structure Analysis")
        print("="*60)

        # Header
        print("\n=== Header (0x00-0x30) ===")
        f.seek(0)
        header = f.read(0x32)
        for i in range(0, len(header), 16):
            hex_part = ' '.join(f'{b:02x}' for b in header[i:i+16])
            print(f"  {i:04X}: {hex_part}")

        # Model table
        models = parse_model_table(f)

        # US VIN section
        analyze_vin_section(f, 0x800, 5)

        # JDM VIN section
        analyze_vin_section(f, 0x260400, 5)

        # 2. Pattern analysis
        print("\n" + "="*60)
        print("PHASE 2: Pattern Analysis")
        print("="*60)
        scan_for_patterns(f, file_size)

        # 3. Search for images
        print("\n" + "="*60)
        print("PHASE 3: Image Search")
        print("="*60)
        images = search_for_images(f, file_size)
        print(f"\nTotal images found: {len(images)}")

        # 4. Multilingual text search
        print("\n" + "="*60)
        print("PHASE 4: Multilingual Text Analysis")
        print("="*60)
        text_regions = analyze_text_regions(f, file_size)

        # 5. Section boundary detection (can be slow for large files)
        print("\n" + "="*60)
        print("PHASE 5: Section Boundary Detection")
        print("="*60)
        # Only scan first 100MB for boundaries to save time
        boundaries = find_section_boundaries(f, min(file_size, 100 * 1024 * 1024))

        # 6. Sample random offsets user mentioned
        print("\n" + "="*60)
        print("PHASE 6: Random Offset Sampling")
        print("="*60)

        # Sample at various points throughout the file
        sample_offsets = [
            0x1000000,   # 16 MB
            0x5000000,   # 80 MB
            0xA000000,   # 160 MB
            0xF000000,   # 240 MB
            0x14000000,  # 320 MB
            0x19000000,  # 400 MB
            0x1E000000,  # 480 MB
        ]

        for offset in sample_offsets:
            if offset < file_size:
                extract_record_at_offset(f, offset, 128)

        print("\n" + "="*60)
        print("ANALYSIS COMPLETE")
        print("="*60)

        # Summary
        print(f"\nSummary:")
        print(f"  - File size: {file_size/1024/1024:.1f} MB")
        print(f"  - Model codes found: {len(models)}")
        print(f"  - Images detected: {len(images)}")
        print(f"  - Text regions found: {len(text_regions)}")
        print(f"  - Section boundaries: {len(boundaries)}")

if __name__ == '__main__':
    main()
