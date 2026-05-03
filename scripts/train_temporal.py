"""Train a temporal landmark classifier from WLASL sequence datasets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model_contract import FRAME_FEATURE_DIM, SEQUENCE_LENGTH, TEMPORAL_MODEL_TYPE

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

try:
    import tensorflow as tf
    from tensorflow import keras
except ImportError:
    tf = None  # type: ignore[assignment]
    keras = None  # type: ignore[assignment]


DEFAULT_DATASET = PROJECT_ROOT / "data" / "wlasl_sequences" / "wlasl_sequences.npz"
MODEL_OUT = PROJECT_ROOT / "models" / "gesture_model.h5"
LABEL_MAP_OUT = PROJECT_ROOT / "models" / "label_map.json"
METRICS_OUT = PROJECT_ROOT / "models" / "temporal_metrics.json"
CONFUSION_OUT = PROJECT_ROOT / "models" / "temporal_confusion_matrix.csv"
HISTORY_OUT = PROJECT_ROOT / "models" / "history.json"
TRAINING_CONFIG_OUT = PROJECT_ROOT / "models" / "training_config.json"
PER_CLASS_METRICS_OUT = PROJECT_ROOT / "models" / "per_class_metrics.csv"


def _set_seeds(seed: int) -> None:
    """Set Python, NumPy, and TensorFlow seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)
    os.environ.setdefault("PYTHONHASHSEED", str(seed))


def _canonicalize_hand(hand: np.ndarray) -> np.ndarray:
    points = hand.reshape(21, 3).astype(np.float32)
    points = points - points[0]
    scale = float(np.linalg.norm(points[9]))
    if scale < 1e-6:
        scale = float(np.linalg.norm(points[5] - points[17]))
    if scale < 1e-6:
        scale = 1.0
    return (points / scale).reshape(-1)


def _canonicalize_sequence(seq: np.ndarray) -> np.ndarray:
    """Canonicalize a single (T, F) landmark sequence frame-by-frame.

    Translates each hand's wrist to the origin and normalises by the span of
    metacarpal joints so that the representation is scale- and
    translation-invariant.  Zero frames (no detected hands) are left as-is.
    """
    result = np.zeros_like(seq, dtype=np.float32)
    for frame_idx in range(seq.shape[0]):
        frame = seq[frame_idx].astype(np.float32)
        if np.abs(frame).sum() < 1e-8:
            continue
        hand1 = _canonicalize_hand(frame[:63])
        hand2_raw = frame[63:126]
        hand2 = _canonicalize_hand(hand2_raw) if np.abs(hand2_raw).sum() > 1e-8 else hand2_raw
        result[frame_idx] = np.concatenate([hand1, hand2])
    return result


def canonicalize_sequences(X: np.ndarray) -> np.ndarray:
    """Canonicalize an (N, T, F) batch of landmark sequences."""
    return np.stack([_canonicalize_sequence(X[i]) for i in range(X.shape[0])], axis=0)


