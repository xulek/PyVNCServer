"""
VNC Authentication - RFC 6143 Section 7.2.2
Implements proper DES-based VNC authentication
"""

import os
import struct
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

    def __init__(self, password: str):
        """
        Initialize VNC authentication

        Args:
            password: VNC password (max 8 characters, per RFC)
        """
        self.password = password
        self.logger = logging.getLogger(__name__)

        if not CRYPTO_AVAILABLE:
            raise ImportError("pycryptodome is required for VNC authentication. "
                            "Install it with: pip install pycryptodome")

    def authenticate(self, client_socket) -> bool:
        """
        Perform VNC authentication challenge-response

        RFC 6143 Section 7.2.2:
        1. Server sends 16-byte random challenge
        2. Client encrypts challenge with DES using password as key
        3. Server verifies the response

        Returns: True if authentication successful
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
                return False

            self.logger.debug(f"Received response: {response.hex()}")

            # Verify response
            expected_response = self._encrypt_challenge(challenge)
            self.logger.debug(f"Expected response: {expected_response.hex()}")

            if response == expected_response:
                self.logger.info("VNC authentication successful")
                return True
            else:
                self.logger.warning("VNC authentication failed - incorrect password")
                return False

        except Exception as e:
            self.logger.error(f"Authentication error: {e}")
            return False

    def _encrypt_challenge(self, challenge: bytes) -> bytes:
        """
        Encrypt challenge using VNC's DES algorithm

        VNC uses DES in ECB mode with a quirk: the password bits are reversed.
        This is a historical artifact of the original VNC implementation.
        """
        # Prepare password key (max 8 bytes, pad with nulls)
        key = (self.password[:8] + '\x00' * 8)[:8].encode('latin-1')

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
        buf = b''
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf


class NoAuth:
    """No authentication - for development/testing only"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def authenticate(self, client_socket) -> bool:
        """No authentication required"""
        self.logger.info("No authentication (security type 1)")
        return True
