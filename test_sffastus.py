import unittest

from sffastus_parser import parse_model_table


class MyTestCase(unittest.TestCase):
    def test_model_table(self):
        with open("SFCDUS1/sffastus", "rb") as f:
            parse_model_table(f)


if __name__ == '__main__':
    unittest.main()
