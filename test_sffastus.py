#!/usr/bin/env python3
"""
Unit tests for sffastus_parser.py
Run from project root: python3 -m pytest test_sffastus.py -v
Or directly: python3 test_sffastus.py
"""

import os
import unittest
from io import BufferedReader
from typing import Any

# Import parser functions
from sffastus_parser import (
    parse_model_table,
    parse_figname_txt,
    analyze_vin_blocks,
    scan_vin_blocks_2kb,
    analyze_vin_blocks_2kb,
    is_valid_subaru_vin,
    is_valid_subaru_vin_strict,
    is_valid_model_code,
    print_block_type_map,
    SffastusBlockParser,
    SUBARU_VIN_PREFIXES,
    VALID_MODEL_CODES,
    VINRecord,
    VINModelRecord,
    MultilingualPartRecord192,
    MultilingualPartRecord180,
    MultilingualPartRecord167,
    PartRangeRecord24,
    ModelSpecRecord103,
    ModelIndexRecord288,
    CatalogApplicabilityRecord466,
    ColorRecord91,
    GlossaryRecord28,
    CodeIndexRecord33,
    FIGGroupCategoryRecord184,
    FIGIllustrationRecord183,
    FIGIllustrationPage89,
    EngineSpecRecord230,
    PartGroupRecord185,
    VariantGlossaryRecord81,
    InventoryRecord199,
    MultilingualPartRecord182,
    FigureIndexRecord22,
    SpecMappingRecord22, parse_itca_data, ItcaPartsCatalog, PartRangeIndex34, PartIndex21, ItcaRecord,
    ModelYearRecord44,
    CategoryIndexRecord20,
    VersionIndexRecord20,
    BodyModelRecord17,
)

# Test data paths
SFCDUS1_PATH = "SFCDUS1/sffastus"
SFCDUS2_PATH = "SFCDUS2/sffastus"
SFCDUS3_PATH = "SFCDUS3/sffastus"
FIGNAME_PATH = "SFCDUS2/sffastpg/win/figname.txt"
ITCA_DATA = ["SFCDUS1/ITCA_DATA.TXT", "SFCDUS2/itca_data.txt", "SFCDUS3/itca_data.txt"]
MYSTI_VIN = "JF1GD70655L510047"

def create_parser():
    # Shared parser instance with figure codes for block disambiguation
    _figure_codes = set()
    if os.path.exists(FIGNAME_PATH):
        _figure_codes = {r.figure_code for r in parse_figname_txt(FIGNAME_PATH)}

    itca_records = []
    for itca_data_txt in ITCA_DATA:
        _records = parse_itca_data(itca_data_txt)
        itca_records.extend(_records)
    parts_catalog = ItcaPartsCatalog(itca_records)

    return SffastusBlockParser(figure_codes=_figure_codes, parts_catalog=parts_catalog)


parser = create_parser()


class TestVINValidation(unittest.TestCase):
    """Tests for VIN validation functions"""

    def test_valid_prefixes(self):
        """Test that all documented prefixes are accepted"""
        self.assertTrue(is_valid_subaru_vin("4S3BD3350T1200011"))  # US
        self.assertTrue(is_valid_subaru_vin(MYSTI_VIN))  # Japan JF1
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

