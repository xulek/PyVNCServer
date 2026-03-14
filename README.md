<p align="center">
  <h1 align="center">PyVNCServer</h1>
  <p align="center">
    <strong>A feature-rich RFB/VNC server written in pure Python</strong>
  </p>
  <p align="center">
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.13+"></a>&nbsp;
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="MIT License"></a>&nbsp;
    <a href="https://github.com/xulek/PyVNCServer/actions"><img src="https://img.shields.io/badge/CI-passing-brightgreen?style=for-the-badge&logo=github-actions&logoColor=white" alt="CI"></a>&nbsp;
    <a href="#"><img src="https://img.shields.io/badge/version-3.2.0-blue?style=for-the-badge" alt="Version 3.2.0"></a>
  </p>
</p>

---

PyVNCServer is an [RFC 6143](https://datatracker.ietf.org/doc/html/rfc6143)-compliant VNC server that captures your desktop and streams it to any VNC viewer. It supports multiple encodings, adaptive compression, WebSocket transport for browser access via [noVNC](https://novnc.com/), and network-aware performance tuning -- all from a single Python package.

## Highlights

<table>
<tr>
<td width="50%">

**Protocol & Security**
- RFB 3.3 / 3.7 / 3.8 negotiation
- No-auth, VNC Authentication, TightVNC Security (type 16)
- Read-only password support
- Multi-client with configurable input arbitration

</td>
<td width="50%">

**Encodings**
- **Core:** Raw, RRE, Hextile, Zlib, CopyRect
- **Advanced:** ZRLE, Tight, JPEG
- **Experimental:** H.264 (requires PyAV)
- Adaptive per-rectangle encoder selection

</td>
</tr>
<tr>
<td>

**Performance**
- LAN-tuned adaptive encoding with auto thresholds
- Parallel region encoding with thread pool
- Tile-grid incremental change detection
- Request coalescing to reduce lag
- Runtime capture backend failover

</td>
<td>

**Platform & Transport**
- Screen capture: DXGI (dxcam), MSS, PIL fallback
- Native cursor capture & RichCursor pseudo-encoding
- Desktop resize (ExtendedDesktopSize)
- WebSocket on the same port -- no websockify needed
- Bundled noVNC web client

</td>
</tr>
</table>

## Quick Start

### 1. Install

```bash
git clone https://github.com/xulek/PyVNCServer.git
cd PyVNCServer
pip install -e .[dev]
```

<details>
<summary><b>Alternative: run without installing</b></summary>

```powershell
# PowerShell
$env:PYTHONPATH = "src"
python -m pyvncserver --help
```

```bash
# Bash
PYTHONPATH=src python -m pyvncserver --help
```

</details>

<details>
<summary><b>Optional: Windows DXGI capture backend</b></summary>

```bash
pip install -e .[windows-capture]
```

Provides hardware-accelerated screen capture via Desktop Duplication API. Falls back to MSS automatically if unavailable.

</details>

### 2. Configure

Edit `config/pyvncserver.toml` -- set at least `password` for authentication:

```toml
[server]
host = "0.0.0.0"
port = 5900
password = "secret"
```

### 3. Run

```bash
pyvncserver serve --config config/pyvncserver.toml
```

### 4. Connect

```bash
vncviewer localhost:5900
```

## Browser Access (WebSocket + noVNC)

PyVNCServer serves WebSocket and standard VNC on the **same port** -- no external proxy required.

**1.** Enable WebSocket in `config/pyvncserver.toml`:

```toml
[features]
enable_websocket = true

[websocket]
allowed_origins = ["http://localhost:8000"]
```

**2.** Start the VNC server, then serve the web client:

```bash
pyvncserver serve --config config/pyvncserver.toml
python -m http.server 8000                              # separate terminal
```

**3.** Open [`http://localhost:8000/web/vnc_client.html`](http://localhost:8000/web/vnc_client.html) in your browser.

> For production `wss://` transport, terminate TLS at a reverse proxy (e.g. Nginx). See [`WEBSOCKET.md`](WEBSOCKET.md) for details and an Nginx config example.

## Configuration Reference

All settings live in [`config/pyvncserver.toml`](config/pyvncserver.toml), organized into sections:

<details>
<summary><b><code>[server]</code> -- Core server settings</b></summary>

| Key | Type | Default | Description |
|---|---|---|---|
| `host` | `str` | `"0.0.0.0"` | Bind address |
| `port` | `int` | `5900` | VNC port |
| `password` | `str` | `""` | VNC password (empty = no auth) |
| `read_only_password` | `str` | `""` | Optional view-only password |
| `frame_rate` | `int` | `30` | Target FPS (WAN profile) |
| `lan_frame_rate` | `int` | `90` | Target FPS (LAN profile) |
| `network_profile_override` | `str\|null` | `"lan"` | Force `localhost`, `lan`, `wan`, or auto-detect (`""`) |
| `scale_factor` | `float` | `1.0` | Capture scaling factor |
| `capture_backend` | `str` | `"auto"` | `auto`, `dxcam`, `mss`, or `pil` |
| `capture_probe_frames` | `int` | `0` | Startup capture latency probe samples |
| `capture_probe_warn_ms` | `float` | `40.0` | Probe warning threshold (ms) |
| `max_connections` | `int` | `10` | Maximum simultaneous clients |
| `client_socket_timeout` | `float` | `60.0` | Per-client read timeout (seconds) |
| `input_control_policy` | `str` | `"single-controller"` | `single-controller` or `shared` |

</details>

<details>
<summary><b><code>[features]</code> -- Feature toggles</b></summary>

| Key | Default | Description |
|---|---|---|
| `enable_region_detection` | `true` | Incremental update optimization |
| `enable_metrics` | `true` | Internal metrics collection |
| `enable_request_coalescing` | `true` | Drop stale framebuffer requests |
| `enable_lan_adaptive_encoding` | `true` | LAN-tuned encoder parameter adaptation |
| `enable_websocket` | `false` | WebSocket transport support |
| `enable_tight_security` | `true` | TightVNC security type 16 |
| `enable_cursor_encoding` | `false` | RichCursor & PointerPos pseudo-encodings |
| `enable_copyrect_encoding` | `true` | CopyRect encoding |
| `enable_zrle_encoding` | `true` | ZRLE encoding |
| `enable_tight_encoding` | `true` | Tight encoding |
| `enable_jpeg_encoding` | `true` | JPEG encoding |
| `enable_h264_encoding` | `false` | H.264 encoding (requires PyAV) |
| `enable_parallel_encoding` | `true` | Multi-threaded region encoding |

</details>

<details>
<summary><b><code>[lan]</code> -- LAN adaptive encoding thresholds</b></summary>

| Key | Default | Description |
|---|---|---|
| `raw_area_threshold` | `0.10` | Area ratio below which Raw is preferred |
| `raw_max_pixels` | `65536` | Max rectangle size eligible for Raw |
| `zlib_area_threshold` | `0.08` | Area ratio above which Zlib is preferred |
| `zlib_min_pixels` | `8192` | Min rectangle size for Zlib |
| `zlib_compression_level` | `2` | Zlib compression level |
| `zlib_disable_if_request_gap_ms` | `1500` | Disable Zlib if client request gap exceeds this |
| `jpeg_area_threshold` | `0.20` | Area ratio above which JPEG is preferred |
| `jpeg_min_pixels` | `16384` | Min rectangle size for JPEG |
| `jpeg_quality_initial` | `84` | Starting JPEG quality |
| `jpeg_quality_min` / `max` | `70` / `95` | Adaptive JPEG quality bounds |
| `zrle_compression_level` | `3` | ZRLE compression level |

</details>

<details>
<summary><b><code>[websocket]</code> -- WebSocket transport settings</b></summary>

| Key | Default | Description |
|---|---|---|
| `allowed_origins` | `[]` | Allowed browser `Origin` values |
| `detect_timeout` | `0.5` | WebSocket handshake detection timeout |
| `max_handshake_bytes` | `65536` | Max HTTP upgrade header size |
| `max_payload_bytes` | `8388608` | Max inbound frame payload (8 MB) |
| `max_buffer_bytes` | `16777216` | Max receive buffer (16 MB) |

</details>

<details>
<summary><b><code>[limits]</code> and <code>[logging]</code></b></summary>

| Key | Default | Description |
|---|---|---|
| `max_set_encodings` | `1024` | Max SetEncodings items from client |
| `max_client_cut_text` | `16777216` | Max ClientCutText payload (16 MB) |
| `encoding_threads` | `0` | Worker threads for parallel encoding (0 = auto) |
| `log_level` | `"INFO"` | Python logging level |
| `log_file` | `""` | Optional log file path |

</details>

## CLI Usage

```bash
# Start with default config
pyvncserver serve

# Start with custom config and debug logging
pyvncserver serve --config config/pyvncserver.toml --log-level DEBUG

# Run as Python module (no install required, set PYTHONPATH=src)
python -m pyvncserver serve --config config/pyvncserver.toml
```

**Programmatic startup:**

```python
from pyvncserver import VNCServer

server = VNCServer(config_file="config/pyvncserver.toml")
server.start()
```

## Project Structure

```
PyVNCServer/
├── src/
│   ├── pyvncserver/            # Packaged application (new code goes here)
│   │   ├── cli.py              # CLI entrypoint
│   │   ├── config.py           # TOML config loader
│   │   ├── app/server.py       # Main VNCServerV3 class
│   │   ├── rfb/                # Protocol layer (auth, encodings, messages)
│   │   ├── platform/           # OS integration (capture, cursor, input)
│   │   ├── runtime/            # Connection pool, network profiles, threading
│   │   ├── features/           # Clipboard, session recording, WebSocket
│   │   └── observability/      # Logging, metrics, Prometheus, profiling
│   └── vnc_lib/                # Internal implementation library
│       ├── protocol.py         # RFB protocol negotiation
│       ├── encodings.py        # Encoder implementations + EncoderManager
│       ├── screen_capture.py   # Screen capture with backend selection
│       ├── auth.py             # VNC/Tight authentication
│       └── ...                 # 20+ modules
├── config/pyvncserver.toml     # Default server configuration
├── tests/                      # 320+ pytest tests
├── benchmarks/                 # Performance measurement scripts
├── examples/                   # Demo scripts
├── web/                        # noVNC browser client
└── docs/                       # Architecture & protocol docs
```

## Testing

```bash
# Full test suite
python -m pytest tests/ -v --tb=short

# Single test file
python -m pytest tests/test_encodings.py -v

# Single test
python -m pytest tests/test_vnc_server.py::TestClassName::test_method -v

# With coverage report
python -m pytest tests/ --cov=pyvncserver --cov=vnc_lib --cov-report=term-missing
```

## Benchmarks

```bash
python benchmarks/benchmark_encoders.py              # Encoder throughput (Raw/Zlib/Tight/ZRLE)
python benchmarks/benchmark_screen_capture.py         # Capture backend performance
python benchmarks/benchmark_screen_capture_methods.py 20  # Comparative backend benchmark
python benchmarks/benchmark_lan_latency.py 127.0.0.1 5900 20  # Network latency
```

To measure real capture latency at startup, set in config:

```toml
[server]
capture_probe_frames = 12
capture_probe_warn_ms = 40.0
```

## Security

> **Important:** VNC authentication uses DES-based challenge-response and provides only basic protection. Traffic is **not encrypted** by default.

For production deployments:
- Set a strong password in `config/pyvncserver.toml`
- Run behind SSH tunneling, a VPN, or a TLS-terminating reverse proxy
- Restrict `allowed_origins` for WebSocket access
- Bind to `127.0.0.1` if only local access is needed
- Do not expose directly to untrusted networks

## Troubleshooting

<details>
<summary><b>No screen capture or input in Linux headless environments</b></summary>

`pyautogui` and capture backends require a graphical session. For X11:

```bash
export DISPLAY=:0
```

For headless servers, run Xvfb and ensure the process has display access.

</details>

<details>
<summary><b>Import or runtime issues with <code>mss</code> / <code>Pillow</code></b></summary>

Reinstall dependencies:

```bash
pip install -r requirements.txt
```

</details>

<details>
<summary><b>Browser connects but shows nothing</b></summary>

- Verify `enable_websocket = true` in `[features]`
- Verify `allowed_origins` contains the origin serving the page (e.g., `http://localhost:8000`)
- Serve the web client over HTTP, not `file://` (ES modules require it)
- Check that the VNC port is not blocked by a firewall

</details>

## Dependencies

| Package | Purpose |
|---|---|
| [mss](https://github.com/BoboTiG/python-mss) | Fast cross-platform screen capture |
| [Pillow](https://python-pillow.org/) | Image processing and PIL capture fallback |
| [pyautogui](https://github.com/asweigart/pyautogui) | Keyboard and mouse input simulation |
| [pycryptodome](https://www.pycryptodome.org/) | DES encryption for VNC authentication |
| [numpy](https://numpy.org/) | Fast pixel data operations |
| [dxcam](https://github.com/ra1nty/DXcam) | *(optional)* Windows DXGI Desktop Duplication capture |
| [PyAV](https://github.com/PyAV-Org/PyAV) | *(optional)* H.264 encoding via FFmpeg |

## License

This project is licensed under the [MIT License](LICENSE).

---

<p align="center">
  <sub>Built with Python 3.13+ &bull; RFC 6143 compliant &bull; <a href="https://github.com/xulek/PyVNCServer">github.com/xulek/PyVNCServer</a></sub>
</p>
