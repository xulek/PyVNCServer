"""Public rectangle-encoding API for embedders and plugins."""

from ._core.encodings import (
    CopyRectEncoder,
    Encoder,
    EncoderManager,
    EncodingNotSuitable,
    HextileEncoder,
    RREEncoder,
    RawEncoder,
    ZRLEEncoder,
    ZlibEncoder,
    encoding_name,
    format_encoding_list,
)
from ._core.h264_encoding import H264Encoder, H264Profile, H264StreamManager
from ._core.jpeg_encoding import AdaptiveJPEGEncoder, JPEGEncoder
from ._core.tight_encoding import TightCompressionControl, TightEncoder

__all__ = [
    "AdaptiveJPEGEncoder",
    "CopyRectEncoder",
    "Encoder",
    "EncoderManager",
    "EncodingNotSuitable",
    "H264Encoder",
    "H264Profile",
    "H264StreamManager",
    "HextileEncoder",
    "JPEGEncoder",
    "RREEncoder",
    "RawEncoder",
    "TightCompressionControl",
    "TightEncoder",
    "ZRLEEncoder",
    "ZlibEncoder",
    "encoding_name",
    "format_encoding_list",
]
