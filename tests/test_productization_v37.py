from __future__ import annotations

import socket
import struct

import pytest

from pyvncserver.config import ServerSettings
from pyvncserver._core.exceptions import ConfigurationError
from pyvncserver._core.protocol import RFBProtocol


def test_clipboard_settings_round_trip_mapping():
    settings = ServerSettings.from_mapping({
        'host': '127.0.0.1',
        'clipboard_enabled': True,
        'clipboard_direction': 'client-to-server',
        'clipboard_max_bytes': 4096,
        'clipboard_encoding': 'utf-8',
    })
    assert settings.clipboard.direction == 'client-to-server'
    assert settings.clipboard.max_bytes == 4096
    assert settings.clipboard.encoding == 'utf-8'
    flat = settings.to_dict()
    assert flat['clipboard_max_bytes'] == 4096


@pytest.mark.parametrize('direction', ['sideways', '', 'client'])
def test_invalid_clipboard_direction_is_rejected(direction):
    with pytest.raises(ConfigurationError):
        ServerSettings.from_mapping({
            'host': '127.0.0.1',
            'clipboard_direction': direction,
        })


def test_invalid_clipboard_encoding_is_rejected():
    with pytest.raises(ConfigurationError):
        ServerSettings.from_mapping({
            'host': '127.0.0.1',
            'clipboard_encoding': 'utf-16',
        })


def test_utf8_client_cut_text_protocol_round_trip():
    left, right = socket.socketpair()
    try:
        protocol = RFBProtocol(max_client_cut_text=1024, clipboard_encoding='utf-8')
        text = 'zażółć gęślą jaźń'
        payload = text.encode('utf-8')
        right.sendall(b'\x00\x00\x00' + struct.pack('>I', len(payload)) + payload)
        assert protocol.parse_client_cut_text(left) == text
    finally:
        left.close()
        right.close()


def test_utf8_server_cut_text_protocol_round_trip():
    left, right = socket.socketpair()
    try:
        protocol = RFBProtocol(clipboard_encoding='utf-8')
        protocol.send_server_cut_text(left, 'gęślą')
        header = right.recv(8)
        assert header[0] == protocol.MSG_SERVER_CUT_TEXT
        length = struct.unpack('>I', header[4:8])[0]
        assert right.recv(length).decode('utf-8') == 'gęślą'
    finally:
        left.close()
        right.close()


def test_invalid_observability_port_is_rejected():
    with pytest.raises(ConfigurationError):
        ServerSettings.from_mapping({
            'host': '127.0.0.1',
            'observability_prometheus_enabled': True,
            'observability_prometheus_port': 70000,
        })
