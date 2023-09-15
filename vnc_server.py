import hashlib
import os
import signal
import socket
import struct
import sys
import threading

from PIL import ImageGrab

SUPPORTED_ENCODINGS = {
    0: "Raw",
    1: "CopyRect",
    -239: "Cursor",           # Cursor pseudo-encoding
    -223: "DesktopSize",       # DesktopSize pseudo-encoding
}

CHUNK_SIZE = 4096

def send_large_data(client_socket, data):
    """
    Send a large data chunk over the socket.

    :param client_socket: The socket over which data is to be sent.
    :param data: Data to be sent.
    """
    total_sent = 0
    while total_sent < len(data):
        sent = client_socket.send(data[total_sent:total_sent+CHUNK_SIZE])
        if sent == 0:
            raise RuntimeError("Cannot send data")
        total_sent += sent

def parse_copyrect_encoding(data):
    """
    Parse CopyRect encoding data.

    :param data: The data to be parsed.
    :return: A tuple with x and y positions.
    """
    src_x_position = int.from_bytes(data[0:2], byteorder='big')
    src_y_position = int.from_bytes(data[2:4], byteorder='big')
    return src_x_position, src_y_position

last_screenshot = None  # Variable to store the previous screenshot

def capture_screen_from_desktop():
    """
    Capture a screenshot and convert it to RGB format.

    :return: A tuple containing the screenshot, its data, and its MD5 hash.
    """
    screenshot = ImageGrab.grab()
    screenshot_rgb = screenshot.convert('RGB')
    return screenshot, screenshot_rgb.tobytes(), hashlib.md5(screenshot_rgb.tobytes()).digest()

def calculate_position_difference(old_position, new_position):
    """
    Calculate the difference between two positions.

    :param old_position: Tuple of old position (x, y).
    :param new_position: Tuple of new position (x, y).
    :return: A tuple (delta_x, delta_y) representing the difference.
    """
    old_x, old_y = old_position
    new_x, new_y = new_position
    delta_x = new_x - old_x
    delta_y = new_y - old_y
    return delta_x, delta_y

def send_framebuffer_update(client_socket, screen_data, x_position, y_position, width, height, old_screen=None):
    """
    Sends a framebuffer update to the client.

    :param client_socket: The socket connected to the client.
    :param screen_data: The data of the screen to be sent.
    :param x_position: The x-coordinate of the top-left corner.
    :param y_position: The y-coordinate of the top-left corner.
    :param width: Width of the area to be updated.
    :param height: Height of the area to be updated.
    :param old_screen: The old screen data for comparison.
    """
    # If old screen data is available and new screen data is different, use CopyRect
    if old_screen and old_screen != screen_data:
        # FramebufferUpdate header
        client_socket.sendall(struct.pack(">BxH", 0, 1))

        # Sending screen data to the client (in CopyRect format)
        encoding_type = 1  # CopyRect encoding
        client_socket.sendall(struct.pack(">HHHHI", x_position, y_position, width, height, encoding_type))
        
        # Calculate the shift relative to the previous frame
        src_x, src_y = calculate_position_difference(old_screen, screen_data)
        client_socket.sendall(struct.pack(">HH", src_x, src_y))

    else:
        # FramebufferUpdate header
        client_socket.sendall(struct.pack(">BxH", 0, 1))

        # Sending screen data to the client (in Raw format)
        encoding_type = 0  # Raw encoding
        client_socket.sendall(struct.pack(">HHHHI", x_position, y_position, width, height, encoding_type))
        send_large_data(client_socket, screen_data)  # We use send_large_data instead of sendall

def send_set_color_map_entries(client_socket, first_color, colors):
    """
    Sends the SetColorMapEntries message.

    :param client_socket: The socket connected to the client.
    :param first_color: Index of the first color.
    :param colors: List of RGB color values.
    """
    # SetColorMapEntries header
    client_socket.sendall(struct.pack(">BxHH", 1, first_color, len(colors)))

    # Sending RGB values for each color
    for color in colors:
        red, green, blue = color
        client_socket.sendall(struct.pack(">HHH", red, green, blue))

def send_bell(client_socket):
    """
    Sends a Bell message.

    :param client_socket: The socket connected to the client.
    """
    client_socket.sendall(struct.pack(">B", 2))

