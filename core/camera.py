"""Camera lifecycle management for SignConnect."""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any, Optional

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - depends on runtime environment
    cv2 = None


LOGGER = logging.getLogger(__name__)


class CameraUnavailableError(RuntimeError):
    """Raised when the camera device cannot be initialized."""


class CameraManager:
    """Thread-safe camera manager with non-blocking frame capture loop."""

    _INDICES = (0, 1, 2)
    _WARMUP_READS = 3
    _MAX_CONSECUTIVE_FAILURES = 10  # ~0.5 s of read failures → declare device dead

    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self._capture: Optional[Any] = None
        self._active_camera_index: Optional[int] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._hw_probe_time: float = 0.0
        self._hw_probe_cache: Optional[bool] = None
        self._hw_probe_ttl_seconds: float = 30.0

    @property
    def _camera_index(self) -> Optional[int]:
        """Camera device index that succeeded during open (task-named property)."""
        return self._active_camera_index

    def _try_open_camera(self) -> tuple[Optional[Any], Optional[int]]:
        """Try indices 0, 1, 2 and return ``(capture, index)`` on first success.

        The capture object is configured for 640x480 @ 30 FPS and warmed up
        with several discarded reads.  Returns ``(None, None)`` if no camera
        index produces a valid frame.
        """
        if cv2 is None:
            return None, None
        for index in self._INDICES:
            # On Windows, DirectShow is often more reliable than the default MSMF backend
            if sys.platform == "win32":
                cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(index)

            if not cap.isOpened():
                cap.release()
                # If DSHOW fails on Windows, try default backend as fallback
                if sys.platform == "win32":
                    cap = cv2.VideoCapture(index)
                    if not cap.isOpened():
                        cap.release()
                        continue
                else:
                    continue

            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 30)
                for _ in range(self._WARMUP_READS):
                    cap.read()
                ok, frame = cap.read()
                if ok and frame is not None and frame.size > 0:
                    LOGGER.info("Camera opened on index %s", index)
                    return cap, index
            except Exception as error:
                LOGGER.warning("Camera probe failed on index %s: %s", index, error)
            cap.release()
        return None, None

    def _try_init(self) -> bool:
        """Open the first usable camera and store it on the instance.

        Returns:
            True if a capture is stored on ``self._capture`` and index set.
        """
        cap, index = self._try_open_camera()
        if cap is not None:
            self._capture = cap
            self._active_camera_index = index
            return True
        self._capture = None
        self._active_camera_index = None
        return False

    def start(self) -> None:
        """Start camera capture in a daemon thread."""
        if cv2 is None:
            raise CameraUnavailableError("OpenCV is not installed")
        with self._lock:
            if self._running:
                return
            self._running = True

        if not self._try_init():
            with self._lock:
                self._running = False
            LOGGER.error("Camera not found or busy")
            raise CameraUnavailableError("Camera not found or busy")

        LOGGER.info("Camera capture started")
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self) -> None:
        """Continuously read frames; self-terminates and releases the hardware
        lock if the device is disconnected or fails consecutively."""
        consecutive_failures = 0
        try:
            while self._running:
                if self._capture is None:
                    break
                try:
                    ok, frame = self._capture.read()
                except Exception as exc:
                    LOGGER.error("cv2.read() raised unexpectedly: %s", exc)
                    ok, frame = False, None

                if ok and frame is not None:
                    consecutive_failures = 0
                    with self._lock:
                        self._latest_frame = frame.copy()
                else:
                    consecutive_failures += 1
                    LOGGER.warning(
                        "Frame read failed (%d/%d)",
                        consecutive_failures,
                        self._MAX_CONSECUTIVE_FAILURES,
                    )
                    if consecutive_failures >= self._MAX_CONSECUTIVE_FAILURES:
                        LOGGER.error(
                            "Camera declared dead after %d consecutive read failures "
                            "(device likely disconnected) — stopping capture thread.",
                            consecutive_failures,
                        )
                        break
                    time.sleep(0.05)
        finally:
            # Guaranteed to run on every exit path, including unhandled exceptions.
            # When the thread self-terminates here (hardware failure), this is the
            # sole owner of release(); stop() detects _capture is None and skips it.
            with self._lock:
                self._running = False
                if self._capture is not None:
                    try:
                        self._capture.release()
                    except Exception:
                        LOGGER.exception("cv2.VideoCapture.release() failed during cleanup")
                    self._capture = None
                self._latest_frame = None
                self._active_camera_index = None
            LOGGER.info("Capture thread exited and hardware lock released.")

    def stop(self) -> None:
        """Stop capture thread and release camera resource safely."""
        with self._lock:
            self._running = False
            if self._capture is not None:
                self._capture.release()
                self._capture = None
            self._latest_frame = None
            self._active_camera_index = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        LOGGER.info("Camera capture stopped")

    def get_frame(self) -> Optional[np.ndarray]:
        """Return a copy of the latest frame if available."""
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def _probe_hardware_available(self) -> bool:
        """Return True if some camera index can produce a frame."""
        cap, _ = self._try_open_camera()
        if cap is not None:
            cap.release()
            return True
        return False

    @property
    def is_streaming(self) -> bool:
        """True when capture thread is active and a device is open."""
        with self._lock:
            return self._running and self._capture is not None

    def is_available(self) -> bool:
        """True if capture is running, or a quick probe shows hardware is usable."""
        with self._lock:
            if self._running and self._capture is not None:
                return True
        now = time.time()
        if (
            self._hw_probe_cache is not None
            and (now - self._hw_probe_time) < self._hw_probe_ttl_seconds
        ):
            return self._hw_probe_cache
        self._hw_probe_cache = self._probe_hardware_available()
        self._hw_probe_time = now
        return self._hw_probe_cache
