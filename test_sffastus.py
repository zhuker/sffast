#!/usr/bin/env python3
"""
Unit tests for sffastus_parser.py
Run from project root: python3 -m pytest test_sffastus.py -v
Or directly: python3 test_sffastus.py
"""

import os
import sys
import unittest

# Import parser functions
from sffastus_parser import (
    parse_model_table,
    parse_vin_blocks,
    parse_vin_model_records,
    parse_multilingual_part_records,
    parse_multilingual_part_records,
    parse_multilingual_part_records_180,
    parse_multilingual_part_records_167,
    analyze_vin_blocks,
    scan_vin_blocks_2kb,
    analyze_vin_blocks_2kb,
    is_valid_subaru_vin,
    is_valid_subaru_vin_strict,
    is_valid_model_code,
    is_multilingual_part_block,
    is_multilingual_part_block_180,
    is_multilingual_part_block_167,
    detect_block_type,
    detect_vin_record_type,
    scan_block_types,
    print_block_type_map,
    SUBARU_VIN_PREFIXES,
    MODEL_CODE_PREFIXES,
    VINRecord,
    VINModelRecord,
    MultilingualPartRecord,
    MultilingualPartRecord180,
    MultilingualPartRecord167,
)

# Test data paths
SFCDUS1_PATH = "SFCDUS1/sffastus"
SFCDUS2_PATH = "SFCDUS2/sffastus"
SFCDUS3_PATH = "SFCDUS3/sffastus"


class TestVINValidation(unittest.TestCase):
    """Tests for VIN validation functions"""

    def test_valid_prefixes(self):
        """Test that all documented prefixes are accepted"""
        self.assertTrue(is_valid_subaru_vin("4S3BD3350T1200011"))  # US
        self.assertTrue(is_valid_subaru_vin("JF1GD70655L510047"))  # Japan JF1
        self.assertTrue(is_valid_subaru_vin("JF2SJAAC5FH123456"))  # Japan JF2

    def test_invalid_prefixes(self):
        """Test that non-Subaru VINs are rejected"""
        self.assertFalse(is_valid_subaru_vin("1G1YY22G965109876"))  # GM
        self.assertFalse(is_valid_subaru_vin("WVWZZZ3CZWE012345"))  # VW
        self.assertFalse(is_valid_subaru_vin(""))
        self.assertFalse(is_valid_subaru_vin("AB"))

    def test_prefix_constant(self):
        """Test that SUBARU_VIN_PREFIXES includes expected values"""
        self.assertIn('4S3', SUBARU_VIN_PREFIXES)
        self.assertIn('JF1', SUBARU_VIN_PREFIXES)
        self.assertIn('JF2', SUBARU_VIN_PREFIXES)

    def test_strict_validation(self):
        """Test strict VIN validation with length check"""
        # Valid 17-char VIN
        self.assertTrue(is_valid_subaru_vin_strict("4S3BD3350T1200011"))
        # Too short
        self.assertFalse(is_valid_subaru_vin_strict("4S3BD3350T12"))
        # Invalid chars (I, O, Q not allowed in VINs)
        self.assertFalse(is_valid_subaru_vin_strict("4S3BD3350I1200011"))


