# Python 3.13 Specific Improvements for PyVNCServer

This document provides concrete Python 3.13 improvements that can be made to enhance code quality, readability, and performance.

## 1. Structural Pattern Matching (PEP 634) - HIGH PRIORITY

### Use Case 1: Message Type Handling in protocol.py

**Current Implementation:**
```python
def handle_client_message(self, client_socket, message_type):
    if message_type == self.MSG_SET_PIXEL_FORMAT:
        handle_set_pixel_format(client_socket)
    elif message_type == self.MSG_SET_ENCODINGS:
        handle_set_encodings(client_socket)
    elif message_type == self.MSG_FRAMEBUFFER_UPDATE_REQUEST:
        handle_framebuffer_update(client_socket)
    elif message_type == self.MSG_KEY_EVENT:
        handle_key_event(client_socket)
    elif message_type == self.MSG_POINTER_EVENT:
        handle_pointer_event(client_socket)
    elif message_type == self.MSG_CLIENT_CUT_TEXT:
        handle_cut_text(client_socket)
    else:
        raise ValueError(f"Unknown message type: {message_type}")
```

**Python 3.13 Improvement:**
```python
def handle_client_message(self, client_socket, message_type):
    match message_type:
        case self.MSG_SET_PIXEL_FORMAT:
            handle_set_pixel_format(client_socket)
        case self.MSG_SET_ENCODINGS:
            handle_set_encodings(client_socket)
        case self.MSG_FRAMEBUFFER_UPDATE_REQUEST:
            handle_framebuffer_update(client_socket)
        case self.MSG_KEY_EVENT:
            handle_key_event(client_socket)
        case self.MSG_POINTER_EVENT:
            handle_pointer_event(client_socket)
        case self.MSG_CLIENT_CUT_TEXT:
            handle_cut_text(client_socket)
        case _:
            raise ValueError(f"Unknown message type: {message_type}")
```

**Benefits:**
- More Pythonic and readable
- Easier to extend with new message types
- Better IDE support and linting
- Clearer intent

---

### Use Case 2: Encoding Selection in encodings.py

**Current Implementation:**
```python
class EncoderManager:
    def get_best_encoder(self, client_encodings, content_type="dynamic"):
        if 16 in client_encodings:  # ZRLE
            return 16, ZRLEEncoder()
        elif 5 in client_encodings:  # Hextile
            return 5, HextileEncoder()
        elif 2 in client_encodings:  # RRE
            return 2, RREEncoder()
        elif 0 in client_encodings:  # Raw
            return 0, RawEncoder()
        else:
            raise ValueError("Client supports no encodings")
```

**Python 3.13 Improvement:**
```python
class EncoderManager:
    def get_best_encoder(self, client_encodings: set[int], content_type: str = "dynamic") -> tuple[int, Encoder]:
        match (16 in client_encodings, 5 in client_encodings, 2 in client_encodings, 0 in client_encodings):
            case (True, _, _, _):  # ZRLE available
                return 16, ZRLEEncoder()
            case (_, True, _, _) if content_type == "dynamic":  # Hextile for dynamic
                return 5, HextileEncoder()
            case (_, _, True, _) if content_type == "static":  # RRE for static
                return 2, RREEncoder()
            case (_, _, _, True):  # Raw fallback
                return 0, RawEncoder()
            case _:
                raise ValueError("Client supports no encodings")
```

**Alternative with more elegant pattern:**
```python
def get_best_encoder(self, client_encodings: set[int], content_type: str = "dynamic") -> tuple[int, Encoder]:
    match (content_type, sorted(client_encodings, reverse=True)):
        case ("static", encs) if 16 in encs or 2 in encs:
            # ZRLE or RRE for static content
            return (16, ZRLEEncoder()) if 16 in encs else (2, RREEncoder())
        case ("dynamic", encs) if 5 in encs:
            # Hextile for dynamic content
            return 5, HextileEncoder()
        case (_, encs) if 0 in encs:
            # Raw fallback
            return 0, RawEncoder()
        case _:
            raise ValueError(f"No compatible encoding for {content_type}")
```

---

### Use Case 3: Region Change Detection in change_detector.py

