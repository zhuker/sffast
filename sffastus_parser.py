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
from enum import Enum
from typing import BinaryIO, Dict, Generator, List, Optional, Tuple

SFFASTUS_PATH = "sffastus"

CHARSET = 'cp437'


def clean(b: bytes, encoding: str = CHARSET) -> str:
    return b.decode(encoding, errors='replace').strip()


def clean_nostrip(b: bytes, encoding: str = CHARSET) -> str:
    return b.decode(encoding, errors='replace')


def read_langs(data: bytes, lang_offset: int, width: int, num_languages: int,
               encoding: str = CHARSET):
    """Read the language-description fields of a multilingual record.

    US records carry 4 language fields (EN/DE/FR/ES); JDM carries 1 (JP). Returns
    (en, de, fr, es, post_offset) where post_offset = lang_offset + num_languages
    * width is where the record's post-language fields/trailer begin. Languages
    not present in this region are returned as ''.
    """
    vals = ['', '', '', '']
    for i in range(num_languages):
        vals[i] = clean(data[lang_offset + i * width:lang_offset + (i + 1) * width], encoding)
    return vals[0], vals[1], vals[2], vals[3], lang_offset + num_languages * width


# --- Region profiles ---------------------------------------------------------
# The sffastus/SFFASTA binary comes in market variants that share the same
# container format (magic, block-pointer encoding, MODEL_BLOCK_INDEX slot->type
# map) but differ in a few fixed ways. A RegionProfile captures every
# region-varying constant; it is detected once at open() and threaded through
# parsing. US is the default so existing behavior is unchanged.
#
# Differences (US vs modern JDM 20710SF/30804SF):
#  - model-index record size: 288 (45-slot array) vs 420 (78-slot array)
#  - text encoding: cp437 vs cp932 (Shift-JIS; half-width katakana + ASCII)
#  - language fields per text record: 4 (EN/DE/FR/ES) vs 1 (JP)
#  - count-pair region start slot in the model array: 30 vs 52
#  - catalog applicability record size: 466 vs 496 (internal layout differs)
#  - VIN/chassis range record: 38 B / 17-char VIN vs 22 B / 9-char chassis id

US_COUNT_REGION_START = 30  # baseline assumed by MODEL_BLOCK_COUNTS


@dataclass(frozen=True)
class RegionProfile:
    name: str                       # 'US' | 'JDM'
    model_record_size: int          # 288 | 420
    encoding: str                   # 'cp437' | 'cp932'
    num_languages: int              # 4 | 1
    count_region_start: int         # first count-pair slot in model array
    cat_size: int                   # catalog_applicability record size
    vin_record_size: int            # VIN/chassis range record size
    vin_id_len: int                 # VIN/chassis identifier length
    record_sizes: dict = field(default_factory=dict)  # record_id -> JDM size override

    @property
    def model_array_len(self) -> int:
        """Length of the model record's block-index array (record minus the
        6-byte model code and the shared 102-byte text trailer)."""
        return self.model_record_size - 108

    def size_for(self, record_id: str, default: int) -> int:
        """Record size for this region (override or the US default)."""
        return self.record_sizes.get(record_id, default)


def check_bitmask(data: bytes, position: int) -> bool:
    """Check if a 1-based bit position is set in a binary bitmask.

    Equivalent to EPC3's _check_bitmask() but operates on raw bytes
    instead of hex strings. Position 1 = MSB of byte 0.
    """
    if not data or position < 1:
        return False
    pos0 = position - 1
    byte_idx = pos0 // 8
    bit_idx = pos0 % 8
    if byte_idx >= len(data):
        return False
    return bool(data[byte_idx] & (0x80 >> bit_idx))


# Valid Subaru VIN prefixes
# 4S3 - US manufactured (Subaru of Indiana Automotive)
# JF1 - Japan manufactured (Fuji Heavy Industries)
# JF2 - Japan manufactured (Fuji Heavy Industries, newer)
SUBARU_VIN_PREFIXES = ('4S3', '4S4', 'JF1', 'JF2')
BLOCK_SIZE = 2048


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


def is_valid_vehicle_id(s: str, profile: Optional['RegionProfile'] = None) -> bool:
    """Validate a vehicle identifier for the region.

    US uses 17-char Subaru VINs (4S3/JF1/...); JDM uses chassis numbers like
    'BE5002001' (3-letter chassis code + 6-digit serial).
    """
    if profile is not None and profile.name == 'JDM':
        s = s.strip()
        return len(s) >= 3 and s[0].isalpha() and s[:profile.vin_id_len].isalnum()
    return is_valid_subaru_vin(s)


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


def is_printable_text(data: bytes, threshold: float = 0.7) -> bool:
    """Check if data is mostly printable ASCII/extended ASCII text"""
    if not data:
        return False
    printable = sum(1 for b in data if 32 <= b <= 126 or b in (9, 10, 13, 0))
    return printable / len(data) >= threshold


def detect_language(text: str) -> str:
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


def find_image_signatures(data: bytes, offset: int) -> Optional[str]:
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


def analyze_region(f: BinaryIO, start: int, size: int, description: str = "") -> dict:
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


def scan_for_strings(f: BinaryIO, start: int, end: int, min_length: int = 10) -> List[Tuple[int, str]]:
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


