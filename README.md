# Python VNC Server (Simplified Implementation)

This Python script provides a simplified implementation of a VNC (Virtual Network Computing) server. It is a minimal example that supports a subset of VNC features.

## Getting Started

To run the server:

1. Ensure Python 3.x is installed on your system.
2. Install the required Python package:

`pip install -r requirements.txt`

3. Run the server script:

`python vnc_server.py`

By default, the server listens on all interfaces at port 5900 (`0.0.0.0:5900`). You can modify the `main()` function in `vnc_server.py` to change these settings.

## Features

The server supports:

- Basic RFB protocol version negotiation.
- VNC Authentication (with a static password for demonstration purposes).
- Handling of `SetPixelFormat` and `SetEncodings` messages.
- Sending `FramebufferUpdate` messages with Raw and CopyRect encodings.
- Handling of `KeyEvent`, `PointerEvent`, and `ClientCutText` messages.

Note: The server's capabilities are rudimentary and may not perform optimally.

## Compatibility and Limitations

- The server has been tested with UltraVNC clients.
- Connections are established, but visual artifacts may appear on the screen.
- Mouse movement and click functionality are operational.

Due to its limited functionality, the current implementation may not correctly handle all aspects of screen updates and input events, potentially leading to incomplete functionality or the need for client reconnections.

## Extending and Securing the Server

This server is intended for educational and testing purposes and is not secure for production use. You may extend it with additional features and implement proper authentication and encryption for real-world applications.

## Licensing

This server is released under the MIT License, which is included in the repository. Modify and use it as needed, keeping in mind the security considerations mentioned above.

**Always use secure practices when deploying servers like this in a production environment.**