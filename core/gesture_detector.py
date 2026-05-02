"""Hand landmark detection using MediaPipe Hands."""
# STATUS: graceful-degradation pattern applied — safe for startup

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    import mediapipe as mp
except ImportError:  # pragma: no cover
    mp = None


LOGGER = logging.getLogger(__name__)


class GestureDetector:
    """Detect and annotate hand landmarks from a BGR image frame."""

    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        self._available = False
        self._hands_module = None
        self._drawing_utils = None
        self.hands = None
        self._min_detection_confidence = min_detection_confidence
        self._min_tracking_confidence = min_tracking_confidence
        self._try_init()

    @property
    def is_available(self) -> bool:
        """Return whether MediaPipe Hands is available and initialized."""
        return self._available

    def _try_init(self) -> None:
        """Try to initialize MediaPipe resources without propagating failures."""
        self._available = False
        _ = mp  # touch import for clarity
        try:
            if mp is None or cv2 is None:
                raise RuntimeError("MediaPipe or OpenCV not importable")
            if not hasattr(mp, "solutions"):
                raise RuntimeError("MediaPipe has no solutions (wrong package version?)")
            # Lightweight: confirms solutions / protobuf stack loads
            _ = mp.solutions.drawing_utils
            self._drawing_utils = mp.solutions.drawing_utils
            self._hands_module = mp.solutions.hands
            self.hands = self._hands_module.Hands(
                static_image_mode=False,
                max_num_hands=2,
                model_complexity=0,
                min_detection_confidence=self._min_detection_confidence,
                min_tracking_confidence=self._min_tracking_confidence,
            )
            self._available = True
            LOGGER.info("Gesture detector initialized successfully")
        except Exception as error:
            self._hands_module = None
            self._drawing_utils = None
            self.hands = None
            self._available = False
            LOGGER.warning("Gesture detector initialization failed: %s", error)

    def detect(
        self, frame: np.ndarray
    ) -> tuple[np.ndarray, Optional[np.ndarray]]:
        """Return annotated frame and flattened landmarks (126-dim: two hands).

        When only one hand is detected the second hand's 63 values are zeros.
        When no hand is detected, landmarks is ``None``.
        """
        if frame is None or not self._available or self.hands is None or cv2 is None:
            return frame, None
        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.hands.process(rgb_frame)
            if not results.multi_hand_landmarks:
                return frame, None

            annotated = frame.copy()

            # Two fixed slots: slot 0 = left hand, slot 1 = right hand.
            # MediaPipe reports handedness relative to the *mirrored* image, so
            # its "Left" label corresponds to the user's right hand appearing on
            # the left side of the video feed.  We map "Left" → slot 0 to stay
            # consistent with the legacy mean-X ordering used during training.
            hand_slots: list[np.ndarray | None] = [None, None]
            for i, hand_landmarks in enumerate(results.multi_hand_landmarks[:2]):
                self._drawing_utils.draw_landmarks(
                    annotated, hand_landmarks, self._hands_module.HAND_CONNECTIONS
                )
                flat = np.array(
                    [
                        coord
                        for lm in hand_landmarks.landmark
                        for coord in (lm.x, lm.y, lm.z)
                    ],
                    dtype=np.float32,
                )
                handedness_label = (
                    results.multi_handedness[i].classification[0].label
                )
                slot = 0 if handedness_label == "Left" else 1
                hand_slots[slot] = flat

            left_hand = hand_slots[0] if hand_slots[0] is not None else np.zeros(63, dtype=np.float32)
            right_hand = hand_slots[1] if hand_slots[1] is not None else np.zeros(63, dtype=np.float32)
            flattened = np.concatenate([left_hand, right_hand])
            return annotated, flattened
        except Exception as error:
            LOGGER.warning("Hand landmark detection failed: %s", error)
            return frame, None
