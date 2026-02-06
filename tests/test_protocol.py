"""
Tests for RFB Protocol Implementation
Test RFC 6143 compliance and pattern matching
"""

import pytest
import struct
import socket
from unittest.mock import Mock, MagicMock
from vnc_lib.protocol import RFBProtocol


class MockSocket:
    """Mock socket for testing"""

    def __init__(self, data_to_receive=b''):
        self.data_to_receive = data_to_receive
        self.data_sent = bytearray()
        self.receive_offset = 0

    def sendall(self, data):
        """Mock sendall"""
        self.data_sent.extend(data)

    def recv(self, n):
        """Mock recv"""
        if self.receive_offset >= len(self.data_to_receive):
            return b''

        end = min(self.receive_offset + n, len(self.data_to_receive))
        data = self.data_to_receive[self.receive_offset:end]
        self.receive_offset = end
        return data

    def send(self, data):
        """Mock send"""
        self.data_sent.extend(data)
        return len(data)


class TestProtocolNegotiation:
    """Test protocol version negotiation"""

    def test_version_negotiation_003_008(self):
        """Test negotiation with RFB 003.008 client"""
        protocol = RFBProtocol()
        mock_socket = MockSocket(b"RFB 003.008\n")

        version = protocol.negotiate_version(mock_socket)

        assert version == (3, 8)
        assert mock_socket.data_sent == b"RFB 003.008\n"

    def test_version_negotiation_003_007(self):
        """Test negotiation with RFB 003.007 client"""
        protocol = RFBProtocol()
        mock_socket = MockSocket(b"RFB 003.007\n")

        version = protocol.negotiate_version(mock_socket)

        assert version == (3, 7)
        assert protocol.version == (3, 7)

    def test_version_negotiation_003_003(self):
        """Test negotiation with RFB 003.003 client"""
        protocol = RFBProtocol()
        mock_socket = MockSocket(b"RFB 003.003\n")

        version = protocol.negotiate_version(mock_socket)

        assert version == (3, 3)
        assert protocol.version == (3, 3)

    def test_version_negotiation_invalid(self):
        """Test negotiation with higher version (should negotiate down)"""
        protocol = RFBProtocol()
        mock_socket = MockSocket(b"RFB 999.999\n")

        # Should negotiate to our highest supported version
        major, minor = protocol.negotiate_version(mock_socket)
        assert (major, minor) in protocol.SUPPORTED_VERSIONS

    def test_version_negotiation_malformed(self):
        """Test negotiation with malformed version string"""
        protocol = RFBProtocol()
        # Must be exactly 12 bytes like RFB protocol expects
        mock_socket = MockSocket(b"NOTVRB 1.0\n\n")

        with pytest.raises(ValueError):
            protocol.negotiate_version(mock_socket)


class TestSecurityNegotiation:
    """Test security type negotiation"""

    def test_security_negotiation_none_v38(self):
        """Test no security with RFB 3.8"""
        protocol = RFBProtocol()
        protocol.version = (3, 8)
        mock_socket = MockSocket(struct.pack("B", 1))  # Client selects type 1

        sec_type, needs_auth = protocol.negotiate_security(mock_socket, password=None)

        assert sec_type == protocol.SECURITY_NONE
        assert needs_auth is False
        # Should send [1, 1] (count, type)
        assert mock_socket.data_sent[:2] == b'\x01\x01'

    def test_security_negotiation_vnc_auth_v38(self):
        """Test VNC auth with RFB 3.8"""
        protocol = RFBProtocol()
        protocol.version = (3, 8)
        mock_socket = MockSocket(struct.pack("B", 2))  # Client selects type 2

        sec_type, needs_auth = protocol.negotiate_security(mock_socket, password="test")

        assert sec_type == protocol.SECURITY_VNC_AUTH
        assert needs_auth is True

    def test_security_negotiation_v33(self):
        """Test security with RFB 3.3 (sends type directly)"""
        protocol = RFBProtocol()
        protocol.version = (3, 3)
        mock_socket = MockSocket()

        sec_type, needs_auth = protocol.negotiate_security(mock_socket, password="test")

        assert sec_type == protocol.SECURITY_VNC_AUTH
        # Should send 4-byte security type
        assert len(mock_socket.data_sent) == 4
        assert struct.unpack(">I", mock_socket.data_sent)[0] == 2

    def test_security_negotiation_unsupported_selection_fails(self):
        """Client selecting unsupported security type must fail hard."""
        protocol = RFBProtocol()
        protocol.version = (3, 8)
        mock_socket = MockSocket(struct.pack("B", 42))

        with pytest.raises(ConnectionError):
            protocol.negotiate_security(mock_socket, password="test")

        # Server should send [count, offered_type] and then failure result.
        assert mock_socket.data_sent[:2] == b'\x01\x02'
        assert struct.unpack(">I", mock_socket.data_sent[2:6])[0] == 1


