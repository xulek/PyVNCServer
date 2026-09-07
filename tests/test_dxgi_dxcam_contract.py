"""Contract tests for the optional DXCam integration used by v3.3.

These tests do not create a Desktop Duplication session, so they can run on a
headless GitHub-hosted Windows runner. Their purpose is to detect an upstream
DXCam private-API change before it silently disables native metadata capture.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.skipif(os.name != "nt", reason="DXCam contract is Windows-only")
def test_dxcam_private_metadata_contract():
    pytest.importorskip("dxcam")

    from dxcam.core.dxgi_duplicator import DXGIDuplicator
    from dxcam.dxcam import DXCamera
    from dxcam._libs.dxgi import IDXGIOutputDuplication

    assert hasattr(DXGIDuplicator, "update_frame")

    # DXCamera stores the active duplicator on this private attribute. The v3.3
    # hook intentionally checks it dynamically and falls back to software diff
    # if it disappears, but CI should still make such an upstream change loud.
    annotations = getattr(DXCamera, "__annotations__", {})
    assert "_duplicator" in annotations or "_duplicator" in vars(DXCamera)

    method_names = {
        getattr(method, "name", None)
        for method in getattr(IDXGIOutputDuplication, "_methods_", ())
    }
    assert "GetFrameDirtyRects" in method_names
    assert "GetFrameMoveRects" in method_names
