"""
Type Aliases and Type Definitions for VNC Server
Python 3.13 with enhanced type syntax (PEP 695)
"""

from typing import Protocol, Callable, TypedDict
from collections.abc import Sequence


# ============================================================================
# Basic Types (Python 3.13 type statement)
# ============================================================================

# Binary data types
type PixelData = bytes
type EncodedData = bytes
type AuthChallenge = bytes
type AuthResponse = bytes

# Network types
type IPAddress = str
type Port = int
type ClientID = str
type SocketAddress = tuple[IPAddress, Port]

# Dimensions and coordinates
type Width = int
type Height = int
type XCoordinate = int
type YCoordinate = int
type Dimension = tuple[Width, Height]
type Position = tuple[XCoordinate, YCoordinate]
type Rectangle = tuple[XCoordinate, YCoordinate, Width, Height]

# Time and performance
type Timestamp = float
type Duration = float  # in seconds
type Milliseconds = float
type FPS = float
type CompressionRatio = float

# Protocol types
type ProtocolVersion = tuple[int, int]  # (major, minor)
type SecurityType = int
type EncodingType = int
type MessageType = int

# Color and pixel format
type RGB = tuple[int, int, int]
type RGBA = tuple[int, int, int, int]
type PixelValue = int
type ColorDepth = int
type BitsPerPixel = int
type BytesPerPixel = int

# Configuration
type ConfigValue = str | int | float | bool
type ConfigDict = dict[str, ConfigValue]


# ============================================================================
# Structured Types (TypedDict)
# ============================================================================

class PixelFormat(TypedDict):
    """VNC pixel format structure"""
    bits_per_pixel: BitsPerPixel
    depth: ColorDepth
    big_endian_flag: int
    true_colour_flag: int
    red_max: int
    green_max: int
    blue_max: int
    red_shift: int
    green_shift: int
    blue_shift: int


class FramebufferUpdateRequest(TypedDict):
    """Framebuffer update request from client"""
    incremental: int
    x: XCoordinate
    y: YCoordinate
    width: Width
    height: Height


class KeyEvent(TypedDict):
    """Keyboard event from client"""
    down_flag: int
    key: int


class PointerEvent(TypedDict):
    """Mouse/pointer event from client"""
    button_mask: int
    x: XCoordinate
    y: YCoordinate


class ServerConfig(TypedDict, total=False):
    """Server configuration dictionary"""
    host: IPAddress
    port: Port
    password: str
    frame_rate: FPS
    scale_factor: float
    max_connections: int
    enable_region_detection: bool
    enable_cursor_encoding: bool
    enable_metrics: bool
    log_level: str
    log_file: str


class MetricsSummary(TypedDict):
    """Metrics summary structure"""
    uptime_seconds: Duration
    total_connections: int
    active_connections: int
    failed_auth_attempts: int
    total_frames_sent: int
    total_bytes_sent: int
    avg_fps: FPS


# ============================================================================
# Protocol Interfaces
# ============================================================================

class Encoder(Protocol):
    """Protocol for encoder implementations"""

    ENCODING_TYPE: int

    def encode(self, pixel_data: PixelData, width: Width,
               height: Height, bytes_per_pixel: BytesPerPixel) -> EncodedData:
        """Encode pixel data to specified encoding"""
        ...


class ScreenCapture(Protocol):
    """Protocol for screen capture implementations"""

    def capture(self, pixel_format: PixelFormat) -> tuple[PixelData, Width, Height]:
        """Capture screen with specified pixel format"""
        ...


class AuthHandler(Protocol):
    """Protocol for authentication handlers"""

    def authenticate(self, client_socket) -> bool:
        """Authenticate client"""
        ...


# ============================================================================
# Callback Types
# ============================================================================

type ErrorCallback = Callable[[Exception], None]
type ClientCallback = Callable[[ClientID], None]
type FrameCallback = Callable[[PixelData, Width, Height], None]
type ResizeCallback = Callable[[Width, Height], None]
type LogCallback = Callable[[str, str], None]  # (level, message)

# Health check callback
type HealthCheckFunc = Callable[[], bool]


# ============================================================================
# Generic Bounded Types (Python 3.13)
# ============================================================================

type Numeric = int | float
type MetricValue[T: Numeric] = T
type WindowSize = int


# ============================================================================
# Result Types (for error handling)
# ============================================================================

class Result[T, E]:
    """
    Result type for operations that can fail
    Python 3.13 generic class with type parameters

    Example:
        >>> def divide(a: float, b: float) -> Result[float, str]:
        ...     if b == 0:
        ...         return Err("Division by zero")
        ...     return Ok(a / b)
    """

    def __init__(self, value: T | None = None, error: E | None = None):
        self._value = value
        self._error = error
        self._is_ok = error is None

    @classmethod
    def ok(cls, value: T) -> 'Result[T, E]':
        """Create successful result"""
        return cls(value=value, error=None)

    @classmethod
    def err(cls, error: E) -> 'Result[T, E]':
        """Create error result"""
        return cls(value=None, error=error)

    def is_ok(self) -> bool:
        """Check if result is successful"""
        return self._is_ok

    def is_err(self) -> bool:
        """Check if result is error"""
        return not self._is_ok

    def unwrap(self) -> T:
        """Get value or raise exception"""
        if self._is_ok:
            return self._value  # type: ignore
        raise ValueError(f"Called unwrap on error: {self._error}")

    def unwrap_or(self, default: T) -> T:
        """Get value or return default"""
        return self._value if self._is_ok else default  # type: ignore

    def unwrap_err(self) -> E:
        """Get error or raise exception"""
        if not self._is_ok:
            return self._error  # type: ignore
        raise ValueError("Called unwrap_err on ok result")


