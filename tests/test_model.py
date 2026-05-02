"""Tests for model prediction thresholds."""

from __future__ import annotations

from threading import Thread
from unittest.mock import patch

import pytest

np = pytest.importorskip("numpy")
from core.ai_model import GestureClassifier


@pytest.fixture(autouse=True)
def reset_gesture_classifier_singleton() -> None:
    """Each test gets a fresh ``GestureClassifier`` (singleton reset)."""
    GestureClassifier.reset_instance()
    yield
    GestureClassifier.reset_instance()


class _FakeModel:
    def __init__(self, input_shape=(None, 126), output_shape=(None, 31)) -> None:
        self.input_shape = input_shape
        self.output_shape = output_shape


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


def test_singleton_reuse_warns_on_config_mismatch(caplog) -> None:
    first = GestureClassifier(
        model_path="missing-model.h5",
        confidence_threshold=0.75,
        labels_count=31,
    )
    second = GestureClassifier(
        model_path="other-model.h5",
        confidence_threshold=0.5,
        labels_count=12,
    )

    assert first is second
    assert "singleton already initialized" in caplog.text


def test_loaded_model_contract_match_is_available(tmp_path) -> None:
    model_path = tmp_path / "model.h5"
    model_path.write_text("placeholder", encoding="utf-8")

    with patch("core.ai_model.load_model", return_value=_FakeModel()):
        classifier = GestureClassifier(
            model_path=str(model_path),
            confidence_threshold=0.75,
            labels_count=31,
        )

    assert classifier.is_available
    assert not classifier.is_demo_mode


def test_loaded_model_output_mismatch_falls_back_to_demo(tmp_path) -> None:
    model_path = tmp_path / "model.h5"
    model_path.write_text("placeholder", encoding="utf-8")

    with patch("core.ai_model.load_model", return_value=_FakeModel(output_shape=(None, 30))):
        classifier = GestureClassifier(
            model_path=str(model_path),
            confidence_threshold=0.75,
            labels_count=31,
        )

    assert not classifier.is_available
    assert classifier.is_demo_mode


def test_loaded_model_input_mismatch_falls_back_to_demo(tmp_path) -> None:
    model_path = tmp_path / "model.h5"
    model_path.write_text("placeholder", encoding="utf-8")

    with patch("core.ai_model.load_model", return_value=_FakeModel(input_shape=(None, 64))):
        classifier = GestureClassifier(
            model_path=str(model_path),
            confidence_threshold=0.75,
            labels_count=31,
        )

    assert not classifier.is_available
    assert classifier.is_demo_mode


# ── Temporal-specific tests ──────────────────────────────────────────────────

def test_temporal_sequence_buffer_starts_empty() -> None:
    """Sequence buffer should be empty right after construction."""
    from model_contract import TEMPORAL_MODEL_TYPE

    classifier = GestureClassifier(
        model_path="missing-model.h5",
        confidence_threshold=0.75,
        labels_count=31,
        model_type=TEMPORAL_MODEL_TYPE,
        sequence_length=10,
    )
    assert len(classifier._sequence_buffer) == 0


def test_temporal_zero_padding_matches_masking_layer() -> None:
    """When fewer than sequence_length frames are buffered, left-pad with zeros."""
    from model_contract import TEMPORAL_MODEL_TYPE, FRAME_FEATURE_DIM

    sequence_length = 5
    classifier = GestureClassifier(
        model_path="missing-model.h5",
        confidence_threshold=0.75,
        labels_count=31,
        model_type=TEMPORAL_MODEL_TYPE,
        sequence_length=sequence_length,
    )
    # Build a frame where different landmarks have different values so
    # canonicalization produces a non-zero result (all-same values collapse to zero).
    rng = np.random.default_rng(42)
    frame = rng.uniform(0.1, 0.9, FRAME_FEATURE_DIM).astype(np.float32)
    # Ensure at least some variety between landmark positions so scale > 1e-6
    frame[0:3] = [0.1, 0.2, 0.0]   # wrist
    frame[27:30] = [0.5, 0.7, 0.1]  # middle finger landmark (index 9 of first hand)
    # Add one real frame, then build the padded tensor
    tensor = classifier._prepare_temporal_features(frame)
    assert tensor.shape == (1, sequence_length, FRAME_FEATURE_DIM)
    # First (sequence_length - 1) frames should be all-zeros (the mask value)
    assert np.all(tensor[0, : sequence_length - 1] == 0.0)
    # Last frame should be the (canonicalized) actual frame — not trivially all-zero
    assert not np.all(tensor[0, -1] == 0.0)


def test_reset_sequence_clears_buffer() -> None:
    """reset_sequence() should clear all buffered temporal frames."""
    from model_contract import TEMPORAL_MODEL_TYPE, FRAME_FEATURE_DIM

    classifier = GestureClassifier(
        model_path="missing-model.h5",
        confidence_threshold=0.75,
        labels_count=31,
        model_type=TEMPORAL_MODEL_TYPE,
        sequence_length=10,
    )
    frame = np.random.rand(FRAME_FEATURE_DIM).astype(np.float32)
    classifier._prepare_temporal_features(frame)
    assert len(classifier._sequence_buffer) == 1

    classifier.reset_sequence()
    assert len(classifier._sequence_buffer) == 0


def test_reload_clears_sequence_buffer(tmp_path) -> None:
    """reload() must clear the temporal sequence buffer."""
    from model_contract import TEMPORAL_MODEL_TYPE, FRAME_FEATURE_DIM

    model_path = tmp_path / "model.h5"
    model_path.write_text("placeholder", encoding="utf-8")

    with patch("core.ai_model.load_model", return_value=_FakeModel()):
        classifier = GestureClassifier(
            model_path=str(model_path),
            confidence_threshold=0.75,
            labels_count=31,
            model_type=TEMPORAL_MODEL_TYPE,
            sequence_length=10,
        )

    frame = np.random.rand(FRAME_FEATURE_DIM).astype(np.float32)
    classifier._sequence_buffer.append(frame)
    assert len(classifier._sequence_buffer) == 1

    with patch("core.ai_model.load_model", return_value=_FakeModel()):
        classifier.reload()

    assert len(classifier._sequence_buffer) == 0


def test_predict_with_details_acquires_lock() -> None:
    """predict_with_details must work correctly under concurrent access."""
    from model_contract import FRAME_FEATURE_DIM

    classifier = GestureClassifier(
        model_path="missing-model.h5",
        confidence_threshold=0.75,
        labels_count=31,
    )
    results: list[dict] = []
    errors: list[Exception] = []

    def _predict() -> None:
        try:
            frame = np.random.rand(FRAME_FEATURE_DIM).astype(np.float32)
            result = classifier.predict_with_details(frame)
            results.append(result)
        except Exception as exc:
            errors.append(exc)

    threads = [Thread(target=_predict) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent predictions raised: {errors}"
    assert len(results) == 8
    for result in results:
        assert "label_index" in result
        assert "confidence" in result

