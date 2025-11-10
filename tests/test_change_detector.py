"""
Unit tests for change detection
Python 3.13 compatible
"""

import unittest
from vnc_lib.change_detector import Region, TileGrid, AdaptiveChangeDetector


class TestRegion(unittest.TestCase):
    """Test Region class"""

    def test_region_creation(self):
        """Test region creation"""
        region = Region(10, 20, 100, 50)
        self.assertEqual(region.x, 10)
        self.assertEqual(region.y, 20)
        self.assertEqual(region.width, 100)
        self.assertEqual(region.height, 50)

    def test_region_area(self):
        """Test region area calculation"""
        region = Region(0, 0, 100, 50)
        self.assertEqual(region.area(), 5000)

    def test_region_intersects(self):
        """Test region intersection detection"""
        r1 = Region(0, 0, 100, 100)
        r2 = Region(50, 50, 100, 100)
        r3 = Region(200, 200, 100, 100)

        self.assertTrue(r1.intersects(r2))
        self.assertFalse(r1.intersects(r3))

    def test_region_merge(self):
        """Test region merging"""
        r1 = Region(0, 0, 50, 50)
        r2 = Region(25, 25, 50, 50)

        merged = r1.merge(r2)
        self.assertEqual(merged.x, 0)
        self.assertEqual(merged.y, 0)
        self.assertEqual(merged.width, 75)
        self.assertEqual(merged.height, 75)


class TestTileGrid(unittest.TestCase):
    """Test TileGrid class"""

    def setUp(self):
        """Setup test data"""
        self.width = 640
        self.height = 480
        self.tile_size = 64

    def test_tile_grid_creation(self):
        """Test tile grid initialization"""
        grid = TileGrid(self.width, self.height, self.tile_size)

        expected_tiles_x = (self.width + self.tile_size - 1) // self.tile_size
        expected_tiles_y = (self.height + self.tile_size - 1) // self.tile_size

        self.assertEqual(grid.tiles_x, expected_tiles_x)
        self.assertEqual(grid.tiles_y, expected_tiles_y)

    def test_tile_grid_no_changes(self):
        """Test detection with no changes"""
        grid = TileGrid(self.width, self.height, self.tile_size)

        # Create dummy pixel data
        bpp = 4
        pixel_data = bytes([128, 128, 128, 255] * self.width * self.height)

        # First update - all tiles are new
        changed1 = grid.update_and_get_changed(pixel_data, bpp)
        self.assertGreater(len(changed1), 0)

        # Second update - no changes
        changed2 = grid.update_and_get_changed(pixel_data, bpp)
        self.assertEqual(len(changed2), 0)

    def test_tile_grid_partial_change(self):
        """Test detection with partial changes"""
        grid = TileGrid(self.width, self.height, self.tile_size)
        bpp = 4

        # Create initial pixel data
        pixel_data1 = bytearray([128, 128, 128, 255] * self.width * self.height)

        # First update
        grid.update_and_get_changed(bytes(pixel_data1), bpp)

        # Modify small region
        for i in range(0, 64 * 64 * bpp, bpp):
            pixel_data1[i:i+3] = [255, 0, 0]  # Change to red

        # Second update - should detect change
        changed = grid.update_and_get_changed(bytes(pixel_data1), bpp)
        self.assertGreater(len(changed), 0)

    def test_tile_grid_resize(self):
        """Test grid resizing"""
        grid = TileGrid(self.width, self.height, self.tile_size)

        # Add some checksums
        bpp = 4
        pixel_data = bytes([128, 128, 128, 255] * self.width * self.height)
        grid.update_and_get_changed(pixel_data, bpp)

        # Resize
        new_width, new_height = 800, 600
        grid.resize(new_width, new_height)

        self.assertEqual(grid.width, new_width)
        self.assertEqual(grid.height, new_height)
        self.assertEqual(len(grid.tile_checksums), 0)  # Should be reset


class TestAdaptiveChangeDetector(unittest.TestCase):
    """Test AdaptiveChangeDetector class"""

    def setUp(self):
        """Setup test data"""
        self.width = 640
        self.height = 480
        self.bpp = 4

    def test_detector_creation(self):
        """Test detector initialization"""
        detector = AdaptiveChangeDetector(self.width, self.height)
        self.assertEqual(detector.width, self.width)
        self.assertEqual(detector.height, self.height)

    def test_detector_no_changes(self):
        """Test detection with no changes"""
        detector = AdaptiveChangeDetector(self.width, self.height)

        pixel_data = bytes([128, 128, 128, 255] * self.width * self.height)

        # First call - everything is new
        changes1 = detector.detect_changes(pixel_data, self.bpp)
        self.assertIsNotNone(changes1)

        # Second call - no changes
        changes2 = detector.detect_changes(pixel_data, self.bpp)
        self.assertEqual(len(changes2), 0)

    def test_detector_full_change(self):
        """Test detection with full screen change"""
        detector = AdaptiveChangeDetector(self.width, self.height)

        pixel_data1 = bytes([128, 128, 128, 255] * self.width * self.height)
        pixel_data2 = bytes([255, 0, 0, 255] * self.width * self.height)

        detector.detect_changes(pixel_data1, self.bpp)
        changes = detector.detect_changes(pixel_data2, self.bpp)

        # Large change should return None (full update)
        self.assertIsNone(changes)

    def test_detector_resize(self):
        """Test detector resizing"""
        detector = AdaptiveChangeDetector(self.width, self.height)

        new_width, new_height = 800, 600
        detector.resize(new_width, new_height)

        self.assertEqual(detector.width, new_width)
        self.assertEqual(detector.height, new_height)


if __name__ == '__main__':
    unittest.main()
