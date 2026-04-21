"""Tests for model prediction thresholds."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
from core.ai_model import GestureClassifier


@pytest.fixture(autouse=True)
def reset_gesture_classifier_singleton() -> None:
    """Each test gets a fresh ``GestureClassifier`` (singleton reset)."""
    GestureClassifier._instance = None
    yield
    GestureClassifier._instance = None


def test_predict_with_dummy_input() -> None:
    """Prediction should return tuple with label index and confidence."""
    classifier = GestureClassifier(
        model_path="missing-model.h5",
        confidence_threshold=0.75,
        labels_count=31,
    )
    label, confidence = classifier.predict(np.random.rand(63).astype(np.float32))
    assert isinstance(label, int)
    assert isinstance(confidence, float)


def test_confidence_threshold_rejection() -> None:
    """Demo mode returns synthetic scores in [0.76, 0.95] (threshold not applied)."""
    classifier = GestureClassifier(
        model_path="missing-model.h5",
        confidence_threshold=0.95,
        labels_count=31,
    )
    label, confidence = classifier.predict(np.random.rand(63).astype(np.float32))
    assert classifier.is_demo_mode
    assert 0.76 <= confidence <= 0.95
    assert label >= 0
