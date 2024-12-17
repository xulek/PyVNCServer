# Python VNC Server (Simplified Implementation)

This Python script provides a simplified implementation of a VNC (Virtual Network Computing) server. It is a minimal example that supports a subset of VNC features.

## Getting Started

To run the server:

1.  Ensure you have Python 3.x installed on your system.
2.  Install the required Python packages:

    ```bash
    pip install -r requirements.txt
    ```
3.  Run the server script:

    ```bash
    python vnc_server.py
    ```

By default, the server listens on all interfaces at port 5900 (`0.0.0.0:5900`). You can modify the `VNCServer` constructor in `vnc_server.py` to change these settings.

## Features

The server supports:

-   **RFB Protocol Version Negotiation:** Correct handling of the VNC protocol handshake.
-   **VNC Authentication:** Client authentication (using a simple password for demonstration purposes).
-   **Pixel Format Handling:** Correct configuration and transmission of the **BGRA** pixel format for accurate color display.
-   **Encoding Support:** Sending screen updates using `Raw` and `CopyRect` encodings, with an emphasis on performance and compatibility.
-   **Message Handling:** Proper handling of `SetPixelFormat`, `SetEncodings`, `FramebufferUpdate`, and events like `KeyEvent`, `PointerEvent`, and `ClientCutText`.
-   **Pseudo-Encodings:** Support for pseudo-encodings `Cursor` (for sending cursor updates) and `DesktopSize` (for sending screen size information).
-   **Frame Rate Control:** Limiting the frame transmission rate to a specific frequency (30 FPS by default) to avoid overloading resources.
-   **Logging:** Detailed logging of events, errors, and server messages for easier diagnostics.
-   **Mouse Event Handling:** Proper transmission and interpretation of mouse movements and clicks.
-   **Error Handling:** Protection against crashes and unexpected errors through `try...except` blocks.

## Compatibility and Limitations

-   The server has been tested with various VNC clients (including TightVNC, RealVNC, UltraVNC).
-   Improved pixel format handling (BGRA) eliminates the issue of incorrect colors (red and blue swapped).
-   Improved `CopyRect` handling.
-   Greater stability, compatibility, and performance compared to previous implementations.
-   Smooth operation and higher image quality.
-   Support for dynamic screen updates.
-   Support for dynamic resizing of the VNC window.
-   Support for cursor movement and mouse clicks.
-   However, due to its simplified nature, some aspects (e.g., advanced encodings) may not be supported.

## Extending and Securing the Server

This server is intended for educational and testing purposes and is not secure for production use. You can extend it with additional features and implement proper authentication and encryption for real-world applications:

*   **Encryption:** Add connection encryption (e.g., TLS) to protect transmitted data.
*   **Password Verification:** Instead of a static password, use a more advanced verification method, such as from a configuration file or database.
*   **Encoding Support:** Implement support for additional encodings for further performance optimization.
*   **Change Detection:** Add logic to detect changes on the screen for more efficient image updates and reduced network load.
*   **Configuration:** Allow configuration (port, password, options) from a configuration file or command-line arguments.

## Licensing

This server is released under the MIT License, which is included in the repository. You can modify and use it as needed, keeping in mind the security considerations mentioned above.

**Always use secure practices when deploying servers like this in a production environment.**