**Current Implementation:**
```python
def update_and_get_changed(self, pixel_data, bytes_per_pixel):
    changed_regions = []
    
    for ty in range(self.tiles_y):
        for tx in range(self.tiles_x):
            tile_data = self._extract_tile(pixel_data, tx, ty, bytes_per_pixel)
            checksum = hashlib.md5(tile_data).digest()
            key = (tx, ty)
            
            # Check if tile changed
            if key not in self.tile_checksums:
                changed_regions.append(Region(tx * self.tile_size, ty * self.tile_size, 
                                            self.tile_size, self.tile_size))
                self.tile_checksums[key] = checksum
            elif self.tile_checksums[key] != checksum:
                changed_regions.append(Region(tx * self.tile_size, ty * self.tile_size, 
                                            self.tile_size, self.tile_size))
                self.tile_checksums[key] = checksum
    
    return changed_regions
```

**Python 3.13 Improvement:**
```python
def update_and_get_changed(self, pixel_data: bytes, bytes_per_pixel: int) -> list[Region]:
    changed_regions = []
    
    for ty in range(self.tiles_y):
        for tx in range(self.tiles_x):
            tile_data = self._extract_tile(pixel_data, tx, ty, bytes_per_pixel)
            checksum = hashlib.md5(tile_data).digest()
            key = (tx, ty)
            
            # Use pattern matching for change detection
            match (key in self.tile_checksums, self.tile_checksums.get(key) == checksum):
                case (False, _):  # First capture of this tile
                    changed_regions.append(self._make_region(tx, ty))
                    self.tile_checksums[key] = checksum
                case (True, False):  # Tile has changed
                    changed_regions.append(self._make_region(tx, ty))
                    self.tile_checksums[key] = checksum
                case (True, True):  # No change
                    pass
    
    return changed_regions
```

---

## 2. Enhanced Generic Type Parameters (PEP 695)

### Use Case 1: Generic Encoder Interface

**Current Implementation:**
```python
from typing import Protocol, Generic, TypeVar

T = TypeVar('T')

class Encoder(Protocol):
    def encode(self, pixel_data: bytes, width: int, height: int,
               bytes_per_pixel: int) -> bytes:
        ...
```

**Python 3.13 Improvement:**
```python
from typing import Protocol

type EncodedResult = bytes
type PixelBuffer = bytes | memoryview

class Encoder(Protocol):
    """Generic encoder interface with better type safety"""
    
    def encode(self, pixel_data: PixelBuffer, width: int, height: int,
               bytes_per_pixel: int) -> EncodedResult:
        ...

# Type alias for encoder factories
type EncoderFactory = Callable[[], Encoder]

# Specific type aliases
type CompressionRatio = float
type EncodingMetrics = tuple[EncodedResult, CompressionRatio]
```

---

### Use Case 2: Metrics with Generics

**Current Implementation:**
```python
from typing import Deque, Generic, TypeVar
from collections import deque

T = TypeVar('T')

class SlidingWindow(Generic[T]):
    """Generic sliding window for metrics"""
    
    def __init__(self, maxlen: int = 100):
        self.window: Deque[T] = deque(maxlen=maxlen)
    
    def add(self, value: T) -> None:
        self.window.append(value)
    
    def average(self) -> float:
        if not self.window:
            return 0.0
        return sum(self.window) / len(self.window)
```

**Python 3.13 Improvement:**
```python
from collections import deque

type Numeric = int | float
type MetricValue[T: Numeric] = T

class SlidingWindow[T: Numeric]:
    """Generic sliding window with Python 3.13 type syntax"""
    
    def __init__(self, maxlen: int = 100):
        self.window: deque[T] = deque(maxlen=maxlen)
    
    def add(self, value: T) -> None:
        self.window.append(value)
    
    def average(self) -> float:
        if not self.window:
            return 0.0
        return sum(self.window) / len(self.window)  # type: ignore
    
    def min(self) -> T | None:
        return min(self.window) if self.window else None
    
    def max(self) -> T | None:
        return max(self.window) if self.window else None

# Usage
fps_window: SlidingWindow[float] = SlidingWindow(maxlen=100)
encoding_time_window: SlidingWindow[float] = SlidingWindow(maxlen=100)
```

---

## 3. Exception Groups (PEP 654)

### Use Case: Multi-Client Error Handling in vnc_server_v3.py

**Current Implementation:**
```python
def handle_multiple_clients(self, client_sockets):
    errors = []
    
    for client_socket in client_sockets:
        try:
            self.handle_client(client_socket)
        except ConnectionError as e:
            errors.append(("connection", e))
        except AuthenticationError as e:
            errors.append(("auth", e))
        except Exception as e:
            errors.append(("unknown", e))
    
    if errors:
        self.logger.error(f"Multiple errors occurred: {len(errors)}")
        for error_type, error in errors:
            self.logger.error(f"  {error_type}: {error}")
```

