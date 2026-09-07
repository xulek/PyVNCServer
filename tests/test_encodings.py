"""
Unit tests for encoding implementations
Python 3.13 compatible
"""

import unittest
import struct
import zlib
from vnc_lib.encodings import (
    RawEncoder, RREEncoder, HextileEncoder, ZlibEncoder, ZRLEEncoder,
    EncoderManager, EncodingNotSuitable, encoding_name, format_encoding_list
)
from vnc_lib.tight_encoding import TightEncoder
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

    def test_encoding_name_human_readable(self):
        self.assertEqual(encoding_name(7), "Tight")
        self.assertEqual(encoding_name(-24), "JPEGQualityLevel8")
        self.assertEqual(encoding_name(-250), "CompressLevel6")
        self.assertEqual(encoding_name(-223), "DesktopSize")
        self.assertEqual(encoding_name(-224), "LastRect")
        self.assertEqual(encoding_name(-308), "ExtendedDesktopSize")
        self.assertEqual(encoding_name(-312), "Fence")
        self.assertEqual(encoding_name(-313), "ContinuousUpdates")
        self.assertEqual(encoding_name(123456), "Unknown(123456)")

    def test_format_encoding_list_human_readable(self):
        formatted = format_encoding_list([7, 0, -24, 7])
        self.assertEqual(
            formatted,
            "Tight (7), Raw (0), JPEGQualityLevel8 (-24)"
        )
        self.assertEqual(format_encoding_list(set()), "none")

    def test_rre_encoder_solid(self):
        """Test RRE encoding on solid color"""
        encoder = RREEncoder()
        result = encoder.encode(self.solid_pixels, self.width, self.height, self.bpp)

        # RRE should compress solid color well
        # Format: 4 bytes (num_subrects) + 4 bytes (background) + subrects
        # For solid color, should have 0 subrectangles
        self.assertLessEqual(len(result), len(self.solid_pixels))

    def test_rre_encoder_mixed_rejects_expanding_payload(self):
        """RRE must not return Raw bytes while the rectangle is still labelled RRE."""
        encoder = RREEncoder()
        with self.assertRaises(EncodingNotSuitable):
            encoder.encode(self.mixed_pixels, self.width, self.height, self.bpp)

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
        payload_len = struct.unpack(">I", result[:4])[0]
        self.assertEqual(payload_len, len(result) - 4)
        decoded = zlib.decompressobj().decompress(result[4:])
        self.assertEqual(decoded, b"\x01\xff\x00\x00")

    def test_zrle_encoder_16bit_pixels(self):
        """ZRLE should work with 16-bit pixel streams (bpp=2)."""
        encoder = ZRLEEncoder(compression_level=6)
        pixels_16 = bytes([0x12, 0x34] * (self.width * self.height))
        result = encoder.encode(pixels_16, self.width, self.height, 2)

        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 4)
        decoded = zlib.decompressobj().decompress(result[4:])
        self.assertEqual(decoded, b"\x01\x12\x34")

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

    def test_tight_fill_32bpp_uses_rgb_tpixel(self):
        """Tight fill should send RGB TPIXEL for 32bpp BGRX input."""
        encoder = TightEncoder()
        width, height, bpp = 8, 8, 4
        # BGRX for red
        pixels = bytes([0, 0, 255, 0] * (width * height))
        encoded = encoder.encode(pixels, width, height, bpp)

        self.assertEqual(encoded[0], 0x80)  # FILL
        self.assertEqual(encoded[1:4], bytes([255, 0, 0]))  # RGB

    def test_tight_palette_32bpp_uses_3byte_palette_entries(self):
        """Tight palette payload should use 3-byte RGB entries for 32bpp input."""
        encoder = TightEncoder()
        width, height, bpp = 8, 8, 4
        colors_bgrx = (
            [255, 0, 0, 0],   # blue in BGRX
            [0, 255, 0, 0],   # green
            [0, 0, 255, 0],   # red
        )
        pixels = bytearray()
        for i in range(width * height):
            pixels.extend(colors_bgrx[i % len(colors_bgrx)])
        encoded = encoder.encode(bytes(pixels), width, height, bpp)

        self.assertGreaterEqual(len(encoded), 3)
        self.assertTrue((encoded[0] >> 4) & 0x04)  # explicit filter
        self.assertEqual(encoded[1], 0x01)  # palette filter id
        num_colors = encoded[2] + 1
        palette_len = num_colors * 3
        self.assertGreaterEqual(len(encoded), 3 + palette_len)

    def test_tight_palette_three_colors_uses_8bit_indices(self):
        """For 3+ colors, Tight palette indices must be 8 bits per pixel."""
        encoder = TightEncoder()
        width, height, bpp = 3, 1, 4
        # Three distinct BGRX pixels.
        pixels = bytes([
            255, 0, 0, 0,
            0, 255, 0, 0,
            0, 0, 255, 0,
        ])
        encoded = encoder.encode(pixels, width, height, bpp)

        self.assertGreaterEqual(len(encoded), 3)
        self.assertEqual(encoded[1], 0x01)  # palette filter id
        num_colors = encoded[2] + 1
        self.assertEqual(num_colors, 3)
        palette_len = num_colors * 3
        tail = encoded[3 + palette_len:]
        # Small palette payload (<12) must be raw and 1 byte/pixel => 3 bytes.
        self.assertEqual(len(tail), 3)

    def test_tight_two_color_palette_uses_mono_stream_id(self):
        """Two-color Tight palette rectangles should use stream 1 like TightVNC."""
        encoder = TightEncoder()
        width, height, bpp = 8, 2, 4
        pixels = bytes(([0, 0, 0, 0] * 8) + ([255, 255, 255, 0] * 8))
        encoded = encoder.encode(pixels, width, height, bpp)

        self.assertEqual(encoded[1], 0x01)
        self.assertEqual((encoded[0] >> 4) & 0x03, 0x01)

    def test_tight_multi_color_palette_uses_indexed_stream_id(self):
        """3+ color Tight palette rectangles should use stream 2 like TightVNC."""
        encoder = TightEncoder()
        width, height, bpp = 16, 16, 4
        pixels = bytearray()
        for i in range(width * height):
            pixels.extend([i & 0xFF, (i * 3) & 0xFF, (i * 5) & 0xFF, 0])
        encoded = encoder.encode(bytes(pixels), width, height, bpp)

        self.assertEqual(encoded[1], 0x01)
        self.assertEqual((encoded[0] >> 4) & 0x03, 0x02)

    def test_tight_basic_reset_mode_sets_stream_reset_bit(self):
        """Compatibility mode should set stream reset bit for Tight basic rectangles."""
        encoder = TightEncoder()
        encoder.set_stream_reset_mode(True)
        width, height, bpp = 64, 64, 4
        pixels = bytearray()
        for i in range(width * height):
            # Many colors -> bypass fill/palette and use basic path
            pixels.extend([i & 0xFF, (i >> 2) & 0xFF, (i >> 4) & 0xFF, 0])
        encoded = encoder.encode(bytes(pixels), width, height, bpp)
        self.assertGreater(len(encoded), 1)
        self.assertTrue(encoded[0] & 0x01)  # stream 0 is reset
        self.assertEqual(encoded[0] >> 4, 0x00)  # basic compression, stream 0

    def test_tight_basic_small_payload_sent_uncompressed(self):
        """Basic Tight payloads <12 bytes should be sent raw without length field."""
        encoder = TightEncoder()
        payload = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9])  # 9 bytes
        encoded = encoder._encode_basic(payload, width=3, height=1, bpp=3)
        self.assertEqual(encoded[0], 0x00)
        self.assertEqual(encoded[1:], payload)

    def test_tight_basic_small_payload_reset_mode_keeps_reset_bit(self):
        """In reset mode, small raw-basic payload keeps stream reset bit."""
        encoder = TightEncoder()
        encoder.set_stream_reset_mode(True)
        payload = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9])  # 9 bytes
        encoded = encoder._encode_basic(payload, width=3, height=1, bpp=3)
        self.assertTrue(encoded[0] & 0x01)
        self.assertEqual(encoded[1:], payload)


    def test_tight_solid_detection_never_uses_sparse_false_positive(self):
        """A changed pixel between old sampling points must prevent Tight FILL."""
        encoder = TightEncoder()
        width, height, bpp = 64, 64, 4
        pixels = bytearray([0, 0, 0, 0] * (width * height))
        # The old detector sampled every 16th pixel for a 64x64 rectangle and
        # therefore missed this change at pixel index 1.
        pixels[4:8] = bytes([255, 255, 255, 0])

        encoded = encoder.encode(bytes(pixels), width, height, bpp)
        self.assertNotEqual(encoded[0] >> 4, 0x08)

    def test_tight_stream_reset_round_trip_like_ultravnc(self):
        """Per-rectangle reset mode must produce independently decodable Tight zlib data."""
        encoder = TightEncoder(compression_level=3)
        encoder.set_stream_reset_mode(True)
        width, height, bpp = 32, 16, 4

        def make_frame(seed):
            data = bytearray()
            for i in range(width * height):
                data.extend([
                    (i + seed) & 0xFF,
                    ((i >> 8) + seed * 3) & 0xFF,
                    ((i * 47) + seed * 7) & 0xFF,
                    0,
                ])
            return bytes(data)

        def compact_length(buf, offset=1):
            b0 = buf[offset]
            length = b0 & 0x7F
            offset += 1
            if b0 & 0x80:
                b1 = buf[offset]
                length |= (b1 & 0x7F) << 7
                offset += 1
                if b1 & 0x80:
                    b2 = buf[offset]
                    length |= b2 << 14
                    offset += 1
            return length, offset

        for seed in (1, 9, 23):
            frame = make_frame(seed)
            encoded = encoder.encode(frame, width, height, bpp)
            control = encoded[0]
            self.assertTrue(control & 0x01)
            self.assertEqual(control >> 4, 0x00)
            compressed_len, payload_offset = compact_length(encoded)
            compressed = encoded[payload_offset:payload_offset + compressed_len]
            decoded_rgb = zlib.decompressobj().decompress(compressed)

            expected_rgb = bytearray()
            for i in range(0, len(frame), 4):
                b, g, r, _ = frame[i:i + 4]
                expected_rgb.extend((r, g, b))
            self.assertEqual(decoded_rgb, bytes(expected_rgb))

    def test_tight_requested_reset_bits_are_sent_even_on_fill(self):
        """Tight reset bits are legal and must not be lost on a FILL rectangle."""
        encoder = TightEncoder()
        encoder.request_stream_reset()
        pixels = bytes([10, 20, 30, 0] * 16)
        encoded = encoder.encode(pixels, 4, 4, 4)
        self.assertEqual(encoded[0] & 0x0F, 0x0F)
        self.assertEqual(encoded[0] >> 4, 0x08)
        self.assertEqual(encoded[1:4], bytes([30, 20, 10]))

    def test_rre_large_region_requests_outer_fallback(self):
        """Large RRE regions must ask the selection layer to choose another encoding."""
        encoder = RREEncoder(max_pixels=64)
        large_pixels = bytes([1, 2, 3, 4] * 100)  # 100 pixels
        with self.assertRaises(EncodingNotSuitable):
            encoder.encode(large_pixels, width=10, height=10, bytes_per_pixel=4)

    def test_encoder_manager(self):
        """Test encoder manager selection"""
        manager = EncoderManager()

        # Test with different client encodings
        encodings_raw = [0]
        enc_type, encoder = manager.get_best_encoder(encodings_raw)
        self.assertEqual(enc_type, 0)
        self.assertIsInstance(encoder, RawEncoder)

        # Experimental ZRLE is disabled by default; manager should fall back to Raw.
        encodings_zrle = [16, 0]
        enc_type, encoder = manager.get_best_encoder(encodings_zrle)
        self.assertEqual(enc_type, 0)
        self.assertIsInstance(encoder, RawEncoder)

        # Test with ordered encodings - manager should respect first supported value.
        encodings_all = [5, 2, 0, 16]
        enc_type, encoder = manager.get_best_encoder(encodings_all)
        self.assertEqual(enc_type, 5)
        self.assertIsInstance(encoder, HextileEncoder)

    def test_encoder_manager_respects_client_order_across_content_types(self):
        """Client order takes precedence over server-side content heuristics."""
        manager = EncoderManager()
        encodings_lan = [2, 0, 5, 16]
        enc_type, _ = manager.get_best_encoder(encodings_lan, content_type="lan")
        self.assertEqual(enc_type, 2)


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
