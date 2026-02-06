#!/usr/bin/env python3
"""
LAN Latency Benchmark for VNC Server

Connects as a minimal VNC client and measures:
- TCP connect time
- VNC handshake time
- Frame request-to-response latency

Usage: python benchmarks/benchmark_lan_latency.py <host> [port] [iterations]
"""

import socket
import struct
import time
import sys
import statistics


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes"""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf


def benchmark_connect(host: str, port: int) -> float:
    """Measure TCP connect time"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    start = time.perf_counter()
    sock.connect((host, port))
    elapsed = time.perf_counter() - start
    sock.close()
    return elapsed


def vnc_handshake(sock: socket.socket) -> float:
    """Perform VNC handshake and return elapsed time"""
    start = time.perf_counter()

    # Receive server version
    server_version = recv_exact(sock, 12)

    # Send client version (match server)
    sock.sendall(server_version)

    # Receive security types
    num_types_data = recv_exact(sock, 1)
    num_types = struct.unpack("B", num_types_data)[0]

    if num_types == 0:
        # Error
        reason_len = struct.unpack(">I", recv_exact(sock, 4))[0]
        reason = recv_exact(sock, reason_len)
        raise ConnectionError(f"Server rejected: {reason.decode()}")

    security_types = recv_exact(sock, num_types)

    # Select None auth (type 1) if available
    if 1 in security_types:
        sock.sendall(struct.pack("B", 1))
    elif 2 in security_types:
        raise ConnectionError("Server requires VNC auth - run benchmark without password")
    else:
        raise ConnectionError(f"No supported security type: {list(security_types)}")

    # Receive security result
    result = struct.unpack(">I", recv_exact(sock, 4))[0]
    if result != 0:
        raise ConnectionError("Authentication failed")

    # Send ClientInit (shared=1)
    sock.sendall(struct.pack("B", 1))

    # Receive ServerInit
    init_data = recv_exact(sock, 4)  # width, height
    width, height = struct.unpack(">HH", init_data)
    recv_exact(sock, 16)  # pixel format
    name_len = struct.unpack(">I", recv_exact(sock, 4))[0]
    recv_exact(sock, name_len)  # server name

    elapsed = time.perf_counter() - start
    return elapsed


def measure_frame_latency(sock: socket.socket, width: int, height: int) -> float:
    """Request a frame and measure response time"""
    # Send FramebufferUpdateRequest (type 3)
    # incremental=0, x=0, y=0, width, height
    request = struct.pack(">BBHHHH", 3, 0, 0, 0, width, height)

    start = time.perf_counter()
    sock.sendall(request)

    # Receive FramebufferUpdate response header
    header = recv_exact(sock, 4)  # type + padding + num_rectangles
    msg_type, num_rects = struct.unpack(">BxH", header)

    if msg_type != 0:
        raise ConnectionError(f"Unexpected message type: {msg_type}")

    # Read all rectangles
    for _ in range(num_rects):
        rect_header = recv_exact(sock, 12)
        rx, ry, rw, rh, encoding = struct.unpack(">HHHHi", rect_header)

        # Read rectangle data based on encoding
        if encoding == 0:  # Raw
            data_size = rw * rh * 4  # Assume 32bpp
            recv_exact(sock, data_size)
        elif encoding == 2:  # RRE
            num_subrects_data = recv_exact(sock, 4)
            num_subrects = struct.unpack(">I", num_subrects_data)[0]
            recv_exact(sock, 4)  # background pixel
            recv_exact(sock, num_subrects * (4 + 8))  # pixel + x,y,w,h
        elif encoding == 5:  # Hextile
            # Hextile: read tiles
            for ty in range(0, rh, 16):
                for tx in range(0, rw, 16):
                    tw = min(16, rw - tx)
                    th = min(16, rh - ty)
                    subencoding = recv_exact(sock, 1)[0]
                    if subencoding & 0x01:  # Raw
                        recv_exact(sock, tw * th * 4)
                    else:
                        if subencoding & 0x02:  # background
                            recv_exact(sock, 4)
                        if subencoding & 0x04:  # foreground
                            recv_exact(sock, 4)
                        if subencoding & 0x08:  # any subrects
                            num_sub = recv_exact(sock, 1)[0]
                            if subencoding & 0x10:  # colored
                                recv_exact(sock, num_sub * (4 + 2))
                            else:
                                recv_exact(sock, num_sub * 2)
        elif encoding == 16:  # ZRLE
            zrle_len = struct.unpack(">I", recv_exact(sock, 4))[0]
            recv_exact(sock, zrle_len)
        elif encoding == 7:  # Tight
            # Tight is complex; read until we get all data
            # For benchmark purposes, read the control byte and data
            control = recv_exact(sock, 1)[0]
            comp_type = control & 0x0F
            if comp_type <= 3:  # Basic compression
                # Read compact length
                length = 0
                for i in range(3):
                    b = recv_exact(sock, 1)[0]
                    length |= (b & 0x7F) << (7 * i)
                    if not (b & 0x80):
                        break
                recv_exact(sock, length)
            elif comp_type == 8:  # Fill
                recv_exact(sock, 3)  # RGB
            elif comp_type == 9:  # JPEG
                length = 0
                for i in range(3):
                    b = recv_exact(sock, 1)[0]
                    length |= (b & 0x7F) << (7 * i)
                    if not (b & 0x80):
                        break
                recv_exact(sock, length)
        elif encoding == -223:  # DesktopSize
            pass  # No data
        else:
            # Unknown encoding - try to read raw data
            recv_exact(sock, rw * rh * 4)

    elapsed = time.perf_counter() - start
    return elapsed


