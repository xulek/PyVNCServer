"""Session/runtime helpers separated from server lifecycle orchestration."""

import socket
import struct
import time

from pyvncserver._core.capture_backends import CaptureFrame, CaptureMetadata, CaptureMoveRect
from pyvncserver._core.cursor import CursorEncoder, SystemCursorCapture
from pyvncserver._core.encodings import EncoderManager, EncodingNotSuitable, encoding_name
from pyvncserver._core.io_utils import recv_exact
from pyvncserver._core.protocol import RFBProtocol
from pyvncserver._core.screen_capture import ScreenCapture
from pyvncserver._core.server_utils import NetworkProfile
from pyvncserver._core.types import is_valid_pixel_format
from pyvncserver.platform.producer import FrameSnapshot


class SessionRuntimeMixin:
    """Framebuffer, encoder, input-control and request-coalescing helpers."""

    def _is_supported_pixel_format(self, pixel_format: dict) -> bool:
        """Restrict runtime to formats the server can actually encode correctly."""
        if not is_valid_pixel_format(pixel_format):
            return False
        if int(pixel_format.get('true_colour_flag', 0)) != 1:
            return False
        if int(pixel_format.get('big_endian_flag', 0)) != 0:
            return False

        bpp = int(pixel_format.get('bits_per_pixel', 0))
        depth = int(pixel_format.get('depth', 0))
        if bpp == 32 and depth != 24:
            return False
        if bpp not in (8, 16, 32):
            return False

        for max_key, shift_key in (
            ('red_max', 'red_shift'),
            ('green_max', 'green_shift'),
            ('blue_max', 'blue_shift'),
        ):
            channel_max = int(pixel_format.get(max_key, 0))
            channel_shift = int(pixel_format.get(shift_key, -1))
            if channel_shift < 0:
                return False
            if channel_max.bit_length() + channel_shift > bpp:
                return False

        return True

    def _is_native_bgr0_pixel_format(self, pixel_format: dict | None) -> bool:
        """Return True only for the server's native 32bpp little-endian BGR0 layout."""
        if not pixel_format:
            return False
        return (
            int(pixel_format.get('bits_per_pixel', 0)) == 32
            and int(pixel_format.get('depth', 0)) == 24
            and int(pixel_format.get('true_colour_flag', 0)) == 1
            and int(pixel_format.get('big_endian_flag', 0)) == 0
            and int(pixel_format.get('red_max', 0)) == 255
            and int(pixel_format.get('green_max', 0)) == 255
            and int(pixel_format.get('blue_max', 0)) == 255
            and int(pixel_format.get('red_shift', -1)) == 16
            and int(pixel_format.get('green_shift', -1)) == 8
            and int(pixel_format.get('blue_shift', -1)) == 0
        )

    def _encoding_supported_for_pixel_format(self, encoding_type: int,
                                             pixel_format: dict | None) -> bool:
        """Limit encoder selection to wire formats the current implementation really supports."""
        if encoding_type in (7, 21, 50):
            return self._is_native_bgr0_pixel_format(pixel_format)
        return True

    def _filter_encodings_for_pixel_format(self, client_encodings: list[int],
                                           encoder_manager: EncoderManager,
                                           pixel_format: dict | None) -> tuple[list[int], list[int]]:
        """Drop server-supported encodings that are incompatible with the current pixel format."""
        filtered: list[int] = []
        dropped: list[int] = []
        for enc_type in client_encodings:
            if enc_type in encoder_manager.encoders and not self._encoding_supported_for_pixel_format(
                enc_type, pixel_format
            ):
                dropped.append(enc_type)
                continue
            filtered.append(enc_type)
        return filtered, dropped

    def _is_parallel_safe_encoding(self, encoding_type: int) -> bool:
        """Allow parallel encoding only for stateless encoder implementations."""
        return encoding_type in {0, 2, 5}

    def _reset_stateful_encoders(self, encoder_manager: EncoderManager) -> None:
        """Reset encoder state that depends on the client's framebuffer contents."""
        copyrect_encoder = encoder_manager.encoders.get(1)
        if copyrect_encoder is not None and hasattr(copyrect_encoder, 'reset'):
            try:
                copyrect_encoder.reset()
            except Exception:
                pass

    def _commit_frame_state(self, encoder_manager: EncoderManager,
                            pixel_data: bytes, fb_width: int, fb_height: int,
                            bytes_per_pixel: int) -> None:
        """Commit the framebuffer that the client now holds after a successful update."""
        copyrect_encoder = encoder_manager.encoders.get(1)
        if copyrect_encoder is not None and hasattr(copyrect_encoder, 'commit_frame'):
            try:
                copyrect_encoder.commit_frame(pixel_data, fb_width, fb_height, bytes_per_pixel)
            except Exception:
                pass

    def _register_authenticated_client_socket(self, client_id: str, client_socket: socket.socket) -> None:
        """Track authenticated clients so shared-flag=0 can evict peers per RFC 6143."""
        with self._client_registry_lock:
            self._authenticated_client_sockets[client_id] = client_socket

    def _unregister_authenticated_client_socket(self, client_id: str) -> None:
        """Remove a client from the authenticated socket registry."""
        with self._client_registry_lock:
            self._authenticated_client_sockets.pop(client_id, None)

    def _disconnect_other_authenticated_clients(self, keep_client_id: str) -> None:
        """Close all authenticated client sockets except the requesting client."""
        with self._client_registry_lock:
            to_close = [
                (client_id, sock)
                for client_id, sock in self._authenticated_client_sockets.items()
                if client_id != keep_client_id
            ]
            for client_id, _ in to_close:
                self._authenticated_client_sockets.pop(client_id, None)

        for client_id, client_socket in to_close:
            try:
                self.logger.info(
                    "Disconnecting client %s due to exclusive shared-flag=0 request",
                    client_id,
                )
                try:
                    client_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client_socket.close()
            except OSError:
                pass

    def _try_acquire_input_control(self, client_id: str) -> bool:
        """Grant input control to exactly one client unless policy allows sharing."""
        if self.input_control_policy != 'single-controller':
            return True

        with self._input_control_lock:
            if self._input_controller_client_id in (None, client_id):
                newly_assigned = self._input_controller_client_id is None
                self._input_controller_client_id = client_id
                if newly_assigned:
                    self._input_control_rejections_logged.discard(client_id)
                    self.logger.info("Input control assigned to %s", client_id)
                return True

            controller = self._input_controller_client_id

        if client_id not in self._input_control_rejections_logged:
            self._input_control_rejections_logged.add(client_id)
            self.logger.info(
                "Ignoring input from %s because %s currently controls the server",
                client_id,
                controller,
            )
        return False

    def _release_input_control(self, client_id: str) -> None:
        """Release single-controller input ownership on disconnect."""
        if self.input_control_policy != 'single-controller':
            return

        with self._input_control_lock:
            self._input_control_rejections_logged.discard(client_id)
            if self._input_controller_client_id == client_id:
                self._input_controller_client_id = None
                self.logger.info("Input control released from %s", client_id)

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

    def _split_rectangles_for_encoding(self, encoding_type: int, x: int, y: int,
                                       width: int, height: int) -> list[tuple[int, int, int, int]]:
        """
        Split large rectangles the way TightVNC does for Tight encoding.

        Reference TightVNC aggressively splits large Tight rectangles before encoding,
        while ZRLE keeps the original rectangle and handles 64x64 tiling internally.
        """
        if width <= 0 or height <= 0:
            return []

        # RRE is intentionally bounded to avoid an expensive Python scan over a
        # full desktop. Split it into protocol-independent rectangles that stay
        # within RREEncoder.DEFAULT_MAX_PIXELS; individual tiles can still fall
        # back to another client-supported encoding when RRE would expand data.
        if encoding_type == 2:
            tile_width = 256
            tile_height = 256
            return [
                (x0, y0, min(tile_width, x + width - x0), min(tile_height, y + height - y0))
                for y0 in range(y, y + height, tile_height)
                for x0 in range(x, x + width, tile_width)
            ]

        if encoding_type != 7:
            return [(x, y, width, height)]

        max_rect_size = 524288
        max_rect_width = 2048
        if width <= 2048 and width * height <= max_rect_size:
            return [(x, y, width, height)]

        split_rects: list[tuple[int, int, int, int]] = []
        step_width = min(max_rect_width, width)
        step_height = max(1, max_rect_size // max(1, step_width))

        for y0 in range(y, y + height, step_height):
            h = min(step_height, (y + height) - y0)
            for x0 in range(x, x + width, step_width):
                w = min(step_width, (x + width) - x0)
                split_rects.append((x0, y0, w, h))
        return split_rects

    def _capture_frame(self, screen_capture: ScreenCapture, pixel_format: dict):
        """Capture a frame for a single client connection."""
        if hasattr(screen_capture, 'capture_frame'):
            return screen_capture.capture_frame(pixel_format)
        result = screen_capture.capture_fast(pixel_format)
        return CaptureFrame(result=result, metadata=CaptureMetadata(backend_name="legacy"))

    def _capture_frame_with_generation(self, screen_capture: ScreenCapture,
                                       pixel_format: dict,
                                       since_generation: int | None = None) -> FrameSnapshot:
        """Return a frame plus a producer generation identifier."""
        if self.capture_producer is not None:
            return self.capture_producer.get_frame(
                pixel_format, timeout=self.handshake_timeout,
                since_generation=since_generation,
            )
        return FrameSnapshot(
            generation=time.monotonic_ns(),
            frame=self._capture_frame(screen_capture, pixel_format),
        )

    def _resolve_incremental_update_hints(
        self,
        protocol: RFBProtocol,
        client_encodings: list[int],
        capture_metadata: CaptureMetadata,
        request_region: tuple[int, int, int, int],
    ) -> tuple[list[tuple[int, int, int, int]] | None, list[tuple[int, int, int, int, int, bytes]]]:
        """Use backend-supplied dirty/move hints when available."""
        changed_regions = capture_metadata.dirty_regions
        if changed_regions is not None:
            changed_regions = self._intersect_regions(changed_regions, request_region)

        copyrect_rectangles: list[tuple[int, int, int, int, int, bytes]] = []
        if (
            self.enable_copyrect_encoding
            and protocol.ENCODING_COPYRECT in client_encodings
            and capture_metadata.move_rects
        ):
            copyrect_rectangles = self._build_copyrect_rectangles_from_moves(
                capture_metadata.move_rects,
                request_region,
            )

        return changed_regions, copyrect_rectangles

    def _build_copyrect_rectangles_from_moves(
        self,
        move_rects: list[CaptureMoveRect],
        request_region: tuple[int, int, int, int],
    ) -> list[tuple[int, int, int, int, int, bytes]]:
        """Translate backend move hints into RFB CopyRect rectangles."""
        req_x, req_y, req_w, req_h = request_region
        req_x2 = req_x + req_w
        req_y2 = req_y + req_h
        rectangles: list[tuple[int, int, int, int, int, bytes]] = []

        for move in move_rects:
            dst_x1 = max(move.dst_x, req_x)
            dst_y1 = max(move.dst_y, req_y)
            dst_x2 = min(move.dst_x + move.width, req_x2)
            dst_y2 = min(move.dst_y + move.height, req_y2)
            if dst_x1 >= dst_x2 or dst_y1 >= dst_y2:
                continue

            offset_x = dst_x1 - move.dst_x
            offset_y = dst_y1 - move.dst_y
            src_x = move.src_x + offset_x
            src_y = move.src_y + offset_y
            width = dst_x2 - dst_x1
            height = dst_y2 - dst_y1
            rectangles.append(
                (
                    dst_x1,
                    dst_y1,
                    width,
                    height,
                    1,
                    struct.pack(">HH", src_x, src_y),
                )
            )

        return rectangles

    def _configure_lan_encoders(self, encoder_manager: EncoderManager,
                                jpeg_quality: int) -> None:
        """Apply LAN-specific encoder settings."""
        zrle_encoder = encoder_manager.encoders.get(16)
        if zrle_encoder is not None:
            try:
                if hasattr(zrle_encoder, 'set_compression_level'):
                    zrle_encoder.set_compression_level(self.lan_zrle_compression_level)
                elif hasattr(zrle_encoder, 'compression_level'):
                    zrle_encoder.compression_level = self.lan_zrle_compression_level
            except Exception:
                pass

        tight_encoder = encoder_manager.encoders.get(7)
        if tight_encoder is not None and hasattr(tight_encoder, 'set_compression_level'):
            try:
                tight_encoder.set_compression_level(self.lan_tight_compression_level)
            except Exception:
                pass

        zlib_encoder = encoder_manager.encoders.get(6)
        if zlib_encoder is not None:
            try:
                if hasattr(zlib_encoder, 'set_compression_level'):
                    zlib_encoder.set_compression_level(self.lan_zlib_compression_level)
                elif hasattr(zlib_encoder, 'compression_level'):
                    zlib_encoder.compression_level = self.lan_zlib_compression_level
            except Exception:
                pass

        jpeg_encoder = encoder_manager.encoders.get(21)
        if jpeg_encoder is not None and hasattr(jpeg_encoder, 'set_quality'):
            try:
                jpeg_encoder.set_quality(jpeg_quality)
            except Exception:
                pass

    def _prepare_encoder_for_send(self, encoding_type: int, encoder,
                                  lan_jpeg_quality: int) -> None:
        """Prepare encoder before a frame/region encode."""
        if encoding_type != 21:
            return
        if hasattr(encoder, 'set_quality'):
            try:
                encoder.set_quality(lan_jpeg_quality)
            except Exception:
                pass

    def _log_selected_region_encodings(self, encoding_types: list[int]) -> None:
        """Log the actually used region encodings for a framebuffer update."""
        if not encoding_types:
            return
        enc_counts: dict[int, int] = {}
        for enc_type in encoding_types:
            enc_counts[enc_type] = enc_counts.get(enc_type, 0) + 1
        enc_summary = ", ".join(
            f"{encoding_name(enc)} ({enc}) x{count}"
            for enc, count in sorted(enc_counts.items())
        )
        self.logger.info("Selected region encodings: %s", enc_summary)

    def _log_selected_encoding(self, encoding_type: int, content_type: str) -> None:
        """Log the actually used rectangle encoding for a framebuffer update."""
        self.logger.info(
            "Selected encoding: %s (%d) for content type: %s",
            encoding_name(encoding_type),
            encoding_type,
            content_type,
        )

    def _build_cursor_pseudo_rectangles(
        self,
        protocol: RFBProtocol,
        client_encodings: list[int],
        current_pixel_format: dict,
        cursor_capture: SystemCursorCapture | None,
        cursor_encoder: CursorEncoder | None,
        last_pointer_pos: tuple[int, int] | None,
    ) -> tuple[list[tuple[int, int, int, int, int, bytes]], tuple[int, int] | None]:
        """Build RichCursor/PointerPos pseudo-rectangles for the current frame."""
        if (
            not self.enable_cursor_encoding
            or cursor_capture is None
            or cursor_encoder is None
        ):
            return [], last_pointer_pos

        rectangles: list[tuple[int, int, int, int, int, bytes]] = []
        bytes_per_pixel = max(1, current_pixel_format.get("bits_per_pixel", 32) // 8)

        if protocol.ENCODING_CURSOR in client_encodings:
            cursor_data = cursor_capture.capture_cursor()
            if cursor_data is not None and cursor_encoder.has_cursor_changed(cursor_data):
                hotspot_x, hotspot_y, encoded_data = cursor_encoder.encode_cursor(
                    cursor_data,
                    bytes_per_pixel=bytes_per_pixel,
                )
                rectangles.append(
                    (
                        hotspot_x,
                        hotspot_y,
                        cursor_data.width,
                        cursor_data.height,
                        protocol.ENCODING_CURSOR,
                        encoded_data,
                    )
                )

        if protocol.ENCODING_POINTER_POS in client_encodings:
            pointer_pos = cursor_capture.get_pointer_position()
            if pointer_pos is not None and pointer_pos != last_pointer_pos:
                rectangles.append(
                    (
                        pointer_pos[0],
                        pointer_pos[1],
                        0,
                        0,
                        protocol.ENCODING_POINTER_POS,
                        b"",
                    )
                )
                last_pointer_pos = pointer_pos

        return rectangles, last_pointer_pos

    def _configure_tight_compatibility(self, encoder_manager: EncoderManager,
                                       client_encodings: list[int] | None = None) -> None:
        """Keep Tight zlib streams synchronized, including UltraVNC compatibility."""
        tight_encoder = encoder_manager.encoders.get(7)
        if tight_encoder is None or not hasattr(tight_encoder, 'set_stream_reset_mode'):
            return

        encodings = client_encodings or []
        # UltraVNC advertises its private Ultra encoding (9) even when the user
        # explicitly selects Tight. Per-rectangle reset mode is slightly less
        # bandwidth-efficient but avoids stale persistent-stream state when the
        # viewer changes encoding while a connection is already active.
        ultravnc_like = 9 in encodings
        enabled = bool(self.tight_stream_reset_for_ultravnc or ultravnc_like)

        try:
            tight_encoder.set_stream_reset_mode(enabled)
            # SetEncodings may arrive after Tight data has already been exchanged.
            # Explicitly reset all four wire streams before the next Tight rectangle.
            if 7 in encodings and hasattr(tight_encoder, 'request_stream_reset'):
                tight_encoder.request_stream_reset()
            if ultravnc_like and 7 in encodings:
                self.logger.debug(
                    "UltraVNC Tight compatibility enabled (Ultra encoding marker present)"
                )
        except Exception as exc:
            self.logger.debug("Unable to configure Tight compatibility: %s", exc)

    def _encode_with_selected_encoder(self, encoding_type: int, encoder,
                                      pixel_data: bytes, width: int, height: int,
                                      lan_jpeg_quality: int, bytes_per_pixel: int,
                                      pixel_format: dict | None) -> bytes:
        """Encode bytes with an already-selected encoder instance."""
        self._prepare_encoder_for_send(encoding_type, encoder, lan_jpeg_quality)
        if encoding_type == 16:
            return encoder.encode(
                pixel_data, width, height, bytes_per_pixel, pixel_format=pixel_format
            )
        return encoder.encode(pixel_data, width, height, bytes_per_pixel)

    def _select_encoder_for_update(self,
                                   encoder_manager: EncoderManager,
                                   client_encodings: list[int],
                                   network_profile: NetworkProfile,
                                   width: int,
                                   height: int,
                                   fb_width: int,
                                   fb_height: int,
                                   content_type: str,
                                   allow_jpeg: bool = True,
                                   allow_zlib: bool = True,
                                   allow_copyrect: bool = True,
                                   bytes_per_pixel: int | None = None,
                                   pixel_format: dict | None = None) -> tuple[int, object]:
        """
        Pick the first usable encoding in client-preferred order.
        """
        ordered_client_encodings, _ = self._filter_encodings_for_pixel_format(
            client_encodings, encoder_manager, pixel_format
        )
        encoders = encoder_manager.encoders
        def available(enc_type: int) -> bool:
            if not self._encoding_supported_for_pixel_format(enc_type, pixel_format):
                return False
            if enc_type == 1 and not allow_copyrect:
                return False
            if enc_type == 21 and not allow_jpeg:
                return False
            if enc_type == 6 and not allow_zlib:
                return False
            if enc_type == 21 and bytes_per_pixel not in (3, 4):
                return False
            return enc_type in encoders

        for enc_type in ordered_client_encodings:
            if available(enc_type):
                return enc_type, encoders[enc_type]

        # RFC 6143 allows Raw even if not listed explicitly by the client.
        if 0 in encoders and self._encoding_supported_for_pixel_format(0, pixel_format):
            return 0, encoders[0]

        return encoder_manager.get_best_encoder(
            ordered_client_encodings, content_type=content_type
        )

    def _encode_rectangle_for_update(self,
                                     encoder_manager: EncoderManager,
                                     client_encodings: list[int],
                                     network_profile: NetworkProfile,
                                     x: int,
                                     y: int,
                                     width: int,
                                     height: int,
                                     fb_width: int,
                                     fb_height: int,
                                     content_type: str,
                                     pixel_data: bytes,
                                     full_frame: bytes,
                                     request_region: tuple[int, int, int, int] | None,
                                     allow_jpeg: bool = True,
                                     allow_zlib: bool = True,
                                     allow_copyrect: bool = True,
                                     lan_jpeg_quality: int = 75,
                                     bytes_per_pixel: int | None = None,
                                     pixel_format: dict | None = None) -> tuple[int, object, bytes]:
        """Encode a rectangle using the first client-preferred encoding that produces valid payload."""
        if bytes_per_pixel is None:
            bytes_per_pixel = max(1, int(pixel_format.get('bits_per_pixel', 32)) // 8) if pixel_format else 4

        ordered_client_encodings, _ = self._filter_encodings_for_pixel_format(
            client_encodings, encoder_manager, pixel_format
        )
        encoders = encoder_manager.encoders

        def available(enc_type: int) -> bool:
            if enc_type not in encoders:
                return False
            if not self._encoding_supported_for_pixel_format(enc_type, pixel_format):
                return False
            if enc_type == 1 and not allow_copyrect:
                return False
            if enc_type == 21 and (not allow_jpeg or bytes_per_pixel not in (3, 4)):
                return False
            if enc_type == 6 and not allow_zlib:
                return False
            return True

        for enc_type in ordered_client_encodings:
            if not available(enc_type):
                continue
            if enc_type == 1:
                encoder = encoders[enc_type]
                payload = encoder.encode_copyrect(
                    full_frame,
                    fb_width,
                    fb_height,
                    x,
                    y,
                    width,
                    height,
                    bytes_per_pixel,
                    request_region=request_region,
                )
                if payload is not None:
                    return enc_type, encoder, payload
                continue

            encoder = encoders[enc_type]
            cache = getattr(self, 'encoded_region_cache', None)
            cache_key = None
            if cache is not None:
                cache_key = cache.make_key(
                    enc_type,
                    pixel_data,
                    width,
                    height,
                    bytes_per_pixel,
                    pixel_format,
                    encoder_variant=(lan_jpeg_quality if enc_type == 21 else 0),
                )
                cached_payload = cache.get(cache_key)
                if cached_payload is not None:
                    return enc_type, encoder, cached_payload

            self._prepare_encoder_for_send(enc_type, encoder, lan_jpeg_quality)
            try:
                if enc_type == 16:
                    encoded_data = encoder.encode(
                        pixel_data, width, height, bytes_per_pixel, pixel_format=pixel_format
                    )
                else:
                    encoded_data = encoder.encode(
                        pixel_data, width, height, bytes_per_pixel
                    )
            except EncodingNotSuitable as exc:
                self.logger.debug(
                    "%s (%d) is not suitable for %dx%d rectangle: %s; trying next encoding",
                    encoding_name(enc_type),
                    enc_type,
                    width,
                    height,
                    exc,
                )
                continue
            if cache is not None:
                cache.put(cache_key, encoded_data)
            return enc_type, encoder, encoded_data

        raw_encoder = encoders[0]
        cache = getattr(self, 'encoded_region_cache', None)
        cache_key = None
        if cache is not None:
            cache_key = cache.make_key(
                0, pixel_data, width, height, bytes_per_pixel, pixel_format
            )
            cached_payload = cache.get(cache_key)
            if cached_payload is not None:
                return 0, raw_encoder, cached_payload
        raw_payload = raw_encoder.encode(pixel_data, width, height, bytes_per_pixel)
        if cache is not None:
            cache.put(cache_key, raw_payload)
        return 0, raw_encoder, raw_payload

    def _adjust_lan_jpeg_quality(self, current_quality: int,
                                 frame_time: float,
                                 encoded_bytes: int,
                                 original_bytes: int,
                                 target_frame_time: float) -> int:
        """Adapt JPEG quality based on frame timing and achieved compression."""
        if target_frame_time <= 0 or original_bytes <= 0:
            return current_quality

        compression_ratio = encoded_bytes / max(1, original_bytes)
        next_quality = current_quality

        if frame_time > target_frame_time * 1.35:
            next_quality -= 5
        elif frame_time > target_frame_time * 1.10:
            next_quality -= 2
        elif frame_time < target_frame_time * 0.70 and compression_ratio < 0.28:
            next_quality += 3
        elif frame_time < target_frame_time * 0.85 and compression_ratio < 0.40:
            next_quality += 1

        return max(self.lan_jpeg_quality_min, min(self.lan_jpeg_quality_max, next_quality))

    def _coalesce_framebuffer_update_requests(self, client_socket,
                                              protocol: RFBProtocol,
                                              first_request: dict) -> dict:
        """
        Coalesce queued FramebufferUpdateRequest messages and keep only newest.
        """
        latest = first_request
        if not hasattr(client_socket, 'recv'):
            return latest

        original_timeout = None
        try:
            original_timeout = client_socket.gettimeout()
            client_socket.settimeout(0.0)

            while True:
                try:
                    # FramebufferUpdateRequest is 1-byte type + 9-byte payload.
                    peek = client_socket.recv(10, socket.MSG_PEEK)
                except (BlockingIOError, InterruptedError, socket.timeout):
                    break
                except OSError:
                    break

                if len(peek) < 10 or peek[0] != protocol.MSG_FRAMEBUFFER_UPDATE_REQUEST:
                    break

                msg_type_data = recv_exact(client_socket, 1)
                if (
                    not msg_type_data
                    or msg_type_data[0] != protocol.MSG_FRAMEBUFFER_UPDATE_REQUEST
                ):
                    break

                latest = protocol.parse_framebuffer_update_request(client_socket)
        except Exception:
            # Best-effort optimization; fall back to first request.
            pass
        finally:
            if original_timeout is not None:
                try:
                    client_socket.settimeout(original_timeout)
                except Exception:
                    pass

        return latest

    def _coalesce_pointer_events(self, client_socket,
                                 protocol: RFBProtocol,
                                 first_event: dict) -> dict:
        """
        Coalesce a burst of PointerEvent messages and keep only the newest one.

        This prevents cursor "catch-up" behavior when the socket queue contains
        many stale pointer positions.
        """
        latest = first_event
        if not hasattr(client_socket, 'recv'):
            return latest

        original_timeout = None
        try:
            original_timeout = client_socket.gettimeout()
            client_socket.settimeout(0.0)

            while True:
                try:
                    # PointerEvent message is 1-byte type + 5-byte payload.
                    peek = client_socket.recv(6, socket.MSG_PEEK)
                except (BlockingIOError, InterruptedError, socket.timeout):
                    break
                except OSError:
                    break

                if len(peek) < 6 or peek[0] != protocol.MSG_POINTER_EVENT:
                    break
                if peek[1] != latest.get('button_mask', peek[1]):
                    # Preserve button transitions (press/release) as separate events.
                    break

                msg_type_data = recv_exact(client_socket, 1)
                if not msg_type_data or msg_type_data[0] != protocol.MSG_POINTER_EVENT:
                    break

                latest = protocol.parse_pointer_event(client_socket)
        except Exception:
            # Best-effort optimization; fall back to single-event handling.
            pass
        finally:
            if original_timeout is not None:
                try:
                    client_socket.settimeout(original_timeout)
                except Exception:
                    pass

        return latest

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

    def _collapse_regions_to_bounding_box(self, regions) -> list[tuple[int, int, int, int]]:
        """
        Collapse multiple regions into one bounding rectangle.

        Compatibility path for clients that behave poorly with frequent
        multi-rectangle updates.
        """
        if not regions:
            return []
        if len(regions) == 1:
            region = regions[0]
            if hasattr(region, 'x'):
                return [(int(region.x), int(region.y), int(region.width), int(region.height))]
            return [(int(region[0]), int(region[1]), int(region[2]), int(region[3]))]

        normalized: list[tuple[int, int, int, int]] = []
        for region in regions:
            if hasattr(region, 'x'):
                x, y, w, h = int(region.x), int(region.y), int(region.width), int(region.height)
            else:
                x, y, w, h = int(region[0]), int(region[1]), int(region[2]), int(region[3])
            if w > 0 and h > 0:
                normalized.append((x, y, w, h))

        if not normalized:
            return []

        left = min(r[0] for r in normalized)
        top = min(r[1] for r in normalized)
        right = max(r[0] + r[2] for r in normalized)
        bottom = max(r[1] + r[3] for r in normalized)
        if right <= left or bottom <= top:
            return []
        return [(left, top, right - left, bottom - top)]