class TestMyQueries(unittest.TestCase):
    # my sti offset 128744666
    def test_vin_model(self):
        # 0x003E5000  0x0CD41000    103096  vin_model
        all_records = []
        body_model_index = dict()

        with open(SFCDUS2_PATH, 'rb') as f:
            initial_offset = 0x003E5000
            num_blocks = 103096
            for i in range(num_blocks):
                offset = initial_offset + i * 2048
                if i % 1000 == 0:
                    print(i, offset)

                # print(offset)
                records = parser.parse_vin_model_records(f, start_offset=offset)
                self.assertTrue(len(records) > 0)
                all_records.extend(records)
                for r in records:
                    if r.body_model not in body_model_index:
                        body_model_index[r.body_model] = []
                    body_model_index[r.body_model].append(r)


        print(len(all_records))
        mysti = list(filter(lambda r: r.vin == MYSTI_VIN, all_records))
        print(mysti)

    def test_extended_block_map(self):
        """Print block map with block numbers and one example record per range"""
        with open(SFCDUS2_PATH, 'rb') as f:
            ranges = parser.scan_block_types(f)

            # Dispatch: block_type -> parse function returning list of records
            parse_one = {
                'body_model': lambda off: parser.parse_body_model_records_17(f, start_offset=off, max_records=1),
                'vin_range': lambda off: parser.parse_vin_blocks(f, start_offset=off, max_records=1),
                'vin_model': lambda off: parser.parse_vin_model_records(f, off, max_records=1),
                'model_index_288': lambda off: parser.parse_model_index_records_288(f, off, max_records=2),
                'part_range_24': lambda off: parser.parse_part_range_records_24(f, off, max_records=1),
                'category_index_20': lambda off: parser.parse_category_index_records_20(f, off, max_records=1),
                'version_index_20': lambda off: parser.parse_version_index_records_20(f, off, max_records=1),
                'multilingual_part_192': lambda off: parser.parse_multilingual_part_records_192(f, off, max_records=1),
                'multilingual_part_180': lambda off: parser.parse_multilingual_part_records_180(f, off, max_records=1),
                'multilingual_part_167': lambda off: parser.parse_multilingual_part_records_167(f, off, max_records=1),
                'multilingual_part_182': lambda off: parser.parse_multilingual_part_records_182(f, off, max_records=1),
                'model_spec_103': lambda off: parser.parse_model_spec_records_103(f, off, max_records=1),
                'catalog_applicability_466': lambda off: parser.parse_catalog_applicability_records_466(f, off, max_records=1),
                'color_record_91': lambda off: parser.parse_color_records_91(f, off, max_records=1),
                'glossary_record_28': lambda off: parser.parse_glossary_records_28(f, off, max_records=1),
                'code_index_record_33': lambda off: parser.parse_code_index_records_33(f, off, max_records=1),
                'fig_group_category_184': lambda off: parser.parse_fig_group_category_records_184(f, off, max_records=1),
                'fig_illustration_183': lambda off: parser.parse_fig_illustration_records_183(f, off, max_records=1),
                'fig_illustration_page_89': lambda off: parser.parse_fig_illustration_page_records_89(f, off, max_records=1),
                'engine_spec_230': lambda off: parser.parse_engine_spec_records_230(f, off, max_records=1),
                'part_group_185': lambda off: parser.parse_part_group_records_185(f, off, max_records=1),
                'variant_glossary_81': lambda off: parser.parse_variant_glossary_records_81(f, off, max_records=1),
                'inventory_199': lambda off: parser.parse_inventory_records_199(f, off, max_records=1),
                'figure_index_22': lambda off: parser.parse_figure_index_records_22(f, off, max_records=1),
                'spec_mapping_22': lambda off: parser.parse_spec_mapping_records_22(f, off, max_records=1),
                'part_index_34': lambda off: parser.parse_part_index_records_34(f, off, max_records=1),
                'part_index_21': lambda off: parser.parse_part_index_records_21(f, off, max_records=1),
                'itca_251': lambda off: parser.parse_itca_records_251(f, off, max_records=1),
                'model_year_44': lambda off: parser.parse_model_year_records_44(f, off, max_records=1),
            }

            total_blocks = 0
            print(f"\n{'#':>4} {'Start':>12} {'End':>12} {'Blocks':>8} {'Type'}")
            print("-" * 70)

            for start, end, count, block_type in ranges:
                block_num_in_file = start//2048
                print(f"{block_num_in_file:4d} 0x{start:08X}  0x{end:08X}  {count:8d}  {block_type}")
                total_blocks += count

                if block_type in parse_one:
                    try:
                        records = parse_one[block_type](start)
                        for rec in records:
                            print(f"      -> {rec}")
                    except Exception as e:
                        print(f"      -> ERROR: {e}")

            print("-" * 70)
            print(f"{'Total':>30}  {total_blocks:8d}")


    def test_figures(self):
        with open(SFCDUS2_PATH, 'rb') as f:
            ranges = parser.scan_block_types(f)

            for r in ranges:
                r_start, r_len, num_blocks, block_type = r
                if block_type == FIGIllustrationRecord183.ID:
                    for i in range(num_blocks):
                        offset = r_start + i * 2048
                        records = parser.parse_fig_illustration_records_183(f, offset)
                        for rec in records:
                            if "G11" in rec.model_code and "081" == rec.fig_group_code2:
                                print(rec)
                elif block_type == MultilingualPartRecord182.ID:
                    for i in range(num_blocks):
                        offset = r_start + i * 2048
                        records = parser.parse_multilingual_part_records_182(f, offset)
                        for rec in records:
                            if "G11" in rec.model_code and "081" == rec.figure:
                                print(rec)
                elif block_type == MultilingualPartRecord192.ID:
                    for i in range(num_blocks):
                        offset = r_start + i * 2048
                        records = parser.parse_multilingual_part_records_192(f, offset)
                        for rec in records:
                            if "G11" in rec.model_code and "081" == rec.figure_code:
                                print(rec)




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
            records = parser.parse_vin_blocks(f, start_offset=0x800, max_records=10)

        self.assertEqual(len(records), 10)

        # First record should be a 4S3 (US) VIN
        self.assertTrue(records[0].vin_start.startswith('4S3'))
        self.assertTrue(records[0].vin_end.startswith('4S3'))

        # Records should be at consecutive offsets (38 bytes each)
        for i in range(1, len(records)):
            self.assertEqual(records[i].offset - records[i - 1].offset, 38)

    def test_parse_vin_blocks_us2_section_structure(self):
        """Verify VIN records have section and index fields"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_vin_blocks(f, start_offset=0x800, max_records=100)

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
            records = parser.parse_vin_blocks(f, start_offset=0x800, max_records=10)

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
            records = parser.parse_vin_blocks(f, start_offset=0x800, max_records=10)

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

                print(f"\n[Block {block_idx}] Offset: 0x{block_addr:06X} - 0x{block_addr + 2048:06X}")

                # Scan for records
                rec_size = 38
                record_count = 0
                valid_records = []

                for i in range(53):  # Max theoretical records (2048 // 38 = 53)
                    offset = i * rec_size
                    rec_data = block[offset:offset + rec_size]

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

    def test_valid_model_codes_constant(self):
        """Test that VALID_MODEL_CODES includes expected values"""
        self.assertIn('B11', VALID_MODEL_CODES)
        self.assertIn('G10', VALID_MODEL_CODES)
        self.assertIn('S10', VALID_MODEL_CODES)
        self.assertIn('W10', VALID_MODEL_CODES)

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
        self.assertFalse(is_valid_model_code(b''))  # Empty
        self.assertFalse(is_valid_model_code(b'B1'))  # Too short

    def test_detect_header_block(self):
        """Header block at offset < 0x800"""
        data = b'\x00' * 2048
        self.assertEqual(parser.detect_block_type(data, offset=0), 'header')
        self.assertEqual(parser.detect_block_type(data, offset=0x400), 'header')

    def test_detect_padding_block(self):
        """All-zero padding block"""
        data = b'\x00' * 2048
        self.assertEqual(parser.detect_block_type(data, offset=0x1000), 'padding')

    def test_detect_vin_range_block(self):
        """VIN range block with 38-byte records (VIN start + VIN end + pointer)"""
        # Create a fake 38-byte VIN range record: VIN1 + VIN2 + 4-byte pointer
        vin1 = b'4S3BD3350T1200011'
        vin2 = b'4S3BD4350V7205795'
        pointer = b'\x00\x04\x29\x00'  # Little-endian pointer
        record = vin1 + vin2 + pointer
        data = record + b'\x00' * (2048 - len(record))
        self.assertEqual(parser.detect_block_type(data, offset=0x800), 'vin_range')

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
        self.assertEqual(parser.detect_block_type(data, offset=0x3E5000), 'vin_model')

    def test_detect_vin_record_type(self):
        """Test detect_vin_record_type distinguishes 38 vs 69 byte records"""
        # 38-byte VIN range - needs at least 69 bytes for detection
        vin1 = b'4S3BD3350T1200011'
        vin2 = b'4S3BD4350V7205795'
        pointer = b'\x00\x04\x29\x00'
        range_data = vin1 + vin2 + pointer + b'\x00' * 31  # Pad to 69 bytes
        self.assertEqual(len(range_data), 69)
        self.assertEqual(parser.detect_vin_record_type(range_data), 'vin_range')

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
        self.assertEqual(parser.detect_vin_record_type(model_data), 'vin_model')

    def test_detect_text_block(self):
        """Text block with mostly printable ASCII"""
        # Create block with >70% printable text
        text = b'ENGINE ASSEMBLY COMPLETE WITH ALL PARTS AND COMPONENTS ' * 30
        data = text[:2048].ljust(2048, b' ')
        self.assertEqual(parser.detect_block_type(data, offset=0x1000000), 'text')

    def test_detect_binary_block(self):
        """Binary block with low printable ratio"""
        # Create block with mostly non-printable bytes
        data = bytes([0x80 + (i % 128) for i in range(2048)])
        self.assertEqual(parser.detect_block_type(data, offset=0x1000000), 'binary')

    def test_detect_incomplete_block(self):
        """Incomplete block (< 2048 bytes)"""
        data = b'\x00' * 1000
        self.assertEqual(parser.detect_block_type(data, offset=0x1000), 'incomplete')

    def test_detect_block_types(self):
        # 0x1C686800

        with open(SFCDUS2_PATH, 'rb') as f:
            def assert_block(expected_type, offset):
                f.seek(offset)
                data = f.read(2048)
                self.assertEqual(expected_type, parser.detect_block_type(data, offset))

            def assert_binary(offset):
                assert_block("binary", offset)

            assert_binary(0x1A3C1800)

            assert_block(ModelYearRecord44.ID, 0x1C686800)
            assert_block(ModelYearRecord44.ID, 0x17B7A800)

            assert_binary(0x0E182000)
            assert_binary(0x1E56F800)
            assert_binary(0x1E53E000)
            assert_binary(0x0E6AE800)

            assert_block(BodyModelRecord17.ID, 0x003E1800)

            assert_block(CategoryIndexRecord20.ID, 0x0CD42000)
            assert_block(VersionIndexRecord20.ID, 0x0E6ED000)

            assert_block(ModelSpecRecord103.ID, 0x0E76C800)

            assert_block("empty", 0x0FED7000)

            assert_block(VariantGlossaryRecord81.ID, 0x10819800)

            assert_block(SpecMappingRecord22.ID, 0x10887000)
            assert_block(InventoryRecord199.ID, 0x129B8800)
            assert_block(FIGIllustrationRecord183.ID, 0x1301B000)
            assert_block(MultilingualPartRecord167.ID, 0x13C9C000)
            assert_block(CatalogApplicabilityRecord466.ID, 0x1525B800)
            assert_block(PartGroupRecord185.ID, 0x155B0000)

            assert_block(ColorRecord91.ID, 0x1BF44800)







class TestVINModelRecords(unittest.TestCase):
    """Tests for 69-byte VIN-Model record parsing"""

    def test_parse_vin_model_records_us2(self):
        """Parse VIN-Model records from 0x3E5000 in SFCDUS2"""
        offset = 128744666 // 2048 * 2048
        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_vin_model_records(f, start_offset=offset)

        mysti = list(filter(lambda r: r.vin == MYSTI_VIN, records))
        self.assertEqual(len(mysti), 1)
        rec = mysti[0]
        self.assertEqual(rec.offset, 128744666)
        self.assertEqual(rec.vin, MYSTI_VIN)
        self.assertEqual(rec.model_code, "G11")
        self.assertEqual(rec.color_code, "51E")
        self.assertEqual(rec.trim_code, "B20")
        self.assertEqual(rec.option_code, "TG")
        self.assertEqual(rec.destination_code, "U4")
        self.assertEqual(rec.date1, '20040625')
        self.assertEqual(rec.date2, '20040624')
        self.assertEqual(rec.date1, '20040625')
        self.assertEqual(rec.flag, 1)


    def test_parse_my_sti(self):
        """Parse VIN-Model records from 0x3E5000 in SFCDUS2"""
        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_vin_model_records(f, start_offset=0x3E5000, max_records=10)

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
            color_code="G1U",
            trim_code="H20",
            option_code="NT",
            binary_flags=b'\x00\x10',
            date1="20120116",
            date2="20120112",
            date3="20120112",
            destination_code="U5",
            raw_data=b'\x00' * 69
        )
        self.assertEqual(rec.offset, 0x3E5000)
        self.assertEqual(rec.vin, "JF2SHAEC0CH440463")
        self.assertEqual(rec.model_code, "S12")
        self.assertEqual(rec.color_code, "G1U")
        self.assertEqual(rec.trim_code, "H20")
        self.assertEqual(rec.option_code, "NT")
        self.assertEqual(rec.destination_code, "U5")
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
        self.assertTrue(parser.is_multilingual_part_block_192(data))

    def test_detect_multilingual_part_block(self):
        """Test detect_block_type identifies multilingual_part"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0CD4D000 which contains multilingual parts
            f.seek(0x0CD4D000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0CD4D000)
        self.assertEqual(block_type, 'multilingual_part')

    def test_parse_multilingual_part_records_us2(self):
        """Parse multilingual part records from 0x0CD4D000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_multilingual_part_records_192(f, start_offset=0x0CD4D000, max_records=10)

        self.assertEqual(len(records), 10)

        # First record should be B11 model
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], MultilingualPartRecord192)

        # Check all 4 languages have content
        self.assertTrue(len(records[0].name_en) > 0)
        self.assertTrue(len(records[0].name_de) > 0)
        self.assertTrue(len(records[0].name_fr) > 0)
        self.assertTrue(len(records[0].name_es) > 0)

    def test_multilingual_part_record_dataclass(self):
        """Test MultilingualPartRecord dataclass structure"""
        rec = MultilingualPartRecord192(
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
        self.assertTrue(parser.is_multilingual_part_block_180(data))

    def test_detect_multilingual_part_block_180(self):
        """Test detect_block_type identifies multilingual_part_180"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0CD45000 which contains 180-byte multilingual parts
            f.seek(0x0CD45000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0CD45000)
        self.assertEqual(block_type, 'multilingual_part_180')

    def test_parse_multilingual_part_records_180_us2(self):
        """Parse 180-byte records from 0x0CD45000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_multilingual_part_records_180(f, start_offset=0x0CD45000, max_records=10)

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
        description = b'WAGON(STEP ROOF)' + b' ' * 9  # 25 bytes
        trailer = b'\x00' * 125  # 125 bytes

        # 6 + 11 + 25 + 125 = 167
        record = model_code + spec_code + description + trailer
        self.assertEqual(len(record), 167)

        # Pad to 2KB block
        # 2048 // 167 = 12 records
        data = (record * 12) + b'\x00' * (2048 - (167 * 12))
        self.assertTrue(parser.is_multilingual_part_block_167(data))

    def test_detect_multilingual_part_block_167(self):
        """Test detect_block_type identifies multilingual_part_167"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0CD41000 which contains 167-byte records
            f.seek(0x0CD41000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0CD41000)
        self.assertEqual(block_type, 'multilingual_part_167')

    def test_parse_multilingual_part_records_167_us2(self):
        """Parse 167-byte records from 0x0CD41000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_multilingual_part_records_167(f, start_offset=0x0CD41000, max_records=10)

        self.assertEqual(len(records), 10)

        # First record should be B11 model
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], MultilingualPartRecord167)

        # Check spec and description
        self.assertTrue(len(records[0].spec_code) > 0)
        self.assertTrue(len(records[0].description) > 0)


class TestPartRangeRecords24(unittest.TestCase):
    """Tests for 24-byte part range records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_part_range_block_24(self):
        """Test detection of 24-byte part range block pattern"""
        # Create fake 24-byte records
        # Model(6) PartStart(7) PartEnd(7) Metadata(4)
        record = b'B11   ' + b'11711  ' + b'12024  ' + b'\x17\x19\x2A\x00'
        self.assertEqual(len(record), 24)

        # Block with 2 consistent records
        data = (record * 2) + b'\x00' * (2048 - 48)
        self.assertTrue(parser.is_part_range_block_24(data))

    def test_detect_part_range_block_24(self):
        """Test detect_block_type identifies part_range_24"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0CD42800 which contains 24-byte records
            f.seek(0x0CD42800)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0CD42800)
        self.assertEqual(block_type, 'part_range_24')

    def test_parse_part_range_records_24_us2(self):
        """Parse 24-byte records from 0x0CD42800 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_part_range_records_24(f, start_offset=0x0CD42800, max_records=10)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], PartRangeRecord24)
        self.assertEqual(records[0].part_start, '11711')
        self.assertEqual(records[0].part_end, '12024')


