# Python VNC Server (Simplified Implementation)

This Python script is a **simplified** VNC (Virtual Network Computing) server example. It implements only the essential parts of the VNC protocol and uses **Raw** encoding for sending screen updates. While it is functional for basic remote desktop access, it is **not** intended for secure production use.

## Getting Started

1. **Install Python 3.x**  
   Make sure Python 3 is installed on your machine.

2. **Install Dependencies**  
   From within the same directory as `requirements.txt`, run:
   ```bash
   pip install -r requirements.txt
   ```

3. **Create or Edit `config.json`** (Optional)  
   You can customize server settings in a JSON file named `config.json`. For example:
   ```json
   {
     "host": "0.0.0.0",
     "port": 5900,
     "password": "",
     "frame_rate": 10,
     "log_level": "DEBUG",
     "scale_factor": 0.5,
     "chunk_size": 65536
   }
   ```
   - **host / port**: Where the server listens for incoming VNC connections.  
   - **password**: Simple password authentication (RFB 003.003).  
   - **frame_rate**: Target frames per second (1–60).  
   - **log_level**: Logging verbosity (e.g., INFO, DEBUG).  
   - **scale_factor**: Resize the captured screen before sending. `1.0` means no scaling, `0.5` means 50% reduction, etc.  
   - **chunk_size**: How many bytes to send in one chunk (for Raw encoding).  

4. **Run the Server**  
   ```bash
   python vnc_server.py
   ```
   The server will load settings from `config.json` (if present) or use defaults.

## Features

- **RFB Protocol Handshake**: Basic support for RFB 003.003 version negotiation.
- **Optional Password**: A simple, “fake” VNC password mechanism for demonstration (no real encryption).
- **Raw Encoding Only**: Screen updates use Raw encoding. (Other encodings like CopyRect or Hextile are **commented out** or not implemented.)
- **Screen Capture & Optional Rescaling**: Captures the local screen via `PIL.ImageGrab`, optionally resizes it if `scale_factor` is set below 1.0.
- **Chunk-based Sending**: Large screen data is split into user-configurable chunks (e.g., 64 KB) to reduce the number of send() calls.
- **DesktopSize Pseudo-encoding**: Allows the client to request a change in screen dimensions (though in practice, it depends on the actual monitor size).
- **Frame Rate Control**: Throttles updates to avoid saturating the network or CPU (default 10 FPS, adjustable via config).
- **Mouse & Keyboard Events**: Basic pointer (mouse move/click) and key event handling (no special key mapping beyond that).

## Limitations

- **No CopyRect or Other Advanced Encodings**: Only Raw is currently active. Support for CopyRect is commented out in the code.
- **No Real Encryption**: This is for demonstration; data travels unencrypted.
- **Basic Delta Checking**: If the screen’s MD5 checksum is unchanged and `incremental=1`, the server sends zero rectangles (no update).
- **No Production Hardening**: The code is not secured for public internet exposure.
- **Limited Compatibility**: Most modern VNC clients can still connect via Raw encoding, but advanced features (like compression) are not present.

## Configuration

All adjustable parameters are designed to be loaded from `config.json`. If you omit the file, default values are used. You can also edit them directly in the source code if desired. Examples of config parameters:

- **host** (default `0.0.0.0`)
- **port** (default `5900`)
- **password** (empty by default)
- **frame_rate** (1–60)
- **log_level** (`INFO` or `DEBUG` typically)
- **scale_factor** (e.g., `1.0` for no scaling, `0.5` for half size)
- **chunk_size** (default `65536`)

## Extending and Securing

This example is **not secure** and only demonstrates a minimal approach. For real-world usage:

- **Encryption**: Add TLS or SSH tunneling to protect data in transit.
- **Robust Password Auth**: Replace the simple password check with a real credential store or advanced method.
- **More Encodings**: Implement or uncomment advanced encodings (e.g., CopyRect, Hextile, Tight) for better bandwidth efficiency.
- **Delta-based Updates**: Incorporate partial updates or advanced difference detection for improved performance.
- **Production Hardening**: Improve error handling, logging, and concurrency if used beyond local testing.

## License

This code is released under the [MIT License](LICENSE). You are free to modify and distribute it, but **please note** it is **not** intended for secure production use without significant enhancements (encryption, authentication, robust error handling, etc.).

---
**Warning**: Operating any server carries security risks. Use secure practices and additional protections if this server is accessible on an untrusted network.