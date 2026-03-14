# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PyVNCServer is an RFB (VNC) server written in Python 3.13+. It provides a packaged CLI (`pyvncserver`) and reusable protocol/encoding libraries. The server captures the host screen and streams it to VNC clients over the RFB protocol (RFC 6143), with optional WebSocket transport for browser clients.

## Build & Development Commands

```bash
# Install in editable mode with dev dependencies
python -m pip install -e .[dev]

# Run without installing (Windows PowerShell)
$env:PYTHONPATH="src"; python -m pyvncserver serve --config config/pyvncserver.toml

# Run without installing (bash)
PYTHONPATH=src python -m pyvncserver serve --config config/pyvncserver.toml

# Run all tests
python -m pytest tests/ -v --tb=short

# Run a single test file
python -m pytest tests/test_vnc_server.py -v --tb=short

# Run a single test function
python -m pytest tests/test_vnc_server.py::test_function_name -v

# Run tests with coverage
python -m pytest tests/ -v --cov=pyvncserver --cov=vnc_lib --cov-report=term-missing

# Quick syntax check
python -m py_compile src/pyvncserver/app/server.py src/pyvncserver/cli.py

# Lint (CI uses ruff)
ruff check src/pyvncserver src/vnc_lib --select=E,F,W,C,N

# Type check (CI uses mypy)
mypy src/pyvncserver src/vnc_lib --ignore-missing-imports --check-untyped-defs

# Run benchmarks
python benchmarks/benchmark_encoders.py
python benchmarks/benchmark_screen_capture.py
```

## Architecture

### Two-package layout under `src/`

- **`src/pyvncserver/`** — The packaged application. New code goes here.
  - `cli.py` / `__main__.py` — CLI entrypoint (`pyvncserver serve`)
  - `config.py` — TOML config loading, flattening, and normalization
  - `app/server.py` — Main server class (`VNCServerV3`), ~100KB monolith that handles socket accept, RFB handshake, per-client threads, encoding dispatch, and frame loop
  - `rfb/` — Protocol-layer re-exports (auth, encodings, exceptions, messages, pixel format)
  - `platform/` — OS integration re-exports (capture, cursor, desktop, input)
  - `runtime/` — Orchestration re-exports (connection pool, network profile, parallel encoder, throttling)
  - `features/` — Optional feature re-exports (clipboard, session recording, websocket)
  - `observability/` — Monitoring re-exports (logging, metrics, profiling, prometheus)

- **`src/vnc_lib/`** — Internal support library with the actual implementations. The `pyvncserver` subpackages mostly re-export from here.
  - `protocol.py` — RFB protocol negotiation (versions 3.3/3.7/3.8)
  - `encodings.py` — Raw, RRE, Hextile, Zlib, ZRLE, CopyRect encoders + `EncoderManager`
  - `tight_encoding.py` — Tight encoder (zlib-based with subrect optimization)
  - `jpeg_encoding.py` — JPEG encoder
  - `h264_encoding.py` — H.264 encoder (requires `av`/FFmpeg)
  - `screen_capture.py` — Screen capture with backend selection and DPI awareness
  - `capture_backends.py` — Backend abstraction (dxcam, mss, PIL fallback)
  - `auth.py` — VNC authentication (DES challenge-response) and TightVNC-style auth
  - `change_detector.py` — Tile-grid adaptive change detection for incremental updates
  - `cursor.py` — RichCursor/PointerPos pseudo-encoding, Win32 cursor capture
  - `input_handler.py` — Keyboard/mouse input via pyautogui
  - `websocket_wrapper.py` — WebSocket transport adapter
  - `server_utils.py` — Connection pool, health checker, network profile detection, throttling
  - `types.py` — Type definitions (`PixelFormat`, `Result[T, E]`, encoding constants)
  - `exceptions.py` — Exception hierarchy with `ExceptionGroup` support

### Key architectural patterns

- **Config flow**: TOML sections (`[server]`, `[features]`, `[lan]`, `[websocket]`, `[limits]`, `[logging]`) are flattened into a single dict with prefixed keys (e.g., `lan_zlib_compression_level`). The server reads this flat dict from `self.config`.
- **Encoding negotiation**: Clients send `SetEncodings` with ordered preferences. `EncoderManager` resolves the best encoder per rectangle based on client preferences, LAN adaptive thresholds, and tile change statistics.
- **Per-client threading**: Each connected client gets its own thread. The main frame loop captures screen, detects changed regions, encodes, and sends updates.
- **Network profiles**: Auto-detected (`localhost`/`lan`/`wan`) or overridden via config. Profiles control frame rate caps, encoding parameters, and socket tuning.

### Configuration

Runtime config lives in `config/pyvncserver.toml`. This is the only supported config format (TOML).

### Tests

Tests use `pytest` and live in `tests/`. The `conftest.py` adds `src/` to `sys.path`. Tests are self-contained with mocks for screen capture and socket I/O — no live VNC connection needed.

## Conventions

- Python 3.13+ required. Uses `match/case`, `type` aliases, and `ExceptionGroup`.
- Commit messages follow Conventional Commits: `feat(server):`, `fix(encoder):`, `refactor(capture):`, `docs:`, `perf(encoder):`, `build:`, etc.
- 4-space indentation, type hints on public APIs, `snake_case` functions, `PascalCase` classes, `UPPER_SNAKE_CASE` constants.
- New code should go in `src/pyvncserver/` domain packages. `vnc_lib` is the legacy internal library.