class TestModelSpecRecords103(unittest.TestCase):
    """Tests for 103-byte model specification records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_model_spec_block_103(self):
        """Test detection of 103-byte model spec block pattern"""
        # Create fake 103-byte record
        # Model(6) + Period(15) + BodySpec(15) + ... + Trailer(6) = 103
        record = b'B11   ' + b'011199601199805' + b'BD7-Y3M        ' + b' ' * 26 + b'EJ25D  ' + b'F4WD   ' + b'AT     ' + b'LSI    ' + b'N/S    ' + b' ' * 6
        self.assertEqual(len(record), 103)

        # Block with 2 consistent records
        data = (record * 2) + b'\x00' * (2048 - 206)
        self.assertTrue(parser.is_model_spec_block_103(data))

    def test_detect_model_spec_block_103(self):
        """Test detect_block_type identifies model_spec_103"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0CD4B800 which contains 103-byte records
            f.seek(0x0CD4B800)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0CD4B800)
        self.assertEqual(block_type, 'model_spec_103')

    def test_parse_model_spec_records_103_us2(self):
        """Parse 103-byte records from 0x0CD4B800 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_model_spec_records_103(f, start_offset=0x0CD4B800, max_records=10)

        for i, r in enumerate(records):
            print(i, r)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0].trim_level, 'BASE')
        self.assertEqual(records[3].model_code, 'B11')
        self.assertIsInstance(records[3], ModelSpecRecord103)
        self.assertEqual(records[3].engine, 'EJ25D')
        self.assertEqual(records[3].drivetrain, 'F4WD')


class TestModelIndexRecords288(unittest.TestCase):
    """Tests for 288-byte model index records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_model_index_block_288(self):
        """Test detection of 288-byte model index block pattern"""
        # Create fake 288-byte record with known structure
        model_code = b'B11   '
        block_index_array = b'\x00' * 180  # 180 bytes
        series_code = b'B '
        model_name = b'LEGACY         '  # 15 bytes
        start_date = b'199601'
        end_date = b'199805'
        features = b'12345678901234'  # 14 bytes
        category1 = b'BODY    '  # 8 bytes
        category2 = b'ENGINE  '  # 8 bytes
        category3 = b'TRAIN   '  # 8 bytes
        category4 = b'MISSION '  # 8 bytes
        category5 = b'GRADE   '  # 8 bytes
        category6 = b'SUS     '  # 8 bytes
        trailer = b'\x00' * 11

        record = (model_code + block_index_array + series_code + model_name +
                  start_date + end_date + features +
                  category1 + category2 + category3 + category4 + category5 + category6 +
                  trailer)
        self.assertEqual(len(record), 288)

        # Pad to 2KB block
        data = record + b'\x00' * (2048 - 288)
        self.assertTrue(parser.is_model_index_block_288(data))

    def test_detect_model_index_block_288(self):
        """Test detect_block_type identifies model_index_288"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x13000 which contains model index records
            f.seek(0x13000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x13000)
        self.assertEqual(block_type, 'model_index_288')

    def test_parse_model_index_records_288_us2(self):
        """Parse 288-byte records from 0x13000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_model_index_records_288(f, start_offset=0x13000, max_records=5)

        self.assertGreater(len(records), 0)

        # First record should be B11 model
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], ModelIndexRecord288)

        # Check that model name is populated
        self.assertTrue(len(records[0].model_name) > 0)

        # Print for inspection
        for i, r in enumerate(records):
            print(r)
            print(f"Record {i}: {r.model_code} - {r.model_name} ({r.start_date} to {r.end_date})")
            print(f"  Series: {r.series_code}")
            print(f"  Categories: {r.category1}, {r.category2}, {r.category3}, {r.category4}, {r.category5}, {r.category6}")


class TestPartDetailRecords466(unittest.TestCase):
    """Tests for 466-byte part detail records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_parse_part_detail_records_466_us2(self):
        """Parse 466-byte records from 0x0CE04000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        initial_offset = 0x0CE04000
        records = []
        with open(SFCDUS2_PATH, 'rb') as f:
            for block in range(10):
                offset = initial_offset + (block * 2048)
                f.seek(offset)
                # Read first few records manually
                for i in range(2048 // 466):  # 4 records fit in 2KB (466*4=1864)
                    data = f.read(466)
                    if len(data) < 466:
                        break

                    # Basic validation: starts with model code
                    record = CatalogApplicabilityRecord466.parse_466(data, offset)
                    records.append(record)
                    offset = offset + 466

        # Should have found at least one valid record
        self.assertGreater(len(records), 0)

        # First record should be B11
        self.assertEqual(records[0].model_code, 'B11')

        # Print for manual inspection
        for i, r in enumerate(records):
            print(f"Record {i}: {r}")


class TestColorRecords91(unittest.TestCase):
    """Tests for 91-byte color/paint code records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_color_record_block_91(self):
        """Test detection of 91-byte color record block pattern"""
        # Create fake 91-byte record
        record = b'B11   ' + b'AC 62 ' + b'SILVER M' + b' ' * 12 + b'SILBER M' + b' ' * 12 + b'ARGENT M' + b' ' * 12 + b'PLATA M' + b' ' * 13 + b' ' * 15
        self.assertEqual(len(record), 91)

        # Block with 2 consistent records
        data = (record * 2) + b'\x00' * (2048 - 182)
        self.assertTrue(parser.is_color_record_block_91(data))

    def test_detect_color_record_block_91(self):
        """Test detect_block_type identifies color_record_91"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            f.seek(0x0DE1F800)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0DE1F800)
        self.assertEqual(block_type, 'color_record_91')

    def test_parse_color_records_91_us2(self):
        """Parse 91-byte color records from 0x0DE1F800 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_color_records_91(f, start_offset=0x0DE1F800, max_records=10)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], ColorRecord91)
        # Check that we have color names
        self.assertTrue(len(records[0].color_name_en) > 0)

        # Print for inspection
        for i, r in enumerate(records[:3]):
            print(f"Record {i}: {r.paint_code} - {r.color_name_en}")


class TestGlossaryRecords28(unittest.TestCase):
    """Tests for 28-byte glossary/terminology records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_detect_glossary_record_block_28(self):
        """Test detect_block_type identifies glossary_record_28"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            f.seek(0x0DE23800)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0DE23800)
        self.assertEqual(block_type, 'glossary_record_28')

    def test_parse_glossary_records_28_us2(self):
        """Parse 28-byte glossary records from 0x0DE23800 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_glossary_records_28(f, start_offset=0x0DE23800, max_records=10)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], GlossaryRecord28)
        # Check that we have terms
        self.assertTrue(len(records) > 0)

        # Print for inspection
        for i, r in enumerate(records[:5]):
            print(f"Record {i}: Cat={r.category:02X} Term='{r.term}'")


class TestFIGIllustrationRecords183(unittest.TestCase):
    """Tests for 183-byte FIG illustration records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_detect_fig_illustration_block_183(self):
        """Test detect_block_type identifies fig_illustration_183"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            f.seek(0x0DF9B000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0DF9B000)
        self.assertEqual(block_type, 'fig_illustration_183')

    def test_parse_fig_illustration_records_183_us2(self):
        """Parse 183-byte FIG illustration records from 0x0DF9B000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_fig_illustration_records_183(f, start_offset=0x0DF9B000, max_records=10)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], FIGIllustrationRecord183)
        # Check that we have descriptions
        self.assertTrue(len(records[2].desc_en) > 0)
        self.assertIn('PISTON', records[2].desc_en)

        # Print for inspection
        for i, r in enumerate(records[:5]):
            print(f"Record {i}: Group={r.fig_group_code} EN='{r.desc_en}'")


class TestFIGIllustrationPageRecords89(unittest.TestCase):
    """Tests for 89-byte FIG illustration page records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_detect_fig_illustration_page_block_89(self):
        """Test detect_block_type identifies fig_illustration_page_89"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            f.seek(0x0DFA5000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0DFA5000)
        self.assertEqual(block_type, 'fig_illustration_page_89')

    def test_parse_fig_illustration_page_records_89_us2(self):
        """Parse 89-byte FIG illustration page records from 0x0DFA5000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_fig_illustration_page_records_89(f, start_offset=0x0DFA5000, max_records=10)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], FIGIllustrationPage89)
        # Check numeric fields
        self.assertEqual(records[0].fig_index, '001')
        self.assertEqual(records[0].page_index, '01')

        # Print for inspection
        for i, r in enumerate(records[:5]):
            print(f"Record {i}: Fig={r.fig_index} Page={r.page_index} Label='{r.label}'")


