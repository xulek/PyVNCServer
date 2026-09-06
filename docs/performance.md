# Performance

PyVNCServer optimizes the path from desktop capture to encoded rectangle rather than relying on one codec alone.

## Capture backends

`capture_backend = "auto"` chooses from available backends.

| Backend | Platform | Role |
| --- | --- | --- |
| DXCam / DXGI | Windows | optional fast Desktop Duplication capture path |
| MSS | cross-platform | portable primary fallback |
| Pillow ImageGrab | platform dependent | fallback capture path |

Install the performance extras:

```bash
python -m pip install -e ".[performance]"
```

## Shared capture producer

A server-wide producer captures once and distributes framebuffer generations to sessions. This avoids N clients causing N independent desktop captures.

## Changed regions

Incremental requests benefit from limiting work to changed regions. When a backend cannot provide native dirty metadata, PyVNCServer performs change detection above the backend.

!!! note
    Native DXGI dirty/move rectangle harvesting is not yet implemented in the current DXCam integration. CopyRect/dirty-region opportunities therefore depend on metadata available to the higher layers.

## Request coalescing

Viewers can generate update/input messages faster than the server should perform expensive work. Request coalescing reduces redundant framebuffer computations while preserving the most recent requested state.

## Encoding workers

```toml
[limits]
encoding_threads = 0
```

`0` enables automatic worker selection. More workers are not always faster: compression, memory bandwidth and Python/native-code behavior matter, and many tiny rectangles can lose to scheduling overhead.

## Network profiles

```toml
[server]
network_profile_override = "auto"
frame_rate = 30
lan_frame_rate = 90
```

Automatic profiling allows localhost/LAN/WAN tuning to diverge. Forcing `lan` everywhere can waste bandwidth or CPU on slower links.

## Compression tuning

Relevant LAN settings include zlib/ZRLE compression levels, raw thresholds and JPEG thresholds/quality. Lower zlib levels often reduce latency on fast LANs at the cost of additional bytes.

## Benchmarks

```bash
PYTHONPATH=src python benchmarks/benchmark_encoders.py
PYTHONPATH=src python benchmarks/benchmark_screen_capture.py
PYTHONPATH=src python benchmarks/benchmark_screen_capture_methods.py
PYTHONPATH=src python benchmarks/benchmark_lan_latency.py
```

For meaningful numbers:

- benchmark on the target OS/GPU/display setup;
- separate capture time from encode time;
- test full-screen and small-region updates;
- include the actual viewer over the intended network path;
- record CPU usage and transmitted bytes, not only FPS.