def scan_for_patterns(f: BinaryIO, file_size: int) -> None:
    """Scan the file for repeating patterns that might indicate record structures"""
    patterns = defaultdict(int)

    # Sample at various offsets
    sample_points = [
        0x800,  # Known VIN data start
        0x100000,  # 1MB
        0x500000,  # 5MB
        0x1000000,  # 16MB
        0x5000000,  # 80MB
        0x10000000,  # 256MB
        0x15000000,  # 336MB
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


def find_section_boundaries(f: BinaryIO, file_size: int) -> List[dict]:
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
            print(f"  0x{offset:08X} ({offset / 1024 / 1024:6.1f} MB): {region['type']}")

    return boundaries


def parse_model_table(f: BinaryIO) -> List[Tuple[str, int]]:
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


def analyze_vin_section(f: BinaryIO, start: int, count: int = 10) -> None:
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


def search_for_images(f: BinaryIO, file_size: int) -> List[Tuple[int, str]]:
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
                print(f"  Found {fmt} at 0x{abs_pos:08X} ({abs_pos / 1024 / 1024:.1f} MB)")
                pos += 1

    return images_found


def analyze_text_regions(f: BinaryIO, file_size: int) -> List[Tuple[int, str, str]]:
    """Find and analyze text regions with multilingual content"""
    print("\n=== Multilingual Text Search ===")

    # Look for known multilingual patterns
    search_terms = [
        b'ENGINE',
        b'MOTOR',  # German
        b'MOTEUR',  # French
        b'CLUTCH',
        b'KUPPLUNG',  # German
        b'EMBRAYAGE',  # French
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


def extract_record_at_offset(f: BinaryIO, offset: int, record_size: int = 256) -> bytes:
    """Extract and display a record at a given offset"""
    f.seek(offset)
    data = f.read(record_size)

    print(f"\n=== Record at 0x{offset:08X} ===")

    # Hex dump
    for i in range(0, len(data), 16):
        hex_part = ' '.join(f'{b:02x}' for b in data[i:i + 16])
        ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data[i:i + 16])
        print(f"  {offset + i:08X}: {hex_part:48s} {ascii_part}")

    return data


@dataclass
class SffastusHeader:
    """Parsed header (first 50 bytes) of an sffastus file.

    The header describes the VIN-data section layout:
        0x00 (4):  Magic (always 00 04 01 00)
        0x04 (2):  US VIN block count (BE u16)
        0x06 (4):  Pointer → body model range index block
        0x0A (2):  Body model range index block count (BE u16, always 1)
        0x0C (4):  Pointer → JDM VIN start block
        0x10 (2):  JDM VIN block count (BE u16)
        0x12 (4):  Pointer → body model start block
        0x16 (2):  Body model block count (BE u16)
        0x18 (4):  Pointer → VIN detail start block
        0x1C (4):  VIN detail block count (BE u32)
        0x20 (18): Three catalog section descriptors (4-byte ptr + 2-byte count each)

    Block pointers use the (b1-4)*75+b2 encoding.
    """
    magic: bytes
    us_vin_count: int
    body_model_range_index_block: int
    body_model_range_index_count: int
    jdm_vin_start_block: int
    jdm_vin_count: int
    body_model_start_block: int
    body_model_count: int
    vin_detail_start_block: int
    vin_detail_count: int
    catalog_descriptors: list  # 3 tuples of (raw_ptr_bytes, count)
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse(data: bytes) -> 'SffastusHeader':
        """Parse the first 50 bytes of an sffastus file."""
        return SffastusHeader(
            magic=data[0:4],
            us_vin_count=struct.unpack('>H', data[4:6])[0],
            body_model_range_index_block=decode_block_pointer(data[6:10]),
            body_model_range_index_count=struct.unpack('>H', data[10:12])[0],
            jdm_vin_start_block=decode_block_pointer(data[12:16]),
            jdm_vin_count=struct.unpack('>H', data[16:18])[0],
            body_model_start_block=decode_block_pointer(data[18:22]),
            body_model_count=struct.unpack('>H', data[22:24])[0],
            vin_detail_start_block=decode_block_pointer(data[24:28]),
            vin_detail_count=struct.unpack('>I', data[28:32])[0],
            catalog_descriptors=[
                (data[32:36], struct.unpack('>H', data[36:38])[0]),
                (data[38:42], struct.unpack('>H', data[42:44])[0]),
                (data[44:48], struct.unpack('>H', data[48:50])[0]),
            ],
            raw_data=data[:50],
        )

    @property
    def us_vin_start_block(self) -> int:
        """US VIN data always starts at block 1 (right after header block 0)."""
        return 1

    @property
    def model_index_start_block(self) -> int:
        """Model index starts right after US VIN blocks."""
        return 1 + self.us_vin_count

    @property
    def model_index_count(self) -> int:
        """Number of model index blocks (between US VIN end and range index)."""
        return self.body_model_range_index_block - self.model_index_start_block


@dataclass
class VINRecord:
    RECORD_SIZE = 38
    """Represents a VIN range record from sffastus (38 bytes)

    Used for VIN range lookup - maps VIN ranges to section pointers.
    """
    offset: int
    vin_start: str
    vin_end: str
    section: int
    index: int
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_38(data: bytes, offset: int = 0) -> 'VINRecord':
        """Parse a 38-byte US VIN range record (17-char VIN start/end)."""
        return VINRecord.parse_range(data, offset, id_len=17)

    @staticmethod
    def parse_range(data: bytes, offset: int = 0, id_len: int = 17) -> 'VINRecord':
        """Parse a VIN/chassis range record: start(id_len) + end(id_len) + LE
        section(2) + index(2). US id_len=17 (38 B), JDM id_len=9 (22 B)."""
        p = 2 * id_len
        return VINRecord(
            offset=offset,
            raw_data=data,
            vin_start=data[0:id_len].decode(CHARSET, errors='replace').strip('\x00'),
            vin_end=data[id_len:2 * id_len].decode(CHARSET, errors='replace').strip('\x00'),
            section=struct.unpack('<H', data[p:p + 2])[0],
            index=struct.unpack('<H', data[p + 2:p + 4])[0],
        )


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
        0x20 (3):  Color Code (e.g., "G1U")
        0x23 (3):  Trim Code (e.g., "H20")
        0x26 (2):  Main Option Code (e.g., "NT")
        0x28 (1):  Padding (space)
        0x29 (2):  Binary flags
        0x2B (8):  Body Production Date (YYYYMMDD) — EPC3: BD_SEISAN_YMD
        0x33 (8):  Engine Production Date (YYYYMMDD) — EPC3: EG_SEISAN_YMD
        0x3B (8):  Trans Production Date (YYYYMMDD) — EPC3: TM_SEISAN_YMD
        0x43 (2):  Destination Code (e.g., "U5")
    """
    offset: int
    vin: str
    flag: int
    model_code: str
    body_model: str
    color_code: str
    trim_code: str
    option_code: str
    binary_flags: bytes
    body_production_date: str
    engine_production_date: str
    trans_production_date: str
    destination_code: str
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_69(data: bytes, offset: int = 0) -> 'VINModelRecord':
        """Parse a 69-byte VIN-Model detail record."""
        return VINModelRecord(
            offset=offset,
            raw_data=data,
            vin=data[0:17].decode(CHARSET, errors='replace').strip('\x00'),
            flag=data[18],
            model_code=clean(data[19:25]),
            body_model=clean(data[25:32]),
            color_code=clean(data[32:35]),
            trim_code=clean(data[35:38]),
            option_code=clean(data[38:40]),
            binary_flags=data[41:43],
            body_production_date=clean_nostrip(data[43:51]),
            engine_production_date=clean_nostrip(data[51:59]),
            trans_production_date=clean_nostrip(data[59:67]),
            destination_code=clean_nostrip(data[67:69]),
        )

    @staticmethod
    def parse_jdm68(data: bytes, offset: int = 0, encoding: str = 'cp932') -> 'VINModelRecord':
        """Parse the JDM 68-byte chassis detail record.

        Layout (reverse-engineered from 30804SF/SFFASTA):
            0x00 (9):  Chassis number (e.g. "BE5002001")
            0x0A (1):  Flag (0x01)
            0x0B (6):  Model Code (e.g. "B12   ")
            0x11 (7):  Body Model (e.g. "BE5A48T") — first 7 chars match the
                       ModelSpec applied_model grade (e.g. "BE5-48T")
            0x18..0x21 color/trim/option (best-effort)
            0x2C (8):  Body production date YYYYMMDD
            0x34 (8):  Engine production date
            0x3C (8):  Trans production date
        """
        return VINModelRecord(
            offset=offset,
            raw_data=data,
            vin=clean(data[0:9], encoding),
            flag=data[10],
            model_code=clean(data[11:17], encoding),
            body_model=clean(data[17:24], encoding),
            color_code=clean(data[24:27], encoding),
            trim_code=clean(data[27:30], encoding),
            option_code=clean(data[30:33], encoding),
            binary_flags=data[33:36],
            body_production_date=clean_nostrip(data[44:52], encoding),
            engine_production_date=clean_nostrip(data[52:60], encoding),
            trans_production_date=clean_nostrip(data[60:68], encoding),
            destination_code='',
        )


@dataclass
class BodyModelRecord17:
    RECORD_SIZE = 17
    """Represents a 17-byte body model mapping record from sffastus

    Maps body model codes (7-char, e.g., "BD6AY1G") to model codes (e.g., "B11")
    and a model position (bit index for APPLIED_MODEL bitmask filtering).

    Structure:
        0x00 (7):  Body Model Code (e.g., "BD6AY1G", "SHMDY6S")
        0x07 (2):  Constant (always 0x0001 BE)
        0x09 (6):  Model Code (e.g., "B11   ", "S12   ")
        0x0F (2):  Model Position (BE uint16) — EPC3: MODEL_POSITION
    """
    ID = 'body_model'
    offset: int
    body_model: str
    constant: int
    model_code: str
    model_position: int
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_17(data: bytes, offset: int = 0) -> 'BodyModelRecord17':
        return BodyModelRecord17(
            offset=offset,
            body_model=clean_nostrip(data[0:7]),
            constant=(data[7] << 8) | data[8],
            model_code=clean(data[9:15]),
            model_position=(data[15] << 8) | data[16],
            raw_data=data,
        )


@dataclass
class BodyModelRangeRecord18:
    RECORD_SIZE = 18
    """Represents an 18-byte body model range index record from sffastus.

    Located at the "transition block" between model index and JDM VIN section.
    Maps sorted body model code ranges to body model data blocks.
    Used for binary search: given a body model code, find which block to read.

    Structure:
        0x00 (7): model_from — first body model code in range (e.g., "BD6AY1G")
        0x07 (7): model_to   — last body model code in range (e.g., "BH9CY5R")
        0x0E (4): pointer    — 4-byte block pointer (00 b1 b2 00)

    Pointer encoding: block_number = (b1 - 4) * 75 + b2

    Sentinel: record starting with 0x2A ('*') marks end of list.
    """
    offset: int
    model_from: str
    model_to: str
    block_pointer: bytes
    block_number: int
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_18(data: bytes, offset: int = 0) -> 'BodyModelRangeRecord18':
        ptr = data[14:18]
        return BodyModelRangeRecord18(
            offset=offset,
            model_from=clean_nostrip(data[0:7]),
            model_to=clean_nostrip(data[7:14]),
            block_pointer=ptr,
            block_number=decode_block_pointer(ptr),
            raw_data=data,
        )


@dataclass
class MultilingualPartRecord192:
    ID = 'multilingual_part_192'
    RECORD_SIZE = 192
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
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_192(data: bytes, offset: int = 0, encoding: str = CHARSET,
                  num_languages: int = 4) -> 'MultilingualPartRecord192':
        """Parse a multilingual part record (US 192 B / JDM 72 B)."""
        en, de, fr, es, post = read_langs(data, 20, 40, num_languages, encoding)
        return MultilingualPartRecord192(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            part_code=clean(data[6:12], encoding),
            figure_code=clean(data[12:17], encoding),
            index=clean(data[17:20], encoding),
            name_en=en, name_de=de, name_fr=fr, name_es=es,
            trailer=data[post:post + 12],
        )


@dataclass
class CodeIndexRecord33:
    ID = 'code_index_record_33'
    RECORD_SIZE = 33
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
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_33(data: bytes, offset: int = 0, encoding: str = CHARSET) -> 'CodeIndexRecord33':
        """Parse a code index record (US 33 B / JDM 32 B)."""

        # Don't strip the size_variant field to preserve all data
        size_variant_raw = clean_nostrip(data[7:22], encoding)

        return CodeIndexRecord33(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            category=data[6],  # Single byte
            size_variant=size_variant_raw,  # Keep as-is, don't strip - 15 bytes
            code=clean(data[22:29], encoding),  # 7 bytes (was 6 + separator)
            metadata=data[29:33],  # 4 bytes
        )


class ItcaCode(Enum):
    """ITCA interchangeability condition codes."""
    MUTUAL = '1'              # New ↔ Old: mutually interchangeable
    NEW_REPLACES_OLD = '2'    # New → Old: only new can replace old
    OLD_REPLACES_NEW = '3'    # Old → New: only old can replace new
    SIMPLE_MOD = '4'          # New → Old with simple modifications
    WITH_OTHER_PARTS = '6'    # New + other parts → Old
    BOTH_SIDES = '7'          # Must replace both RH and LH (color/appearance)
    KIT = '8'                 # New part number (parts kit) replaces old
    COMPULSORY = '9'          # Compulsory replacement (other conditions)

    @property
    def label(self) -> str:
        return {
            '1': 'mutual',
            '2': 'new→old',
            '3': 'old→new',
            '4': 'simple mod',
            '6': 'w/other parts',
            '7': 'both sides',
            '8': 'kit',
            '9': 'compulsory',
        }[self.value]

    @property
    def has_bulletin(self) -> bool:
        """Whether this code can trigger an I&S Bulletin.

        Per FAST2 manual (pdf/FAST2.txt p.23): "Detailed data of ITCA Bltn
        is available only when ITCA condition codes represents 4, 6, 7, and 8."
        """
        return self.value in ('4', '6', '7', '8')

    @classmethod
    def from_str(cls, s: str) -> Optional['ItcaCode']:
        s = s.strip()
        try:
            return cls(s)
        except ValueError:
            return None


@dataclass
class ItcaRecord:
    ID = "itca_251"
    RECORD_SIZE = 251
    """Represents a record in ITCA_DATA.TXT (Parts Catalog)

    Structure (87 bytes/rec):
        0-15:   Part number (Current)
        17:     ITCA code (Status)
        19-34:  ITCA part number (Supersedes-to)
        35-37:  Q'ty
        38-45:  Part code
        46-86:  Part name (Description)
    """
    offset: int
    part_number: str
    itca_code: str
    supersedes_to: str
    quantity: str
    part_code: str
    description: str
    description_de: str = ""
    description_fr: str = ""
    description_sp: str = ""
    unknown: bytes = None
    raw_data: bytes = field(default=None, repr=False)

    @staticmethod
    def parse_itca_251(data: bytes, offset: int = 0) -> 'ItcaRecord':
        part_number = data[0:15]
        supersedes_to = data[15:15 + 15]
        status = data[15 + 15:15 + 15 + 1]
        desc_en = data[15 + 15 + 1:15 + 15 + 1 + 40]
        desc_de = data[15 + 15 + 1 + 40:15 + 15 + 1 + 40 + 40]
        desc_fr = data[15 + 15 + 1 + 40 + 40:15 + 15 + 1 + 40 + 40 + 40]
        desc_sp = data[15 + 15 + 1 + 40 + 40 + 40:15 + 15 + 1 + 40 + 40 + 40 + 40]
        qty = data[15 + 15 + 1 + 40 + 40 + 40 + 40:15 + 15 + 1 + 40 + 40 + 40 + 40 + 40]
        part_code = data[15 + 15 + 1 + 40 + 40 + 40 + 40 + 40:15 + 15 + 1 + 40 + 40 + 40 + 40 + 40 + 9]
        unknown = data[15 + 15 + 1 + 40 + 40 + 40 + 40 + 42 + 9:]
        return ItcaRecord(
            offset=offset,
            part_number=clean(part_number),
            itca_code=clean(status),
            supersedes_to=clean(supersedes_to),
            quantity=clean(qty),
            part_code=clean(part_code),
            description=clean(desc_en),
            description_de=clean(desc_de),
            description_fr=clean(desc_fr),
            description_sp=clean(desc_sp),
            unknown=unknown,
            raw_data=data
        )


class ItcaPartsCatalog:
    """Catalog of ITCA records with lookup capability."""

    def __init__(self, records: List[ItcaRecord]) -> None:
        self.records = records
        self._build_indexes()

    def _build_indexes(self) -> None:
        self.primary_index = {r.part_number: r for r in self.records}
        # For supersedes, multiple parts might supersede to the same one
        self.supersedes_index = defaultdict(list)
        for r in self.records:
            if r.supersedes_to and r.supersedes_to.strip():
                self.supersedes_index[r.supersedes_to.strip()].append(r)

    def contains(self, part_number: str) -> bool:
        part_number = part_number.strip()
        return (part_number in self.primary_index) or (part_number in self.supersedes_index)

    def lookup(self, part_number: str) -> List[ItcaRecord]:
        """Lookup record by current part number or supersedes-to part number."""
        part_number = part_number.strip()
        results = []
        if part_number in self.primary_index:
            results.append(self.primary_index[part_number])
        if part_number in self.supersedes_index:
            results.extend(self.supersedes_index[part_number])
        return results

    def follow_chain(self, part_number: str) -> List[tuple[str, ItcaCode]]:
        """Walk the supersession chain from a part number.

        Returns list of (supersedes_to, ItcaCode) hops, e.g.:
            A --(6)--> B --(6)--> C  =>  [("B", WITH_OTHER_PARTS), ("C", WITH_OTHER_PARTS)]
        Stops at dead-ends, cycles, or unknown codes.
        """
        part_number = part_number.strip()
        chain: list[tuple[str, ItcaCode]] = []
        visited: set[str] = {part_number}
        current = part_number
        while current in self.primary_index:
            rec = self.primary_index[current]
            nxt = rec.supersedes_to.strip()
            if not nxt or nxt in visited:
                break
            code = ItcaCode.from_str(rec.itca_code)
            if code is None:
                break
            chain.append((nxt, code))
            visited.add(nxt)
            current = nxt
        return chain


@dataclass
class CatalogApplicabilityRecord466:
    ID = 'catalog_applicability_466'
    RECORD_SIZE = 466
    """Represents a 466-byte catalog applicability record from sffastus.

    Structure (466 bytes total):
        0x00  (6):   Model Code (e.g., "G11   ")
        0x06  (7):   Group/Category a.k.a. Callout Code (e.g., "H505301", "14878")
        0x0D  (12):  Part ID (e.g., "98271FE090OE")
        0x19  (3):   Padding (spaces)
        0x1C  (1):   Model Year Version (A-H letter code) — EPC3: NENKAI
        0x1D  (16):  Date Range YYYYMMDDYYYYMMDD
        0x2D  (19):  Destination Codes (e.g., "C0U4", "U5U6")
        0x40  (64):  Spec Logic expression (e.g., "EJ22# +EJ25D")
        0x80  (32):  Usage Notes / OP (e.g., "LH", "FOR A/C", "-E/#979080")
        0xA0  (46):  Part Spec / Part Color (e.g., "T=4.68", "CLARION", "PAINT FOR USAGE")
        --- tail region (data[206:]) ---
        0xCE  (10):  Ref Code - 10-digit internal ref (e.g., "0100000009", "*00017300")
        0xD8  (12):  Related Part number (e.g., "13228AB102") or spaces
        0xE4  (6):   Figure cross-ref qualifier (right-justified number, optional letter prefix)
        0xEA  (4):   Figure Ref: group letter (A-Z) + 3-digit number (e.g., "A012")
        0xEE  (2):   Padding (spaces)
        0xF0  (2):   Figure Page (e.g., "04") or spaces
        0xF2  (44):  Secondary binder ref (e.g., "B20") + market code at end
        0x11E (4):   Market/Locale code (e.g., "C", "T", "ND", "MI", "GL")
        0x122 (15):  Option Position bitmask (EPC3: OPTION_POSITION)
        0x131 (109): Padding (zeros)
        0x19E (2):   Option flag: 0x00 + 0x2A('*') or 0x20(' ') (EPC3: OP_FLG)
        0x1A0 (25):  Line Options (EPC3: LINE_OP1..LINE_OP5, 5x5 bytes)
        0x1B9 (15):  Supplier/distribution code (e.g., "SSPCQ", "COWPX", "SUNRO")
        0x1C8 (10):  Padding (spaces)
    """
    offset: int

    model_code: str
    callout_code: str
    part_id: str

    model_year_version: str
    date: str
    destination_codes: str

    spec_logic: str
    usage_notes: str

    part_spec: str
    ref_code: str
    related_part: str
    figure_ref: str
    figure_page: str
    supplier_code: str
    option_flag: str
    option_position: bytes
    line_options: bytes
    raw_data: bytes = field(repr=False)

    @property
    def is_manual_only(self) -> bool:
        """Helper: Checks if spec logic restricts to Manual Transmission."""
        return '.MT' in self.spec_logic or 'MT.' in self.spec_logic

    @staticmethod
    def parse_466(data: bytes, offset: int = 0) -> 'CatalogApplicabilityRecord466':
        return CatalogApplicabilityRecord466(
            # Identification
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            callout_code=clean(data[6:13]),
            part_id=clean(data[13:25]),

            # Validity Range
            model_year_version=clean(data[28:29]),
            date=clean(data[29:45]),

            # Destination / Market Codes (e.g., C0=Canada, U4/U5/U6=US)
            destination_codes=clean(data[45:64]),

            # The Logic String (Fixed window at 0x40/64 decimal)
            spec_logic=clean(data[64:128]),

            # Notes / Constraints (Fixed window at 0x80/128 decimal)
            usage_notes=clean(data[128:160]),

            # Part Spec / Part Color (extends to byte 206 where numeric code starts)
            part_spec=clean(data[160:206]),

            # Internal reference code (10 digits)
            ref_code=clean(data[206:216]),

            # Related/companion part number
            related_part=clean(data[216:228]),

            # Figure reference (group letter + 3-digit number)
            figure_ref=(chr(data[234]) + clean(data[235:238])
                        if len(data) > 241 and 0x41 <= data[234] <= 0x5A else ''),
            figure_page=clean(data[240:242]) if len(data) > 241 else '',

            # Supplier/distribution code (e.g., "SSPCQ", "COWPX", "SUNRO")
            supplier_code=clean(data[441:456]) if len(data) > 455 else '',

            # Option flag: '*' = has option condition, ' ' = none (EPC3: OP_FLG)
            option_flag=chr(data[0x19F]) if len(data) > 0x19F else '',

            # Option position bitmask (EPC3: OPTION_POSITION)
            option_position=data[0x122:0x131] if len(data) > 0x130 else b'',

            # Line options (EPC3: LINE_OP1..LINE_OP5, 5x5 bytes)
            line_options=data[0x1A0:0x1B9] if len(data) > 0x1B8 else b'',
        )

    @staticmethod
    def parse_496(data: bytes, offset: int = 0, encoding: str = 'cp932') -> 'CatalogApplicabilityRecord466':
        """Parse the JDM 496-byte catalog applicability record.

        The identification/validity head (0x00-0x2D: model_code, callout_code,
        part_id, model_year_version, date) is identical to the US 466 layout. The
        remaining fields are reorganized:
          - spec_logic lives at 0x2D (where US keeps destination_codes); JDM is a
            single market (Japan) so there are no separate destination codes.
          - the figure link is a 6-char field at 0xD4: a volume/book digit (0xD4),
            then a US-style "<group_letter><nnn>" figure_ref (0xD5, e.g. "A039"),
            with the 2-digit figure page at 0xDC. figure_ref is taken WITHOUT the
            leading volume digit so the shared `figure_ref[1:] == fig` matching in
            get_fig_callouts works the same as US.
        Reverse-engineered from 30804SF/SFFASTA (B12). Fields not present in JDM
        (usage_notes, part_spec, related_part, supplier_code, options) are blank.
        """
        return CatalogApplicabilityRecord466(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            callout_code=clean(data[6:13], encoding),
            part_id=clean(data[13:25], encoding),
            model_year_version=clean(data[28:29], encoding),
            date=clean(data[29:45], encoding),
            destination_codes='',
            spec_logic=clean(data[45:109], encoding),
            usage_notes='',
            part_spec='',
            ref_code=clean(data[206:213], encoding),
            related_part='',
            figure_ref=clean(data[214:218], encoding),
            figure_page=clean(data[220:222], encoding),
            supplier_code='',
            option_flag='',
            option_position=b'',
            line_options=b'',
        )


@dataclass
class GlossaryRecord28:
    RECORD_SIZE = 28
    """Represents a glossary/terminology record from sffastus (28 bytes)

    Located at 0x0DE23800+
    Encoding: CP437

    Structure:
        0x00 (6): Model Code (e.g., "B11   ")
        0x06 (1): Category/Type byte
        0x07 (17): Term/Text (e.g., "AUTO", "AXLE", "5X20")
        0x18 (2): Display Order (BE uint16) — EPC3: HYOUZI_ORDER
        0x1A (2): Metadata tail
    """
    ID = 'glossary_record_28'
    offset: int
    model_code: str
    category: int  # Single byte category
    term: str
    display_order: int
    metadata_tail: bytes
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_28(data: bytes, offset: int = 0, encoding: str = CHARSET) -> 'GlossaryRecord28':
        """Parse a glossary record (US 28 B / JDM 27 B)."""

        return GlossaryRecord28(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            category=data[6],  # Single byte
            term=clean(data[7:24], encoding),  # 17 bytes
            display_order=(data[24] << 8) | data[25],
            metadata_tail=data[26:28],
        )


@dataclass
class ColorRecord91:
    ID = 'color_record_91'
    RECORD_SIZE = 91
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
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_91(data: bytes, offset: int = 0, encoding: str = CHARSET,
                 num_languages: int = 4) -> 'ColorRecord91':
        """Parse a color record (US 91 B / JDM 31 B). Color names are 20-B fields."""
        en, de, fr, es, _ = read_langs(data, 10, 20, num_languages, encoding)
        return ColorRecord91(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            paint_code=clean(data[6:10], encoding),  # 4 bytes
            color_name_en=en, color_name_de=de, color_name_fr=fr, color_name_es=es,
        )


@dataclass
class FIGIllustrationRecord183:
    ID = 'fig_illustration_183'
    RECORD_SIZE = 183
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
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_183(data: bytes, offset: int = 0, encoding: str = CHARSET,
                  num_languages: int = 4) -> 'FIGIllustrationRecord183':
        """Parse a FIG illustration record (US 183 B / JDM 63 B). Descriptions at 13."""
        en, de, fr, es, post = read_langs(data, 13, 40, num_languages, encoding)
        return FIGIllustrationRecord183(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            fig_group_code=clean(data[6:8], encoding),
            fig_group_code2=clean(data[8:8 + 5], encoding),
            desc_en=en, desc_de=de, desc_fr=fr, desc_es=es,
            trailer=data[post:post + 10],
        )


@dataclass
class EngineSpecRecord230:
    RECORD_SIZE = 230
    """Represents a 230-byte engine specification record from sffastus

    Located at 0x0DFB1000+
    Encoding: CP437

    Contains engine types and production periods.
    The 125-byte applied_model_bitmask encodes which model positions this
    figure page applies to (EPC3: M_ILLUST_NARROW.APPLIED_MODEL).

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (2):  Group Code (usually "00")
        0x08 (40): Description (EN)
        0x30 (40): Description (DE)
        0x58 (5):  Padding
        0x5D (6):  Start Date (YYYYMM)
        0x63 (6):  End Date (YYYYMM)
        0x69 (125): Applied Model bitmask (EPC3: APPLIED_MODEL, 1000 bits)
    """
    ID = 'engine_spec_230'
    offset: int
    model_code: str
    figure: str
    figure_page: str
    applicable_model: str
    start_date: str
    end_date: str
    applied_model_bitmask: bytes
    raw_data: bytes = field(repr=False)

    def check_model_position(self, position: int) -> bool:
        """Check if model_position (1-based) is set in the applied_model bitmask."""
        return check_bitmask(self.applied_model_bitmask, position)

    @staticmethod
    def parse_230(data: bytes, offset: int = 0) -> 'EngineSpecRecord230':
        """Parse a 230-byte engine specification record."""

        return EngineSpecRecord230(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            figure=clean(data[6:9]),
            figure_page=clean(data[9:9 + 4]),
            applicable_model=clean(data[9 + 4:88]),
            start_date=clean(data[93:99]),
            end_date=clean(data[99:105]),
            applied_model_bitmask=data[105:230],
        )


@dataclass
class FIGIllustrationPage89:
    """Represents a FIG illustration page/sub-index record from sffastus (89 bytes)

    Located at 0x0DFA5000+
    Encoding: CP437

    Contains sub-indexing for FIG illustrations, mapping specific FIG indices
    to page numbers and labels, with pointers to CCITT Group 4 image data.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (3):  FIG Index (e.g., "002")
        0x09 (2):  Padding (usually spaces)
        0x0B (2):  Page Index (e.g., "01")
        0x0D (40): Label (e.g., "VALVE")
        Trailer (36 bytes at 0x35):
        0x35 (4):  ptr1 - model-level pointer (same for all pages in a model)
        0x39 (4):  ptr2 - model-level pointer (same for all pages in a model)
        0x3D (8):  zeros
        0x45 (4):  ptr3 - figure image data pointer (per-page)
        0x49 (12): other fields
        0x55 (2):  image_size - raw G4 data byte count (big-endian uint16)
        0x57 (2):  zeros

    ptr3 encoding (4 bytes): [marker] [byte1] [byte2] [byte3]
        position = (byte1 - ref_byte1) * 19200 + byte2 * 256 + byte3
        file_offset = base + position * 8
        where 19200 = 75 * 256 (factor 75 matches section-level block pointers)
        base and ref_byte1 are model-specific constants.
        Verified for G11: ref_byte1=0x1A, base=0x1745D000 (23/23 records, 0 errors).
    """
    ID = 'fig_illustration_page_89'
    RECORD_SIZE = 89
    offset: int
    model_code: str
    fig_index: str
    page_index: str
    label: str
    ptr1: bytes
    ptr2: bytes
    ptr3: bytes
    image_size: int
    trailer: bytes
    raw_data: bytes = field(repr=False)

    def get_figure_offset(self) -> int:
        return decode_fig_data_pointer(self.ptr3)

    @staticmethod
    def parse_89(data: bytes, offset: int = 0) -> 'FIGIllustrationPage89':
        """Parse an 89-byte FIG illustration page record."""

        trailer = data[53:89]
        return FIGIllustrationPage89(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            fig_index=clean(data[6:9]),
            page_index=clean(data[11:13]),
            label=clean(data[13:53]),
            ptr1=trailer[0:4],
            ptr2=trailer[4:8],
            ptr3=trailer[16:20],
            image_size=(trailer[32] << 8) | trailer[33],
            trailer=trailer,
        )


@dataclass
class InventoryRecord199:
    ID = 'inventory_199'
    RECORD_SIZE = 199
    """Represents a 199-byte inventory/part name record from sffastus

    Located at 0x0E147000+ (B11), 0x17451000+ (G11), etc.
    Encoding: CP437

    Maps figure callout codes to part numbers with multilingual names and
    X,Y coordinates indicating where the callout appears on the figure image.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (5):  Figure (e.g., "004  ")
        0x0B (2):  Figure Page (e.g., "02")
        0x0D (15): Part Number (e.g., "037018200      ")
        0x1C (2):  X Coordinate (BE uint16, ~2x pixel coords on 1280x640 figure)
        0x1E (2):  Y Coordinate (BE uint16, ~2x pixel coords on 1280x640 figure)
        0x20 (7):  Part Code (e.g., "0370S  ")
        0x27 (40): English Name
        0x4F (40): German Name
        0x77 (40): French Name
        0x9F (40): Spanish Name
        0xC7 (0):  End (6+5+2+15+2+2+7+40*4 = 199)
    """
    offset: int
    model_code: str
    figure: str
    figure_page: str
    part_number: str
    x: int
    y: int
    part_code: str
    name_en: str
    name_de: str
    name_fr: str
    name_es: str
    raw_data: bytes = field(repr=False)
    trailer: bytes = b''  # JDM carries a 14-byte trailer after the single name

    @staticmethod
    def parse_199(data: bytes, offset: int = 0, encoding: str = CHARSET,
                  num_languages: int = 4) -> 'InventoryRecord199':
        """Parse an inventory record (US 199 B / JDM 93 B). Names are 40-B fields
        starting at 0x27; JDM has a 14-B trailer after the single name."""
        en, de, fr, es, post = read_langs(data, 39, 40, num_languages, encoding)
        return InventoryRecord199(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            figure=clean(data[6:11], encoding),
            figure_page=clean(data[11:13], encoding),
            part_number=clean(data[13:28], encoding),
            x=struct.unpack('>H', data[28:30])[0],
            y=struct.unpack('>H', data[30:32])[0],
            part_code=clean(data[32:39], encoding),
            name_en=en, name_de=de, name_fr=fr, name_es=es,
            trailer=data[post:],
        )


@dataclass
class MultilingualPartRecord182:
    ID = 'multilingual_part_182'
    RECORD_SIZE = 182
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
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_182(data: bytes, offset: int = 0, encoding: str = CHARSET,
                  num_languages: int = 4) -> 'MultilingualPartRecord182':
        """Parse a multilingual part record (US 182 B / JDM 62 B). Names at 18."""
        en, de, fr, es, post = read_langs(data, 18, 40, num_languages, encoding)
        return MultilingualPartRecord182(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            part_code=clean(data[6:13], encoding),
            figure=clean(data[13:18], encoding),
            name_en=en, name_de=de, name_fr=fr, name_es=es,
            trailer=data[post:post + 4],
        )


@dataclass
class PartGroupRecord185:
    ID = 'part_group_185'
    RECORD_SIZE = 185
    """Represents a 185-byte part group description record from sffastus

    Located at 0x0DFD3000+
    Encoding: CP437

    Contains descriptive names for part groups with callout coordinates.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (3):  Figure (e.g., "940")
        0x09 (4):  Figure Page (e.g., "01  ")
        0x0D (7):  Callout Code (e.g., "94088A ", "W130076", "42037BA")
        0x14 (1):  Variant Letter (A-R) or space (0x20 = no variant)
        0x15 (40): Description (EN)
        0x3D (40): Description (DE)
        0x65 (40): Description (FR)
        0x8D (40): Description (ES)
        0xB5 (2):  X Coordinate (BE uint16, divide by 2 for pixel on 1280x640)
        0xB7 (2):  Y Coordinate (BE uint16, divide by 2 for pixel on 1280x640)
    """
    offset: int
    model_code: str
    figure: str
    figure_page: str
    callout_code: str
    variant: str
    desc_en: str
    desc_de: str
    desc_fr: str
    desc_es: str
    x: int
    y: int
    raw_data: bytes = field(repr=False)

    @property
    def part_code(self) -> str:
        """Legacy accessor: returns 'callout_code variant' or just 'callout_code'."""
        if self.variant:
            return f'{self.callout_code} {self.variant}'
        return self.callout_code

    @staticmethod
    def parse_185(data: bytes, offset: int = 0, encoding: str = CHARSET,
                  num_languages: int = 4) -> 'PartGroupRecord185':
        """Parse a part group description record (US 185 B / JDM 65 B). Descriptions
        at 21; X/Y callout coordinates follow the language fields."""
        en, de, fr, es, post = read_langs(data, 21, 40, num_languages, encoding)
        return PartGroupRecord185(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            figure=clean(data[6:9], encoding),
            figure_page=clean(data[9:13], encoding),
            callout_code=clean(data[13:20], encoding),
            variant=clean(data[20:21], encoding),
            desc_en=en, desc_de=de, desc_fr=fr, desc_es=es,
            x=struct.unpack('>H', data[post:post + 2])[0],
            y=struct.unpack('>H', data[post + 2:post + 4])[0],
        )


@dataclass
class VariantGlossaryRecord81:
    ID = 'variant_glossary_81'
    RECORD_SIZE = 81
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
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_81(data: bytes, offset: int = 0, encoding: str = CHARSET) -> 'VariantGlossaryRecord81':
        """Parse an 81-byte variant glossary record."""

        return VariantGlossaryRecord81(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            variant_code=clean(data[6:21], encoding),
            description=clean(data[21:81], encoding),
        )


@dataclass
class CategoryIndexRecord20:
    RECORD_SIZE = 20
    """20-byte category index record (text variant)

    One block per model code (10 blocks in SFCDUS2).
    Label is a category code: byte 6 = letter A-J, byte 7 = letter (C or T).
    Payload is printable ASCII.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (2):  Label (e.g., "AC", "ET", "GT")
        0x08 (8):  Payload (ASCII)
        0x10 (4):  Pointer (binary)
    """
    ID = 'category_index_20'
    offset: int
    model_code: str
    label: str
    payload: bytes
    pointer: bytes
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_20(data: bytes, offset: int = 0) -> 'CategoryIndexRecord20':
        return CategoryIndexRecord20(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            label=clean(data[6:8]),
            payload=data[8:16],
            pointer=data[16:20],
        )


@dataclass
class VersionIndexRecord20:
    RECORD_SIZE = 20
    """20-byte version index record (binary variant)

    One block per model code (10 blocks in SFCDUS2).
    Label is version letter + digit: byte 6 = letter A-D, byte 7 = digit 1-9.
    Payload is binary data.

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (2):  Label (e.g., "A1", "B3", "D2")
        0x08 (8):  Payload (binary)
        0x10 (4):  Pointer (binary)
    """
    ID = 'version_index_20'
    offset: int
    model_code: str
    label: str
    payload: bytes
    pointer: bytes
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_20(data: bytes, offset: int = 0) -> 'VersionIndexRecord20':
        return VersionIndexRecord20(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            label=clean(data[6:8]),
            payload=data[8:16],
            pointer=data[16:20],
        )


@dataclass
class ModelYearRecord44:
    RECORD_SIZE = 44
    """Represents a 44-byte model year version record from sffastus

    One block per model code (10 blocks in SFCDUS2).
    Maps version letters to production date ranges and model year labels.

    Structure:
        0x00 (6):  Model Code (e.g., "G11   ")
        0x06 (1):  Version Letter (A,B,C... skips I)
        0x07 (8):  Date From (YYYYMMDD)
        0x0F (8):  Date To (YYYYMMDD)
        0x17 (20): Model Year Label (e.g., "'02MY")
        0x2B (1):  Version Letter (repeated)
    """
    ID = 'model_year_44'
    offset: int
    model_code: str
    version: str
    date_from: str
    date_to: str
    label: str
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_44(data: bytes, offset: int = 0) -> 'ModelYearRecord44':
        return ModelYearRecord44(
            offset=offset,
            raw_data=data,
            model_code=clean_nostrip(data[0:6]),
            version=clean_nostrip(data[6:7]),
            date_from=clean_nostrip(data[7:15]),
            date_to=clean_nostrip(data[15:23]),
            label=clean(data[23:43]),
        )


@dataclass
class FigureIndexRecord22:
    RECORD_SIZE = 22
    """Represents a 22-byte figure cross-reference record from sffastus

    Located at 0x0E75D800+ (B11), 0x17BA3800+ (G11), etc.
    Encoding: CP437

    Stores inter-figure cross-reference arrows: "on figure X page Y,
    at position (x,y), see also figure Z." The coordinates use a
    coordinate space of approximately 2x the pixel dimensions of the
    1280x640 figure images.

    Structure:
        0x00 (6): Model Code (e.g., "B11   ", "G11   ")
        0x06 (3): Figure (e.g., "003")
        0x09 (2): Padding (spaces)
        0x0B (2): Page (e.g., "01")
        0x0D (3): Ref Figure (target figure code, e.g., "004")
        0x10 (2): Padding (spaces)
        0x12 (2): X Coordinate (BE uint16)
        0x14 (2): Y Coordinate (BE uint16)
    """
    ID = 'figure_index_22'
    offset: int
    model_code: str
    figure: str
    page: str
    ref_figure: str
    x: int
    y: int
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_22(data: bytes, offset: int = 0) -> 'FigureIndexRecord22':
        return FigureIndexRecord22(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            figure=clean(data[6:9]),
            page=clean(data[11:13]),
            ref_figure=clean(data[13:16]),
            x=struct.unpack('>H', data[18:20])[0],
            y=struct.unpack('>H', data[20:22])[0],
        )


@dataclass
class PartIndex21:
    ID = 'part_index_21'
    RECORD_SIZE = 21
    offset: int
    part_number: str
    metadata: bytes  # block index maybe
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_21(data: bytes, offset: int = 0) -> 'PartIndex21':
        return PartIndex21(
            offset=offset,
            raw_data=data,
            part_number=clean_nostrip(data[0:15]),
            metadata=data[15:],
        )


@dataclass
class PartRangeIndex34:
    ID = 'part_index_34'
    RECORD_SIZE = 34
    offset: int
    part_number_from: str
    part_number_to: str
    metadata: bytes  # block index maybe BE 16-bit block index (starts 0x1441=5185, increments by 1)
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_34(data: bytes, offset: int = 0) -> 'PartRangeIndex34':
        return PartRangeIndex34(
            offset=offset,
            raw_data=data,
            part_number_from=clean_nostrip(data[0:15]),
            part_number_to=clean_nostrip(data[15:30]),
            metadata=data[30:],
        )


@dataclass
class SpecMappingRecord22:
    ID = 'spec_mapping_22'
    RECORD_SIZE = 22
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
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_22(data: bytes, offset: int = 0) -> 'SpecMappingRecord22':
        return SpecMappingRecord22(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            option_code=clean(data[6:11]),
            description=clean(data[11:22]),
        )


@dataclass
class FIGGroupCategoryRecord184:
    RECORD_SIZE = 184
    """Represents a FIG group category description record from sffastus (184 bytes)

    Located at 0x0DF9A000+
    Encoding: CP437

    Contains multilingual descriptions for FIG group codes.
    Two grouping schemes:
      - 0A-9B: "by system" categories (17 groups mapping to figure number ranges)
      - A1-D3: "by book/binder" categories (~20 figures each, physical binder tabs)

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (2):  FIG Group Code (e.g., "0A", "1B", "9B", "A1", "D3")
        0x08 (40): English Description
        0x30 (40): German Description (Deutsch)
        0x58 (40): French Description (Français)
        0x80 (40): Spanish Description (Español)
        0xA8 (16): Trailer (decoded below)

    Trailer (16 bytes at 0xA8):
        0x00 (2): Trailer ID (BE u16, varies per record)
        0x02 (2): Record Index (BE u16, index into EngineSpecRecord230 list)
        0x04 (4): ptr1 — figure data pointer → FIGIllustrationRecord183 blocks
        0x08 (2): Figure Count (BE u16, number of unique figures in this category)
        0x0A (4): ptr2 — figure data pointer → binary catalog data
        0x0E (2): Record Count (BE u16, number of catalog records for this category)

    Hierarchy:
        FIGGroupCategoryRecord184 (category, e.g. "0A" = ENGINE MAIN)
          └─ FIGIllustrationRecord183 (figure, e.g. "004" = CYLINDER BLOCK)
               └─ FIGIllustrationPage89 (page, e.g. page "01", label "SYSTEM")
    """
    ID = 'fig_group_category_184'
    offset: int
    model_code: str
    fig_group_code: str
    desc_en: str
    desc_de: str
    desc_fr: str
    desc_es: str
    trailer: bytes
    # Decoded trailer fields
    trailer_constant: int
    trailer_record_index: int
    ptr1: bytes  # raw 4-byte pointer → FIGIllustrationRecord183 blocks
    figure_count: int  # number of figures in this category
    ptr2: bytes  # raw 4-byte pointer → catalog data blocks
    record_count: int  # number of catalog records for this category
    raw_data: bytes = field(repr=False)

    @property
    def ptr1_offset(self) -> int:
        """Decode ptr1 to absolute file offset using figure data pointer encoding."""
        return decode_fig_data_pointer(self.ptr1)

    @property
    def ptr2_offset(self) -> int:
        """Decode ptr2 to absolute file offset using figure data pointer encoding."""
        return decode_fig_data_pointer(self.ptr2)

    @staticmethod
    def parse_184(data: bytes, offset: int = 0, encoding: str = CHARSET,
                  num_languages: int = 4) -> 'FIGGroupCategoryRecord184':
        """Parse a FIG group category record (US 184 B / JDM 64 B). Descriptions at
        8; the 16-B binary trailer (figure_count/record_count + pointers) follows."""
        en, de, fr, es, post = read_langs(data, 8, 40, num_languages, encoding)
        trailer = data[post:post + 16]
        trailer_constant = struct.unpack('>H', trailer[0:2])[0]
        trailer_record_index = struct.unpack('>H', trailer[2:4])[0]
        ptr1 = trailer[4:8]
        figure_count = struct.unpack('>H', trailer[8:10])[0]
        ptr2 = trailer[10:14]
        record_count = struct.unpack('>H', trailer[14:16])[0]

        return FIGGroupCategoryRecord184(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            fig_group_code=clean(data[6:8], encoding),
            desc_en=en, desc_de=de, desc_fr=fr, desc_es=es,
            trailer=trailer,
            trailer_constant=trailer_constant,
            trailer_record_index=trailer_record_index,
            ptr1=ptr1,
            figure_count=figure_count,
            ptr2=ptr2,
            record_count=record_count,
        )


@dataclass
class ModelSpecRecord103:
    ID = 'model_spec_103'
    RECORD_SIZE = 103
    """
    Parsed representation of a Subaru Applied Model string.
    Handles variable-length fields found in B11, B13, and G11 chassis codes.
    """
    # Metadata
    offset: int
    raw_data: bytes = field(repr=False)

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
    def parse_103(data: bytes, offset: int = 0, encoding: str = CHARSET) -> 'ModelSpecRecord103':
        """
        Parses fixed-width Subaru model data, automatically stripping whitespace padding.
        Uses wider windows to capture variable length fields (e.g. '5MT' vs 'MT').
        US 103 B / JDM 111 B (the head fields 0x06-0x55 align; JDM adds a tail code).
        """

        # Parsing Logic based on observed B11/G11/B13 offsets
        return ModelSpecRecord103(
            offset=offset,
            raw_data=data,

            # Fixed Header
            model_code=clean(data[0:6], encoding),
            production_period=clean(data[6:21], encoding),
            applied_model=clean(data[21:39], encoding),  # Expanded to catch long codes

            # Variable Specs (Offsets adjusted for wider capture)
            body_config=clean(data[39:47], encoding),  # Window for "S", "W", "WOBK"
            engine=clean(data[47:55], encoding),  # Window for "EJ22EZ", "257"
            drivetrain=clean(data[55:63], encoding),  # Window for "F4WD", "4W"
            transmission=clean(data[63:71], encoding),  # Window for "MT", "5MT", "6MT"
            trim_level=clean(data[71:79], encoding),  # Window for "L", "STI", "25GT"
            spec_option=clean(data[79:85], encoding),  # Window for "N/S"

            _padding=clean(data[85:], encoding)
        )


@dataclass
class PartRangeRecord24:
    RECORD_SIZE = 24
    """Represents a part number range record from sffastus (24 bytes)

    Located at 0x0CD42800+
    Encoding: CP437

    Structure:
        0x00 (6): Model Code (e.g., "B11   ")
        0x06 (7): Part Number Start (e.g., "11711  ")
        0x0D (7): Part Number End (e.g., "12024  ")
        0x14 (4): Metadata (e.g., [0x17, 0x19, Index, 0x00])
    """
    ID = 'part_range_24'
    offset: int
    model_code: str
    part_start: str
    part_end: str
    metadata: bytes
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_24(data: bytes, offset: int = 0) -> 'PartRangeRecord24':
        """Parse a 24-byte part range record."""

        return PartRangeRecord24(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6]),
            part_start=clean(data[6:13]),
            part_end=clean(data[13:20]),
            metadata=data[20:24],
        )


@dataclass
class ModelIndexRecord288:
    RECORD_SIZE = 288
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
    ID = 'model_index_288'
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
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_288(data: bytes, offset: int = 0,
                  profile: Optional['RegionProfile'] = None) -> 'ModelIndexRecord288':
        """Parse a model index record.

        The block-index array width varies by region (US 180 B / JDM 312 B), but
        the 102-byte text trailer is identical and sits at the end of the record.
        Field offsets are therefore expressed relative to the trailer start
        (T = record_size - 102 = 6 + array_len).
        """
        if profile is None:
            profile = US_PROFILE
        enc = profile.encoding
        array_len = profile.model_array_len
        T = 6 + array_len  # trailer start (186 for US 288, 318 for JDM 420)

        return ModelIndexRecord288(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], enc),
            block_index_array=data[6:6 + array_len],
            series_code=clean(data[T:T + 2], enc),
            model_name=clean(data[T + 2:T + 17], enc),
            start_date=clean(data[T + 17:T + 23], enc),
            end_date=clean(data[T + 23:T + 29], enc),
            features=clean(data[T + 29:T + 37], enc),
            category1=clean(data[T + 37:T + 45], enc),
            category2=clean(data[T + 45:T + 53], enc),
            category3=clean(data[T + 53:T + 61], enc),
            category4=clean(data[T + 61:T + 69], enc),
            category5=clean(data[T + 69:T + 77], enc),
            category6=clean(data[T + 77:T + 85], enc),
            trailer=data[T + 85:],
        )


@dataclass
class MultilingualPartRecord167:
    ID = 'multilingual_part_167'
    RECORD_SIZE = 167
    """Represents a multilingual part name record from sffastus (167 bytes)

    Located at 0x0CD41000+
    Encoding: CP437

    The 125-byte applied_position_bitmask encodes which model positions
    this spec code applies to (EPC3: M_TOKUCHO_KIGOU.APPLIED_POSITION).

    Structure:
        0x00 (6):  Model Code (e.g., "B11   ")
        0x06 (11): Spec Code (e.g., "103TW      ")
        0x11 (25): Description (e.g., "WAGON(STEP ROOF)         ")
        0x2A (125): Applied Position bitmask (EPC3: APPLIED_POSITION, 1000 bits)
    """
    offset: int
    model_code: str
    spec_code: str
    description: str
    applied_position_bitmask: bytes
    raw_data: bytes = field(repr=False)

    def check_position(self, position: int) -> bool:
        """Check if model_position (1-based) is set in the applied_position bitmask."""
        return check_bitmask(self.applied_position_bitmask, position)

    @staticmethod
    def parse_167(data: bytes, offset: int = 0, encoding: str = CHARSET) -> 'MultilingualPartRecord167':
        """Parse a 167-byte multilingual part record (single description + bitmask;
        same size in both regions)."""

        return MultilingualPartRecord167(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            spec_code=clean(data[6:17], encoding),
            description=clean(data[17:42], encoding),
            applied_position_bitmask=data[42:167],
        )


@dataclass
class MultilingualPartRecord180:
    RECORD_SIZE = 180
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
    ID = 'multilingual_part_180'
    offset: int
    model_code: str
    part_code: str
    name_en: str
    name_de: str
    name_fr: str
    name_es: str
    trailer: bytes
    raw_data: bytes = field(repr=False)

    @staticmethod
    def parse_180(data: bytes, offset: int = 0, encoding: str = CHARSET,
                  num_languages: int = 4) -> 'MultilingualPartRecord180':
        """Parse a multilingual part record (US 180 B / JDM 60 B). Names at 13."""
        en, de, fr, es, post = read_langs(data, 13, 40, num_languages, encoding)
        return MultilingualPartRecord180(
            offset=offset,
            raw_data=data,
            model_code=clean(data[0:6], encoding),
            part_code=clean(data[6:13], encoding),
            name_en=en, name_de=de, name_fr=fr, name_es=es,
            trailer=data[post:post + 7],
        )


@dataclass
class FigNameRecord:
    """Represents a figure name record from figname.txt

    Location: SFCDUS*/sffastpg/win/figname.txt
    Format: Fixed-width ASCII, 44 bytes per line

    Structure:
        0x00 (3):  Figure Code (e.g., "001", "040")
        0x03 (41): Description (e.g., "ENGINE ASSEMBLY")
    """
    figure_code: str
    description: str

    @staticmethod
    def parse(line: str) -> 'FigNameRecord':
        """Parse a single line from figname.txt"""
        if len(line) < 3:
            raise ValueError(f"Line too short: {len(line)} bytes")

        return FigNameRecord(
            figure_code=line[0:3].strip(),
            description=line[3:].strip()
        )


class SffastusBlockParser:
    """Block type detection and record parsing for sffastus files.

    Holds context (e.g. figure codes from figname.txt) used to
    improve block type disambiguation.
    """

    def __init__(self, figure_codes: Optional[set] = None, parts_catalog: Optional[ItcaPartsCatalog] = None,
                 profile: Optional['RegionProfile'] = None) -> None:
        self.figure_codes = figure_codes or set()
        self.parts_catalog = parts_catalog
        self.profile = profile if profile is not None else US_PROFILE

    def _is_model_code_block(self, data: bytes, record_size: int, *,
                             allow_asterisk: bool = False,
                             extra_check=None,
                             min_records: int = 1) -> bool:
        """Check if data contains fixed-size records starting with valid model codes.

        Args:
            data: Block data bytes.
            record_size: Size of each record in bytes.
            allow_asterisk: If True, 2nd record can be all asterisks (0x2A sentinel).
            extra_check: Optional callable(data) -> bool for additional first-record validation.
            min_records: Minimum number of records required (default 1).
        """
        min_len = record_size * min_records
        if len(data) < min_len:
            return False
        try:
            if not is_valid_model_code(data[0:6]):
                return False
            if extra_check and not extra_check(data):
                return False
            if len(data) >= record_size * 2:
                rec2_start = record_size
                if not is_valid_model_code(data[rec2_start:rec2_start + 6]):
                    if not (allow_asterisk and
                            data[rec2_start:rec2_start + record_size].decode(CHARSET,
                                                                             errors='replace') == '*' * record_size):
                        return False
            return True
        except Exception:
            return False

    def is_code_index_record_block_33(self, data: bytes) -> bool:
        """Check if data looks like a 33-byte code index record block."""
        return self._is_model_code_block(data, CodeIndexRecord33.RECORD_SIZE)

    def is_glossary_record_block_28(self, data: bytes) -> bool:
        """Check if data looks like a 28-byte glossary record block."""
        return self._is_model_code_block(data, GlossaryRecord28.RECORD_SIZE)

    def is_color_record_block_91(self, data: bytes) -> bool:
        """Check if data looks like a 91-byte color record block."""
        return self._is_model_code_block(data, ColorRecord91.RECORD_SIZE, allow_asterisk=True)

    def is_engine_spec_block_230(self, data: bytes) -> bool:
        """Check if data looks like a 230-byte engine specification block."""

        def _check_date(d):
            start_date = clean(d[93:99])
            return not start_date or start_date.isdigit()

        return self._is_model_code_block(data, EngineSpecRecord230.RECORD_SIZE, extra_check=_check_date)

    def is_multilingual_part_block_182(self, data: bytes) -> bool:
        """Check if data looks like a 182-byte multilingual part record block."""
        return self._is_model_code_block(data, MultilingualPartRecord182.RECORD_SIZE)

    def is_inventory_block_199(self, data: bytes) -> bool:
        """Check if data looks like a 199-byte inventory record block."""
        return self._is_model_code_block(data, InventoryRecord199.RECORD_SIZE, allow_asterisk=True)

    def is_part_group_block_185(self, data: bytes) -> bool:
        """Check if data looks like a 185-byte part group block."""

        def _check_group_index(d):
            idx = clean(d[6:9])
            return not idx or idx.isdigit()

        return self._is_model_code_block(data, PartGroupRecord185.RECORD_SIZE, allow_asterisk=True,
                                         extra_check=_check_group_index)

    def is_fig_illustration_page_block_89(self, data: bytes) -> bool:
        """Check if data looks like an 89-byte FIG illustration page record block."""

        def _check_numeric_fields(d):
            fig_idx = clean(d[6:9])
            page_idx = clean(d[11:13])
            return fig_idx.isdigit() and page_idx.isdigit()

        return self._is_model_code_block(data, FIGIllustrationPage89.RECORD_SIZE, extra_check=_check_numeric_fields)

    def is_fig_illustration_block_183(self, data: bytes) -> bool:
        """Check if data looks like a 183-byte FIG illustration record block."""
        return self._is_model_code_block(data, FIGIllustrationRecord183.RECORD_SIZE, allow_asterisk=True)

    def is_variant_glossary_block_81(self, data: bytes) -> bool:
        """Check if data looks like an 81-byte variant glossary record block."""
        return self._is_model_code_block(data, VariantGlossaryRecord81.RECORD_SIZE, allow_asterisk=True, min_records=2)

    def is_part_num(self, partnum: bytes) -> bool:
        return self.parts_catalog.contains(clean(partnum))

    def _is_block_20(self, data: bytes) -> bool:
        """Common check for 20-byte record blocks: valid model codes, same model, terminated by 0x2A."""
        if len(data) < 40:
            return False
        try:
            if not is_valid_model_code(data[0:6]):
                return False
            if not is_valid_model_code(data[20:26]):
                return False
            if data[0:6] != data[20:26]:
                return False
            if not (0x41 <= data[6] <= 0x5A):
                return False
            if not (0x41 <= data[26] <= 0x5A):
                return False
            for i in range(2, BLOCK_SIZE // 20):
                rec_start = i * 20
                if rec_start >= len(data):
                    return False
                if data[rec_start] == 0x2A:
                    return True
                if all(b == 0 for b in data[rec_start:rec_start + 20]):
                    return True
                if not is_valid_model_code(data[rec_start:rec_start + 6]):
                    return False
                if data[rec_start:rec_start + 6] != data[0:6]:
                    return False
            return False
        except Exception:
            return False

    def is_category_index_block_20(self, data: bytes) -> bool:
        """Detect 20-byte category index blocks (text variant). Byte 7 is a letter (C/T)."""
        if len(data) < 40:
            return False
        if not (0x41 <= data[7] <= 0x5A):  # byte 7 must be letter
            return False
        return self._is_block_20(data)

    def is_version_index_block_20(self, data: bytes) -> bool:
        """Detect 20-byte version index blocks (binary variant). Byte 7 is a digit (1-9)."""
        if len(data) < 40:
            return False
        if not (0x31 <= data[7] <= 0x39):  # byte 7 must be digit
            return False
        return self._is_block_20(data)

    def is_body_model_block_17(self, data: bytes) -> bool:
        """Detect 17-byte body model mapping blocks.

        Records are 7-char alphanumeric body code + 2-byte constant (0x0001) + 6-char model code + 2-byte config index.
        120 records per block (2040 bytes) + 8 bytes padding.
        """
        if len(data) < 34:
            return False
        try:
            # Check first record
            body1 = data[0:7].decode(CHARSET)
            if not (body1[0].isalpha() and body1.isalnum()):
                return False
            if data[7] != 0x00 or data[8] != 0x01:
                return False
            if not is_valid_model_code(data[9:15]):
                return False
            # Check second record
            body2 = data[17:24].decode(CHARSET)
            if not (body2[0].isalpha() and body2.isalnum()):
                return False
            if data[24] != 0x00 or data[25] != 0x01:
                return False
            if not is_valid_model_code(data[26:32]):
                return False
            return True
        except Exception:
            return False

    def is_body_model_range_block_18(self, data: bytes) -> bool:
        """Detect 18-byte body model range index blocks.

        Records: 7-byte model_from + 7-byte model_to + 4-byte block pointer.
        Pointer format: 00 b1 b2 00 (all records share the same b1).
        Terminated by asterisk sentinel.
        """
        if len(data) < 36:
            return False
        try:
            # Check first record
            mf1 = data[0:7].decode(CHARSET)
            if not (mf1[0].isalpha() and mf1[0].isupper() and mf1.isalnum()):
                return False
            mt1 = data[7:14].decode(CHARSET)
            if not (mt1[0].isalpha() and mt1[0].isupper() and mt1.isalnum()):
                return False
            # Pointer: byte 0 and 3 must be 0x00
            if data[14] != 0x00 or data[17] != 0x00:
                return False
            # Check second record
            rec2 = data[18:36]
            if rec2[0] == 0x2A:  # sentinel — valid single-entry block
                return True
            mf2 = rec2[0:7].decode(CHARSET)
            if not (mf2[0].isalpha() and mf2[0].isupper() and mf2.isalnum()):
                return False
            if rec2[14] != 0x00 or rec2[17] != 0x00:
                return False
            # Both pointers must share the same b1 (same section)
            if data[15] != rec2[15]:
                return False
            # b2 must increment by 1
            if rec2[16] != data[16] + 1:
                return False
            return True
        except Exception:
            return False

    def parse_body_model_range_records_18(self, data: bytes, base_offset: int = 0) -> List[BodyModelRangeRecord18]:
        """Parse 18-byte body model range index records from a single 2KB block.

        Returns list of BodyModelRangeRecord18.
        """
        records = []
        for i in range(BLOCK_SIZE // BodyModelRangeRecord18.RECORD_SIZE):
            start = i * BodyModelRangeRecord18.RECORD_SIZE
            rec = data[start:start + BodyModelRangeRecord18.RECORD_SIZE]
            if len(rec) < BodyModelRangeRecord18.RECORD_SIZE:
                break
            if rec[0] == 0x2A or rec[0] == 0x00:
                break
            records.append(BodyModelRangeRecord18.parse_18(rec, base_offset + start))
        return records

    def is_model_year_block_44(self, data: bytes) -> bool:
        if len(data) < 44:
            return False
        try:
            if not is_valid_model_code(data[0:6]):
                return False
            ver = data[6]
            if not (0x41 <= ver <= 0x5A):  # A-Z
                return False
            d1 = clean_nostrip(data[7:15])
            d2 = clean_nostrip(data[15:23])
            if not (d1.isdigit() and d2.isdigit()):
                return False
            return True
        except:
            return False

    def is_part_index_block_21(self, data: bytes) -> bool:
        if len(data) < 21 * 2:  # cant distinguish from is_part_index_block_34 if size is less than 2*21
            return False
        assert self.parts_catalog is not None
        return self.is_part_num(data[0:15]) and self.is_part_num(data[21:21 + 15])

    def is_part_index_block_34(self, data: bytes) -> bool:
        if len(data) < 34 * 2:
            return False
        assert self.parts_catalog is not None
        return self.is_part_num(data[0:15]) and self.is_part_num(data[15:30]) \
            and self.is_part_num(data[34:34 + 15]) and self.is_part_num(data[34 + 15:34 + 15 + 15])

    def is_itca_251(self, data: bytes) -> bool:
        if len(data) < 251 * 2:
            return False
        assert self.parts_catalog is not None
        return self.is_part_num(data[0:15]) and self.is_part_num(data[15:30]) \
            and self.is_part_num(data[251:251 + 15]) and self.is_part_num(data[251 + 15:251 + 15 + 15])

    def is_figure_index_block_22(self, data: bytes) -> bool:
        """
        Check if data looks like a 22-byte figure index record block.
        Uses figure_codes from figname.txt when available for precise matching.
        Falls back to digit heuristic when no figure codes loaded.
        """
        if len(data) < 44:
            return False

        try:
            # Check first record model code
            if not is_valid_model_code(data[0:6]):
                return False

            # First record figure code (5 bytes, e.g. "003  ")
            figure = clean(data[6:11])

            if self.figure_codes:
                # Precise: must be a known figure code from figname.txt
                if figure not in self.figure_codes:
                    return False
            else:
                # Fallback: require digits
                if not any(c.isdigit() for c in figure):
                    return False

            # Verify second record
            if not is_valid_model_code(data[22:28]):
                return False

            return True
        except:
            return False

    def is_spec_mapping_block_22(self, data: bytes) -> bool:
        """
        Check if data looks like a 22-byte spec mapping record block.
        Matches 22-byte records with valid model codes that are NOT figure index blocks.
        """
        if len(data) < 44:
            return False

        try:
            # Check first record model code
            if not is_valid_model_code(data[0:6]):
                return False

            # Code field (6-11) must NOT be a known figure code
            code = clean(data[6:11])
            if self.figure_codes and code in self.figure_codes:
                return False
            elif not self.figure_codes:
                # Fallback: reject if code has digits (likely figure index)
                if any(c.isdigit() for c in code):
                    return False

            # Verify second record
            if not (is_valid_model_code(data[22:28]) or (
                    data[22:22 + 22].decode(CHARSET, errors="replace") == "*" * 22)):
                return False

            return True
        except:
            return False

    def is_fig_group_category_block_184(self, data: bytes) -> bool:
        """Check if data looks like a 184-byte FIG group category record block."""
        return self._is_model_code_block(data, FIGGroupCategoryRecord184.RECORD_SIZE)

    def is_catalog_applicability_block_466(self, data: bytes) -> bool:
        """Check if data looks like a 466-byte catalog applicability record block."""
        return self._is_model_code_block(data, CatalogApplicabilityRecord466.RECORD_SIZE, allow_asterisk=True)

    def is_model_spec_block_103(self, data: bytes) -> bool:
        """Check if data looks like a 103-byte model spec record block."""
        return self._is_model_code_block(data, ModelSpecRecord103.RECORD_SIZE, allow_asterisk=True)

    def is_part_range_block_24(self, data: bytes) -> bool:
        """Check if data looks like a 24-byte part range record block."""
        return self._is_model_code_block(data, PartRangeRecord24.RECORD_SIZE)

    def is_model_index_block_288(self, data: bytes) -> bool:
        """Check if data looks like a 288-byte model index record block."""
        return self._is_model_code_block(data, ModelIndexRecord288.RECORD_SIZE)

    def is_multilingual_part_block_167(self, data: bytes) -> bool:
        """Check if data looks like a 167-byte multilingual part record block."""
        return self._is_model_code_block(data, MultilingualPartRecord167.RECORD_SIZE, allow_asterisk=True)

    def is_multilingual_part_block_180(self, data: bytes) -> bool:
        """Check if data looks like a 180-byte multilingual part record block."""
        return self._is_model_code_block(data, MultilingualPartRecord180.RECORD_SIZE, allow_asterisk=True)

    def is_multilingual_part_block_192(self, data: bytes) -> bool:
        """Check if data looks like a 192-byte multilingual part record block."""
        return self._is_model_code_block(data, MultilingualPartRecord192.RECORD_SIZE)

    def _parse_fixed_records(self, f: BinaryIO, start_offset: int, record_size: int, parse_fn,
                             max_records: Optional[int] = None, verbose: bool = False,
                             validator=None) -> list:
        """Generic helper to parse fixed-size records from a file stream."""
        if validator is None:
            validator = lambda data: is_valid_model_code(data[0:6])
        records = []
        f.seek(start_offset)
        count = 0
        while True:
            if max_records and count >= max_records:
                break
            offset = f.tell()
            data = f.read(record_size)
            if len(data) < record_size:
                break
            if not validator(data):
                break
            records.append(parse_fn(data, offset))
            if verbose and count % 1000 == 0:
                print(f"  Parsed {count} records at 0x{offset:08X}...")
            count += 1
        return records

    def _parse_text(self, f: BinaryIO, start_offset: int, record_cls, parse_fn,
                    max_records=None, verbose=False, validator=None) -> list:
        """Parse text records that need the region's record size + encoding."""
        p = self.profile
        size = p.size_for(record_cls.ID, record_cls.RECORD_SIZE)
        fn = lambda d, o: parse_fn(d, o, p.encoding)
        return self._parse_fixed_records(f, start_offset, size, fn, max_records, verbose, validator)

    def _parse_ml(self, f: BinaryIO, start_offset: int, record_cls, parse_fn,
                  max_records=None, verbose=False, validator=None) -> list:
        """Parse multilingual records: region size + encoding + language count
        (US carries 4 language fields, JDM 1)."""
        p = self.profile
        size = p.size_for(record_cls.ID, record_cls.RECORD_SIZE)
        fn = lambda d, o: parse_fn(d, o, p.encoding, p.num_languages)
        return self._parse_fixed_records(f, start_offset, size, fn, max_records, verbose, validator)

    def parse_code_index_records_33(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                    verbose: bool = False) -> List[CodeIndexRecord33]:
        return self._parse_text(f, start_offset, CodeIndexRecord33, CodeIndexRecord33.parse_33,
                                max_records, verbose)

    def parse_glossary_records_28(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                  verbose: bool = False) -> List[GlossaryRecord28]:
        return self._parse_text(f, start_offset, GlossaryRecord28, GlossaryRecord28.parse_28,
                                max_records, verbose)

    def parse_color_records_91(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                               verbose: bool = False) -> List[ColorRecord91]:
        return self._parse_ml(f, start_offset, ColorRecord91, ColorRecord91.parse_91,
                              max_records, verbose)

    def parse_part_group_records_185(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                     verbose: bool = False) -> List[PartGroupRecord185]:
        return self._parse_ml(f, start_offset, PartGroupRecord185, PartGroupRecord185.parse_185,
                              max_records, verbose)

    def parse_variant_glossary_records_81(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                          verbose: bool = False) -> List[VariantGlossaryRecord81]:
        return self._parse_text(f, start_offset, VariantGlossaryRecord81, VariantGlossaryRecord81.parse_81,
                                max_records, verbose)

    def parse_multilingual_part_records_182(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                            verbose: bool = False) -> List[MultilingualPartRecord182]:
        return self._parse_ml(f, start_offset, MultilingualPartRecord182, MultilingualPartRecord182.parse_182,
                              max_records, verbose)

    def parse_inventory_records_199(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                    verbose: bool = False) -> List[InventoryRecord199]:
        return self._parse_ml(f, start_offset, InventoryRecord199, InventoryRecord199.parse_199,
                              max_records, verbose)

    def parse_engine_spec_records_230(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                      verbose: bool = False) -> List[EngineSpecRecord230]:
        return self._parse_fixed_records(f, start_offset, EngineSpecRecord230.RECORD_SIZE,
                                         EngineSpecRecord230.parse_230, max_records, verbose)

    def parse_catalog_applicability_records_466(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                                verbose: bool = False) -> List[CatalogApplicabilityRecord466]:
        # The catalog record is reorganized (not just resized) between regions, so
        # dispatch on cat_size to the matching field map.
        p = self.profile
        if p.cat_size == 496:
            parse_fn = lambda d, o: CatalogApplicabilityRecord466.parse_496(d, o, p.encoding)
        else:
            parse_fn = CatalogApplicabilityRecord466.parse_466
        return self._parse_fixed_records(f, start_offset, p.cat_size, parse_fn, max_records, verbose)

    def parse_body_model_records_17(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                    verbose: bool = False) -> List[BodyModelRecord17]:
        records = []

        f.seek(start_offset)
        count = 0

        while True:
            if max_records and count >= max_records:
                break

            offset = f.tell()
            data = f.read(BodyModelRecord17.RECORD_SIZE)

            if len(data) < BodyModelRecord17.RECORD_SIZE:
                break

            # End marker: asterisks or all zeros
            if data[0] == 0x2A or all(b == 0 for b in data):
                break

            body = clean_nostrip(data[0:7])
            if not (body[0].isalpha() and body.isalnum()):
                break

            record = BodyModelRecord17.parse_17(data, offset)
            records.append(record)

            if verbose and count % 1000 == 0:
                print(f"  Parsed {count} records at 0x{offset:08X}...")

            count += 1

        return records

    def parse_model_year_records_44(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                    verbose: bool = False) -> List[ModelYearRecord44]:
        return self._parse_fixed_records(f, start_offset, ModelYearRecord44.RECORD_SIZE, ModelYearRecord44.parse_44,
                                         max_records, verbose)

    @staticmethod
    def _validate_20(data: bytes) -> bool:
        if all(b == 0x2a for b in data) or all(b == 0 for b in data):
            return False
        return is_valid_model_code(data[0:6])

    def parse_category_index_records_20(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                        verbose: bool = False) -> List[CategoryIndexRecord20]:
        return self._parse_fixed_records(f, start_offset, CategoryIndexRecord20.RECORD_SIZE,
                                         CategoryIndexRecord20.parse_20, max_records, verbose,
                                         validator=self._validate_20)

    def parse_version_index_records_20(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                       verbose: bool = False) -> List[VersionIndexRecord20]:
        return self._parse_fixed_records(f, start_offset, VersionIndexRecord20.RECORD_SIZE,
                                         VersionIndexRecord20.parse_20, max_records, verbose,
                                         validator=self._validate_20)

    def parse_part_index_records_34(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                    verbose: bool = False) -> List[PartRangeIndex34]:
        return self._parse_fixed_records(f, start_offset, PartRangeIndex34.RECORD_SIZE, PartRangeIndex34.parse_34,
                                         max_records, verbose,
                                         validator=lambda d: self.is_part_num(d[0:15]))

    def parse_itca_records_251(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                               verbose: bool = False) -> List[ItcaRecord]:
        return self._parse_fixed_records(f, start_offset, ItcaRecord.RECORD_SIZE, ItcaRecord.parse_itca_251,
                                         max_records, verbose,
                                         validator=lambda d: self.is_part_num(d[0:15]))

    def parse_part_index_records_21(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                    verbose: bool = False) -> List[PartIndex21]:
        return self._parse_fixed_records(f, start_offset, PartIndex21.RECORD_SIZE, PartIndex21.parse_21, max_records,
                                         verbose,
                                         validator=lambda d: self.is_part_num(d[0:15]))

    def parse_figure_index_records_22(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                      verbose: bool = False) -> List[FigureIndexRecord22]:
        return self._parse_fixed_records(f, start_offset, FigureIndexRecord22.RECORD_SIZE, FigureIndexRecord22.parse_22,
                                         max_records, verbose)

    def parse_spec_mapping_records_22(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                      verbose: bool = False) -> List[SpecMappingRecord22]:
        return self._parse_fixed_records(f, start_offset, SpecMappingRecord22.RECORD_SIZE, SpecMappingRecord22.parse_22,
                                         max_records, verbose)

    def parse_fig_illustration_page_records_89(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                               verbose: bool = False) -> List[FIGIllustrationPage89]:
        return self._parse_fixed_records(f, start_offset, FIGIllustrationPage89.RECORD_SIZE,
                                         FIGIllustrationPage89.parse_89, max_records, verbose)

    def parse_fig_illustration_records_183(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                           verbose: bool = False) -> List[FIGIllustrationRecord183]:
        return self._parse_ml(f, start_offset, FIGIllustrationRecord183, FIGIllustrationRecord183.parse_183,
                              max_records, verbose)

    def parse_fig_group_category_records_184(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                             verbose: bool = False) -> List[FIGGroupCategoryRecord184]:
        return self._parse_ml(f, start_offset, FIGGroupCategoryRecord184, FIGGroupCategoryRecord184.parse_184,
                              max_records, verbose)

    def parse_model_spec_records_103(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                     verbose: bool = False) -> List[ModelSpecRecord103]:
        return self._parse_text(f, start_offset, ModelSpecRecord103, ModelSpecRecord103.parse_103,
                                max_records, verbose)

    def parse_model_index_records_288(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                      verbose: bool = False) -> List[ModelIndexRecord288]:
        return self._parse_fixed_records(f, start_offset, ModelIndexRecord288.RECORD_SIZE,
                                         ModelIndexRecord288.parse_288, max_records, verbose)

    def parse_part_range_records_24(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                    verbose: bool = False) -> List[PartRangeRecord24]:
        return self._parse_fixed_records(f, start_offset, PartRangeRecord24.RECORD_SIZE, PartRangeRecord24.parse_24,
                                         max_records, verbose)

    def parse_multilingual_part_records_167(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                            verbose: bool = False) -> List[MultilingualPartRecord167]:
        # 167 has a single description field + a binary bitmask (no 4->1 collapse),
        # so it only needs the region encoding, not the language count.
        return self._parse_text(f, start_offset, MultilingualPartRecord167, MultilingualPartRecord167.parse_167,
                                max_records, verbose)

    def parse_multilingual_part_records_180(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                            verbose: bool = False) -> List[MultilingualPartRecord180]:
        return self._parse_ml(f, start_offset, MultilingualPartRecord180, MultilingualPartRecord180.parse_180,
                              max_records, verbose)

    def parse_multilingual_part_records_192(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                            verbose: bool = False) -> List[MultilingualPartRecord192]:
        return self._parse_ml(f, start_offset, MultilingualPartRecord192, MultilingualPartRecord192.parse_192,
                              max_records, verbose)

    def detect_vin_record_type(self, data: bytes) -> str:
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
                if is_valid_model_code(data[19:25]):
                    return 'vin_model'
        except:
            pass

        return 'unknown'

    def parse_vin_model_records(self, f: BinaryIO, start_offset: int, max_records: Optional[int] = None,
                                verbose: bool = False) -> List[VINModelRecord]:
        p = self.profile
        idl = p.vin_id_len
        if p.name == 'JDM':
            size, parse_fn = 68, lambda d, o: VINModelRecord.parse_jdm68(d, o, p.encoding)
        else:
            size, parse_fn = 69, VINModelRecord.parse_69
        return self._parse_fixed_records(
            f, start_offset, size, parse_fn, max_records, verbose,
            validator=lambda d: is_valid_vehicle_id(
                d[0:idl].decode(p.encoding, errors='replace').strip('\x00'), p))

    def parse_vin_blocks(self, f: BinaryIO, start_offset: int = 0x800, max_records: Optional[int] = None,
                         verbose: bool = False) -> List[VINRecord]:
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
        records = []

        f.seek(start_offset)
        count = 0

        while True:
            if max_records and count >= max_records:
                break

            offset = f.tell()
            data = f.read(self.profile.vin_record_size)

            if len(data) < self.profile.vin_record_size:
                break

            record = VINRecord.parse_range(data, offset, self.profile.vin_id_len)

            # Validate - must be a valid vehicle id for the region
            if not is_valid_vehicle_id(record.vin_start, self.profile):
                break

            records.append(record)

            if verbose and count % 100 == 0:
                print(f"  Parsed {count} records at 0x{offset:06X}...")

            count += 1

        return records

    def detect_block_type(self, data: bytes, offset: int = 0) -> str:
        """
        Detect the type of a 2KB block.

        Args:
            data: 2048 bytes of block data
            offset: File offset of this block (used for header detection)

        Returns:
            Block type string: 'header', 'vin', 'model_index',
            'body_model', 'text', 'binary', 'padding', 'unknown'
        """

        if len(data) < BLOCK_SIZE:
            return 'incomplete'

        # 1. Header block (first 2KB contains header + model table + padding)
        if offset < 0x800:
            return 'header'

        # 2. All zeros = padding
        if all(b == 0 for b in data):
            return 'padding'

        # 2b. Asterisk-padded empty block: contiguous 0x2A then contiguous 0x00
        if data[0] == 0x2A:
            first_zero = data.index(0x00) if 0x00 in data else BLOCK_SIZE
            if first_zero > 0 and data[:first_zero] == b'\x2a' * first_zero and all(b == 0 for b in data[first_zero:]):
                return 'empty'

        # 3. VIN block - first 17 bytes are a valid Subaru VIN
        # Distinguish between 38-byte VIN range records and 69-byte VIN-Model records
        try:
            vin = clean_nostrip(data[0:17])
            if is_valid_subaru_vin(vin):
                vin_type = self.detect_vin_record_type(data)
                if vin_type == 'vin_range':
                    return 'vin_range'
                elif vin_type == 'vin_model':
                    return 'vin_model'
                else:
                    return 'vin'  # Fallback for unknown VIN format
        except:
            pass

        if self.is_part_range_block_24(data):
            return PartRangeRecord24.ID

        if self.is_category_index_block_20(data):
            return CategoryIndexRecord20.ID

        if self.is_version_index_block_20(data):
            return VersionIndexRecord20.ID

        if self.is_multilingual_part_block_192(data):
            return MultilingualPartRecord192.ID

        if self.is_multilingual_part_block_180(data):
            return MultilingualPartRecord180.ID

        if self.is_multilingual_part_block_167(data):
            return MultilingualPartRecord167.ID

        if self.is_model_spec_block_103(data):
            return ModelSpecRecord103.ID

        # 4f. Catalog applicability block (466-byte) - NEW
        if self.is_catalog_applicability_block_466(data):
            return CatalogApplicabilityRecord466.ID

        # 4g. Color record block (91-byte) - NEW
        if self.is_color_record_block_91(data):
            return ColorRecord91.ID

        # 4h. Glossary record block (28-byte) - NEW
        if self.is_glossary_record_block_28(data):
            return GlossaryRecord28.ID

        # 4i. Code index record block (33-byte) - NEW
        if self.is_code_index_record_block_33(data):
            return CodeIndexRecord33.ID

        # 4j. Model index block (288-byte) - NEW
        if self.is_model_index_block_288(data):
            return ModelIndexRecord288.ID

        # 4k. FIG group category block (184-byte) - NEW
        if self.is_fig_group_category_block_184(data):
            return FIGGroupCategoryRecord184.ID

        # 4l. FIG illustration block (183-byte) - NEW
        if self.is_fig_illustration_block_183(data):
            return FIGIllustrationRecord183.ID

        # 4m. FIG illustration page block (89-byte) - NEW
        if self.is_fig_illustration_page_block_89(data):
            return FIGIllustrationPage89.ID

        # 4n. Engine spec block (230-byte) - NEW
        if self.is_engine_spec_block_230(data):
            return EngineSpecRecord230.ID

        # 4o. Part group block (185-byte) - NEW
        if self.is_part_group_block_185(data):
            return PartGroupRecord185.ID

        # 4p. Variant glossary block (81-byte) - NEW
        if self.is_variant_glossary_block_81(data):
            return VariantGlossaryRecord81.ID

        # 4q. Inventory record block (199-byte) - NEW
        if self.is_inventory_block_199(data):
            return InventoryRecord199.ID

        # 4r. Multilingual part block (182-byte) - NEW
        if self.is_multilingual_part_block_182(data):
            return MultilingualPartRecord182.ID

        # 4s. Figure index block (22-byte) - NEW
        if self.is_figure_index_block_22(data):
            return FigureIndexRecord22.ID

        # 4t. Spec mapping block (22-byte) - NEW
        if self.is_spec_mapping_block_22(data):
            return SpecMappingRecord22.ID

        if self.is_part_index_block_34(data):
            return PartRangeIndex34.ID

        if self.is_part_index_block_21(data):
            return PartIndex21.ID

        if self.is_itca_251(data):
            return ItcaRecord.ID

        if self.is_model_year_block_44(data):
            return ModelYearRecord44.ID

        # 5. Body model block - 17-byte records with 7-char body code + model code
        if self.is_body_model_block_17(data):
            return BodyModelRecord17.ID

        # 6. Text block - mostly printable ASCII
        non_zero = sum(1 for b in data if b != 0)
        printable_count = sum(1 for b in data if 32 <= b <= 126 or b in (9, 10, 13))
        printable_ratio = printable_count / non_zero
        # print(f"0x{offset:08X} printable_ratio: {printable_ratio} = {printable_count} / {non_zero}")

        if printable_ratio >= 0.8:
            return 'text'

        # 7. Binary block - low printable ratio, has content
        if non_zero > 0 and printable_ratio < 0.55:
            return 'binary'

        # 8. Mixed content
        if printable_ratio >= 0.55:
            return 'mixed'

        return 'unknown'

    def scan_block_types(self, f: BinaryIO, max_blocks: Optional[int] = None) -> List[Tuple[int, int, int, str]]:
        """
        Scan entire file block by block and return map of ranges to types.

        Args:
            f: File handle to sffastus
            max_blocks: Maximum blocks to scan (None = entire file)

        Returns:
            List of (start_offset, end_offset, block_count, block_type) tuples.
            Consecutive blocks of same type are merged into ranges.
        """

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

            block_type = self.detect_block_type(data, offset)
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
                quantity = qty_str
                part_code = line[37:45].strip()
                description = line[45:85].strip()

                records.append(ItcaRecord(
                    offset=0,
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


def parse_figname_txt(file_path: str) -> List[FigNameRecord]:
    """Parse FIGNAME.TXT and return a list of FigNameRecord objects.

    Args:
        file_path: Path to figname.txt file

    Returns:
        List of FigNameRecord objects

    File format:
        - Fixed-width ASCII, 44 bytes per line
        - 3-char figure code + 41-char description
        - No delimiters, direct concatenation
        - Each line is exactly 44 characters
    """
    records = []
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return records

    with open(file_path, 'r', encoding='ascii', errors='replace') as f:
        for line_num, line in enumerate(f, 1):
            # Remove trailing newline/whitespace but preserve internal spacing
            line = line.rstrip('\r\n')

            if len(line) < 3:
                continue

            try:
                record = FigNameRecord.parse(line)
                records.append(record)
            except Exception as e:
                print(f"Error parsing line {line_num}: {e}")

    return records


def analyze_vin_blocks(f: BinaryIO, start_offset: int = 0x800, max_records: int = 2000) -> dict:
    """
    Analyze VIN block structure and print statistics.

    Returns dict with analysis results.
    """
    print(f"\n=== Analyzing VIN Blocks at 0x{start_offset:X} ===")

    parser = SffastusBlockParser()
    records = parser.parse_vin_blocks(f, start_offset, max_records, verbose=True)

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


def scan_vin_blocks_2kb(f: BinaryIO, min_contiguous: int = 5) -> List[Tuple[int, int, int]]:
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

        vin = clean_nostrip(data)

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


def analyze_vin_blocks_2kb(f: BinaryIO, min_contiguous: int = 5) -> List[Tuple[int, int, int]]:
    """
    Analyze 2KB VIN block structure and print report.
    """
    f.seek(0, 2)
    file_size = f.tell()

    print(f"\n=== 2KB VIN Block Analysis ===")
    print(f"File size: {file_size:,} bytes ({file_size / 1024 / 1024:.1f} MB)")

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
        end = start + blocks * BLOCK_SIZE
        print(f"0x{start:08X}  0x{end:08X}  {blocks:8d}  ~{records:9d}")

    print("-" * 46)
    print(f"{'Total':>26}  {total_blocks:8d}  ~{total_records:9d}")
    print(f"\nTotal VIN data: {total_blocks * BLOCK_SIZE / 1024 / 1024:.2f} MB")

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


def decode_block_pointer(ptr: bytes) -> int:
    """Decode a 3-byte block pointer to an absolute block number.

    Format: [byte0] [byte1] [byte2] (in a 4-byte field, byte3 is padding)
    Formula from SFCOMMON.DLL FUN_100012f0:
      block_number = (byte1 - 4 + byte0 * 60) * 75 + byte2
      file_offset  = block_number * 2048

    For section-level pointers where byte0=0, reduces to (byte1 - 4) * 75 + byte2.
    Verified across SFCDUS1/2/3 for all section-level pointers.
    """
    return (ptr[1] - 4 + ptr[0] * 60) * 75 + ptr[2]


def encode_block_pointer(block: int) -> bytes:
    """Encode an absolute block number into a 4-byte pointer.

    Inverse of decode_block_pointer.
    """
    b2 = block % 75
    q = block // 75
    b0 = q // 60
    b1 = q % 60 + 4
    return bytes([b0, b1, b2, 0x00])


def decode_fig_data_pointer(ptr: bytes) -> int:
    """Decode a 4-byte figure data pointer to an absolute file offset.

    Format: [marker] [byte1] [byte2] [byte3]
    Formula from SFCOMMON.DLL OffsetCalculator (FUN_100012f0):
      offset = ((byte1 - 4 + marker * 60) * 75 + byte2) * 2048 + byte3 * 8

    Extends decode_block_pointer with sub-block precision via byte3 * 8.
    """
    return decode_block_pointer(ptr) * BLOCK_SIZE + ptr[3] * 8


# Mapping from block type ID to index in ModelIndexRecord288.block_index_array.
# Entries 0-29 are block pointers (4 bytes each), entries 30-44 are count pairs.
# Indices 16-18, 23 are raw CCITT G4 figure image data (no record structure).
# Index 20 is a NULL separator (all zeros).
MODEL_BLOCK_INDEX = {
    MultilingualPartRecord167.ID: 0,  # multilingual_part_167
    CategoryIndexRecord20.ID: 1,  # category_index_20
    PartRangeRecord24.ID: 2,  # part_range_24
    MultilingualPartRecord180.ID: 3,  # multilingual_part_180
    ModelSpecRecord103.ID: 4,  # model_spec_103
    MultilingualPartRecord192.ID: 5,  # multilingual_part_192
    CatalogApplicabilityRecord466.ID: 6,  # catalog_applicability_466
    ColorRecord91.ID: 7,  # color_record_91
    GlossaryRecord28.ID: 8,  # glossary_record_28
    CodeIndexRecord33.ID: 9,  # code_index_record_33
    FIGGroupCategoryRecord184.ID: 10,  # fig_group_category_184
    FIGIllustrationRecord183.ID: 11,  # fig_illustration_183
    FIGIllustrationPage89.ID: 12,  # fig_illustration_page_89
    EngineSpecRecord230.ID: 13,  # engine_spec_230
    PartGroupRecord185.ID: 14,  # part_group_185
    InventoryRecord199.ID: 15,  # inventory_199
    # 16: figure_image_a (binary CCITT G4)
    # 17: figure_image_b (binary CCITT G4)
    # 18: figure_image_c (binary CCITT G4, main bulk)
    VariantGlossaryRecord81.ID: 19,  # variant_glossary_81
    # 20: NULL separator
    VersionIndexRecord20.ID: 21,  # version_index_20
    # 22: fig_illustration_183_b (by-book variant)
    # 23: figure_image_d (binary CCITT G4)
    ModelYearRecord44.ID: 24,  # model_year_44
    MultilingualPartRecord182.ID: 25,  # multilingual_part_182
    # 26: code_index_33_b (secondary)
    FigureIndexRecord22.ID: 27,  # figure_index_22
    SpecMappingRecord22.ID: 28,  # spec_mapping_22 (a)
    # 29: spec_mapping_22_b
}

# Count pair layout: entries 30-44, each 4 bytes = 2 BE uint16 counts.
# Maps (array_index, hi_or_lo) -> pointer index.
# hi=True means first uint16 in the 4-byte entry, lo=True means second.
MODEL_BLOCK_COUNTS = {
    0: (30, 'hi'), 1: (30, 'lo'),
    2: (31, 'hi'), 3: (31, 'lo'),
    4: (32, 'hi'), 5: (32, 'lo'),
    6: (33, 'hi'), 7: (33, 'lo'),
    8: (34, 'hi'), 9: (34, 'lo'),
    10: (35, 'hi'), 11: (35, 'lo'),
    12: (36, 'hi'), 13: (36, 'lo'),
    14: (37, 'hi'), 15: (37, 'lo'),
    # 16: entry [38] hi is anomalous (NOT a block count)
    17: (38, 'lo'),
    18: (39, 'hi'), 19: (39, 'lo'),
    # 20: NULL, no count
    21: (40, 'lo'),
    22: (41, 'hi'), 23: (41, 'lo'),
    24: (42, 'hi'), 25: (42, 'lo'),
    26: (43, 'hi'), 27: (43, 'lo'),
    28: (44, 'hi'), 29: (44, 'lo'),
}


# Known region profiles, keyed by detected model-record size.
US_PROFILE = RegionProfile(
    name='US', model_record_size=288, encoding='cp437', num_languages=4,
    count_region_start=30, cat_size=466, vin_record_size=38, vin_id_len=17,
)
# JDM record-size overrides (verified by record tiling on 30804SF/SFFASTA).
# Multilingual records collapse 4 language fields (EN/DE/FR/ES) to 1 (JP):
# size = US_size - 3*field_width, except inventory which gains a 14-byte trailer.
# glossary/code_index shrink by 1; model_spec gains an 8-byte tail code.
JDM_RECORD_SIZES = {
    'color_record_91': 31,
    'fig_group_category_184': 64,
    'fig_illustration_183': 63,
    'part_group_185': 65,
    'inventory_199': 93,
    'multilingual_part_182': 62,
    'multilingual_part_180': 60,
    'multilingual_part_192': 72,
    'glossary_record_28': 27,
    'code_index_record_33': 32,
    'model_spec_103': 111,
    # catalog_applicability size comes from profile.cat_size (496)
}
JDM_PROFILE = RegionProfile(
    name='JDM', model_record_size=420, encoding='cp932', num_languages=1,
    count_region_start=52, cat_size=496, vin_record_size=22, vin_id_len=9,
    record_sizes=JDM_RECORD_SIZES,
)
REGION_PROFILES = {p.model_record_size: p for p in (US_PROFILE, JDM_PROFILE)}


def detect_region_profile(first_model_block: bytes) -> RegionProfile:
    """Detect the RegionProfile from the first model-index record.

    The model record's size is a per-file constant. We find it by anchoring on
    the text trailer's start_date+end_date (12 consecutive ASCII digits that
    follow the binary block-pointer array): record_size = date_offset + 85.
    The detected size selects a known profile from REGION_PROFILES.

    Raises ValueError if the size does not match a supported profile.
    """
    import re
    if not (first_model_block[0:1].isalpha() and first_model_block[3:6] == b'   '):
        raise ValueError("Block does not start with a model code; not a model index block")
    m = re.search(rb'(?<![0-9])[0-9]{6}[0-9]{6}', first_model_block[100:])
    if not m:
        raise ValueError("Could not locate model-record date trailer for region detection")
    record_size = 100 + m.start() + 85
    profile = REGION_PROFILES.get(record_size)
    if profile is None:
        raise ValueError(
            f"Unsupported model-record size {record_size}; "
            f"known: {sorted(REGION_PROFILES)}")
    return profile


def parse_model_index(f: BinaryIO, header: SffastusHeader,
                      profile: Optional['RegionProfile'] = None) -> dict[str, ModelIndexRecord288]:
    """Parse all ModelIndexRecord288 entries from the model index area.

    Records are a fixed per-file size (profile.model_record_size); they are
    block-aligned and do not span 2KB block boundaries (the block tail is
    zero-padded when a full record does not fit).
    """
    if profile is None:
        profile = US_PROFILE
    rec_size = profile.model_record_size
    models = {}
    offset = header.model_index_start_block * BLOCK_SIZE
    records_per_block = BLOCK_SIZE // rec_size
    for block_idx in range(header.model_index_count):
        block_offset = offset + block_idx * BLOCK_SIZE
        for i in range(records_per_block):
            rec_offset = block_offset + i * rec_size
            f.seek(rec_offset)
            data = f.read(rec_size)
            if len(data) < rec_size:
                return models
            mc = clean(data[0:6], profile.encoding)
            if not mc or not mc[0].isalnum():
                break  # padding at block tail; next record starts at next block
            rec = ModelIndexRecord288.parse_288(data, rec_offset, profile)
            models[rec.model_code] = rec
    return models


def get_model_block_section(model_rec: ModelIndexRecord288, block_type_id: str,
                            profile: Optional['RegionProfile'] = None) -> Tuple[int, int]:
    """Get (file_offset, block_count) for a block type from a ModelIndexRecord288.

    The slot->type map (MODEL_BLOCK_INDEX) is shared across regions, but the
    count-pair region starts at a region-specific slot (profile.count_region_start);
    MODEL_BLOCK_COUNTS is expressed against the US baseline and shifted here.

    Returns (offset, count), or (0, 0) if not found.
    """
    if profile is None:
        profile = US_PROFILE
    idx = MODEL_BLOCK_INDEX.get(block_type_id)
    if idx is None:
        return (0, 0)

    # Decode block pointer from array entry
    arr = model_rec.block_index_array
    ptr_bytes = arr[idx * 4: idx * 4 + 4]
    if ptr_bytes == b'\x00\x00\x00\x00':
        return (0, 0)
    block_num = decode_block_pointer(ptr_bytes)
    file_offset = block_num * BLOCK_SIZE

    # Get block count from count pairs (count region shifted per region)
    count_info = MODEL_BLOCK_COUNTS.get(idx)
    if count_info is None:
        return (file_offset, 0)
    count_entry_idx, hi_lo = count_info
    count_entry_idx += profile.count_region_start - US_COUNT_REGION_START
    count_bytes = arr[count_entry_idx * 4: count_entry_idx * 4 + 4]
    if hi_lo == 'hi':
        count = (count_bytes[0] << 8) | count_bytes[1]
    else:
        count = (count_bytes[2] << 8) | count_bytes[3]

    return (file_offset, count)


def iter_model_blocks(model_rec: ModelIndexRecord288, block_type_id: str,
                      profile: Optional['RegionProfile'] = None) -> Generator[int, None, None]:
    """Yield block offsets for a block type from a ModelIndexRecord288."""
    offset, count = get_model_block_section(model_rec, block_type_id, profile)
    for i in range(count):
        yield offset + i * BLOCK_SIZE


def print_block_type_map(ranges: List[Tuple[int, int, int, str]]) -> None:
    """
    Print a formatted block type map.

    Args:
        ranges: List from self.scan_block_types()
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


def main() -> None:
    if not os.path.exists(SFFASTUS_PATH):
        print(f"Error: {SFFASTUS_PATH} not found")
        print(f"Current directory: {os.getcwd()}")
        sys.exit(1)

    file_size = os.path.getsize(SFFASTUS_PATH)
    print(f"=== Subaru FAST2 sffastus Analyzer ===")
    print(f"File: {SFFASTUS_PATH}")
    print(f"Size: {file_size:,} bytes ({file_size / 1024 / 1024:.1f} MB)")

    with open(SFFASTUS_PATH, 'rb') as f:
        # 1. Parse known structures
        print("\n" + "=" * 60)
        print("PHASE 1: Known Structure Analysis")
        print("=" * 60)

        # Header
        print("\n=== Header (0x00-0x30) ===")
        f.seek(0)
        header = f.read(0x32)
        for i in range(0, len(header), 16):
            hex_part = ' '.join(f'{b:02x}' for b in header[i:i + 16])
            print(f"  {i:04X}: {hex_part}")

        # Model table
        models = parse_model_table(f)

        # US VIN section
        analyze_vin_section(f, 0x800, 5)

        # JDM VIN section
        analyze_vin_section(f, 0x260400, 5)

        # 2. Pattern analysis
        print("\n" + "=" * 60)
        print("PHASE 2: Pattern Analysis")
        print("=" * 60)
        scan_for_patterns(f, file_size)

        # 3. Search for images
        print("\n" + "=" * 60)
        print("PHASE 3: Image Search")
        print("=" * 60)
        images = search_for_images(f, file_size)
        print(f"\nTotal images found: {len(images)}")

        # 4. Multilingual text search
        print("\n" + "=" * 60)
        print("PHASE 4: Multilingual Text Analysis")
        print("=" * 60)
        text_regions = analyze_text_regions(f, file_size)

        # 5. Section boundary detection (can be slow for large files)
        print("\n" + "=" * 60)
        print("PHASE 5: Section Boundary Detection")
        print("=" * 60)
        # Only scan first 100MB for boundaries to save time
        boundaries = find_section_boundaries(f, min(file_size, 100 * 1024 * 1024))

        # 6. Sample random offsets user mentioned
        print("\n" + "=" * 60)
        print("PHASE 6: Random Offset Sampling")
        print("=" * 60)

        # Sample at various points throughout the file
        sample_offsets = [
            0x1000000,  # 16 MB
            0x5000000,  # 80 MB
            0xA000000,  # 160 MB
            0xF000000,  # 240 MB
            0x14000000,  # 320 MB
            0x19000000,  # 400 MB
            0x1E000000,  # 480 MB
        ]

        for offset in sample_offsets:
            if offset < file_size:
                extract_record_at_offset(f, offset, 128)

        print("\n" + "=" * 60)
        print("ANALYSIS COMPLETE")
        print("=" * 60)

        # Summary
        print(f"\nSummary:")
        print(f"  - File size: {file_size / 1024 / 1024:.1f} MB")
        print(f"  - Model codes found: {len(models)}")
        print(f"  - Images detected: {len(images)}")
        print(f"  - Text regions found: {len(text_regions)}")
        print(f"  - Section boundaries: {len(boundaries)}")


if __name__ == '__main__':
    main()