class TestEngineSpecRecords230(unittest.TestCase):
    """Tests for 230-byte Engine Spec records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_detect_engine_spec_block_230(self):
        """Test detect_block_type identifies engine_spec_230"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            f.seek(0x0DFB1000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0DFB1000)
        self.assertEqual(block_type, 'engine_spec_230')

    def test_parse_engine_spec_records_230_us2(self):
        """Parse 230-byte Engine Spec records from 0x0DFB1000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_engine_spec_records_230(f, start_offset=0x0DFB1000, max_records=10)

        self.assertEqual(len(records), 8)  # Block only fits 8 records (230*8=1840)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], EngineSpecRecord230)
        # Check date fields
        self.assertEqual(records[0].start_date, '199310')

        # Print for inspection
        for i, r in enumerate(records[:5]):
            print(
                f"Record {i}: Fig={r.figure} Page={r.figure_page} Model='{r.applicable_model}' Period={r.start_date}-{r.end_date}")


class TestPartGroupRecords185(unittest.TestCase):
    """Tests for 185-byte Part Group records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_detect_part_group_block_185(self):
        """Test detect_block_type identifies part_group_185"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            f.seek(0x0DFD3000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0DFD3000)
        self.assertEqual(block_type, 'part_group_185')

    def test_parse_part_group_records_185_us2(self):
        """Parse 185-byte Part Group records from 0x0DFD3000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_part_group_records_185(f, start_offset=0x0DFD3000, max_records=10)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertEqual(records[0].figure, '001')
        self.assertIsInstance(records[0], PartGroupRecord185)
        self.assertIn('ENGINE ASSEMBLY', records[0].desc_en)

        # Print for inspection
        for i, r in enumerate(records[:5]):
            print(f"Record {i}: Fig={r.figure} Page={r.figure_page} PartCode='{r.part_code}' EN='{r.desc_en}'")


