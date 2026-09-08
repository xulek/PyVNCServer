"""DXGI Desktop Duplication metadata hook tests."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import logging

import pyvncserver._core.dxgi_metadata as dxgi_metadata
from pyvncserver._core.capture_backends import CaptureMoveRect, DXCamCaptureBackend
from pyvncserver._core.dxgi_metadata import DXGIFrameMetadata, DXGIMetadataHook, DXGIMetadataReader


class _FakeReader:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def is_supported(self) -> bool:
        return True

    def read(self, _duplicator_pointer):
        self.calls += 1
        return self.values.pop(0) if self.values else None


class _FakeDuplicator:
    def __init__(self):
        self.duplicator = object()
        self.updated = True

    def update_frame(self, *_args, **_kwargs):
        return True


@dataclass
class _FakeCamera:
    _duplicator: _FakeDuplicator
    backend: str = "dxgi"
    width: int = 100
    height: int = 100
    region: tuple[int, int, int, int] = (0, 0, 100, 100)
    rotation_angle: int = 0


def test_decode_dirty_rectangles():
    values = (dxgi_metadata._Rect * 2)(
        dxgi_metadata._Rect(10, 20, 40, 60),
        dxgi_metadata._Rect(100, 200, 150, 220),
    )
    assert DXGIMetadataReader._decode_dirty(bytes(values)) == [
        (10, 20, 30, 40),
        (100, 200, 50, 20),
    ]


def test_decode_move_rectangles():
    values = (dxgi_metadata._MoveRect * 1)(
        dxgi_metadata._MoveRect(
            dxgi_metadata._Point(5, 7),
            dxgi_metadata._Rect(20, 30, 60, 80),
        )
    )
    assert DXGIMetadataReader._decode_moves(bytes(values)) == [
        CaptureMoveRect(src_x=5, src_y=7, dst_x=20, dst_y=30, width=40, height=50)
    ]


def test_hook_captures_metadata_once_per_frame():
    reader = _FakeReader([
        DXGIFrameMetadata(
            dirty_regions=((1, 2, 3, 4),),
            move_rects=(CaptureMoveRect(0, 0, 10, 10, 5, 5),),
        )
    ])
    duplicator = _FakeDuplicator()
    hook = DXGIMetadataHook(reader=reader)
    assert hook.ensure_attached(_FakeCamera(duplicator))
    assert duplicator.update_frame()

    metadata = hook.consume(100, 100)
    assert metadata == DXGIFrameMetadata(
        dirty_regions=((1, 2, 3, 4),),
        move_rects=(CaptureMoveRect(0, 0, 10, 10, 5, 5),),
    )
    assert hook.consume(100, 100) is None
    assert reader.calls == 1


def test_hook_timeout_is_authoritative_empty_metadata():
    reader = _FakeReader([])
    duplicator = _FakeDuplicator()
    duplicator.updated = False
    hook = DXGIMetadataHook(reader=reader)
    assert hook.ensure_attached(_FakeCamera(duplicator))
    assert duplicator.update_frame()
    assert hook.consume(100, 100) == DXGIFrameMetadata((), ())
    assert reader.calls == 0


def test_failed_metadata_read_requests_software_fallback():
    reader = _FakeReader([None])
    duplicator = _FakeDuplicator()
    hook = DXGIMetadataHook(reader=reader)
    assert hook.ensure_attached(_FakeCamera(duplicator))
    duplicator.update_frame()
    assert hook.consume(100, 100) is None


def test_hook_clips_metadata_to_framebuffer():
    reader = _FakeReader([
        DXGIFrameMetadata(
            dirty_regions=((-10, -5, 30, 20), (200, 200, 10, 10)),
            move_rects=(CaptureMoveRect(5, 5, -2, -3, 10, 10),),
        )
    ])
    duplicator = _FakeDuplicator()
    hook = DXGIMetadataHook(reader=reader)
    assert hook.ensure_attached(_FakeCamera(duplicator))
    duplicator.update_frame()

    metadata = hook.consume(100, 100)
    assert metadata is not None
    assert metadata.dirty_regions == ((0, 0, 20, 15),)
    assert metadata.move_rects == (
        CaptureMoveRect(src_x=7, src_y=8, dst_x=0, dst_y=0, width=8, height=7),
    )


def test_invalid_move_source_invalidates_native_metadata():
    reader = _FakeReader([
        DXGIFrameMetadata(
            dirty_regions=(),
            move_rects=(CaptureMoveRect(-5, 0, 20, 20, 10, 10),),
        )
    ])
    duplicator = _FakeDuplicator()
    hook = DXGIMetadataHook(reader=reader)
    assert hook.ensure_attached(_FakeCamera(duplicator))
    duplicator.update_frame()
    assert hook.consume(100, 100) is None


def test_raw_vtable_metadata_buffer_reader():
    item = dxgi_metadata._Rect(1, 2, 11, 22)
    payload = bytes(item)
    callback_type = dxgi_metadata._WINFUNCTYPE(
        dxgi_metadata._HRESULT,
        ctypes.c_void_p,
        dxgi_metadata._UINT,
        ctypes.c_void_p,
        ctypes.POINTER(dxgi_metadata._UINT),
    )

    def callback(_this, buffer_size, buffer, required):
        required[0] = len(payload)
        if int(buffer_size) < len(payload) or not buffer:
            return -1
        ctypes.memmove(buffer, payload, len(payload))
        return 0

    callback_fn = callback_type(callback)
    vtable = (ctypes.c_void_p * 15)()
    vtable[dxgi_metadata._GET_FRAME_DIRTY_RECTS_INDEX] = ctypes.cast(
        callback_fn, ctypes.c_void_p
    ).value

    class _FakeComObject(ctypes.Structure):
        _fields_ = [("vtable", ctypes.POINTER(ctypes.c_void_p))]

    obj = _FakeComObject(ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p)))
    reader = DXGIMetadataReader()
    raw = reader._read_buffer(
        ctypes.pointer(obj),
        dxgi_metadata._GET_FRAME_DIRTY_RECTS_INDEX,
        ctypes.sizeof(dxgi_metadata._Rect),
    )
    assert raw == payload
    assert reader._decode_dirty(raw) == [(1, 2, 10, 20)]


def test_dxcam_backend_keeps_move_destination_dirty_for_safe_fallback():
    move = CaptureMoveRect(1, 2, 20, 30, 10, 12)

    class FakeMetadataHook:
        is_available = True

        def ensure_attached(self, _camera):
            return True

        def consume(self, _width, _height):
            return DXGIFrameMetadata(((4, 5, 6, 7),), (move,))

    class FakeOwner:
        logger = logging.getLogger("test.dxgi.backend")
        scale_factor = 1.0
        enable_dxgi_metadata = True
        _dxcam_available = True

        def __init__(self):
            self.camera = _FakeCamera(_FakeDuplicator())

        def _get_dxcam_session(self):
            return self.camera

    backend = DXCamCaptureBackend(FakeOwner())
    backend._metadata_hook = FakeMetadataHook()
    metadata = backend.build_metadata(100, 100)

    assert metadata.dirty_regions == [(4, 5, 6, 7), (20, 30, 10, 12)]
    assert metadata.move_rects == [move]
    assert metadata.supports_dirty_regions is True
    assert metadata.supports_move_rects is True


def test_dxcam_healthcheck_does_not_create_camera():
    class FakeOwner:
        logger = logging.getLogger("test.dxgi.healthcheck")
        _dxcam_available = True

        def _get_dxcam_session(self):
            raise AssertionError("healthcheck must not create a DXCamera")

    backend = DXCamCaptureBackend(FakeOwner())

    assert backend.healthcheck() is True


def test_dxcam_capability_probe_does_not_create_camera():
    class ProbeOwner:
        logger = logging.getLogger("test.dxgi.capability-probe")
        scale_factor = 1.0
        enable_dxgi_metadata = True
        _dxcam_available = True

        def _get_dxcam_session(self):
            raise AssertionError("capability probe must not create a DXCamera")

    backend = DXCamCaptureBackend(ProbeOwner())
    metadata = backend.build_metadata(0, 0)

    assert metadata.backend_name == "dxcam+dxgi-metadata"
    assert metadata.supports_dirty_regions is True
    assert metadata.supports_move_rects is True


def test_dxcam_capability_probe_respects_metadata_disable_flag():
    class ProbeOwner:
        logger = logging.getLogger("test.dxgi.capability-probe-disabled")
        scale_factor = 1.0
        enable_dxgi_metadata = False
        _dxcam_available = True

        def _get_dxcam_session(self):
            raise AssertionError("capability probe must not create a DXCamera")

    backend = DXCamCaptureBackend(ProbeOwner())
    metadata = backend.build_metadata(0, 0)

    assert metadata.backend_name == "dxcam"
    assert metadata.supports_dirty_regions is False
    assert metadata.supports_move_rects is False
