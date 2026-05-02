"""Train a temporal landmark classifier from WLASL sequence datasets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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


def canonicalize_sequences(X: np.ndarray) -> np.ndarray:
    canonical = np.zeros_like(X, dtype=np.float32)
    for sample_idx in range(X.shape[0]):
        for frame_idx in range(X.shape[1]):
            frame = X[sample_idx, frame_idx].astype(np.float32)
            if np.abs(frame).sum() < 1e-8:
                continue
            hand1 = _canonicalize_hand(frame[:63])
            hand2_raw = frame[63:126]
            hand2 = _canonicalize_hand(hand2_raw) if np.abs(hand2_raw).sum() > 1e-8 else hand2_raw
            canonical[sample_idx, frame_idx] = np.concatenate([hand1, hand2])
    return canonical


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


def _augment_sequence(X: np.ndarray, rng: np.random.Generator, noise_std: float = 0.005) -> np.ndarray:
    """Apply lightweight augmentation to a batch of sequences (in-place copy)."""
    result = X.copy()
    # Small Gaussian noise on non-zero frames
    mask = np.abs(result).sum(axis=-1, keepdims=True) > 1e-8
    result += mask * rng.standard_normal(result.shape).astype(np.float32) * noise_std
    return result


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


def main() -> None:
    if np is None:
        sys.exit("ERROR: numpy not installed. Run: pip install numpy")
    if tf is None or keras is None:
        sys.exit("ERROR: tensorflow not installed. Run: pip install tensorflow==2.15.1")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-classes", type=int, default=50)
    parser.add_argument("--min-samples-per-class", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--dropout", type=float, default=0.35)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--arch",
        choices=["bigru", "bigru_attention"],
        default="bigru",
        help="Model architecture (default: bigru)",
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
        help="Apply lightweight noise augmentation to training sequences",
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

    mean = X[train_idx].reshape(-1, FRAME_FEATURE_DIM).mean(axis=0)
    std = X[train_idx].reshape(-1, FRAME_FEATURE_DIM).std(axis=0) + 1e-8
    X = (X - mean.reshape(1, 1, FRAME_FEATURE_DIM)) / std.reshape(1, 1, FRAME_FEATURE_DIM)

    X_train = X[train_idx]
    if args.augment:
        aug_rng = np.random.default_rng(args.seed + 1)
        X_train = _augment_sequence(X_train, aug_rng)

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
        "min_samples_per_class": args.min_samples_per_class,
        "lr": args.lr,
        "dropout": args.dropout,
        "seed": args.seed,
        "arch": args.arch,
        "split_mode": args.split_mode,
        "augment": args.augment,
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

    print("\n" + "=" * 64)
    print("SignConnect - Temporal Landmark Training")
    print("=" * 64)
    print(f"TensorFlow      : {tf.__version__}")
    print(f"Dataset         : {dataset_path}")
    print(f"Architecture    : {args.arch}")
    print(f"Split mode      : {args.split_mode}")
    print(f"Samples/classes : {len(X)} / {num_classes}")
    print(f"Input shape     : ({sequence_length}, {FRAME_FEATURE_DIM})")
    print(f"Split           : train={len(train_idx)} val={len(val_idx)} test={len(test_idx)}")
    print(f"Signer overlap  : train/val={overlap_report['train_val_overlap']} train/test={overlap_report['train_test_overlap']}")

    history = model.fit(
        X_train,
        y[train_idx],
        validation_data=(X[val_idx], y[val_idx]),
        epochs=args.epochs,
        batch_size=args.batch_size,
        class_weight=class_weight,
        callbacks=callbacks,
        verbose=1,
    )

    best_val_accuracy = float(max(history.history.get("val_accuracy", [0.0])))
    actual_epochs = len(history.history.get("val_accuracy", []))
    eval_indices = test_idx if len(test_idx) else val_idx
    probabilities = model.predict(X[eval_indices], verbose=0)
    predictions = np.argmax(probabilities, axis=1)
    top1 = float(np.mean(predictions == y[eval_indices]))
    top5 = _top_k_accuracy(y[eval_indices], probabilities, k=min(5, num_classes))
    macro_f1 = _macro_f1(y[eval_indices], predictions, num_classes)

    _write_confusion(CONFUSION_OUT, y[eval_indices], predictions, label_map)
    _write_per_class_metrics(PER_CLASS_METRICS_OUT, y[eval_indices], predictions, label_map)

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
