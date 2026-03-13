"""
VNC Authentication - RFC 6143 Section 7.2.2
Implements proper DES-based VNC authentication
"""

import os
import logging
from typing import Optional

try:
    from Crypto.Cipher import DES
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logging.warning("pycryptodome not available - VNC authentication will not work")


class VNCAuth:
    """Handles VNC authentication using DES encryption per RFC 6143"""

    CHALLENGE_SIZE = 16

    def __init__(self, password: str, read_only_password: str = ""):
        """
        Initialize VNC authentication

        Args:
            password: VNC password (max 8 characters, per RFC)
        """
        self.password = password
        self.read_only_password = read_only_password
        self.logger = logging.getLogger(__name__)

        if not CRYPTO_AVAILABLE:
            raise ImportError("pycryptodome is required for VNC authentication. "
                            "Install it with: pip install pycryptodome")

    def authenticate(self, client_socket) -> bool:
        """Backward-compatible boolean result."""
        success, _ = self.authenticate_with_access(client_socket)
        return success

    def authenticate_with_access(self, client_socket) -> tuple[bool, bool]:
        """
        Perform VNC authentication challenge-response

        RFC 6143 Section 7.2.2:
        1. Server sends 16-byte random challenge
        2. Client encrypts challenge with DES using password as key
        3. Server verifies the response

        Returns:
            tuple[success, view_only]
        """
        try:
            # Generate random challenge
            challenge = os.urandom(self.CHALLENGE_SIZE)
            self.logger.debug(f"Generated challenge: {challenge.hex()}")

            # Send challenge to client
            client_socket.sendall(challenge)

            # Receive encrypted response
            response = self._recv_exact(client_socket, self.CHALLENGE_SIZE)
            if not response:
                self.logger.warning("Failed to receive authentication response")
                return False, False

            self.logger.debug(f"Received response: {response.hex()}")

            if self._response_matches_password(challenge, response, self.password):
                self.logger.info("VNC authentication successful")
                return True, False

            if self.read_only_password and self._response_matches_password(
                challenge, response, self.read_only_password
            ):
                self.logger.info("VNC authentication successful (read-only)")
                return True, True

            self.logger.warning("VNC authentication failed - incorrect password")
            return False, False

        except Exception as e:
            self.logger.error(f"Authentication error: {e}")
            return False, False

    def _response_matches_password(
        self, challenge: bytes, response: bytes, password: str
    ) -> bool:
        expected_response = self._encrypt_challenge(challenge, password=password)
        self.logger.debug(f"Expected response: {expected_response.hex()}")
        return response == expected_response

    def _encrypt_challenge(self, challenge: bytes, password: str | None = None) -> bytes:
        """
        Encrypt challenge using VNC's DES algorithm

        VNC uses DES in ECB mode with a quirk: the password bits are reversed.
        This is a historical artifact of the original VNC implementation.
        """
        # Prepare password key (max 8 bytes, pad with nulls)
        effective_password = self.password if password is None else password
        key = (effective_password[:8] + '\x00' * 8)[:8].encode('latin-1')

        # VNC quirk: reverse the bits in each byte of the key
        key = bytes([self._reverse_bits(b) for b in key])

        # Encrypt using DES in ECB mode
        cipher = DES.new(key, DES.MODE_ECB)

        # Encrypt the challenge (16 bytes = two 8-byte DES blocks)
        encrypted = cipher.encrypt(challenge)

        return encrypted

    @staticmethod
    def _reverse_bits(byte: int) -> int:
        """
        Reverse the bits in a byte

        This is required for VNC authentication due to historical reasons.
        VNC uses a non-standard bit ordering for the DES key.
        """
        result = 0
        for i in range(8):
            if byte & (1 << i):
                result |= (1 << (7 - i))
        return result

    def _recv_exact(self, sock, n: int) -> Optional[bytes]:
        """Receive exactly n bytes from socket"""
        if n == 0:
            return b''

        buf = bytearray(n)
        view = memoryview(buf)
        total_received = 0
        while total_received < n:
            chunk = sock.recv(n - total_received)
            if not chunk:
                return None
            chunk_len = len(chunk)
            view[total_received:total_received + chunk_len] = chunk
            total_received += chunk_len
        return bytes(buf)


class NoAuth:
    """No authentication - for development/testing only"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def authenticate(self, client_socket) -> bool:
        """No authentication required"""
        self.logger.info("No authentication (security type 1)")
        return True
