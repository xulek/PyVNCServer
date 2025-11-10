"""
Unit tests for encoding implementations
Python 3.13 compatible
"""

import unittest
from vnc_lib.encodings import (
    RawEncoder, RREEncoder, HextileEncoder, ZRLEEncoder, EncoderManager
)


class TestEncoders(unittest.TestCase):
    """Test suite for VNC encoders"""

    def setUp(self):
        """Setup test data"""
        # Create 8x8 test image (32 bytes per pixel = 256 bytes total)
        self.width = 8
        self.height = 8
        self.bpp = 4

        # Create solid color image (easier to compress)
        self.solid_pixels = bytes([255, 0, 0, 255] * (self.width * self.height))

        # Create mixed image
        mixed = bytearray()
        for y in range(self.height):
            for x in range(self.width):
                if (x + y) % 2 == 0:
                    mixed.extend([255, 0, 0, 255])  # Red
                else:
                    mixed.extend([0, 0, 255, 255])  # Blue
        self.mixed_pixels = bytes(mixed)

    def test_raw_encoder(self):
        """Test raw encoding (no compression)"""
        encoder = RawEncoder()
        result = encoder.encode(self.solid_pixels, self.width, self.height, self.bpp)

        # Raw encoding should return data as-is
        self.assertEqual(result, self.solid_pixels)
        self.assertEqual(len(result), self.width * self.height * self.bpp)

    def test_rre_encoder_solid(self):
        """Test RRE encoding on solid color"""
        encoder = RREEncoder()
        result = encoder.encode(self.solid_pixels, self.width, self.height, self.bpp)

        # RRE should compress solid color well
        # Format: 4 bytes (num_subrects) + 4 bytes (background) + subrects
        # For solid color, should have 0 subrectangles
        self.assertLessEqual(len(result), len(self.solid_pixels))

    def test_rre_encoder_mixed(self):
        """Test RRE encoding on mixed colors"""
        encoder = RREEncoder()
        result = encoder.encode(self.mixed_pixels, self.width, self.height, self.bpp)

        # RRE might not compress checkerboard pattern well
        # Just verify it produces valid output
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_hextile_encoder(self):
        """Test Hextile encoding"""
        encoder = HextileEncoder()
        result = encoder.encode(self.solid_pixels, self.width, self.height, self.bpp)

        # Hextile divides into 16x16 tiles
        # For 8x8 image, should have 1 tile
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_zrle_encoder(self):
        """Test ZRLE encoding"""
        encoder = ZRLEEncoder(compression_level=6)
        result = encoder.encode(self.solid_pixels, self.width, self.height, self.bpp)

        # ZRLE should compress well
        # Result format: 4 bytes (length) + compressed data
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 4)  # At least header

    def test_encoder_manager(self):
        """Test encoder manager selection"""
        manager = EncoderManager()

        # Test with different client encodings
        encodings_raw = {0}
        enc_type, encoder = manager.get_best_encoder(encodings_raw)
        self.assertEqual(enc_type, 0)
        self.assertIsInstance(encoder, RawEncoder)

        # Test with ZRLE support
        encodings_zrle = {0, 16}
        enc_type, encoder = manager.get_best_encoder(encodings_zrle)
        self.assertEqual(enc_type, 16)
        self.assertIsInstance(encoder, ZRLEEncoder)

        # Test with all encodings
        encodings_all = {0, 2, 5, 16}
        enc_type, encoder = manager.get_best_encoder(encodings_all)
        self.assertIn(enc_type, encodings_all)


class TestEncoderPerformance(unittest.TestCase):
    """Performance tests for encoders"""

    def setUp(self):
        """Setup larger test data"""
        self.width = 64
        self.height = 64
        self.bpp = 4

        # Create gradient image
        gradient = bytearray()
        for y in range(self.height):
            for x in range(self.width):
                r = int((x / self.width) * 255)
                g = int((y / self.height) * 255)
                b = 128
                gradient.extend([r, g, b, 255])
        self.gradient_pixels = bytes(gradient)

    def test_compression_ratios(self):
        """Compare compression ratios of different encoders"""
        original_size = len(self.gradient_pixels)

        raw_encoder = RawEncoder()
        raw_size = len(raw_encoder.encode(
            self.gradient_pixels, self.width, self.height, self.bpp
        ))

        zrle_encoder = ZRLEEncoder()
        zrle_size = len(zrle_encoder.encode(
            self.gradient_pixels, self.width, self.height, self.bpp
        ))

        # Raw should be same as original
        self.assertEqual(raw_size, original_size)

        # ZRLE should achieve some compression
        compression_ratio = zrle_size / original_size
        print(f"ZRLE compression ratio: {compression_ratio:.2%}")

        # For gradient, might not compress much, but should not expand significantly
        self.assertLess(zrle_size, original_size * 1.5)


if __name__ == '__main__':
    unittest.main()
