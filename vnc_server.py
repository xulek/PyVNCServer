import hashlib
import os
import socket
import struct
import threading
import time
import pyautogui
from PIL import ImageGrab, Image
import logging
import json

def clamp(val, min_val, max_val):
    """Helper function to clamp a value between min_val and max_val."""
    return max(min_val, min(max_val, val))

class VNCServer:
    SUPPORTED_ENCODINGS = {
        0: "Raw",
        # 1: "CopyRect",  # commented out
        -223: "DesktopSize"
    }

    # Default fallback constants
    DEFAULT_PORT = 5900
    DEFAULT_CHUNK_SIZE = 65536
    FRAME_RATE = 30
    COLOR_MAP_SIZE = 256

    def __init__(self, host='0.0.0.0', port=DEFAULT_PORT, config_file="config.json"):
        # Basic defaults
        self.load_config(config_file)

        # 32-bit RGBA
        self.bytes_per_pixel = 4
        self.current_pixel_format = {
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

        # Create the server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((host, port))
        self.server_socket.listen(5)
        logging.info(f"Listening on {host}:{port}...")

        # Initialize other fields
        self.last_screenshot = None
        self.color_map = self.generate_default_color_map()
        self.color_map_entries_sent = False

        # If user set a password in config
        self.password = getattr(self, "password", None)

    def load_config(self, config_file):
        """
        Loads configuration from JSON.
        Potential keys:
          - host (str)
          - port (int)
          - password (str)
          - frame_rate (int)
          - log_level (str, e.g. "DEBUG")
          - scale_factor (float, e.g. 1.0 or 0.5)
          - chunk_size (int, how big the send chunks are)
        """
        # Defaults
        self.host = '0.0.0.0'
        self.port = self.DEFAULT_PORT
        self.password = ""
        self.frame_rate = self.FRAME_RATE
        self.scale_factor = 1.0
        self.chunk_size = self.DEFAULT_CHUNK_SIZE  # can be overridden by config

        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                # Load stuff from config if present
                self.host = config.get("host", self.host)
                self.port = config.get("port", self.port)
                self.password = config.get("password", self.password)
                self.frame_rate = config.get("frame_rate", self.frame_rate)
                log_level_str = config.get("log_level", "INFO").upper()
                self.scale_factor = config.get("scale_factor", self.scale_factor)
                self.chunk_size = config.get("chunk_size", self.chunk_size)

                # clamp frame_rate if it's too large or negative
                if self.frame_rate < 1:
                    logging.warning("frame_rate < 1 in config, clamping to 1")
                    self.frame_rate = 1
                if self.frame_rate > 60:
                    logging.warning("frame_rate > 60 in config, clamping to 60")
                    self.frame_rate = 60

                try:
                    log_level = getattr(logging, log_level_str)
                    logging.getLogger().setLevel(log_level)
                    logging.info(f"Log level set to: {log_level_str}")
                except AttributeError:
                    logging.warning(f"Invalid log level '{log_level_str}' in config. Using INFO.")
                    logging.getLogger().setLevel(logging.INFO)

                logging.info(f"Configuration loaded from {config_file}")
        except FileNotFoundError:
            logging.warning(f"Configuration file {config_file} not found. Using default values.")
        except Exception as e:
            logging.error(f"Error loading configuration: {e}. Using default values.")

    def generate_default_color_map(self):
        """
        Creates a default grayscale color map, 256 entries
        """
        color_map = []
        for i in range(self.COLOR_MAP_SIZE):
            gray = int(i * 255 / (self.COLOR_MAP_SIZE - 1))
            color_map.append((gray, gray, gray))
        return color_map

    def start(self):
        """
        Main accept loop
        """
        try:
            while True:
                client_socket, addr = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client_socket, addr)).start()
        except KeyboardInterrupt:
            logging.info("Server shutting down via KeyboardInterrupt.")
        finally:
            self.server_socket.close()
            logging.info("Server closed.")

    def handle_client(self, client_socket, addr):
        """
        Main per-client logic
        """
        client_encodings = set()
        last_screen_checksum = None
        last_frame_time = time.time()

        try:
            screen_width, screen_height = pyautogui.size()
            # We'll do an optional scale for sending
            framebuffer_width = int(screen_width * self.scale_factor)
            framebuffer_height = int(screen_height * self.scale_factor)

            # Basic handshake
            server_version = b"RFB 003.003\n"
            client_socket.sendall(server_version)
            client_version_data = client_socket.recv(12)
            if client_version_data != server_version:
                logging.warning(f"Client version mismatch: {client_version_data.decode().strip()} vs 003.003")

            # Security (don't change)
            security_type = 2 if self.password else 1
            client_socket.sendall(struct.pack(">I", security_type))
            if security_type == 2:
                if not self.vnc_authenticate(client_socket):
                    logging.warning("Client authentication failed")
                    client_socket.close()
                    return
            else:
                logging.info("No authentication needed.")

            # ClientInitialization
            _ = client_socket.recv(1)  # shared_flag

            # ServerInitialization
            pixel_format = struct.pack(
                ">BBBBHHHBBB3x",
                self.current_pixel_format['bits_per_pixel'],
                self.current_pixel_format['depth'],
                self.current_pixel_format['big_endian_flag'],
                self.current_pixel_format['true_colour_flag'],
                self.current_pixel_format['red_max'],
                self.current_pixel_format['green_max'],
                self.current_pixel_format['blue_max'],
                self.current_pixel_format['red_shift'],
                self.current_pixel_format['green_shift'],
                self.current_pixel_format['blue_shift']
            )
            name_length = len("Python VNC Server")
            server_init_msg = struct.pack(
                ">HH16sI",
                framebuffer_width,
                framebuffer_height,
                pixel_format,
                name_length
            ) + b"Python VNC Server"
            client_socket.sendall(server_init_msg)
            last_screen_checksum = b""

            # Send color map once
            if not self.color_map_entries_sent:
                self.send_set_color_map_entries(client_socket, 0, self.color_map)
                self.color_map_entries_sent = True

            # Send first frame in Raw
            screenshot, screen_data, screen_checksum = self.capture_screen_from_desktop()
            if screen_data:
                self.send_framebuffer_update(
                    client_socket, screen_data,
                    0, 0,
                    framebuffer_width, framebuffer_height,
                    framebuffer_width, framebuffer_height,
                    0
                )
                self.last_screenshot = screenshot
                last_screen_checksum = screen_checksum

            # Main loop
            while True:
                message_type, message_data = self.handle_client_messages(client_socket, client_encodings)
                if not message_type:
                    logging.warning("No valid message from client, closing connection.")
                    break

                if message_type == 'SetEncodings':
                    pass  # Already processed

                elif message_type == 'DesktopSize':
                    # Client requests desktop size change
                    framebuffer_width = message_data['width']
                    framebuffer_height = message_data['height']
                    self.send_desktop_size_update(client_socket, framebuffer_width, framebuffer_height)
                    screenshot, screen_data, screen_checksum = self.capture_screen_from_desktop()
                    if screen_data:
                        self.send_framebuffer_update(
                            client_socket, screen_data,
                            0, 0,
                            framebuffer_width, framebuffer_height,
                            framebuffer_width, framebuffer_height,
                            0
                        )
                        self.last_screenshot = screenshot
                        last_screen_checksum = screen_checksum

                elif message_type == 'FrameBufferUpdate':
                    incremental = message_data['incremental']
                    current_time = time.time()
                    time_elapsed = current_time - last_frame_time
                    if time_elapsed < 1 / self.frame_rate:
                        time.sleep(1 / self.frame_rate - time_elapsed)

                    screenshot, screen_data, screen_checksum = self.capture_screen_from_desktop()
                    if not screen_data:
                        continue

                    # If nothing changed
                    if incremental and screen_checksum == last_screen_checksum:
                        logging.debug("No changes detected. Sending 0 rectangles.")
                        client_socket.sendall(struct.pack(">BxH", 0, 0))
                        continue

                    # In any case, we send raw
                    logging.debug("Sending full Raw frame.")
                    self.send_framebuffer_update(
                        client_socket,
                        screen_data,
                        message_data['x_position'],
                        message_data['y_position'],
                        framebuffer_width,
                        framebuffer_height,
                        framebuffer_width,
                        framebuffer_height,
                        0
                    )

                    self.last_screenshot = screenshot
                    last_screen_checksum = screen_checksum
                    last_frame_time = time.time()

                else:
                    pass

        except Exception as e:
            logging.error(f"Error while communicating with client {addr}: {e}")
        finally:
            client_socket.close()

    def capture_screen_from_desktop(self):
        """
        1) Grab screen
        2) Resize if scale_factor != 1.0
        3) Convert to RGBA
        4) Return data + checksum
        """
        try:
            start_time = time.time()
            screenshot = ImageGrab.grab()
            screen_width, screen_height = screenshot.size
            new_width = int(screen_width * self.scale_factor)
            new_height = int(screen_height * self.scale_factor)

            if new_width < 1 or new_height < 1:
                logging.warning("Scale factor too small, skipping capture.")
                return None, None, None

            if self.scale_factor != 1.0:
                screenshot = screenshot.resize((new_width, new_height), Image.Resampling.BILINEAR)

            screenshot_rgba = screenshot.convert("RGBA")
            data = screenshot_rgba.tobytes()
            checksum = hashlib.md5(data).digest()

            total_time = time.time() - start_time
            logging.debug(f"capture_screen_from_desktop took {total_time:.4f} s")
            return screenshot_rgba, data, checksum
        except Exception as e:
            logging.error(f"capture_screen_from_desktop error: {e}")
            return None, None, None

    def handle_client_messages(self, client_socket, client_encodings):
        """
        Handles a single client message: SetEncodings, FramebufferUpdateRequest, etc.
        """
        try:
            hdr = self.recv_exact(client_socket, 1)
            if not hdr:
                return None, {}
            msg_type = struct.unpack(">B", hdr)[0]
        except Exception as e:
            logging.error(f"handle_client_messages error: {e}")
            return None, {}

        try:
            if msg_type == 0:  # SetPixelFormat
                self.recv_exact(client_socket, 3)  # padding
                self.recv_exact(client_socket, 16) # ignore pixel format
                return 'SetPixelFormat', {}

            elif msg_type == 2:  # SetEncodings
                subhdr = self.recv_exact(client_socket, 3)
                if not subhdr:
                    return None, {}
                _, n_enc = struct.unpack(">BH", subhdr)
                enc_data = self.recv_exact(client_socket, 4 * n_enc)
                if not enc_data:
                    return None, {}
                enc_list = struct.unpack(">" + "I" * n_enc, enc_data)

                client_encodings.clear()
                for enc in enc_list:
                    if enc in self.SUPPORTED_ENCODINGS:
                        client_encodings.add(enc)
                enc_names = [self.SUPPORTED_ENCODINGS[e] for e in client_encodings]
                logging.info(f"Client encodings updated: {enc_names}")
                return 'SetEncodings', {}

            elif msg_type == 3:  # FramebufferUpdateRequest
                fb_req = self.recv_exact(client_socket, 9)
                if not fb_req:
                    return None, {}
                incremental, x, y, w, h = struct.unpack(">BHHHH", fb_req)
                logging.debug(f"FramebufferUpdate request: x={x}, y={y}, w={w}, h={h}, incremental={incremental}")
                return 'FrameBufferUpdate', {
                    'incremental': incremental,
                    'x_position': x,
                    'y_position': y,
                    'width': w,
                    'height': h
                }

            elif msg_type == 4:  # KeyEvent
                self.recv_exact(client_socket, 7)  # ignore
                return 'KeyEvent', {}

            elif msg_type == 5:  # PointerEvent
                ptr_data = self.recv_exact(client_socket, 5)
                if not ptr_data:
                    return None, {}
                button_mask, px, py = struct.unpack(">BHH", ptr_data)
                self.handle_pointer_event(button_mask, px, py)
                return 'PointerEvent', {}

            elif msg_type == 6:  # ClientCutText
                _ = self.recv_exact(client_socket, 3)  # padding
                length_data = self.recv_exact(client_socket, 4)
                if not length_data:
                    return None, {}
                length, = struct.unpack(">I", length_data)
                text_data = self.recv_exact(client_socket, length)
                if text_data is None:
                    return None, {}
                return 'ClientCutText', text_data.decode("latin-1")

            elif msg_type == -223:  # DesktopSize
                ds_data = self.recv_exact(client_socket, 4)
                if ds_data is None:
                    return None, {}
                w, h = struct.unpack(">HH", ds_data)
                logging.info(f"Client requested DesktopSize: w={w}, h={h}")
                return 'DesktopSize', {'width': w, 'height': h}

            else:
                logging.warning(f"Unknown message type: {msg_type}")
                return None, {}
        except Exception as e:
            logging.error(f"Error processing message {msg_type}: {e}")
            return None, {}

    def recv_exact(self, sock, n):
        """
        Normal instance method (not @staticmethod).
        Reads exactly n bytes from the socket, or returns None if fails.
        """
        buf = b''
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Failed to receive all data")
            buf += chunk
        return buf

    def send_framebuffer_update(self, client_socket, screen_data,
                                x_position, y_position,
                                width, height,
                                full_width, full_height,
                                encoding_type=0):
        """
        Sends a single rectangle update (Raw).
        """
        try:
            num_rectangles = 1
            client_socket.sendall(struct.pack(">BxH", 0, num_rectangles))
            client_socket.sendall(struct.pack(">HHHHI", x_position, y_position, width, height, encoding_type))

            rectangle_size = width * height * self.bytes_per_pixel
            self.send_large_data(client_socket, screen_data[:rectangle_size])
        except Exception as e:
            logging.error(f"send_framebuffer_update error: {e}")

    def send_set_color_map_entries(self, client_socket, first_color, colors):
        """
        Sends the color map once (grayscale).
        """
        client_socket.sendall(struct.pack(">BxHH", 1, first_color, len(colors)))
        for color in colors:
            red, green, blue = color
            client_socket.sendall(struct.pack(">HHH", red, green, blue))

    def send_desktop_size_update(self, client_socket, width, height):
        """
        DesktopSizeUpdate pseudo-encoding
        """
        try:
            client_socket.sendall(struct.pack(">BxH", 0, 1))
            client_socket.sendall(struct.pack(">HHHHI", 0, 0, width, height, -223))
        except Exception as e:
            logging.error(f"send_desktop_size_update error: {e}")

    def send_large_data(self, client_socket, data):
        """
        Sends big data in self.chunk_size chunks.
        """
        total_sent = 0
        data_len = len(data)
        start_time = time.time()
        while total_sent < data_len:
            end = min(total_sent + self.chunk_size, data_len)
            sent = client_socket.send(data[total_sent:end])
            if sent == 0:
                raise RuntimeError("Connection lost during send")
            total_sent += sent
        elapsed = time.time() - start_time
        logging.debug(f"send_large_data: sent {data_len} bytes in {elapsed:.4f} s")

    @staticmethod
    def handle_pointer_event(button_mask, x_position, y_position):
        """
        Moves the mouse pointer accordingly. This can remain @staticmethod,
        because it's not calling 'self'.
        """
        safe_margin = 10
        screen_width, screen_height = pyautogui.size()
        if (x_position < safe_margin or x_position > screen_width - safe_margin or
                y_position < safe_margin or y_position > screen_height - safe_margin):
            logging.warning("Pointer event near screen edge, ignoring for safety.")
            return
        current_x, current_y = pyautogui.position()
        dx = x_position - current_x
        dy = y_position - current_y
        try:
            pyautogui.move(dx, dy)
        except Exception as e:
            logging.error(f"Error moving cursor: {e}")
            return
        # handle mouse clicks
        try:
            if button_mask & 1:
                pyautogui.mouseDown(button='left') if button_mask & 1 else pyautogui.mouseUp(button='left')
            if button_mask & 2:
                pyautogui.mouseDown(button='middle') if button_mask & 2 else pyautogui.mouseUp(button='middle')
            if button_mask & 4:
                pyautogui.mouseDown(button='right') if button_mask & 4 else pyautogui.mouseUp(button='right')
        except Exception as e:
            logging.error(f"Error handling mouse clicks: {e}")

    def vnc_authenticate(self, client_socket):
        """Simple 'fake' RFB 003.003 authentication. (Do not change)"""
        challenge = os.urandom(16)
        client_socket.sendall(challenge)
        _ = client_socket.recv(16)
        client_socket.sendall(struct.pack(">I", 0))
        return True

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    server = VNCServer()
    server.start()
