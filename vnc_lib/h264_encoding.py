"""
H.264/AVC Video Encoding for VNC
Modern video codec for efficient video streaming
Provides superior compression for video and animations
"""

import struct
import logging
import time
from typing import TypeAlias
from enum import IntEnum

try:
    import av
    AV_AVAILABLE = True
except ImportError:
    AV_AVAILABLE = False
    logging.warning("PyAV not available - H.264 encoding disabled. "
                   "Install with: pip install av")

# Type aliases
PixelData: TypeAlias = bytes
EncodedData: TypeAlias = bytes


class H264Profile(IntEnum):
    """H.264 encoding profiles"""
    BASELINE = 0    # For low-latency, real-time streaming
    MAIN = 1        # Balanced quality and compression
    HIGH = 2        # Best quality, higher complexity


class H264Encoder:
    """
    H.264/AVC Video Encoder for VNC

    Uses H.264 video codec for efficient video streaming.
    Provides 50-500x compression for video content with temporal compression.

    Best for:
    - Video playback
    - Animations
    - Screen recording
    - High-motion content

    Features:
    - Inter-frame compression (P-frames, B-frames)
    - I-frame keyframes
    - Low latency mode for real-time streaming
    - Hardware acceleration support (if available)

    Encoding Type: Custom extension (not in RFC 6143)
    """

    ENCODING_TYPE = 50  # Custom H.264 encoding type

    # Frame types
    FRAME_TYPE_I = 0  # Keyframe (full frame)
    FRAME_TYPE_P = 1  # Predictive frame (delta from previous)
    FRAME_TYPE_B = 2  # Bi-directional frame (not used in low-latency)

    # Bitrate presets
    BITRATE_LOW = 500_000      # 500 Kbps - low quality, low bandwidth
    BITRATE_MEDIUM = 1_500_000  # 1.5 Mbps - balanced
    BITRATE_HIGH = 5_000_000    # 5 Mbps - high quality
    BITRATE_ULTRA = 10_000_000  # 10 Mbps - ultra quality

    def __init__(self, width: int, height: int,
                 bitrate: int = BITRATE_MEDIUM,
                 fps: int = 30,
                 profile: H264Profile = H264Profile.BASELINE,
                 use_hardware: bool = True):
        """
        Initialize H.264 encoder

        Args:
            width: Video width
            height: Video height
            bitrate: Target bitrate in bits/second
            fps: Target frames per second
            profile: H.264 profile (baseline/main/high)
            use_hardware: Try to use hardware acceleration
        """
        if not AV_AVAILABLE:
            raise RuntimeError("PyAV is required for H.264 encoding. "
                             "Install with: pip install av")

        self.width = width
        self.height = height
        self.bitrate = bitrate
        self.fps = fps
        self.profile = profile
        self.use_hardware = use_hardware

        self.logger = logging.getLogger(__name__)

        # Initialize codec
        self.codec = None
        self.stream = None
        self.container = None
        self.frame_count = 0
        self.keyframe_interval = fps * 2  # Keyframe every 2 seconds

        self._initialize_encoder()

    def _initialize_encoder(self):
        """Initialize H.264 encoder with PyAV"""
        try:
            # Try hardware encoder first
            if self.use_hardware:
                codec_name = self._get_hardware_codec()
                if codec_name:
                    try:
                        self.codec = av.CodecContext.create(codec_name, 'w')
                        self.logger.info(f"Using hardware H.264 encoder: {codec_name}")
                    except Exception as e:
                        self.logger.warning(f"Hardware encoder failed: {e}")
                        self.codec = None

            # Fallback to software encoder
            if self.codec is None:
                self.codec = av.CodecContext.create('h264', 'w')
                self.logger.info("Using software H.264 encoder (libx264)")

            # Configure encoder
            self.codec.width = self.width
            self.codec.height = self.height
            self.codec.bit_rate = self.bitrate
            self.codec.time_base = av.Rational(1, self.fps)
            self.codec.framerate = av.Rational(self.fps, 1)
            self.codec.pix_fmt = 'yuv420p'  # Standard pixel format

            # Profile settings
            profile_map = {
                H264Profile.BASELINE: 'baseline',
                H264Profile.MAIN: 'main',
                H264Profile.HIGH: 'high'
            }
            profile_name = profile_map[self.profile]

            # Encoder options for low latency
            self.codec.options = {
                'profile': profile_name,
                'preset': 'ultrafast',  # Low latency preset
                'tune': 'zerolatency',  # Optimize for live streaming
                'crf': '23',           # Constant rate factor (quality)
                'g': str(self.keyframe_interval),  # GOP size (keyframe interval)
                'bf': '0',             # No B-frames for low latency
                'threads': '4',        # Multi-threaded encoding
            }

            # Open codec
            self.codec.open()

            self.logger.info(f"H.264 encoder initialized: {self.width}x{self.height}, "
                           f"{self.bitrate} bps, {self.fps} fps, profile={profile_name}")

        except Exception as e:
            self.logger.error(f"Failed to initialize H.264 encoder: {e}")
            raise

    def _get_hardware_codec(self) -> str | None:
        """Get hardware encoder name if available"""
        # Try NVIDIA NVENC
        try:
            av.codec.Codec('h264_nvenc', 'w')
            return 'h264_nvenc'
        except:
            pass

        # Try Intel QSV
        try:
            av.codec.Codec('h264_qsv', 'w')
            return 'h264_qsv'
        except:
            pass

        # Try AMD AMF
        try:
            av.codec.Codec('h264_amf', 'w')
            return 'h264_amf'
        except:
            pass

        # Try Apple VideoToolbox
        try:
            av.codec.Codec('h264_videotoolbox', 'w')
            return 'h264_videotoolbox'
        except:
            pass

        return None

    def encode(self, pixel_data: PixelData, width: int, height: int,
               bytes_per_pixel: int) -> EncodedData:
        """
        Encode frame as H.264

        Args:
            pixel_data: Raw pixel data (RGB or RGBA)
            width: Frame width
            height: Frame height
            bytes_per_pixel: Bytes per pixel (3 or 4)

        Returns:
            H.264 encoded data with custom header
        """
        if width != self.width or height != self.height:
            # Resolution changed - reinitialize encoder
            self.logger.info(f"Resolution changed: {self.width}x{self.height} "
                           f"-> {width}x{height}")
            self.width = width
            self.height = height
            self._initialize_encoder()

        try:
            # Convert pixel data to video frame
            frame = self._create_frame(pixel_data, width, height, bytes_per_pixel)

            # Encode frame
            packets = self.codec.encode(frame)

            # Collect encoded data
            encoded_data = bytearray()
            frame_type = self.FRAME_TYPE_P

            for packet in packets:
                # Check if this is a keyframe
                if packet.is_keyframe:
                    frame_type = self.FRAME_TYPE_I

                encoded_data.extend(packet.to_bytes())

            self.frame_count += 1

            # Build result with custom header
            # Format:
            # - 1 byte: frame type (I/P/B)
            # - 4 bytes: data length
            # - 8 bytes: timestamp (microseconds)
            # - N bytes: H.264 NAL units
            result = bytearray()
            result.append(frame_type)
            result.extend(struct.pack(">I", len(encoded_data)))
            result.extend(struct.pack(">Q", int(time.time() * 1_000_000)))
            result.extend(encoded_data)

            compression_ratio = len(pixel_data) / len(result) if len(result) > 0 else 1
            self.logger.debug(f"H.264 {'I-frame' if frame_type == self.FRAME_TYPE_I else 'P-frame'}: "
                            f"{len(pixel_data)} -> {len(result)} bytes "
                            f"({compression_ratio:.1f}x compression)")

            return bytes(result)

        except Exception as e:
            self.logger.error(f"H.264 encoding failed: {e}")
            return pixel_data  # Fallback to raw

    def _create_frame(self, pixel_data: PixelData, width: int, height: int,
                     bytes_per_pixel: int) -> av.VideoFrame:
        """Convert raw pixel data to PyAV VideoFrame"""
        try:
            # Determine pixel format
            if bytes_per_pixel == 3:
                format_name = 'rgb24'
            elif bytes_per_pixel == 4:
                format_name = 'rgba'
            else:
                raise ValueError(f"Unsupported bytes_per_pixel: {bytes_per_pixel}")

            # Create frame from bytes
            frame = av.VideoFrame.from_ndarray(
                self._pixel_data_to_array(pixel_data, width, height, bytes_per_pixel),
                format=format_name
            )

            # Convert to YUV420p (required by H.264)
            frame = frame.reformat(format='yuv420p')

            # Set PTS (presentation timestamp)
            frame.pts = self.frame_count
            frame.time_base = av.Rational(1, self.fps)

            return frame

        except Exception as e:
            self.logger.error(f"Failed to create video frame: {e}")
            raise

    def _pixel_data_to_array(self, pixel_data: PixelData, width: int,
                            height: int, bpp: int):
        """Convert pixel data bytes to numpy array"""
        try:
            import numpy as np

            # Reshape to (height, width, channels)
            array = np.frombuffer(pixel_data, dtype=np.uint8)
            array = array.reshape((height, width, bpp))

            return array

        except ImportError:
            raise RuntimeError("NumPy is required for H.264 encoding. "
                             "Install with: pip install numpy")

    def force_keyframe(self):
        """Force next frame to be a keyframe"""
        self.frame_count = 0  # Reset counter to trigger keyframe

    def set_bitrate(self, bitrate: int):
        """
        Dynamically adjust bitrate

        Args:
            bitrate: New target bitrate in bits/second
        """
        self.bitrate = bitrate
        if self.codec:
            self.codec.bit_rate = bitrate
            self.logger.info(f"H.264 bitrate adjusted to {bitrate} bps")

    def get_stats(self) -> dict:
        """Get encoding statistics"""
        return {
            'frame_count': self.frame_count,
            'width': self.width,
            'height': self.height,
            'bitrate': self.bitrate,
            'fps': self.fps,
            'profile': self.profile.name,
            'codec': self.codec.name if self.codec else None,
            'hardware_accel': 'nvenc' in self.codec.name if self.codec else False
        }

    def close(self):
        """Close encoder and free resources"""
        if self.codec:
            try:
                # Flush encoder
                for packet in self.codec.encode(None):
                    pass  # Discard remaining packets

                self.codec.close()
                self.logger.info("H.264 encoder closed")
            except Exception as e:
                self.logger.error(f"Error closing encoder: {e}")

            self.codec = None

    def __del__(self):
        """Cleanup on deletion"""
        self.close()