class TestVINBlocks(unittest.TestCase):
    """Tests for VIN block parsing"""

    @classmethod
    def setUpClass(cls):
        """Check if test data files exist"""
        cls.has_us1 = os.path.exists(SFCDUS1_PATH)
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)
        cls.has_us3 = os.path.exists(SFCDUS3_PATH)

    def test_parse_vin_blocks_us2_first_10(self):
        """Parse first 10 VIN records from SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parse_vin_blocks(f, start_offset=0x800, max_records=10)

        self.assertEqual(len(records), 10)

        # First record should be a 4S3 (US) VIN
        self.assertTrue(records[0].vin_start.startswith('4S3'))
        self.assertTrue(records[0].vin_end.startswith('4S3'))

        # Records should be at consecutive offsets (38 bytes each)
        for i in range(1, len(records)):
            self.assertEqual(records[i].offset - records[i-1].offset, 38)

    def test_parse_vin_blocks_us2_section_structure(self):
        """Verify VIN records have section and index fields"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parse_vin_blocks(f, start_offset=0x800, max_records=100)

        self.assertGreater(len(records), 0)

        # All records should have valid section numbers
        for rec in records:
            self.assertIsInstance(rec.section, int)
            self.assertIsInstance(rec.index, int)
            self.assertGreaterEqual(rec.section, 0)
            self.assertGreaterEqual(rec.index, 0)

    def test_parse_vin_blocks_us1(self):
        """Parse VIN records from SFCDUS1 (oldest data)"""
        if not self.has_us1:
            self.skipTest("SFCDUS1/sffastus not found")

        with open(SFCDUS1_PATH, 'rb') as f:
            records = parse_vin_blocks(f, start_offset=0x800, max_records=10)

        self.assertGreater(len(records), 0)
        # Oldest database should also have 4S3 or JF1 VINs
        self.assertTrue(
            records[0].vin_start.startswith('4S3') or
            records[0].vin_start.startswith('JF1')
        )

    def test_parse_vin_blocks_us3(self):
        """Parse VIN records from SFCDUS3 (newest data)"""
        if not self.has_us3:
            self.skipTest("SFCDUS3/sffastus not found")

        with open(SFCDUS3_PATH, 'rb') as f:
            records = parse_vin_blocks(f, start_offset=0x800, max_records=10)

        self.assertGreater(len(records), 0)

    def test_vin_record_dataclass(self):
        """Test VINRecord dataclass structure"""
        rec = VINRecord(
            offset=0x800,
            vin_start="4S3BD3350T1200011",
            vin_end="4S3BD4350V7205795",
            section=4,
            index=41,
            raw_data=b'\x00' * 38
        )
        self.assertEqual(rec.offset, 0x800)
        self.assertEqual(rec.section, 4)
        self.assertEqual(rec.index, 41)
        self.assertEqual(len(rec.vin_start), 17)


