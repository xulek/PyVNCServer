# Repository Guidelines

## Project Structure & Module Organization

- `src/pyvncserver/`: primary packaged application and library code.
- `src/pyvncserver/app/`: server bootstrap and runtime entrypoints.
- `src/pyvncserver/rfb/`, `platform/`, `runtime/`, `features/`, `observability/`: domain layers.
- `src/vnc_lib/`: internal support modules still packaged with the project; prefer `pyvncserver.*` for new code.
- `tests/`: regression and unit tests. Add new tests here, not under `examples/`.
- `config/`: preferred runtime config, e.g. `config/pyvncserver.toml`.
- `web/`: browser assets and noVNC integration.
- `docs/`: architecture, configuration, and operational notes.

## Build, Test, and Development Commands

- `python -m pip install -e .[dev]`: install the package in editable mode with test dependencies.
- `$env:PYTHONPATH="src"; python -m pyvncserver --help`: run the packaged module directly from a checkout without installing it.
- `pyvncserver serve --config config/pyvncserver.toml`: run the packaged server entrypoint.
- `python -m pytest tests -q`: run the full test suite.
- `python -m pytest tests/test_packaging.py tests/test_vnc_server.py -q`: run focused packaging and server regressions.
- `python -m py_compile src\pyvncserver\app\server.py src\pyvncserver\cli.py`: quick syntax validation before a larger run.

## Coding Style & Naming Conventions

- Target Python `3.13+`.
- Use 4-space indentation and type hints on public functions and methods.
- Prefer small, domain-focused modules under `src/pyvncserver/` over expanding monoliths.
- Use `snake_case` for modules/functions, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.
- Preserve ASCII unless a file already requires Unicode.
- Keep compatibility shims thin; put real logic in packaged modules, not in wrappers.

## Testing Guidelines

- Tests use `pytest`.
- Name files `test_*.py` and test functions `test_*`.
- Add regression tests with each bug fix, especially for protocol negotiation, encodings, and config loading.
- When refactoring imports or packaging, add smoke tests similar to `tests/test_packaging.py`.

## Commit & Pull Request Guidelines

- Follow the existing commit style: Conventional Commit prefixes such as `feat(server): ...`, `refactor(server): ...`, `docs: ...`.
- Keep commits scoped to one change area when possible.
- PRs should include:
  - a short summary of behavior changes,
  - testing performed (`pytest` commands),
  - config or import-path notes if entrypoints/imports changed,
  - screenshots only for web/client UI changes.

## Security & Configuration Tips

- Do not expose the server without authentication or network protections.
- Use `config/pyvncserver.toml` as the only supported runtime config.
- Treat WebSocket origin allowlists and protocol limits as production settings, not optional cleanup.