class TestCodeIndexRecords33(unittest.TestCase):
    """Tests for 33-byte code index records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_detect_code_index_record_block_33(self):
        """Test detect_block_type identifies code_index_record_33"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            f.seek(0x0DE42800)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0DE42800)
        self.assertEqual(block_type, 'code_index_record_33')

    def test_parse_code_index_records_33_us2(self):
        """Parse 33-byte code index records from 0x0DE42800 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_code_index_records_33(f, start_offset=0x0DE42800, max_records=10)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], CodeIndexRecord33)
        # Check that we have codes
        self.assertTrue(len(records[0].option_code) > 0)

        # Print for inspection
        for i, r in enumerate(records[:5]):
            cat_char = chr(r.category) if 32 <= r.category <= 126 else f'0x{r.category:02X}'
            print(f"Record {i}: Cat={cat_char} Code='{r.option_code}'")


class TestFIGGroupCategoryRecords184(unittest.TestCase):
    """Tests for 184-byte FIG group category records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_fig_group_category_block_184(self):
        """Test detection of 184-byte FIG group category block pattern"""
        # Create fake 184-byte record
        # Model(6) + FIGCode(2) + EN(40) + DE(40) + FR(40) + ES(40) + Trailer(16)
        model_code = b'B11   '
        fig_code1 = b'0A'
        desc_en1 = b'ENGINE MAIN' + b' ' * 29  # 40 bytes
        desc_de1 = b'MOTOR-HAUPTBAUGRUPPE' + b' ' * 20  # 40 bytes
        desc_fr1 = b'MOTEUR, PRINCIPAL' + b' ' * 23  # 40 bytes
        desc_es1 = b'UNIDAT PRINCIPAL DEL MOTOR' + b' ' * 14  # 40 bytes
        trailer1 = b'\x00' * 16

        record1 = model_code + fig_code1 + desc_en1 + desc_de1 + desc_fr1 + desc_es1 + trailer1
        self.assertEqual(len(record1), 184)

        # Create second record for detection validation
        fig_code2 = b'0B'
        desc_en2 = b'ENGINE AUXILIARIES' + b' ' * 22  # 40 bytes
        desc_de2 = b'MOTOR-ZUSATZTEILE' + b' ' * 23  # 40 bytes
        desc_fr2 = b'MOTEUR, AUXILIAIRES' + b' ' * 21  # 40 bytes
        desc_es2 = b'UNIDADES AUXILIARES DEL MOTOR' + b' ' * 11  # 40 bytes
        trailer2 = b'\x00' * 16

        record2 = model_code + fig_code2 + desc_en2 + desc_de2 + desc_fr2 + desc_es2 + trailer2
        self.assertEqual(len(record2), 184)

        # Combine records and pad to 2KB block
        data = record1 + record2 + b'\x00' * (2048 - 368)
        self.assertTrue(parser.is_fig_group_category_block_184(data))

    def test_detect_fig_group_category_block_184(self):
        """Test detect_block_type identifies fig_group_category_184"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            f.seek(0x0DF9A000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0DF9A000)
        self.assertEqual(block_type, 'fig_group_category_184')

    def test_parse_fig_group_category_records_184_us2(self):
        """Parse 184-byte FIG group category records from 0x0DF9A000 in SFCDUS2"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_fig_group_category_records_184(f, start_offset=0x0DF9A000, max_records=15)

        self.assertEqual(len(records), 15)
        self.assertEqual(records[0].model_code, 'B11')
        self.assertIsInstance(records[0], FIGGroupCategoryRecord184)

        # Check first record is 0A (ENGINE MAIN)
        self.assertEqual(records[0].fig_group_code, '0A')
        self.assertEqual(records[0].desc_en, 'ENGINE MAIN')

        # Check all 4 languages have content
        self.assertTrue(len(records[0].desc_de) > 0)
        self.assertTrue(len(records[0].desc_fr) > 0)
        self.assertTrue(len(records[0].desc_es) > 0)

        # Print for inspection - should show all FIG groups (0A-9B)
        print("\n=== FIG Group Category Records ===")
        for i, r in enumerate(records):
            print(f"  {i:2d}. {r.model_code} | {r.fig_group_code} | {r.desc_en}")

    def test_verify_fig_groups_match_documentation(self):
        """Verify FIG group codes match WINDOWS_APP_GUIDE.md"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        # Expected FIG groups from WINDOWS_APP_GUIDE.md
        expected_groups = {
            '0A': 'ENGINE MAIN',
            '0B': 'ENGINE AUXILIARIES',
            '0C': 'ENGINE ELECTRICAL',
            '1A': 'MANUAL TRANSMISSION',
            '1B': 'AUTOMATIC TRANSMISSION',
            '1C': 'DIFFERENTIAL',
            '2A': 'SUSPENSION',
            '3A': 'STEERING',
            '4A': 'ENGINE MOUNTING',
            '5A': 'BODY',
            '6A': 'DOOR',
            '6B': 'SEAT',
            '7A': 'HEATER',
            '8A': 'ELECTRICAL',
            '8B': 'ELECTRICAL',
            '9A': 'ACCESSORIES',
            '9B': 'ACCESSORIES',
        }

        with open(SFCDUS2_PATH, 'rb') as f:
            records = parser.parse_fig_group_category_records_184(f, start_offset=0x0DF9A000, max_records=20)

        # Check that we found expected groups
        found_groups = {r.fig_group_code: r.desc_en for r in records}

        for group_code, expected_keyword in expected_groups.items():
            if group_code in found_groups:
                # Check that the description contains the expected keyword
                self.assertIn(expected_keyword, found_groups[group_code].upper())


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
            ranges = parser.scan_block_types(f, max_blocks=100)

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
            records = parser.parse_multilingual_part_records_192(f, start_offset=0x0CD4D000, max_records=10)

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
            ranges = parser.scan_block_types(f)

        self.assertGreater(len(ranges), 0)

        # Print the block map
        print_block_type_map(ranges)

        # Verify we found expected block types
        types_found = set(r[3] for r in ranges)
        self.assertIn('header', types_found)
        # Should have variant_glossary_81
        self.assertIn('variant_glossary_81', types_found)
        # Should have either vin_range or vin_model (or both)
        self.assertTrue('vin_range' in types_found or 'vin_model' in types_found)

        # Calculate totals - count both VIN types
        total_blocks = sum(r[2] for r in ranges)
        vin_blocks = sum(r[2] for r in ranges if r[3] in ('vin_range', 'vin_model', 'vin'))

        print(f"\nTotal blocks: {total_blocks}")
        print(f"VIN blocks: {vin_blocks} ({100 * vin_blocks / total_blocks:.1f}%)")

        # VIN blocks should be a significant portion of the file
        self.assertGreater(vin_blocks, 1000)

    def test_parse_all_blocks_full_file(self):
        print("\n=== Parse all Block Types of SFCDUS2/sffastus ===")

        with open(SFCDUS2_PATH, 'rb') as f:
            ranges = parser.scan_block_types(f)
            self.validate_183(f, ranges)
            self.validate_89(f, ranges)
            self.validate_185(f, ranges)
            self.validate_230(f, ranges)
            self.validate_184(f, ranges)
            self.validate_81(f, ranges)
            self.validate_199(f, ranges)
            self.validate_182(f, ranges)
            self.validate_figure_index_22(f, ranges)
            self.validate_spec_map_22(f, ranges)
            self.validate_33(f, ranges)
            self.validate_34(f, ranges)
            self.validate_21(f, ranges)
            self.validate_itca_251(f, ranges)
            self.validate_model_year_44(f, ranges)
            self.validate_category_index_20(f, ranges)
            self.validate_version_index_20(f, ranges)
            self.validate_466(f, ranges)
            self.validate_body_model_17(f, ranges)


    def validate_466(self, f: BufferedReader, ranges: list[Any]):
        cat_ranges = [r for r in ranges if r[3] == CatalogApplicabilityRecord466.ID]
        self.assertGreater(len(cat_ranges), 0, "No CatalogApplicabilityRecord466 blocks found")

        total_blocks = sum(r[2] for r in cat_ranges)
        print(f"Found {len(cat_ranges)} CatalogApplicabilityRecord466 ranges (covering {total_blocks} blocks)")

        total_records = 0
        models_seen = set()
        for r_start, r_end, num_blocks, block_type in cat_ranges:
            for block in range(num_blocks):
                offset = r_start + block * 2048
                records = parser.parse_catalog_applicability_records_466(f, offset)
                self.assertTrue(len(records) > 0, f"No records at 0x{offset:08X}")
                for rec in records:
                    self.assertIsInstance(rec, CatalogApplicabilityRecord466)
                    self.assertIn(rec.model_code, VALID_MODEL_CODES,
                                  f"Bad model code {rec.model_code!r} at 0x{rec.offset:08X}")
                    self.assertTrue(len(rec.group_category) > 0,
                                    f"Empty group_category at 0x{rec.offset:08X}")
                    self.assertTrue(len(rec.part_id) > 0,
                                    f"Empty part_id at 0x{rec.offset:08X}")
                    if rec.date:
                        self.assertTrue(rec.date.isdigit() and len(rec.date) == 16,
                                        f"Bad date {rec.date!r} at 0x{rec.offset:08X}")
                    models_seen.add(rec.model_code)
                total_records += len(records)

        print(f"Validated {total_records} CatalogApplicabilityRecord466 records across {total_blocks} blocks.")
        print(f"  Models: {sorted(models_seen)}")

    def validate_body_model_17(self, f: BufferedReader, ranges: list[Any]):
        bm_ranges = [r for r in ranges if r[3] == BodyModelRecord17.ID]
        self.assertGreater(len(bm_ranges), 0, "No BodyModelRecord17 blocks found")

        total_records = 0
        models_seen = set()
        for r_start, r_end, num_blocks, block_type in bm_ranges:
            for block in range(num_blocks):
                offset = r_start + block * 2048
                records = parser.parse_body_model_records_17(f, offset)
                self.assertTrue(len(records) > 0, f"No records at 0x{offset:08X}")
                for rec in records:
                    self.assertIsInstance(rec, BodyModelRecord17)
                    self.assertEqual(rec.constant, 1, f"Unexpected constant 0x{rec.constant:04X} at 0x{rec.offset:08X}")
                    self.assertTrue(rec.body_model[0].isalpha(), f"Bad body model {rec.body_model!r}")
                    self.assertIn(rec.model_code, VALID_MODEL_CODES, f"Bad model code {rec.model_code!r}")
                    models_seen.add(rec.model_code)
                total_records += len(records)

        print(f"Validated {total_records} BodyModelRecord17 records across {sum(r[2] for r in bm_ranges)} blocks.")
        print(f"  Models: {sorted(models_seen)}")

    def validate_itca_251(self, f: BufferedReader, ranges: list[Any]):
        spec_ranges = [r for r in ranges if r[3] == ItcaRecord.ID]
        self.assertGreater(len(spec_ranges), 0, "No ItcaRecord blocks found")

        print(f"Found {len(spec_ranges)} ItcaRecord blocks (covering {sum(r[2] for r in spec_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in spec_ranges:
            print(r_start, r_len, num_blocks, block_type)
            for block in range(num_blocks):
                offset = r_start + block * 2048
                # print(f"{block} 0x{offset:08X}")
                records = parser.parse_itca_records_251(f, offset)
                self.assertTrue(len(records) > 0)
                # for r in records:
                #     print(r)

        print("Successfully parsed all 251-byte ItcaRecord records.")

    def validate_model_year_44(self, f: BufferedReader, ranges: list[Any]):
        my_ranges = [r for r in ranges if r[3] == ModelYearRecord44.ID]
        self.assertGreater(len(my_ranges), 0, "No ModelYearRecord44 blocks found")

        print(f"Found {len(my_ranges)} ModelYearRecord44 blocks (covering {sum(r[2] for r in my_ranges)} blocks)")

        total_records = 0
        for r_start, r_len, num_blocks, block_type in my_ranges:
            for block in range(num_blocks):
                offset = r_start + block * 2048
                records = parser.parse_model_year_records_44(f, offset)
                self.assertTrue(len(records) > 0, f"No records parsed at 0x{offset:08X}")
                for rec in records:
                    #print(rec)
                    self.assertIsInstance(rec, ModelYearRecord44)
                    # version letter at offset 6 must equal tail at offset 43
                    ver_byte = rec.raw_data[6:7]
                    tail_byte = rec.raw_data[43:44]
                    self.assertEqual(ver_byte, tail_byte,
                                     f"Version/tail mismatch at 0x{rec.offset:08X}: "
                                     f"ver={ver_byte!r} tail={tail_byte!r}")
                    self.assertTrue(rec.date_from.isdigit() and len(rec.date_from) == 8,
                                    f"Bad date_from at 0x{rec.offset:08X}: {rec.date_from}")
                    self.assertTrue(rec.date_to.isdigit() and len(rec.date_to) == 8,
                                    f"Bad date_to at 0x{rec.offset:08X}: {rec.date_to}")
                    self.assertTrue(rec.model_code.strip() in VALID_MODEL_CODES,
                                    f"Bad model at 0x{rec.offset:08X}: {rec.model_code}")
                total_records += len(records)

        print(f"Successfully validated {total_records} ModelYearRecord44 records (version==tail, valid dates, valid models).")

    def validate_category_index_20(self, f: BufferedReader, ranges: list[Any]):
        cr_ranges = [r for r in ranges if r[3] == CategoryIndexRecord20.ID]
        self.assertGreater(len(cr_ranges), 0, "No CategoryIndexRecord20 blocks found")
        print(f"Found {len(cr_ranges)} CategoryIndexRecord20 blocks (covering {sum(r[2] for r in cr_ranges)} blocks)")
        total_records = 0
        for r_start, r_len, num_blocks, block_type in cr_ranges:
            for block in range(num_blocks):
                offset = r_start + block * 2048
                records = parser.parse_category_index_records_20(f, offset)
                self.assertTrue(len(records) > 0, f"No records parsed at 0x{offset:08X}")
                for rec in records:
                    self.assertIsInstance(rec, CategoryIndexRecord20)
                    self.assertTrue(rec.model_code.strip() in VALID_MODEL_CODES,
                                    f"Bad model at 0x{rec.offset:08X}: {rec.model_code}")
                    self.assertTrue(rec.label[1].isalpha(),
                                    f"Bad label at 0x{rec.offset:08X}: {rec.label!r}")
                total_records += len(records)
        print(f"Validated {total_records} CategoryIndexRecord20 records.")

    def validate_version_index_20(self, f: BufferedReader, ranges: list[Any]):
        vr_ranges = [r for r in ranges if r[3] == VersionIndexRecord20.ID]
        self.assertGreater(len(vr_ranges), 0, "No VersionIndexRecord20 blocks found")
        print(f"Found {len(vr_ranges)} VersionIndexRecord20 blocks (covering {sum(r[2] for r in vr_ranges)} blocks)")
        total_records = 0
        for r_start, r_len, num_blocks, block_type in vr_ranges:
            for block in range(num_blocks):
                offset = r_start + block * 2048
                records = parser.parse_version_index_records_20(f, offset)
                self.assertTrue(len(records) > 0, f"No records parsed at 0x{offset:08X}")
                for rec in records:
                    self.assertIsInstance(rec, VersionIndexRecord20)
                    self.assertTrue(rec.model_code.strip() in VALID_MODEL_CODES,
                                    f"Bad model at 0x{rec.offset:08X}: {rec.model_code}")
                    self.assertTrue(rec.label[1].isdigit(),
                                    f"Bad label at 0x{rec.offset:08X}: {rec.label!r}")
                total_records += len(records)
        print(f"Validated {total_records} VersionIndexRecord20 records.")

    def validate_230(self, f: BufferedReader, ranges: list[Any]):
        spec_ranges = [r for r in ranges if r[3] == 'engine_spec_230']
        self.assertGreater(len(spec_ranges), 0, "No Engine Spec blocks found")

        print(f"Found {len(spec_ranges)} Engine Spec blocks (covering {sum(r[2] for r in spec_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in spec_ranges:
            records = parser.parse_engine_spec_records_230(f, r_start)
            self.assertTrue(len(records) > 0)

        print("Successfully parsed all 230-byte Engine Spec records.")

    def validate_185(self, f: BufferedReader, ranges: list[Any]):
        group_ranges = [r for r in ranges if r[3] == 'part_group_185']
        self.assertGreater(len(group_ranges), 0, "No Part Group blocks found")

        print(f"Found {len(group_ranges)} Part Group blocks (covering {sum(r[2] for r in group_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in group_ranges:
            records = parser.parse_part_group_records_185(f, r_start)
            self.assertTrue(len(records) > 0)

        print("Successfully parsed all 185-byte Part Group records.")

    def validate_89(self, f: BufferedReader, ranges: list[Any]):
        fig_ranges = [r for r in ranges if r[3] == 'fig_illustration_page_89']
        self.assertGreater(len(fig_ranges), 0, "No FIG illustration page blocks found")

        print(
            f"Found {len(fig_ranges)} FIG illustration page blocks (covering {sum(r[2] for r in fig_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in fig_ranges:
            records = parser.parse_fig_illustration_page_records_89(f, r_start)
            for rec in records:
                pad1 = rec.raw_data[9:11]
                # Verify that padding is constant/empty (spaces or zeros)
                self.assertTrue(pad1 in (b'  ', b'\x00\x00'),
                                f"Field 1 padding at offset 0x{rec.offset + 9:08X} is not empty: {pad1.hex()}")

        print("Successfully validated all 89-byte FIG Illustration Page padding fields.")

    def validate_183(self, f: BufferedReader, ranges: list[Any]):
        fig_ranges = [r for r in ranges if r[3] == 'fig_illustration_183']
        self.assertGreater(len(fig_ranges), 0, "No FIG group category blocks found")

        print(
            f"Found {len(fig_ranges)} FIG group category blocks (covering {sum(r[2] for r in fig_ranges)} blocks)")

        validated_codes = set()

        for r_start, r_len, num_blocks, block_type in fig_ranges:
            # Parse all records in this range
            records = parser.parse_fig_illustration_records_183(f, r_start)
            self.assertTrue(len(records) > 0)

    def validate_81(self, f: BufferedReader, ranges: list[Any]):
        glossary_ranges = [r for r in ranges if r[3] == 'variant_glossary_81']
        self.assertGreater(len(glossary_ranges), 0, "No Variant Glossary blocks found")

        print(
            f"Found {len(glossary_ranges)} Variant Glossary blocks (covering {sum(r[2] for r in glossary_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in glossary_ranges:
            records = parser.parse_variant_glossary_records_81(f, r_start)
            for rec in records:
                self.assertIsInstance(rec, VariantGlossaryRecord81)
                # Use a smaller count for validation to avoid huge logs if many records
                # but check at least some properties
                self.assertTrue(len(rec.model_code) >= 3)

    def validate_199(self, f: BufferedReader, ranges: list[Any]):
        inv_ranges = [r for r in ranges if r[3] == 'inventory_199']
        self.assertGreater(len(inv_ranges), 0, "No Inventory blocks found")

        print(f"Found {len(inv_ranges)} Inventory blocks (covering {sum(r[2] for r in inv_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in inv_ranges:
            records = parser.parse_inventory_records_199(f, r_start, max_records=10)
            for rec in records:
                # print(rec)
                self.assertIsInstance(rec, InventoryRecord199)
                self.assertTrue(len(rec.model_code) >= 3)
                self.assertTrue(len(rec.part_code) > 0)

    def validate_182(self, f: BufferedReader, ranges: list[Any]):
        rel_ranges = [r for r in ranges if r[3] == 'multilingual_part_182']
        self.assertGreater(len(rel_ranges), 0, "No 182-byte Multilingual blocks found")

        print(f"Found {len(rel_ranges)} blocks (covering {sum(r[2] for r in rel_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in rel_ranges:
            records = parser.parse_multilingual_part_records_182(f, r_start, max_records=10)
            for rec in records:
                # print(f"0x{rec.offset:08X}", rec)
                self.assertIsInstance(rec, MultilingualPartRecord182)
                self.assertTrue(len(rec.model_code) >= 3)
                self.assertTrue(len(rec.part_code) > 0)

    def validate_figure_index_22(self, f: BufferedReader, ranges: list[Any]):
        idx_ranges = [r for r in ranges if r[3] == 'figure_index_22']
        self.assertGreater(len(idx_ranges), 0, "No Figure Index blocks found")

        print(f"Found {len(idx_ranges)} Figure Index blocks (covering {sum(r[2] for r in idx_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in idx_ranges:
            records = parser.parse_figure_index_records_22(f, r_start, max_records=10)
            # print(r_start)
            for rec in records:
                # print(f"0x{rec.offset:08X}", rec)
                self.assertIsInstance(rec, FigureIndexRecord22)
                self.assertTrue(len(rec.model_code) >= 3)
                self.assertTrue(len(rec.figure) > 0)

    def validate_21(self, f: BufferedReader, ranges: list[Any]):
        mapping_ranges = [r for r in ranges if r[3] == PartIndex21.ID]
        self.assertGreater(len(mapping_ranges), 0, "No PartIndex21 blocks found")

        print(
            f"Found {len(mapping_ranges)} PartIndex21 blocks (covering {sum(r[2] for r in mapping_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in mapping_ranges:
            records = parser.parse_part_index_records_21(f, r_start)
            for rec in records:
                self.assertIsInstance(rec, PartIndex21)
                self.assertTrue(len(rec.part_number) >= 3)

    def validate_34(self, f: BufferedReader, ranges: list[Any]):
        mapping_ranges = [r for r in ranges if r[3] == PartRangeIndex34.ID]
        self.assertGreater(len(mapping_ranges), 0, "No PartRangeIndex34 blocks found")

        print(
            f"Found {len(mapping_ranges)} PartRangeIndex34 blocks (covering {sum(r[2] for r in mapping_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in mapping_ranges:
            records = parser.parse_part_index_records_34(f, r_start)
            for rec in records:
                self.assertIsInstance(rec, PartRangeIndex34)
                self.assertTrue(len(rec.part_number_from) >= 3)
                self.assertTrue(len(rec.part_number_to) >= 3)

    def validate_spec_map_22(self, f: BufferedReader, ranges: list[Any]):
        mapping_ranges = [r for r in ranges if r[3] == 'spec_mapping_22']
        self.assertGreater(len(mapping_ranges), 0, "No Spec Mapping blocks found")

        print(
            f"Found {len(mapping_ranges)} Spec Mapping blocks (covering {sum(r[2] for r in mapping_ranges)} blocks)")

        for r_start, r_len, num_blocks, block_type in mapping_ranges:
            records = parser.parse_spec_mapping_records_22(f, r_start, max_records=10)
            for rec in records:
                # print(f"0x{rec.offset:08X}", rec)
                self.assertIsInstance(rec, SpecMappingRecord22)
                self.assertTrue(len(rec.model_code) >= 3)
                self.assertTrue(len(rec.option_code) > 0)

    def validate_33(self, f: BufferedReader, ranges: list[Any]):
        code_index_ranges = [r for r in ranges if r[3] == 'code_index_record_33']

        print(f"Found {len(code_index_ranges)} code_index_record_33 block ranges")
        total_blocks = sum(r[2] for r in code_index_ranges)
        print(f"Total blocks: {total_blocks}")

        self.assertGreater(len(code_index_ranges), 0, "Should find at least one code_index_record_33 range")

        # Step 2: Parse all records from these blocks
        all_records = []
        size_variant_patterns = {}  # Analyze size_variant field content
        code_length_distribution = {}  # Track code lengths

        for start, end, count, block_type in code_index_ranges:
            f.seek(start)
            # Parse all records in this range
            for block_idx in range(count):
                block_offset = start + (block_idx * 2048)
                f.seek(block_offset)
                block_data = f.read(2048)

                # Parse records in this block (2048 // 33 = 62 records max)
                for rec_idx in range(62):
                    rec_offset = rec_idx * 33
                    if rec_offset + 33 > len(block_data):
                        break

                    rec_data = block_data[rec_offset:rec_offset + 33]

                    # Check if valid (starts with model code)
                    if not is_valid_model_code(rec_data[0:6]):
                        break  # End of valid records in this block

                    record = CodeIndexRecord33.parse_33(rec_data, block_offset + rec_offset)
                    all_records.append(record)

                    # Analyze size_variant field
                    size_variant_stripped = record.size_variant.strip()
                    if size_variant_stripped:  # Non-empty after stripping
                        size_variant_patterns[size_variant_stripped] = \
                            size_variant_patterns.get(size_variant_stripped, 0) + 1

                    # Track code length distribution
                    code_len = len(record.code)
                    code_length_distribution[code_len] = code_length_distribution.get(code_len, 0) + 1

        print(f"\nTotal records parsed: {len(all_records)}")

        # Print code length distribution
        print(f"\nPart code length distribution:")
        for length, count in sorted(code_length_distribution.items()):
            pct = (count / len(all_records)) * 100
            print(f"  {length} chars: {count:6d} occurrences ({pct:5.2f}%)")

        # Print size_variant patterns (top 30)
        print(f"\nSize/Variant field patterns (top 30 by frequency):")
        sorted_patterns = sorted(size_variant_patterns.items(), key=lambda x: x[1], reverse=True)
        for pattern, count in sorted_patterns[:30]:
            pct = (count / len(all_records)) * 100
            print(f"  '{pattern}': {count:6d} occurrences ({pct:5.2f}%)")

        # Show sample records with interesting size_variant values
        print(f"\nSample records with non-empty size_variant (first 15):")
        samples_shown = 0
        for rec in all_records:
            if rec.size_variant.strip() and samples_shown < 15:
                cat_char = chr(rec.category) if 32 <= rec.category <= 126 else f'0x{rec.category:02X}'
                print(f"  {samples_shown + 1}. Offset 0x{rec.offset:08X}")
                print(f"     Model: {rec.model_code}, Category: {cat_char}")
                print(f"     Part Code: '{rec.code}' (len={len(rec.code)})")
                print(f"     Size/Variant: '{rec.size_variant.strip()}'")
                samples_shown += 1

        # Assertions
        self.assertGreater(len(all_records), 0, "Should parse at least one record")

        # Validate structure:
        # 1. Part codes should be <= 7 characters
        max_code_len = max(len(r.code) for r in all_records)
        print(f"\nMax part code length: {max_code_len} chars")
        self.assertLessEqual(max_code_len, 7, "Part codes should be <= 7 characters")

        # 2. Size/variant field should have content in most records
        non_empty_size_variant = sum(1 for r in all_records if r.size_variant.strip())
        non_empty_ratio = non_empty_size_variant / len(all_records)
        print(f"Size/variant field has content: {non_empty_ratio * 100:.1f}% of records")
        self.assertGreater(non_empty_ratio, 0.90, "Expected >90% of records to have size/variant data")

        print("\n=== CodeIndexRecord33 structure validated successfully ===")

    def test_scan_matches_vin_scan(self):
        """Verify VIN block ranges match scan_vin_blocks_2kb()"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Get VIN regions from existing function
            vin_regions = scan_vin_blocks_2kb(f, min_contiguous=10)

            # Get block type map
            ranges = parser.scan_block_types(f)

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

    def validate_184(self, f, ranges):
        expected_categories = {
            '0A': ['ENGINE MAIN'],
            '0B': ['ENGINE AUXILIARIES'],
            '0C': ['ENGINE ELECTRICAL PARTS'],
            '1A': ['MANUAL TRANSMISSION'],
            '1B': ['AUTOMATIC TRANSMISSION'],
            '1C': ['DIFFERENTIAL & PROPELLER SHAFT'],
            '2A': ['SUSPENSION, AXLE & BRAKE'],
            '3A': ['STEERING', 'STEERING SYSTEM & CABLE'],
            '4A': ['ENGINE MOUNT & COOLING', 'ENGINE MOUNTING & COOLING'],
            '5A': ['BODY & BUMPER', 'BODY, KEY KIT & BUMPER'],
            '6A': ['DOOR PARTS'],
            '6B': ['SEAT & INSTRUMENT PANEL'],
            '7A': ['HEATER & AIR CONDITIONER'],
            '8A': ['ELECTRICAL PARTS (1)'],
            '8B': ['ELECTRICAL PARTS (2)'],
            '9A': ['ACCESSORIES (EXTERIOR)'],
            '9B': ['ACCESSORIES (INTERIOR)']
        }

        fig_ranges = [r for r in ranges if r[3] == 'fig_group_category_184']
        self.assertGreater(len(fig_ranges), 0, "No FIG group category blocks found")

        print(
            f"Found {len(fig_ranges)} FIG group category blocks (covering {sum(r[2] for r in fig_ranges)} blocks)")

        validated_codes = set()

        for r_start, r_len, num_blocks, block_type in fig_ranges:
            # Parse all records in this range
            records = parser.parse_fig_group_category_records_184(f, r_start)

            for rec in records:
                code = rec.fig_group_code
                desc_en = rec.desc_en

                if code in expected_categories:
                    expected_descs = expected_categories[code]
                    # Check if expected description is contained in the record's description
                    # (allowing for minor padding or case differences if any)
                    self.assertTrue(desc_en in expected_descs,
                                    f"Mismatch for code {code} at 0x{rec.offset:08X}: "
                                    f"Expected '{desc_en}' in '{expected_descs}'")
                    validated_codes.add(code)
                else:
                    # If we find a new code, we should at least note it
                    print(f"Found unknown FIG group code: {code} ('{desc_en}') at 0x{rec.offset:08X}")

        print(f"Validated {len(validated_codes)} unique FIG group codes: {sorted(list(validated_codes))}")

        # Ensure we found most of the core categories
        # Some versions might not have all, but they should have at least the engine ones
        self.assertIn('0A', validated_codes)
        self.assertIn('5A', validated_codes)
        self.assertGreater(len(validated_codes), 10)


