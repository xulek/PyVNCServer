# Performance

PyVNCServer optimizes the path from desktop capture to encoded rectangle rather than relying on one codec alone.

## Capture backends

`capture_backend = "auto"` chooses from available backends.

| Backend | Platform | Role |
| --- | --- | --- |
| DXCam / DXGI | Windows | optional fast Desktop Duplication capture path with native dirty/move metadata in v3.3 |
| MSS | cross-platform | portable primary fallback |
| Pillow ImageGrab | platform dependent | fallback capture path |

Install the performance extras:

```bash
python -m pip install -e ".[performance]"
```

PyVNCServer 3.3 requires DXCam `0.3.0+` for the native metadata integration.

## Shared capture producer

A server-wide producer captures once and distributes framebuffer generations to sessions. This avoids N clients causing N independent desktop captures.

## Native DXGI changed regions

On an unscaled, unrotated full-output DXCam capture, v3.3 reads Desktop Duplication metadata directly from the active `IDXGIOutputDuplication` object:

- `GetFrameDirtyRects` identifies framebuffer regions whose pixel contents changed;
- `GetFrameMoveRects` identifies regions copied from another framebuffer location and exposes them as CopyRect hints;
- a DXGI timeout/no-new-frame is treated as an authoritative empty update;
- any metadata read/validation failure returns to the existing software change detector instead of assuming the screen is unchanged.

Native metadata is deliberately disabled for scaled, rotated or cropped DXCam captures until coordinate translation is implemented. MSS and Pillow also continue to use software change detection.

!!! important
    Native metadata is an optimization, never a correctness requirement. An ambiguous native result becomes `dirty_regions = None`, which explicitly activates the software differ.

### Move-rectangle safety in v3.3

Move destinations are currently included in the dirty pixel list even when a CopyRect hint is emitted. This is intentionally conservative: clients without CopyRect support and clients that skip capture generations still converge to the correct framebuffer. Once the real-client interoperability matrix has broader coverage, the redundant pixel update can be removed for clients that are exactly one generation behind and advertise CopyRect.

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

Encoder/capture benchmarks:

```bash
PYTHONPATH=src python benchmarks/benchmark_encoders.py
PYTHONPATH=src python benchmarks/benchmark_screen_capture.py
PYTHONPATH=src python benchmarks/benchmark_screen_capture_methods.py
PYTHONPATH=src python benchmarks/benchmark_lan_latency.py
```

### DXGI metadata benchmark

On a real Windows desktop with the performance extra installed:

```powershell
python benchmarks/benchmark_dxgi_metadata.py --frames 300 --fps 60
```

The diagnostic reports:

- native metadata hit rate vs software-diff fallback rate;
- average and p95 capture time;
- average dirty/move rectangle count;
- approximate changed framebuffer area.

For meaningful numbers:

- benchmark on the target OS/GPU/display setup;
- test idle desktop, text editing, window movement, scrolling and video separately;
- separate capture time from encode time;
- test full-screen and small-region updates;
- include the actual viewer over the intended network path;
- record CPU usage and transmitted bytes, not only FPS.
