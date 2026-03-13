#!/usr/bin/env python3
"""
Legacy compatibility entrypoint for the packaged PyVNCServer runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pyvncserver.app.server import VNCServer, VNCServerV3
from pyvncserver.cli import main


__all__ = ["VNCServer", "VNCServerV3", "main"]


if __name__ == "__main__":
    main()
