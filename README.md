# PyVNCServer

[![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

PyVNCServer is an RFB (VNC) server implementation in Python. The repository combines:
- a packaged runtime in `src/pyvncserver/`
- a legacy compatibility entrypoint in `vnc_server.py`
- reusable protocol/encoding modules
- browser client assets (`web/`)
- demos, tests, and benchmarks

## Scope

The preferred entrypoint is now the packaged CLI in `pyvncserver`. The legacy `vnc_server.py`
wrapper remains available for compatibility.

The `src/pyvncserver/` package is the new source of truth for runtime structure.
The legacy `vnc_lib/` package is retained during the migration and still backs many internals.

## Implemented Capabilities

### Server Runtime (`vnc_server.py`)
- RFB protocol negotiation for versions 3.3, 3.7, and 3.8
- Security: `None` and `VNC Authentication`
- Encodings: Raw, RRE, Hextile, Zlib
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
python -m pip install -e .[dev]
```

## Quick Start

1. Review `config.json` and set at least `host`, `port`, and `password`.
   The shipped default is currently tuned for LAN quality/performance
   (`network_profile_override` is set to `"lan"`).
2. Start the server:

```bash
pyvncserver serve --config config/pyvncserver.toml
```

3. Connect with a VNC client (example):

```bash
vncviewer localhost:5900
```

If you want automatic profile detection (`localhost`/`lan`/`wan`) instead of
forced LAN mode, set `"network_profile_override": null` in `config.json`.

## Browser Access (WebSocket + noVNC)

1. Set `"enable_websocket": true` in `config.json`.
2. Set `"websocket_allowed_origins"` to the browser origins that may connect.
   Example: `["http://localhost:8000"]`.
3. Start the VNC server:

```bash
python vnc_server.py
```

4. Serve web assets from project root:

```bash
python -m http.server 8000
```

5. Open:

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
| `enable_lan_adaptive_encoding` | `bool` | LAN tuning for encoder parameters and transport behavior; encoding order still follows client preference |
| `enable_request_coalescing` | `bool` | Drops stale framebuffer requests to reduce lag |
| `lan_raw_area_threshold` | `float` | Area ratio below which Raw is preferred on LAN |
| `lan_raw_max_pixels` | `int` | Maximum rectangle size (pixels) eligible for Raw on LAN |
| `lan_prefer_zlib` | `bool` | Legacy tuning flag; no longer overrides client encoding order |
| `lan_zlib_area_threshold` | `float` | Area ratio above which Zlib is preferred on LAN |
| `lan_zlib_min_pixels` | `int` | Minimum rectangle size for Zlib consideration on LAN |
| `lan_zlib_compression_level` | `int` | Zlib compression level used in LAN mode |
| `lan_zlib_warmup_requests` | `int` | Initial framebuffer requests served without Zlib |
| `lan_zlib_disable_if_request_gap_ms` | `int` | Auto-disable Zlib for client if request gaps are too large |
| `lan_jpeg_area_threshold` | `float` | Area ratio above which JPEG is preferred on LAN |
| `lan_jpeg_min_pixels` | `int` | Minimum rectangle size for JPEG consideration |
| `lan_jpeg_quality_initial` | `int` | Initial JPEG quality in adaptive LAN mode |
| `lan_jpeg_quality_min` | `int` | Lower bound for adaptive JPEG quality |
| `lan_jpeg_quality_max` | `int` | Upper bound for adaptive JPEG quality |
| `lan_zrle_compression_level` | `int` | Reserved legacy setting; ZRLE is not negotiated by default |
| `network_profile_override` | `null \| "localhost" \| "lan" \| "wan"` | Forces profile, bypasses auto-detection |
| `scale_factor` | `float` | Capture scaling factor |
| `max_connections` | `int` | Max simultaneous clients |
| `client_socket_timeout` | `float` | Per-client read timeout in seconds |
| `enable_region_detection` | `bool` | Incremental update optimization |
| `enable_cursor_encoding` | `bool` | Reserved legacy flag; runtime currently disables cursor pseudo-encoding |
| `enable_metrics` | `bool` | Internal metrics collection |
| `enable_tight_encoding` | `bool` | Tight encoder availability |
| `tight_disable_for_ultravnc` | `bool` | Legacy hard-disable for Tight on UltraVNC-like clients; default `false` |
| `ultravnc_tight_warmup_requests` | `int` | Delay Tight for UltraVNC-like clients for initial framebuffer requests |
| `ultravnc_tight_warmup_seconds` | `float` | Delay Tight for UltraVNC-like clients for initial connection seconds |
| `enable_jpeg_encoding` | `bool` | JPEG encoder availability |
| `enable_h264_encoding` | `bool` | H.264 encoder availability (requires optional deps) |
| `enable_parallel_encoding` | `bool` | Parallel region encoding |
| `encoding_threads` | `int \| null` | Worker count for parallel encoding |
| `enable_websocket` | `bool` | WebSocket transport support |
| `websocket_allowed_origins` | `list[str]` | Allowed browser `Origin` values for WebSocket upgrade |
| `websocket_detect_timeout` | `float` | Timeout for WebSocket request detection |
| `websocket_max_handshake_bytes` | `int` | Max HTTP upgrade header size |
| `websocket_max_payload_bytes` | `int` | Max inbound WebSocket frame payload size |
| `websocket_max_buffer_bytes` | `int` | Max adapter receive buffer size |
| `input_control_policy` | `"single-controller" \| "shared"` | Multi-client input arbitration policy |
| `max_set_encodings` | `int` | Max SetEncodings items accepted from client |
| `max_client_cut_text` | `int` | Max ClientCutText payload accepted from client |
| `log_level` | `str` | Python logging level |
| `log_file` | `str \| null` | Optional file logging target |

## CLI And Programmatic Startup

CLI supports config and log level overrides:

```bash
python vnc_server.py serve --config config/pyvncserver.toml --log-level DEBUG
```

Programmatic startup is also available:

```python
from pyvncserver import VNCServer

server = VNCServer(config_file="config/pyvncserver.toml")
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
config/              Preferred runtime configuration files
docs/                Project and architecture documentation
examples/            Runnable demo scripts
src/pyvncserver/     Packaged application and library code
tests/               Unit tests
vnc_lib/             Legacy modules retained during migration
web/                 Browser client assets and noVNC integration
vnc_server.py        Legacy compatibility entrypoint
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