class TestModelTable(unittest.TestCase):
    """Tests for model table parsing"""

    @classmethod
    def setUpClass(cls):
        cls.has_us1 = os.path.exists(SFCDUS1_PATH)
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_parse_model_table_us1(self):
        """Parse model table from SFCDUS1"""
        if not self.has_us1:
            self.skipTest("SFCDUS1/sffastus not found")

        with open(SFCDUS1_PATH, 'rb') as f:
            models = parse_model_table(f)

        self.assertGreater(len(models), 0)
        # SFCDUS1 should have A10, B10, C10, etc.
        model_codes = [m[0] for m in models]
        self.assertTrue(any('A10' in code or 'B10' in code for code in model_codes))

    def test_parse_model_table_us2(self):
        """Parse model table from SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            models = parse_model_table(f)

        self.assertGreater(len(models), 0)

        # Check known model codes exist
        model_codes = [m[0] for m in models]
        # SFCDUS2 should have B11, B12, G10, G11, etc.
        self.assertTrue(any('B1' in code for code in model_codes))


class TestAnalyzeVINBlocks(unittest.TestCase):
    """Integration tests for VIN block analysis"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_analyze_vin_blocks_us2(self):
        """Full analysis of VIN blocks in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            result = analyze_vin_blocks(f, start_offset=0x800, max_records=500)

        self.assertIn('records', result)
        self.assertIn('sections', result)
        self.assertIn('total', result)
        self.assertGreater(result['total'], 0)


class TestVINBlocks2KB(unittest.TestCase):
    """Tests for 2KB VIN block scanning"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_scan_vin_blocks_2kb_us2(self):
        """Scan for 2KB VIN blocks in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            regions = scan_vin_blocks_2kb(f, min_contiguous=5)

        self.assertGreater(len(regions), 0)

        # Each region should have (start, blocks, records)
        for start, blocks, records in regions:
            self.assertGreaterEqual(blocks, 5)
            self.assertEqual(records, blocks * 53)  # ~53 records per block

    def test_analyze_vin_blocks_2kb_us2(self):
        """Full 2KB block analysis of SFCDUS2"""
        # if not self.has_us2:
        #     self.skipTest("SFCDUS2/sffastus not found")

        with open("SFCDUS3/sffastus", 'rb') as f:
            regions = analyze_vin_blocks_2kb(f, min_contiguous=10)

        # Should find at least one large region
        self.assertGreater(len(regions), 0)
        # Largest regions should have hundreds of blocks
        max_blocks = max(r[1] for r in regions)
        self.assertGreater(max_blocks, 100)

    def test_print_block_interpretations(self):
        """
        Print interpretation of the first few 2KB blocks.
        Useful for manual verification of block structure.
        """
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        print("\n=== Detailed VIN Block Inspection (First 2 Blocks) ===")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Start at known VIN region
            start_addr = 0x800

            for block_idx in range(2):
                block_addr = start_addr + (block_idx * 2048)
                f.seek(block_addr)
                block = f.read(2048)

                print(f"\n[Block {block_idx}] Offset: 0x{block_addr:06X} - 0x{block_addr+2048:06X}")

                # Scan for records
                rec_size = 38
                record_count = 0
                valid_records = []

                for i in range(53): # Max theoretical records (2048 // 38 = 53)
                    offset = i * rec_size
                    rec_data = block[offset:offset+rec_size]

                    # Check for zero/padding
                    if all(b == 0 for b in rec_data):
                        break

                    # Parse
                    try:
                        p_start = rec_data[0:17].decode('latin-1').strip('\x00')
                        p_end = rec_data[17:34].decode('latin-1').strip('\x00')

                        # Section/Index or Pointer
                        p_sec = int.from_bytes(rec_data[34:36], 'little')
                        p_idx = int.from_bytes(rec_data[36:38], 'little')
                        p_full = int.from_bytes(rec_data[34:38], 'little')

                        if is_valid_subaru_vin(p_start):
                            valid_records.append(
                                f"  Rec {i:02d}: {p_start} -> {p_end} | "
                                f"Ptr: 0x{p_full:08X} (Sec:{p_sec}, Idx:{p_idx})"
                            )
                            record_count += 1
                    except:
                        pass

                # Check padding
                last_byte_idx = 0
                for i in range(2047, -1, -1):
                    if block[i] != 0:
                        last_byte_idx = i
                        break

                padding_size = 2047 - last_byte_idx

                print(f"Status: {record_count} records found")
                print(f"Padding: {padding_size} bytes at end")
                print("Content:")
                for line in valid_records:
                    print(line)


class TestBlockTypeDetection(unittest.TestCase):
    """Tests for block type detection functions"""

    def test_model_code_prefixes_constant(self):
        """Test that MODEL_CODE_PREFIXES includes expected values"""
        self.assertIn('B', MODEL_CODE_PREFIXES)
        self.assertIn('G', MODEL_CODE_PREFIXES)
        self.assertIn('S', MODEL_CODE_PREFIXES)
        self.assertIn('W', MODEL_CODE_PREFIXES)

    def test_is_valid_model_code_valid(self):
        """Test valid model codes"""
        self.assertTrue(is_valid_model_code(b'B11   '))
        self.assertTrue(is_valid_model_code(b'W10   '))
        self.assertTrue(is_valid_model_code(b'G13   '))
        self.assertTrue(is_valid_model_code(b'S12   '))

    def test_is_valid_model_code_invalid(self):
        """Test invalid model codes"""
        self.assertFalse(is_valid_model_code(b'XYZ   '))  # Invalid prefix
        self.assertFalse(is_valid_model_code(b'BAA   '))  # Letters instead of digits
        self.assertFalse(is_valid_model_code(b''))       # Empty
        self.assertFalse(is_valid_model_code(b'B1'))     # Too short

    def test_detect_header_block(self):
        """Header block at offset < 0x800"""
        data = b'\x00' * 2048
        self.assertEqual(detect_block_type(data, offset=0), 'header')
        self.assertEqual(detect_block_type(data, offset=0x400), 'header')

    def test_detect_padding_block(self):
        """All-zero padding block"""
        data = b'\x00' * 2048
        self.assertEqual(detect_block_type(data, offset=0x1000), 'padding')

    def test_detect_vin_range_block(self):
        """VIN range block with 38-byte records (VIN start + VIN end + pointer)"""
        # Create a fake 38-byte VIN range record: VIN1 + VIN2 + 4-byte pointer
        vin1 = b'4S3BD3350T1200011'
        vin2 = b'4S3BD4350V7205795'
        pointer = b'\x00\x04\x29\x00'  # Little-endian pointer
        record = vin1 + vin2 + pointer
        data = record + b'\x00' * (2048 - len(record))
        self.assertEqual(detect_block_type(data, offset=0x800), 'vin_range')

    def test_detect_vin_model_block(self):
        """VIN model block with 69-byte records (single VIN + model spec)"""
        # Create a fake 69-byte VIN-Model record
        vin = b'JF2SHAEC0CH440463'
        null_flag = b'\x00\x01'
        model_code = b'S12   '
        body_model = b'SHMDY6S'
        spec_code = b'G1UH20NT '
        binary = b'\x00\x10'
        date1 = b'20120116'
        date2 = b'20120112'
        date3 = b'20120112'
        suffix = b'U5'
        record = vin + null_flag + model_code + body_model + spec_code + binary + date1 + date2 + date3 + suffix
        self.assertEqual(len(record), 69)
        data = record + b'\x00' * (2048 - len(record))
        self.assertEqual(detect_block_type(data, offset=0x3E5000), 'vin_model')

    def test_detect_vin_record_type(self):
        """Test detect_vin_record_type distinguishes 38 vs 69 byte records"""
        # 38-byte VIN range - needs at least 69 bytes for detection
        vin1 = b'4S3BD3350T1200011'
        vin2 = b'4S3BD4350V7205795'
        pointer = b'\x00\x04\x29\x00'
        range_data = vin1 + vin2 + pointer + b'\x00' * 31  # Pad to 69 bytes
        self.assertEqual(len(range_data), 69)
        self.assertEqual(detect_vin_record_type(range_data), 'vin_range')

        # 69-byte VIN-Model
        vin = b'JF2SHAEC0CH440463'
        null_flag = b'\x00\x01'
        model_code = b'S12   '
        body_model = b'SHMDY6S'
        spec_code = b'G1UH20NT '
        binary = b'\x00\x10'
        dates = b'20120116' * 3
        suffix = b'U5'
        model_data = vin + null_flag + model_code + body_model + spec_code + binary + dates + suffix
        self.assertEqual(len(model_data), 69)
        self.assertEqual(detect_vin_record_type(model_data), 'vin_model')

    def test_detect_text_block(self):
        """Text block with mostly printable ASCII"""
        # Create block with >70% printable text
        text = b'ENGINE ASSEMBLY COMPLETE WITH ALL PARTS AND COMPONENTS ' * 30
        data = text[:2048].ljust(2048, b' ')
        self.assertEqual(detect_block_type(data, offset=0x1000000), 'text')

    def test_detect_binary_block(self):
        """Binary block with low printable ratio"""
        # Create block with mostly non-printable bytes
        data = bytes([0x80 + (i % 128) for i in range(2048)])
        self.assertEqual(detect_block_type(data, offset=0x1000000), 'binary')

    def test_detect_incomplete_block(self):
        """Incomplete block (< 2048 bytes)"""
        data = b'\x00' * 1000
        self.assertEqual(detect_block_type(data, offset=0x1000), 'incomplete')


class TestVINModelRecords(unittest.TestCase):
    """Tests for 69-byte VIN-Model record parsing"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_parse_vin_model_records_us2(self):
        """Parse VIN-Model records from 0x3E5000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parse_vin_model_records(f, start_offset=0x3E5000, max_records=10)

        self.assertEqual(len(records), 10)

        # First record should be JF2 VIN
        self.assertTrue(records[0].vin.startswith('JF2'))
        self.assertEqual(records[0].model_code, 'S12')
        self.assertIsInstance(records[0], VINModelRecord)

        # Check dates are valid format YYYYMMDD
        self.assertEqual(len(records[0].date1), 8)
        self.assertTrue(records[0].date1.isdigit())

    def test_vin_model_record_dataclass(self):
        """Test VINModelRecord dataclass structure"""
        rec = VINModelRecord(
            offset=0x3E5000,
            vin="JF2SHAEC0CH440463",
            flag=1,
            model_code="S12",
            body_model="SHMDY6S",
            spec_code="G1UH20NT",
            binary_flags=b'\x00\x10',
            date1="20120116",
            date2="20120112",
            date3="20120112",
            suffix="U5",
            raw_data=b'\x00' * 69
        )
        self.assertEqual(rec.offset, 0x3E5000)
        self.assertEqual(rec.vin, "JF2SHAEC0CH440463")
        self.assertEqual(rec.model_code, "S12")
        self.assertEqual(len(rec.date1), 8)


class TestMultilingualPartRecords(unittest.TestCase):
    """Tests for 192-byte multilingual part name records"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_multilingual_part_block(self):
        """Test detection of multilingual part block pattern"""
        # Create a fake 192-byte multilingual part record
        model_code = b'B11   '
        part_code = b'0951S '
        figure = b' 421 '
        index = b'11'
        name_en = b'FUEL HOSE' + b' ' * 31
        name_de = b'KRAFTSTOFFSCHLAUCH' + b' ' * 22
        name_fr = b'FLEXIBLE DE CARBURANT' + b' ' * 19
        name_es = b'MANGUERA COMBUSTIBLE' + b' ' * 20
        trailer = b'\x00' * 13

        record = model_code + part_code + figure + index + name_en + name_de + name_fr + name_es + trailer
        self.assertEqual(len(record), 192)

        # Pad to 2KB block
        data = record + b'\x00' * (2048 - 192)
        self.assertTrue(is_multilingual_part_block(data))

    def test_detect_multilingual_part_block(self):
        """Test detect_block_type identifies multilingual_part"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0CD4D000 which contains multilingual parts
            f.seek(0x0CD4D000)
            data = f.read(2048)

        block_type = detect_block_type(data, offset=0x0CD4D000)
        self.assertEqual(block_type, 'multilingual_part')

    def test_parse_multilingual_part_records_us2(self):
        """Parse multilingual part records from 0x0CD4D000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parse_multilingual_part_records(f, start_offset=0x0CD4D000, max_records=10)

        self.assertEqual(len(records), 10)

        # First record should be B11 model
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], MultilingualPartRecord)

        # Check all 4 languages have content
        self.assertTrue(len(records[0].name_en) > 0)
        self.assertTrue(len(records[0].name_de) > 0)
        self.assertTrue(len(records[0].name_fr) > 0)
        self.assertTrue(len(records[0].name_es) > 0)

    def test_multilingual_part_record_dataclass(self):
        """Test MultilingualPartRecord dataclass structure"""
        rec = MultilingualPartRecord(
            offset=0x0CD4D000,
            model_code="B11",
            part_code="0951S",
            figure_code="421",
            index="11",
            name_en="FUEL HOSE",
            name_de="KRAFTSTOFFSCHLAUCH",
            name_fr="FLEXIBLE DE CARBURANT",
            name_es="MANGUERA COMBUSTIBLE",
            trailer=b'\x00' * 13,
            raw_data=b'\x00' * 192
        )
        self.assertEqual(rec.offset, 0x0CD4D000)
        self.assertEqual(rec.model_code, "B11")
        self.assertEqual(rec.name_en, "FUEL HOSE")
        self.assertEqual(rec.name_de, "KRAFTSTOFFSCHLAUCH")


