"""
Region-based change detection for efficient screen updates
Implements intelligent dirty region tracking
"""

import zlib
import logging
from typing import NamedTuple
from collections.abc import Iterator


class Region(NamedTuple):
    """Represents a rectangular region (Python 3.13 compatible)"""
    x: int
    y: int
    width: int
    height: int

    def intersects(self, other: 'Region') -> bool:
        """Check if this region intersects with another"""
        return not (
            self.x + self.width <= other.x or
            other.x + other.width <= self.x or
            self.y + self.height <= other.y or
            other.y + other.height <= self.y
        )

    def merge(self, other: 'Region') -> 'Region':
        """Merge this region with another, returning bounding box"""
        x1 = min(self.x, other.x)
        y1 = min(self.y, other.y)
        x2 = max(self.x + self.width, other.x + other.width)
        y2 = max(self.y + self.height, other.y + other.height)
        return Region(x1, y1, x2 - x1, y2 - y1)

    def area(self) -> int:
        """Calculate region area"""
        return self.width * self.height


class TileGrid:
    """
    Divides screen into tiles for efficient change detection
    Uses Python 3.13 type parameter syntax
    """

    def __init__(self, width: int, height: int, tile_size: int = 64):
        """
        Initialize tile grid

        Args:
            width: Screen width in pixels
            height: Screen height in pixels
            tile_size: Size of each tile (default 64x64)
        """
        self.width = width
        self.height = height
        self.tile_size = tile_size

        # Calculate grid dimensions
        self.tiles_x = (width + tile_size - 1) // tile_size
        self.tiles_y = (height + tile_size - 1) // tile_size

        # Store checksums for each tile (CRC32 returns int)
        self.tile_checksums: dict[tuple[int, int], int] = {}

        self.logger = logging.getLogger(__name__)

    def update_and_get_changed(self, pixel_data: bytes,
                               bytes_per_pixel: int) -> list[Region]:
        """
        Update tile checksums and return changed regions

        Args:
            pixel_data: Current screen pixel data
            bytes_per_pixel: Bytes per pixel

        Returns:
            List of changed regions
        """
        changed_tiles: list[tuple[int, int]] = []

        # Check each tile
        for ty in range(self.tiles_y):
            for tx in range(self.tiles_x):
                # Extract tile data
                tile_data = self._extract_tile(
                    pixel_data, tx, ty, bytes_per_pixel
                )

                # Calculate checksum (CRC32 is 5-10x faster than MD5 for change detection)
                checksum = zlib.crc32(tile_data)

                # Compare with previous
                key = (tx, ty)
                if key not in self.tile_checksums or self.tile_checksums[key] != checksum:
                    changed_tiles.append((tx, ty))
                    self.tile_checksums[key] = checksum

        # Convert tiles to regions
        regions = self._tiles_to_regions(changed_tiles)

        # Merge nearby regions
        merged_regions = self._merge_regions(regions)

        self.logger.debug(
            f"Changed tiles: {len(changed_tiles)}, "
            f"regions: {len(regions)} -> {len(merged_regions)}"
        )

        return merged_regions

    def _extract_tile(self, pixel_data: bytes, tile_x: int, tile_y: int,
                     bpp: int) -> bytes:
        """
        Extract pixel data for a specific tile
        Optimized with memoryview for faster slicing and reduced allocations
        """
        # Calculate tile boundaries
        start_x = tile_x * self.tile_size
        start_y = tile_y * self.tile_size
        end_x = min(start_x + self.tile_size, self.width)
        end_y = min(start_y + self.tile_size, self.height)

        tile_width = (end_x - start_x) * bpp
        tile_height = end_y - start_y

        # Pre-allocate result buffer (faster than extend in loop)
        result = bytearray(tile_width * tile_height)

        # Use memoryview for zero-copy slicing
        src_view = memoryview(pixel_data)
        dst_offset = 0

        # Extract tile rows with optimized slicing
        for y in range(start_y, end_y):
            row_offset = y * self.width * bpp
            tile_offset = row_offset + start_x * bpp
            tile_end = tile_offset + tile_width

            # Direct memoryview slice copy (faster than extend)
            result[dst_offset:dst_offset + tile_width] = src_view[tile_offset:tile_end]
            dst_offset += tile_width

        return bytes(result)

    def _tiles_to_regions(self, tiles: list[tuple[int, int]]) -> list[Region]:
        """Convert tile coordinates to regions"""
        regions: list[Region] = []

        for tx, ty in tiles:
            x = tx * self.tile_size
            y = ty * self.tile_size
            width = min(self.tile_size, self.width - x)
            height = min(self.tile_size, self.height - y)
            regions.append(Region(x, y, width, height))

        return regions

    def _merge_regions(self, regions: list[Region],
                      max_merge_distance: int = 128) -> list[Region]:
        """
        Merge nearby regions to reduce number of rectangles

        Args:
            regions: List of regions to merge
            max_merge_distance: Maximum distance for merging

        Returns:
            Merged regions
        """
        if not regions:
            return []

        merged: list[Region] = []
        remaining = list(regions)

        while remaining:
            current = remaining.pop(0)
            merged_any = False

            # Try to merge with existing merged regions
            for i, existing in enumerate(merged):
                # Check if regions are close enough
                distance = self._region_distance(current, existing)

                if distance <= max_merge_distance:
                    # Merge regions
                    merged[i] = current.merge(existing)
                    merged_any = True
                    break

            if not merged_any:
                merged.append(current)

        return merged

    def _region_distance(self, r1: Region, r2: Region) -> int:
        """Calculate distance between two regions"""
        if r1.intersects(r2):
            return 0

        # Calculate horizontal distance
        if r1.x + r1.width < r2.x:
            dx = r2.x - (r1.x + r1.width)
        elif r2.x + r2.width < r1.x:
            dx = r1.x - (r2.x + r2.width)
        else:
            dx = 0

        # Calculate vertical distance
        if r1.y + r1.height < r2.y:
            dy = r2.y - (r1.y + r1.height)
        elif r2.y + r2.height < r1.y:
            dy = r1.y - (r2.y + r2.height)
        else:
            dy = 0

        return max(dx, dy)

    def reset(self):
        """Reset all tile checksums"""
        self.tile_checksums.clear()

    def resize(self, width: int, height: int):
        """Update grid size when screen resolution changes"""
        self.width = width
        self.height = height
        self.tiles_x = (width + self.tile_size - 1) // self.tile_size
        self.tiles_y = (height + self.tile_size - 1) // self.tile_size
        self.reset()


