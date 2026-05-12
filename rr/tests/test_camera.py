"""Tests for camera manager behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("numpy")

from core.camera import CameraManager, CameraUnavailableError, cv2


class _FakeCaptureClosed:
    """Fake camera that cannot be opened."""

    def isOpened(self) -> bool:
        return False

    def release(self) -> None:
        return None


@pytest.mark.skipif(cv2 is None, reason="OpenCV not installed")
@patch("core.camera.cv2.VideoCapture", return_value=_FakeCaptureClosed())
def test_unavailable_camera_raises_error(_: object) -> None:
    """Raise camera unavailable error when capture cannot open."""
    manager = CameraManager()
    with pytest.raises(CameraUnavailableError):
        manager.start()
