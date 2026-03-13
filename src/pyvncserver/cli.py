"""
Packaged command line interface for PyVNCServer.
"""

from __future__ import annotations

import argparse

from .app.server import run_server
from .config import DEFAULT_CONFIG_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyvncserver", description="PyVNCServer CLI")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the VNC server")
    serve_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to TOML or legacy JSON configuration (default: {DEFAULT_CONFIG_PATH.as_posix()})",
    )
    serve_parser.add_argument(
        "--log-level",
        default=None,
        help="Override log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command or "serve"
    if command == "serve":
        run_server(config_file=args.config, log_level=args.log_level)
        return 0

    parser.error(f"Unsupported command: {command}")
    return 2