class TestVariantGlossaryRecords81(unittest.TestCase):
    """Tests for 81-byte variant glossary records (NEW)"""

    def test_is_variant_glossary_block_81(self):
        """Test detection of 81-byte variant glossary block pattern"""
        # Create a fake 81-byte record
        # model(6) + variant(15) + desc(60) = 81
        model_code = b'B11   '
        variant_code = b'2200CC         '  # 15 bytes
        description = b'ENGINE DISPLACEMENT : 2200CC' + b' ' * 32  # 60 bytes

        record = model_code + variant_code + description
        self.assertEqual(len(record), 81)

        # Pad to 2KB block
        data = (record * 2) + b'\x00' * (2048 - 162)
        self.assertTrue(parser.is_variant_glossary_block_81(data))

        # Test with leading spaces in first record
        data_padded = b'  ' + (record * 2)
        data_padded = data_padded[:2048].ljust(2048, b'\x00')
        self.assertTrue(parser.is_variant_glossary_block_81(data_padded))

    def test_detect_variant_glossary_block_81(self):
        """Test detect_block_type identifies variant_glossary_81"""

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0E6E9000 which contains 81-byte records
            f.seek(0x0E6E9000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0E6E9000)
        self.assertEqual(block_type, 'variant_glossary_81')


class TestItca251(unittest.TestCase):
    def test_detect_itca_251(self):
        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0E6E9000 which contains 81-byte records
            offset = 0x1E7AA800
            f.seek(offset)
            data = f.read(2048)
            block_type = parser.detect_block_type(data, offset=offset)
            self.assertEqual(block_type, ItcaRecord.ID)

    def test_parse_itca_251_2(self):
        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0E6E9000 which contains 81-byte records
            offset = 511701243
            f.seek(offset)
            data = f.read(251)
            r = ItcaRecord.parse_itca_251(data, offset=offset)
            print(r)
            self.assertEqual('01X10 FIG-842(X10)', r.quantity)

