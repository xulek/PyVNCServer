from pathlib import Path

from pyvncserver import DEFAULT_CONFIG_PATH, VNCServer, VNCServerV3, load_config_file
from pyvncserver.cli import build_parser
from pyvncserver.features.websocket import WebSocketWrapper
from pyvncserver.platform.capture import ScreenCapture
from pyvncserver.rfb.protocol import RFBProtocol
from pyvncserver.runtime.network import NetworkProfile


def test_packaged_exports_are_available():
    assert VNCServer is VNCServerV3
    assert RFBProtocol is not None
    assert ScreenCapture is not None
    assert WebSocketWrapper is not None
    assert NetworkProfile.LAN.value == "lan"


def test_default_toml_config_loads():
    config = load_config_file(DEFAULT_CONFIG_PATH)

    assert config["host"] == "0.0.0.0"
    assert config["port"] == 5900
    assert config["enable_tight_encoding"] is True
    assert config["encoding_threads"] is None
    assert config["log_file"] is None


def test_json_config_is_not_supported_anymore(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text("{}", encoding="utf-8")

    try:
        load_config_file(legacy)
    except ValueError as exc:
        assert "Unsupported config format" in str(exc)
    else:
        raise AssertionError("JSON config should no longer be supported")


def test_cli_parser_defaults_to_packaged_config():
    parser = build_parser()
    args = parser.parse_args(["serve"])

    assert Path(args.config).as_posix() == DEFAULT_CONFIG_PATH.as_posix()
    assert args.log_level is None
