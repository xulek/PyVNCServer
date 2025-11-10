"""
Desktop Resize Support - ExtendedDesktopSize Pseudo-encoding
RFC 6143 Extension for dynamic screen size changes
Python 3.13 compatible
"""

import struct
import logging
from dataclasses import dataclass
from typing import Protocol


# Type aliases (Python 3.13)
type ScreenID = int
type ResizeReason = int


@dataclass
class Screen:
    """
    Represents a single screen in multi-monitor setup
    Python 3.13 dataclass
    """
    id: ScreenID
    x: int
    y: int
    width: int
    height: int
    flags: int = 0

    def to_bytes(self) -> bytes:
        """Encode screen data for transmission"""
        return struct.pack(">IIHHHI",
                          self.id,
                          self.x,
                          self.y,
                          self.width,
                          self.height,
                          self.flags)

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Screen':
        """Decode screen data from bytes"""
        if len(data) < 16:
            raise ValueError(f"Invalid screen data length: {len(data)}")

        screen_id, x, y, width, height, flags = struct.unpack(">IIHHHI", data[:16])
        return cls(
            id=screen_id,
            x=x,
            y=y,
            width=width,
            height=height,
            flags=flags
        )


class DesktopSizeHandler:
    """
    Handles desktop size changes and ExtendedDesktopSize encoding
    Python 3.13 compatible with pattern matching
    """

    # Pseudo-encoding types
    ENCODING_DESKTOP_SIZE = -223  # Legacy
    ENCODING_EXTENDED_DESKTOP_SIZE = -308  # Extended (preferred)

    # Resize status codes
    STATUS_NO_ERROR = 0
    STATUS_OUT_OF_RESOURCES = 1
    STATUS_INVALID_SCREEN_LAYOUT = 2

    # Resize reasons
    REASON_SERVER = 0  # Server-initiated resize
    REASON_CLIENT = 1  # Client-requested resize
    REASON_OTHER = 2   # Other reason

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.current_width: int = 0
        self.current_height: int = 0
        self.screens: list[Screen] = []
        self.supports_extended: bool = False

    def initialize(self, width: int, height: int):
        """Initialize with screen dimensions"""
        self.current_width = width
        self.current_height = height
        self.screens = [Screen(id=0, x=0, y=0, width=width, height=height)]
        self.logger.info(f"Desktop size initialized: {width}x{height}")

    def resize(self, new_width: int, new_height: int,
               reason: ResizeReason = REASON_SERVER) -> bool:
        """
        Resize desktop

        Args:
            new_width: New width
            new_height: New height
            reason: Resize reason code

        Returns:
            True if resize successful
        """
        if new_width <= 0 or new_height <= 0:
            self.logger.error(f"Invalid dimensions: {new_width}x{new_height}")
            return False

        old_size = (self.current_width, self.current_height)
        self.current_width = new_width
        self.current_height = new_height

        # Update primary screen
        self.screens[0] = Screen(
            id=0,
            x=0,
            y=0,
            width=new_width,
            height=new_height
        )

        self.logger.info(f"Desktop resized: {old_size} -> ({new_width}x{new_height}), reason={reason}")
        return True

    def encode_desktop_size_update(self, reason: ResizeReason = REASON_SERVER) -> tuple[int, bytes]:
        """
        Encode desktop size update for transmission

        Returns:
            (encoding_type, encoded_data) tuple

        For ExtendedDesktopSize:
            - number-of-screens (1 byte)
            - padding (3 bytes)
            - screen array (16 bytes per screen)
        """
        if self.supports_extended:
            # ExtendedDesktopSize format
            num_screens = len(self.screens)
            data = bytearray()

            # Header: number-of-screens + padding
            data.extend(struct.pack(">Bxxx", num_screens))

            # Screen array
            for screen in self.screens:
                data.extend(screen.to_bytes())

            self.logger.debug(f"Encoded ExtendedDesktopSize: {num_screens} screen(s)")
            return (self.ENCODING_EXTENDED_DESKTOP_SIZE, bytes(data))
        else:
            # Legacy DesktopSize - no data needed
            return (self.ENCODING_DESKTOP_SIZE, b'')

    def parse_client_resize_request(self, data: bytes) -> tuple[int, int] | None:
        """
        Parse client's resize request

        Args:
            data: Request data from client

        Returns:
            (width, height) tuple if valid, None otherwise
        """
        if len(data) < 4:
            self.logger.warning("Invalid resize request: too short")
            return None

        try:
            width, height = struct.unpack(">HH", data[:4])

            if width <= 0 or height <= 0:
                self.logger.warning(f"Invalid resize request: {width}x{height}")
                return None

            return (width, height)

        except struct.error as e:
            self.logger.error(f"Failed to parse resize request: {e}")
            return None

    def add_screen(self, screen: Screen) -> bool:
        """
        Add a screen to multi-monitor configuration

        Args:
            screen: Screen to add

        Returns:
            True if added successfully
        """
        if not self.supports_extended:
            self.logger.warning("ExtendedDesktopSize not supported")
            return False

        # Check for duplicate ID
        if any(s.id == screen.id for s in self.screens):
            self.logger.warning(f"Screen ID {screen.id} already exists")
            return False

        self.screens.append(screen)
        self.logger.info(f"Added screen {screen.id}: {screen.width}x{screen.height} at ({screen.x}, {screen.y})")
        return True

    def remove_screen(self, screen_id: ScreenID) -> bool:
        """
        Remove a screen from configuration

        Args:
            screen_id: ID of screen to remove

        Returns:
            True if removed successfully
        """
        if screen_id == 0:
            self.logger.error("Cannot remove primary screen (ID 0)")
            return False

        initial_count = len(self.screens)
        self.screens = [s for s in self.screens if s.id != screen_id]

        if len(self.screens) < initial_count:
            self.logger.info(f"Removed screen {screen_id}")
            return True

        self.logger.warning(f"Screen {screen_id} not found")
        return False

    def get_total_dimensions(self) -> tuple[int, int]:
        """
        Calculate total bounding box dimensions

        Returns:
            (width, height) of bounding box containing all screens
        """
        if not self.screens:
            return (0, 0)

        max_x = max(s.x + s.width for s in self.screens)
        max_y = max(s.y + s.height for s in self.screens)

        return (max_x, max_y)

    def validate_layout(self) -> tuple[bool, str]:
        """
        Validate current screen layout

        Returns:
            (is_valid, error_message) tuple
        """
        if not self.screens:
            return (False, "No screens configured")

        # Check for primary screen
        if not any(s.id == 0 for s in self.screens):
            return (False, "No primary screen (ID 0)")

        # Check for overlapping screens (warning, not error)
        for i, screen1 in enumerate(self.screens):
            for screen2 in self.screens[i+1:]:
                if self._screens_overlap(screen1, screen2):
                    self.logger.warning(
                        f"Screens {screen1.id} and {screen2.id} overlap"
                    )

        return (True, "Layout valid")

    def _screens_overlap(self, s1: Screen, s2: Screen) -> bool:
        """Check if two screens overlap"""
        return not (
            s1.x + s1.width <= s2.x or
            s2.x + s2.width <= s1.x or
            s1.y + s1.height <= s2.y or
            s2.y + s2.height <= s1.y
        )

    def handle_resize_event(self, new_width: int, new_height: int,
                           reason: ResizeReason) -> tuple[int, bytes | None]:
        """
        Handle resize event using pattern matching (Python 3.13)

        Args:
            new_width: New width
            new_height: New height
            reason: Resize reason

        Returns:
            (status_code, encoded_data) tuple
        """
        match (new_width > 0, new_height > 0):
            case (True, True):
                # Valid dimensions
                if self.resize(new_width, new_height, reason):
                    encoding_type, data = self.encode_desktop_size_update(reason)
                    return (self.STATUS_NO_ERROR, data)
                else:
                    return (self.STATUS_OUT_OF_RESOURCES, None)

            case (False, _) | (_, False):
                # Invalid dimensions
                self.logger.error(f"Invalid dimensions: {new_width}x{new_height}")
                return (self.STATUS_INVALID_SCREEN_LAYOUT, None)

    def get_status_message(self, status_code: int) -> str:
        """
        Get human-readable status message using pattern matching

        Args:
            status_code: Status code

        Returns:
            Status message string
        """
        match status_code:
            case self.STATUS_NO_ERROR:
                return "Resize successful"
            case self.STATUS_OUT_OF_RESOURCES:
                return "Out of resources"
            case self.STATUS_INVALID_SCREEN_LAYOUT:
                return "Invalid screen layout"
            case _:
                return f"Unknown status: {status_code}"


# Helper functions
def create_single_screen_layout(width: int, height: int) -> list[Screen]:
    """
    Create a single-screen layout

    Args:
        width: Screen width
        height: Screen height

    Returns:
        List containing single screen
    """
    return [Screen(id=0, x=0, y=0, width=width, height=height)]


def create_dual_screen_layout(w1: int, h1: int, w2: int, h2: int,
                              horizontal: bool = True) -> list[Screen]:
    """
    Create a dual-screen layout

    Args:
        w1, h1: Primary screen dimensions
        w2, h2: Secondary screen dimensions
        horizontal: If True, screens are side-by-side; if False, stacked

    Returns:
        List containing two screens
    """
    primary = Screen(id=0, x=0, y=0, width=w1, height=h1)

    if horizontal:
        secondary = Screen(id=1, x=w1, y=0, width=w2, height=h2)
    else:
        secondary = Screen(id=1, x=0, y=h1, width=w2, height=h2)

    return [primary, secondary]