def build_model(
    num_classes: int,
    sequence_length: int,
    dropout_rate: float,
    arch: str = "bigru",
) -> keras.Model:
    reg = keras.regularizers.l2(1e-4)
    inputs = keras.layers.Input(shape=(sequence_length, FRAME_FEATURE_DIM), name="landmark_sequence")
    x = keras.layers.Masking(mask_value=0.0, name="mask_empty_frames")(inputs)

    if arch == "bigru_attention":
        x = keras.layers.Bidirectional(
            keras.layers.GRU(128, return_sequences=True, kernel_regularizer=reg),
            name="bigru_1",
        )(x)
        x = keras.layers.Dropout(dropout_rate, name="drop_1")(x)
        x = keras.layers.Bidirectional(
            keras.layers.GRU(64, return_sequences=True, kernel_regularizer=reg),
            name="bigru_2",
        )(x)
        x = keras.layers.Dropout(dropout_rate, name="drop_2")(x)
        # Additive (Bahdanau-style) attention pooling over the time axis
        score = keras.layers.Dense(1, name="attn_score")(x)
        weights = keras.layers.Softmax(axis=1, name="attn_weights")(score)
        x = keras.layers.Lambda(
            lambda tensors: tf.reduce_sum(tensors[0] * tensors[1], axis=1),
            name="attn_context",
        )([x, weights])
    else:
        # Default: bigru
        x = keras.layers.Bidirectional(
            keras.layers.GRU(128, return_sequences=True, kernel_regularizer=reg),
            name="bigru_1",
        )(x)
        x = keras.layers.Dropout(dropout_rate, name="drop_1")(x)
        x = keras.layers.Bidirectional(
            keras.layers.GRU(64, kernel_regularizer=reg),
            name="bigru_2",
        )(x)
        x = keras.layers.Dropout(dropout_rate, name="drop_2")(x)

    x = keras.layers.Dense(128, activation="relu", kernel_regularizer=reg, name="hidden_1")(x)
    x = keras.layers.Dropout(max(0.1, dropout_rate / 2), name="drop_3")(x)
    outputs = keras.layers.Dense(num_classes, activation="softmax", name="output")(x)
    return keras.Model(inputs, outputs, name=f"signconnect_{arch}_temporal_classifier")


def _filter_classes(
    X: np.ndarray,
    labels: np.ndarray,
    splits: np.ndarray,
    max_classes: int,
    min_samples_per_class: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[int, str]]:
    counts: dict[str, int] = {}
    for label in labels:
        label_text = str(label)
        counts[label_text] = counts.get(label_text, 0) + 1

    eligible = [
        (label, count)
        for label, count in counts.items()
        if count >= min_samples_per_class
    ]
    eligible.sort(key=lambda item: (-item[1], item[0]))
    if max_classes > 0:
        eligible = eligible[:max_classes]
    keep_labels = {label for label, _ in eligible}
    if not keep_labels:
        sys.exit("ERROR: No labels left after class filtering.")

    mask = np.asarray([str(label) in keep_labels for label in labels], dtype=bool)
    X = X[mask]
    labels = labels[mask]
    splits = splits[mask]

    ordered_labels = sorted(str(label) for label in keep_labels)
    label_to_idx = {label: idx for idx, label in enumerate(ordered_labels)}
    y = np.asarray([label_to_idx[str(label)] for label in labels], dtype=np.int32)
    label_map = {idx: label for label, idx in label_to_idx.items()}
    return X, y, splits, label_map


