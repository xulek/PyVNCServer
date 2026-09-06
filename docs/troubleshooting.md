# Troubleshooting

## Viewer connects, then immediately disconnects

Run with debug logs:

```bash
pyvncserver serve --log-level DEBUG
```

Check the last negotiated/selected encoding. If the disconnect happens immediately after one encoding is selected, retry with Raw or Hextile to establish whether the failure is codec-specific.

For UltraVNC-specific cases, see [UltraVNC](ultravnc.md).

## Tight connects but the image stops updating

Try, in order:

1. confirm Raw/Zlib/ZRLE updates continue;
2. reconnect with Tight selected from session start;
3. enable debug logging;
4. try `tight_stream_reset_for_ultravnc = true` for UltraVNC;
5. use `tight_disable_for_ultravnc = true` only as a diagnostic fallback.

A server can remain connected even when an encoding stream is desynchronized, so absence of a socket exception does not prove the encoded rectangles are valid.

## RRE disconnects the viewer

A correct RRE rectangle must contain RRE-formatted payload bytes. If an encoder fallback emits Raw bytes, the rectangle header must advertise Raw too. Current PyVNCServer keeps the payload/header pair consistent and bounds RRE work with tiling.

## Server refuses to start on `0.0.0.0`

This is deliberate when no authentication is configured.

Choose one:

```toml
[security]
password = "vncpass"
```

or bind to loopback, or explicitly opt into unsafe no-auth operation:

```toml
[security]
allow_insecure_no_auth = true
```

## Browser connection rejected

For noVNC/WebSocket:

- enable WebSocket support;
- add the exact browser Origin to `allowed_origins`;
- verify binary WebSocket transport;
- check reverse-proxy Upgrade headers;
- ensure message limits are not below the client workload.

## Capture backend fails

Use:

```toml
[server]
capture_backend = "auto"
```

The capture layer can probe/fall back between available backends. If DXCam fails, confirm the optional performance dependencies are installed and retry with MSS to isolate the GPU/Desktop Duplication path.

## Performance is unexpectedly low

Check:

- which capture backend was selected;
- whether full-frame updates are being sent instead of incremental regions;
- selected encoding and compression level;
- client update request cadence;
- network profile detection;
- whether `encoding_threads` is oversubscribing the CPU.

Use the scripts described in [Performance](performance.md) to separate capture and encoding costs.
