#!/usr/bin/env python3
"""
RFC 6143 Compliant VNC Server - Enhanced Version 3.0
Python 3.13 compatible with modern features and optimizations
"""

import socket
import threading
import time
import logging
import argparse
import struct
import os
import ssl
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vnc_lib.protocol import RFBProtocol
from vnc_lib.vencrypt import VeNCryptServer, parse_minimum_tls_version
from vnc_lib.io_utils import recv_exact
from vnc_lib.auth import VNCAuth, CRYPTO_AVAILABLE
from vnc_lib.input_handler import InputHandler
from vnc_lib.screen_capture import ScreenCapture
from vnc_lib.capture_backends import CaptureFrame, CaptureMetadata, CaptureMoveRect
from vnc_lib.encodings import EncoderManager, encoding_name, format_encoding_list
from vnc_lib.change_detector import AdaptiveChangeDetector
from vnc_lib.cursor import CursorEncoder, SystemCursorCapture
from vnc_lib.metrics import ServerMetrics, ConnectionMetrics, PerformanceMonitor
from vnc_lib.types import is_valid_pixel_format
from vnc_lib.clipboard import sanitize_clipboard_text
from vnc_lib.server_utils import (
    GracefulShutdown, HealthChecker, ConnectionLimiter, PerformanceThrottler,
    NetworkProfile, detect_network_profile
)
from vnc_lib.exceptions import (
    VNCError, ProtocolError, AuthenticationError, ConnectionError as VNCConnectionError,
    ConfigurationError,
)
from pyvncserver.config import DEFAULT_CONFIG_PATH, ServerSettings, load_config_file
from pyvncserver._version import __version__, SERVER_NAME
from pyvncserver.platform.producer import CaptureProducer, FrameSnapshot
from pyvncserver.runtime.security import AuthRateLimiter, PerIPConnectionLimiter
from pyvncserver.runtime.adaptive import AdaptiveStreamConfig, EncodedRegionCache
from pyvncserver.session_state import ClientSessionState
from pyvncserver.session.loop import SessionLoopMixin
from pyvncserver.session.runtime import SessionRuntimeMixin


