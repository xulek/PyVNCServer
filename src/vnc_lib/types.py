"""
Type Aliases and Type Definitions for VNC Server
"""

from typing import Protocol, Callable, TypedDict, TypeAlias


# ============================================================================
# Basic Types
# ============================================================================

PixelData: TypeAlias = bytes
EncodedData: TypeAlias = bytes

IPAddress: TypeAlias = str
Port: TypeAlias = int
ClientID: TypeAlias = str

Width: TypeAlias = int
Height: TypeAlias = int
XCoordinate: TypeAlias = int
YCoordinate: TypeAlias = int
Rectangle: TypeAlias = tuple[XCoordinate, YCoordinate, Width, Height]

Timestamp: TypeAlias = float
Duration: TypeAlias = float
FPS: TypeAlias = float
CompressionRatio: TypeAlias = float

EncodingType: TypeAlias = int
MessageType: TypeAlias = int
SecurityType: TypeAlias = int

BitsPerPixel: TypeAlias = int
BytesPerPixel: TypeAlias = int
ColorDepth: TypeAlias = int


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
        ...


class ScreenCapture(Protocol):
    """Protocol for screen capture implementations"""

    def capture(self, pixel_format: PixelFormat) -> tuple[PixelData, Width, Height]:
        ...


class AuthHandler(Protocol):
    """Protocol for authentication handlers"""

    def authenticate(self, client_socket) -> bool:
        ...


# ============================================================================
# Callback Types
# ============================================================================

ErrorCallback: TypeAlias = Callable[[Exception], None]
ClientCallback: TypeAlias = Callable[[ClientID], None]
FrameCallback: TypeAlias = Callable[[PixelData, Width, Height], None]
ResizeCallback: TypeAlias = Callable[[Width, Height], None]
LogCallback: TypeAlias = Callable[[str, str], None]
HealthCheckFunc: TypeAlias = Callable[[], bool]


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

def is_valid_pixel_format(pf: PixelFormat) -> bool:
    """Type guard for valid pixel format"""
    return (
        pf['bits_per_pixel'] in (8, 16, 32) and
        pf['depth'] <= pf['bits_per_pixel'] and
        pf['red_max'] > 0 and
        pf['green_max'] > 0 and
        pf['blue_max'] > 0
    )


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
    POINTER_POS: EncodingType = -232
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
    TIGHT: SecurityType = 16
    VENCRYPT: SecurityType = 19
