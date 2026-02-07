"""
Unit tests for encoding implementations
Python 3.13 compatible
"""

import unittest
import struct
import zlib
from vnc_lib.encodings import (
    RawEncoder, RREEncoder, HextileEncoder, ZlibEncoder, ZRLEEncoder, EncoderManager
)
try:
    from vnc_lib.jpeg_encoding import JPEGEncoder
    JPEG_TESTS_AVAILABLE = True
except Exception:
    JPEG_TESTS_AVAILABLE = False


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

    def test_zrle_encoder_16bit_pixels(self):
        """ZRLE should work with 16-bit pixel streams (bpp=2)."""
        encoder = ZRLEEncoder(compression_level=6)
        pixels_16 = bytes([0x12, 0x34] * (self.width * self.height))
        result = encoder.encode(pixels_16, self.width, self.height, 2)

        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 4)

    def test_zrle_encoder_8bit_pixels(self):
        """ZRLE should work with 8-bit pixel streams (bpp=1)."""
        encoder = ZRLEEncoder(compression_level=6)
        pixels_8 = bytes([0x7F] * (self.width * self.height))
        result = encoder.encode(pixels_8, self.width, self.height, 1)

        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 4)

    def test_zlib_encoder_round_trip(self):
        """Zlib encoding should round-trip to original bytes."""
        encoder = ZlibEncoder(compression_level=3)
        result1 = encoder.encode(self.mixed_pixels, self.width, self.height, self.bpp)
        result2 = encoder.encode(self.solid_pixels, self.width, self.height, self.bpp)

        self.assertGreater(len(result1), 4)
        self.assertGreater(len(result2), 4)

        compressed_len1 = struct.unpack(">I", result1[:4])[0]
        compressed_len2 = struct.unpack(">I", result2[:4])[0]
        compressed_data1 = result1[4:]
        compressed_data2 = result2[4:]
        self.assertEqual(compressed_len1, len(compressed_data1))
        self.assertEqual(compressed_len2, len(compressed_data2))

        inflator = zlib.decompressobj()
        out1 = inflator.decompress(compressed_data1, len(self.mixed_pixels))
        out2 = inflator.decompress(compressed_data2, len(self.solid_pixels))
        self.assertEqual(out1, self.mixed_pixels)
        self.assertEqual(out2, self.solid_pixels)

    @unittest.skipUnless(JPEG_TESTS_AVAILABLE, "JPEG encoder unavailable")
    def test_jpeg_encoder_outputs_jpeg_stream(self):
        """JPEG encoding type 21 payload must be a raw JPEG stream."""
        encoder = JPEGEncoder(quality=70)
        # 32x32 in server-native BGRX layout (blue-ish color)
        width, height, bpp = 32, 32, 4
        pixels = bytes([200, 120, 40, 0] * (width * height))
        encoded = encoder.encode(pixels, width, height, bpp)

        self.assertGreater(len(encoded), 4)
        self.assertEqual(encoded[:2], b"\xFF\xD8")
        self.assertEqual(encoded[-2:], b"\xFF\xD9")

    def test_rre_large_region_falls_back_to_raw(self):
        """Large region should avoid expensive RRE path."""
        encoder = RREEncoder(max_pixels=64)
        large_pixels = bytes([1, 2, 3, 4] * 100)  # 100 pixels
        result = encoder.encode(large_pixels, width=10, height=10, bytes_per_pixel=4)
        self.assertEqual(result, large_pixels)

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

    def test_encoder_manager_lan_prefers_raw(self):
        """LAN profile should prioritize low-latency raw encoding."""
        manager = EncoderManager()
        encodings_lan = {0, 2, 5, 16}
        enc_type, _ = manager.get_best_encoder(encodings_lan, content_type="lan")
        self.assertEqual(enc_type, 0)


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