# Convenience constructors
def Ok[T, E](value: T) -> Result[T, E]:
    """Create successful result"""
    return Result.ok(value)


def Err[T, E](error: E) -> Result[T, E]:
    """Create error result"""
    return Result.err(error)


# ============================================================================
# Encoding-specific types
# ============================================================================

type RawData = bytes
type CompressedData = bytes
type RLEData = bytes
type TileData = bytes
type SubrectangleData = bytes

# CopyRect
type SourcePosition = tuple[XCoordinate, YCoordinate]

# Hextile
type SubencodingMask = int
type TileIndex = tuple[int, int]

# ZRLE
type CPIXELData = bytes
type CompressionLevel = int


# ============================================================================
# Change detection types
# ============================================================================

type TileChecksum = bytes
type TileCoordinate = tuple[int, int]
type ChangeScore = float
type RegionList = list[Rectangle]


# ============================================================================
# Cursor types
# ============================================================================

type CursorPixelData = bytes
type CursorBitmask = bytes
type HotspotX = int
type HotspotY = int


# ============================================================================
# Statistics types
# ============================================================================

class EncodingStats(TypedDict):
    """Statistics for an encoding type"""
    encoding_type: EncodingType
    frames_encoded: int
    total_bytes: int
    avg_compression_ratio: CompressionRatio
    avg_encode_time: Duration


class ConnectionStats(TypedDict):
    """Statistics for a client connection"""
    client_id: ClientID
    connected_at: Timestamp
    frames_sent: int
    bytes_sent: int
    bytes_received: int
    avg_fps: FPS
    errors: int


# ============================================================================
# Type guards and validators
# ============================================================================

def is_valid_dimension(width: int, height: int) -> bool:
    """Type guard for valid dimensions"""
    return width > 0 and height > 0 and width <= 65535 and height <= 65535


def is_valid_pixel_format(pf: PixelFormat) -> bool:
    """Type guard for valid pixel format"""
    return (
        pf['bits_per_pixel'] in (8, 16, 32) and
        pf['depth'] <= pf['bits_per_pixel'] and
        pf['red_max'] > 0 and
        pf['green_max'] > 0 and
        pf['blue_max'] > 0
    )


def is_valid_encoding_type(enc: int) -> bool:
    """Type guard for valid encoding type"""
    # Standard encodings: 0-16, pseudo-encodings: negative
    return -1000 <= enc <= 1000


# ============================================================================
# Type narrowing helpers (Python 3.13)
# ============================================================================

def narrow_bytes(data: bytes | bytearray | memoryview) -> bytes:
    """
    Narrow union type to bytes

    Example with pattern matching:
        match data:
            case bytes() as b:
                return b
            case bytearray() | memoryview() as other:
                return bytes(other)
    """
    match data:
        case bytes():
            return data
        case bytearray() | memoryview():
            return bytes(data)
        case _:
            raise TypeError(f"Expected bytes-like object, got {type(data)}")


def narrow_positive_int(value: int, name: str = "value") -> int:
    """Narrow int to positive int with validation"""
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


# ============================================================================
# Constants as types (for pattern matching)
# ============================================================================

class EncodingTypes:
    """Encoding type constants"""
    RAW: EncodingType = 0
    COPYRECT: EncodingType = 1
    RRE: EncodingType = 2
    HEXTILE: EncodingType = 5
    ZRLE: EncodingType = 16
    CURSOR: EncodingType = -239
    DESKTOP_SIZE: EncodingType = -223
    EXTENDED_DESKTOP_SIZE: EncodingType = -308


class MessageTypes:
    """Message type constants"""
    # Client to Server
    SET_PIXEL_FORMAT: MessageType = 0
    SET_ENCODINGS: MessageType = 2
    FRAMEBUFFER_UPDATE_REQUEST: MessageType = 3
    KEY_EVENT: MessageType = 4
    POINTER_EVENT: MessageType = 5
    CLIENT_CUT_TEXT: MessageType = 6

    # Server to Client
    FRAMEBUFFER_UPDATE: MessageType = 0
    SET_COLOR_MAP_ENTRIES: MessageType = 1
    BELL: MessageType = 2
    SERVER_CUT_TEXT: MessageType = 3


class SecurityTypes:
    """Security type constants"""
    INVALID: SecurityType = 0
    NONE: SecurityType = 1
    VNC_AUTH: SecurityType = 2
