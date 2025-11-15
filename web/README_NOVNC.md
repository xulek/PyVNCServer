# noVNC Quick Notes

PyVNCServer ships with built‑in WebSocket + noVNC support. Below are the only steps you need.

## 1. Ensure WebSocket is enabled

`config.json` should contain:
```json
{ "enable_websocket": true }
```
(Default is already `true` in this repo.)

## 2. Start the server

```bash
python vnc_server.py
```

## 3. Use the bundled browser client (recommended)

```bash
python -m http.server 8000        # from repo root
# visit http://localhost:8000/web/vnc_client.html
```

Features:
- Responsive canvas that stays visible (no CSS hacks needed)
- FPS/Bandwidth/Resolution/Encoding stats
- Toggleable **View only** mode (blocks mouse/keyboard)

Because the page imports `web/noVNC` via ES modules, serve it over HTTP/HTTPS (not `file://`).

## 4. Prefer upstream noVNC UI?

```bash
git clone https://github.com/novnc/noVNC.git
cd noVNC
# open vnc.html or vnc_lite.html in your browser
```
Connect using `Host=localhost`, `Port=5900`, optional password.

## 5. Embedding elsewhere

Import the module from `web/noVNC/core/rfb.js`:

```html
<script type="module">
  import RFB from './noVNC/core/rfb.js';
  const rfb = new RFB(document.getElementById('screen'), 'ws://localhost:5900', {
    credentials: { password: '' },
  });
  rfb.scaleViewport = true;
</script>
```

That’s it—no websockify needed since PyVNCServer already speaks WebSocket/TCP on the same port (5900).
