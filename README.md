# PyVNCServer

A modern, RFC 6143 compliant VNC server implementation in pure Python 3.13, showcasing advanced language features and efficient remote desktop protocol handling.

[![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Overview

PyVNCServer is a full-featured VNC (Virtual Network Computing) server written entirely in Python 3.13. It demonstrates modern Python capabilities while providing a complete, RFC-compliant remote desktop solution.

**Key Highlights:**
- 🚀 Pure Python implementation (no native dependencies)
- 📡 Full RFC 6143 protocol compliance
- 🎯 Python 3.13 features (pattern matching, type parameters, exception groups)
- ⚡ High performance with smart encoding and change detection
- 📊 Built-in monitoring and metrics

## Features

### Core VNC Protocol
- **Protocol Versions**: RFB 3.3, 3.7, 3.8
- **Authentication**: None, VNC Authentication (DES)
- **Encodings**: Raw, CopyRect, RRE, Hextile, ZRLE
- **Pixel Formats**: 8, 16, 32 bits per pixel
- **Input Events**: Keyboard and pointer (mouse)
- **Clipboard**: Bidirectional clipboard synchronization

### Advanced Features
- 🚀 **CopyRect Encoding** - 10-100x bandwidth reduction for scrolling
- 📐 **Desktop Resize** - Dynamic screen resolution changes
- 📊 **Performance Metrics** - Real-time FPS, bandwidth, and compression stats
- 🔄 **Change Detection** - Region-based updates for optimal performance
- 📹 **Session Recording** - Record and playback VNC sessions
- 📈 **Prometheus Metrics** - HTTP endpoint for monitoring
- 📝 **Structured Logging** - Context-aware logging with JSON support
- ⚡ **Performance Monitoring** - Real-time profiling and analysis

### Python 3.13 Features
- Pattern matching for message handling (PEP 634)
- Generic type parameters (PEP 695)
- Exception groups for error handling (PEP 654)
- Full type hints with strict validation

## Requirements

- **Python 3.13+**
- **Linux** with X11 or Xvfb
- Dependencies: `Pillow`, `python-xlib`

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/xulek/PyVNCServer.git
cd PyVNCServer

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

```bash
# Start server (default: port 5900, no password)
python vnc_server.py

# Connect with any VNC client
vncviewer localhost:5900
```

### Configuration

Edit `config.json` for custom settings:

```json
{
    "host": "0.0.0.0",
    "port": 5900,
    "password": "your_password",
    "frame_rate": 30,
    "max_connections": 10,
    "enable_metrics": true,
    "log_level": "INFO"
}
```

Then run:
```bash
python vnc_server.py
```

## Usage Examples

### Basic Server

```python
from vnc_lib import VNCServer

server = VNCServer(config_file="config.json")
server.start()
```

### Session Recording

```python
from vnc_lib import SessionRecorder

with SessionRecorder('session.vnc.gz') as recorder:
    recorder.record_handshake(b'RFB 003.008\n')
    recorder.record_key_event(key=65, down=True)
    # Session automatically saved on exit
```

### Prometheus Metrics

```python
from vnc_lib import PrometheusExporter

with PrometheusExporter(port=9100) as exporter:
    collector = exporter.collector
    collector.record_connection(success=True)
    collector.record_bytes_sent(1024, encoding='zrle')
    # Metrics available at http://localhost:9100/metrics
```

### Structured Logging

```python
from vnc_lib import get_logger, LogContext

logger = get_logger('vnc_server')

with LogContext(client_ip='192.168.1.100'):
    logger.info("Client connected")
    # All logs include client_ip context
```

## Architecture

```
vnc_lib/
├── protocol.py             # RFB protocol implementation
├── encodings.py            # Encoding implementations
├── screen_capture.py       # Screen grabbing
├── input_handler.py        # Keyboard/mouse input
├── session_recorder.py     # Session recording
├── clipboard.py            # Clipboard sync
├── prometheus_exporter.py  # Metrics export
├── structured_logging.py   # Enhanced logging
├── performance_monitor.py  # Performance profiling
└── connection_pool.py      # Connection management
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | "0.0.0.0" | Bind address |
| `port` | 5900 | VNC port |
| `password` | "" | Authentication password (empty = no auth) |
| `frame_rate` | 30 | Target FPS (1-60) |
| `max_connections` | 10 | Maximum concurrent clients |
| `enable_region_detection` | true | Region-based change detection |
| `enable_metrics` | true | Performance metrics collection |
| `log_level` | "INFO" | Logging level |

## Performance

### Encoding Performance

| Encoding | Use Case | Bandwidth | CPU |
|----------|----------|-----------|-----|
| **Raw** | Fallback | Highest | Lowest |
| **CopyRect** | Scrolling | 1-2% of Raw | Minimal |
| **RRE** | Static content | 20-40% of Raw | Low |
| **Hextile** | Dynamic content | 30-60% of Raw | Medium |
| **ZRLE** | Mixed content | 10-30% of Raw | Higher |

### Real-World Performance

- **Static desktop**: ~100 bytes/frame (99.98% reduction)
- **Scrolling**: ~2 KB/frame with CopyRect
- **Video playback**: ~150 KB/frame
- **Change detection**: 95-99% bandwidth savings on static content

## Testing

```bash
# Run all tests
python -m pytest tests/

# With coverage
python -m pytest --cov=vnc_lib tests/
```

## Security Considerations

⚠️ **Important**:
- VNC Authentication uses DES (weak by modern standards)
- No TLS/SSL encryption - use SSH tunnel for production
- No built-in brute-force protection

### Recommended Secure Setup

```bash
# SSH tunnel (recommended)
ssh -L 5900:localhost:5900 user@server

# Then connect to localhost:5900
vncviewer localhost:5900
```

## Troubleshooting

### Permission denied on screen capture
```bash
xhost +local:
export DISPLAY=:0
```

### Low frame rate / high latency
- Check encoding selection
- Disable region detection for faster updates
- Reduce frame_rate in config

### High CPU usage
- Reduce frame_rate
- Enable region_detection
- Use more efficient encoding (ZRLE)

## Development

```bash
# Debug mode
python vnc_server.py --log-level DEBUG

# Run demo
python examples/advanced_features_demo.py
```

## Roadmap

- [ ] TLS/SSL encryption (VeNCrypt)
- [ ] Tight encoding support
- [ ] H.264/VP9 video encoding
- [ ] WebSocket support (noVNC compatibility)
- [ ] Multi-threaded encoding

## Contributing

Contributions welcome! Please:
1. Use Python 3.13 features where appropriate
2. Maintain RFC 6143 compliance
3. Add type hints to all functions
4. Include tests for new features

## License

MIT License - see [LICENSE](LICENSE) file for details.

## References

- [RFC 6143 - The Remote Framebuffer Protocol](https://datatracker.ietf.org/doc/html/rfc6143)
- [PEP 634 - Structural Pattern Matching](https://peps.python.org/pep-0634/)
- [PEP 695 - Type Parameter Syntax](https://peps.python.org/pep-0695/)
- [PEP 654 - Exception Groups](https://peps.python.org/pep-0654/)

---

**Note**: This is an educational/demonstration project showcasing Python 3.13 features. For production use, consider established VNC servers with full security features.