def _split_indices(
    splits: np.ndarray,
    y: np.ndarray,
    seed: int,
    split_mode: str = "official",
    signer_ids: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if split_mode == "official":
        train_idx = np.where(splits == "train")[0]
        val_idx = np.where(splits == "val")[0]
        test_idx = np.where(splits == "test")[0]
        if len(train_idx) and len(val_idx):
            return train_idx, val_idx, test_idx

    rng = np.random.default_rng(seed)

    if split_mode == "signer-grouped" and signer_ids is not None and len(signer_ids):
        unique_signers = np.asarray(sorted(set(int(s) for s in signer_ids if s >= 0)))
        rng.shuffle(unique_signers)
        n = len(unique_signers)
        n_test = max(1, int(round(n * 0.15)))
        n_val = max(1, int(round(n * 0.15)))
        test_signers = set(int(s) for s in unique_signers[:n_test])
        val_signers = set(int(s) for s in unique_signers[n_test : n_test + n_val])
        train_idx = np.where(
            np.asarray([int(s) not in test_signers and int(s) not in val_signers for s in signer_ids])
        )[0]
        val_idx = np.where(np.asarray([int(s) in val_signers for s in signer_ids]))[0]
        test_idx = np.where(np.asarray([int(s) in test_signers for s in signer_ids]))[0]
        if len(train_idx) and len(val_idx):
            return train_idx, val_idx, test_idx

    # Fallback: random-stratified by class
    train: list[int] = []
    val: list[int] = []
    test: list[int] = []
    for cls in sorted(set(int(value) for value in y)):
        indices = np.where(y == cls)[0]
        rng.shuffle(indices)
        n = len(indices)
        n_test = max(1, int(round(n * 0.15))) if n >= 8 else 0
        n_val = max(1, int(round(n * 0.15))) if n >= 8 else 0
        test.extend(indices[:n_test].tolist())
        val.extend(indices[n_test : n_test + n_val].tolist())
        train.extend(indices[n_test + n_val :].tolist())
    return (
        np.asarray(train, dtype=np.int32),
        np.asarray(val, dtype=np.int32),
        np.asarray(test, dtype=np.int32),
    )


def _top_k_accuracy(y_true: np.ndarray, probabilities: np.ndarray, k: int) -> float:
    if len(y_true) == 0:
        return 0.0
    top_k = np.argsort(probabilities, axis=1)[:, -k:]
    return float(np.mean([truth in row for truth, row in zip(y_true, top_k)]))


def _macro_f1(y_true: np.ndarray, y_pred: np.ndarray, num_classes: int) -> float:
    scores: list[float] = []
    for cls in range(num_classes):
        tp = int(((y_pred == cls) & (y_true == cls)).sum())
        fp = int(((y_pred == cls) & (y_true != cls)).sum())
        fn = int(((y_pred != cls) & (y_true == cls)).sum())
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        if precision + recall == 0:
            scores.append(0.0)
        else:
            scores.append(2 * precision * recall / (precision + recall))
    return float(np.mean(scores)) if scores else 0.0


def _augment_sequence_single(seq: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Apply spatial and temporal augmentations to a single (T, F) landmark sequence.

    All operations are purely mathematical transforms on 3D landmark coordinates.
    NO horizontal (X-axis) mirroring is applied — left/right hand dominance is
    semantically significant in ASL and must be preserved.

    Applied augmentations:
        - **Spatial Jitter**   : Zero-mean Gaussian noise (std=0.01) on active frames.
        - **Spatial Scaling**  : Uniform scale factor sampled from U(0.85, 1.15).
        - **Temporal Scaling** : Time-axis stretch/compress via linear interpolation
                                 followed by re-sampling back to the original T frames.

    Args:
        seq: Input landmark array of shape (T, F).
        rng: NumPy random Generator for reproducible stochastic operations.

    Returns:
        Augmented copy of *seq* with the same shape (T, F).
    """
    result = seq.astype(np.float32).copy()
    T, _ = result.shape

    # Boolean mask for frames that contain actual detections — shape (T,).
    active: np.ndarray = np.abs(result).sum(axis=-1) > 1e-8

    # ── Spatial Jitter ────────────────────────────────────────────────────────
    # Additive zero-mean Gaussian noise (std=0.01) applied only to non-zero
    # frames.  This simulates small detector uncertainty in landmark positions.
    noise = rng.standard_normal(result.shape).astype(np.float32) * 0.01
    result[active] += noise[active]

    # ── Spatial Scaling ───────────────────────────────────────────────────────
    # Multiply every landmark coordinate by a single per-sample scale factor.
    # This simulates variation in signer distance from the camera.
    scale_factor = float(rng.uniform(0.85, 1.15))
    result[active] *= scale_factor

    # ── Temporal Scaling ─────────────────────────────────────────────────────
    # Stretch or compress the sequence along the time axis using linear
    # interpolation to a new_len, then resample uniformly back to T frames.
    # This simulates signers performing the same gesture at different speeds.
    stretch = float(rng.uniform(0.8, 1.2))
    new_len = max(2, int(round(T * stretch)))

    # Compute source positions (floating point) in the original T-frame array.
    src_pos = np.linspace(0, T - 1, new_len)
    src_floor = np.floor(src_pos).astype(int)
    src_ceil = np.minimum(src_floor + 1, T - 1)
    frac = (src_pos - src_floor).reshape(-1, 1).astype(np.float32)

    # Linear interpolation between adjacent frames.
    resampled = (1.0 - frac) * result[src_floor] + frac * result[src_ceil]  # (new_len, F)

    # Resample the stretched sequence back to T frames.
    out_pos = np.round(np.linspace(0, new_len - 1, T)).astype(int)
    result = resampled[out_pos]  # (T, F)

    return result.astype(np.float32)


def _signer_overlap(
    signer_ids: np.ndarray,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    test_idx: np.ndarray,
) -> dict[str, object]:
    """Return a report of signer ID overlap across dataset splits."""
    train_signers = set(int(s) for s in signer_ids[train_idx] if int(s) >= 0)
    val_signers = set(int(s) for s in signer_ids[val_idx] if int(s) >= 0)
    test_signers = set(int(s) for s in signer_ids[test_idx] if int(s) >= 0)
    return {
        "train_unique_signers": len(train_signers),
        "val_unique_signers": len(val_signers),
        "test_unique_signers": len(test_signers),
        "train_val_overlap": len(train_signers & val_signers),
        "train_test_overlap": len(train_signers & test_signers),
        "val_test_overlap": len(val_signers & test_signers),
    }


def _write_per_class_metrics(
    path: Path,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    label_map: dict[int, str],
) -> None:
    """Write per-class precision, recall, F1, and support to *path* as CSV."""
    num_classes = len(label_map)
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["class", "label", "precision", "recall", "f1", "support"])
        for cls in range(num_classes):
            tp = int(((y_pred == cls) & (y_true == cls)).sum())
            fp = int(((y_pred == cls) & (y_true != cls)).sum())
            fn = int(((y_pred != cls) & (y_true == cls)).sum())
            precision = tp / max(1, tp + fp)
            recall = tp / max(1, tp + fn)
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0.0
            )
            support = int((y_true == cls).sum())
            writer.writerow([cls, label_map[cls], f"{precision:.4f}", f"{recall:.4f}", f"{f1:.4f}", support])


def _file_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of *path*."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_confusion(path: Path, y_true: np.ndarray, y_pred: np.ndarray, label_map: dict[int, str]) -> None:
    num_classes = len(label_map)
    matrix = np.zeros((num_classes, num_classes), dtype=np.int32)
    for truth, pred in zip(y_true, y_pred):
        matrix[int(truth), int(pred)] += 1
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.writer(file_obj)
        labels = [label_map[idx] for idx in range(num_classes)]
        writer.writerow(["true\\pred"] + labels)
        for idx, label in enumerate(labels):
            writer.writerow([label] + matrix[idx].tolist())


# Provide a safe base class for LandmarkDataGenerator when TensorFlow is absent
# (keeps the module importable for unit tests that don't need the full stack).
_KerasSequenceBase = keras.utils.Sequence if keras is not None else object  # type: ignore[union-attr]


class LandmarkDataGenerator(_KerasSequenceBase):  # type: ignore[misc,valid-type]
    """Memory-efficient Keras Sequence generator for landmark sequence training.

    Reads individual samples from a pre-canonicalized in-memory array on demand,
    applies per-sample normalisation and optional landmark augmentation inside
    each batch call.  This avoids materialising an augmented copy of the entire
    training set in RAM — critical for resource-constrained runtimes such as
    Google Colab T4 with ~12 GB of system RAM.

    Args:
        X_canonical: Canonicalized landmark array of shape (N, T, F).
        y:           Integer label array of shape (N,).
        indices:     Row indices into *X_canonical* / *y* for this data split.
        mean:        Per-feature normalisation mean, shape (F,).
        std:         Per-feature normalisation std (never zero), shape (F,).
        batch_size:  Number of samples per batch.
        augment:     When True, apply :func:`_augment_sequence_single` per sample.
        seed:        Integer RNG seed for shuffling and augmentation.
        shuffle:     Reshuffle *indices* at the start of every epoch when True.
    """

    def __init__(
        self,
        X_canonical: np.ndarray,
        y: np.ndarray,
        indices: np.ndarray,
        mean: np.ndarray,
        std: np.ndarray,
        batch_size: int,
        augment: bool = False,
        seed: int = 42,
        shuffle: bool = True,
    ) -> None:
        self._X = X_canonical
        self._y = y
        self._indices = indices.copy()
        # Pre-reshape for efficient broadcast in __getitem__.
        self._mean = mean.reshape(1, -1).astype(np.float32)
        self._std = std.reshape(1, -1).astype(np.float32)
        self._batch_size = batch_size
        self._augment = augment
        self._rng = np.random.default_rng(seed)
        self._shuffle = shuffle
        if shuffle:
            self._rng.shuffle(self._indices)

    # ── Keras Sequence protocol ───────────────────────────────────────────────

    def __len__(self) -> int:
        """Number of batches per epoch (ceiling division)."""
        return math.ceil(len(self._indices) / self._batch_size)

    def on_epoch_end(self) -> None:
        """Reshuffle the sample order at the end of every training epoch."""
        if self._shuffle:
            self._rng.shuffle(self._indices)

    def __getitem__(self, batch_idx: int) -> tuple[np.ndarray, np.ndarray]:
        """Return normalised (and optionally augmented) (X_batch, y_batch).

        Args:
            batch_idx: Zero-based batch index within the current epoch.

        Returns:
            Tuple of ``(X_batch, y_batch)`` with shapes
            ``(batch_size, T, F)`` and ``(batch_size,)`` respectively.
        """
        start = batch_idx * self._batch_size
        batch_indices = self._indices[start : start + self._batch_size]
        T, F = self._X.shape[1], self._X.shape[2]
        X_batch = np.empty((len(batch_indices), T, F), dtype=np.float32)

        for local_i, global_i in enumerate(batch_indices):
            # Normalise the pre-canonicalized sequence (broadcast over T axis).
            seq = (self._X[global_i].astype(np.float32) - self._mean) / self._std
            # Apply stochastic landmark augmentations (training only).
            if self._augment:
                seq = _augment_sequence_single(seq, self._rng)
            X_batch[local_i] = seq

        y_batch = self._y[batch_indices]
        return X_batch, y_batch


def main() -> None:
    if np is None:
        sys.exit("ERROR: numpy not installed. Run: pip install numpy")
    if tf is None or keras is None:
        sys.exit("ERROR: tensorflow not installed. Run: pip install tensorflow==2.15.1")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-classes", type=int, default=50)
    parser.add_argument("--min-samples-per-class", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--dropout", type=float, default=0.4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--arch",
        choices=["bigru", "bigru_attention"],
        default="bigru_attention",
        help="Model architecture (default: bigru_attention)",
    )
    parser.add_argument(
        "--split-mode",
        choices=["official", "signer-grouped", "random-stratified"],
        default="official",
        help="Train/val/test split strategy (default: official)",
    )
    parser.add_argument(
        "--augment",
        action="store_true",
        help="Apply landmark augmentation to training sequences (jitter, scaling, temporal resampling)",
    )
    parser.add_argument(
        "--exact-classes",
        type=int,
        default=0,
        metavar="N",
        help=(
            "After --max-classes filtering, further restrict to exactly N classes "
            "(top N by sample count, then re-sorted alphabetically). "
            "Set to 31 to match the application LABELS_COUNT=31 config. "
            "0 = disabled (default)."
        ),
    )
    parser.add_argument(
        "--drive-checkpoint",
        type=str,
        default="",
        metavar="DIR",
        help=(
            "Path to a Google Drive directory (e.g. /content/drive/MyDrive/) "
            "where an additional ModelCheckpoint will save gesture_model_best.h5 "
            "to survive Colab preemptions.  Leave empty to disable (default)."
        ),
    )
    args = parser.parse_args()

    _set_seeds(args.seed)

    dataset_path = args.data.resolve()
    if not dataset_path.exists():
        sys.exit(f"ERROR: Dataset not found: {dataset_path}")

    payload = np.load(dataset_path, allow_pickle=True)
    X = payload["X"].astype(np.float32)
    labels = payload["labels"].astype(str)
    splits = payload["splits"].astype(str)
    raw_signer_ids = (
        payload["signer_ids"].astype(np.int32)
        if "signer_ids" in payload
        else np.full(len(labels), -1, dtype=np.int32)
    )
    if X.ndim != 3 or X.shape[2] != FRAME_FEATURE_DIM:
        sys.exit(f"ERROR: Expected X shape (N, T, {FRAME_FEATURE_DIM}), got {X.shape}")
    sequence_length = int(X.shape[1])

    X, y, splits, label_map = _filter_classes(
        X,
        labels,
        splits,
        max_classes=args.max_classes,
        min_samples_per_class=args.min_samples_per_class,
    )
    # Keep signer_ids aligned after class filtering
    keep_mask = np.asarray([str(lbl) in {v for v in label_map.values()} for lbl in labels], dtype=bool)
    signer_ids = raw_signer_ids[keep_mask]

    # ── Optional exact-class subsetting ──────────────────────────────────────
    # When --exact-classes N is specified, further restrict to exactly the top N
    # classes by sample count (e.g. N=31 to match LABELS_COUNT=31 in the app).
    # The surviving classes are re-sorted alphabetically and re-indexed 0..N-1
    # so the resulting label_map is contiguous and correct for the application.
    if args.exact_classes > 0 and args.exact_classes < len(label_map):
        n_before = len(label_map)
        # Count samples per class index within the current filtered set.
        class_counts_now = np.bincount(y, minlength=len(label_map))
        # Take the top exact_classes indices sorted by descending count.
        top_indices = sorted(
            range(len(label_map)),
            key=lambda c: -int(class_counts_now[c]),
        )[:args.exact_classes]
        keep_class_set = set(top_indices)

        # Filter samples to the chosen class subset.
        sample_mask = np.isin(y, sorted(keep_class_set))
        X = X[sample_mask]
        splits = splits[sample_mask]
        signer_ids = signer_ids[sample_mask]
        y_before_remap = y[sample_mask]

        # Rebuild alphabetically ordered label_map with contiguous indices 0..N-1.
        kept_labels_sorted = sorted(label_map[c] for c in keep_class_set)
        new_label_to_idx: dict[str, int] = {lbl: i for i, lbl in enumerate(kept_labels_sorted)}
        old_label_map = label_map
        label_map = {i: lbl for i, lbl in enumerate(kept_labels_sorted)}

        # Remap y to new contiguous class indices.
        old_to_new = {c: new_label_to_idx[old_label_map[c]] for c in keep_class_set}
        y = np.array([old_to_new[c] for c in y_before_remap], dtype=np.int32)

        print(
            f"Exact-class subset: {len(label_map)} classes kept "
            f"(from {n_before} after max-class filter); "
            f"{int(sample_mask.sum())} samples retained."
        )
    elif args.exact_classes > 0 and args.exact_classes >= len(label_map):
        print(
            f"WARNING: --exact-classes {args.exact_classes} >= available classes "
            f"{len(label_map)}; subsetting skipped."
        )

    X = canonicalize_sequences(X)

    train_idx, val_idx, test_idx = _split_indices(
        splits,
        y,
        seed=args.seed,
        split_mode=args.split_mode,
        signer_ids=signer_ids,
    )
    if len(train_idx) == 0 or len(val_idx) == 0:
        sys.exit("ERROR: Empty train or validation split after filtering.")

    overlap_report = _signer_overlap(signer_ids, train_idx, val_idx, test_idx)

    # Compute normalisation statistics from training samples only.
    mean = X[train_idx].reshape(-1, FRAME_FEATURE_DIM).mean(axis=0)
    std = X[train_idx].reshape(-1, FRAME_FEATURE_DIM).std(axis=0) + 1e-8
    # Normalisation is applied per-batch inside LandmarkDataGenerator;
    # we intentionally do NOT globalise-normalize X here to avoid a
    # full second copy of the data in memory.

    num_classes = len(label_map)
    class_counts = np.bincount(y[train_idx], minlength=num_classes).astype(np.float32)
    max_count = float(class_counts.max())
    class_weight = {
        cls_idx: float(np.sqrt(max_count / max(count, 1.0)))
        for cls_idx, count in enumerate(class_counts)
    }

    model = build_model(num_classes, sequence_length, dropout_rate=args.dropout, arch=args.arch)
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=args.lr),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez(MODEL_OUT.parent / "norm_stats.npz", mean=mean, std=std)
    with LABEL_MAP_OUT.open("w", encoding="utf-8") as file_obj:
        json.dump({str(idx): label for idx, label in label_map.items()}, file_obj, indent=2)

    training_config = {
        "data": str(dataset_path),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "max_classes": args.max_classes,
        "exact_classes": args.exact_classes,
        "min_samples_per_class": args.min_samples_per_class,
        "lr": args.lr,
        "dropout": args.dropout,
        "seed": args.seed,
        "arch": args.arch,
        "split_mode": args.split_mode,
        "augment": args.augment,
        "drive_checkpoint": args.drive_checkpoint,
        "sequence_length": sequence_length,
        "feature_dim": FRAME_FEATURE_DIM,
        "tensorflow_version": tf.__version__,
    }
    TRAINING_CONFIG_OUT.write_text(json.dumps(training_config, indent=2), encoding="utf-8")

    callbacks = [
        keras.callbacks.ModelCheckpoint(
            str(MODEL_OUT),
            monitor="val_accuracy",
            save_best_only=True,
            verbose=1,
        ),
        keras.callbacks.EarlyStopping(
            monitor="val_accuracy",
            patience=10,
            restore_best_weights=True,
            verbose=1,
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=5,
            min_lr=1e-6,
            verbose=1,
        ),
    ]

    # ── Optional Google Drive checkpoint ─────────────────────────────────────
    # When --drive-checkpoint points to a mounted Drive directory, an additional
    # ModelCheckpoint writes gesture_model_best.h5 there so the best weights
    # survive a Colab runtime preemption or idle disconnect.
    if args.drive_checkpoint:
        drive_dir = Path(args.drive_checkpoint)
        if drive_dir.is_dir():
            drive_model_path = drive_dir / "gesture_model_best.h5"
            callbacks.append(
                keras.callbacks.ModelCheckpoint(
                    str(drive_model_path),
                    monitor="val_accuracy",
                    save_best_only=True,
                    verbose=1,
                )
            )
            print(f"Drive checkpoint  : {drive_model_path}")
        else:
            print(
                f"WARNING: --drive-checkpoint '{drive_dir}' does not exist or is not a "
                "directory — Drive backup disabled.  Mount Google Drive first with: "
                "from google.colab import drive; drive.mount('/content/drive')"
            )

    print("\n" + "=" * 64)
    print("SignConnect - Temporal Landmark Training")
    print("=" * 64)
    print(f"TensorFlow      : {tf.__version__}")
    print(f"Dataset         : {dataset_path}")
    print(f"Architecture    : {args.arch}")
    print(f"Split mode      : {args.split_mode}")
    print(f"Augmentation    : {args.augment}")
    print(f"Samples/classes : {len(X)} / {num_classes}")
    print(f"Input shape     : ({sequence_length}, {FRAME_FEATURE_DIM})")
    print(f"Split           : train={len(train_idx)} val={len(val_idx)} test={len(test_idx)}")
    print(f"Signer overlap  : train/val={overlap_report['train_val_overlap']} train/test={overlap_report['train_test_overlap']}")

    # ── Build Keras Sequence generators ──────────────────────────────────────
    # Generators apply normalisation (and optional augmentation) per batch,
    # keeping memory usage flat regardless of augmentation multiplier.
    train_gen = LandmarkDataGenerator(
        X_canonical=X,
        y=y,
        indices=train_idx,
        mean=mean,
        std=std,
        batch_size=args.batch_size,
        augment=args.augment,
        seed=args.seed + 1,
        shuffle=True,
    )
    val_gen = LandmarkDataGenerator(
        X_canonical=X,
        y=y,
        indices=val_idx,
        mean=mean,
        std=std,
        batch_size=args.batch_size,
        augment=False,
        seed=args.seed,
        shuffle=False,
    )

    history = model.fit(
        train_gen,
        validation_data=val_gen,
        epochs=args.epochs,
        class_weight=class_weight,
        callbacks=callbacks,
        verbose=1,
    )

    best_val_accuracy = float(max(history.history.get("val_accuracy", [0.0])))
    actual_epochs = len(history.history.get("val_accuracy", []))
    eval_indices = test_idx if len(test_idx) else val_idx

    # Build a non-shuffling generator for deterministic ordered predictions.
    eval_gen = LandmarkDataGenerator(
        X_canonical=X,
        y=y,
        indices=eval_indices,
        mean=mean,
        std=std,
        batch_size=args.batch_size,
        augment=False,
        seed=args.seed,
        shuffle=False,
    )
    probabilities = model.predict(eval_gen, verbose=0)
    predictions = np.argmax(probabilities, axis=1)
    y_eval = y[eval_indices]
    top1 = float(np.mean(predictions == y_eval))
    top5 = _top_k_accuracy(y_eval, probabilities, k=min(5, num_classes))
    macro_f1 = _macro_f1(y_eval, predictions, num_classes)

    _write_confusion(CONFUSION_OUT, y_eval, predictions, label_map)
    _write_per_class_metrics(PER_CLASS_METRICS_OUT, y_eval, predictions, label_map)

    demo_marker = MODEL_OUT.with_suffix(".demo")
    if demo_marker.exists():
        demo_marker.unlink()

    # Save training history curves
    HISTORY_OUT.write_text(
        json.dumps({k: [float(v) for v in vals] for k, vals in history.history.items()}, indent=2),
        encoding="utf-8",
    )

    # Compute artifact checksums
    checksums: dict[str, str] = {}
    for artifact_path in (MODEL_OUT, LABEL_MAP_OUT, MODEL_OUT.parent / "norm_stats.npz"):
        if artifact_path.exists():
            checksums[artifact_path.name] = _file_sha256(artifact_path)

    metrics = {
        "model_type": TEMPORAL_MODEL_TYPE,
        "arch": args.arch,
        "dataset": str(dataset_path),
        "sequence_length": sequence_length,
        "feature_dim": FRAME_FEATURE_DIM,
        "classes": num_classes,
        "samples": int(len(X)),
        "train_samples": int(len(train_idx)),
        "val_samples": int(len(val_idx)),
        "test_samples": int(len(test_idx)),
        "best_val_accuracy": best_val_accuracy,
        "actual_epochs": actual_epochs,
        "eval_split": "test" if len(test_idx) else "val",
        "eval_top1_accuracy": top1,
        "eval_top5_accuracy": top5,
        "eval_macro_f1": macro_f1,
        "signer_overlap": overlap_report,
        "training_config": training_config,
        "artifact_checksums": checksums,
        "labels": [label_map[idx] for idx in range(num_classes)],
    }
    METRICS_OUT.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("-" * 64)
    print(f"Best val accuracy : {best_val_accuracy:.4f}")
    print(f"Eval top-1        : {top1:.4f}")
    print(f"Eval top-5        : {top5:.4f}")
    print(f"Eval macro F1     : {macro_f1:.4f}")
    print(f"Epochs run        : {actual_epochs}")
    print(f"Signer overlap    : {overlap_report}")
    print(f"Model saved       : {MODEL_OUT}")
    print(f"Metrics saved     : {METRICS_OUT}")
    print(f"Confusion matrix  : {CONFUSION_OUT}")
    print(f"Per-class metrics : {PER_CLASS_METRICS_OUT}")
    print(f"History           : {HISTORY_OUT}")
    print(f"Training config   : {TRAINING_CONFIG_OUT}")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
