"""Build local wheel/sdist after running PyVNCServer's release checks."""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import shutil
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run([sys.executable, "-m", "pyvncserver", "release", "check", "--root", str(root)], cwd=root, check=True, env=env)
    dist = root / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    # Build through the backend declared by pyproject.toml; no network access is needed
    # when setuptools/wheel are already installed.
    code = "from setuptools import build_meta; build_meta.build_wheel('dist'); build_meta.build_sdist('dist')"
    subprocess.run([sys.executable, "-c", code], cwd=root, check=True)
    print(f"Artifacts written to {dist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
