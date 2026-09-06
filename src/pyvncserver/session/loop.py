"""Client session message loop separated from server lifecycle orchestration."""

import socket
import time

from vnc_lib.encodings import format_encoding_list
from vnc_lib.exceptions import (
    VNCError, ProtocolError, AuthenticationError, ConnectionError as VNCConnectionError,
)
from vnc_lib.io_utils import recv_exact
from vnc_lib.protocol import RFBProtocol
from vnc_lib.server_utils import NetworkProfile, PerformanceThrottler
from pyvncserver.session_state import ClientSessionState


class SessionLoopMixin:
    """Implements the per-client RFB message pump.

    The concrete server supplies capture, encoder-selection, cursor and input
    helpers. Keeping the message pump here prevents lifecycle/orchestration
    code from becoming a multi-thousand-line god object.
    """

    def _client_message_loop(self, client_socket: socket.socket,
                            protocol: RFBProtocol,
                            session: ClientSessionState):
        """
        Enhanced client message handling loop with network-aware optimization

        Localhost optimizations:
        - Up to 120 FPS frame rate
        - Raw encoding only (no compression overhead)
        - TCP_NODELAY enabled (lower latency)
        - Change detection disabled (unnecessary overhead)

        LAN optimizations:
        - Up to 60 FPS frame rate (configurable)
        - Client-preferred encoding order with LAN-specific transport tuning
        - TCP_NODELAY enabled
        """

        screen_capture = self.screen_capture
        input_handler = self.input_handler
        current_pixel_format = session.pixel_format
        client_encodings = session.encodings
        fb_width = session.fb_width
        fb_height = session.fb_height
        encoder_manager = session.encoder_manager
        change_detector = session.change_detector
        conn_metrics = session.conn_metrics
        client_id = session.client_id
        cursor_capture = session.cursor_capture
        cursor_encoder = session.cursor_encoder
        view_only_session = session.view_only
        parallel_encoder = session.parallel_encoder
        network_profile = session.network_profile
        is_localhost = network_profile == NetworkProfile.LOCALHOST

        # Frame rate based on network profile
        match network_profile:
            case NetworkProfile.LOCALHOST:
                max_frame_rate = 120
            case NetworkProfile.LAN:
                max_frame_rate = self.lan_frame_rate
            case _:
                max_frame_rate = self.frame_rate
        throttler = PerformanceThrottler(max_rate=max_frame_rate)
        lan_adaptive = (
            network_profile == NetworkProfile.LAN
            and self.enable_lan_adaptive_encoding
        )
        target_frame_time = 1.0 / max_frame_rate if max_frame_rate > 0 else 0.0
        lan_jpeg_quality = self.lan_jpeg_quality_initial
        if lan_adaptive:
            self._configure_lan_encoders(encoder_manager, lan_jpeg_quality)
        parallel_enabled_for_client = parallel_encoder is not None
        last_pointer_pos = session.last_pointer_pos

        while not self.shutdown_handler.is_shutting_down():
            try:
                # Receive message type
                msg_type_data = recv_exact(client_socket, 1)
                if not msg_type_data:
                    break

                msg_type = msg_type_data[0]

                # Handle different message types using Python 3.13 pattern matching
                match msg_type:
                    case protocol.MSG_SET_PIXEL_FORMAT:
                        new_format = protocol.parse_set_pixel_format(client_socket)
                        if not self._is_supported_pixel_format(new_format):
                            raise ProtocolError(
                                f"Unsupported client pixel format requested: {new_format}"
                            )
                        current_pixel_format.update(new_format)
                        session.last_frame_generation = -1
                        if change_detector is not None:
                            change_detector.resize(fb_width, fb_height)
                        self._reset_stateful_encoders(encoder_manager)
                        filtered_after_pf, dropped = self._filter_encodings_for_pixel_format(
                            client_encodings, encoder_manager, current_pixel_format
                        )
                        if dropped:
                            self.logger.info(
                                "Pixel format disables negotiated encodings: %s",
                                format_encoding_list(dropped),
                            )
                            self.logger.info(
                                "Filtered usable encodings: %s",
                                format_encoding_list(filtered_after_pf),
                            )
                        self.logger.info(f"Pixel format updated: {new_format}")

                    case protocol.MSG_SET_ENCODINGS:
                        encodings = protocol.parse_set_encodings(client_socket)
                        client_encodings[:] = encodings
                        self._configure_tight_compatibility(
                            encoder_manager, client_encodings
                        )
                        self.logger.info(
                            f"Client encoding preference order: {format_encoding_list(client_encodings)}"
                        )
                        selection_preview, dropped = self._filter_encodings_for_pixel_format(
                            client_encodings, encoder_manager, current_pixel_format
                        )
                        negotiated_rect = [
                            enc for enc in selection_preview if enc in encoder_manager.encoders
                        ]
                        self.logger.info(
                            f"Negotiated rectangle encodings: {format_encoding_list(negotiated_rect)}"
                        )
                        if dropped:
                            self.logger.info(
                                "Skipping incompatible negotiated encodings for current pixel format: %s",
                                format_encoding_list(dropped),
                            )

                    case protocol.MSG_FRAMEBUFFER_UPDATE_REQUEST:
                        request = protocol.parse_framebuffer_update_request(client_socket)
                        if self.enable_request_coalescing:
                            request = self._coalesce_framebuffer_update_requests(
                                client_socket, protocol, request
                            )
                        selection_encodings, _ = self._filter_encodings_for_pixel_format(
                            client_encodings, encoder_manager, current_pixel_format
                        )

                        # Throttle before expensive capture/encoding work.
                        throttler.throttle()
                        start_time = time.perf_counter()
                        snapshot = self._capture_frame_with_generation(
                            screen_capture, current_pixel_format,
                            since_generation=session.last_frame_generation,
                        )
                        frame = snapshot.frame
                        result = frame.result
                        capture_metadata = frame.metadata

                        if result.pixel_data is None:
                            continue

                        # Handle dimension changes
                        if result.width != fb_width or result.height != fb_height:
                            new_width, new_height = result.width, result.height
                            self.logger.info(
                                "Framebuffer size changed from %dx%d to %dx%d",
                                fb_width, fb_height, new_width, new_height,
                            )

                            if protocol.ENCODING_DESKTOP_SIZE not in client_encodings:
                                raise VNCConnectionError(
                                    "Framebuffer size changed but the client did not negotiate "
                                    "DesktopSize; reconnect is required"
                                )

                            fb_width, fb_height = new_width, new_height
                            session.fb_width = fb_width
                            session.fb_height = fb_height
                            session.last_frame_generation = snapshot.generation
                            if change_detector:
                                change_detector.resize(fb_width, fb_height)
                            self._reset_stateful_encoders(encoder_manager)
                            protocol.send_framebuffer_update(client_socket, [
                                (0, 0, fb_width, fb_height, protocol.ENCODING_DESKTOP_SIZE, None)
                            ])
                            continue

                        cursor_rectangles, last_pointer_pos = self._build_cursor_pseudo_rectangles(
                            protocol,
                            client_encodings,
                            current_pixel_format,
                            cursor_capture,
                            cursor_encoder,
                            last_pointer_pos,
                        )

                        request_region = self._normalize_request_region(request, fb_width, fb_height)
                        if request_region is None:
                            protocol.send_framebuffer_update(client_socket, cursor_rectangles)
                            session.last_pointer_pos = last_pointer_pos
                            continue
                        req_x, req_y, req_w, req_h = request_region

                        backend_copyrect_rectangles: list[tuple[int, int, int, int, int, bytes]] = []

                        # With the server-wide producer, the generation number is an
                        # exact indication that no new capture has been published.
                        if (
                            request['incremental']
                            and snapshot.generation == session.last_frame_generation
                        ):
                            protocol.send_framebuffer_update(client_socket, cursor_rectangles)
                            session.last_pointer_pos = last_pointer_pos
                            continue

                        # Check for changes (incremental update)
                        if request['incremental']:
                            changed_regions, backend_copyrect_rectangles = (
                                self._resolve_incremental_update_hints(
                                    protocol,
                                    client_encodings,
                                    capture_metadata,
                                    request_region,
                                )
                            )
                            if changed_regions is None and change_detector:
                                changed_regions = change_detector.detect_changes(
                                    result.pixel_data,
                                    current_pixel_format['bits_per_pixel'] // 8
                                )
                                if changed_regions is not None:
                                    changed_regions = self._intersect_regions(changed_regions, request_region)

                            if changed_regions is not None and len(changed_regions) == 0:
                                protocol.send_framebuffer_update(
                                    client_socket,
                                    cursor_rectangles + backend_copyrect_rectangles,
                                )
                                session.last_frame_generation = snapshot.generation
                                session.last_pointer_pos = last_pointer_pos
                                continue

                            # Send region updates if available using parallel encoding
                            if changed_regions is not None and len(changed_regions) < 10 and parallel_enabled_for_client and parallel_encoder:
                                # Use parallel encoding for changed regions
                                bytes_per_pixel = current_pixel_format['bits_per_pixel'] // 8
                                content_type = network_profile.value if network_profile != NetworkProfile.WAN else "dynamic"

                                # Prepare regions for parallel encoding
                                regions_to_encode = []
                                parallel_safe = True
                                jpeg_original_bytes = 0
                                jpeg_encoded_bytes = 0
                                for x, y, w, h in changed_regions:
                                    # Extract region pixel data
                                    region_data = self._extract_region(
                                        result.pixel_data, fb_width, fb_height,
                                        x, y, w, h, bytes_per_pixel
                                    )
                                    encoding_type, encoder = self._select_encoder_for_update(
                                        encoder_manager,
                                        selection_encodings,
                                        network_profile,
                                        w,
                                        h,
                                        fb_width,
                                        fb_height,
                                        content_type=content_type,
                                        allow_jpeg=False,
                                        allow_zlib=True,
                                        bytes_per_pixel=bytes_per_pixel,
                                        pixel_format=current_pixel_format,
                                    )
                                    self._prepare_encoder_for_send(
                                        encoding_type, encoder, lan_jpeg_quality
                                    )
                                    parallel_safe = parallel_safe and self._is_parallel_safe_encoding(
                                        encoding_type
                                    )
                                    regions_to_encode.append(((x, y, w, h), region_data, encoding_type, encoder))
                                if not parallel_safe:
                                    self.logger.debug(
                                        "Falling back to sequential region encoding due to stateful encoder selection"
                                    )
                                else:
                                    # Encode regions in parallel
                                    encoded_results = parallel_encoder.encode_regions(regions_to_encode, bytes_per_pixel)

                                    # Build rectangles from results
                                    rectangles = cursor_rectangles + backend_copyrect_rectangles + [
                                        (r.x, r.y, r.width, r.height, r.encoding_type, r.encoded_data)
                                        for r in encoded_results
                                    ]
                                    self._log_selected_region_encodings(
                                        [r.encoding_type for r in encoded_results]
                                    )

                                    self.logger.debug(
                                        "Sending framebuffer update with %d rectangle(s)",
                                        len(rectangles),
                                    )
                                    protocol.send_framebuffer_update(client_socket, rectangles)
                                    self._commit_frame_state(
                                        encoder_manager,
                                        result.pixel_data,
                                        fb_width,
                                        fb_height,
                                        bytes_per_pixel,
                                    )
                                    session.last_frame_generation = snapshot.generation
                                    session.last_pointer_pos = last_pointer_pos
                                    self.logger.debug("Framebuffer update sent successfully")

                                    # Record metrics
                                    if conn_metrics:
                                        encoding_time = time.perf_counter() - start_time
                                        total_bytes = sum(r.original_size for r in encoded_results)
                                        compressed_bytes = sum(r.compressed_size for r in encoded_results)
                                        conn_metrics.record_frame(
                                            compressed_bytes, encoding_time, total_bytes
                                        )
                                        if lan_adaptive:
                                            for r in encoded_results:
                                                if r.encoding_type == 21:
                                                    jpeg_original_bytes += r.original_size
                                                    jpeg_encoded_bytes += r.compressed_size
                                            if jpeg_original_bytes > 0:
                                                lan_jpeg_quality = self._adjust_lan_jpeg_quality(
                                                    lan_jpeg_quality,
                                                    encoding_time,
                                                    jpeg_encoded_bytes,
                                                    jpeg_original_bytes,
                                                    target_frame_time,
                                                )
                                    continue

                            # Non-parallel region encoding fallback
                            if changed_regions is not None and len(changed_regions) > 0:
                                bytes_per_pixel = current_pixel_format['bits_per_pixel'] // 8
                                content_type = network_profile.value if network_profile != NetworkProfile.WAN else "dynamic"

                                rectangles = list(cursor_rectangles) + list(backend_copyrect_rectangles)
                                original_total_bytes = 0
                                compressed_total_bytes = 0
                                jpeg_original_bytes = 0
                                jpeg_encoded_bytes = 0
                                pixel_rectangles_sent = 0
                                for x, y, w, h in changed_regions:
                                    region_data = self._extract_region(
                                        result.pixel_data, fb_width, fb_height,
                                        x, y, w, h, bytes_per_pixel
                                    )
                                    original_total_bytes += len(region_data)
                                    allow_copyrect = pixel_rectangles_sent == 0 and len(changed_regions) == 1
                                    preferred_encoding_type, preferred_encoder = self._select_encoder_for_update(
                                        encoder_manager,
                                        selection_encodings,
                                        network_profile,
                                        w,
                                        h,
                                        fb_width,
                                        fb_height,
                                        content_type=content_type,
                                        allow_jpeg=True,
                                        allow_zlib=True,
                                        allow_copyrect=allow_copyrect,
                                        bytes_per_pixel=bytes_per_pixel,
                                        pixel_format=current_pixel_format,
                                    )
                                    split_rectangles = self._split_rectangles_for_encoding(
                                        preferred_encoding_type, x, y, w, h
                                    )
                                    if len(split_rectangles) > 1:
                                        for sx, sy, sw, sh in split_rectangles:
                                            split_pixels = self._extract_region(
                                                result.pixel_data,
                                                fb_width,
                                                fb_height,
                                                sx,
                                                sy,
                                                sw,
                                                sh,
                                                bytes_per_pixel,
                                            )
                                            split_encoding_type, split_encoder, split_payload = (
                                                self._encode_rectangle_for_update(
                                                    encoder_manager,
                                                    selection_encodings,
                                                    network_profile,
                                                    sx,
                                                    sy,
                                                    sw,
                                                    sh,
                                                    fb_width,
                                                    fb_height,
                                                    content_type=content_type,
                                                    pixel_data=split_pixels,
                                                    full_frame=result.pixel_data,
                                                    request_region=request_region,
                                                    allow_copyrect=False,
                                                    lan_jpeg_quality=lan_jpeg_quality,
                                                    bytes_per_pixel=bytes_per_pixel,
                                                    pixel_format=current_pixel_format,
                                                )
                                            )
                                            compressed_total_bytes += len(split_payload)
                                            if split_encoding_type == 21:
                                                jpeg_original_bytes += len(split_pixels)
                                                jpeg_encoded_bytes += len(split_payload)
                                            rectangles.append(
                                                (sx, sy, sw, sh, split_encoding_type, split_payload)
                                            )
                                        pixel_rectangles_sent += len(split_rectangles)
                                        continue

                                    encoding_type, encoder, encoded_data = self._encode_rectangle_for_update(
                                        encoder_manager,
                                        selection_encodings,
                                        network_profile,
                                        x,
                                        y,
                                        w,
                                        h,
                                        fb_width,
                                        fb_height,
                                        content_type=content_type,
                                        pixel_data=region_data,
                                        full_frame=result.pixel_data,
                                        request_region=request_region,
                                        allow_copyrect=allow_copyrect,
                                        lan_jpeg_quality=lan_jpeg_quality,
                                        bytes_per_pixel=bytes_per_pixel,
                                        pixel_format=current_pixel_format,
                                    )
                                    if len(split_rectangles) == 1:
                                        compressed_total_bytes += len(encoded_data)
                                        if encoding_type == 21:
                                            jpeg_original_bytes += len(region_data)
                                            jpeg_encoded_bytes += len(encoded_data)
                                        rectangles.append((x, y, w, h, encoding_type, encoded_data))
                                        pixel_rectangles_sent += 1
                                self._log_selected_region_encodings(
                                    [enc_type for _, _, _, _, enc_type, _ in rectangles if enc_type >= 0]
                                )

                                self.logger.debug(
                                    "Sending framebuffer update with %d rectangle(s)",
                                    len(rectangles),
                                )
                                protocol.send_framebuffer_update(client_socket, rectangles)
                                self._commit_frame_state(
                                    encoder_manager,
                                    result.pixel_data,
                                    fb_width,
                                    fb_height,
                                    bytes_per_pixel,
                                )
                                session.last_frame_generation = snapshot.generation
                                session.last_pointer_pos = last_pointer_pos
                                self.logger.debug("Framebuffer update sent successfully")

                                if conn_metrics:
                                    encoding_time = time.perf_counter() - start_time
                                    conn_metrics.record_frame(
                                        compressed_total_bytes,
                                        encoding_time,
                                        original_total_bytes,
                                    )
                                    if lan_adaptive and jpeg_original_bytes > 0:
                                        lan_jpeg_quality = self._adjust_lan_jpeg_quality(
                                            lan_jpeg_quality,
                                            encoding_time,
                                            jpeg_encoded_bytes,
                                            jpeg_original_bytes,
                                            target_frame_time,
                                        )
                                continue

                        # Select best encoding based on network profile
                        content_type = network_profile.value if network_profile != NetworkProfile.WAN else "dynamic"
                        bytes_per_pixel = current_pixel_format['bits_per_pixel'] // 8
                        # Encode pixel data (single-threaded for full frame)
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

                        preferred_encoding_type, preferred_encoder = self._select_encoder_for_update(
                            encoder_manager,
                            selection_encodings,
                            network_profile,
                            req_w,
                            req_h,
                            fb_width,
                            fb_height,
                            content_type=content_type,
                            allow_jpeg=True,
                            allow_zlib=True,
                            allow_copyrect=True,
                            bytes_per_pixel=bytes_per_pixel,
                            pixel_format=current_pixel_format,
                        )
                        split_rectangles = self._split_rectangles_for_encoding(
                            preferred_encoding_type, req_x, req_y, req_w, req_h
                        )
                        selected_encoding_type = preferred_encoding_type
                        selected_encoded_bytes = encoded_bytes_total = 0
                        if len(split_rectangles) > 1:
                            rectangles = list(cursor_rectangles)
                            for sx, sy, sw, sh in split_rectangles:
                                split_pixels = self._extract_region(
                                    result.pixel_data,
                                    fb_width,
                                    fb_height,
                                    sx,
                                    sy,
                                    sw,
                                    sh,
                                    bytes_per_pixel,
                                )
                                split_encoding_type, split_encoder, split_payload = (
                                    self._encode_rectangle_for_update(
                                        encoder_manager,
                                        selection_encodings,
                                        network_profile,
                                        sx,
                                        sy,
                                        sw,
                                        sh,
                                        fb_width,
                                        fb_height,
                                        content_type=content_type,
                                        pixel_data=split_pixels,
                                        full_frame=result.pixel_data,
                                        request_region=request_region,
                                        allow_copyrect=False,
                                        lan_jpeg_quality=lan_jpeg_quality,
                                        bytes_per_pixel=bytes_per_pixel,
                                        pixel_format=current_pixel_format,
                                    )
                                )
                                encoded_bytes_total += len(split_payload)
                                if selected_encoded_bytes == 0:
                                    selected_encoding_type = split_encoding_type
                                selected_encoded_bytes += len(split_payload)
                                rectangles.append((sx, sy, sw, sh, split_encoding_type, split_payload))
                            self._log_selected_region_encodings(
                                [rect[4] for rect in rectangles if rect[4] >= 0]
                            )
                        else:
                            encoding_type, encoder, encoded_data = self._encode_rectangle_for_update(
                                encoder_manager,
                                selection_encodings,
                                network_profile,
                                req_x,
                                req_y,
                                req_w,
                                req_h,
                                fb_width,
                                fb_height,
                                content_type=content_type,
                                pixel_data=frame_pixels,
                                full_frame=result.pixel_data,
                                request_region=request_region,
                                allow_copyrect=True,
                                lan_jpeg_quality=lan_jpeg_quality,
                                bytes_per_pixel=bytes_per_pixel,
                                pixel_format=current_pixel_format,
                            )
                            self._log_selected_encoding(encoding_type, content_type)
                            self.logger.debug(f"Encoded data size: {len(encoded_data)} bytes")
                            rectangles = list(cursor_rectangles) + [
                                (req_x, req_y, req_w, req_h, encoding_type, encoded_data)
                            ]
                            selected_encoding_type = encoding_type
                            selected_encoded_bytes = len(encoded_data)
                            encoded_bytes_total = len(encoded_data)
                        self.logger.debug(f"Sending framebuffer update with {len(rectangles)} rectangle(s)")
                        protocol.send_framebuffer_update(client_socket, rectangles)
                        self._commit_frame_state(
                            encoder_manager,
                            result.pixel_data,
                            fb_width,
                            fb_height,
                            bytes_per_pixel,
                        )
                        session.last_frame_generation = snapshot.generation
                        session.last_pointer_pos = last_pointer_pos
                        self.logger.debug("Framebuffer update sent successfully")

                        # Record metrics
                        if conn_metrics:
                            encoding_time = time.perf_counter() - start_time
                            conn_metrics.record_frame(
                                encoded_bytes_total, encoding_time, len(frame_pixels)
                            )
                            if lan_adaptive and selected_encoding_type == 21:
                                lan_jpeg_quality = self._adjust_lan_jpeg_quality(
                                    lan_jpeg_quality,
                                    encoding_time,
                                    selected_encoded_bytes,
                                    len(frame_pixels),
                                    target_frame_time,
                                )

                    case protocol.MSG_KEY_EVENT:
                        key_event = protocol.parse_key_event(client_socket)
                        if view_only_session:
                            self.logger.info(
                                "Ignoring key event from read-only client %s",
                                client_id,
                            )
                        elif self._try_acquire_input_control(client_id):
                            input_handler.handle_key_event(
                                key_event['down_flag'],
                                key_event['key']
                            )
                            if conn_metrics:
                                conn_metrics.record_input('key')

                    case protocol.MSG_POINTER_EVENT:
                        pointer_event = protocol.parse_pointer_event(client_socket)
                        pointer_event = self._coalesce_pointer_events(
                            client_socket, protocol, pointer_event
                        )
                        if view_only_session:
                            self.logger.info(
                                "Ignoring pointer event from read-only client %s",
                                client_id,
                            )
                        elif self._try_acquire_input_control(client_id):
                            input_handler.handle_pointer_event(
                                pointer_event['button_mask'],
                                pointer_event['x'],
                                pointer_event['y']
                            )
                            if conn_metrics:
                                conn_metrics.record_input('pointer')

                    case protocol.MSG_CLIENT_CUT_TEXT:
                        text = protocol.parse_client_cut_text(client_socket)
                        if view_only_session:
                            self.logger.info(
                                "Ignoring client cut text from read-only client %s",
                                client_id,
                            )
                        else:
                            # Clipboard contents may contain credentials or other
                            # sensitive data. Log metadata only, never the text.
                            self.logger.info(
                                "Client cut text received (%d chars)",
                                len(text),
                            )

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
                    case VNCConnectionError():
                        self.logger.warning(f"Connection error: {e}")
                        break
                    case _:
                        self.logger.error(f"VNC error: {e}", exc_info=True)
                        if conn_metrics:
                            conn_metrics.record_error()
                        break

            except Exception as e:
                if isinstance(e, OSError):
                    self.logger.warning(f"Socket error in message loop: {e}")
                    break
                self.logger.error(f"Unexpected error in message loop: {e}", exc_info=True)
                if conn_metrics:
                    conn_metrics.record_error()
                break
