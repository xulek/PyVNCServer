# Development

## Environment

```bash
python -m venv .venv
```

=== "Windows PowerShell"

    ```powershell
    .\.venv\Scripts\Activate.ps1
    python -m pip install -U pip
    python -m pip install -e ".[dev,performance]"
    ```

=== "Linux / macOS"

    ```bash
    source .venv/bin/activate
    python -m pip install -U pip
    python -m pip install -e ".[dev]"
    ```

## Tests

```bash
python -m compileall -q src tests
python -m pytest -q
```

The suite covers protocol negotiation, encoders, WebSocket framing, configuration validation, security limits, capture producer behavior and end-to-end RFB communication.

## Package build

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

## Documentation locally

```bash
python -m pip install -r requirements-docs.txt
mkdocs serve
```

Open `http://127.0.0.1:8000/PyVNCServer/` or use the URL printed by MkDocs.

Strict production build:

```bash
mkdocs build --strict
```

## GitHub Pages

`.github/workflows/docs.yml` performs a strict documentation build on pull requests. On a push to `main`, it also uploads the generated site as a GitHub Pages artifact and deploys it through the `github-pages` environment.

The repository Pages source must be configured for **GitHub Actions** in repository settings.

## Encoder changes

When changing an encoder:

- test the byte-level format, not only compression ratio;
- keep rectangle header encoding IDs consistent with fallback payloads;
- test multiple consecutive rectangles when the codec has stream state;
- test in-session encoding switches and fresh connections;
- run UltraVNC compatibility checks for Tight/RRE/Hextile/Zlib/ZRLE.

## Performance changes

Run at least the encoder benchmark for codec work:

```bash
PYTHONPATH=src python benchmarks/benchmark_encoders.py
```

For capture changes, benchmark on the target desktop platform; headless CI cannot meaningfully validate desktop-capture latency.
