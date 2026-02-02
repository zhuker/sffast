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
    analyze_vin_blocks,
    scan_vin_blocks_2kb,
    analyze_vin_blocks_2kb,
    is_valid_subaru_vin,
    is_valid_subaru_vin_strict,
    SUBARU_VIN_PREFIXES,
    VINRecord,
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


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