class AdaptiveChangeDetector:
    """
    Adaptive change detector that adjusts strategy based on activity
    Python 3.13 compatible with modern type hints
    """

    def __init__(self, width: int, height: int):
        """
        Initialize adaptive change detector

        Args:
            width: Screen width
            height: Screen height
        """
        self.width = width
        self.height = height

        # Tile-based detection for normal activity
        self.tile_grid = TileGrid(width, height, tile_size=64)

        # Full-screen checksum for low activity (CRC32 returns int)
        self.full_checksum: int | None = None

        # Activity tracking
        self.change_history: list[float] = []  # % of screen changed
        self.max_history = 10

        self.logger = logging.getLogger(__name__)

    def detect_changes(self, pixel_data: bytes,
                      bytes_per_pixel: int) -> list[Region] | None:
        """
        Detect changed regions adaptively

        Args:
            pixel_data: Current screen pixel data
            bytes_per_pixel: Bytes per pixel

        Returns:
            List of changed regions, or None if full update needed
        """
        # First, check if anything changed at all (CRC32 is much faster than MD5)
        current_checksum = zlib.crc32(pixel_data)

        if self.full_checksum == current_checksum:
            # No changes at all
            return []

        # Update full checksum
        self.full_checksum = current_checksum

        # Use tile-based detection
        changed_regions = self.tile_grid.update_and_get_changed(
            pixel_data, bytes_per_pixel
        )

        # Calculate change percentage
        changed_area = sum(r.area() for r in changed_regions)
        total_area = self.width * self.height
        change_pct = (changed_area / total_area * 100) if total_area > 0 else 0

        # Update history
        self.change_history.append(change_pct)
        if len(self.change_history) > self.max_history:
            self.change_history.pop(0)

        # If too much changed, send full update
        if change_pct > 50:
            self.logger.debug(f"Large change ({change_pct:.1f}%), sending full update")
            return None

        self.logger.debug(f"Change: {change_pct:.1f}%, regions: {len(changed_regions)}")
        return changed_regions

    def resize(self, width: int, height: int):
        """Handle screen resize"""
        self.width = width
        self.height = height
        self.tile_grid.resize(width, height)
        self.full_checksum = None
        self.change_history.clear()

    def reset(self):
        """Reset change detection state"""
        self.tile_grid.reset()
        self.full_checksum = None
        self.change_history.clear()