class TestMultilingualPartRecords180(unittest.TestCase):
    """Tests for 180-byte multilingual part name records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_multilingual_part_block_180(self):
        """Test detection of 180-byte multilingual part block pattern"""
        # Create a fake 180-byte multilingual part record
        model_code = b'B11   '
        part_code = b'13028  '  # 7 bytes
        # No figure/index
        name_en = b'BELT-TIMING' + b' ' * 29
        name_de = b'ZAHNRIEMEN' + b' ' * 30
        name_fr = b'COURROIE DE DISTRIBUTION' + b' ' * 16
        name_es = b'CORREA DISTRIBUCION' + b' ' * 21
        trailer = b'\x00' * 7  # 7 bytes

        # model(6) + part(7) + 40*4 + 7 = 180
        record = model_code + part_code + name_en + name_de + name_fr + name_es + trailer
        self.assertEqual(len(record), 180)

        # Pad to 2KB block
        data = record + b'\x00' * (2048 - 180)
        self.assertTrue(is_multilingual_part_block_180(data))

    def test_detect_multilingual_part_block_180(self):
        """Test detect_block_type identifies multilingual_part_180"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0CD45000 which contains 180-byte multilingual parts
            f.seek(0x0CD45000)
            data = f.read(2048)

        block_type = detect_block_type(data, offset=0x0CD45000)
        self.assertEqual(block_type, 'multilingual_part_180')

    def test_parse_multilingual_part_records_180_us2(self):
        """Parse 180-byte records from 0x0CD45000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parse_multilingual_part_records_180(f, start_offset=0x0CD45000, max_records=10)

        self.assertEqual(len(records), 10)

        # First record should be B11 model
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], MultilingualPartRecord180)
        self.assertEqual(records[0].part_code, '13028')

        # Check all 4 languages have content
        # Note: encoding is CP437, parser handles it
        self.assertTrue(len(records[0].name_en) > 0)
        self.assertTrue("BELT-TIMING" in records[0].name_en)
        self.assertTrue(len(records[0].name_de) > 0)
        self.assertTrue(len(records[0].name_fr) > 0)
        self.assertTrue(len(records[0].name_es) > 0)

    def test_multilingual_part_record_180_dataclass(self):
        """Test MultilingualPartRecord180 dataclass structure"""
        rec = MultilingualPartRecord180(
            offset=0x0CD45000,
            model_code="B11",
            part_code="13028",
            name_en="BELT-TIMING",
            name_de="ZAHNRIEMEN",
            name_fr="COURROIE DE DISTRIBUTION",
            name_es="CORREA DISTRIBUCION",
            trailer=b'\x00' * 7,
            raw_data=b'\x00' * 180
        )
        self.assertEqual(rec.offset, 0x0CD45000)
        self.assertEqual(rec.model_code, "B11")
        self.assertEqual(rec.name_en, "BELT-TIMING")


class TestMultilingualPartRecords167(unittest.TestCase):
    """Tests for 167-byte multilingual part name records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_multilingual_part_block_167(self):
        """Test detection of 167-byte multilingual part block pattern"""
        # Create a fake 167-byte record
        model_code = b'B11   '
        spec_code = b'103TW      '  # 11 bytes
        description = b'WAGON(STEP ROOF)' + b' ' * 9 # 25 bytes
        trailer = b'\x00' * 125  # 125 bytes

        # 6 + 11 + 25 + 125 = 167
        record = model_code + spec_code + description + trailer
        self.assertEqual(len(record), 167)

        # Pad to 2KB block
        # 2048 // 167 = 12 records
        data = (record * 12) + b'\x00' * (2048 - (167 * 12))
        self.assertTrue(is_multilingual_part_block_167(data))

    def test_detect_multilingual_part_block_167(self):
        """Test detect_block_type identifies multilingual_part_167"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0CD41000 which contains 167-byte records
            f.seek(0x0CD41000)
            data = f.read(2048)

        block_type = detect_block_type(data, offset=0x0CD41000)
        self.assertEqual(block_type, 'multilingual_part_167')

    def test_parse_multilingual_part_records_167_us2(self):
        """Parse 167-byte records from 0x0CD41000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parse_multilingual_part_records_167(f, start_offset=0x0CD41000, max_records=10)

        self.assertEqual(len(records), 10)

        # First record should be B11 model
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], MultilingualPartRecord167)
        
        # Check spec and description
        self.assertTrue(len(records[0].spec_code) > 0)
        self.assertTrue(len(records[0].description) > 0)


