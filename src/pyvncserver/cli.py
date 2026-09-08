"""Packaged command line interface for PyVNCServer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from .app.server import run_server
from .config import DEFAULT_CONFIG_PATH, ServerSettings, load_config_file
from .diagnostics import format_doctor_report, run_doctor, runtime_info
from .release import format_release_report, run_release_check
from ._version import SERVER_NAME


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyvncserver", description=f"{SERVER_NAME} CLI")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the VNC server")
    serve_parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to TOML configuration")
    serve_parser.add_argument("--log-level", default=None, help="Override log level")

    doctor_parser = subparsers.add_parser("doctor", help="Check configuration and runtime prerequisites")
    doctor_parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    _add_json_flag(doctor_parser)

    info_parser = subparsers.add_parser("info", help="Show installed version and optional runtime capabilities")
    _add_json_flag(info_parser)

    config_parser = subparsers.add_parser("config", help="Create or validate TOML configuration")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_init = config_sub.add_parser("init", help="Write a safe starter configuration")
    config_init.add_argument("path", nargs="?", default="pyvncserver.toml")
    config_init.add_argument("--force", action="store_true")
    config_validate = config_sub.add_parser("validate", help="Validate configuration without starting the server")
    config_validate.add_argument("path", nargs="?", default=str(DEFAULT_CONFIG_PATH))
    _add_json_flag(config_validate)

    release_parser = subparsers.add_parser("release", help="Local release validation")
    release_sub = release_parser.add_subparsers(dest="release_command", required=True)
    release_check = release_sub.add_parser("check", help="Validate release metadata and source tree")
    release_check.add_argument("--root", default=".")
    _add_json_flag(release_check)

    benchmark = subparsers.add_parser("benchmark", help="Benchmark the configured capture backend")
    benchmark.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    benchmark.add_argument("--backend", choices=["auto", "dxcam", "mss", "pil"], default=None)
    benchmark.add_argument("--iterations", type=int, default=20)
    benchmark.add_argument("--warmup", type=int, default=3)
    _add_json_flag(benchmark)

    return parser


def _cmd_config_init(path_text: str, force: bool) -> int:
    target = Path(path_text)
    if target.exists() and not force:
        print(f"Refusing to overwrite existing file: {target}", file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEFAULT_CONFIG_PATH, target)
    print(f"Wrote safe starter configuration: {target}")
    return 0


def _cmd_config_validate(path_text: str, as_json: bool) -> int:
    try:
        values = load_config_file(path_text)
        settings = ServerSettings.from_mapping(values)
        result = {"ok": True, "path": str(path_text), "host": settings.host, "port": settings.port}
    except Exception as exc:
        result = {"ok": False, "path": str(path_text), "error": str(exc)}
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Configuration valid" if result["ok"] else f"Configuration invalid: {result['error']}")
    return 0 if result["ok"] else 2


def _cmd_benchmark(args: argparse.Namespace) -> int:
    from pyvncserver._core.screen_capture import ScreenCapture

    values = load_config_file(args.config)
    settings = ServerSettings.from_mapping(values)
    backend = args.backend or settings.capture_backend
    capture = ScreenCapture(
        scale_factor=settings.scale_factor,
        monitor=settings.monitor_index,
        backend_preference=backend,
    )
    try:
        result = capture.benchmark_capture(
            {
                "bits_per_pixel": 32,
                "depth": 24,
                "big_endian_flag": 0,
                "true_colour_flag": 1,
                "red_max": 255,
                "green_max": 255,
                "blue_max": 255,
                "red_shift": 16,
                "green_shift": 8,
                "blue_shift": 0,
            },
            iterations=max(1, args.iterations),
            warmup=max(0, args.warmup),
        )
    finally:
        capture.close_current_thread_sessions()

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Backend: {result['backend']}")
        print(f"Frame:   {result['width']}x{result['height']} ({result['bytes']} bytes)")
        print(f"Samples: {result['iterations']}")
        print(f"Average: {result['avg_ms']:.2f} ms")
        print(f"Min/Max: {result['min_ms']:.2f} / {result['max_ms']:.2f} ms")
        print(f"Approx:  {result['fps']:.1f} FPS")
    return 0 if result.get("iterations", 0) else 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "serve"

    if command == "serve":
        run_server(config_file=args.config, log_level=args.log_level)
        return 0
    if command == "doctor":
        report = run_doctor(args.config)
        print(report.to_json() if args.json else format_doctor_report(report))
        return 0 if report.ok else 2
    if command == "info":
        info = runtime_info()
        print(json.dumps(info, indent=2, sort_keys=True) if args.json else "\n".join(
            [f"PyVNCServer {info['version']}", f"Python: {info['python']}", f"Platform: {info['platform']}", f"Default config: {info['default_config']}"]
        ))
        return 0
    if command == "config":
        if args.config_command == "init":
            return _cmd_config_init(args.path, args.force)
        return _cmd_config_validate(args.path, args.json)
    if command == "benchmark":
        return _cmd_benchmark(args)
    if command == "release":
        report = run_release_check(args.root)
        print(report.to_json() if args.json else format_release_report(report))
        return 0 if report.ok else 2

    parser.error(f"Unsupported command: {command}")
    return 2