class VNCServerV3(SessionRuntimeMixin, SessionLoopMixin):
    """
    RFC 6143 compliant VNC Server - Enhanced Version 3.0

    New features:
    - Multiple encoding support (Raw, RRE, Hextile, Zlib, Tight)
    - Region-based change detection
    - Performance metrics and monitoring
    - Graceful shutdown handling
    - Connection pooling
    - Health checks
    - Python 3.13 type hints
    """

    DEFAULT_PORT = 5900
    DEFAULT_HOST = '127.0.0.1'
    DEFAULT_FRAME_RATE = 30
    DEFAULT_SCALE_FACTOR = 1.0
    MAX_CONNECTIONS = 10

    def __init__(self, config_file: str | Path | None = None):
        """Initialize enhanced VNC Server with configuration"""
        self.logger = logging.getLogger(__name__)

        # Load and validate configuration. Configuration errors are fatal: a
        # VNC server must never silently fall back to insecure defaults.
        self.config = self._load_config(config_file or DEFAULT_CONFIG_PATH)
        self.settings = ServerSettings.from_mapping(self.config)

        # Setup logging
        self._setup_logging()

        # Server configuration
        self.host = self.settings.host
        self.port = self.settings.port
        self.password = self.settings.security.password
        self.read_only_password = self.settings.security.read_only_password
        self.frame_rate = self.settings.frame_rate
        self.lan_frame_rate = self.settings.lan_frame_rate
        self.network_profile_override = self.settings.network_profile_override
        self.scale_factor = self.settings.scale_factor
        self.capture_backend = self.settings.capture_backend
        self.monitor_index = self.settings.monitor_index
        self.capture_all_monitors = self.settings.capture_all_monitors
        self.capture_probe_frames = max(0, int(self.config.get('capture_probe_frames', 0)))
        self.capture_probe_warn_ms = max(
            1.0, float(self.config.get('capture_probe_warn_ms', 40.0))
        )
        self.max_connections = self.settings.max_connections
        self.max_connections_per_ip = self.settings.max_connections_per_ip
        self.max_unauthenticated_connections = self.settings.max_unauthenticated_connections
        self.handshake_timeout = self.settings.handshake_timeout
        self.client_socket_timeout = self.settings.client_socket_timeout
        if (self.password or self.read_only_password) and not CRYPTO_AVAILABLE:
            raise ConfigurationError(
                "VNC authentication is configured but pycryptodome is not installed"
            )
        self.tls_context: ssl.SSLContext | None = None
        if self.settings.security.tls_enabled:
            self.tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.tls_context.minimum_version = parse_minimum_tls_version(
                self.settings.security.tls_minimum_version
            )
            self.tls_context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
            self.tls_context.load_cert_chain(
                self.settings.security.tls_cert_file,
                self.settings.security.tls_key_file,
            )

        self.vencrypt_server: VeNCryptServer | None = None
        if self.settings.security.vencrypt_enabled:
            self.vencrypt_server = VeNCryptServer(
                cert_file=self.settings.security.tls_cert_file,
                key_file=self.settings.security.tls_key_file,
                subtype_names=self.settings.security.vencrypt_subtypes,
                allow_anonymous_tls=self.settings.security.vencrypt_allow_anonymous_tls,
                allow_no_auth_with_password=(
                    self.settings.security.vencrypt_allow_no_auth_with_password
                ),
                minimum_tls_version=self.settings.security.tls_minimum_version,
                logger=self.logger,
            )
            try:
                self.vencrypt_subtypes = self.vencrypt_server.validate_configuration(
                    has_vnc_auth=bool(self.password or self.read_only_password)
                )
            except (ValueError, ssl.SSLError, OSError, VNCConnectionError) as exc:
                raise ConfigurationError(
                    f"Invalid VeNCrypt configuration: {exc}"
                ) from exc
        else:
            self.vencrypt_subtypes = ()

        # Features
        self.enable_region_detection = self.config.get('enable_region_detection', True)
        requested_cursor_encoding = bool(self.config.get('enable_cursor_encoding', False))
        cursor_probe = SystemCursorCapture(scale_factor=self.scale_factor)
        self.enable_cursor_encoding = requested_cursor_encoding and cursor_probe.enabled
        self.enable_metrics = self.config.get('enable_metrics', True)
        self.enable_health_checks = self.config.get('enable_health_checks', True)
        self.enable_websocket = self.config.get('enable_websocket', False)
        self.enable_capture_producer = self.config.get('enable_capture_producer', True)
        # Tight is an RFB extension negotiation mechanism, not transport
        # encryption. Keep the legacy key as a compatibility fallback.
        self.enable_tight_extensions = self.config.get(
            'enable_tight_extensions', self.config.get('enable_tight_security', True)
        )
        self.enable_tight_security = self.enable_tight_extensions
        self.enable_lan_adaptive_encoding = self.config.get('enable_lan_adaptive_encoding', True)
        self.enable_request_coalescing = self.config.get('enable_request_coalescing', True)
        self.enable_copyrect_encoding = self.config.get('enable_copyrect_encoding', True)
        self.enable_zrle_encoding = self.config.get('enable_zrle_encoding', True)
        self.enable_dxgi_metadata = bool(
            self.config.get('enable_dxgi_metadata', True)
        )
        self.enable_continuous_updates = bool(
            self.config.get('enable_continuous_updates', True)
        )
        self.enable_fence = bool(self.config.get('enable_fence', True))
        self.enable_last_rect = bool(self.config.get('enable_last_rect', False))
        self.enable_extended_desktop_size = bool(
            self.config.get('enable_extended_desktop_size', True)
        )
        self.allow_client_resize = bool(self.config.get('allow_client_resize', False))
        self.tight_stream_reset_for_ultravnc = bool(
            self.config.get('tight_stream_reset_for_ultravnc', False)
        )
        self.enable_adaptive_streaming = bool(
            self.config.get('adaptive_enabled', True)
        )
        self.adaptive_stream_config = AdaptiveStreamConfig(
            enabled=self.enable_adaptive_streaming,
            min_fps=max(1.0, float(self.config.get('adaptive_min_fps', 12.0))),
            target_utilization=max(0.25, min(0.98, float(self.config.get('adaptive_target_utilization', 0.80)))),
            decrease_factor=max(0.20, min(0.95, float(self.config.get('adaptive_decrease_factor', 0.80)))),
            increase_step_fps=max(0.1, float(self.config.get('adaptive_increase_step_fps', 2.0))),
            overload_ratio=max(1.0, float(self.config.get('adaptive_overload_ratio', 1.10))),
            recovery_ratio=max(0.10, min(0.95, float(self.config.get('adaptive_recovery_ratio', 0.72)))),
            overload_samples=max(1, int(self.config.get('adaptive_overload_samples', 2))),
            recovery_samples=max(1, int(self.config.get('adaptive_recovery_samples', 8))),
            ewma_alpha=max(0.01, min(1.0, float(self.config.get('adaptive_ewma_alpha', 0.20)))),
            merge_regions=bool(self.config.get('adaptive_merge_regions', True)),
            merge_gap_px=max(0, int(self.config.get('adaptive_merge_gap_px', 12))),
            merge_max_expansion=max(1.0, float(self.config.get('adaptive_merge_max_expansion', 1.35))),
            merge_force_count=max(2, int(self.config.get('adaptive_merge_force_count', 12))),
            cache_enabled=bool(self.config.get('adaptive_cache_enabled', True)),
            cache_max_entries=max(1, int(self.config.get('adaptive_cache_max_entries', 512))),
            cache_max_bytes=max(1024, int(self.config.get('adaptive_cache_max_bytes', 32 * 1024 * 1024))),
            cache_max_item_bytes=max(1, int(self.config.get('adaptive_cache_max_item_bytes', 1024 * 1024))),
            cache_ttl_seconds=max(0.05, float(self.config.get('adaptive_cache_ttl_seconds', 2.0))),
            reorder_encodings=bool(self.config.get('adaptive_reorder_encodings', True)),
            adapt_tight_compression=bool(self.config.get('adaptive_adapt_tight_compression', True)),
        )
        if requested_cursor_encoding and not self.enable_cursor_encoding:
            self.logger.warning(
                "Cursor pseudo-encoding is unavailable on this platform; disabling enable_cursor_encoding"
            )

        # LAN adaptive encoding tuning
        self.lan_raw_area_threshold = max(
            0.01, min(1.0, float(self.config.get('lan_raw_area_threshold', 0.12)))
        )
        self.lan_raw_max_pixels = max(
            1024, int(self.config.get('lan_raw_max_pixels', 65536))
        )
        self.lan_prefer_zlib = bool(self.config.get('lan_prefer_zlib', False))
        self.lan_zlib_area_threshold = max(
            0.05, min(1.0, float(self.config.get('lan_zlib_area_threshold', 0.20)))
        )
        self.lan_zlib_min_pixels = max(
            4096, int(self.config.get('lan_zlib_min_pixels', 131072))
        )
        self.lan_zlib_compression_level = max(
            1, min(9, int(self.config.get('lan_zlib_compression_level', 3)))
        )
        self.lan_zlib_disable_if_request_gap_ms = max(
            100, int(self.config.get('lan_zlib_disable_if_request_gap_ms', 1500))
        )
        self.lan_jpeg_area_threshold = max(
            0.05, min(1.0, float(self.config.get('lan_jpeg_area_threshold', 0.25)))
        )
        self.lan_jpeg_min_pixels = max(1024, int(self.config.get('lan_jpeg_min_pixels', 32768)))
        self.lan_jpeg_quality_min = max(
            1, min(100, int(self.config.get('lan_jpeg_quality_min', 55)))
        )
        self.lan_jpeg_quality_max = max(
            self.lan_jpeg_quality_min,
            min(100, int(self.config.get('lan_jpeg_quality_max', 90))),
        )
        self.lan_jpeg_quality_initial = max(
            self.lan_jpeg_quality_min,
            min(
                self.lan_jpeg_quality_max,
                int(self.config.get('lan_jpeg_quality_initial', 75)),
            ),
        )
        self.lan_zrle_compression_level = max(
            1, min(9, int(self.config.get('lan_zrle_compression_level', 2)))
        )
        self.lan_tight_compression_level = max(
            1, min(9, int(self.config.get('lan_tight_compression_level', 2)))
        )
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
        self.websocket_max_message_bytes = max(
            self.websocket_max_payload_bytes,
            int(self.config.get('websocket_max_message_bytes', 16 * 1024 * 1024)),
        )
        self.websocket_allowed_origins = self._coerce_allowed_origins(
            self.config.get('websocket_allowed_origins', [])
        )

        self.input_control_policy = self.settings.input_control_policy
        self._input_control_lock = threading.Lock()
        self._input_controller_client_id: str | None = None
        self._input_control_rejections_logged: set[str] = set()
        self._client_registry_lock = threading.Lock()
        self._authenticated_client_sockets: dict[str, socket.socket] = {}
        self._all_client_sockets: dict[str, object] = {}
        self._client_threads: dict[str, threading.Thread] = {}

        # Shared OS-facing services. Capture is internally locked to avoid
        # racing its backend state across client threads.
        try:
            self.screen_capture = ScreenCapture(
                scale_factor=self.scale_factor,
                monitor=self.monitor_index,
                backend_preference=self.capture_backend,
                capture_all_monitors=self.capture_all_monitors,
            )
        except TypeError:
            # Preserve compatibility with embedders/tests providing a custom
            # ScreenCapture implementation with the pre-3.4 constructor.
            self.screen_capture = ScreenCapture(
                scale_factor=self.scale_factor,
                monitor=self.monitor_index,
                backend_preference=self.capture_backend,
            )
            try:
                self.screen_capture.capture_all_monitors = self.capture_all_monitors
            except Exception:
                pass
        try:
            self.screen_capture.enable_dxgi_metadata = self.enable_dxgi_metadata
        except Exception:
            pass
        self.input_handler = InputHandler(scale_factor=self.scale_factor)

        # Server components
        self.shutdown_handler = GracefulShutdown()
        self.connection_limiter = ConnectionLimiter(max_connections=self.max_connections)
        # Compatibility attribute for older callers.
        self.connection_pool = self.connection_limiter
        self.unauthenticated_limiter = ConnectionLimiter(
            max_connections=self.max_unauthenticated_connections
        )
        self.per_ip_limiter = PerIPConnectionLimiter(self.max_connections_per_ip)
        self.auth_rate_limiter = AuthRateLimiter(
            max_failures=self.settings.security.auth_max_failures,
            window_seconds=self.settings.security.auth_failure_window_seconds,
            max_backoff_seconds=self.settings.security.auth_backoff_max_seconds,
        )
        self.metrics = ServerMetrics.get_instance() if self.enable_metrics else None
        self.health_checker = HealthChecker(check_interval=30.0)
        self.encoded_region_cache = (
            EncodedRegionCache(
                max_entries=self.adaptive_stream_config.cache_max_entries,
                max_bytes=self.adaptive_stream_config.cache_max_bytes,
                max_item_bytes=self.adaptive_stream_config.cache_max_item_bytes,
                ttl_seconds=self.adaptive_stream_config.cache_ttl_seconds,
            )
            if self.enable_adaptive_streaming and self.adaptive_stream_config.cache_enabled
            else None
        )

        # One executor is shared across clients to avoid N-clients × N-workers
        # thread explosions. ParallelEncoder instances become lightweight views.
        configured_workers = self.config.get('encoding_threads', None)
        if isinstance(configured_workers, int) and configured_workers <= 0:
            configured_workers = None
        auto_workers = max(1, min((os.cpu_count() or 4) - 1, 8))
        self.encoding_workers = configured_workers or auto_workers
        self.encoding_executor = ThreadPoolExecutor(
            max_workers=self.encoding_workers,
            thread_name_prefix="VNC-Encoder",
        )

        producer_fps = float(
            self.config.get('capture_producer_fps', max(self.frame_rate, self.lan_frame_rate, 60))
        )
        self.capture_producer = (
            CaptureProducer(self.screen_capture, fps=producer_fps)
            if self.enable_capture_producer
            else None
        )

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

        self.logger.info(f"{SERVER_NAME} listening on {self.host}:{self.port}")
        self.logger.info(f"Frame rate: {self.frame_rate} FPS, Scale: {self.scale_factor}")
        self.logger.info(
            "Capture backend: %s (requested=%s)",
            getattr(self.screen_capture, 'get_backend_name', lambda: 'unknown')(),
            self.capture_backend,
        )
        if hasattr(self.screen_capture, 'get_backend_capabilities'):
            caps = self.screen_capture.get_backend_capabilities()
            self.logger.info(
                "Capture metadata: dirty_regions=%s, move_rects=%s",
                caps.supports_dirty_regions,
                caps.supports_move_rects,
            )
        self.logger.info(f"Max connections: {self.max_connections}")
        self.logger.info(f"Features: region_detection={self.enable_region_detection}, "
                        f"cursor={self.enable_cursor_encoding}, metrics={self.enable_metrics}, "
                        f"websocket={self.enable_websocket}")
        self.logger.info(
            "Adaptive streaming: enabled=%s, min_fps=%.1f, region_merge=%s, cache=%s",
            self.enable_adaptive_streaming,
            self.adaptive_stream_config.min_fps,
            self.adaptive_stream_config.merge_regions,
            self.encoded_region_cache is not None,
        )
        if not (self.password or self.read_only_password):
            self.logger.warning(
                "Server is running without VNC authentication on loopback only. "
                "Use a password before binding to a non-loopback interface."
            )
        elif (
            self.tls_context is None
            and self.vencrypt_server is None
            and self.host not in {'127.0.0.1', '::1', 'localhost'}
        ):
            self.logger.warning(
                "Classic VNC authentication protects the password challenge but does not "
                "encrypt framebuffer/input traffic. Consider VeNCrypt, TLS, SSH, or a VPN."
            )
        if self.tls_context is not None:
            self.logger.info(
                "Legacy direct TLS transport enabled (minimum TLS %s)",
                self.settings.security.tls_minimum_version,
            )
        if self.vencrypt_server is not None:
            self.logger.info(
                "VeNCrypt 0.2 enabled: subtypes=%s, require_encrypted_transport=%s",
                ",".join(str(value) for value in self.vencrypt_subtypes),
                self.settings.security.require_encrypted_transport,
            )
        self._log_capture_probe()

    def _load_config(self, config_file: str | Path) -> dict:
        """Load configuration and fail closed on any error."""
        try:
            config = load_config_file(config_file)
        except Exception as exc:
            raise ConfigurationError(
                f"Failed to load secure server configuration from {config_file}: {exc}"
            ) from exc
        logging.info("Configuration loaded from %s", config_file)
        return config

    def _log_capture_probe(self) -> None:
        """Optionally benchmark startup capture cost for the active backend."""
        if self.capture_probe_frames <= 0:
            return
        if not hasattr(self.screen_capture, 'benchmark_capture'):
            return

        native_bgr0 = {
            'bits_per_pixel': 32,
            'depth': 24,
            'big_endian_flag': 0,
            'true_colour_flag': 1,
            'red_max': 255,
            'green_max': 255,
            'blue_max': 255,
            'red_shift': 16,
            'green_shift': 8,
            'blue_shift': 0,
        }
        try:
            stats = self.screen_capture.benchmark_capture(
                native_bgr0,
                iterations=self.capture_probe_frames,
            )
        except Exception as exc:
            self.logger.warning("Capture probe failed: %s", exc)
            return

        if int(stats.get('iterations', 0)) <= 0:
            self.logger.warning("Capture probe did not produce any frames")
            return

        avg_ms = float(stats.get('avg_ms', 0.0))
        self.logger.info(
            "Capture probe: backend=%s, %sx%s, avg=%.2fms, min=%.2fms, max=%.2fms, fps=%.1f",
            stats.get('backend', 'unknown'),
            stats.get('width', 0),
            stats.get('height', 0),
            avg_ms,
            float(stats.get('min_ms', 0.0)),
            float(stats.get('max_ms', 0.0)),
            float(stats.get('fps', 0.0)),
        )
        if avg_ms >= self.capture_probe_warn_ms:
            self.logger.warning(
                "Capture backend is averaging %.2fms per frame; an advanced Windows pipeline "
                "(DXGI Desktop Duplication / mirror-driver style) is likely worth evaluating.",
                avg_ms,
            )

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
            root_logger = logging.getLogger()
            target_path = str(Path(log_file).resolve())
            existing = [
                handler for handler in root_logger.handlers
                if isinstance(handler, logging.FileHandler)
                and Path(getattr(handler, 'baseFilename', '')).resolve() == Path(target_path)
            ]
            if not existing:
                handler = logging.FileHandler(log_file)
                handler.setFormatter(logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                ))
                root_logger.addHandler(handler)

    def _setup_health_checks(self):
        """Register liveness checks only; capacity is reported as readiness."""
        def check_socket() -> bool:
            try:
                return self.server_socket.fileno() != -1
            except OSError:
                return False

        def check_capture() -> bool:
            backend = getattr(self.screen_capture, "_backend", None)
            if backend is None:
                return False
            try:
                return bool(backend.healthcheck())
            except Exception:
                return False

        self.health_checker.register_check('socket', check_socket)
        self.health_checker.register_check('capture', check_capture)

    def start(self):
        """Start accepting client connections."""
        self.logger.info("%s started", SERVER_NAME)

        if self.enable_health_checks:
            self.health_checker.start()
        if self.capture_producer is not None:
            self.capture_producer.start()

        try:
            while not self.shutdown_handler.is_shutting_down():
                try:
                    client_socket, addr = self.server_socket.accept()
                    client_id = f"{addr[0]}:{addr[1]}"

                    if not self.per_ip_limiter.acquire(addr[0]):
                        self.logger.warning(
                            "Per-IP connection limit reached for %s, rejecting %s",
                            addr[0], addr,
                        )
                        client_socket.close()
                        continue

                    if not self.connection_limiter.acquire(client_id, timeout=0.1):
                        self.per_ip_limiter.release(addr[0])
                        self.logger.warning("Connection limit reached, rejecting %s", addr)
                        client_socket.close()
                        continue

                    self.logger.info("New connection from %s", addr)
                    thread = threading.Thread(
                        target=self._handle_client_wrapper,
                        args=(client_socket, addr, client_id),
                        name=f"Client-{client_id}",
                        daemon=False,
                    )
                    with self._client_registry_lock:
                        self._all_client_sockets[client_id] = client_socket
                        self._client_threads[client_id] = thread
                    thread.start()

                except socket.timeout:
                    continue
                except OSError as exc:
                    if self.shutdown_handler.is_shutting_down():
                        break
                    self.logger.error("Socket error: %s", exc)
                    time.sleep(0.1)

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        finally:
            self.shutdown_handler.shutdown()
            self.logger.info("Server stopped")

    def _handle_client_wrapper(self, client_socket: socket.socket,
                               addr: tuple, client_id: str):
        """Wrapper for client handling with deterministic cleanup."""
        try:
            self.handle_client(client_socket, addr, client_id)
        finally:
            self.connection_limiter.release(client_id)
            self.per_ip_limiter.release(addr[0])
            with self._client_registry_lock:
                self._all_client_sockets.pop(client_id, None)
                self._client_threads.pop(client_id, None)

    def handle_client(self, client_socket: socket.socket,
                     addr: tuple, client_id: str):
        """Handle a single client connection"""
        conn_metrics: ConnectionMetrics | None = None
        parallel_encoder = None
        registered_client_socket = False
        unauthenticated_slot_acquired = False

        try:
            auth_decision = self.auth_rate_limiter.check(addr[0])
            if not auth_decision.allowed:
                self.logger.warning(
                    "Temporarily rejecting %s after repeated authentication failures; retry in %.2fs",
                    addr[0], auth_decision.retry_after,
                )
                return

            if not self.unauthenticated_limiter.acquire(client_id, timeout=0.1):
                self.logger.warning("Pre-authentication connection limit reached for %s", addr)
                return
            unauthenticated_slot_acquired = True

            if self.tls_context is not None:
                try:
                    client_socket.settimeout(self.handshake_timeout)
                    client_socket = self.tls_context.wrap_socket(
                        client_socket,
                        server_side=True,
                        do_handshake_on_connect=False,
                    )
                    with self._client_registry_lock:
                        self._all_client_sockets[client_id] = client_socket
                    client_socket.do_handshake()
                except (ssl.SSLError, OSError) as exc:
                    self.logger.warning("TLS handshake failed for %s: %s", addr, exc)
                    return

            # Detect network profile for performance optimization
            if self.network_profile_override:
                network_profile = NetworkProfile(self.network_profile_override)
            else:
                network_profile = detect_network_profile(addr[0])
            is_localhost = network_profile == NetworkProfile.LOCALHOST
            is_lan = network_profile == NetworkProfile.LAN
            self.logger.info(f"Connection from {addr[0]}: network profile = {network_profile.value}")

            try:
                client_socket.settimeout(self.handshake_timeout)
            except Exception as e:
                self.logger.warning(f"Could not set handshake timeout: {e}")

            # Enable TCP_NODELAY for all connections (VNC is interactive;
            # Nagle's algorithm only adds latency with zero benefit)
            try:
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception as e:
                self.logger.warning(f"Could not set TCP_NODELAY: {e}")

            # Set socket send buffer size based on network profile
            if not is_localhost:
                try:
                    sndbuf = 2097152 if is_lan else 262144  # 2MB LAN, 256KB WAN
                    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf)
                except Exception as e:
                    self.logger.warning(f"Could not set SO_SNDBUF: {e}")

            # Register connection metrics
            if self.metrics:
                conn_metrics = self.metrics.register_connection(client_id)

            # Optional WebSocket support (for browser/noVNC clients)
            is_websocket_transport = False
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
                            max_message_bytes=self.websocket_max_message_bytes,
                            allowed_origins=self.websocket_allowed_origins,
                            max_buffer_bytes=self.websocket_max_buffer_bytes,
                        )
                        is_websocket_transport = True
                        with self._client_registry_lock:
                            self._all_client_sockets[client_id] = client_socket
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
                security = protocol.negotiate_security(
                    client_socket,
                    self.password,
                    read_only_password=self.read_only_password,
                    allow_tight_security=self.enable_tight_security,
                    vencrypt_server=(
                        None if is_websocket_transport else self.vencrypt_server
                    ),
                    require_encrypted_transport=(
                        self.settings.security.require_encrypted_transport
                        and self.tls_context is None
                    ),
                )

            if security.transport_socket is not None:
                client_socket = security.transport_socket
                with self._client_registry_lock:
                    self._all_client_sockets[client_id] = client_socket

            # Step 3: Authentication
            view_only_session = False
            if security.needs_auth:
                auth_handler = VNCAuth(self.password, self.read_only_password)
                auth_success, view_only_session = auth_handler.authenticate_with_access(client_socket)
                if auth_success or security.send_security_result_on_failure:
                    protocol.send_security_result(client_socket, auth_success)

                if not auth_success:
                    delay = self.auth_rate_limiter.record_failure(addr[0])
                    self.logger.warning("Client %s authentication failed", addr)
                    if self.metrics:
                        self.metrics.record_failed_auth()
                    if delay > 0:
                        time.sleep(delay)
                    return
                self.auth_rate_limiter.record_success(addr[0])
            else:
                if security.send_security_result_on_success:
                    protocol.send_security_result(client_socket, True)

            if unauthenticated_slot_acquired:
                self.unauthenticated_limiter.release(client_id)
                unauthenticated_slot_acquired = False

            try:
                client_socket.settimeout(self.client_socket_timeout)
            except Exception as exc:
                self.logger.warning("Could not set authenticated client timeout: %s", exc)

            self.logger.info(f"Client {addr} authenticated successfully")
            if view_only_session:
                self.logger.info("Client %s authenticated with read-only access", client_id)

            # Step 4: ClientInit
            shared_flag = protocol.receive_client_init(client_socket)
            self.logger.debug(f"Client shared flag: {shared_flag}")
            self._register_authenticated_client_socket(client_id, client_socket)
            registered_client_socket = True
            if shared_flag == 0:
                self.logger.info(
                    "Client %s requested exclusive access; disconnecting other clients",
                    client_id,
                )
                self._disconnect_other_authenticated_clients(client_id)

            # Step 5: ServerInit
            screen_capture = self.screen_capture
            input_handler = self.input_handler

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
            initial_snapshot = self._capture_frame_with_generation(
                screen_capture, current_pixel_format
            )
            initial_frame = initial_snapshot.frame
            initial_result = initial_frame.result
            if (
                initial_result.pixel_data is None
                or initial_result.width <= 0
                or initial_result.height <= 0
            ):
                raise VNCConnectionError("Initial screen capture failed")

            width, height = initial_result.width, initial_result.height

            protocol.send_server_init(
                client_socket, width, height,
                current_pixel_format, SERVER_NAME
            )
            if security.tight_enabled:
                protocol.send_tight_interaction_caps(client_socket)

            cursor_capture = None
            cursor_encoder = None
            if self.enable_cursor_encoding:
                cursor_capture = SystemCursorCapture(
                    scale_factor=self.scale_factor,
                    monitor=getattr(screen_capture, "monitor", 0),
                )
                if cursor_capture.enabled:
                    cursor_encoder = CursorEncoder()

            # Initialize encoders and change detection
            # Enable advanced encodings from config
            enable_tight = self.config.get('enable_tight_encoding', True)
            enable_jpeg = self.config.get('enable_jpeg_encoding', True)
            enable_h264 = self.config.get('enable_h264_encoding', False)
            disable_tight_for_ultravnc = self.config.get('tight_disable_for_ultravnc', False)

            encoder_manager = EncoderManager(
                enable_tight=enable_tight,
                enable_jpeg=enable_jpeg,
                enable_h264=enable_h264,
                disable_tight_for_ultravnc=disable_tight_for_ultravnc,
                enable_copyrect=self.enable_copyrect_encoding,
                enable_zrle=self.enable_zrle_encoding,
            )
            client_encodings: list[int] = [0]  # Default: Raw encoding
            self.logger.info(
                f"Server rectangle encodings: {format_encoding_list(set(encoder_manager.encoders.keys()))}"
            )
            self.logger.info(
                f"Initial client rectangle encodings: {format_encoding_list(client_encodings)}"
            )

            # For localhost, disable change detection (overhead not worth it with high bandwidth)
            use_change_detection = self.enable_region_detection and not is_localhost
            change_detector = AdaptiveChangeDetector(width, height) if use_change_detection else None

            # Initialize parallel encoder for multi-threaded encoding
            use_parallel = self.config.get('enable_parallel_encoding', True)
            if use_parallel:
                try:
                    from vnc_lib.parallel_encoder import ParallelEncoder
                    parallel_encoder = ParallelEncoder(
                        max_workers=self.encoding_workers,
                        executor=self.encoding_executor,
                        encoded_region_cache=self.encoded_region_cache,
                    )
                    self.logger.info(
                        "Parallel encoding enabled with shared %d-worker executor",
                        parallel_encoder.max_workers,
                    )
                except ImportError as e:
                    self.logger.warning(f"Parallel encoding unavailable: {e}")

            if is_localhost and self.enable_region_detection:
                self.logger.info("Change detection disabled for localhost connection (optimization)")

            # Main message loop. Keep all mutable per-client state in one object.
            session = ClientSessionState(
                client_id=client_id,
                pixel_format=current_pixel_format,
                encodings=client_encodings,
                fb_width=width,
                fb_height=height,
                encoder_manager=encoder_manager,
                network_profile=network_profile,
                view_only=view_only_session,
                change_detector=change_detector,
                conn_metrics=conn_metrics,
                cursor_capture=cursor_capture,
                cursor_encoder=cursor_encoder,
                parallel_encoder=parallel_encoder,
                last_frame_generation=-1,
            )
            self._client_message_loop(client_socket, protocol, session)

        except Exception as e:
            self.logger.error(f"Error handling client {addr}: {e}", exc_info=True)
            if conn_metrics:
                conn_metrics.record_error()
        finally:
            if unauthenticated_slot_acquired:
                self.unauthenticated_limiter.release(client_id)
            if parallel_encoder:
                try:
                    parallel_encoder.shutdown(wait=False)
                except Exception:
                    pass
            try:
                client_socket.close()
            except Exception:
                pass
            if registered_client_socket:
                self._unregister_authenticated_client_socket(client_id)
            self._release_input_control(client_id)
            if self.metrics:
                self.metrics.unregister_connection(client_id)
            self.logger.info(f"Client {addr} disconnected")


    def _coerce_allowed_origins(self, raw_origins) -> tuple[str, ...]:
        """Normalize configured WebSocket origins into an immutable tuple."""
        if raw_origins is None:
            return ()
        if isinstance(raw_origins, str):
            items = [raw_origins]
        else:
            items = list(raw_origins)
        normalized = []
        for origin in items:
            text = str(origin).strip().rstrip('/').lower()
            if text:
                normalized.append(text)
        return tuple(dict.fromkeys(normalized))


    def _cleanup(self):
        """Gracefully stop listeners, sessions, workers, capture and health checks."""
        self.logger.info("Cleaning up server resources...")

        # 1. Stop accepting new connections.
        try:
            self.server_socket.close()
        except OSError:
            pass

        # 2. Stop producing new desktop frames.
        if self.capture_producer is not None:
            self.capture_producer.stop(timeout=3.0)

        # 3. Interrupt all active and pre-authentication client sessions.
        with self._client_registry_lock:
            sockets = list(self._all_client_sockets.values())
            threads = list(self._client_threads.values())
        for client_socket in sockets:
            try:
                shutdown = getattr(client_socket, 'shutdown', None)
                if callable(shutdown):
                    shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                client_socket.close()
            except Exception:
                pass

        # 4. Wait briefly for non-daemon session threads to release their state.
        deadline = time.monotonic() + 3.0
        current = threading.current_thread()
        for thread in threads:
            if thread is current or not thread.is_alive():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

        # 5. Stop background health checks and shared encoding workers.
        self.health_checker.stop()
        try:
            self.encoding_executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.encoding_executor.shutdown(wait=False)
        self.screen_capture.close_current_thread_sessions()

        if self.encoded_region_cache is not None:
            self.encoded_region_cache.clear()

        if self.metrics:
            summary = self.metrics.format_summary()
            self.logger.info(f"Final metrics:\n{summary}")

    def get_status(self) -> dict:
        """Return liveness metrics separately from readiness/capacity."""
        active = self.connection_limiter.get_active_count()
        status = self.metrics.get_summary() if self.metrics else {}
        health = self.health_checker.last_status
        if self.encoded_region_cache is not None:
            status['encoded_region_cache'] = self.encoded_region_cache.stats
        status['adaptive_streaming_enabled'] = self.enable_adaptive_streaming
        status.update({
            'version': __version__,
            'active_connections': active,
            'max_connections': self.max_connections,
            'ready': active < self.max_connections and not self.shutdown_handler.is_shutting_down(),
            'saturated': active >= self.max_connections,
            'healthy': health.is_healthy if health is not None else True,
        })
        return status


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the legacy CLI parser."""
    parser = argparse.ArgumentParser(description=SERVER_NAME)
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to configuration file (default: {DEFAULT_CONFIG_PATH.as_posix()})",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    return parser


def run_server(config_file: str | Path | None = None,
               log_level: str | None = None) -> "VNCServerV3":
    """Create and start the server from CLI-style parameters."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    server = VNCServerV3(config_file=config_file or DEFAULT_CONFIG_PATH)
    if log_level:
        level_name = str(log_level).upper()
        level = getattr(logging, level_name, None)
        if isinstance(level, int):
            logging.getLogger().setLevel(level)
            server.logger.info(f"Log level overridden from CLI: {level_name}")
        else:
            server.logger.warning(
                f"Invalid CLI log level '{log_level}', keeping configured level"
            )
    server.start()
    return server


def main(argv: list[str] | None = None):
    """Main entry point"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    run_server(config_file=args.config, log_level=args.log_level)


VNCServer = VNCServerV3


if __name__ == '__main__':
    main()
