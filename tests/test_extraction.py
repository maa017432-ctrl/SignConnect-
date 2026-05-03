"""Tests for WLASL temporal sequence extraction."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

np = pytest.importorskip("numpy")

# Bring the scripts directory onto sys.path
import sys
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from wlasl_to_sequences import (
    Clip,
    _frame_indices,
    _load_checkpoint,
    _write_dataset,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_clip(label: str = "hello", video_id: str = "v001", frame_start: int = 1, frame_end: int = -1, split: str = "train", signer_id: int = 1, video_path: Path | None = None) -> Clip:
    return Clip(
        label=label,
        video_id=video_id,
        video_path=video_path or Path(f"/fake/{video_id}.mp4"),
        frame_start=frame_start,
        frame_end=frame_end,
        split=split,
        signer_id=signer_id,
    )


# ── Clip key tests ────────────────────────────────────────────────────────────

def test_clip_key_is_stable_and_unique() -> None:
    clip_a = _make_clip(label="hello", video_id="v001", frame_start=1, frame_end=50, split="train")
    clip_b = _make_clip(label="hello", video_id="v001", frame_start=51, frame_end=100, split="train")
    clip_c = _make_clip(label="world", video_id="v001", frame_start=1, frame_end=50, split="train")

    assert clip_a.clip_key != clip_b.clip_key, "Different frame ranges must produce different keys"
    assert clip_a.clip_key != clip_c.clip_key, "Different labels must produce different keys"
    assert clip_a.clip_key == clip_a.clip_key, "Clip key must be deterministic"


def test_clip_key_format() -> None:
    clip = _make_clip(label="book", video_id="12345", frame_start=10, frame_end=80, split="val")
    assert clip.clip_key == "book|12345|10|80|val"


# ── Frame indices tests ───────────────────────────────────────────────────────

def test_frame_indices_returns_sequence_length_items() -> None:
    indices = _frame_indices(total_frames=100, start_frame=1, end_frame=-1, sequence_length=30)
    assert len(indices) == 30


def test_frame_indices_are_within_bounds() -> None:
    indices = _frame_indices(total_frames=50, start_frame=10, end_frame=40, sequence_length=15)
    assert all(0 <= idx < 50 for idx in indices)


def test_frame_indices_single_frame() -> None:
    indices = _frame_indices(total_frames=20, start_frame=5, end_frame=5, sequence_length=1)
    assert len(indices) == 1


# ── Checkpoint resume tests ───────────────────────────────────────────────────

def test_checkpoint_roundtrip(tmp_path) -> None:
    """_write_dataset followed by _load_checkpoint must restore all arrays."""
    npz_path = tmp_path / "seqs.npz"
    sequences = [np.zeros((30, 126), dtype=np.float32), np.ones((30, 126), dtype=np.float32)]
    labels = ["hello", "world"]
    splits = ["train", "val"]
    video_ids = ["v001", "v002"]
    clip_keys = ["hello|v001|1|-1|train", "world|v002|1|-1|val"]
    signer_ids = [1, 2]

    _write_dataset(
        output_path=npz_path,
        sequences=sequences,
        labels=labels,
        splits=splits,
        video_ids=video_ids,
        clip_keys=clip_keys,
        signer_ids=signer_ids,
        sequence_length=30,
    )

    loaded_seq, loaded_labels, loaded_splits, loaded_vids, loaded_keys, loaded_signers = _load_checkpoint(npz_path)

    assert len(loaded_seq) == 2
    assert loaded_labels == labels
    assert loaded_splits == splits
    assert loaded_keys == clip_keys
    assert loaded_signers == signer_ids


def test_load_checkpoint_missing_file(tmp_path) -> None:
    """_load_checkpoint on a missing file should return six empty lists."""
    result = _load_checkpoint(tmp_path / "nonexistent.npz")
    assert result == ([], [], [], [], [], [])


def test_load_checkpoint_backward_compat(tmp_path) -> None:
    """Old checkpoints without clip_keys key fall back to video_ids."""
    npz_path = tmp_path / "old.npz"
    np.savez_compressed(
        npz_path,
        X=np.zeros((1, 30, 126), dtype=np.float32),
        labels=np.array(["hello"]),
        splits=np.array(["train"]),
        video_ids=np.array(["v001"]),
        signer_ids=np.array([1], dtype=np.int32),
        sequence_length=np.array([30], dtype=np.int32),
    )
    _, _, _, _, clip_keys, _ = _load_checkpoint(npz_path)
    assert clip_keys == ["v001"]


# ── Deduplication / resume tests ─────────────────────────────────────────────

def test_clip_key_deduplication_prevents_double_extraction(tmp_path) -> None:
    """Clips already in processed_clip_keys must not be re-extracted."""
    npz_path = tmp_path / "seqs.npz"
    clip_key = "hello|v001|1|-1|train"
    # Pre-populate checkpoint with this clip key already processed
    _write_dataset(
        output_path=npz_path,
        sequences=[np.zeros((30, 126), dtype=np.float32)],
        labels=["hello"],
        splits=["train"],
        video_ids=["v001"],
        clip_keys=[clip_key],
        signer_ids=[1],
        sequence_length=30,
    )

    _, _, _, _, loaded_keys, _ = _load_checkpoint(npz_path)
    processed = set(loaded_keys)
    assert clip_key in processed


# ── Skipped-reason tests ──────────────────────────────────────────────────────

def test_extract_clip_unreadable_video(tmp_path) -> None:
    """If VideoCapture cannot open the file, skip reason must be 'unreadable_video'."""
    # Import here to avoid issues if cv2 not installed
    cv2_mod = pytest.importorskip("cv2")
    from wlasl_to_sequences import _extract_clip

    fake_path = tmp_path / "bad.mp4"
    fake_path.write_bytes(b"not a video")
    clip = _make_clip(video_path=fake_path)
    fake_hands = MagicMock()

    sequence, reason = _extract_clip(
        hands=fake_hands,
        clip=clip,
        sequence_length=10,
        min_detected_frames=3,
    )
    assert sequence is None
    assert reason == "unreadable_video"