class TestBlockTypeScan(unittest.TestCase):
    """Tests for full file block type scanning"""

    @classmethod
    def setUpClass(cls):
        cls.has_us1 = os.path.exists(SFCDUS1_PATH)
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)
        cls.has_us3 = os.path.exists(SFCDUS3_PATH)

    def test_scan_block_types_us2_first_100(self):
        """Scan first 100 blocks of SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            ranges = scan_block_types(f, max_blocks=100)

        self.assertGreater(len(ranges), 0)

        # First block should be header
        self.assertEqual(ranges[0][3], 'header')
        self.assertEqual(ranges[0][0], 0)

        # Should find VIN blocks starting at 0x800 (either vin_range or vin_model)
        vin_ranges = [r for r in ranges if r[3] in ('vin_range', 'vin_model', 'vin')]
        self.assertGreater(len(vin_ranges), 0)
        # First VIN range should start at 0x800
        self.assertEqual(vin_ranges[0][0], 0x800)

    def test_print_a_couple(self):
        with open('SFCDUS2/sffastus', 'rb') as f:
            records = parse_multilingual_part_records(f, start_offset=0x0CD4D000, max_records=10)

        print('Multilingual Part Records (192 bytes each)')
        print('=' * 80)

        for i, rec in enumerate(records):
            print(f'\nRecord {i} @ 0x{rec.offset:08X}')
            print(f'  Model:  {rec.model_code}')
            print(f'  Part:   {rec.part_code}')
            print(f'  Figure: {rec.figure_code}')
            print(f'  Index:  {rec.index}')
            print(f'  EN:     {rec.name_en}')
            print(f'  DE:     {rec.name_de}')
            print(f'  FR:     {rec.name_fr}')
            print(f'  ES:     {rec.name_es}')
            print(f'  Trailer: {rec.trailer.hex()}')

    def test_scan_block_types_full_file(self):
        print("\n=== Full Block Type Scan of SFCDUS2/sffastus ===")

        with open(SFCDUS2_PATH, 'rb') as f:
            ranges = scan_block_types(f)

        self.assertGreater(len(ranges), 0)

        # Print the block map
        print_block_type_map(ranges)

        # Verify we found expected block types
        types_found = set(r[3] for r in ranges)
        self.assertIn('header', types_found)
        # Should have either vin_range or vin_model (or both)
        self.assertTrue('vin_range' in types_found or 'vin_model' in types_found)

        # Calculate totals - count both VIN types
        total_blocks = sum(r[2] for r in ranges)
        vin_blocks = sum(r[2] for r in ranges if r[3] in ('vin_range', 'vin_model', 'vin'))

        print(f"\nTotal blocks: {total_blocks}")
        print(f"VIN blocks: {vin_blocks} ({100*vin_blocks/total_blocks:.1f}%)")

        # VIN blocks should be a significant portion of the file
        self.assertGreater(vin_blocks, 1000)

    def test_scan_matches_vin_scan(self):
        """Verify VIN block ranges match scan_vin_blocks_2kb()"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Get VIN regions from existing function
            vin_regions = scan_vin_blocks_2kb(f, min_contiguous=10)

            # Get block type map
            ranges = scan_block_types(f)

        # Extract VIN ranges from block type map (both vin_range and vin_model)
        vin_ranges_from_map = [r for r in ranges if r[3] in ('vin_range', 'vin_model', 'vin')]

        # Total VIN blocks should be similar
        total_vin_from_2kb = sum(r[1] for r in vin_regions)
        total_vin_from_map = sum(r[2] for r in vin_ranges_from_map)

        print(f"\nVIN blocks from scan_vin_blocks_2kb: {total_vin_from_2kb}")
        print(f"VIN blocks from scan_block_types: {total_vin_from_map}")

        # Should be within 1% (small differences due to min_contiguous filtering)
        ratio = total_vin_from_map / total_vin_from_2kb if total_vin_from_2kb > 0 else 0
        self.assertGreater(ratio, 0.95)
        self.assertLess(ratio, 1.05)


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
