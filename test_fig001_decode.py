#!/usr/bin/env python3
"""
test_fig001_decode.py - Unit test for fig001 G4 decode.

Decodes the raw G4 stream from testdata/fig001_g4.bin to PBM via ImageMagick
and verifies the output matches the known good hash.

Inputs:
  testdata/fig001_g4.bin       - raw CCITT G4 data (4520 bytes)

Reference:
  testdata/fig001_expected.pbm - known good PBM decode (1280x640)

Usage: python3 -m pytest test_fig001_decode.py -v
"""

import hashlib
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from wand.image import Image as WandImage

TESTDATA = Path(__file__).parent / "testdata"
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 640

EXPECTED_PBM_SHA256 = "dc94fbf097585a68d773f0cab8cd885c746d80fce27c41a4a9ae5037fecf7bfa"


def make_g4_tiff(raw_data, width, height):
    """Build minimal TIFF container around raw G4 data."""
    ifd_offset = 8 + len(raw_data)
    header = struct.pack('<2sHI', b'II', 42, ifd_offset)
    strip_offset = 8
    strip_size = len(raw_data)
    entries = [
        (256, 3, 1, width),
        (257, 3, 1, height),
        (258, 3, 1, 1),
        (259, 3, 1, 4),
        (262, 3, 1, 0),
        (273, 4, 1, strip_offset),
        (278, 3, 1, height),
        (279, 4, 1, strip_size),
        (292, 4, 1, 0),
    ]
    ifd = struct.pack('<H', len(entries))
    for tag, typ, count, val in entries:
        ifd += struct.pack('<HHII', tag, typ, count, val)
    ifd += struct.pack('<I', 0)
    return header + raw_data + ifd


class TestFig001Decode(unittest.TestCase):

    def setUp(self):
        self.g4_path = TESTDATA / "fig001_g4.bin"
        self.raw_data = self.g4_path.read_bytes()

    def test_raw_data_size(self):
        """Raw G4 data should be exactly 4520 bytes."""
        self.assertEqual(len(self.raw_data), 4520)

    def test_raw_data_starts_with_g4(self):
        """Raw data should start with FF FF FF FE (G4 white line codes)."""
        self.assertEqual(self.raw_data[:4], b'\xff\xff\xff\xfe')

    def test_decode_to_pbm(self):
        """Decode G4 to PBM via ImageMagick and verify hash."""
        tiff_data = make_g4_tiff(self.raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)

        with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as f:
            f.write(tiff_data)
            tiff_path = f.name

        try:
            result = subprocess.run(
                ["magick", tiff_path, "pbm:-"],
                capture_output=True, timeout=30
            )
            self.assertGreater(len(result.stdout), 0, "ImageMagick produced no output")

            pbm_hash = hashlib.sha256(result.stdout).hexdigest()
            self.assertEqual(pbm_hash, EXPECTED_PBM_SHA256,
                             f"PBM hash mismatch: got {pbm_hash}")
        finally:
            Path(tiff_path).unlink()

    def test_pbm_dimensions(self):
        """Decoded PBM should be 1280x640."""
        tiff_data = make_g4_tiff(self.raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)

        with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as f:
            f.write(tiff_data)
            tiff_path = f.name

        try:
            result = subprocess.run(
                ["magick", "identify", "-format", "%wx%h", tiff_path],
                capture_output=True, timeout=10
            )
            dims = result.stdout.decode().strip()
            self.assertEqual(dims, "1280x640")
        finally:
            Path(tiff_path).unlink()


    def test_decode_to_pbm_wand(self):
        """Decode G4 to PBM via Wand (Python ImageMagick binding) and verify hash."""
        tiff_data = make_g4_tiff(self.raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)

        with WandImage(blob=tiff_data, format='tiff') as img:
            self.assertEqual(img.width, IMAGE_WIDTH)
            self.assertEqual(img.height, IMAGE_HEIGHT)
            pbm = img.make_blob('pbm')

        pbm_hash = hashlib.sha256(pbm).hexdigest()
        self.assertEqual(pbm_hash, EXPECTED_PBM_SHA256,
                         f"PBM hash mismatch: got {pbm_hash}")

    def test_wand_image_type(self):
        """Wand should report bilevel image type."""
        tiff_data = make_g4_tiff(self.raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)

        with WandImage(blob=tiff_data, format='tiff') as img:
            self.assertEqual(img.depth, 1)
            self.assertEqual(img.type, 'bilevel')


if __name__ == "__main__":
    unittest.main()
