# Performance and latency

PyVNCServer 4.1 focuses on **frame freshness and end-to-end latency**, not only theoretical throughput. The low-latency path is designed to avoid spending CPU or socket queue space on a frame that has already been superseded.

## v4.1 low-latency pipeline

The default profile is:

```toml
[performance]
profile = "low-latency"
capture_producer_fps = 120
socket_send_buffer_bytes = 262144
socket_receive_buffer_bytes = 131072
framebuffer_send_coalesce_bytes = 131072
producer_conversion_cache_entries = 4
producer_conversion_cache_max_bytes = 67108864
drop_stale_continuous_frames = true
```

Three profiles are accepted:

| Profile | Goal | TCP/send behavior | Cache behavior |
| --- | --- | --- | --- |
| `low-latency` | freshest possible frame | smaller send queue, earlier backpressure | encoded-region cache skipped for a single client |
| `balanced` | latency/throughput compromise | larger coalescing and socket queue | cache remains available |
| `throughput` | bulk transfer efficiency | largest queue/coalescing defaults | favors reuse and fewer syscalls |

### Exact unchanged-frame fast path

The software change detector first performs an exact whole-frame equality comparison against the previous framebuffer. If the frame is byte-for-byte identical, tile CRC scanning is skipped entirely. This is exact, not sampled, so it cannot miss a changed pixel. On the development microbenchmark, a static 1920×1080×4 frame dropped from roughly 10 ms of tile scanning to well below 1 ms. Treat this as a CPU microbenchmark, not a Windows/DXGI glass-to-glass result.

### Bounded dirty-region compaction

Adaptive region merging no longer allows a large pathological rectangle set to turn into an expensive quadratic hot path. The v4.1 merge path uses bounded greedy compaction and retains the configured expansion guard, so nearby rectangles can be combined without accidentally encoding a huge mostly-unchanged area.

### Fewer copies and allocations

- contiguous full-width framebuffer regions are sliced in one operation;
- partial regions use `memoryview`-backed row copies;
- `recv_exact()` prefers `recv_into()` so input messages do not allocate a new bytes object for every receive chunk;
- large framebuffer payloads are sent separately instead of always building one giant joined `bytes`;
- shared producer pixel-format conversions are cached per framebuffer generation and pixel format.

### Freshness over queue depth

ContinuousUpdates checks whether the generation being encoded has already been superseded. With `drop_stale_continuous_frames = true`, an obsolete frame is discarded before wire send and the session proceeds toward the newest generation.

The low-latency socket send buffer defaults to 256 KiB. A smaller queue causes slow clients to exert backpressure earlier instead of allowing multiple old framebuffer updates to sit in the kernel queue.

### Single-client cache policy

Hashing a large rectangle just to look it up in the shared encoded-region cache can cost more than it saves when there is only one low-latency client. For `profile = "low-latency"`, that cache is bypassed for one authenticated session and becomes active when multiple sessions can actually reuse the encoded result. Raw encoding is excluded from encoded-region cache reuse.

## Latency telemetry

Per-connection metrics include producer-to-wire latency samples and stale-frame drops. Status/metrics expose P50/P95/P99 values so regressions are visible even when average FPS still looks healthy.

Key measurements to watch:

- capture duration;
- producer generation age;
- encode duration;
- socket send duration;
- producer→wire P50/P95/P99;
- stale frames dropped;
- transmitted bytes and compression ratio.

## Benchmarks

### CPU hot-path benchmark

```bash
PYTHONPATH=src python benchmarks/benchmark_latency_pipeline.py --width 1920 --height 1080 --iterations 100
```

It reports min/avg/P50/P95/P99/max for:

- exact unchanged-frame detection;
- 8/16/32/64 dirty-rectangle compaction;
- full-width and inner framebuffer extraction.

### End-to-end LAN request/response

```bash
PYTHONPATH=src python benchmarks/benchmark_lan_latency.py 192.168.1.10 5900 100
```

This measures TCP connect time, RFB handshake and framebuffer request-to-response latency. Run it from the actual client machine against the Windows server to obtain useful LAN latency figures.

### Other benchmarks

```bash
PYTHONPATH=src python benchmarks/benchmark_encoders.py
PYTHONPATH=src python benchmarks/benchmark_screen_capture.py
PYTHONPATH=src python benchmarks/benchmark_screen_capture_methods.py
python benchmarks/benchmark_dxgi_metadata.py --frames 300 --fps 120
```

## Capture backends

`capture_backend = "auto"` chooses from available backends. DXCam/DXGI remains the preferred Windows low-latency path when available; MSS and Pillow are fallbacks. Native DXGI dirty/move metadata avoids software diff work when the capture is an unscaled, unrotated full output. If metadata is invalid or unavailable, correctness takes priority and the software detector is used.

## Shared capture producer

A server-wide producer captures once and publishes framebuffer generations to all sessions. In 4.1 its low-latency default target is 120 FPS. Clients can still stream at a lower adaptive/session FPS; the higher producer rate mainly reduces the age of the newest available frame.

## Measuring correctly

For meaningful results:

- measure on the target Windows GPU/display configuration;
- test idle desktop, text editing, dragging windows, scrolling and video separately;
- distinguish capture, diff, encode, send and network/display latency;
- report P50/P95/P99, not only averages;
- test the actual viewer (UltraVNC/noVNC) and intended LAN/WAN path;
- compare CPU usage and transmitted bytes as well as latency.
