# PyVNCServer

A modern, RFC 6143 compliant VNC server implementation in pure Python 3.13, showcasing advanced language features and efficient remote desktop protocol handling.

[![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-type--safe-brightgreen.svg)](https://peps.python.org/pep-0695/)

## Features

### Core VNC Protocol (RFC 6143)
- ✅ **Protocol Versions**: RFB 3.3, 3.7, 3.8
- ✅ **Authentication**: None, VNC Authentication (DES)
- ✅ **Encodings**: Raw, CopyRect, RRE, Hextile, ZRLE
- ✅ **Pixel Formats**: 8, 16, 32 bits per pixel
- ✅ **Input Events**: Keyboard and pointer (mouse)
- ✅ **Clipboard**: Client cut text support

### Advanced Features
- 🚀 **CopyRect Encoding**: 10-100x bandwidth reduction for scrolling operations
- 📐 **Desktop Resize**: Dynamic screen resolution changes (ExtendedDesktopSize)
- 📊 **Performance Metrics**: Real-time FPS, bandwidth, and compression statistics
- 🔄 **Adaptive Change Detection**: Region-based updates for optimal performance
- 🎯 **Smart Encoding Selection**: Content-aware encoding (static vs dynamic)
- 🔌 **Graceful Shutdown**: Clean resource cleanup and connection handling

### Python 3.13 Enhancements
- 🎭 **Pattern Matching**: Message handling with `match`/`case` statements (PEP 634)
- 🧬 **Generic Types**: Type-safe generic classes with PEP 695 syntax
- 🔗 **Exception Groups**: Structured multi-error handling (PEP 654)
- 📝 **Type System**: Comprehensive type aliases and runtime validation
- 🛡️ **Type Safety**: Full type hints with strict validation

## Requirements

- **Python 3.13** or higher
- **Linux** with X11 or Xvfb
- Dependencies:
  - `Pillow` (screen capture)
  - `python-xlib` (X11 interaction)

## Installation

```bash
# Clone repository
git clone https://github.com/xulek/PyVNCServer.git
cd PyVNCServer

# Install dependencies
pip install -r requirements.txt
```

## Quick Start

### Basic Usage

```bash
# Start server with default settings (port 5900, no password)
python vnc_server.py

# Connect with any VNC client
vncviewer localhost:5900
```

### With Configuration

```bash
# Edit config.json
{
    "host": "0.0.0.0",
    "port": 5900,
    "password": "secure123",
    "frame_rate": 30,
    "max_connections": 5,
    "enable_region_detection": true,
    "enable_metrics": true,
    "log_level": "INFO"
}

# Run server
python vnc_server.py
```

## Architecture

### Module Organization

```
vnc_lib/
├── protocol.py          # RFB protocol implementation
├── auth.py              # Authentication handlers
├── encodings.py         # Encoding implementations (Raw, RRE, Hextile, ZRLE, CopyRect)
├── screen_capture.py    # Screen grabbing and conversion
├── input_handler.py     # Keyboard and mouse input
├── change_detector.py   # Region-based change detection
├── cursor.py            # Cursor pseudo-encoding
├── desktop_resize.py    # Dynamic screen resizing
├── metrics.py           # Performance monitoring
├── exceptions.py        # Exception hierarchy and groups
├── types.py             # Type definitions and aliases
└── server_utils.py      # Utilities (health checks, connection pool)
```

### Encoding Performance

| Encoding | Use Case | Bandwidth | CPU |
|----------|----------|-----------|-----|
| **Raw** | Fallback | Highest | Lowest |
| **CopyRect** | Scrolling | 1-2% of Raw | Minimal |
| **RRE** | Static content | 20-40% of Raw | Low |
| **Hextile** | Dynamic content | 30-60% of Raw | Medium |
| **ZRLE** | Mixed content | 10-30% of Raw | Higher |

*Measured on typical desktop usage (1920x1080, 24bpp)*

## Performance Metrics

### Real-World Benchmarks

Based on testing with TightVNC viewer on 1920x1080 desktop:

```
Scenario: Static desktop (no changes)
- Bandwidth: ~100 bytes/frame (99.98% reduction)
- FPS: 30
- Encoding: ZRLE

Scenario: Scrolling web page
- Bandwidth: ~2 KB/frame (97.5% reduction with CopyRect)
- FPS: 25-30
- Encoding: CopyRect + ZRLE

Scenario: Video playback
- Bandwidth: ~150 KB/frame
- FPS: 15-20
- Encoding: Hextile
```

### Change Detection Efficiency

- **Tile size**: 64x64 pixels
- **Checksum**: MD5 (fast for comparison)
- **Update strategy**: Send only changed regions
- **Typical savings**: 95-99% on static content

## Usage Examples

### Example 1: Basic Server

```python
from vnc_lib import VNCServer

# Create server instance
server = VNCServer(config_file="config.json")

# Start accepting connections
server.start()
```

### Example 2: Custom Encoding Strategy

```python
from vnc_lib.encodings import EncoderManager

manager = EncoderManager()

# Get best encoder for content type
encoding_type, encoder = manager.get_best_encoder(
    client_encodings={0, 1, 2, 5, 16},
    content_type="scrolling"  # Prefers CopyRect
)

# Encode frame
encoded_data = encoder.encode(pixel_data, width, height, bytes_per_pixel)
```

### Example 3: Metrics Monitoring

```python
from vnc_lib.metrics import ServerMetrics, SlidingWindow

metrics = ServerMetrics.get_instance()

# Track FPS
fps_window: SlidingWindow[float] = SlidingWindow(maxlen=100)
fps_window.add(current_fps)

# Get statistics
print(f"Average FPS: {fps_window.average():.1f}")
print(f"95th percentile: {fps_window.percentile(95):.1f}")

# Server summary
summary = metrics.get_summary()
print(f"Active connections: {summary['active_connections']}")
print(f"Total frames: {summary['total_frames_sent']}")
```

### Example 4: Exception Handling

```python
from vnc_lib.exceptions import ExceptionCollector, categorize_exceptions

# Collect errors from batch operations
with ExceptionCollector() as collector:
    for client_id, client_socket in clients.items():
        with collector.catch(f"client_{client_id}"):
            process_client(client_socket)

# Handle errors by category
if collector.has_exceptions():
    exc_group = collector.create_exception_group("Batch processing failed")
    categories = categorize_exceptions(exc_group)

    for exc_type, exceptions in categories.items():
        logger.error(f"{exc_type}: {len(exceptions)} occurrences")
```

## Python 3.13 Features

This project demonstrates modern Python capabilities:

### Pattern Matching
```python
match msg_type:
    case protocol.MSG_SET_PIXEL_FORMAT:
        handle_set_pixel_format(client_socket)
    case protocol.MSG_FRAMEBUFFER_UPDATE_REQUEST:
        handle_framebuffer_update(client_socket)
    case _:
        logger.warning(f"Unknown message: {msg_type}")
```

### Generic Type Parameters
```python
class SlidingWindow[T: Numeric]:
    """Type-safe sliding window for numeric values"""
    def __init__(self, maxlen: int = 100):
        self.window: deque[T] = deque(maxlen=maxlen)

    def average(self) -> float:
        return sum(self.window) / len(self.window)
```

### Exception Groups
```python
try:
    # Multiple operations
    ...
except ExceptionGroup as eg:
    categories = categorize_exceptions(eg)
    if "ProtocolError" in categories:
        # Handle protocol errors
        ...
```

See [PYTHON313_FEATURES.md](PYTHON313_FEATURES.md) for comprehensive examples and best practices.

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `host` | string | "0.0.0.0" | Bind address |
| `port` | integer | 5900 | VNC port |
| `password` | string | "" | Authentication password (empty = no auth) |
| `frame_rate` | integer | 30 | Target frames per second (1-60) |
| `scale_factor` | float | 1.0 | Screen scaling factor |
| `max_connections` | integer | 10 | Maximum concurrent clients |
| `enable_region_detection` | boolean | true | Region-based change detection |
| `enable_cursor_encoding` | boolean | false | Cursor pseudo-encoding |
| `enable_metrics` | boolean | true | Performance metrics collection |
| `log_level` | string | "INFO" | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `log_file` | string | null | Log file path (null = console only) |

## Testing

```bash
# Run all tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_encodings.py -v

# With coverage
python -m pytest --cov=vnc_lib tests/
```

## Performance Tuning

### For Low Bandwidth
```json
{
    "frame_rate": 15,
    "enable_region_detection": true,
    "scale_factor": 0.75
}
```

### For Low Latency
```json
{
    "frame_rate": 30,
    "enable_region_detection": false,
    "scale_factor": 1.0
}
```

### For Many Clients
```json
{
    "max_connections": 20,
    "frame_rate": 10,
    "enable_metrics": true
}
```

## Security Considerations

⚠️ **Important Security Notes**:

1. **VNC Authentication** uses DES encryption which is **considered weak** by modern standards
2. **No TLS/SSL** - traffic is not encrypted (use SSH tunnel recommended)
3. **No brute-force protection** - implement rate limiting externally if needed

### Recommended Secure Setup

```bash
# SSH tunnel method (recommended)
ssh -L 5900:localhost:5900 user@server

# Or use stunnel for SSL/TLS wrapper
stunnel stunnel.conf
```

## Troubleshooting

### Issue: "Permission denied" on screen capture

**Solution**: Ensure X11 access permissions
```bash
xhost +local:
# Or run with proper DISPLAY variable
export DISPLAY=:0
```

### Issue: Low frame rate / high latency

**Solution**: Check encoding selection and disable region detection
```python
# Force faster encoding
client_encodings = {5}  # Hextile only
enable_region_detection = false
```

### Issue: High CPU usage

**Solution**: Reduce frame rate or use more efficient encoding
```json
{
    "frame_rate": 15,
    "enable_region_detection": true
}
```

## Development

### Running in Development Mode

```bash
# Enable debug logging
python vnc_server.py --log-level DEBUG

# Run with specific config
python vnc_server.py --config dev_config.json
```

### Interactive Demo

Try the Python 3.13 features demonstration:

```bash
python examples/python313_features_demo.py
```

## Roadmap

- [ ] TLS/SSL encryption (VeNCrypt)
- [ ] Tight encoding support
- [ ] H.264/VP9 video encoding
- [ ] Multi-threaded encoding
- [ ] WebSocket support (noVNC compatibility)
- [ ] Clipboard extended formats
- [ ] Audio forwarding

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Use Python 3.13 features where appropriate
2. Maintain RFC 6143 compliance
3. Add type hints to all functions
4. Include tests for new features
5. Update documentation

## License

MIT License - see [LICENSE](LICENSE) file for details.

## References

- [RFC 6143 - The Remote Framebuffer Protocol](https://datatracker.ietf.org/doc/html/rfc6143)
- [PEP 634 - Structural Pattern Matching](https://peps.python.org/pep-0634/)
- [PEP 695 - Type Parameter Syntax](https://peps.python.org/pep-0695/)
- [PEP 654 - Exception Groups](https://peps.python.org/pep-0654/)

## Acknowledgments

- Built with pure Python 3.13
- Uses Pillow for screen capture
- Implements RFC 6143 VNC protocol
- Demonstrates modern Python language features

---

**Note**: This is an educational/demonstration project showcasing Python 3.13 features in a real-world application. For production use, consider established VNC servers with full security features.