class TestMessageParsing:
    """Test message parsing functions"""

    def test_parse_set_pixel_format(self):
        """Test parsing SetPixelFormat message"""
        protocol = RFBProtocol()

        # 3 bytes padding + 16 bytes pixel format
        pf_data = struct.pack(
            ">xxxBBBBHHHBBB3x",
            32,  # bits_per_pixel
            24,  # depth
            0,   # big_endian
            1,   # true_colour
            255, 255, 255,  # max values
            0, 8, 16  # shifts
        )

        mock_socket = MockSocket(pf_data)
        pixel_format = protocol.parse_set_pixel_format(mock_socket)

        assert pixel_format['bits_per_pixel'] == 32
        assert pixel_format['depth'] == 24
        assert pixel_format['true_colour_flag'] == 1

    def test_parse_set_encodings(self):
        """Test parsing SetEncodings with signed integers"""
        protocol = RFBProtocol()

        # 1 byte padding + 2 bytes count + encodings
        encodings_data = struct.pack(
            ">BH" + "i" * 4,  # Signed integers
            0,  # padding
            4,  # count
            0,  # Raw
            2,  # RRE
            -223,  # DesktopSize (negative!)
            16  # ZRLE
        )

        mock_socket = MockSocket(encodings_data)
        encodings = protocol.parse_set_encodings(mock_socket)

        assert 0 in encodings
        assert 2 in encodings
        assert -223 in encodings  # Pseudo-encoding
        assert 16 in encodings
        assert len(encodings) == 4

    def test_parse_set_encodings_rejects_too_many(self):
        """Reject oversized SetEncodings list to avoid resource abuse."""
        protocol = RFBProtocol(max_set_encodings=2)
        encodings_data = struct.pack(">BH" + "i" * 3, 0, 3, 0, 2, 16)
        mock_socket = MockSocket(encodings_data)

        with pytest.raises(ConnectionError):
            protocol.parse_set_encodings(mock_socket)

    def test_parse_framebuffer_update_request(self):
        """Test parsing FramebufferUpdateRequest"""
        protocol = RFBProtocol()

        request_data = struct.pack(
            ">BHHHH",
            1,  # incremental
            100, 200,  # x, y
            800, 600  # width, height
        )

        mock_socket = MockSocket(request_data)
        request = protocol.parse_framebuffer_update_request(mock_socket)

        assert request['incremental'] == 1
        assert request['x'] == 100
        assert request['y'] == 200
        assert request['width'] == 800
        assert request['height'] == 600

    def test_parse_key_event(self):
        """Test parsing KeyEvent message"""
        protocol = RFBProtocol()

        key_data = struct.pack(
            ">BHI",
            1,  # down_flag
            0,  # padding
            65  # key (ASCII 'A')
        )

        mock_socket = MockSocket(key_data)
        key_event = protocol.parse_key_event(mock_socket)

        assert key_event['down_flag'] == 1
        assert key_event['key'] == 65

    def test_parse_pointer_event(self):
        """Test parsing PointerEvent message"""
        protocol = RFBProtocol()

        pointer_data = struct.pack(
            ">BHH",
            1,  # button_mask (left button)
            500, 300  # x, y
        )

        mock_socket = MockSocket(pointer_data)
        pointer_event = protocol.parse_pointer_event(mock_socket)

        assert pointer_event['button_mask'] == 1
        assert pointer_event['x'] == 500
        assert pointer_event['y'] == 300

    def test_parse_client_cut_text(self):
        """Test parsing ClientCutText message"""
        protocol = RFBProtocol()

        text = "Hello VNC"
        text_bytes = text.encode('latin-1')
        cut_data = struct.pack(">xxxI", len(text_bytes)) + text_bytes

        mock_socket = MockSocket(cut_data)
        received_text = protocol.parse_client_cut_text(mock_socket)

        assert received_text == text

    def test_parse_client_cut_text_rejects_oversized_payload(self):
        """Reject oversized clipboard message before reading body."""
        protocol = RFBProtocol(max_client_cut_text=8)
        cut_data = struct.pack(">xxxI", 9) + b'123456789'
        mock_socket = MockSocket(cut_data)

        with pytest.raises(ConnectionError):
            protocol.parse_client_cut_text(mock_socket)


