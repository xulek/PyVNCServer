#!/usr/bin/env python3
"""Static architecture checks for the PyVNCServer 4.x package boundary."""

from __future__ import annotations

import ast
from pathlib import Path
import sys


PUBLIC_MODULES = {
    "pyvncserver.capture",
    "pyvncserver.encodings",
    "pyvncserver.errors",
    "pyvncserver.plugins",
    "pyvncserver.protocol",
    "pyvncserver.security",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    package = src / "pyvncserver"
    failures: list[str] = []

    if (src / "vnc_lib").exists():
        failures.append("top-level src/vnc_lib still exists")

    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            failures.append(f"syntax error in {path.relative_to(root)}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "vnc_lib" or alias.name.startswith("vnc_lib."):
                        failures.append(f"legacy import in {path.relative_to(root)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "vnc_lib" or module.startswith("vnc_lib."):
                    failures.append(f"legacy import in {path.relative_to(root)}:{node.lineno}")

    for module in sorted(PUBLIC_MODULES):
        path = src / Path(*module.split("."))
        if path.is_dir():
            path = path / "__init__.py"
        else:
            path = path.with_suffix(".py")
        if not path.is_file():
            failures.append(f"missing public module: {module}")

    if not (package / "py.typed").is_file():
        failures.append("PEP 561 marker src/pyvncserver/py.typed is missing")

    if failures:
        print("PyVNCServer 4.x architecture check: FAIL")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("PyVNCServer 4.x architecture check: PASS")
    print(" - no top-level vnc_lib package")
    print(" - no legacy vnc_lib imports")
    print(" - public facade modules present")
    print(" - PEP 561 marker present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
