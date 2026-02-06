# PyVNCServer

[![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

PyVNCServer is an RFB (VNC) server implementation in Python. The repository combines:
- a runnable server (`vnc_server.py`)
- a reusable protocol/encoding library (`vnc_lib/`)
- browser client assets (`web/`)
- demos, tests, and benchmarks

## Scope

`vnc_server.py` is the main entrypoint and source of truth for runtime behavior.

The `vnc_lib/` package contains additional modules (for example session recording, clipboard helpers, Prometheus exporter, structured logging, and performance tooling). These modules are available for integration, but not all of them are wired into the default server loop.

## Implemented Capabilities

### Server Runtime (`vnc_server.py`)
- RFB protocol negotiation for versions 3.3, 3.7, and 3.8
- Security: `None` and `VNC Authentication`
- Encodings: Raw, CopyRect, RRE, Hextile, ZRLE
- Optional encoders: Tight, JPEG, H.264 (H.264 requires extra dependencies)
- Incremental updates with adaptive change detection
- Desktop size update support via pseudo-encoding
- Network profile tuning (`localhost`, `lan`, `wan`) for frame rate and socket behavior
- Optional WebSocket transport support for browser clients
- Connection pool, health checks, and per-connection metrics
- Optional parallel region encoding

### Library Modules (`vnc_lib/`)
- Session recording and playback (`session_recorder.py`)
- Clipboard message parsing and synchronization helpers (`clipboard.py`)
- Prometheus metrics exporter (`prometheus_exporter.py`)
- Structured logging helpers (`structured_logging.py`)
- Performance monitoring utilities (`metrics.py`, `performance_monitor.py`)

## Requirements

- Python 3.13+ (CI is configured for Python 3.13)
- GUI-capable environment for screen capture and input simulation
- Dependencies from `requirements.txt`:
  - `mss` (preferred capture backend)
  - `Pillow`
  - `pyautogui`
  - `pycryptodome`
  - `numpy`
- Optional for H.264:
  - `av` (PyAV) and FFmpeg libraries

## Installation

```bash
git clone https://github.com/xulek/PyVNCServer.git
cd PyVNCServer
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Quick Start

1. Review `config.json` and set at least `host`, `port`, and `password`.
2. Start the server:

```bash
python vnc_server.py
```

3. Connect with a VNC client (example):

```bash
vncviewer localhost:5900
```

## Browser Access (WebSocket + noVNC)

1. Set `"enable_websocket": true` in `config.json`.
2. Start the VNC server:

```bash
python vnc_server.py
```

3. Serve web assets from project root:

```bash
python -m http.server 8000
```

4. Open:

`http://localhost:8000/web/vnc_client.html`

Additional details are documented in `WEBSOCKET.md` and `web/README_NOVNC.md`.

## Configuration

The repository ships with a ready-to-edit `config.json`. Key fields:

| Key | Type | Description |
|---|---|---|
| `host` | `str` | Bind address |
| `port` | `int` | VNC port |
| `password` | `str` | Empty string disables auth |
| `frame_rate` | `int` | Target FPS for WAN profile |
| `lan_frame_rate` | `int` | Target FPS for LAN profile |
| `network_profile_override` | `null \| "localhost" \| "lan" \| "wan"` | Forces profile, bypasses auto-detection |
| `scale_factor` | `float` | Capture scaling factor |
| `max_connections` | `int` | Max simultaneous clients |
| `enable_region_detection` | `bool` | Incremental update optimization |
| `enable_cursor_encoding` | `bool` | Cursor pseudo-encoding support |
| `enable_metrics` | `bool` | Internal metrics collection |
| `enable_tight_encoding` | `bool` | Tight encoder availability |
| `tight_disable_for_ultravnc` | `bool` | Compatibility workaround for UltraVNC-like clients |
| `enable_jpeg_encoding` | `bool` | JPEG encoder availability |
| `enable_h264_encoding` | `bool` | H.264 encoder availability (requires optional deps) |
| `enable_parallel_encoding` | `bool` | Parallel region encoding |
| `encoding_threads` | `int \| null` | Worker count for parallel encoding |
| `enable_websocket` | `bool` | WebSocket transport support |
| `log_level` | `str` | Python logging level |
| `log_file` | `str \| null` | Optional file logging target |

## Programmatic Startup

`vnc_server.py` does not expose CLI flags for config selection. For a custom config path, start it programmatically:

```python
from vnc_server import VNCServerV3

server = VNCServerV3(config_file="config.production.json")
server.start()
```

## Examples

```bash
python examples/advanced_features_demo.py
python examples/python313_features_demo.py
```

## Benchmarks

```bash
python benchmarks/benchmark_lan_latency.py 127.0.0.1 5900 20
python benchmarks/benchmark_screen_capture.py
python benchmarks/benchmark_screen_capture_methods.py 20
```

## Testing

```bash
python -m pytest tests/ -v --tb=short
python -m pytest tests/ -v --cov=vnc_lib --cov-report=term-missing
```

## Project Layout

```text
benchmarks/          Performance and latency scripts
examples/            Runnable demo scripts
tests/               Unit tests
vnc_lib/             Core protocol, encoding, and utility modules
web/                 Browser client assets and noVNC integration
vnc_server.py        Server entrypoint
config.json          Runtime configuration template
```

## Security Notes

- VNC authentication is DES-based challenge/response and should be treated as legacy protection.
- Traffic is not encrypted by default.
- For production, run behind SSH tunneling or TLS-terminating reverse proxy/VPN.
- Expose the server only on trusted networks.

## Troubleshooting

### No screen capture/input in Linux headless environments

`pyautogui` and capture backends require a graphical session. For X11:

```bash
export DISPLAY=:0
```

For headless servers, run an X server/Xvfb and ensure the process has display access.

### `mss` or `Pillow` import/runtime issues

Reinstall dependencies:

```bash
python -m pip install -r requirements.txt
```

## License

MIT. See `LICENSE`.
