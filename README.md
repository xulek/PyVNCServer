# Python VNC Server - RFC 6143 Compliant Implementation

A fully **RFC 6143 compliant** VNC (Virtual Network Computing) server implementation in Python. This server provides remote desktop access with proper protocol handling, authentication, and input support.

## ✨ Key Features

### RFC 6143 Compliance
- ✅ **Proper Protocol Version Negotiation** - Supports RFB 003.003, 003.007, and 003.008
- ✅ **Correct Security Handshake** - Implements both version-specific security negotiation methods
- ✅ **Proper DES Authentication** - Real VNC authentication with DES encryption (not fake)
- ✅ **Signed Encoding Types** - Correctly handles signed 32-bit integers per RFC (fixes pseudo-encodings)
- ✅ **SetPixelFormat Support** - Properly processes and applies client pixel format requests
- ✅ **Multiple Pixel Formats** - Supports 32-bit, 16-bit, and 8-bit true color modes
- ✅ **Full Keyboard Support** - KeyEvent handling with X11 keysym mapping
- ✅ **Proper Mouse Handling** - Button state tracking with press/release detection
- ✅ **DesktopSize Pseudo-encoding** - Dynamic screen resolution changes

### Technical Improvements
- 🏗️ **Modular Architecture** - Clean separation of concerns (protocol, auth, input, capture)
- 🔒 **Real Security** - Proper VNC DES authentication implementation
- 🎯 **State Tracking** - Correct mouse button state management
- 🎨 **Pixel Format Conversion** - Automatic conversion to client's requested format
- 📊 **Change Detection** - Efficient MD5-based screen change detection
- ⚡ **Performance** - Frame rate throttling and chunked data transmission

## 📁 Project Structure

```
PyVNCServer/
├── vnc_server.py           # Main server implementation
├── vnc_lib/                # VNC library modules
│   ├── __init__.py
│   ├── protocol.py         # RFC 6143 protocol handler
│   ├── auth.py             # VNC DES authentication
│   ├── input_handler.py    # Keyboard and mouse input
│   └── screen_capture.py   # Screen capture and conversion
├── config.json             # Server configuration
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## 🚀 Getting Started

### Prerequisites
- Python 3.7 or higher
- Linux/Windows/macOS (tested on Linux)

### Installation

1. **Clone the repository** (if applicable):
   ```bash
   git clone <repository-url>
   cd PyVNCServer
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the server** (optional):
   Edit `config.json`:
   ```json
   {
     "host": "0.0.0.0",
     "port": 5900,
     "password": "your_password",
     "frame_rate": 30,
     "log_level": "INFO",
     "scale_factor": 1.0
   }
   ```

4. **Run the server**:
   ```bash
   python vnc_server.py
   ```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `host` | `0.0.0.0` | Bind address (0.0.0.0 = all interfaces) |
| `port` | `5900` | VNC server port |
| `password` | `""` | VNC password (empty = no auth) |
| `frame_rate` | `30` | Target FPS (1-60) |
| `log_level` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `scale_factor` | `1.0` | Screen scaling (1.0=100%, 0.5=50%) |

## 🔧 Technical Details

### Protocol Implementation

#### Version Negotiation (RFC 6143 Section 7.1.1)
- Server sends highest supported version (003.008)
- Accepts client versions: 003.003, 003.007, 003.008
- Negotiates to highest mutually supported version

#### Security Types (RFC 6143 Section 7.1.2)
- **Type 1**: No authentication
- **Type 2**: VNC authentication with DES encryption
- Version-specific negotiation:
  - RFB 003.003: Sends security type directly
  - RFB 003.007+: Sends list, client selects

#### Authentication (RFC 6143 Section 7.2.2)
- 16-byte random challenge
- Client encrypts with DES using password
- VNC-specific bit reversal applied to key
- Proper success/failure response

#### Message Handling
All client-to-server messages implemented:
- `SetPixelFormat` (type 0) - Updates pixel format
- `SetEncodings` (type 2) - **FIXED**: Uses signed integers
- `FramebufferUpdateRequest` (type 3) - Sends screen updates
- `KeyEvent` (type 4) - **NEW**: Full keyboard support
- `PointerEvent` (type 5) - **FIXED**: Proper state tracking
- `ClientCutText` (type 6) - Clipboard support