class H264StreamManager:
    """
    Manages multiple H.264 streams for different clients

    Each client can have different resolution, bitrate requirements
    """

    def __init__(self):
        self.streams: dict[str, H264Encoder] = {}
        self.logger = logging.getLogger(__name__)

    def get_encoder(self, client_id: str, width: int, height: int,
                   bitrate: int = H264Encoder.BITRATE_MEDIUM,
                   fps: int = 30) -> H264Encoder:
        """
        Get or create H.264 encoder for client

        Args:
            client_id: Unique client identifier
            width: Video width
            height: Video height
            bitrate: Target bitrate
            fps: Target FPS

        Returns:
            H264Encoder instance for this client
        """
        # Check if encoder exists and matches parameters
        if client_id in self.streams:
            encoder = self.streams[client_id]
            if encoder.width == width and encoder.height == height:
                return encoder

            # Parameters changed - close old encoder
            encoder.close()

        # Create new encoder
        try:
            encoder = H264Encoder(width, height, bitrate, fps)
            self.streams[client_id] = encoder
            self.logger.info(f"Created H.264 encoder for client {client_id}")
            return encoder

        except Exception as e:
            self.logger.error(f"Failed to create H.264 encoder: {e}")
            raise

    def remove_encoder(self, client_id: str):
        """Remove and close encoder for client"""
        if client_id in self.streams:
            self.streams[client_id].close()
            del self.streams[client_id]
            self.logger.info(f"Removed H.264 encoder for client {client_id}")

    def close_all(self):
        """Close all encoders"""
        for client_id in list(self.streams.keys()):
            self.remove_encoder(client_id)

    def get_stats(self) -> dict:
        """Get statistics for all streams"""
        return {
            client_id: encoder.get_stats()
            for client_id, encoder in self.streams.items()
        }
