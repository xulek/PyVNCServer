# CLI & Python API

## Command line

The installed entry point is:

```text
pyvncserver
```

### Start the server

```bash
pyvncserver serve
```

### Custom configuration

```bash
pyvncserver serve --config path/to/config.toml
```

### Log level override

```bash
pyvncserver serve --log-level DEBUG
```

Accepted log-level values are handled by the server logging configuration; typical values are `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL`.

Running without an explicit subcommand defaults to `serve`.

## Public Python package surface

The top-level package currently exports:

```python
from pyvncserver import (
    __version__,
    DEFAULT_CONFIG_PATH,
    ServerSettings,
    VNCServer,
    VNCServerV3,
    load_config_file,
)
```

### Load and validate configuration

```python
from pyvncserver import ServerSettings

settings = ServerSettings.from_file("config/pyvncserver.toml")
print(settings.host, settings.port)
```

`ServerSettings` is immutable (`frozen`) and validates core/security values before use.

### Flat compatibility mapping

```python
from pyvncserver import load_config_file

config = load_config_file("config/pyvncserver.toml")
print(config["host"])
print(config["websocket_max_message_bytes"])
```

The loader flattens TOML sections into the mapping expected by the existing runtime while preserving typed validation through `ServerSettings`.

## Stability note

`pyvncserver` is the public package surface. `vnc_lib` remains an internal/compatibility implementation layer; new integrations should prefer imports from `pyvncserver` where an equivalent public symbol exists.
