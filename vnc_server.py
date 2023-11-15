import hashlib
import os
import signal
import socket
import struct
import sys
import threading
import pyautogui

from PIL import ImageGrab

# Define the supported encodings according to RFB 003.003
SUPPORTED_ENCODINGS = {
    0: "Raw",
    1: "CopyRect",
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
    Capture a screenshot and convert it to RGBA format.
    """
    screenshot = ImageGrab.grab()
    screenshot_rgba = screenshot.convert('RGBA')
    return screenshot, screenshot_rgba.tobytes(), hashlib.md5(screenshot_rgba.tobytes()).digest()


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


def send_framebuffer_update(client_socket, screen_data, x_position, y_position, width, height, full_width, full_height):
    """
    Sends a framebuffer update to the client, divided into smaller chunks if necessary.
    """
    bytes_per_pixel = 4  # Assuming 32 bits-per-pixel

    # Ensure width and height are within 16-bit unsigned integer range
    width = min(width, 65535)
    height = min(height, 65535)
    
    # Ensure x_position and y_position are within 16-bit unsigned integer range
    x_position = min(x_position, 65535 - width)
    y_position = min(y_position, 65535 - height)

    # Send the framebuffer update message header
    num_rectangles = 1  # Sending one rectangle at a time
    client_socket.sendall(struct.pack(">BxH", 0, num_rectangles))

    # Calculate the size of the rectangle data
    rectangle_size = width * height * bytes_per_pixel
    if rectangle_size > len(screen_data):
        # If calculated data size is larger than actual screen data size, send only the available data
        rectangle_size = len(screen_data)

    # Send the rectangle header
    encoding_type = 0  # Raw encoding
    client_socket.sendall(struct.pack(">HHHHI", x_position, y_position, width, height, encoding_type))

    # Send the rectangle data in chunks
    start_index = 0
    while start_index < rectangle_size:
        end_index = min(start_index + CHUNK_SIZE, rectangle_size)
        client_socket.sendall(screen_data[start_index:end_index])
        start_index = end_index


def send_copyrect_update(client_socket, src_x, src_y, x_position, y_position, width, height):
    """
    Sends a CopyRect update to the client.

    :param client_socket: The socket connected to the client.
    :param src_x: The x-coordinate of the source rectangle.
    :param src_y: The y-coordinate of the source rectangle.
    :param x_position: The x-coordinate of the destination rectangle.
    :param y_position: The y-coordinate of the destination rectangle.
    :param width: The width of the rectangle to be copied.
    :param height: The height of the rectangle to be copied.
    """
    num_rectangles = 1
    client_socket.sendall(struct.pack(">BxH", 0, num_rectangles))  # FramebufferUpdate message type

    # Specify the CopyRect encoding
    encoding_type = 1  # CopyRect encoding
    client_socket.sendall(struct.pack(">HHHHIHH", x_position, y_position, width, height, encoding_type, src_x, src_y))


def extract_subrectangle(screen_data, x, y, width, height, full_width, full_height, bytes_per_pixel):
    """
    Extract a subrectangle from the full screen data.
    """
    subrect_data = bytearray()

    for row in range(height):
        # Start of the row in the full image data
        full_row_start = (y + row) * full_width * bytes_per_pixel
        # Start of the row within the subrectangle
        subrect_start = full_row_start + x * bytes_per_pixel
        # Extract this row from the full image data
        subrect_data.extend(screen_data[subrect_start:subrect_start + width * bytes_per_pixel])

    return bytes(subrect_data)

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
        print(f"Received {len(data)} bytes, expecting {n} more bytes.")  # Debugging line
    return buf

def handle_client_messages(client_socket, client_encodings):
    """Process messages received from the client."""
    try:
        message_type = struct.unpack(">B", recv_exact(client_socket, 1))[0]
    except struct.error as e:
        print(f"Error reading message type: {e}")
        return None, {}
    try:
        print(f"Processing message of type {message_type}")

        if message_type == 0:
            recv_exact(client_socket, 3)
            pixel_format = struct.unpack(">BBBBHHHBBB3x", recv_exact(client_socket, 16))
            return 'SetPixelFormat', pixel_format

        # Existing code in handle_client_messages
        elif message_type == 2:  # SetEncodings
            _, number_of_encodings = struct.unpack(">BH", recv_exact(client_socket, 3))
            encodings = struct.unpack(">" + "I"*number_of_encodings, recv_exact(client_socket, 4 * number_of_encodings))
            
            # Clear the set of client encodings and add the new ones
            client_encodings.clear()
            for encoding in encodings:
                if encoding in SUPPORTED_ENCODINGS:
                    client_encodings.add(encoding)  # Use 'add' to include encodings in the set
            return 'SetEncodings', client_encodings

        elif message_type == 3:
            data = recv_exact(client_socket, 9)
            incremental, x_position, y_position, width, height = struct.unpack(">BHHHH", data)
            print(f"FrameBufferUpdate request: x={x_position}, y={y_position}, width={width}, height={height}, incremental={incremental}")
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
            try:
                data = recv_exact(client_socket, 5)  # Expecting 5 bytes after the message type
                button_mask, x_position, y_position = struct.unpack(">BHH", data)
                print(f"Pointer event: button_mask={button_mask}, x={x_position}, y={y_position}")
                # Here you would handle the event, for example:
                handle_pointer_event(button_mask, x_position, y_position)
                return 'PointerEvent', {
                    'button_mask': button_mask,
                    'x_position': x_position,
                    'y_position': y_position
                }
            except struct.error as e:
                print(f"Error unpacking PointerEvent: {e}. Data received: {data}")

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
    except Exception as e:
        print(f"Error processing message type {message_type}: {e}")


def handle_pointer_event(button_mask, x_position, y_position):
    """
    Handle pointer events from the VNC client.

    :param client_socket: The client's socket object.
    :param button_mask: The current state of buttons 1 to 8.
    :param x_position: The x-coordinate of the pointer.
    :param y_position: The y-coordinate of the pointer.
    """
    # Move the mouse to the specified position
    pyautogui.moveTo(x_position, y_position)

    # Check each button in the button_mask and perform the appropriate click action
    # Button masks are typically as follows:
    # 1 - Left mouse button
    # 2 - Middle mouse button (or wheel click)
    # 4 - Right mouse button
    # Additional buttons may follow these in the mask
    if button_mask & 1:  # If the left mouse button state is changed
        if button_mask & 1:
            pyautogui.mouseDown(button='left')
        else:
            pyautogui.mouseUp(button='left')

    if button_mask & 2:  # If the middle mouse button state is changed
        if button_mask & 2:
            pyautogui.mouseDown(button='middle')
        else:
            pyautogui.mouseUp(button='middle')

    if button_mask & 4:  # If the right mouse button state is changed
        if button_mask & 4:
            pyautogui.mouseDown(button='right')
        else:
            pyautogui.mouseUp(button='right')

def handle_client(client_socket, addr):
    """Handle individual client connections."""
    
    client_encodings = set()
    
    last_screenshot_data = None  # Store the previous screenshot data here
    last_screen_checksum = None  # Store the previous checksum here
    
    try:
        # Get the screen dimensions
        screen_width, screen_height = pyautogui.size()
        # Initialize framebuffer dimensions
        framebuffer_width = screen_width
        framebuffer_height = screen_height
        # Initialize full dimensions (to be captured from the screen)
        full_width, full_height = framebuffer_width, framebuffer_height

        # 1. Handshake
        server_version = b"RFB 003.003\n"
        client_socket.sendall(server_version)
        client_version_data = client_socket.recv(12)

        # Validate the client's protocol version
        if client_version_data != server_version:
            client_socket.close()
            return

        # 2. Authentication
        # RFB 003.003 expects a 4-byte security-type
        client_socket.sendall(struct.pack(">I", 2))  # VNC Authentication
        
        # Generate a random 16-byte challenge
        challenge = os.urandom(16)
        client_socket.sendall(challenge)

        # The client's response is ignored in this simplified example
        client_socket.recv(16)

        # Authentication is always successful
        client_socket.sendall(struct.pack(">I", 0))  # Authentication OK

        # 3. ClientInit
        # The shared-flag is ignored in this simplified example
        client_socket.recv(1)

        # 4. ServerInit
        pixel_format = struct.pack(
            ">BBBBHHHBBB3x",  # Format zgodny z RGBA i dodatkowy padding
            32,  # bits-per-pixel (32 dla RGBA)
            24,  # depth (24, ponieważ RGBA używa 24 bitów na kolor)
            0,   # big-endian-flag
            1,   # true-colour-flag
            255, # red-max
            255, # green-max
            255, # blue-max
            16,  # red-shift (przesunięcie dla czerwonego koloru)
            8,   # green-shift (przesunięcie dla zielonego)
            0    # blue-shift (przesunięcie dla niebieskiego)
        )  # Dodatkowy padding '3x' na końcu

        name_length = len("Python VNC Server")
        server_init_msg = struct.pack(
            ">HH16sI", 
            framebuffer_width,  # Szerokość ramki
            framebuffer_height, # Wysokość ramki
            pixel_format,       # Zdefiniowany wyżej format piksela
            name_length         # Długość nazwy serwera
        ) + b"Python VNC Server"  # Nazwa serwera

        client_socket.sendall(server_init_msg)

        last_screen_checksum = b""

        while True:
            message_type, message_data = handle_client_messages(client_socket, client_encodings)
            
            if not message_type:
                print("Didn't receive a valid message from the client, closing the connection.")
                break
            
            if message_type == 'SetEncodings':
                encodings = message_data
                # Reset the client encodings and add the new ones
                client_encodings.clear()
                client_encodings.update(encodings)
                print(f"Client encodings updated: {client_encodings}")

            elif message_type == 'FrameBufferUpdate':
                incremental = message_data['incremental']
                if 1 in client_encodings:  # CopyRect is preferred
                    # You will need logic here to determine when to use CopyRect
                    # For now, we are just using it every time for demonstration purposes
                    # In a real-world scenario, you would check if there are areas that have moved
                    src_x, src_y = 100, 100  # Example: Original position of the moved rectangle
                    dest_x, dest_y = 200, 200  # Example: New position of the moved rectangle
                    rect_width, rect_height = 50, 50  # Example: Size of the moved rectangle

                    # Send the CopyRect update
                    send_copyrect_update(client_socket, src_x, src_y, dest_x, dest_y, rect_width, rect_height)
                else:  # Raw encoding or if CopyRect is not chosen
                    # Capture screen data
                    screenshot, screen_data, screen_checksum = capture_screen_from_desktop()

                    # If incremental update is requested and there are no changes, send an empty update
                    if incremental and screen_checksum == last_screen_checksum:
                        client_socket.sendall(struct.pack(">BxH", 0, 0))  # No rectangles update
                        continue

                    # Otherwise, send a full update
                    send_framebuffer_update(client_socket, screen_data,
                                            message_data['x_position'], message_data['y_position'],
                                            message_data['width'], message_data['height'],
                                            full_width, full_height)

                    # Store the current screenshot data and checksum
                    last_screenshot_data = screen_data
                    last_screen_checksum = screen_checksum

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
