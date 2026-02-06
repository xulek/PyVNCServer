# noVNC Integration Notes

This project includes a browser client (`web/vnc_client.html`) built on top of the bundled noVNC sources in `web/noVNC`.

## 1. Enable WebSocket in server config

Set in `config.json`:

```json
{
  "enable_websocket": true
}
```

Important: current repository default is `false`, so this must be enabled explicitly.

## 2. Start PyVNCServer

```bash
python vnc_server.py
```

## 3. Serve the web assets

From repository root:

```bash
python -m http.server 8000
```

Open:

`http://localhost:8000/web/vnc_client.html`

Do not open the HTML directly with `file://`; ES module imports for noVNC require HTTP/HTTPS.

## 4. Connection settings

- Host: `localhost`
- Port: `5900` (or your configured server port)
- Password: if configured in `config.json`

## Using upstream noVNC UI

If you prefer upstream `vnc.html` or `vnc_lite.html`, connect directly to:

`ws://<server-host>:<server-port>`

PyVNCServer already supports WebSocket on the same port as VNC, so `websockify` is not required for basic usage.

## Minimal embedding example

```html
<script type="module">
  import RFB from './noVNC/core/rfb.js';

  const rfb = new RFB(
    document.getElementById('screen'),
    'ws://localhost:5900',
    { credentials: { password: '' } }
  );

  rfb.scaleViewport = true;
</script>
```

## Security note

For production browser access, terminate TLS at a reverse proxy and expose `wss://`.

## Related docs

- `WEBSOCKET.md`
- `web/vnc_client.html`
- https://github.com/novnc/noVNC