#### Encoding Support
- **Raw Encoding (0)** - Uncompressed pixel data
- **DesktopSize (-223)** - Pseudo-encoding for resolution changes

### Fixed Issues from Previous Version

1. ✅ **Protocol Version** - Now properly negotiates versions instead of forcing 003.003
2. ✅ **SetEncodings** - Changed from unsigned to signed integers (fixes pseudo-encodings)
3. ✅ **Mouse Handling** - Implemented proper button state tracking
4. ✅ **DesktopSize** - Removed incorrect handling as client message
5. ✅ **ColorMap** - No longer sent for TrueColor mode
6. ✅ **SetPixelFormat** - Now properly parsed and applied
7. ✅ **KeyEvent** - Fully implemented with X11 keysym mapping
8. ✅ **Authentication** - Real DES encryption instead of fake auth
9. ✅ **Project Structure** - Modularized into separate components

## 🔒 Security Considerations

### Current Implementation
- Uses VNC DES authentication (insecure by modern standards)
- Data transmitted unencrypted
- Suitable for trusted networks only

### Recommendations for Production
1. **Use SSH Tunnel**:
   ```bash
   ssh -L 5900:localhost:5900 user@server
   ```

2. **Use VPN**: Run VNC over a VPN connection

3. **Firewall**: Restrict access to trusted IP addresses

4. **Strong Password**: Use a complex VNC password (max 8 characters)

## 🧪 Testing

### Connect with VNC Client

**TightVNC Viewer**:
```bash
vncviewer localhost:5900
```

**RealVNC Viewer**:
```bash
vncviewer localhost::5900
```

**From Another Machine**:
```bash
vncviewer <server-ip>:5900
```

### Supported Clients
Tested with:
- ✅ TightVNC Viewer
- ✅ RealVNC Viewer
- ✅ TigerVNC Viewer
- ✅ Remmina (Linux)
- ✅ VNC Viewer (macOS)

## 📝 Development

### Adding New Encodings

To add support for compressed encodings (Tight, ZRLE, etc.):

1. Add encoding constant to `protocol.py`:
   ```python
   ENCODING_TIGHT = 7
   ```

2. Implement encoding in `screen_capture.py`:
   ```python
   def encode_tight(self, data, width, height):
       # Encoding implementation
       pass
   ```

3. Update `vnc_server.py` to use encoding based on client preferences

### Running Tests

```bash
# Basic connection test
python -c "import socket; s=socket.socket(); s.connect(('localhost',5900)); print('OK')"

# Debug mode
# Edit config.json: "log_level": "DEBUG"
python vnc_server.py
```

## 🐛 Troubleshooting

### Connection Refused
- Check firewall settings
- Verify server is running: `netstat -tulpn | grep 5900`
- Check bind address in config.json

### Authentication Fails
- Ensure pycryptodome is installed: `pip install pycryptodome`
- Check password matches in both server and client
- VNC passwords are limited to 8 characters

### Black Screen
- Check screen capture permissions (macOS requires accessibility permissions)
- Verify scale_factor is not too small
- Check logs for capture errors

### Slow Performance
- Reduce frame_rate in config.json
- Increase scale_factor to reduce resolution
- Use lower color depth in VNC client

## 📚 References

- [RFC 6143 - The Remote Framebuffer Protocol](https://tools.ietf.org/html/rfc6143)
- [RealVNC Protocol Documentation](https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst)

## 📄 License

This code is released under the [MIT License](LICENSE).

## ⚠️ Disclaimer

This VNC server is provided for educational and development purposes. While it implements RFC 6143 correctly, VNC itself is not a secure protocol by modern standards. Use SSH tunneling or VPN for secure remote access in production environments.

## 🆚 Version History

### v2.0.0 (Current)
- ✅ Full RFC 6143 compliance
- ✅ Modular architecture
- ✅ Real DES authentication
- ✅ Multiple protocol versions
- ✅ Proper pixel format support
- ✅ Complete keyboard/mouse handling

### v1.0.0 (Previous)
- Basic VNC functionality
- Single file implementation
- Fake authentication
- Limited RFC compliance

---

**Made with ❤️ for the VNC community**
