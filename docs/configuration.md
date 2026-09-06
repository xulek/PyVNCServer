# Configuration

PyVNCServer uses TOML. The packaged defaults live in `src/pyvncserver/default_config.toml`; the repository also contains `config/pyvncserver.toml` as an editable example.

Configuration loading is intentionally **fail-closed**: missing/malformed files and invalid security-sensitive values stop startup instead of silently falling back to unsafe defaults.

## Server

| Option | Default | Meaning |
| --- | ---: | --- |
| `host` | `127.0.0.1` | TCP bind address |
| `port` | `5900` | VNC/RFB TCP port, `1..65535` |
| `frame_rate` | `30` | baseline target FPS, `1..240` |
| `lan_frame_rate` | `90` | LAN target FPS, `1..240` |
| `network_profile_override` | `auto` | automatic detection or `localhost`, `lan`, `wan` |
| `scale_factor` | `1.0` | framebuffer scale; must be positive |
| `capture_backend` | `auto` | capture backend selection |
| `capture_probe_frames` | `0` | optional backend startup probe count |
| `capture_probe_warn_ms` | `40.0` | slow-probe warning threshold |
| `max_connections` | `10` | total admitted connections |
| `max_connections_per_ip` | `4` | per-IP cap |
| `max_unauthenticated_connections` | `4` | pre-authentication admission cap |
| `handshake_timeout` | `5.0` | handshake timeout in seconds |
| `client_socket_timeout` | `60.0` | client socket timeout |
| `input_control_policy` | `single-controller` | `single-controller` or `shared` |

## Security

| Option | Default | Meaning |
| --- | ---: | --- |
| `password` | empty | full-control classic VNC password |
| `read_only_password` | empty | read-only classic VNC password |
| `allow_insecure_no_auth` | `false` | explicit opt-in for unauthenticated non-loopback bind |
| `tls_enabled` | `false` | wrap the accepted connection in TLS |
| `tls_cert_file` | empty | certificate path |
| `tls_key_file` | empty | private-key path |
| `auth_max_failures` | `5` | failures allowed in rate-limit window |
| `auth_failure_window_seconds` | `30.0` | authentication failure window |
| `auth_backoff_max_seconds` | `2.0` | maximum auth backoff |

Passwords used by classic VNC authentication must be at most **8 Latin-1 bytes**. Full-control and read-only passwords must differ.

## Features

```toml
[features]
enable_region_detection = true
enable_metrics = true
enable_health_checks = true
enable_request_coalescing = true
enable_lan_adaptive_encoding = true
enable_websocket = false
enable_tight_extensions = true
enable_cursor_encoding = false
enable_copyrect_encoding = true
enable_zrle_encoding = true
enable_tight_encoding = true
enable_jpeg_encoding = true
enable_h264_encoding = false
enable_parallel_encoding = true
enable_capture_producer = true
tight_stream_reset_for_ultravnc = false
```

`enable_capture_producer` uses one server-wide capture producer and publishes framebuffer generations to client sessions instead of asking every client thread to capture independently.

`tight_stream_reset_for_ultravnc` is a compatibility switch. Leave it off unless you are troubleshooting Tight stream-state behavior with UltraVNC.

## LAN tuning

| Option | Default |
| --- | ---: |
| `raw_area_threshold` | `0.10` |
| `raw_max_pixels` | `65536` |
| `prefer_zlib` | `true` |
| `zlib_area_threshold` | `0.08` |
| `zlib_min_pixels` | `8192` |
| `zlib_compression_level` | `2` |
| `zlib_disable_if_request_gap_ms` | `1500` |
| `jpeg_area_threshold` | `0.20` |
| `jpeg_min_pixels` | `16384` |
| `jpeg_quality_initial` | `84` |
| `jpeg_quality_min` | `70` |
| `jpeg_quality_max` | `95` |
| `zrle_compression_level` | `3` |

These settings influence adaptive encoding decisions; they do not override what the client advertised in `SetEncodings`.

## WebSocket

```toml
[websocket]
allowed_origins = []
detect_timeout = 0.5
max_handshake_bytes = 65536
max_payload_bytes = 8388608
max_buffer_bytes = 16777216
max_message_bytes = 16777216
```

For browser clients, configure an explicit Origin allowlist. See [noVNC & WebSocket](novnc.md).

## Limits

```toml
[limits]
max_set_encodings = 1024
max_client_cut_text = 16777216
encoding_threads = 0
tight_disable_for_ultravnc = false
```

`encoding_threads = 0` means automatic worker selection. `tight_disable_for_ultravnc` is a diagnostic fallback, not a recommended default.

## Logging

```toml
[logging]
log_level = "INFO"
log_file = ""
```

Use `--log-level DEBUG` when diagnosing negotiation or encoding issues without editing the file.

## Complete safe baseline

```toml
[server]
host = "127.0.0.1"
port = 5900
frame_rate = 30
lan_frame_rate = 90
network_profile_override = "auto"
scale_factor = 1.0
capture_backend = "auto"
max_connections = 10
max_connections_per_ip = 4
max_unauthenticated_connections = 4
handshake_timeout = 5.0
client_socket_timeout = 60.0
input_control_policy = "single-controller"

[security]
password = ""
read_only_password = ""
allow_insecure_no_auth = false
tls_enabled = false
tls_cert_file = ""
tls_key_file = ""
```
