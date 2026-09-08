"""Local release checks for PyVNCServer artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import compileall
import json
from pathlib import Path
import re
from typing import Any

from ._version import __version__
from .config import DEFAULT_CONFIG_PATH, load_config_file


@dataclass(frozen=True, slots=True)
class ReleaseCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    version: str
    root: str
    checks: tuple[ReleaseCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "version": self.version,
            "root": self.root,
            "checks": [asdict(check) for check in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def run_release_check(root: str | Path = ".", *, compile_sources: bool = True) -> ReleaseReport:
    root_path = Path(root).resolve()
    checks: list[ReleaseCheck] = []

    checks.append(ReleaseCheck(
        "version-format",
        bool(re.fullmatch(r"\d+\.\d+\.\d+", __version__)),
        __version__,
    ))

    try:
        load_config_file(root_path / "src" / "pyvncserver" / "default_config.toml")
        checks.append(ReleaseCheck("default-config", True, "valid"))
    except Exception as exc:
        checks.append(ReleaseCheck("default-config", False, str(exc)))

    pyproject = root_path / "pyproject.toml"
    checks.append(ReleaseCheck("pyproject", pyproject.is_file(), str(pyproject)))

    readme = root_path / "README.md"
    readme_ok = readme.is_file() and __version__ in readme.read_text(encoding="utf-8")
    checks.append(ReleaseCheck(
        "readme-version", readme_ok,
        f"README contains {__version__}" if readme_ok else f"README does not contain {__version__}",
    ))

    major, minor, *_ = __version__.split(".")
    notes = root_path / f"V{major}_{minor}_RELEASE_NOTES.md"
    checks.append(ReleaseCheck("release-notes", notes.is_file(), str(notes)))

    manifest = root_path / "MANIFEST.in"
    manifest_text = manifest.read_text(encoding="utf-8") if manifest.is_file() else ""
    checks.append(ReleaseCheck(
        "sdist-tests", "recursive-include tests *.py" in manifest_text,
        "tests included in source distribution",
    ))

    legacy_dir = root_path / "src" / "vnc_lib"
    checks.append(ReleaseCheck(
        "legacy-package-removed", not legacy_dir.exists(), str(legacy_dir)
    ))

    pytyped = root_path / "src" / "pyvncserver" / "py.typed"
    checks.append(ReleaseCheck("pep561-marker", pytyped.is_file(), str(pytyped)))

    architecture_script = root_path / "scripts" / "check_architecture.py"
    checks.append(ReleaseCheck(
        "architecture-checker", architecture_script.is_file(), str(architecture_script)
    ))

    if compile_sources:
        compile_ok = compileall.compile_dir(root_path / "src", quiet=2, force=True)
        checks.append(ReleaseCheck("compileall", bool(compile_ok), "src"))

    return ReleaseReport(__version__, str(root_path), tuple(checks))


def format_release_report(report: ReleaseReport) -> str:
    lines = [f"PyVNCServer {report.version} release check", f"Root: {report.root}", ""]
    for check in report.checks:
        lines.append(f"[{'OK' if check.ok else 'FAIL':4}] {check.name:18} {check.detail}")
    lines.extend(["", f"Result: {'PASS' if report.ok else 'FAIL'}"])
    return "\n".join(lines)