**Python 3.13 Improvement:**
```python
def handle_multiple_clients(self, client_sockets) -> None:
    """Handle multiple clients with better error grouping"""
    exceptions: list[Exception] = []
    
    for client_socket in client_sockets:
        try:
            self.handle_client(client_socket)
        except (ConnectionError, AuthenticationError, Exception) as e:
            exceptions.append(e)
    
    if exceptions:
        # Group exceptions by type
        try:
            raise ExceptionGroup("Multiple client errors", exceptions)
        except ExceptionGroup as eg:
            # Filter and handle by type
            connection_errors = [e for e in eg.exceptions 
                               if isinstance(e, ConnectionError)]
            auth_errors = [e for e in eg.exceptions 
                          if isinstance(e, AuthenticationError)]
            
            if connection_errors:
                self.logger.error(f"Connection errors: {len(connection_errors)}")
                for e in connection_errors:
                    self.logger.error(f"  {e}")
            
            if auth_errors:
                self.logger.error(f"Auth errors: {len(auth_errors)}")
                for e in auth_errors:
                    self.logger.error(f"  {e}")
            
            # Re-raise critical errors
            if any(isinstance(e, ConnectionError) for e in eg.exceptions):
                raise eg
```

---

## 4. Type Narrowing Improvements

### Use Case 1: Pixel Format Handling in screen_capture.py

**Current Implementation:**
```python
def convert_to_format(self, pixel_data: bytes | bytearray, fmt: str) -> bytes:
    if isinstance(pixel_data, bytes):
        data = pixel_data
    elif isinstance(pixel_data, bytearray):
        data = bytes(pixel_data)
    else:
        raise TypeError(f"Expected bytes or bytearray, got {type(pixel_data)}")
    
    # Use data...
    return data
```

**Python 3.13 Improvement with Pattern Matching:**
```python
def convert_to_format(self, pixel_data: bytes | bytearray, fmt: str) -> bytes:
    """Convert pixel data to target format with type narrowing"""
    match pixel_data:
        case bytes() as data:  # Type narrowing in pattern
            return self._apply_format(data, fmt)
        case bytearray() as data:  # Type narrowing
            return self._apply_format(bytes(data), fmt)
        case _:
            raise TypeError(f"Expected bytes or bytearray, got {type(pixel_data)}")
```

---

### Use Case 2: Encoding Fallback Chain in encodings.py

**Current Implementation:**
```python
def encode(self, pixel_data, width, height, bytes_per_pixel):
    if bytes_per_pixel not in (1, 2, 4):
        self.logger.warning(f"Unsupported bpp: {bytes_per_pixel}")
        return pixel_data
    
    # Encoding logic...
    result = self._encode(pixel_data, width, height, bytes_per_pixel)
    
    if len(result) >= len(pixel_data):
        # Fallback to raw if not better
        return pixel_data
    
    return result
```

**Python 3.13 Improvement with Narrowing:**
```python
def encode(self, pixel_data: bytes, width: int, height: int,
           bytes_per_pixel: int) -> bytes:
    """Encode with better type narrowing and pattern matching"""
    # Check supported formats first
    match bytes_per_pixel:
        case 1 | 2 | 4:  # Supported formats
            result = self._encode(pixel_data, width, height, bytes_per_pixel)
        case other:  # Type narrowed - other is int
            self.logger.warning(f"Unsupported bpp: {other}")
            return pixel_data
    
    # Check compression effectiveness
    match len(result) < len(pixel_data):
        case True:  # Compression effective
            return result
        case False:  # Not effective, use raw
            return pixel_data
```

---

## 5. Better Data Structure Typing

### Use Case: Cursor Data in cursor.py

**Current Implementation:**
```python
from typing import NamedTuple

class CursorData(NamedTuple):
    width: int
    height: int
    hotspot_x: int
    hotspot_y: int
    pixel_data: bytes  # RGBA pixel data
    bitmask: bytes     # Transparency bitmask
    
    def is_valid(self) -> bool:
        expected_pixels = self.width * self.height
        return (len(self.pixel_data) == expected_pixels * 4 and
                len(self.bitmask) >= (expected_pixels + 7) // 8)
```

