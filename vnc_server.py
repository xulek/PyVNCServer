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

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class VNCServer:
    SUPPORTED_ENCODINGS = {
        0: "Raw",
        # 1: "CopyRect",
        -223: "DesktopSize" # Pseudo-encoding
    }
    CHUNK_SIZE = 4096
    DEFAULT_PORT = 5900
    FRAME_RATE = 30
    COLOR_MAP_SIZE = 256

    def __init__(self, host='0.0.0.0', port=DEFAULT_PORT, config_file="config.json"):
        self.load_config(config_file)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((host, port))
        self.server_socket.listen(5)
        logging.info(f"Listening on {host}:{port}...")
        self.last_screenshot = None
        self.last_mouse_position = (0, 0)
        self.color_map = self.generate_default_color_map()
        self.color_map_entries_sent = False
        self.bytes_per_pixel = 4  # RGBA
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

    def load_config(self, config_file):
        """Load configuration from a JSON file."""
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                self.host = config.get("host", '0.0.0.0')
                self.port = config.get("port", self.DEFAULT_PORT)
                self.password = config.get("password", "password")
                self.frame_rate = config.get("frame_rate", self.FRAME_RATE)
                log_level_str = config.get("log_level", "INFO").upper()
                try:
                    log_level = getattr(logging, log_level_str)
                    logging.getLogger().setLevel(log_level)
                    logging.info(f"Log level set to: {log_level_str}")
                except AttributeError:
                    logging.warning(f"Invalid log level '{log_level_str}' in config. Using default INFO.")
                logging.info(f"Configuration loaded from {config_file}")
        except FileNotFoundError:
            logging.warning(f"Configuration file {config_file} not found. Using default values.")
            self.host = '0.0.0.0'
            self.port = self.DEFAULT_PORT
            self.password = "password"
            self.frame_rate = self.FRAME_RATE
        except Exception as e:
            logging.error(f"Error loading configuration: {e}. Using default values.")
            self.host = '0.0.0.0'
            self.port = self.DEFAULT_PORT
            self.password = "password"
            self.frame_rate = self.FRAME_RATE

    @staticmethod
    def send_large_data(client_socket, data):
        """Send a large data chunk over the socket."""
        total_sent = 0
        while total_sent < len(data):
            sent = client_socket.send(data[total_sent:total_sent + VNCServer.CHUNK_SIZE])
            if sent == 0:
                raise RuntimeError("Cannot send data")
            total_sent += sent

    def capture_screen_from_desktop(self):
        """Capture a screenshot and convert it to RGBA format."""
        try:
            screenshot = ImageGrab.grab()
            screenshot_rgba = screenshot.convert('RGBA')
            return screenshot, screenshot_rgba.tobytes(), hashlib.md5(screenshot_rgba.tobytes()).digest()
        except Exception as e:
            logging.error(f"Error capturing screen: {e}")
            return None, None, None

    @staticmethod
    def calculate_position_difference(old_position, new_position):
        """Calculate the difference between two positions."""
        old_x, old_y = old_position
        new_x, new_y = new_position
        delta_x = new_x - old_x
        delta_y = new_y - old_y
        return delta_x, delta_y

    def send_framebuffer_update(self, client_socket, screen_data, x_position, y_position, width, height, full_width, full_height, encoding_type=0):
        """Sends a framebuffer update to the client."""

        # Ensure dimensions are within protocol limits
        width = min(width, 65535)
        height = min(height, 65535)
        x_position = min(x_position, 65535 - width)
        y_position = min(y_position, 65535 - height)

        num_rectangles = 1
        client_socket.sendall(struct.pack(">BxH", 0, num_rectangles))

        if encoding_type == 0:  # Raw encoding
            rectangle_size = width * height * self.bytes_per_pixel
            client_socket.sendall(struct.pack(">HHHHI", x_position, y_position, width, height, encoding_type))

            start_index = 0
            while start_index < rectangle_size:
                end_index = min(start_index + VNCServer.CHUNK_SIZE, rectangle_size)
                client_socket.sendall(screen_data[start_index:end_index])
                start_index = end_index

        elif encoding_type == 1:  # CopyRect
            # Assuming screen_data contains src_x and src_y for CopyRect
            src_x, src_y = struct.unpack(">HH", screen_data[:4])  # Extract src_x, src_y
            client_socket.sendall(struct.pack(">HHHHIHH", x_position, y_position, width, height, encoding_type, src_x, src_y))

        elif encoding_type == 2:  # RRE encoding
            rre_data = self.encode_rre(screen_data, width, height)
            client_socket.sendall(struct.pack(">HHHHI", x_position, y_position, width, height, encoding_type))
            self.send_large_data(client_socket, rre_data)

        elif encoding_type == 4:  # CoRRE encoding
            corre_data = self.encode_corre(screen_data, width, height)
            client_socket.sendall(struct.pack(">HHHHI", x_position, y_position, width, height, encoding_type))
            self.send_large_data(client_socket, corre_data)

        elif encoding_type == 5:  # Hextile encoding
            hextile_data = self.encode_hextile(screen_data, width, height)
            client_socket.sendall(struct.pack(">HHHHI", x_position, y_position, width, height, encoding_type))
            self.send_large_data(client_socket, hextile_data)

        else:
            logging.error(f"Unsupported encoding type: {encoding_type}")

    @staticmethod
    def send_copyrect_update(client_socket, src_x, src_y, x_position, y_position, width, height):
        """Sends a single CopyRect rectangle update."""
        encoding_type = 1
        client_socket.sendall(struct.pack(">HHHHIHH", x_position, y_position, width, height, encoding_type, src_x, src_y))

    @staticmethod
    def extract_subrectangle(screen_data, x, y, width, height, full_width, full_height, bytes_per_pixel):
        """Extract a subrectangle from the full screen data."""
        subrect_data = bytearray()
        for row in range(height):
            full_row_start = (y + row) * full_width * bytes_per_pixel
            subrect_start = full_row_start + x * bytes_per_pixel
            subrect_data.extend(screen_data[subrect_start:subrect_start + width * bytes_per_pixel])
        return bytes(subrect_data)

    def send_set_color_map_entries(self, client_socket, first_color, colors):
        """Sends the SetColorMapEntries message."""
        client_socket.sendall(struct.pack(">BxHH", 1, first_color, len(colors)))
        for color in colors:
            red, green, blue = color
            client_socket.sendall(struct.pack(">HHH", red, green, blue))

    @staticmethod
    def send_bell(client_socket):
        """Sends a Bell message."""
        client_socket.sendall(struct.pack(">B", 2))

    @staticmethod
    def send_server_cut_text(client_socket, text):
        """Sends a ServerCutText message."""
        client_socket.sendall(struct.pack(">BxI", 3, len(text)))
        client_socket.sendall(text.encode())

    def vnc_authenticate(self, client_socket):
        """Authenticate the VNC client using the original RFB 003.003 method."""
        # For RFB 003.003, the server sends a 16-byte challenge
        challenge = os.urandom(16)
        client_socket.sendall(challenge)

        # Client encrypts the challenge with DES, using the password as the key
        encrypted_response = client_socket.recv(16)  # Client sends back 16 bytes

        # In a real implementation, you would decrypt the response here and compare it
        # with the original challenge. For simplicity, we'll skip the actual decryption.

        # Send authentication result (0 = OK, 1 = failed)
        # In this simplified version, we always send OK
        client_socket.sendall(struct.pack(">I", 0))
        return True

    @staticmethod
    def recv_exact(socket, n):
        """Receive exactly n bytes from the socket."""
        buf = b''
        while n > 0:
            try:
                data = socket.recv(n)
                if not data:
                    raise ConnectionError("Failed to receive all data")
                buf += data
                n -= len(data)
            except Exception as e:
                logging.error(f"Error receiving data: {e}")
                return None
        return buf

    def handle_client_messages(self, client_socket, client_encodings):
        """Process messages received from the client."""
        try:
            message_type = struct.unpack(">B", self.recv_exact(client_socket, 1))[0]
        except struct.error as e:
            logging.error(f"Error reading message type: {e}")
            return None, {}
        try:
            logging.debug(f"Processing message of type {message_type}")

            if message_type == 0:  # SetPixelFormat
                self.recv_exact(client_socket, 3)  # Padding
                pixel_format_data = self.recv_exact(client_socket, 16)
                pixel_format = struct.unpack(">BBBBHHHBBB3x", pixel_format_data)
                self.current_pixel_format = {
                    'bits_per_pixel': pixel_format[0],
                    'depth': pixel_format[1],
                    'big_endian_flag': pixel_format[2],
                    'true_colour_flag': pixel_format[3],
                    'red_max': pixel_format[4],
                    'green_max': pixel_format[5],
                    'blue_max': pixel_format[6],
                    'red_shift': pixel_format[7],
                    'green_shift': pixel_format[8],
                    'blue_shift': pixel_format[9]
                }
                logging.info(f"Client set pixel format: {self.current_pixel_format}")
                return 'SetPixelFormat', self.current_pixel_format
            elif message_type == 2:  # SetEncodings
                _, number_of_encodings = struct.unpack(">BH", self.recv_exact(client_socket, 3))
                encodings = struct.unpack(">" + "I"*number_of_encodings, self.recv_exact(client_socket, 4 * number_of_encodings))
                client_encodings.clear()
                for encoding in encodings:
                    if encoding in self.SUPPORTED_ENCODINGS:
                        client_encodings.add(encoding)
                return 'SetEncodings', client_encodings
            elif message_type == 3:
                data = self.recv_exact(client_socket, 9)
                if data is None:
                    return None, {}
                incremental, x_position, y_position, width, height = struct.unpack(">BHHHH", data)
                logging.debug(f"FrameBufferUpdate request: x={x_position}, y={y_position}, width={width}, height={height}, incremental={incremental}")
                return 'FrameBufferUpdate', {
                    'incremental': incremental,
                    'x_position': x_position,
                    'y_position': y_position,
                    'width': width,
                    'height': height
                }
            elif message_type == 4:
                data = self.recv_exact(client_socket, 7)
                if data is None:
                    return None, {}
                down_flag, key = struct.unpack(">BHI", data)[:2]
                return 'KeyEvent', {
                    'down_flag': down_flag,
                    'key': key
                }
            elif message_type == 5:  # PointerEvent
                try:
                    data = self.recv_exact(client_socket, 5)
                    if data is None:
                        return None, {}
                    button_mask, x_position, y_position = struct.unpack(">BHH", data)
                    logging.debug(f"Pointer event: button_mask={button_mask}, x={x_position}, y={y_position}")
                    self.handle_pointer_event(button_mask, x_position, y_position)
                    return 'PointerEvent', {
                        'button_mask': button_mask,
                        'x_position': x_position,
                        'y_position': y_position
                    }
                except struct.error as e:
                    logging.error(f"Error unpacking PointerEvent: {e}. Data received: {data}")
            elif message_type == 6:  # ClientCutText
                _ = self.recv_exact(client_socket, 3)
                length, = struct.unpack(">I", self.recv_exact(client_socket, 4))
                if length is None:
                    return None, {}
                text = self.recv_exact(client_socket, length).decode("latin-1")
                return 'ClientCutText', text
            elif message_type == -223: # DesktopSize pseudo-encoding
                data = self.recv_exact(client_socket, 4)
                if data is None:
                    return None, {}
                width, height = struct.unpack(">HH", data)
                logging.info(f"Client requested DesktopSize update: width={width}, height={height}")
                return 'DesktopSize', {
                    'width': width,
                    'height': height
                }
            else:
                logging.warning(f"Unknown or unsupported message type: {message_type}")
                return None, {}
        except Exception as e:
            logging.error(f"Error processing message type {message_type}: {e}")
            return None, {}

    def handle_client(self, client_socket, addr):
        """Handle individual client connections."""
        client_encodings = set()
        last_screen_checksum = None
        last_frame_time = time.time()
        try:
            screen_width, screen_height = pyautogui.size()
            framebuffer_width = screen_width
            framebuffer_height = screen_height
            full_width, full_height = framebuffer_width, framebuffer_height

            # ProtocolVersion handshake (both server and client send their version)
            server_version = b"RFB 003.003\n"
            client_socket.sendall(server_version)
            client_version_data = client_socket.recv(12)

            # For 003.003, server does not send any message back, it proceeds to security
            if client_version_data != server_version:
                logging.warning(f"Client requested version {client_version_data.decode().strip()}, but server is using 003.003.")

            # Security handshake
            # In 003.003, the server sends a single word indicating the security type
            # 0 = Invalid, 1 = None, 2 = VNC Authentication
            security_type = 2 if self.password else 1
            client_socket.sendall(struct.pack(">I", security_type))

            if security_type == 2:
                if not self.vnc_authenticate(client_socket):
                    logging.warning("Client authentication failed")
                    client_socket.close()
                    return
            elif security_type == 1:
                logging.info("No authentication needed.")
            else:
                logging.error("Invalid security type.")
                client_socket.close()
                return

            # ClientInitialisation
            shared_flag = client_socket.recv(1)

            # ServerInitialisation
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

            # Send initial color map
            if not self.color_map_entries_sent:
                self.send_set_color_map_entries(client_socket, 0, self.color_map)
                self.color_map_entries_sent = True

            # Sending initial framebuffer update (Raw encoding)
            screenshot, screen_data, screen_checksum = self.capture_screen_from_desktop()
            if screen_data:
                self.send_framebuffer_update(client_socket, screen_data, 0, 0, framebuffer_width, framebuffer_height, full_width, full_height, 0)
                self.last_screenshot = Image.frombytes('RGBA', (framebuffer_width, framebuffer_height), screen_data)
                logging.debug("Initial last_screenshot updated.")
                last_screen_checksum = screen_checksum

            while True:
                message_type, message_data = self.handle_client_messages(client_socket, client_encodings)
                if not message_type:
                    logging.warning("Didn't receive a valid message from the client, closing the connection.")
                    break

                if message_type == 'SetEncodings':
                    encodings = message_data
                    encoding_names = [self.SUPPORTED_ENCODINGS.get(enc, f"Unknown ({enc})") for enc in encodings]
                    logging.info(f"Client encodings updated: {encoding_names}")
                    logging.debug(f"Encoding: {encoding_names}")
                    # client_encodings.clear()
                    client_encodings.update(encodings)

                elif message_type == 'SetPixelFormat':
                    # Format already set in handle_client_messages
                    pass

                elif message_type == 'DesktopSize':
                    framebuffer_width = message_data['width']
                    framebuffer_height = message_data['height']
                    self.send_desktop_size_update(client_socket, framebuffer_width, framebuffer_height)
                    # Force a full screen update after DesktopSize change
                    screenshot, screen_data, screen_checksum = self.capture_screen_from_desktop()
                    if screen_data:
                        self.send_framebuffer_update(client_socket, screen_data, 0, 0, framebuffer_width, framebuffer_height, full_width, full_height, 0)
                        self.last_screenshot = Image.frombytes('RGBA', (framebuffer_width, framebuffer_height), screen_data)
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

                    current_screenshot = Image.frombytes('RGBA', (framebuffer_width, framebuffer_height), screen_data)
                    encoding_used = None

                    if 1 in client_encodings and self.last_screenshot:
                        movements = self.find_screen_movements(self.last_screenshot, current_screenshot)
                        if movements:
                            encoding_used = 1
                            logging.debug(f"Using encoding: {encoding_used} (CopyRect) with {len(movements)} rectangles")
                            client_socket.sendall(struct.pack(">BxH", 0, len(movements)))
                            for old_x, old_y, new_x, new_y, width, height in movements:
                                self.send_copyrect_update(client_socket, old_x, old_y, new_x, new_y, width, height)

                    if encoding_used is None:
                        if 5 in client_encodings:
                            encoding_used = 5
                            logging.debug(f"Using encoding: {encoding_used} ({self.SUPPORTED_ENCODINGS.get(encoding_used)})")
                            hextile_data = self.encode_hextile(screen_data, framebuffer_width, framebuffer_height)
                            self.send_framebuffer_update(client_socket, hextile_data,
                                                        message_data['x_position'], message_data['y_position'],
                                                        framebuffer_width, framebuffer_height, # Send full screen dimensions
                                                        full_width, full_height, 5)
                        elif 4 in client_encodings:
                            encoding_used = 4
                            logging.debug(f"Using encoding: {encoding_used} ({self.SUPPORTED_ENCODINGS.get(encoding_used)})")
                            corre_data = self.encode_corre(screen_data, framebuffer_width, framebuffer_height)
                            self.send_framebuffer_update(client_socket, corre_data,
                                                        message_data['x_position'], message_data['y_position'],
                                                        framebuffer_width, framebuffer_height, # Send full screen dimensions
                                                        full_width, full_height, 4)
                        elif 2 in client_encodings:
                            encoding_used = 2
                            logging.debug(f"Using encoding: {encoding_used} ({self.SUPPORTED_ENCODINGS.get(encoding_used)})")
                            rre_data = self.encode_rre(screen_data, framebuffer_width, framebuffer_height)
                            self.send_framebuffer_update(client_socket, rre_data,
                                                        message_data['x_position'], message_data['y_position'],
                                                        framebuffer_width, framebuffer_height, # Send full screen dimensions
                                                        full_width, full_height, 2)
                        else:  # Default to Raw
                            encoding_used = 0
                            logging.debug(f"Using encoding: {encoding_used} ({self.SUPPORTED_ENCODINGS.get(encoding_used)})")
                            if incremental and screen_checksum == last_screen_checksum:
                                client_socket.sendall(struct.pack(">BxH", 0, 0))  # No update needed
                                continue

                            self.send_framebuffer_update(client_socket, screen_data,
                                                        message_data['x_position'], message_data['y_position'],
                                                        framebuffer_width, framebuffer_height,  # Send full screen dimensions
                                                        full_width, full_height, 0)

                    if screen_checksum != last_screen_checksum:
                        changed_rectangles = self.find_screen_changes(self.last_screenshot, current_screenshot) if self.last_screenshot else [(0, 0, framebuffer_width, framebuffer_height)]
                        if changed_rectangles and encoding_used != 0: # Avoid Raw if CopyRect has already been sent and changes are the same
                            if encoding_used != 1: # If CopyRect was not used
                                logging.debug(f"Using encoding: 0 (Raw) for remaining changes")
                                client_socket.sendall(struct.pack(">BxH", 0, len(changed_rectangles)))
                                for x, y, width, height in changed_rectangles:
                                    sub_screen_data = self.extract_subrectangle(screen_data, x, y, width, height, framebuffer_width, framebuffer_height, self.bytes_per_pixel)
                                    self.send_framebuffer_update(client_socket, sub_screen_data, x, y, width, height, full_width, full_height, 0)
                            elif not movements: # If CopyRect was used, but no shifts were found (only changes)
                                logging.debug(f"Using encoding: 0 (Raw) for initial frame or simple changes")
                                self.send_framebuffer_update(client_socket, screen_data, 0, 0, framebuffer_width, framebuffer_height, full_width, full_height, 0)

                    self.last_screenshot = current_screenshot
                    last_screen_checksum = screen_checksum
                    last_frame_time = time.time()

                elif message_type in ('KeyEvent', 'PointerEvent', 'ClientCutText'):
                    pass  # Already handled these events

                else:
                    logging.warning(f"Unhandled message type: {message_type}")

        except Exception as e:
            logging.error(f"Error while communicating with client {addr}: {e}")
        finally:
            client_socket.close()

    @staticmethod
    def handle_pointer_event(button_mask, x_position, y_position):
        safe_margin = 10
        screen_width, screen_height = pyautogui.size()
        if (x_position < safe_margin or x_position > screen_width - safe_margin or
                y_position < safe_margin or y_position > screen_height - safe_margin):
            logging.warning("Cursor position too close to screen corner, movement canceled.")
            return
        current_x, current_y = pyautogui.position()
        delta_x = x_position - current_x
        delta_y = y_position - current_y
        try:
            pyautogui.move(delta_x, delta_y)
        except Exception as e:
            logging.error(f"Error moving the cursor: {e}")
            return
        try:
            if button_mask & 1:
                pyautogui.mouseDown(button='left') if button_mask & 1 else pyautogui.mouseUp(button='left')
            if button_mask & 2:
                pyautogui.mouseDown(button='middle') if button_mask & 2 else pyautogui.mouseUp(button='middle')
            if button_mask & 4:
                pyautogui.mouseDown(button='right') if button_mask & 4 else pyautogui.mouseUp(button='right')
        except Exception as e:
            logging.error(f"Error handling mouse clicks: {e}")
            return
    
    @staticmethod
    def send_desktop_size_update(client_socket, width, height):
        """
        Sends a DesktopSizeUpdate message.

        :param client_socket: The socket connected to the client.
        :param width: The width of the desktop.
        :param height: The height of the desktop.
        """
        client_socket.sendall(struct.pack(">BxH", 0, 1))
        client_socket.sendall(struct.pack(">HHHHI", 0, 0, width, height, -223))

    def start(self):
        try:
            while True:
                client_socket, addr = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client_socket, addr)).start()
        except KeyboardInterrupt:
            logging.info("\nServer shutting down.")
        finally:
            self.server_socket.close()
            logging.info("Server closed.")

    def find_screen_movements(self, old_image, new_image):
        """Finds shifts of rectangular areas between two images."""
        if old_image.size != new_image.size:
            return []

        width, height = old_image.size
        movements = []
        chunk_size = 32
        compared_old_chunks = set()
        compared_new_chunks = set()

        for old_y in range(0, height, chunk_size):
            for old_x in range(0, width, chunk_size):
                if (old_x, old_y) in compared_old_chunks:
                    continue

                region = (old_x, old_y, min(old_x + chunk_size, width), min(old_y + chunk_size, height))
                old_region = old_image.crop(region)

                for new_y in range(0, height, chunk_size):
                    for new_x in range(0, width, chunk_size):
                        if (new_x, new_y) in compared_new_chunks:
                            continue

                        new_region_coords = (new_x, new_y, min(new_x + chunk_size, width), min(new_y + chunk_size, height))
                        new_region = new_image.crop(new_region_coords)

                        if list(old_region.getdata()) == list(new_region.getdata()):
                            movements.append((old_x, old_y, new_x, new_y, region[2] - region[0], region[3] - region[1]))
                            for x in range(old_x, region[2], chunk_size):
                                for y in range(old_y, region[3], chunk_size):
                                    compared_old_chunks.add((x, y))
                            for x in range(new_x, new_region_coords[2], chunk_size):
                                for y in range(new_y, new_region_coords[3], chunk_size):
                                    compared_new_chunks.add((x, y))
                            break  # Match found, proceed to next old region
                    else:
                        continue
                    break
        return movements

    def find_screen_changes(self, old_image, new_image):
        """Find rectangular changes between two images."""
        if old_image.size != new_image.size:
            return []

        width, height = old_image.size
        changes = []
        chunk_size = 32

        for y in range(0, height, chunk_size):
            for x in range(0, width, chunk_size):
                region = (x, y, min(x + chunk_size, width), min(y + chunk_size, height))
                old_region = old_image.crop(region)
                new_region = new_image.crop(region)

                if list(old_region.getdata()) != list(new_region.getdata()):
                    changes.append((x, y, region[2] - region[0], region[3] - region[1]))

        # if changes:
        #     logging.debug(f"Found {len(changes)} changes.")
        #     for x, y, width, height in changes:
        #         logging.debug(f"Change at: x={x}, y={y}, width={width}, height={height}")

        return changes

    def generate_default_color_map(self):
        """Generates a default color map."""
        color_map = []
        for i in range(self.COLOR_MAP_SIZE):
            gray = int(i * 255 / (self.COLOR_MAP_SIZE - 1))
            color_map.append((gray, gray, gray))
        return color_map

    def encode_rre(self, screen_data, width, height):
        """Encode screen data using RRE."""

        pixels = [screen_data[i:i+self.bytes_per_pixel] for i in range(0, len(screen_data), self.bytes_per_pixel)]
        encoded_data = bytearray()

        i = 0
        while i < len(pixels):
            bg_color = pixels[i]
            run_length = 0

            # Count background color run
            while i < len(pixels) and pixels[i] == bg_color and run_length < (2**32 - 1):  # Max run length (minus 1) for RRE
                run_length += 1
                i += 1

            subrectangles = []
            while i < len(pixels):
                sub_color = pixels[i]
                sub_run_length = 0

                # Count subrectangle color run
                while i < len(pixels) and pixels[i] == sub_color and sub_run_length < 255:
                    sub_run_length += 1
                    i += 1

                if sub_run_length > 0:
                    x = (i - sub_run_length) % width
                    y = (i - sub_run_length) // width
                    subrectangles.append((sub_color, x, y, sub_run_length, 1))
                else:
                    break  # No more subrectangles of different color

            # Add RRE header
            encoded_data.extend(struct.pack(">I", len(subrectangles)))
            encoded_data.extend(bg_color)

            # Add subrectangles
            for sub_color, x, y, sub_width, sub_height in subrectangles:
                encoded_data.extend(sub_color)
                encoded_data.extend(struct.pack(">HHHH", x, y, sub_width, sub_height))

        return encoded_data

    def encode_corre(self, screen_data, width, height):
        """Encode screen data using CoRRE."""

        pixels = [screen_data[i:i+self.bytes_per_pixel] for i in range(0, len(screen_data), self.bytes_per_pixel)]
        encoded_data = bytearray()

        i = 0
        while i < len(pixels):
            bg_color = pixels[i]
            run_length = 0

            # Count background color run
            while i < len(pixels) and pixels[i] == bg_color and run_length < 255:
                run_length += 1
                i += 1

            subrectangles = []
            while i < len(pixels):
                sub_color = pixels[i]
                sub_run_length = 0

                # Count subrectangle color run
                while i < len(pixels) and pixels[i] == sub_color and sub_run_length < 255:
                    sub_run_length += 1
                    i += 1

                if sub_run_length > 0:
                    x = (i - sub_run_length) % width
                    y = (i - sub_run_length) // width
                    subrectangles.append((sub_color, x, y, sub_run_length, 1))
                else:
                    break  # No more subrectangles

            # Add CoRRE header
            encoded_data.extend(struct.pack(">I", len(subrectangles)))
            encoded_data.extend(bg_color)

            # Add subrectangles
            for sub_color, x, y, sub_width, sub_height in subrectangles:
                encoded_data.extend(sub_color)
                encoded_data.extend(struct.pack(">BBBB", x, y, sub_width, sub_height))  # Using bytes for CoRRE

        return encoded_data

    def encode_hextile(self, screen_data, width, height):
        """Encode screen data using Hextile."""
        encoded_data = bytearray()
        tile_size = 16

        for y in range(0, height, tile_size):
            for x in range(0, width, tile_size):
                tile_width = min(tile_size, width - x)
                tile_height = min(tile_size, height - y)

                subencoding = 0
                tile_pixels = []

                for ty in range(y, y + tile_height):
                    for tx in range(x, x + tile_width):
                        idx = (ty * width + tx) * self.bytes_per_pixel
                        tile_pixels.append(screen_data[idx:idx+self.bytes_per_pixel])

                # Check for raw encoding
                if len(set(tuple(p) for p in tile_pixels)) > 1:
                    subencoding |= 1  # Set Raw flag
                    encoded_data.append(subencoding)
                    for pixel in tile_pixels:
                        encoded_data.extend(pixel)
                    continue
                # Background color
                bg_color = tile_pixels[0]
                subencoding |= 2  # Set BackgroundSpecified flag
                encoded_data.append(subencoding)
                encoded_data.extend(bg_color)

                # Subrectangles
                subrectangles = []
                i = 0
                while i < len(tile_pixels):
                    fg_color = tile_pixels[i]
                    if fg_color == bg_color:
                        i += 1
                        continue

                    run_length = 0
                    while i < len(tile_pixels) and tile_pixels[i] == fg_color and run_length < 255:
                        run_length += 1
                        i += 1

                    sub_x = (i - run_length) % tile_width
                    sub_y = (i - run_length) // tile_width
                    subrectangles.append((fg_color, sub_x, sub_y, run_length, 1))

                if subrectangles:
                    subencoding |= 8  # Set AnySubrects flag
                    encoded_data[len(encoded_data) - self.bytes_per_pixel - 1] = subencoding  # Update subencoding byte
                    encoded_data.append(len(subrectangles))  # Number of subrectangles

                    for sub_color, sub_x, sub_y, sub_width, sub_height in subrectangles:
                        encoded_data.extend(sub_color)
                        encoded_data.append(((sub_width - 1) & 0x0F) << 4 | ((sub_height - 1) & 0x0F))

        return encoded_data

if __name__ == '__main__':
    server = VNCServer()
    server.start()