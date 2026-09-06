# Security

A remote framebuffer server processes network input and can inject keyboard/pointer events. Treat its exposure as a security boundary.

## Safe defaults

The packaged configuration binds to loopback:

```toml
[server]
host = "127.0.0.1"
port = 5900
```

With no configured password, a non-loopback bind is rejected unless you explicitly set:

```toml
[security]
allow_insecure_no_auth = true
```

That opt-in should be restricted to controlled development environments.

## Classic VNC authentication

```toml
[security]
password = "vncpass"
read_only_password = "readonly"
```

Important limitations:

- classic VNC authentication uses the legacy DES challenge/response mechanism;
- passwords are limited to **8 Latin-1 bytes** by this authentication scheme;
- it authenticates the client but does **not encrypt** framebuffer or input traffic;
- full-control and read-only passwords must be different.

## TLS

```toml
[security]
tls_enabled = true
tls_cert_file = "server.crt"
tls_key_file = "server.key"
```

When TLS is enabled, both files are required and must exist at startup.

For internet-facing or otherwise untrusted paths, use TLS or place VNC behind a VPN/SSH tunnel.

## Admission and authentication limits

```toml
[server]
max_connections = 10
max_connections_per_ip = 4
max_unauthenticated_connections = 4
handshake_timeout = 5.0

[security]
auth_max_failures = 5
auth_failure_window_seconds = 30.0
auth_backoff_max_seconds = 2.0
```

These controls reduce resource exhaustion and repeated authentication attempts before a session is established.

## Browser Origin policy

When WebSocket support is enabled for browser clients, configure explicit allowed Origins:

```toml
[websocket]
allowed_origins = ["https://vnc.example.com"]
```

Do not treat Origin checking as transport encryption; use HTTPS/WSS as well.

## Deployment checklist

- [ ] bind only to the interface you actually need;
- [ ] configure authentication for any non-loopback listener;
- [ ] use TLS/VPN/SSH on untrusted networks;
- [ ] keep WebSocket Origins explicit;
- [ ] leave payload and handshake limits enabled;
- [ ] do not log challenge/response secrets;
- [ ] keep handshake timeout and per-IP admission limits enabled;
- [ ] use a read-only password when input control is unnecessary.
