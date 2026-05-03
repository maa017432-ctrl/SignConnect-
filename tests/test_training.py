"""Tests for temporal training utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

# Bring scripts directory onto sys.path
import sys
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from train_temporal import (
    _augment_sequence_single,
    _canonicalize_sequence,
    _filter_classes,
    _macro_f1,
    _signer_overlap,
    _split_indices,
    _top_k_accuracy,
    canonicalize_sequences,
)


# ── Synthetic dataset factory ─────────────────────────────────────────────────

def _make_dataset(
    n_per_class: int = 12,
    n_classes: int = 3,
    seq_len: int = 10,
    feature_dim: int = 126,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    class_names = [f"sign_{i}" for i in range(n_classes)]
    X_list, label_list, split_list, signer_list = [], [], [], []
    for cls_idx, name in enumerate(class_names):
        for sample_idx in range(n_per_class):
            X_list.append(rng.standard_normal((seq_len, feature_dim)).astype(np.float32))
            label_list.append(name)
            split_list.append("train" if sample_idx < 8 else ("val" if sample_idx < 10 else "test"))
            signer_list.append(cls_idx * 4 + (sample_idx % 4))
    return (
        np.stack(X_list).astype(np.float32),
        np.array(label_list),
        np.array(split_list),
        np.array(signer_list, dtype=np.int32),
    )


# ── _filter_classes tests ────────────────────────────────────────────────────

def test_filter_classes_removes_rare_classes() -> None:
    X, labels, splits, _ = _make_dataset(n_per_class=5, n_classes=4)
    # All classes have 5 samples < 6; _filter_classes exits when nothing is left
    with pytest.raises(SystemExit):
        _filter_classes(X, labels, splits, max_classes=0, min_samples_per_class=6)


def test_filter_classes_max_classes_limit() -> None:
    X, labels, splits, _ = _make_dataset(n_per_class=12, n_classes=5)
    _, y, _, label_map = _filter_classes(X, labels, splits, max_classes=3, min_samples_per_class=5)
    assert len(label_map) <= 3


def test_filter_classes_label_map_contiguous() -> None:
    X, labels, splits, _ = _make_dataset(n_per_class=12, n_classes=4)
    _, y, _, label_map = _filter_classes(X, labels, splits, max_classes=0, min_samples_per_class=10)
    assert set(label_map.keys()) == set(range(len(label_map)))


# ── _split_indices tests ──────────────────────────────────────────────────────

def test_split_indices_official_splits() -> None:
    X, labels, splits, signer_ids = _make_dataset(n_per_class=12, n_classes=3)
    _, y, splits, label_map = _filter_classes(X, labels, splits, max_classes=0, min_samples_per_class=5)
    train_idx, val_idx, test_idx = _split_indices(splits, y, seed=42, split_mode="official")
    all_idx = set(train_idx) | set(val_idx) | set(test_idx)
    assert len(train_idx) > 0
    assert len(val_idx) > 0


def test_split_indices_random_stratified_covers_all_classes() -> None:
    X, labels, splits, signer_ids = _make_dataset(n_per_class=12, n_classes=3)
    # Use all as "unknown" to trigger fallback
    splits_unknown = np.full(len(labels), "unknown")
    _, y, _, label_map = _filter_classes(X, labels, splits, max_classes=0, min_samples_per_class=5)
    train_idx, val_idx, test_idx = _split_indices(splits_unknown[:len(y)], y, seed=42, split_mode="random-stratified")
    assert len(train_idx) > 0
    assert len(val_idx) > 0


def test_split_indices_signer_grouped() -> None:
    X, labels, splits, signer_ids = _make_dataset(n_per_class=16, n_classes=3)
    _, y, _, label_map = _filter_classes(X, labels, splits, max_classes=0, min_samples_per_class=10)
    signer_ids_filtered = signer_ids[: len(y)]
    train_idx, val_idx, test_idx = _split_indices(
        splits[:len(y)], y, seed=42, split_mode="signer-grouped", signer_ids=signer_ids_filtered
    )
    assert len(train_idx) > 0
    assert len(val_idx) > 0


# ── _signer_overlap tests ────────────────────────────────────────────────────

def test_signer_overlap_no_leakage_when_disjoint() -> None:
    signer_ids = np.array([0, 0, 1, 1, 2, 2, 3, 3], dtype=np.int32)
    train_idx = np.array([0, 1])
    val_idx = np.array([2, 3])
    test_idx = np.array([4, 5])
    report = _signer_overlap(signer_ids, train_idx, val_idx, test_idx)
    assert report["train_val_overlap"] == 0
    assert report["train_test_overlap"] == 0


def test_signer_overlap_detects_leakage() -> None:
    # Signer 0 appears in both train and val
    signer_ids = np.array([0, 0, 0, 1, 1, 2], dtype=np.int32)
    train_idx = np.array([0, 1])
    val_idx = np.array([2, 3])
    test_idx = np.array([4, 5])
    report = _signer_overlap(signer_ids, train_idx, val_idx, test_idx)
    assert report["train_val_overlap"] >= 1


# ── Metrics tests ─────────────────────────────────────────────────────────────

def test_top_k_accuracy_perfect() -> None:
    y_true = np.array([0, 1, 2])
    probs = np.eye(3, dtype=np.float32)
    assert _top_k_accuracy(y_true, probs, k=1) == 1.0


def test_top_k_accuracy_empty() -> None:
    assert _top_k_accuracy(np.array([]), np.zeros((0, 3)), k=1) == 0.0


def test_macro_f1_perfect() -> None:
    y_true = np.array([0, 1, 2, 0, 1, 2])
    y_pred = np.array([0, 1, 2, 0, 1, 2])
    assert _macro_f1(y_true, y_pred, num_classes=3) == 1.0


def test_macro_f1_zero() -> None:
    y_true = np.array([0, 0, 0])
    y_pred = np.array([1, 1, 1])
    assert _macro_f1(y_true, y_pred, num_classes=2) == 0.0


# ── canonicalize_sequences tests ─────────────────────────────────────────────

def test_canonicalize_sequences_zero_frames_unchanged() -> None:
    X = np.zeros((2, 5, 126), dtype=np.float32)
    result = canonicalize_sequences(X)
    assert np.allclose(result, 0.0)


def test_canonicalize_sequences_shape_preserved() -> None:
    rng = np.random.default_rng(0)
    X = rng.standard_normal((3, 10, 126)).astype(np.float32)
    result = canonicalize_sequences(X)
    assert result.shape == X.shape


# ── Metrics file output tests ─────────────────────────────────────────────────

def test_write_per_class_metrics_csv(tmp_path) -> None:
    """_write_per_class_metrics should produce a readable CSV with correct columns."""
    from train_temporal import _write_per_class_metrics

    path = tmp_path / "per_class.csv"
    y_true = np.array([0, 1, 2, 0, 1, 2])
    y_pred = np.array([0, 1, 2, 0, 2, 1])
    label_map = {0: "hello", 1: "world", 2: "book"}
    _write_per_class_metrics(path, y_true, y_pred, label_map)

    content = path.read_text(encoding="utf-8")
    lines = content.strip().splitlines()
    assert lines[0].startswith("class,label,precision,recall,f1,support")
    assert len(lines) == 4  # header + 3 classes


def test_write_per_class_metrics_support_counts(tmp_path) -> None:
    from train_temporal import _write_per_class_metrics

    path = tmp_path / "per_class.csv"
    y_true = np.array([0, 0, 1])
    y_pred = np.array([0, 0, 1])
    label_map = {0: "a", 1: "b"}
    _write_per_class_metrics(path, y_true, y_pred, label_map)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    row_a = lines[1].split(",")
    row_b = lines[2].split(",")
    assert int(row_a[-1]) == 2  # support for class 0
    assert int(row_b[-1]) == 1  # support for class 1


# ── Sequence length validation ────────────────────────────────────────────────

def test_dataset_sequence_length_mismatch_exits(tmp_path) -> None:
    """Training should exit early if dataset feature dim does not match contract."""
    from model_contract import FRAME_FEATURE_DIM
    import subprocess

    wrong_dim = FRAME_FEATURE_DIM + 1
    npz_path = tmp_path / "bad.npz"
    X = np.zeros((5, 30, wrong_dim), dtype=np.float32)
    np.savez_compressed(
        npz_path,
        X=X,
        labels=np.array(["a"] * 5),
        splits=np.array(["train"] * 5),
        signer_ids=np.array([1] * 5, dtype=np.int32),
        sequence_length=np.array([30], dtype=np.int32),
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "train_temporal.py"), "--data", str(npz_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "ERROR" in result.stdout or "ERROR" in result.stderr


# ── _canonicalize_sequence tests ──────────────────────────────────────────────

def test_canonicalize_sequence_shape_preserved() -> None:
    rng = np.random.default_rng(0)
    seq = rng.standard_normal((10, 126)).astype(np.float32)
    result = _canonicalize_sequence(seq)
    assert result.shape == seq.shape


def test_canonicalize_sequence_zero_frame_unchanged() -> None:
    seq = np.zeros((5, 126), dtype=np.float32)
    result = _canonicalize_sequence(seq)
    assert np.allclose(result, 0.0)


# ── _augment_sequence_single tests ───────────────────────────────────────────

def test_augment_sequence_single_shape_preserved() -> None:
    """Output shape must equal input shape (T, F)."""
    rng = np.random.default_rng(7)
    seq = rng.standard_normal((30, 126)).astype(np.float32)
    out = _augment_sequence_single(seq, rng)
    assert out.shape == seq.shape


def test_augment_sequence_single_dtype_float32() -> None:
    """Output must be float32 regardless of input dtype."""
    rng = np.random.default_rng(7)
    seq = np.ones((30, 126), dtype=np.float64)
    out = _augment_sequence_single(seq, rng)
    assert out.dtype == np.float32


def test_augment_sequence_single_zero_frames_remain_near_zero() -> None:
    """Frames that were all-zero (no hand detected) receive only tiny jitter."""
    rng = np.random.default_rng(7)
    seq = np.zeros((30, 126), dtype=np.float32)
    out = _augment_sequence_single(seq, rng)
    # Spatial jitter is skipped for zero frames; only temporal interpolation
    # can introduce small values from neighbouring zero frames → still ~zero.
    assert np.abs(out).max() < 1e-5


def test_augment_sequence_single_modifies_active_frames() -> None:
    """Active (non-zero) frames must be numerically changed by augmentation."""
    rng = np.random.default_rng(99)
    seq = rng.standard_normal((30, 126)).astype(np.float32)
    out = _augment_sequence_single(seq, np.random.default_rng(99))
    # At least some values must differ due to jitter / scaling / temporal shift.
    assert not np.allclose(seq, out)


def test_augment_sequence_single_no_horizontal_flip() -> None:
    """X-coordinates (indices 0, 3, 6 … mod 3 == 0) must never be negated."""
    rng = np.random.default_rng(5)
    T, F = 30, 126
    # Build a sequence with all-positive values so a flip would invert the sign.
    seq = np.abs(rng.standard_normal((T, F))).astype(np.float32) + 0.5
    # Run augmentation many times and confirm X-coords stay positive on average.
    x_coord_indices = list(range(0, F, 3))  # every 3rd feature is an X coord
    for trial_seed in range(20):
        out = _augment_sequence_single(seq, np.random.default_rng(trial_seed))
        # Sum of X coords across all frames must remain positive (no sign flip).
        assert out[:, x_coord_indices].sum() > 0, (
            f"Horizontal flip detected at seed {trial_seed}"
        )

