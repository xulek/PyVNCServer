#!/usr/bin/env python3
"""
RFC 6143 Compliant VNC Server
A fully RFC-compliant VNC server implementation in Python
"""

import socket
import threading
import time
import logging
import json
from typing import Optional, Dict, Set

from vnc_lib.protocol import RFBProtocol
from vnc_lib.auth import VNCAuth, NoAuth
from vnc_lib.input_handler import InputHandler
from vnc_lib.screen_capture import ScreenCapture


class VNCServer:
    """RFC 6143 compliant VNC Server"""

    DEFAULT_PORT = 5900
    DEFAULT_HOST = '0.0.0.0'
    DEFAULT_FRAME_RATE = 30
    DEFAULT_SCALE_FACTOR = 1.0

    def __init__(self, config_file: str = "config.json"):
        """Initialize VNC Server with configuration"""
        self.logger = logging.getLogger(__name__)

        # Load configuration
        self.config = self._load_config(config_file)

        # Setup logging
        log_level = self.config.get('log_level', 'INFO').upper()
        try:
            logging.getLogger().setLevel(getattr(logging, log_level))
        except AttributeError:
            logging.getLogger().setLevel(logging.INFO)
            self.logger.warning(f"Invalid log level '{log_level}', using INFO")

        # Server configuration
        self.host = self.config.get('host', self.DEFAULT_HOST)
        self.port = self.config.get('port', self.DEFAULT_PORT)
        self.password = self.config.get('password', '')
        self.frame_rate = max(1, min(60, self.config.get('frame_rate', self.DEFAULT_FRAME_RATE)))
        self.scale_factor = self.config.get('scale_factor', self.DEFAULT_SCALE_FACTOR)

        # Create server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)

        self.logger.info(f"VNC Server listening on {self.host}:{self.port}")
        self.logger.info(f"Frame rate: {self.frame_rate} FPS, Scale factor: {self.scale_factor}")

    def _load_config(self, config_file: str) -> Dict:
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                logging.info(f"Configuration loaded from {config_file}")
                return config
        except FileNotFoundError:
            logging.warning(f"Configuration file {config_file} not found, using defaults")
            return {}
        except Exception as e:
            logging.error(f"Error loading configuration: {e}, using defaults")
            return {}

    def start(self):
        """Start accepting client connections"""
        self.logger.info("VNC Server started")
        try:
            while True:
                client_socket, addr = self.server_socket.accept()
                self.logger.info(f"New connection from {addr}")
                thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, addr),
                    daemon=True
                )
                thread.start()
        except KeyboardInterrupt:
            self.logger.info("Server shutting down...")
        finally:
            self.server_socket.close()
            self.logger.info("Server stopped")

    def handle_client(self, client_socket: socket.socket, addr):
        """Handle a single client connection"""
        try:
            # Initialize protocol handler
            protocol = RFBProtocol()

            # Step 1: Protocol Version Handshake (RFC 6143 Section 7.1.1)
            protocol.negotiate_version(client_socket)

            # Step 2: Security Handshake (RFC 6143 Section 7.1.2)
            security_type, needs_auth = protocol.negotiate_security(
                client_socket, self.password
            )

            # Step 3: Authentication (if required)
            if needs_auth:
                auth_handler = VNCAuth(self.password)
                auth_success = auth_handler.authenticate(client_socket)
                protocol.send_security_result(client_socket, auth_success)

                if not auth_success:
                    self.logger.warning(f"Client {addr} authentication failed")
                    client_socket.close()
                    return
            else:
                # For RFB 003.008+, send security result even for "None" security
                if protocol.version >= (3, 8):
                    protocol.send_security_result(client_socket, True)

            self.logger.info(f"Client {addr} authenticated successfully")

            # Step 4: ClientInit (RFC 6143 Section 7.3.1)
            shared_flag = protocol.receive_client_init(client_socket)
            self.logger.debug(f"Client shared flag: {shared_flag}")

            # Step 5: ServerInit (RFC 6143 Section 7.3.2)
            # Initialize screen capture and input handler
            screen_capture = ScreenCapture(scale_factor=self.scale_factor)
            input_handler = InputHandler(scale_factor=self.scale_factor)

            # Get initial screen dimensions
            initial_capture, _, width, height = screen_capture.capture({
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
            })

            # Default pixel format (32-bit RGBA)
            current_pixel_format = {
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
                client_socket, width, height,
                current_pixel_format, "Python VNC Server"
            )

            # Track client encodings
            client_encodings: Set[int] = set()

            # Main message loop
            self._client_message_loop(
                client_socket, protocol, screen_capture,
                input_handler, current_pixel_format,
                client_encodings, width, height
            )

        except Exception as e:
            self.logger.error(f"Error handling client {addr}: {e}", exc_info=True)
        finally:
            client_socket.close()
            self.logger.info(f"Client {addr} disconnected")

    def _client_message_loop(self, client_socket: socket.socket,
                            protocol: RFBProtocol,
                            screen_capture: ScreenCapture,
                            input_handler: InputHandler,
                            current_pixel_format: Dict,
                            client_encodings: Set[int],
                            fb_width: int, fb_height: int):
        """Main client message handling loop"""
        last_frame_time = time.time()

        while True:
            try:
                # Receive message type
                msg_type_data = protocol._recv_exact(client_socket, 1)
                if not msg_type_data:
                    break

                msg_type = msg_type_data[0]

                # Handle different message types
                if msg_type == protocol.MSG_SET_PIXEL_FORMAT:
                    # SetPixelFormat (RFC 6143 Section 7.5.1)
                    new_format = protocol.parse_set_pixel_format(client_socket)
                    current_pixel_format.update(new_format)
                    self.logger.info(f"Pixel format updated: {new_format}")

                elif msg_type == protocol.MSG_SET_ENCODINGS:
                    # SetEncodings (RFC 6143 Section 7.5.2)
                    encodings = protocol.parse_set_encodings(client_socket)
                    client_encodings.clear()
                    client_encodings.update(encodings)
                    self.logger.info(f"Client encodings: {client_encodings}")

                elif msg_type == protocol.MSG_FRAMEBUFFER_UPDATE_REQUEST:
                    # FramebufferUpdateRequest (RFC 6143 Section 7.5.3)
                    request = protocol.parse_framebuffer_update_request(client_socket)

                    # Throttle frame rate
                    current_time = time.time()
                    time_elapsed = current_time - last_frame_time
                    if time_elapsed < 1.0 / self.frame_rate:
                        time.sleep(1.0 / self.frame_rate - time_elapsed)

                    # Capture screen
                    pixel_data, checksum, cap_width, cap_height = screen_capture.capture(
                        current_pixel_format
                    )

                    if pixel_data is None:
                        continue

                    # Check if screen changed (for incremental updates)
                    if request['incremental'] and not screen_capture.has_changed(checksum):
                        # No change, send empty update
                        protocol.send_framebuffer_update(client_socket, [])
                        continue

                    screen_capture.update_checksum(checksum)

                    # Update dimensions if they changed
                    if cap_width != fb_width or cap_height != fb_height:
                        fb_width, fb_height = cap_width, cap_height
                        self.logger.info(f"Framebuffer size changed to {fb_width}x{fb_height}")

                        # Send DesktopSize pseudo-encoding if supported
                        if protocol.ENCODING_DESKTOP_SIZE in client_encodings:
                            protocol.send_framebuffer_update(client_socket, [
                                (0, 0, fb_width, fb_height, protocol.ENCODING_DESKTOP_SIZE, None)
                            ])
                            continue

                    # Send framebuffer update (Raw encoding)
                    # Note: We only support Raw encoding for now
                    bytes_per_pixel = current_pixel_format['bits_per_pixel'] // 8
                    expected_size = fb_width * fb_height * bytes_per_pixel

                    # Ensure we have the right amount of data
                    if len(pixel_data) >= expected_size:
                        pixel_data = pixel_data[:expected_size]
                    else:
                        self.logger.warning(f"Pixel data size mismatch: {len(pixel_data)} < {expected_size}")
                        continue

                    rectangles = [
                        (0, 0, fb_width, fb_height, protocol.ENCODING_RAW, pixel_data)
                    ]
                    protocol.send_framebuffer_update(client_socket, rectangles)

                    last_frame_time = time.time()

                elif msg_type == protocol.MSG_KEY_EVENT:
                    # KeyEvent (RFC 6143 Section 7.5.4)
                    key_event = protocol.parse_key_event(client_socket)
                    input_handler.handle_key_event(
                        key_event['down_flag'],
                        key_event['key']
                    )

                elif msg_type == protocol.MSG_POINTER_EVENT:
                    # PointerEvent (RFC 6143 Section 7.5.5)
                    pointer_event = protocol.parse_pointer_event(client_socket)
                    input_handler.handle_pointer_event(
                        pointer_event['button_mask'],
                        pointer_event['x'],
                        pointer_event['y']
                    )

                elif msg_type == protocol.MSG_CLIENT_CUT_TEXT:
                    # ClientCutText (RFC 6143 Section 7.5.6)
                    text = protocol.parse_client_cut_text(client_socket)
                    self.logger.info(f"Client cut text: {text[:50]}...")

                else:
                    self.logger.warning(f"Unknown message type: {msg_type}")
                    break

            except Exception as e:
                self.logger.error(f"Error in message loop: {e}")
                break


def main():
    """Main entry point"""
    # Setup basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create and start server
    server = VNCServer()
    server.start()


if __name__ == '__main__':
    main()