class TestMessageSending:
    """Test message sending functions"""

    def test_send_server_init(self):
        """Test sending ServerInit message"""
        protocol = RFBProtocol()
        mock_socket = MockSocket()

        pixel_format = {
            'bits_per_pixel': 32,
            'depth': 24,
            'big_endian_flag': 0,
            'true_colour_flag': 1,
            'red_max': 255,
            'green_max': 255,
            'blue_max': 255,
            'red_shift': 0,
            'green_shift': 8,
            'blue_shift': 16
        }

        protocol.send_server_init(
            mock_socket, 1920, 1080, pixel_format, "PyVNCServer"
        )

        # Check width and height (first 4 bytes)
        width, height = struct.unpack(">HH", mock_socket.data_sent[:4])
        assert width == 1920
        assert height == 1080

    def test_send_framebuffer_update(self):
        """Test sending FramebufferUpdate message"""
        protocol = RFBProtocol()
        mock_socket = MockSocket()

        rectangles = [
            (0, 0, 100, 100, 0, b'\x00' * 1000),  # Raw encoding
            (100, 100, 50, 50, 2, b'\x00' * 100),  # RRE encoding
        ]

        protocol.send_framebuffer_update(mock_socket, rectangles)

        # Check message type and rectangle count
        # Format: message type (B), padding (x - not returned), rectangle count (H)
        msg_type, rect_count = struct.unpack(">BxH", mock_socket.data_sent[:4])
        assert msg_type == protocol.MSG_FRAMEBUFFER_UPDATE
        assert rect_count == 2

    def test_send_security_result_success(self):
        """Test sending successful security result"""
        protocol = RFBProtocol()
        protocol.version = (3, 8)
        mock_socket = MockSocket()

        protocol.send_security_result(mock_socket, success=True)

        result = struct.unpack(">I", mock_socket.data_sent[:4])[0]
        assert result == 0

    def test_send_security_result_failure(self):
        """Test sending failed security result with reason"""
        protocol = RFBProtocol()
        protocol.version = (3, 8)
        mock_socket = MockSocket()

        protocol.send_security_result(mock_socket, success=False)

        result = struct.unpack(">I", mock_socket.data_sent[:4])[0]
        assert result == 1
        # Should include reason string
        assert len(mock_socket.data_sent) > 4


class TestHelperMethods:
    """Test helper methods"""

    def test_recv_exact(self):
        """Test receiving exactly n bytes"""
        protocol = RFBProtocol()
        mock_socket = MockSocket(b"Hello, World!")

        data = protocol._recv_exact(mock_socket, 5)
        assert data == b"Hello"

        data = protocol._recv_exact(mock_socket, 8)
        assert data == b", World!"

    def test_recv_exact_insufficient_data(self):
        """Test recv_exact with insufficient data"""
        protocol = RFBProtocol()
        mock_socket = MockSocket(b"Short")

        data = protocol._recv_exact(mock_socket, 100)
        assert data is None

    def test_find_common_version(self):
        """Test finding common protocol version"""
        protocol = RFBProtocol()

        # Exact match
        version = protocol._find_common_version(3, 8)
        assert version == (3, 8)

        # Lower version
        version = protocol._find_common_version(3, 7)
        assert version == (3, 7)

        # Unsupported version
        version = protocol._find_common_version(2, 0)
        assert version is None

    def test_send_large_data(self):
        """Test sending large data in chunks"""
        protocol = RFBProtocol()
        mock_socket = MockSocket()

        large_data = b'X' * 100000  # 100KB

        protocol._send_large_data(mock_socket, large_data, chunk_size=10000)

        assert bytes(mock_socket.data_sent) == large_data


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
