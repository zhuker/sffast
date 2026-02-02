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

SFFASTUS_PATH = "sffastus"

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
            text = data.decode('latin-1').replace('\x00', ' ').strip()
            result['sample'] = text[:200]
            result['details']['language'] = detect_language(text)
        except:
            pass
        return result

    # Check for VIN-like patterns (4S3 or JF1)
    try:
        text = data.decode('latin-1', errors='ignore')
        if '4S3' in text or 'JF1' in text:
            result['type'] = 'vin_data'
            return result
    except:
        pass

    # Mixed binary/text
    if is_printable_text(data, 0.3):
        result['type'] = 'mixed_binary_text'
        try:
            # Extract readable strings
            text = data.decode('latin-1', errors='ignore')
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
                        s = current_string.decode('latin-1')
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

        code = entry[:6].decode('latin-1').strip()
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
            vin1 = record[0:17].decode('latin-1').strip('\x00')
            vin2 = record[17:34].decode('latin-1').strip('\x00')
            ptr = struct.unpack('<I', record[34:38])[0]

            if vin1 and (vin1.startswith('4S3') or vin1.startswith('JF1')):
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
                    context_str = context.decode('latin-1', errors='replace')
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