class TestInventoryRecord199(unittest.TestCase):
    """Tests for 199-byte inventory records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_inventory_block_199(self):
        """Test detection of 199-byte inventory block pattern"""
        # Create a fake 199-byte record
        # model(6) + part(7) + extra(10) + names(40*4) + trailer(16) = 199
        model_code = b'B11   '
        part_code = b'004  02'
        extra_code = b'037018200 '
        name_en = b'GASKET-ALUMINIUM' + b' ' * 24
        name_de = b'DICHTUNG - ALUMINIUM' + b' ' * 20
        name_fr = b'JOINT - ALUMINIUM' + b' ' * 23
        name_es = b'JUNTA ESTANQUEIDAD ALUMINIO' + b' ' * 13
        trailer = b'\x00' * 16

        record = model_code + part_code + extra_code + name_en + name_de + name_fr + name_es + trailer
        self.assertEqual(len(record), 199)

        # Pad to 2KB block
        data = (record * 2) + b'\x00' * (2048 - 398)
        self.assertTrue(parser.is_inventory_block_199(data))

    def test_detect_inventory_block_199(self):
        """Test detect_block_type identifies inventory_199"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0E147000 which contains 199-byte records
            f.seek(0x0E147000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0E147000)
        self.assertEqual(block_type, 'inventory_199')


class TestMultilingualPartRecords182(unittest.TestCase):
    """Tests for 182-byte multilingual part records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_is_multilingual_part_block_182(self):
        """Test detection of 182-byte multilingual part block pattern"""
        # Create a fake 182-byte record
        # model(6) + part(7) + fig(5) + names(40*4) + trailer(4) = 182
        model_code = b'B11   '
        part_code = b'10101  '
        figure = b'010  '
        name_en = b'CYLINDER BLOCK' + b' ' * 26
        name_de = b'MOTORBLOCK' + b' ' * 30
        name_fr = b'BLOC CYLINDRE' + b' ' * 27
        name_es = b'BLOQUE DE CILINDROS' + b' ' * 21
        trailer = b'\x19\x1e \x00'

        record = model_code + part_code + figure + name_en + name_de + name_fr + name_es + trailer
        self.assertEqual(len(record), 182)

        # Pad to 2KB block
        data = (record * 2) + b'\x00' * (2048 - 364)
        self.assertTrue(parser.is_multilingual_part_block_182(data))

    def test_detect_multilingual_part_block_182(self):
        """Test detect_block_type identifies multilingual_part_182"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0E73B000 which contains 182-byte records
            f.seek(0x0E73B000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0E73B000)
        self.assertEqual(block_type, 'multilingual_part_182')


