#!/usr/bin/env python3
"""
RFC 6143 Compliant VNC Server - Enhanced Version 3.0
Python 3.13 compatible with modern features and optimizations
"""

import socket
import threading
import time
import logging
import json
from pathlib import Path

from vnc_lib.protocol import RFBProtocol
from vnc_lib.auth import VNCAuth, NoAuth
from vnc_lib.input_handler import InputHandler
from vnc_lib.screen_capture import ScreenCapture
from vnc_lib.encodings import EncoderManager
from vnc_lib.change_detector import AdaptiveChangeDetector
from vnc_lib.cursor import CursorEncoder
from vnc_lib.metrics import ServerMetrics, ConnectionMetrics, PerformanceMonitor
from vnc_lib.server_utils import (
    GracefulShutdown, HealthChecker, ConnectionPool, PerformanceThrottler
)
from vnc_lib.exceptions import (
    VNCError, ProtocolError, AuthenticationError, ConnectionError,
    MultiClientError, ExceptionCollector, categorize_exceptions
)


class VNCServerV3:
    """
    RFC 6143 compliant VNC Server - Enhanced Version 3.0

    New features:
    - Multiple encoding support (Raw, RRE, Hextile, ZRLE)
    - Region-based change detection
    - Performance metrics and monitoring
    - Graceful shutdown handling
    - Connection pooling
    - Cursor pseudo-encoding support
    - Health checks
    - Python 3.13 type hints
    """

    DEFAULT_PORT = 5900
    DEFAULT_HOST = '0.0.0.0'
    DEFAULT_FRAME_RATE = 30
    DEFAULT_SCALE_FACTOR = 1.0
    MAX_CONNECTIONS = 10

    def __init__(self, config_file: str = "config.json"):
        """Initialize enhanced VNC Server with configuration"""
        self.logger = logging.getLogger(__name__)

        # Load configuration
        self.config = self._load_config(config_file)

        # Setup logging
        self._setup_logging()

        # Server configuration
        self.host = self.config.get('host', self.DEFAULT_HOST)
        self.port = self.config.get('port', self.DEFAULT_PORT)
        self.password = self.config.get('password', '')
        self.frame_rate = max(1, min(60, self.config.get('frame_rate', self.DEFAULT_FRAME_RATE)))
        self.scale_factor = self.config.get('scale_factor', self.DEFAULT_SCALE_FACTOR)
        self.max_connections = self.config.get('max_connections', self.MAX_CONNECTIONS)

        # Features
        self.enable_region_detection = self.config.get('enable_region_detection', True)
        self.enable_cursor_encoding = self.config.get('enable_cursor_encoding', False)
        self.enable_metrics = self.config.get('enable_metrics', True)

        # Server components
        self.shutdown_handler = GracefulShutdown()
        self.connection_pool = ConnectionPool(max_connections=self.max_connections)
        self.metrics = ServerMetrics.get_instance() if self.enable_metrics else None
        self.health_checker = HealthChecker(check_interval=30.0)

        # Register health checks
        self._setup_health_checks()

        # Create server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.settimeout(1.0)  # For shutdown responsiveness

        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
        except OSError as e:
            self.logger.error(f"Failed to bind to {self.host}:{self.port}: {e}")
            raise

        # Register cleanup
        self.shutdown_handler.register_cleanup(self._cleanup)

        self.logger.info(f"VNC Server v3.0 listening on {self.host}:{self.port}")
        self.logger.info(f"Frame rate: {self.frame_rate} FPS, Scale: {self.scale_factor}")
        self.logger.info(f"Max connections: {self.max_connections}")
        self.logger.info(f"Features: region_detection={self.enable_region_detection}, "
                        f"cursor={self.enable_cursor_encoding}, metrics={self.enable_metrics}")

    def _load_config(self, config_file: str) -> dict:
        """Load configuration from JSON file"""
        try:
            config_path = Path(config_file)
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    logging.info(f"Configuration loaded from {config_file}")
                    return config
            else:
                logging.warning(f"Configuration file {config_file} not found, using defaults")
                return {}
        except Exception as e:
            logging.error(f"Error loading configuration: {e}, using defaults")
            return {}

    def _setup_logging(self):
        """Setup enhanced logging"""
        log_level = self.config.get('log_level', 'INFO').upper()
        try:
            level = getattr(logging, log_level)
        except AttributeError:
            level = logging.INFO
            self.logger.warning(f"Invalid log level '{log_level}', using INFO")

        logging.getLogger().setLevel(level)

        # Add file logging if configured
        log_file = self.config.get('log_file')
        if log_file:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            logging.getLogger().addHandler(handler)

    def _setup_health_checks(self):
        """Setup health check functions"""
        def check_socket() -> bool:
            """Check if server socket is healthy"""
            try:
                return self.server_socket.fileno() != -1
            except:
                return False

        def check_connections() -> bool:
            """Check if connection pool is not overloaded"""
            return not self.connection_pool.is_full()

        self.health_checker.register_check('socket', check_socket)
        self.health_checker.register_check('connections', check_connections)

    def start(self):
        """Start accepting client connections"""
        self.logger.info("VNC Server v3.0 started")

        # Start health checker
        if self.enable_metrics:
            self.health_checker.start()

        try:
            while not self.shutdown_handler.is_shutting_down():
                try:
                    # Accept with timeout for shutdown responsiveness
                    client_socket, addr = self.server_socket.accept()

                    # Check if we can accept more connections
                    client_id = f"{addr[0]}:{addr[1]}"

                    if not self.connection_pool.acquire(client_id, timeout=0.1):
                        self.logger.warning(f"Connection pool full, rejecting {addr}")
                        client_socket.close()
                        continue

                    self.logger.info(f"New connection from {addr}")

                    # Handle in separate thread
                    thread = threading.Thread(
                        target=self._handle_client_wrapper,
                        args=(client_socket, addr, client_id),
                        name=f"Client-{client_id}",
                        daemon=True
                    )
                    thread.start()

                except socket.timeout:
                    # Normal timeout, check for shutdown
                    continue
                except OSError as e:
                    if self.shutdown_handler.is_shutting_down():
                        break
                    self.logger.error(f"Socket error: {e}")
                    time.sleep(0.1)

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        finally:
            self.shutdown_handler.shutdown()
            self.logger.info("Server stopped")

    def _handle_client_wrapper(self, client_socket: socket.socket,
                               addr: tuple, client_id: str):
        """Wrapper for client handling with cleanup"""
        try:
            self.handle_client(client_socket, addr, client_id)
        finally:
            self.connection_pool.release(client_id)

    def handle_client(self, client_socket: socket.socket,
                     addr: tuple, client_id: str):
        """Handle a single client connection"""
        conn_metrics: ConnectionMetrics | None = None

        try:
            # Detect localhost connection for performance optimization
            is_localhost = addr[0] in ('127.0.0.1', '::1', 'localhost')
            if is_localhost:
                self.logger.info(f"Localhost connection detected - using optimized fast path")
                # Enable TCP_NODELAY for localhost (disable Nagle's algorithm for lower latency)
                try:
                    client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception as e:
                    self.logger.warning(f"Could not set TCP_NODELAY: {e}")

            # Register connection metrics
            if self.metrics:
                conn_metrics = self.metrics.register_connection(client_id)

            # Initialize protocol handler
            protocol = RFBProtocol()

            # Step 1: Protocol Version Handshake
            with PerformanceMonitor("Version negotiation", self.logger):
                protocol.negotiate_version(client_socket)

            # Step 2: Security Handshake
            with PerformanceMonitor("Security negotiation", self.logger):
                security_type, needs_auth = protocol.negotiate_security(
                    client_socket, self.password
                )

            # Step 3: Authentication
            if needs_auth:
                auth_handler = VNCAuth(self.password)
                auth_success = auth_handler.authenticate(client_socket)
                protocol.send_security_result(client_socket, auth_success)

                if not auth_success:
                    self.logger.warning(f"Client {addr} authentication failed")
                    if self.metrics:
                        self.metrics.record_failed_auth()
                    return
            else:
                if protocol.version >= (3, 8):
                    protocol.send_security_result(client_socket, True)

            self.logger.info(f"Client {addr} authenticated successfully")

            # Step 4: ClientInit
            shared_flag = protocol.receive_client_init(client_socket)
            self.logger.debug(f"Client shared flag: {shared_flag}")

            # Step 5: ServerInit
            screen_capture = ScreenCapture(scale_factor=self.scale_factor)
            input_handler = InputHandler(scale_factor=self.scale_factor)

            # Get initial screen dimensions
            initial_result = screen_capture.capture_fast({
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

            width, height = initial_result.width, initial_result.height

            # Default pixel format
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
                current_pixel_format, "Python VNC Server v3.0"
            )

            # Initialize encoders and change detection
            encoder_manager = EncoderManager()
            client_encodings: set[int] = {0}  # Default: Raw encoding

            # For localhost, disable change detection (overhead not worth it with high bandwidth)
            use_change_detection = self.enable_region_detection and not is_localhost
            change_detector = AdaptiveChangeDetector(width, height) if use_change_detection else None
            cursor_encoder = CursorEncoder() if self.enable_cursor_encoding else None

            if is_localhost and self.enable_region_detection:
                self.logger.info("Change detection disabled for localhost connection (optimization)")

            # Main message loop
            self._client_message_loop(
                client_socket, protocol, screen_capture, input_handler,
                current_pixel_format, client_encodings, width, height,
                encoder_manager, change_detector, cursor_encoder, conn_metrics, is_localhost
            )

        except Exception as e:
            self.logger.error(f"Error handling client {addr}: {e}", exc_info=True)
            if conn_metrics:
                conn_metrics.record_error()
        finally:
            client_socket.close()
            if self.metrics:
                self.metrics.unregister_connection(client_id)
            self.logger.info(f"Client {addr} disconnected")

    def _client_message_loop(self, client_socket: socket.socket,
                            protocol: RFBProtocol,
                            screen_capture: ScreenCapture,
                            input_handler: InputHandler,
                            current_pixel_format: dict,
                            client_encodings: set[int],
                            fb_width: int, fb_height: int,
                            encoder_manager: EncoderManager,
                            change_detector: AdaptiveChangeDetector | None,
                            cursor_encoder: CursorEncoder | None,
                            conn_metrics: ConnectionMetrics | None,
                            is_localhost: bool = False):
        """
        Enhanced client message handling loop with localhost optimization

        Localhost optimizations:
        - No frame rate limiting (max throughput)
        - Raw encoding only (no compression overhead)
        - TCP_NODELAY enabled (lower latency)
        - Change detection disabled (unnecessary overhead)
        """

        # For localhost, allow higher frame rates (up to 120 FPS), otherwise use configured rate
        max_frame_rate = 120 if is_localhost else self.frame_rate
        throttler = PerformanceThrottler(max_rate=max_frame_rate)
        last_frame_time = time.time()

        while not self.shutdown_handler.is_shutting_down():
            try:
                # Receive message type
                msg_type_data = protocol._recv_exact(client_socket, 1)
                if not msg_type_data:
                    break

                msg_type = msg_type_data[0]

                # Handle different message types using Python 3.13 pattern matching
                match msg_type:
                    case protocol.MSG_SET_PIXEL_FORMAT:
                        new_format = protocol.parse_set_pixel_format(client_socket)
                        current_pixel_format.update(new_format)
                        self.logger.info(f"Pixel format updated: {new_format}")

                    case protocol.MSG_SET_ENCODINGS:
                        encodings = protocol.parse_set_encodings(client_socket)
                        client_encodings.clear()
                        client_encodings.update(encodings)
                        self.logger.info(f"Client encodings: {client_encodings}")

                    case protocol.MSG_FRAMEBUFFER_UPDATE_REQUEST:
                        request = protocol.parse_framebuffer_update_request(client_socket)

                        # Throttle frame rate
                        throttler.throttle()

                        # Capture screen
                        start_time = time.perf_counter()
                        result = screen_capture.capture_fast(current_pixel_format)

                        if result.pixel_data is None:
                            continue

                        # Handle dimension changes
                        if result.width != fb_width or result.height != fb_height:
                            fb_width, fb_height = result.width, result.height
                            self.logger.info(f"Framebuffer size changed to {fb_width}x{fb_height}")

                            if change_detector:
                                change_detector.resize(fb_width, fb_height)

                            # Send DesktopSize if supported
                            if protocol.ENCODING_DESKTOP_SIZE in client_encodings:
                                protocol.send_framebuffer_update(client_socket, [
                                    (0, 0, fb_width, fb_height, protocol.ENCODING_DESKTOP_SIZE, None)
                                ])
                                continue

                        # Check for changes (incremental update)
                        if request['incremental'] and change_detector:
                            changed_regions = change_detector.detect_changes(
                                result.pixel_data,
                                current_pixel_format['bits_per_pixel'] // 8
                            )

                            if changed_regions is not None and len(changed_regions) == 0:
                                # No changes
                                protocol.send_framebuffer_update(client_socket, [])
                                continue

                            # Send region updates if available
                            if changed_regions is not None and len(changed_regions) < 10:
                                # TODO: Implement region-based encoding
                                pass

                        # Select best encoding
                        # For localhost, prefer Raw encoding (no compression overhead)
                        content_type = "localhost" if is_localhost else "dynamic"
                        encoding_type, encoder = encoder_manager.get_best_encoder(
                            client_encodings, content_type=content_type
                        )

                        # Encode pixel data
                        bytes_per_pixel = current_pixel_format['bits_per_pixel'] // 8
                        encoded_data = encoder.encode(
                            result.pixel_data, fb_width, fb_height, bytes_per_pixel
                        )

                        # Send framebuffer update
                        rectangles = [
                            (0, 0, fb_width, fb_height, encoding_type, encoded_data)
                        ]
                        protocol.send_framebuffer_update(client_socket, rectangles)

                        # Record metrics
                        if conn_metrics:
                            encoding_time = time.perf_counter() - start_time
                            conn_metrics.record_frame(
                                len(encoded_data), encoding_time, len(result.pixel_data)
                            )

                        last_frame_time = time.time()

                    case protocol.MSG_KEY_EVENT:
                        key_event = protocol.parse_key_event(client_socket)
                        input_handler.handle_key_event(
                            key_event['down_flag'],
                            key_event['key']
                        )
                        if conn_metrics:
                            conn_metrics.record_input('key')

                    case protocol.MSG_POINTER_EVENT:
                        pointer_event = protocol.parse_pointer_event(client_socket)
                        input_handler.handle_pointer_event(
                            pointer_event['button_mask'],
                            pointer_event['x'],
                            pointer_event['y']
                        )
                        if conn_metrics:
                            conn_metrics.record_input('pointer')

                    case protocol.MSG_CLIENT_CUT_TEXT:
                        text = protocol.parse_client_cut_text(client_socket)
                        self.logger.info(f"Client cut text: {text[:50]}...")

                    case _:
                        self.logger.warning(f"Unknown message type: {msg_type}")
                        break

            except VNCError as e:
                # Specific VNC errors - log and continue or break based on type
                match e:
                    case ProtocolError():
                        self.logger.error(f"Protocol error: {e}")
                        break  # Protocol errors are fatal
                    case AuthenticationError():
                        self.logger.warning(f"Auth error: {e}")
                        break
                    case ConnectionError():
                        self.logger.warning(f"Connection error: {e}")
                        break
                    case _:
                        self.logger.error(f"VNC error: {e}", exc_info=True)
                        if conn_metrics:
                            conn_metrics.record_error()
                        break

            except Exception as e:
                self.logger.error(f"Unexpected error in message loop: {e}", exc_info=True)
                if conn_metrics:
                    conn_metrics.record_error()
                break

    def handle_multiple_clients_batch(self, client_data: list[tuple[socket.socket, tuple, str]]) -> None:
        """
        Handle multiple clients with exception group support (Python 3.13)

        Args:
            client_data: List of (socket, addr, client_id) tuples

        This method demonstrates exception groups for batch client handling
        """
        with ExceptionCollector() as collector:
            for client_socket, addr, client_id in client_data:
                with collector.catch(f"client_{client_id}"):
                    self.handle_client(client_socket, addr, client_id)

        # Handle collected errors
        if collector.has_exceptions():
            exc_group = collector.create_exception_group("Multiple client errors")
            if exc_group:
                # Categorize by exception type
                categories = categorize_exceptions(exc_group)

                for exc_type, exceptions in categories.items():
                    self.logger.error(f"{exc_type}: {len(exceptions)} occurrences")
                    for exc in exceptions[:3]:  # Log first 3 of each type
                        self.logger.error(f"  - {exc}")

                # Re-raise if any critical errors
                if "ProtocolError" in categories or "ConnectionError" in categories:
                    raise exc_group

    def _cleanup(self):
        """Cleanup server resources"""
        self.logger.info("Cleaning up server resources...")

        # Stop health checker
        self.health_checker.stop()

        # Close server socket
        try:
            self.server_socket.close()
        except:
            pass

        # Print metrics summary
        if self.metrics:
            summary = self.metrics.format_summary()
            self.logger.info(f"Final metrics:\n{summary}")

    def get_status(self) -> dict:
        """Get server status"""
        if self.metrics:
            return self.metrics.get_summary()
        return {
            'active_connections': self.connection_pool.get_active_count(),
            'max_connections': self.max_connections,
        }


def main():
    """Main entry point"""
    # Setup basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create and start server
    server = VNCServerV3()
    server.start()


if __name__ == '__main__':
    main()
