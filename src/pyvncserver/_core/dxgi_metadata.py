"""DXGI Desktop Duplication dirty/move rectangle metadata support.

DXCam already owns the IDXGIOutputDuplication object used for capture. The
public DXCam API exposes pixels rather than frame metadata, so PyVNCServer
attaches a small optional hook around DXCam's duplicator to read
GetFrameDirtyRects/GetFrameMoveRects while the acquired frame is still held.

The hook is deliberately fail-safe for correctness: when metadata cannot be
read safely, callers receive ``None`` and fall back to the software change
detector instead of assuming that the framebuffer did not change.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import logging
import os
from typing import Any, Protocol, TYPE_CHECKING

Rectangle = tuple[int, int, int, int]

if TYPE_CHECKING:
    from .capture_backends import CaptureMoveRect


_GET_FRAME_DIRTY_RECTS_INDEX = 9
_GET_FRAME_MOVE_RECTS_INDEX = 10
_MAX_METADATA_BYTES = 8 * 1024 * 1024
_MAX_METADATA_RECTS = 65535

_UINT = ctypes.c_uint32
_HRESULT = ctypes.c_int32
_WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_int32),
        ("top", ctypes.c_int32),
        ("right", ctypes.c_int32),
        ("bottom", ctypes.c_int32),
    ]


class _MoveRect(ctypes.Structure):
    _fields_ = [("source_point", _Point), ("destination_rect", _Rect)]


@dataclass(frozen=True, slots=True)
class DXGIFrameMetadata:
    """Validated Desktop Duplication metadata for one acquired frame."""

    dirty_regions: tuple[Rectangle, ...]
    move_rects: tuple[CaptureMoveRect, ...]


class DXGIMetadataReaderProtocol(Protocol):
    def is_supported(self) -> bool: ...
    def read(self, duplicator_pointer: Any) -> DXGIFrameMetadata | None: ...


class DXGIMetadataReader:
    """Read dirty and move rectangles from an IDXGIOutputDuplication pointer."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    def is_supported(self) -> bool:
        return os.name == "nt"

    def read(self, duplicator_pointer: Any) -> DXGIFrameMetadata | None:
        if not self.is_supported() or not duplicator_pointer:
            return None
        try:
            move_buffer = self._read_buffer(
                duplicator_pointer,
                _GET_FRAME_MOVE_RECTS_INDEX,
                ctypes.sizeof(_MoveRect),
            )
            dirty_buffer = self._read_buffer(
                duplicator_pointer,
                _GET_FRAME_DIRTY_RECTS_INDEX,
                ctypes.sizeof(_Rect),
            )
            if move_buffer is None or dirty_buffer is None:
                return None
            move_rects = self._decode_moves(move_buffer)
            dirty_regions = self._decode_dirty(dirty_buffer)
            if move_rects is None or dirty_regions is None:
                return None
            return DXGIFrameMetadata(tuple(dirty_regions), tuple(move_rects))
        except Exception as exc:
            self.logger.debug("Unable to read DXGI frame metadata: %s", exc)
            return None

    def _read_buffer(self, duplicator_pointer: Any, method_index: int,
                     item_size: int) -> bytes | None:
        method, this_pointer = self._bind_metadata_method(
            duplicator_pointer, method_index
        )
        required = _UINT(0)
        try:
            probe_hr = int(method(this_pointer, 0, None, ctypes.byref(required)))
        except Exception:
            return None

        size = int(required.value)
        if size == 0:
            return b"" if probe_hr >= 0 else None
        if size < item_size or size > _MAX_METADATA_BYTES:
            return None
        if size // item_size > _MAX_METADATA_RECTS:
            return None

        buffer = ctypes.create_string_buffer(size)
        returned = _UINT(size)
        hr = int(method(
            this_pointer,
            size,
            ctypes.cast(buffer, ctypes.c_void_p),
            ctypes.byref(returned),
        ))
        if hr < 0:
            return None

        used = int(returned.value)
        if used < 0 or used > size or used % item_size != 0:
            return None
        return bytes(buffer.raw[:used])

    @staticmethod
    def _bind_metadata_method(duplicator_pointer: Any, method_index: int):
        this_pointer = ctypes.cast(duplicator_pointer, ctypes.c_void_p)
        if not this_pointer.value:
            raise ValueError("null IDXGIOutputDuplication pointer")
        vtable_ptr = ctypes.cast(
            duplicator_pointer,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ).contents
        function_address = vtable_ptr[method_index]
        if isinstance(function_address, ctypes.c_void_p):
            function_address = function_address.value
        if not function_address:
            raise ValueError("missing IDXGIOutputDuplication vtable entry")
        prototype = _WINFUNCTYPE(
            _HRESULT,
            ctypes.c_void_p,
            _UINT,
            ctypes.c_void_p,
            ctypes.POINTER(_UINT),
        )
        return prototype(function_address), this_pointer

    @staticmethod
    def _decode_dirty(buffer: bytes) -> list[Rectangle] | None:
        if not buffer:
            return []
        item_size = ctypes.sizeof(_Rect)
        if len(buffer) % item_size:
            return None
        values = (_Rect * (len(buffer) // item_size)).from_buffer_copy(buffer)
        regions: list[Rectangle] = []
        for rect in values:
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width > 0 and height > 0:
                regions.append((int(rect.left), int(rect.top), width, height))
        return regions

    @staticmethod
    def _decode_moves(buffer: bytes) -> list[CaptureMoveRect] | None:
        if not buffer:
            return []
        item_size = ctypes.sizeof(_MoveRect)
        if len(buffer) % item_size:
            return None
        from .capture_backends import CaptureMoveRect
        values = (_MoveRect * (len(buffer) // item_size)).from_buffer_copy(buffer)
        moves: list[CaptureMoveRect] = []
        for item in values:
            dst = item.destination_rect
            width = int(dst.right - dst.left)
            height = int(dst.bottom - dst.top)
            if width > 0 and height > 0:
                moves.append(CaptureMoveRect(
                    src_x=int(item.source_point.x),
                    src_y=int(item.source_point.y),
                    dst_x=int(dst.left),
                    dst_y=int(dst.top),
                    width=width,
                    height=height,
                ))
        return moves


class DXGIMetadataHook:
    """Attach metadata collection to the private DXCam DXGI duplicator."""

    def __init__(self, reader: DXGIMetadataReaderProtocol | None = None,
                 logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.reader = reader or DXGIMetadataReader(self.logger)
        self._attached_duplicator: Any = None
        self._pending: DXGIFrameMetadata | None = None
        self._pending_valid = False

    @property
    def is_available(self) -> bool:
        return bool(self._attached_duplicator is not None and self.reader.is_supported())

    def ensure_attached(self, camera: Any) -> bool:
        if not self.reader.is_supported():
            return False
        if getattr(camera, "backend", "dxgi") != "dxgi":
            return False
        duplicator = getattr(camera, "_duplicator", None)
        if duplicator is None or getattr(duplicator, "duplicator", None) is None:
            return False
        if duplicator is self._attached_duplicator:
            return True
        original_update = getattr(duplicator, "update_frame", None)
        if not callable(original_update):
            return False
        hook = self

        def update_frame_with_metadata(*args: Any, **kwargs: Any) -> bool:
            ok = bool(original_update(*args, **kwargs))
            hook._pending = None
            hook._pending_valid = False
            if not ok:
                return False
            if not bool(getattr(duplicator, "updated", False)):
                hook._pending = DXGIFrameMetadata((), ())
                hook._pending_valid = True
                return True
            metadata = hook.reader.read(getattr(duplicator, "duplicator", None))
            if metadata is not None:
                hook._pending = metadata
                hook._pending_valid = True
            return True

        duplicator.update_frame = update_frame_with_metadata
        self._attached_duplicator = duplicator
        self._pending = None
        self._pending_valid = False
        return True

    def consume(self, width: int, height: int) -> DXGIFrameMetadata | None:
        if not self._pending_valid:
            return None
        pending = self._pending
        self._pending = None
        self._pending_valid = False
        if pending is None:
            return None

        dirty = tuple(
            region for region in (
                _clip_rectangle(rect, width, height)
                for rect in pending.dirty_regions
            ) if region is not None
        )
        clipped_moves: list[CaptureMoveRect] = []
        for move in pending.move_rects:
            clipped = _clip_move_rect(move, width, height)
            if clipped is not None:
                clipped_moves.append(clipped)
                continue
            destination = _clip_rectangle(
                (move.dst_x, move.dst_y, move.width, move.height), width, height
            )
            if destination is not None:
                return None
        return DXGIFrameMetadata(dirty, tuple(clipped_moves))


def _clip_rectangle(rect: Rectangle, width: int, height: int) -> Rectangle | None:
    x, y, rect_width, rect_height = map(int, rect)
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(int(width), x + rect_width)
    y2 = min(int(height), y + rect_height)
    if x1 >= x2 or y1 >= y2:
        return None
    return x1, y1, x2 - x1, y2 - y1


def _clip_move_rect(move: "CaptureMoveRect", width: int,
                    height: int) -> "CaptureMoveRect | None":
    from .capture_backends import CaptureMoveRect
    dst_x1 = max(0, int(move.dst_x))
    dst_y1 = max(0, int(move.dst_y))
    dst_x2 = min(int(width), int(move.dst_x + move.width))
    dst_y2 = min(int(height), int(move.dst_y + move.height))
    if dst_x1 >= dst_x2 or dst_y1 >= dst_y2:
        return None

    offset_x = dst_x1 - int(move.dst_x)
    offset_y = dst_y1 - int(move.dst_y)
    src_x = int(move.src_x) + offset_x
    src_y = int(move.src_y) + offset_y
    clipped_width = dst_x2 - dst_x1
    clipped_height = dst_y2 - dst_y1
    if (
        src_x < 0 or src_y < 0
        or src_x + clipped_width > width
        or src_y + clipped_height > height
    ):
        return None
    return CaptureMoveRect(
        src_x=src_x,
        src_y=src_y,
        dst_x=dst_x1,
        dst_y=dst_y1,
        width=clipped_width,
        height=clipped_height,
    )