class TestFigureIndexRecords22(unittest.TestCase):
    """Tests for 22-byte figure index records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_detect_figure_index_block_22(self):
        """Test detect_block_type identifies figure_index_22"""
        if not self.has_us2:
            self.skipTest("SFCDUS2/sffastus not found")

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x0E75D800
            f.seek(0x0E75D800)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x0E75D800)
        self.assertEqual(block_type, 'figure_index_22')


class TestSpecMappingRecords22(unittest.TestCase):
    """Tests for 22-byte spec mapping records (NEW)"""

    @classmethod
    def setUpClass(cls):
        cls.has_us2 = os.path.exists(SFCDUS2_PATH)

    def test_detect_spec_mapping_block_22(self):
        """Test detect_block_type identifies spec_mapping_22"""

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x17BA7000
            f.seek(0x17BA7000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x17BA7000)
        self.assertEqual(block_type, 'spec_mapping_22')

    def test_detect_spec_mapping_block_22_2(self):
        """Test detect_block_type identifies spec_mapping_22"""

        with open(SFCDUS2_PATH, 'rb') as f:
            # Read block at 0x17BA7000
            f.seek(0x15C85000)
            data = f.read(2048)

        block_type = parser.detect_block_type(data, offset=0x15C85000)
        self.assertEqual(block_type, 'spec_mapping_22')


class TestFigurePartsLookup(unittest.TestCase):
    """Test VIN -> figure -> parts resolution pipeline"""

    # G11 block offsets from extended_block_map.txt (SFCDUS2)
    G11_MODEL_SPEC_START = 0x15C90800
    G11_MODEL_SPEC_BLOCKS = 2
    G11_CATALOG_START = 0x15D4E800
    G11_CATALOG_BLOCKS = 9970
    G11_PART_GROUP_START = 0x1729A800
    G11_PART_GROUP_BLOCKS = 877

    BLOCK = 2048

    # MYSTI vehicle specs (from VINModelRecord + ModelSpec)
    MY_DATE = '20040625'
    MY_DEST = 'U4'

    @staticmethod
    def _parse_blocks(f, start, num_blocks, record_size, parse_fn):
        """Parse fixed-size records block-by-block, skipping inter-block padding."""
        records = []
        recs_per_block = TestFigurePartsLookup.BLOCK // record_size
        for blk_idx in range(num_blocks):
            block_offset = start + blk_idx * TestFigurePartsLookup.BLOCK
            f.seek(block_offset)
            block_data = f.read(TestFigurePartsLookup.BLOCK)
            for rec_idx in range(recs_per_block):
                off = rec_idx * record_size
                data = block_data[off:off + record_size]
                if len(data) < record_size or not is_valid_model_code(data[0:6]):
                    continue
                records.append(parse_fn(data, block_offset + off))
        return records

    @staticmethod
    def _extract_figure_ref(unknown: bytes):
        """Extract figure group+number and page from catalog_applicability tail.

        Returns (fig_ref, page) e.g. ('B081', '04') or ('B081', '').
        """
        if len(unknown) < 62:
            return ('', '')
        fig_group = chr(unknown[54]) if 0x41 <= unknown[54] <= 0x5A else ''
        fig_num = unknown[55:58].decode('cp437', errors='replace').strip()
        page = unknown[60:62].decode('cp437', errors='replace').strip()
        return (fig_group + fig_num, page)

    @staticmethod
    def _strip_variant_prefix(spec_logic):
        """Strip variant letter prefix (A-H) from spec_logic if present.

        Variant prefixes appear before the actual spec expression when a callout
        has multiple variants (e.g. '98281  A' / '98281  B'). The spec_logic
        then looks like 'AS.(WRX+STI)' where 'A' is the variant selector.

        Returns (variant_letter, actual_spec_logic) or ('', spec_logic).
        """
        if not spec_logic or len(spec_logic) < 2:
            return ('', spec_logic)
        first = spec_logic[0]
        if first in 'ABCDEFGH' and (spec_logic[1] in '*(' or spec_logic[1].isdigit()
                                      or spec_logic[1:3] in ('S.', 'S ', 'W.', 'W ', 'S+', 'W+')):
            return (first, spec_logic[1:])
        return ('', spec_logic)

    @staticmethod
    def _parse_callout(part_code):
        """Parse part_code into (callout_code, variant_letter).

        Space-separated trailing letter = variant (matches spec_logic prefix):
            '98281  A' -> ('98281', 'A')
        Everything else = callout code directly (matches group_category 7-byte field):
            '98201A'  -> ('98201A', '')
            'N450024' -> ('N450024', '')
            '98271'   -> ('98271', '')
        """
        if '  ' in part_code or (len(part_code) > 5 and part_code[5] == ' '):
            parts = part_code.split()
            if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
                return (parts[0], parts[1])
        return (part_code.strip(), '')

    def _build_spec_matcher(self):
        """Build spec_logic matching functions for MYSTI VIN."""
        import fnmatch

        with open(SFCDUS2_PATH, 'rb') as f:
            specs = []
            for blk in range(self.G11_MODEL_SPEC_BLOCKS):
                off = self.G11_MODEL_SPEC_START + blk * self.BLOCK
                specs.extend(parser.parse_model_spec_records_103(f, start_offset=off))

        my_spec = [s for s in specs if s.trim_level == 'STI'
                   and s.engine == '257' and s.transmission == '6MT']
        self.assertTrue(len(my_spec) >= 1)
        spec = my_spec[0]
        self.assertEqual(spec.body_config, 'S')
        self.assertEqual(spec.drivetrain, '4W')

        props = {spec.engine, spec.transmission, spec.body_config,
                 spec.trim_level, spec.drivetrain,
                 'EJ257', 'EJ25', 'MT', '4WD', 'U4', 'TG', '51E',
                 '205', '251', 'G11', 'SEDAN', 'Sedan'}

        def matches_atom(atom):
            atom = atom.strip()
            if not atom:
                return True
            if '#' in atom:
                return any(fnmatch.fnmatch(p, atom.replace('#', '?')) for p in props)
            return atom in props

        def matches_term(term):
            term = term.strip()
            if not term:
                return True
            negate = term.startswith('*')
            if negate:
                term = term[1:]
            parts, depth, cur = [], 0, ''
            for ch in term:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif ch == '.' and depth == 0:
                    parts.append(cur)
                    cur = ''
                    continue
                cur += ch
            if cur:
                parts.append(cur)
            result = True
            for p in parts:
                p = p.strip()
                if p.startswith('(') and p.endswith(')'):
                    result = result and any(matches_atom(o.strip()) for o in p[1:-1].split('+'))
                else:
                    result = result and matches_atom(p)
            return (not result) if negate else result

        def matches_spec_logic(sl):
            if not sl:
                return True
            terms, depth, cur = [], 0, ''
            for ch in sl:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                elif ch == '+' and depth == 0:
                    terms.append(cur)
                    cur = ''
                    continue
                cur += ch
            if cur:
                terms.append(cur)
            return any(matches_term(t) for t in terms)

        return matches_spec_logic

    def _date_ok(self, rec):
        d = rec.date.strip()
        if not d or len(d) < 16:
            return True
        s, e = d[:8], d[8:16]
        return (not s.isdigit() or not e.isdigit()) or (s <= self.MY_DATE <= e)

    def _dest_ok(self, rec):
        dc = rec.destination_codes.strip()
        if not dc:
            return True
        codes = [dc[i:i+2] for i in range(0, len(dc), 2) if dc[i:i+2].strip()]
        return not codes or self.MY_DEST in codes

    def _resolve_figure_parts(self, figure, figure_page, fig_ref):
        """Resolve all parts for a given figure+page.

        Args:
            figure: Figure number (e.g. '081', '343')
            figure_page: Page number (e.g. '04', '02')
            fig_ref: Figure reference key in catalog tail (e.g. 'B081', 'A343')

        Returns:
            list of (callout_code, part_id) tuples
        """
        matches_spec_logic = self._build_spec_matcher()

        # Get callouts from part_group_185
        with open(SFCDUS2_PATH, 'rb') as f:
            pg_records = self._parse_blocks(
                f, self.G11_PART_GROUP_START, self.G11_PART_GROUP_BLOCKS,
                185, PartGroupRecord185.parse_185)

        page_callouts = [r for r in pg_records
                         if r.model_code == 'G11' and r.figure == figure
                         and r.figure_page == figure_page]

        # Parse catalog records for this figure
        fig_catalog = []
        with open(SFCDUS2_PATH, 'rb') as f:
            all_cat = self._parse_blocks(
                f, self.G11_CATALOG_START, self.G11_CATALOG_BLOCKS,
                466, CatalogApplicabilityRecord466.parse_466)

        for rec in all_cat:
            fr, pg = self._extract_figure_ref(rec.unknown)
            if fr == fig_ref:
                fig_catalog.append((rec, pg))

        resolved = []
        for pgr in page_callouts:
            callout_code, variant = self._parse_callout(pgr.part_code)

            candidates = []
            for rec, pg in fig_catalog:
                if rec.group_category != callout_code:
                    continue
                if pg and pg != figure_page:
                    continue

                v_prefix, actual_spec = self._strip_variant_prefix(rec.spec_logic)
                if variant:
                    if v_prefix != variant:
                        continue
                else:
                    if v_prefix:
                        continue

                if not matches_spec_logic(actual_spec):
                    continue
                if not self._date_ok(rec):
                    continue
                if not self._dest_ok(rec):
                    continue
                candidates.append(rec)

            # Deduplicate
            seen = set()
            for r in candidates:
                if r.part_id not in seen:
                    seen.add(r.part_id)
                    resolved.append((pgr.part_code.strip(), r.part_id))

            if not candidates:
                resolved.append((pgr.part_code.strip(), '???'))

        return resolved, len(page_callouts), len(fig_catalog)

    def test_figure_081_04_parts(self):
        """Resolve all parts for figure 081-04 for MYSTI VIN (G11 STI)."""
        resolved, num_callouts, num_catalog = self._resolve_figure_parts('081', '04', 'B081')

        part_ids = [pid for _, pid in resolved]

        self.assertEqual(num_callouts, 20)
        self.assertEqual(num_catalog, 117)
        self.assertEqual(len(resolved), 20)

        # Generic parts: user confirmed exact part numbers
        self.assertIn('047406200', part_ids)   # 0474S -> 047406200
        self.assertIn('023806000', part_ids)   # 0238S -> 023806000
        self.assertIn('09535A270', part_ids)   # 0953S -> 09535A270

        # Named parts
        self.assertIn('14878AA010', part_ids)  # 14878
        self.assertIn('14879AA010', part_ids)  # 14879
        self.assertIn('16102AA360', part_ids)  # 16102
        self.assertIn('14874AA361', part_ids)  # 14874
        self.assertIn('803605010', part_ids)   # D60501
        self.assertIn('807505301', part_ids)   # H505301
        self.assertIn('807505311', part_ids)   # H505311
        self.assertIn('807503820', part_ids)   # H50382
        self.assertIn('16385AA030', part_ids)  # 16385
        self.assertIn('99071AB481', part_ids)  # 1AB481
        self.assertIn('22328KA040', part_ids)  # 22328B

        # All app callout codes present
        app_callouts = {'D60501', '14879', '14878', '0474S', '14874',
                        '16102', '0238S', 'H505311', 'H505301', '16385',
                        'H50382', '0953S', '1AB481', '22328B'}
        our_callouts = {code for code, _ in resolved}
        self.assertTrue(app_callouts.issubset(our_callouts))

    def test_figure_343_02_parts(self):
        """Resolve all parts for figure 343-02 (AIR BAG) for MYSTI VIN (G11 STI)."""
        resolved, num_callouts, num_catalog = self._resolve_figure_parts('343', '02', 'A343')

        part_ids = [pid for _, pid in resolved]

        self.assertEqual(num_callouts, 11)
        self.assertEqual(num_catalog, 135)
        self.assertEqual(len(resolved), 11)

        # Verified against the app
        self.assertIn('98271FE090OE', part_ids)   # 98271 - passenger airbag
        self.assertIn('98281AE060', part_ids)      # 98281 A - label variant A
        self.assertIn('98281FC010', part_ids)      # 98281 B - label variant B
        self.assertIn('904586015', part_ids)       # Q586015 - tapping screw
        self.assertIn('98211FE180', part_ids)      # 98211 - driver airbag
        self.assertIn('98201FE120', part_ids)      # 98201 - side airbag right
        self.assertIn('98201FE130', part_ids)      # 98201A - side airbag left
        self.assertIn('902450024', part_ids)       # N450024 - cap-nut


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