**Python 3.13 Enhancement:**
```python
from typing import NamedTuple

# Type aliases for better clarity
type PixelRGBA = bytes
type TransparencyMask = bytes

class CursorData(NamedTuple):
    """Cursor data with Python 3.13 type annotations"""
    width: int
    height: int
    hotspot_x: int
    hotspot_y: int
    pixel_data: PixelRGBA
    bitmask: TransparencyMask
    
    @property
    def size(self) -> int:
        """Get cursor size in pixels"""
        return self.width * self.height
    
    def is_valid(self) -> bool:
        """Validate cursor data integrity"""
        expected_pixels = self.size
        return (
            len(self.pixel_data) == expected_pixels * 4 and
            len(self.bitmask) >= (expected_pixels + 7) // 8 and
            self.width > 0 and self.height > 0
        )
    
    def validate(self) -> None:
        """Validate or raise TypeError"""
        if not self.is_valid():
            raise ValueError(
                f"Invalid CursorData: {self.width}x{self.height} "
                f"pixel_data={len(self.pixel_data)} "
                f"bitmask={len(self.bitmask)}"
            )
```

---

## 6. Improved Error Handling with Better Messages

### Use Case: Authentication Errors in auth.py

**Current Implementation:**
```python
def authenticate(self, client_socket) -> bool:
    try:
        challenge = os.urandom(self.CHALLENGE_SIZE)
        client_socket.sendall(challenge)
        response = self._recv_exact(client_socket, self.CHALLENGE_SIZE)
        
        if not response:
            return False
        
        expected = self._encrypt_challenge(challenge)
        return response == expected
    except Exception as e:
        self.logger.error(f"Auth error: {e}")
        return False
```

**Python 3.13 Improvement with Better Error Context:**
```python
def authenticate(self, client_socket) -> bool:
    """Authenticate with improved error handling"""
    try:
        challenge = os.urandom(self.CHALLENGE_SIZE)
        client_socket.sendall(challenge)
        
        response = self._recv_exact(client_socket, self.CHALLENGE_SIZE)
        if not response:
            raise AuthenticationError("Client did not respond to challenge")
        
        expected = self._encrypt_challenge(challenge)
        
        if response != expected:
            raise AuthenticationError("Challenge-response mismatch")
        
        return True
        
    except AuthenticationError as e:
        self.logger.warning(f"Authentication failed: {e}")
        return False
    except (BrokenPipeError, ConnectionResetError) as e:
        self.logger.warning(f"Connection lost during auth: {e}")
        return False
    except Exception as e:
        self.logger.error(f"Unexpected auth error: {e}", exc_info=True)
        return False
```

---

## 7. Async/Await Considerations for Future (Not Required)

While not necessary now, Python 3.13 async improvements could enable:

```python
# Potential future improvement - asyncio-based server
import asyncio

class AsyncVNCServer:
    """Async version for better scalability"""
    
    async def handle_client(self, reader, writer):
        """Handle single client connection asynchronously"""
        try:
            # Async version of protocol negotiation
            await self.async_negotiate_version(reader, writer)
            await self.async_negotiate_security(reader, writer)
            
            # Main event loop
            while not self.shutdown_handler.is_shutting_down():
                try:
                    message = await self.async_receive_message(reader)
                    await self.async_handle_message(message, writer)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"Error handling message: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def main(self):
        """Main async server loop"""
        server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        
        async with server:
            await server.serve_forever()
```

Benefits of async migration:
- Scale to 10,000+ concurrent connections
- Better resource efficiency
- Native cancellation support
- Better integration with async libraries

---

## Summary of Recommended Changes

| Priority | Change | File | Impact |
|----------|--------|------|--------|
| HIGH | Pattern matching for messages | protocol.py | Readability |
| HIGH | Pattern matching for encodings | encodings.py | Readability |
| HIGH | Type aliases | All files | Type safety |
| MEDIUM | Exception groups | vnc_server_v3.py | Error handling |
| MEDIUM | Type narrowing | screen_capture.py, encodings.py | Type safety |
| MEDIUM | Generic encoder types | encodings.py | Type safety |
| LOW | Async migration | vnc_server_v3.py | Scalability |

---

## Implementation Guide

### Phase 1: Quick Wins (1 week)
1. Add type aliases with `type` statement
2. Replace major `if/elif/else` chains with `match` statements
3. Update union types to use `|` syntax

### Phase 2: Enhanced Type Safety (1 week)
1. Add generic type parameters to encoders
2. Implement better type narrowing in pixel conversion
3. Add exception groups for error handling

### Phase 3: Future Consideration (TBD)
1. Evaluate async/await migration
2. Consider sub-interpreters for parallelism
3. Profile and optimize critical paths

All changes maintain backward compatibility with Python 3.13+.
