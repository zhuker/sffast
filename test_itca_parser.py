import unittest
import os
import tempfile
from sffastus_parser import parse_itca_data, ItcaRecord, ItcaPartsCatalog

class TestItcaParser(unittest.TestCase):
    def setUp(self):
        self.sample_data = (
            "000009513       2 000093579       01 Y26916  CLUTCH                                  \r\n"
            "000009843       2 773053000       01 ZZZZZ   DUMMY                                   \r\n"
            "000013025       1 651684180       01 57497   KEY PLATE-BLANK,MASTER                  \r\n"
            "000026037       1 G3012G0600      01 Y26003  COMPRESSOR                              \r\n"
        )
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='latin-1')
        self.temp_file.write(self.sample_data)
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_parse_itca_data(self):
        records = parse_itca_data(self.temp_file.name)
        self.assertEqual(len(records), 4)
        
        # Test first record
        r0 = records[0]
        self.assertEqual(r0.part_number, "000009513")
        self.assertEqual(r0.itca_code, "2")
        self.assertEqual(r0.supersedes_to, "000093579")
        self.assertEqual(int(r0.quantity), 1) # Wait, why 1? Oh, the spec says 2 bytes for Q'ty.
        # Line 1: 000009513       2 000093579       01 Y26916  CLUTCH
        # Index 35-37 is "01" (qty)
        self.assertEqual(int(r0.quantity), 1)
        self.assertEqual(r0.part_code, "Y26916")
        self.assertEqual(r0.description, "CLUTCH")

    def test_lookup(self):
        catalog = ItcaPartsCatalog(parse_itca_data(self.temp_file.name))
        
        # Lookup by current part number
        results = catalog.lookup("000009513")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].part_number, "000009513")
        
        # Lookup by supersedes-to part number
        results = catalog.lookup("000093579")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].part_number, "000009513")
        self.assertEqual(results[0].supersedes_to, "000093579")
        
        # Lookup non-existent
        results = catalog.lookup("NONEXISTENT")
        self.assertEqual(len(results), 0)

if __name__ == '__main__':
    unittest.main()
