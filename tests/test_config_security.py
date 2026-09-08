"""Security-focused configuration validation tests."""

from pathlib import Path

import pytest

from pyvncserver.config import ServerSettings, load_config_file
from vnc_lib.exceptions import ConfigurationError


def test_missing_config_fails_closed(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config_file(tmp_path / "missing.toml")


def test_malformed_config_fails_closed(tmp_path: Path):
    path = tmp_path / "broken.toml"
    path.write_text("[server\nhost = '127.0.0.1'", encoding="utf-8")

    with pytest.raises(Exception):
        load_config_file(path)


def test_non_loopback_no_auth_is_rejected_by_default():
    with pytest.raises(ConfigurationError, match="unauthenticated"):
        ServerSettings.from_mapping({"host": "0.0.0.0", "password": ""})


def test_non_loopback_no_auth_can_only_be_explicitly_opted_in():
    settings = ServerSettings.from_mapping({
        "host": "0.0.0.0",
        "password": "",
        "allow_insecure_no_auth": True,
    })

    assert settings.host == "0.0.0.0"
    assert settings.security.allow_insecure_no_auth is True


def test_classic_vnc_password_over_eight_bytes_is_rejected():
    with pytest.raises(ConfigurationError, match="8 bytes"):
        ServerSettings.from_mapping({"password": "123456789"})


def test_primary_and_read_only_passwords_must_differ():
    with pytest.raises(ConfigurationError, match="must be different"):
        ServerSettings.from_mapping({
            "password": "secret",
            "read_only_password": "secret",
        })


def test_auto_network_profile_is_normalized_to_none():
    settings = ServerSettings.from_mapping({"network_profile_override": "auto"})
    assert settings.network_profile_override is None


def test_adaptive_section_is_flattened_into_runtime_keys(tmp_path: Path):
    path = tmp_path / "adaptive.toml"
    path.write_text(
        """
[server]
host = "127.0.0.1"
port = 5900

[adaptive]
enabled = true
min_fps = 17
cache_enabled = false
merge_gap_px = 20
""",
        encoding="utf-8",
    )

    config = load_config_file(path)
    assert config["adaptive_enabled"] is True
    assert config["adaptive_min_fps"] == 17
    assert config["adaptive_cache_enabled"] is False
    assert config["adaptive_merge_gap_px"] == 20
