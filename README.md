# VNC Server in Python (Incomplete Implementation)

This is a Python VNC (Virtual Network Computing) server implementation. This server is a basic implementation that supports selected VNC features but may not work correctly in certain cases.

## Getting Started

To run this VNC server, follow these steps:

1. Clone the repository:
   ```
   git clone <repository-url>
   ```

2. Navigate to the project directory:
   ```
   cd <repository-directory>
   ```

3. Install the required dependencies:
   ```
   pip install Pillow
   ```

4. Start the VNC server:
   ```
   python vnc_server.py
   ```

The server will listen on `0.0.0.0:5900` by default. You can customize the host and port settings in the `main()` function of the `vnc_server.py` file.

## Supported Features

This VNC server implementation supports the following features:

- Handshake and protocol version negotiation.
- VNC Authentication with a default password (you can customize it in the code).
- SetPixelFormat message.
- SetEncodings message with support for Raw and CopyRect encodings.
- FrameBufferUpdate to send screen updates to the client.
- CursorPseudoEncoding to send cursor updates.
- DesktopSizePseudoEncoding to handle changes in desktop size.
- KeyEvent, PointerEvent, and ClientCutText for keyboard and mouse input and clipboard synchronization.

## Issues with Screen Updates

It's worth noting that this VNC server implementation may have issues with correctly sending screen updates, which could result in client reconnections. This is a limitation of the implementation and may require further development and improvement.

## Extending the Server

You can extend this server to support additional VNC features or enhance its security. However, please keep in mind that this is a basic implementation and may not be suitable for production environments without additional security measures.

## License

This VNC server is provided under the [MIT License](LICENSE). Feel free to modify and use it according to your needs.

Please be aware of the security implications of running a VNC server with a default password. In a production environment, it's essential to implement proper authentication and encryption mechanisms to secure remote desktop access.
