# Installation & quick start

This page takes you from a clean Python environment to a working local VNC session.

## Requirements

- Python **3.11+**
- a supported desktop capture/input environment
- a VNC viewer such as UltraVNC

Windows is the primary platform for the optional DXCam/DXGI fast capture path. MSS provides the portable capture backend.

## Install from source

=== "Windows PowerShell"

    ```powershell
    git clone https://github.com/xulek/PyVNCServer.git
    cd PyVNCServer
    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -U pip
    python -m pip install -e .
    ```

=== "Linux / macOS"

    ```bash
    git clone https://github.com/xulek/PyVNCServer.git
    cd PyVNCServer
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    python -m pip install -e .
    ```

### Optional extras

```bash
# NumPy + DXCam on Windows
python -m pip install -e ".[performance]"

# H.264 extension path
python -m pip install -e ".[h264]"

# local development/test dependencies
python -m pip install -e ".[dev]"
```

## Start the server

```bash
pyvncserver serve
```

Equivalent module invocation:

```bash
python -m pyvncserver serve
```

The packaged default configuration binds to:

```text
127.0.0.1:5900
```

!!! tip
    Keeping the first test on loopback removes firewall, NAT and transport-security variables. Confirm the RFB path works locally before exposing the listener.

## Connect with a viewer

For UltraVNC:

1. Open UltraVNC Viewer.
2. Connect to `127.0.0.1:5900`.
3. Leave the encoding on **Auto** for the first test.
4. Once connected, try Tight, ZRLE, Hextile, Zlib and RRE individually if you want to compare behavior.

See the [UltraVNC guide](ultravnc.md) for compatibility-specific notes.

## Use a custom config

Copy the example config and edit it:

```bash
cp config/pyvncserver.toml my-vnc.toml
pyvncserver serve --config my-vnc.toml
```

On PowerShell:

```powershell
Copy-Item config/pyvncserver.toml my-vnc.toml
pyvncserver serve --config my-vnc.toml
```

Override only logging verbosity:

```bash
pyvncserver serve --config my-vnc.toml --log-level DEBUG
```

## Expose it on your LAN

Do **not** only change `host` and forget authentication. A minimal authenticated LAN example is:

```toml
[server]
host = "0.0.0.0"
port = 5900

[security]
password = "vncpass"
```

Classic VNC authentication is limited to 8 Latin-1 bytes and does not encrypt the session. Prefer TLS, SSH tunnelling or a VPN on untrusted networks. See [Security](security.md).

## Next steps

- [Configuration reference](configuration.md)
- [UltraVNC](ultravnc.md)
- [noVNC & WebSocket](novnc.md)
- [Troubleshooting](troubleshooting.md)
