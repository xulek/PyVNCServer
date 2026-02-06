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
from vnc_lib.auth import VNCAuth
from vnc_lib.input_handler import InputHandler
from vnc_lib.screen_capture import ScreenCapture
from vnc_lib.encodings import EncoderManager
from vnc_lib.change_detector import AdaptiveChangeDetector
from vnc_lib.cursor import CursorEncoder
from vnc_lib.metrics import ServerMetrics, ConnectionMetrics, PerformanceMonitor
from vnc_lib.server_utils import (
    GracefulShutdown, HealthChecker, ConnectionPool, PerformanceThrottler,
    NetworkProfile, detect_network_profile
)
from vnc_lib.exceptions import (
    VNCError, ProtocolError, AuthenticationError, ConnectionError,
    ExceptionCollector, categorize_exceptions
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
        self.lan_frame_rate = max(1, min(120, self.config.get('lan_frame_rate', 60)))
        self.network_profile_override = self.config.get('network_profile_override', None)
        self.scale_factor = self.config.get('scale_factor', self.DEFAULT_SCALE_FACTOR)
        self.max_connections = self.config.get('max_connections', self.MAX_CONNECTIONS)
        self.client_socket_timeout = max(
            1.0, float(self.config.get('client_socket_timeout', 60.0))
        )

        # Features
        self.enable_region_detection = self.config.get('enable_region_detection', True)
        self.enable_cursor_encoding = self.config.get('enable_cursor_encoding', False)
        self.enable_metrics = self.config.get('enable_metrics', True)
        self.enable_websocket = self.config.get('enable_websocket', False)

        # Protocol and WebSocket safety limits
        self.max_set_encodings = max(
            1, int(self.config.get('max_set_encodings', RFBProtocol.DEFAULT_MAX_SET_ENCODINGS))
        )
        self.max_client_cut_text = max(
            1, int(self.config.get('max_client_cut_text', RFBProtocol.DEFAULT_MAX_CLIENT_CUT_TEXT))
        )
        self.websocket_detect_timeout = max(
            0.05, float(self.config.get('websocket_detect_timeout', 0.5))
        )
        self.websocket_max_handshake_bytes = max(
            1024,
            int(
                self.config.get(
                    'websocket_max_handshake_bytes',
                    64 * 1024,
                )
            ),
        )
        self.websocket_max_payload_bytes = max(
            1024,
            int(
                self.config.get(
                    'websocket_max_payload_bytes',
                    8 * 1024 * 1024,
                )
            ),
        )
        self.websocket_max_buffer_bytes = max(
            4096,
            int(
                self.config.get(
                    'websocket_max_buffer_bytes',
                    16 * 1024 * 1024,
                )
            ),
        )

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
                        f"cursor={self.enable_cursor_encoding}, metrics={self.enable_metrics}, "
                        f"websocket={self.enable_websocket}")
        if not self.password:
            self.logger.warning(
                "Server is running without authentication (SecurityType None). "
                "Use a password or network-level protections for untrusted environments."
            )

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
        parallel_encoder = None

        try:
            # Detect network profile for performance optimization
            if self.network_profile_override:
                network_profile = NetworkProfile(self.network_profile_override)
            else:
                network_profile = detect_network_profile(addr[0])
            is_localhost = network_profile == NetworkProfile.LOCALHOST
            is_lan = network_profile == NetworkProfile.LAN
            self.logger.info(f"Connection from {addr[0]}: network profile = {network_profile.value}")

            try:
                client_socket.settimeout(self.client_socket_timeout)
            except Exception as e:
                self.logger.warning(f"Could not set client socket timeout: {e}")

            # Enable TCP_NODELAY for all connections (VNC is interactive;
            # Nagle's algorithm only adds latency with zero benefit)
            try:
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception as e:
                self.logger.warning(f"Could not set TCP_NODELAY: {e}")

            # Set socket send buffer size based on network profile
            if not is_localhost:
                try:
                    sndbuf = 524288 if is_lan else 262144  # 512KB LAN, 256KB WAN
                    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf)
                except Exception as e:
                    self.logger.warning(f"Could not set SO_SNDBUF: {e}")

            # Register connection metrics
            if self.metrics:
                conn_metrics = self.metrics.register_connection(client_id)

            # Optional WebSocket support (for browser/noVNC clients)
            if self.enable_websocket:
                try:
                    from vnc_lib.websocket_wrapper import (
                        is_websocket_request,
                        WebSocketVNCAdapter,
                    )
                    if is_websocket_request(
                        client_socket,
                        peek_timeout=self.websocket_detect_timeout
                    ):
                        self.logger.info("WebSocket handshake detected; wrapping client socket")
                        client_socket = WebSocketVNCAdapter(
                            client_socket,
                            max_handshake_bytes=self.websocket_max_handshake_bytes,
                            max_payload_bytes=self.websocket_max_payload_bytes,
                            max_buffer_bytes=self.websocket_max_buffer_bytes,
                        )
                except Exception as e:
                    self.logger.error(f"WebSocket setup failed: {e}")
                    return

            # Initialize protocol handler (raw TCP or WebSocket-adapted)
            protocol = RFBProtocol(
                max_set_encodings=self.max_set_encodings,
                max_client_cut_text=self.max_client_cut_text,
            )

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

            # Default pixel format: BGR0 matches native Windows BGRA capture
            # (zero-copy path: ~33ms vs ~89ms with channel swapping at 1080p)
            # VNC clients may override this with SetPixelFormat
            current_pixel_format = {
                'bits_per_pixel': 32,
                'depth': 24,
                'big_endian_flag': 0,
                'true_colour_flag': 1,
                'red_max': 255,
                'green_max': 255,
                'blue_max': 255,
                'red_shift': 16,
                'green_shift': 8,
                'blue_shift': 0
            }

            # Get initial screen dimensions
            initial_result = self._capture_frame(screen_capture, current_pixel_format)
            if (
                initial_result.pixel_data is None
                or initial_result.width <= 0
                or initial_result.height <= 0
            ):
                raise ConnectionError("Initial screen capture failed")

            width, height = initial_result.width, initial_result.height

            protocol.send_server_init(
                client_socket, width, height,
                current_pixel_format, "Python VNC Server v3.0"
            )

            # Initialize encoders and change detection
            # Enable advanced encodings from config
            enable_tight = self.config.get('enable_tight_encoding', True)
            enable_jpeg = self.config.get('enable_jpeg_encoding', True)
            enable_h264 = self.config.get('enable_h264_encoding', False)
            disable_tight_for_ultravnc = self.config.get('tight_disable_for_ultravnc', True)

            encoder_manager = EncoderManager(
                enable_tight=enable_tight,
                enable_jpeg=enable_jpeg,
                enable_h264=enable_h264,
                disable_tight_for_ultravnc=disable_tight_for_ultravnc,
            )
            client_encodings: set[int] = {0}  # Default: Raw encoding

            # For localhost, disable change detection (overhead not worth it with high bandwidth)
            use_change_detection = self.enable_region_detection and not is_localhost
            change_detector = AdaptiveChangeDetector(width, height) if use_change_detection else None
            cursor_encoder = CursorEncoder() if self.enable_cursor_encoding else None

            # Initialize parallel encoder for multi-threaded encoding
            use_parallel = self.config.get('enable_parallel_encoding', True)
            if use_parallel:
                try:
                    from vnc_lib.parallel_encoder import ParallelEncoder
                    max_workers = self.config.get('encoding_threads', None)
                    parallel_encoder = ParallelEncoder(max_workers=max_workers)
                    self.logger.info(f"Parallel encoding enabled with {parallel_encoder.max_workers} workers")
                except ImportError as e:
                    self.logger.warning(f"Parallel encoding unavailable: {e}")

            if is_localhost and self.enable_region_detection:
                self.logger.info("Change detection disabled for localhost connection (optimization)")

            # Main message loop
            self._client_message_loop(
                client_socket, protocol, screen_capture, input_handler,
                current_pixel_format, client_encodings, width, height,
                encoder_manager, change_detector, cursor_encoder, conn_metrics,
                is_localhost, parallel_encoder, network_profile
            )

        except Exception as e:
            self.logger.error(f"Error handling client {addr}: {e}", exc_info=True)
            if conn_metrics:
                conn_metrics.record_error()
        finally:
            if parallel_encoder:
                try:
                    parallel_encoder.shutdown(wait=False)
                except Exception:
                    pass
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
                            is_localhost: bool = False,
                            parallel_encoder = None,
                            network_profile: NetworkProfile = NetworkProfile.WAN):
        """
        Enhanced client message handling loop with network-aware optimization

        Localhost optimizations:
        - Up to 120 FPS frame rate
        - Raw encoding only (no compression overhead)
        - TCP_NODELAY enabled (lower latency)
        - Change detection disabled (unnecessary overhead)

        LAN optimizations:
        - Up to 60 FPS frame rate (configurable)
        - Fast encoders (Hextile/ZRLE, skip expensive Tight)
        - TCP_NODELAY enabled
        """

        # Frame rate based on network profile
        match network_profile:
            case NetworkProfile.LOCALHOST:
                max_frame_rate = 120
            case NetworkProfile.LAN:
                max_frame_rate = self.lan_frame_rate
            case _:
                max_frame_rate = self.frame_rate
        throttler = PerformanceThrottler(max_rate=max_frame_rate)

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

                        # Throttle before expensive capture/encoding work.
                        throttler.throttle()
                        start_time = time.perf_counter()
                        result = self._capture_frame(screen_capture, current_pixel_format)

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

                        request_region = self._normalize_request_region(request, fb_width, fb_height)
                        if request_region is None:
                            protocol.send_framebuffer_update(client_socket, [])
                            continue
                        req_x, req_y, req_w, req_h = request_region

                        # Check for changes (incremental update)
                        if request['incremental'] and change_detector:
                            changed_regions = change_detector.detect_changes(
                                result.pixel_data,
                                current_pixel_format['bits_per_pixel'] // 8
                            )

                            if changed_regions is not None:
                                changed_regions = self._intersect_regions(changed_regions, request_region)

                            if changed_regions is not None and len(changed_regions) == 0:
                                # No changes
                                protocol.send_framebuffer_update(client_socket, [])
                                continue

                            # Send region updates if available using parallel encoding
                            if changed_regions is not None and len(changed_regions) < 10 and parallel_encoder:
                                # Use parallel encoding for changed regions
                                bytes_per_pixel = current_pixel_format['bits_per_pixel'] // 8
                                content_type = network_profile.value if network_profile != NetworkProfile.WAN else "dynamic"

                                # Prepare regions for parallel encoding
                                regions_to_encode = []
                                for x, y, w, h in changed_regions:
                                    # Extract region pixel data
                                    region_data = self._extract_region(
                                        result.pixel_data, fb_width, fb_height,
                                        x, y, w, h, bytes_per_pixel
                                    )
                                    encoding_type, encoder = encoder_manager.get_best_encoder(
                                        client_encodings, content_type=content_type
                                    )
                                    regions_to_encode.append(((x, y, w, h), region_data, encoding_type, encoder))

                                # Encode regions in parallel
                                encoded_results = parallel_encoder.encode_regions(regions_to_encode, bytes_per_pixel)

                                # Build rectangles from results
                                rectangles = [
                                    (r.x, r.y, r.width, r.height, r.encoding_type, r.encoded_data)
                                    for r in encoded_results
                                ]

                                protocol.send_framebuffer_update(client_socket, rectangles)

                                # Record metrics
                                if conn_metrics:
                                    encoding_time = time.perf_counter() - start_time
                                    total_bytes = sum(r.original_size for r in encoded_results)
                                    compressed_bytes = sum(r.compressed_size for r in encoded_results)
                                    conn_metrics.record_frame(
                                        compressed_bytes, encoding_time, total_bytes
                                    )
                                continue

                            # Non-parallel region encoding fallback
                            if changed_regions is not None and len(changed_regions) > 0:
                                bytes_per_pixel = current_pixel_format['bits_per_pixel'] // 8
                                content_type = network_profile.value if network_profile != NetworkProfile.WAN else "dynamic"

                                rectangles = []
                                original_total_bytes = 0
                                compressed_total_bytes = 0
                                for x, y, w, h in changed_regions:
                                    region_data = self._extract_region(
                                        result.pixel_data, fb_width, fb_height,
                                        x, y, w, h, bytes_per_pixel
                                    )
                                    original_total_bytes += len(region_data)
                                    encoding_type, encoder = encoder_manager.get_best_encoder(
                                        client_encodings, content_type=content_type
                                    )
                                    encoded_data = encoder.encode(region_data, w, h, bytes_per_pixel)
                                    compressed_total_bytes += len(encoded_data)
                                    rectangles.append((x, y, w, h, encoding_type, encoded_data))

                                protocol.send_framebuffer_update(client_socket, rectangles)

                                if conn_metrics:
                                    encoding_time = time.perf_counter() - start_time
                                    conn_metrics.record_frame(
                                        compressed_total_bytes,
                                        encoding_time,
                                        original_total_bytes,
                                    )
                                continue

                        # Select best encoding based on network profile
                        content_type = network_profile.value if network_profile != NetworkProfile.WAN else "dynamic"
                        encoding_type, encoder = encoder_manager.get_best_encoder(
                            client_encodings, content_type=content_type
                        )

                        self.logger.debug(f"Selected encoding: {encoding_type} for content type: {content_type}")

                        # Encode pixel data (single-threaded for full frame)
                        bytes_per_pixel = current_pixel_format['bits_per_pixel'] // 8
                        full_request = (
                            req_x == 0 and req_y == 0 and req_w == fb_width and req_h == fb_height
                        )
                        if full_request:
                            frame_pixels = result.pixel_data
                        else:
                            frame_pixels = self._extract_region(
                                result.pixel_data,
                                fb_width,
                                fb_height,
                                req_x,
                                req_y,
                                req_w,
                                req_h,
                                bytes_per_pixel,
                            )

                        self.logger.debug(
                            f"Encoding frame: {req_w}x{req_h}, bpp={bytes_per_pixel}, "
                            f"data_size={len(frame_pixels)}"
                        )

                        encoded_data = encoder.encode(
                            frame_pixels, req_w, req_h, bytes_per_pixel
                        )

                        self.logger.debug(f"Encoded data size: {len(encoded_data)} bytes")

                        # Send framebuffer update
                        rectangles = [
                            (req_x, req_y, req_w, req_h, encoding_type, encoded_data)
                        ]
                        self.logger.debug(f"Sending framebuffer update with {len(rectangles)} rectangle(s)")
                        protocol.send_framebuffer_update(client_socket, rectangles)
                        self.logger.debug("Framebuffer update sent successfully")

                        # Record metrics
                        if conn_metrics:
                            encoding_time = time.perf_counter() - start_time
                            conn_metrics.record_frame(
                                len(encoded_data), encoding_time, len(frame_pixels)
                            )

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

    def _extract_region(self, pixel_data: bytes, fb_width: int, fb_height: int,
                       x: int, y: int, width: int, height: int,
                       bytes_per_pixel: int) -> bytes:
        """Extract a rectangular region from framebuffer"""
        if bytes_per_pixel <= 0 or width <= 0 or height <= 0:
            return b''

        if x < 0:
            width += x
            x = 0
        if y < 0:
            height += y
            y = 0
        if x >= fb_width or y >= fb_height:
            return b''

        width = min(width, fb_width - x)
        height = min(height, fb_height - y)
        if width <= 0 or height <= 0:
            return b''

        row_size = width * bytes_per_pixel
        result = bytearray(height * row_size)
        dst_offset = 0

        for row in range(height):
            src_offset = ((y + row) * fb_width + x) * bytes_per_pixel
            result[dst_offset:dst_offset + row_size] = pixel_data[src_offset:src_offset + row_size]
            dst_offset += row_size

        return bytes(result)

    def _capture_frame(self, screen_capture: ScreenCapture, pixel_format: dict):
        """Capture a frame for a single client connection."""
        return screen_capture.capture_fast(pixel_format)

    def _normalize_request_region(self, request: dict, fb_width: int,
                                  fb_height: int) -> tuple[int, int, int, int] | None:
        """Clamp client-requested update rectangle to framebuffer bounds."""
        if fb_width <= 0 or fb_height <= 0:
            return None

        x = int(request.get('x', 0))
        y = int(request.get('y', 0))
        width = int(request.get('width', 0))
        height = int(request.get('height', 0))

        if width <= 0 or height <= 0:
            return None
        if x >= fb_width or y >= fb_height:
            return None

        x = max(0, x)
        y = max(0, y)
        width = min(width, fb_width - x)
        height = min(height, fb_height - y)
        if width <= 0 or height <= 0:
            return None

        return x, y, width, height

    def _intersect_rectangles(self, first: tuple[int, int, int, int],
                              second: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
        """Return intersection of two rectangles or None if disjoint."""
        x1, y1, w1, h1 = first
        x2, y2, w2, h2 = second

        left = max(x1, x2)
        top = max(y1, y2)
        right = min(x1 + w1, x2 + w2)
        bottom = min(y1 + h1, y2 + h2)

        if right <= left or bottom <= top:
            return None
        return left, top, right - left, bottom - top

    def _intersect_regions(self, regions, request_region: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
        """Filter changed regions to the client-requested area."""
        filtered: list[tuple[int, int, int, int]] = []
        for region in regions:
            if hasattr(region, 'x'):
                rect = (int(region.x), int(region.y), int(region.width), int(region.height))
            else:
                rect = (
                    int(region[0]),
                    int(region[1]),
                    int(region[2]),
                    int(region[3]),
                )
            intersection = self._intersect_rectangles(rect, request_region)
            if intersection is not None:
                filtered.append(intersection)
        return filtered

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