def send_cursor_update(client_socket, cursor_image, hotspot_x, hotspot_y):
    """
    Sends a CursorUpdate message.

    :param client_socket: The socket connected to the client.
    :param cursor_image: The image of the cursor.
    :param hotspot_x: The x-coordinate of the cursor's hotspot.
    :param hotspot_y: The y-coordinate of the cursor's hotspot.
    """
    client_socket.sendall(struct.pack(">BxH", 0, 1))
    width, height = cursor_image.size
    cursor_data = cursor_image.tobytes()
    # Now we need to create a bitmask for the cursor
    mask = bytearray((width + 7) // 8 * height)
    for y in range(height):
        for x in range(width):
            if cursor_image.getpixel((x, y)) != (0, 0, 0):
                byte_idx = y * ((width + 7) // 8) + x // 8
                bit_idx = 7 - x % 8
                mask[byte_idx] |= 1 << bit_idx

    client_socket.sendall(struct.pack(">HHHHI", hotspot_x, hotspot_y, width, height, -239))
    send_large_data(client_socket, cursor_data)
    send_large_data(client_socket, mask)

def send_desktop_size_update(client_socket, width, height):
    """
    Sends a DesktopSizeUpdate message.

    :param client_socket: The socket connected to the client.
    :param width: The width of the desktop.
    :param height: The height of the desktop.
    """
    client_socket.sendall(struct.pack(">BxH", 0, 1))
    client_socket.sendall(struct.pack(">HHHHI", 0, 0, width, height, -223))

def send_server_cut_text(client_socket, text):
    """
    Sends a ServerCutText message.

    :param client_socket: The socket connected to the client.
    :param text: The text to be sent.
    """
    # ServerCutText header
    client_socket.sendall(struct.pack(">BxI", 3, len(text)))
    client_socket.sendall(text.encode())


def vnc_authenticate(client_socket):
    """
    Authenticate the VNC client.
    
    Parameters:
    - client_socket: The client's socket object.
    
    Returns:
    - bool: Always True in this implementation.
    """
    password = "password"
    password = (password + '\0' * 8)[:8]
    challenge = os.urandom(16)
    client_socket.sendall(challenge)
    client_socket.recv(16)
    client_socket.sendall(struct.pack(">L", 0))
    return True

def recv_exact(socket, n):
    """Receive exactly n bytes from the socket. Return the received bytes."""
    buf = b''
    while n > 0:
        data = socket.recv(n)
        if not data:
            raise ConnectionError("Failed to receive all data")
        buf += data
        n -= len(data)
    return buf

def handle_client_messages(client_socket, encodings):
    """Process messages received from the client."""
    try:
        message_type = struct.unpack(">B", recv_exact(client_socket, 1))[0]
    except struct.error as e:
        print(f"Error reading message type: {e}")
        return None, {}

    print(f"Processing message of type {message_type}")

    if message_type == 0:
        recv_exact(client_socket, 3)
        pixel_format = struct.unpack(">BBBBHHHBBB3x", recv_exact(client_socket, 16))
        return 'SetPixelFormat', pixel_format

    elif message_type == 2:  # SetEncodings
        _, number_of_encodings = struct.unpack(">BH", recv_exact(client_socket, 3))
        encodings = struct.unpack(">" + "I"*number_of_encodings, recv_exact(client_socket, 4 * number_of_encodings))
        
        for encoding in encodings:
            if encoding not in SUPPORTED_ENCODINGS:
                print(f"Unsupported encoding: {encoding}")
        
        return 'SetEncodings', encodings

    elif message_type == 3:
        data = recv_exact(client_socket, 9)
        incremental, x_position, y_position, width, height = struct.unpack(">BHHHH", data)
        return 'FrameBufferUpdate', {
            'incremental': incremental,
            'x_position': x_position,
            'y_position': y_position,
            'width': width,
            'height': height
        }

    elif message_type == 4:
        data = recv_exact(client_socket, 7)
        down_flag, key = struct.unpack(">BHI", data)[:2]
        return 'KeyEvent', {
            'down_flag': down_flag,
            'key': key
        }

    elif message_type == 5:  # PointerEvent
        data = recv_exact(client_socket, 6)
        button_mask, x_position, y_position = struct.unpack(">BHH", data)
        return 'PointerEvent', {
            'button_mask': button_mask,
            'x_position': x_position,
            'y_position': y_position
        }

    elif message_type == 6:  # ClientCutText
        _ = recv_exact(client_socket, 3)  # padding
        length, = struct.unpack(">I", recv_exact(client_socket, 4))
        text = recv_exact(client_socket, length).decode("latin-1")
        return 'ClientCutText', text
    
    elif message_type in SUPPORTED_ENCODINGS:
        if SUPPORTED_ENCODINGS[message_type] == "Cursor":
            # pseudo-encoding Cursor
            hotspot_x, hotspot_y, width, height = struct.unpack(">HHHH", recv_exact(client_socket, 8))
            cursor_data_length = width * height * 4 + (height * ((width + 7) // 8))
            cursor_data = recv_exact(client_socket, cursor_data_length)
            return 'CursorPseudoEncoding', {
                'hotspot_x': hotspot_x,
                'hotspot_y': hotspot_y,
                'width': width,
                'height': height,
                'cursor_data': cursor_data
            }

        elif SUPPORTED_ENCODINGS[message_type] == "DesktopSize":
            # pseudo-encoding DesktopSize
            width, height = struct.unpack(">HH", recv_exact(client_socket, 4))
            return 'DesktopSizePseudoEncoding', {
                'width': width,
                'height': height
            }

    else:
        print(f"Unknown message type: {message_type}")
        client_socket.close()
        return None, {}

    return None, {}

def handle_client(client_socket, addr):
    """Handle individual client connections."""
    try:
        # 1. Handshake 
        server_version = b"RFB 003.003\n"
        client_socket.sendall(server_version)
        client_version_data = client_socket.recv(12)

        if client_version_data != server_version:
            return

        # 2. Authentication
        client_socket.sendall(struct.pack(">I", 2))  # VNC Authentication

        challenge = os.urandom(16)
        client_socket.sendall(challenge)
        
        client_socket.recv(16)
        
        # Always OK
        client_socket.sendall(struct.pack(">I", 0))  # OK

        # 3. ClientInit
        client_init_data = client_socket.recv(1)
        client_init_data[0]
        
        # 4. ServerInit
        framebuffer_width = 1280
        framebuffer_height = 720
        client_socket.sendall(struct.pack(">HH", framebuffer_width, framebuffer_height))
        pixel_format_data = struct.pack(
            ">BBBBHHHBBB3x", 
            32, 24, 0, 1, 255, 255, 255, 16, 8, 0
        )
        client_socket.sendall(pixel_format_data)

        name = "ServerName"
        client_socket.sendall(struct.pack(">I", len(name)))
        client_socket.sendall(name.encode())

        last_screen_checksum = b""

        while True:
            encodings = []

            message_type, message_data = handle_client_messages(client_socket, encodings)
            
            if not message_type:
                print("Didn't receive a valid message from the client, closing the connection.")
                break
            
            if message_type == 'SetEncodings':
                encodings = message_data
                for encoding in encodings:
                    if encoding in SUPPORTED_ENCODINGS:
                        print(f"Client chose the encoding method: {SUPPORTED_ENCODINGS[encoding]}")

            elif message_type == 'FrameBufferUpdate':
                screenshot, screen_data, screen_checksum = capture_screen_from_desktop()
                if screen_checksum != last_screen_checksum:
                    try:
                        send_framebuffer_update(client_socket, screen_data,
                                                message_data['x_position'], message_data['y_position'],
                                                message_data['width'], message_data['height'], last_screenshot)
                        last_screen_checksum = screen_checksum
                    except Exception as e:
                        print(f"Error while sending data to client: {e}")

            elif message_type == 'CursorPseudoEncoding':
                cursor_image = ImageGrab.grab(bbox=(message_data['x_position'], 
                                                    message_data['y_position'], 
                                                    message_data['x_position'] + message_data['width'], 
                                                    message_data['y_position'] + message_data['height']))
                send_cursor_update(client_socket, cursor_image, 
                                message_data['x_position'], 
                                message_data['y_position'])

            elif message_type == 'DesktopSizePseudoEncoding':
                framebuffer_width = message_data['width']
                framebuffer_height = message_data['height']
                send_desktop_size_update(client_socket, framebuffer_width, framebuffer_height)

            elif message_type in ('KeyEvent', 'PointerEvent', 'ClientCutText'):
                pass  # Handle other client messages

    except Exception as e:
        print(f"Error while communicating with client {addr}: {e}")

    finally:
        client_socket.close()

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('0.0.0.0', 5900))
    server_socket.listen(5)
    print("Listening 0.0.0.0:5900...")

    def graceful_exit(signum, frame):
        server_socket.close()
        print("\nServer closed.")
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    while True:
        client_socket, addr = server_socket.accept()
        thread = threading.Thread(target=handle_client, args=(client_socket, addr))
        thread.start()

if __name__ == '__main__':
    main()
