# WebSocket Support - Quick Start

PyVNCServer includes built-in WebSocket support for browser-based VNC access.

## Quick Start (4 Steps)

### 1. Enable WebSocket

Edit `config.json`:
```json
{
  "enable_websocket": true
}
```

**Note:** WebSocket is disabled by default to avoid interfering with regular VNC clients.

### 2. Start Server

```bash
python vnc_server.py
```

WebSocket will listen on port 5900 (same as VNC).

### 3. Connect with Browser

Open [web/vnc_client.html](web/vnc_client.html) in your browser, or use noVNC:

```bash
git clone https://github.com/novnc/noVNC.git
cd noVNC
# Open vnc.html in browser
```

### 4. Connect to Server

- **Host:** localhost
- **Port:** 5900
- **Password:** (if configured)

## Features

✅ **No Proxy Needed** - Direct WebSocket support built-in
✅ **Auto-Detection** - Same port handles VNC and WebSocket
✅ **noVNC Compatible** - Works with standard noVNC client
✅ **High Performance** - 20-100x compression with Tight encoding
✅ **RFC 6455 Compliant** - Standard WebSocket protocol

## Configuration

```json
{
  "enable_websocket": true,
  "enable_tight_encoding": true,
  "port": 5900
}
```

## Example: Embed in Web Page

```html
<!DOCTYPE html>
<html>
<head>
    <script type="module">
        import RFB from './noVNC/core/rfb.js';

        const rfb = new RFB(
            document.getElementById('screen'),
            'ws://localhost:5900'
        );
    </script>
</head>
<body>
    <div id="screen"></div>
</body>
</html>
```

## Documentation

- **Full Guide:** [web/README_NOVNC.md](web/README_NOVNC.md)
- **Performance:** [PERFORMANCE.md](PERFORMANCE.md#websocket-support-browser-access)
- **noVNC Project:** https://github.com/novnc/noVNC

## Architecture

```
Browser (noVNC)
    ↓ WebSocket (ws://)
PyVNCServer (auto-detect WebSocket)
    ↓ VNC Protocol over WebSocket frames
Screen Capture → Encoding (Tight) → WebSocket → Browser
```

## Performance

| Metric | Value |
|--------|-------|
| Bandwidth | 2-5 MB/s (with Tight) |
| Latency | 20-50ms (LAN) |
| FPS | 30-60 |
| Compression | 95-97% reduction |

## Browser Support

✅ Chrome/Chromium
✅ Firefox
✅ Safari
✅ Edge
✅ Mobile browsers

## Security

For production, use reverse proxy with TLS:

```nginx
location / {
    proxy_pass http://localhost:5900;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

---

**That's it!** Browser-based VNC access with zero configuration.