def run_benchmark(host: str, port: int = 5900, iterations: int = 50):
    """Run the full benchmark suite"""
    print(f"VNC LAN Latency Benchmark")
    print(f"Target: {host}:{port}")
    print(f"Iterations: {iterations}")
    print("=" * 60)

    # 1. TCP Connect benchmark
    print("\n[1/3] TCP Connect Time")
    connect_times = []
    for i in range(min(iterations, 20)):
        try:
            t = benchmark_connect(host, port)
            connect_times.append(t * 1000)  # ms
        except Exception as e:
            print(f"  Connect failed: {e}")
            break
        time.sleep(0.05)  # Small delay between connects

    if connect_times:
        print(f"  Min:  {min(connect_times):.2f} ms")
        print(f"  Avg:  {statistics.mean(connect_times):.2f} ms")
        print(f"  P50:  {statistics.median(connect_times):.2f} ms")
        if len(connect_times) >= 20:
            sorted_t = sorted(connect_times)
            p95_idx = int(len(sorted_t) * 0.95)
            p99_idx = int(len(sorted_t) * 0.99)
            print(f"  P95:  {sorted_t[p95_idx]:.2f} ms")
            print(f"  P99:  {sorted_t[p99_idx]:.2f} ms")

    # 2. VNC Handshake benchmark
    print("\n[2/3] VNC Handshake Time")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.connect((host, port))

    try:
        handshake_time = vnc_handshake(sock) * 1000
        print(f"  Handshake: {handshake_time:.2f} ms")
    except Exception as e:
        print(f"  Handshake failed: {e}")
        sock.close()
        return

    # Get dimensions from a first frame request
    request = struct.pack(">BBHHHH", 3, 0, 0, 0, 1920, 1080)
    sock.sendall(request)
    header = recv_exact(sock, 4)
    _, num_rects = struct.unpack(">BxH", header)
    width, height = 1920, 1080
    for _ in range(num_rects):
        rect_header = recv_exact(sock, 12)
        rx, ry, rw, rh, encoding = struct.unpack(">HHHHi", rect_header)
        width, height = max(width, rw), max(height, rh)
        if encoding == 0:
            recv_exact(sock, rw * rh * 4)
        elif encoding == 16:
            zrle_len = struct.unpack(">I", recv_exact(sock, 4))[0]
            recv_exact(sock, zrle_len)

    # 3. Frame latency benchmark
    print(f"\n[3/3] Frame Request-to-Response Latency ({width}x{height})")
    frame_times = []

    # Set encodings to prefer Raw for accurate latency measurement
    enc_list = [0]  # Raw only
    enc_msg = struct.pack(">BxH", 2, len(enc_list))
    for enc in enc_list:
        enc_msg += struct.pack(">i", enc)
    sock.sendall(enc_msg)

    # Warm up
    for _ in range(3):
        try:
            measure_frame_latency(sock, width, height)
        except Exception:
            pass
        time.sleep(0.01)

    # Measure
    for i in range(iterations):
        try:
            t = measure_frame_latency(sock, width, height) * 1000
            frame_times.append(t)
        except Exception as e:
            print(f"  Frame {i} failed: {e}")
            break
        time.sleep(0.005)  # Small delay

    sock.close()

    if frame_times:
        sorted_t = sorted(frame_times)
        print(f"  Min:  {min(frame_times):.2f} ms")
        print(f"  Avg:  {statistics.mean(frame_times):.2f} ms")
        print(f"  P50:  {statistics.median(frame_times):.2f} ms")
        p95_idx = max(0, int(len(sorted_t) * 0.95) - 1)
        p99_idx = max(0, int(len(sorted_t) * 0.99) - 1)
        print(f"  P95:  {sorted_t[p95_idx]:.2f} ms")
        print(f"  P99:  {sorted_t[p99_idx]:.2f} ms")
        print(f"  Max:  {max(frame_times):.2f} ms")

    print("\n" + "=" * 60)
    print("Benchmark complete.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <host> [port] [iterations]")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5900
    iterations = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    run_benchmark(host, port, iterations)
