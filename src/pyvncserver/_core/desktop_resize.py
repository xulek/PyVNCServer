"""DesktopSize and ExtendedDesktopSize helpers for modern RFB clients."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import struct
from typing import Iterable, TypeAlias


ScreenID: TypeAlias = int
ResizeReason: TypeAlias = int


@dataclass(frozen=True, slots=True)
class Screen:
    """One screen in an ExtendedDesktopSize layout.

    RFB encodes every screen in exactly 16 bytes:
    id(4), x(2), y(2), width(2), height(2), flags(4).
    """

    id: ScreenID
    x: int
    y: int
    width: int
    height: int
    flags: int = 0

    WIRE_SIZE = 16

    def validate(self) -> None:
        if not 0 <= self.id <= 0xFFFFFFFF:
            raise ValueError(f"Invalid screen id: {self.id}")
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            if not 0 <= int(value) <= 0xFFFF:
                raise ValueError(f"Screen {name} out of range: {value}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"Screen dimensions must be positive: {self.width}x{self.height}"
            )
        if self.x + self.width > 0x10000 or self.y + self.height > 0x10000:
            raise ValueError("Screen extends beyond RFB 16-bit coordinate space")
        if not 0 <= self.flags <= 0xFFFFFFFF:
            raise ValueError(f"Invalid screen flags: {self.flags}")

    def to_bytes(self) -> bytes:
        self.validate()
        return struct.pack(
            ">IHHHHI",
            self.id,
            self.x,
            self.y,
            self.width,
            self.height,
            self.flags,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "Screen":
        if len(data) < cls.WIRE_SIZE:
            raise ValueError(f"Invalid screen data length: {len(data)}")
        screen = cls(*struct.unpack(">IHHHHI", data[: cls.WIRE_SIZE]))
        screen.validate()
        return screen


class DesktopSizeHandler:
    """Track and encode the server desktop layout."""

    ENCODING_DESKTOP_SIZE = -223
    ENCODING_EXTENDED_DESKTOP_SIZE = -308

    STATUS_NO_ERROR = 0
    STATUS_ADMINISTRATIVELY_PROHIBITED = 1
    STATUS_OUT_OF_RESOURCES = 2
    STATUS_INVALID_SCREEN_LAYOUT = 3

    REASON_SERVER = 0
    REASON_CLIENT = 1
    REASON_OTHER = 2

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.current_width = 0
        self.current_height = 0
        self.screens: list[Screen] = []
        self.supports_extended = False

    def initialize(
        self,
        width: int,
        height: int,
        screens: Iterable[Screen] | None = None,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid desktop dimensions: {width}x{height}")
        self.current_width = int(width)
        self.current_height = int(height)
        self.screens = list(screens or create_single_screen_layout(width, height))
        valid, message = self.validate_layout()
        if not valid:
            raise ValueError(message)

    def set_layout(
        self,
        width: int,
        height: int,
        screens: Iterable[Screen],
    ) -> None:
        old = (self.current_width, self.current_height, list(self.screens))
        self.current_width = int(width)
        self.current_height = int(height)
        self.screens = list(screens)
        valid, message = self.validate_layout()
        if not valid:
            self.current_width, self.current_height, self.screens = old
            raise ValueError(message)

    def resize(
        self,
        new_width: int,
        new_height: int,
        reason: ResizeReason = REASON_SERVER,
    ) -> bool:
        if new_width <= 0 or new_height <= 0:
            return False
        self.current_width = int(new_width)
        self.current_height = int(new_height)
        if len(self.screens) <= 1:
            self.screens = create_single_screen_layout(new_width, new_height)
        self.logger.info(
            "Desktop resized to %dx%d, reason=%d",
            new_width,
            new_height,
            reason,
        )
        return True

    def encode_extended_payload(self) -> bytes:
        if not self.screens:
            raise ValueError("Cannot encode an empty screen layout")
        if len(self.screens) > 255:
            raise ValueError("ExtendedDesktopSize supports at most 255 screens")
        valid, message = self.validate_layout()
        if not valid:
            raise ValueError(message)

        return (
            struct.pack(">Bxxx", len(self.screens))
            + b"".join(screen.to_bytes() for screen in self.screens)
        )

    def encode_desktop_size_update(
        self, reason: ResizeReason = REASON_SERVER
    ) -> tuple[int, bytes]:
        del reason  # reason lives in the rectangle x coordinate, not the payload.
        if self.supports_extended:
            return self.ENCODING_EXTENDED_DESKTOP_SIZE, self.encode_extended_payload()
        return self.ENCODING_DESKTOP_SIZE, b""

    def make_update_rectangle(
        self,
        *,
        reason: ResizeReason = REASON_SERVER,
        status: int = STATUS_NO_ERROR,
    ) -> tuple[int, int, int, int, int, bytes]:
        if self.supports_extended:
            return (
                int(reason),
                int(status),
                self.current_width,
                self.current_height,
                self.ENCODING_EXTENDED_DESKTOP_SIZE,
                self.encode_extended_payload(),
            )
        return (
            0,
            0,
            self.current_width,
            self.current_height,
            self.ENCODING_DESKTOP_SIZE,
            b"",
        )

    def parse_client_resize_request(self, data: bytes) -> tuple[int, int] | None:
        if len(data) < 4:
            return None
        width, height = struct.unpack(">HH", data[:4])
        if width <= 0 or height <= 0:
            return None
        return width, height

    def add_screen(self, screen: Screen) -> bool:
        if not self.supports_extended:
            return False
        if any(existing.id == screen.id for existing in self.screens):
            return False
        candidate = self.screens + [screen]
        old = self.screens
        self.screens = candidate
        valid, _ = self.validate_layout()
        if not valid:
            self.screens = old
            return False
        return True

    def remove_screen(self, screen_id: ScreenID) -> bool:
        if screen_id == 0:
            return False
        new_screens = [screen for screen in self.screens if screen.id != screen_id]
        if len(new_screens) == len(self.screens):
            return False
        self.screens = new_screens
        return True

    def get_total_dimensions(self) -> tuple[int, int]:
        if not self.screens:
            return 0, 0
        return (
            max(screen.x + screen.width for screen in self.screens),
            max(screen.y + screen.height for screen in self.screens),
        )

    def validate_layout(self) -> tuple[bool, str]:
        if self.current_width <= 0 or self.current_height <= 0:
            return False, "Desktop dimensions must be positive"
        if not self.screens:
            return False, "No screens configured"
        if len(self.screens) > 255:
            return False, "Too many screens"
        if len({screen.id for screen in self.screens}) != len(self.screens):
            return False, "Duplicate screen id"

        for screen in self.screens:
            try:
                screen.validate()
            except ValueError as exc:
                return False, str(exc)
            if (
                screen.x + screen.width > self.current_width
                or screen.y + screen.height > self.current_height
            ):
                return False, (
                    f"Screen {screen.id} is outside desktop "
                    f"{self.current_width}x{self.current_height}"
                )
        return True, "Layout valid"

    def handle_resize_event(
        self,
        new_width: int,
        new_height: int,
        reason: ResizeReason,
    ) -> tuple[int, bytes | None]:
        if not self.resize(new_width, new_height, reason):
            return self.STATUS_INVALID_SCREEN_LAYOUT, None
        _encoding, data = self.encode_desktop_size_update(reason)
        return self.STATUS_NO_ERROR, data

    def get_status_message(self, status_code: int) -> str:
        return {
            self.STATUS_NO_ERROR: "Resize successful",
            self.STATUS_ADMINISTRATIVELY_PROHIBITED: "Resize administratively prohibited",
            self.STATUS_OUT_OF_RESOURCES: "Out of resources",
            self.STATUS_INVALID_SCREEN_LAYOUT: "Invalid screen layout",
        }.get(status_code, f"Unknown status: {status_code}")

    @staticmethod
    def _screens_overlap(first: Screen, second: Screen) -> bool:
        return not (
            first.x + first.width <= second.x
            or second.x + second.width <= first.x
            or first.y + first.height <= second.y
            or second.y + second.height <= first.y
        )


def create_single_screen_layout(width: int, height: int) -> list[Screen]:
    return [Screen(id=0, x=0, y=0, width=width, height=height)]


def create_dual_screen_layout(
    w1: int,
    h1: int,
    w2: int,
    h2: int,
    horizontal: bool = True,
) -> list[Screen]:
    primary = Screen(id=0, x=0, y=0, width=w1, height=h1)
    secondary = (
        Screen(id=1, x=w1, y=0, width=w2, height=h2)
        if horizontal
        else Screen(id=1, x=0, y=h1, width=w2, height=h2)
    )
    return [primary, secondary]


def screens_from_monitor_rects(
    monitors: Iterable[dict],
    *,
    virtual_left: int = 0,
    virtual_top: int = 0,
) -> list[Screen]:
    """Convert MSS-style monitor dictionaries to normalized RFB screens."""
    screens: list[Screen] = []
    for index, monitor in enumerate(monitors):
        screens.append(
            Screen(
                id=index,
                x=int(monitor["left"]) - int(virtual_left),
                y=int(monitor["top"]) - int(virtual_top),
                width=int(monitor["width"]),
                height=int(monitor["height"]),
                flags=0,
            )
        )
    return screens
