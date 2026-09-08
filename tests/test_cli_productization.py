from __future__ import annotations

import json
from pathlib import Path

from pyvncserver.cli import build_parser, main
from pyvncserver.diagnostics import DoctorReport, DiagnosticCheck, format_doctor_report


def test_cli_exposes_productization_commands():
    parser = build_parser()
    assert parser.parse_args(["doctor"]).command == "doctor"
    assert parser.parse_args(["info"]).command == "info"
    assert parser.parse_args(["config", "validate"]).config_command == "validate"
    assert parser.parse_args(["benchmark"]).command == "benchmark"


def test_config_init_and_validate(tmp_path, capsys):
    target = tmp_path / "server.toml"
    assert main(["config", "init", str(target)]) == 0
    assert target.is_file()
    capsys.readouterr()
    assert main(["config", "validate", str(target), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["port"] == 5900


def test_config_init_refuses_overwrite(tmp_path):
    target = tmp_path / "server.toml"
    target.write_text("existing", encoding="utf-8")
    assert main(["config", "init", str(target)]) == 2
    assert target.read_text(encoding="utf-8") == "existing"


def test_doctor_formatter_marks_required_failures():
    report = DoctorReport(
        version="3.7.0",
        platform="test",
        python="3.13",
        config_path="x.toml",
        checks=(DiagnosticCheck("config", False, "bad"),),
    )
    assert report.ok is False
    assert "FAIL" in format_doctor_report(report)


def test_release_check_command_is_available():
    parser = build_parser()
    args = parser.parse_args(["release", "check"])
    assert args.command == "release"
    assert args.release_command == "check"
