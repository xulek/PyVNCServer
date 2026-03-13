# WebSocket Support

PyVNCServer can accept browser connections over WebSocket (for noVNC and custom web clients).

## How It Works

- WebSocket and regular VNC can share the same TCP port (default `5900`).
- The server detects WebSocket handshakes by checking whether the incoming stream starts with HTTP `GET`.
- If a WebSocket upgrade is detected, the socket is wrapped and VNC frames are tunneled through WebSocket binary frames.
- If not, the connection continues as regular RFB/TCP.

## Quick Start

### 1. Enable WebSocket in `config/pyvncserver.toml`

```toml
[features]
enable_websocket = true

[websocket]
allowed_origins = ["http://localhost:8000"]
```

`allowed_origins` is required for browser clients. If it is empty, browser handshakes with an `Origin` header are rejected by default.

### 2. Start the server

```bash
pyvncserver serve --config config/pyvncserver.toml
```

### 3. Serve the bundled web client

```bash
python -m http.server 8000
```

Open:

`http://localhost:8000/web/vnc_client.html`

The page imports modules from `web/noVNC`, so use HTTP/HTTPS (not `file://`).

### 4. Connect

- Host: `localhost`
- Port: `5900` (or your configured VNC port)
- Password: according to `config/pyvncserver.toml`

## Upstream noVNC UI

You can also use upstream noVNC (`vnc.html` / `vnc_lite.html`) and connect directly to:

`ws://<server-host>:<vnc-port>`

No `websockify` is required for plain WebSocket because PyVNCServer already supports WebSocket transport.

## Minimal Embedding Example

```html
<script type="module">
  import RFB from './noVNC/core/rfb.js';
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const rfb = new RFB(
    document.getElementById('screen'),
    `${scheme}://localhost:5900`,
    { credentials: { password: '' } }
  );
  rfb.scaleViewport = true;
</script>
```

## Production Notes (TLS / `wss://`)

PyVNCServer provides plain `ws://` transport.  
For browser-safe encrypted transport in production, terminate TLS in a reverse proxy and expose `wss://`.

Example (Nginx):

```nginx
location / {
    proxy_pass http://localhost:5900;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

## Troubleshooting

### Browser page loads but cannot connect

- Verify `enable_websocket = true` in `[features]`.
- Verify `allowed_origins` contains the origin serving the page, for example `http://localhost:8000`.
- Ensure VNC server is running on the target host/port.
- Check that firewalls allow inbound TCP on the VNC port.

### Opening HTML file directly fails

Use an HTTP server (`python -m http.server 8000`), because ES module imports from `web/noVNC` do not work reliably via `file://`.

## Related Docs

- `web/README_NOVNC.md`
- `web/vnc_client.html`
- https://github.com/novnc/noVNC
