"""One-shot diagnostics for environment, camera, MediaPipe, TensorFlow, and model file."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model_contract import (
    MODEL_INPUT_DIM,
    SEQUENCE_LENGTH,
    TEMPORAL_MODEL_TYPE,
    SUPPORTED_MODEL_TYPES,
    model_input_dim,
    model_output_count,
    model_sequence_length,
)


def _import_module(name: str):
    """Import a runtime dependency and report a readable error on failure."""
    try:
        return importlib.import_module(name)
    except Exception as error:
        print(f"{name} import FAILED: {error}")
        return None


def _check_env() -> dict[str, str]:
    """Validate and return key environment variables."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import dotenv_values
            env_vals = dict(dotenv_values(str(env_path)))
        except Exception:
            env_vals = {}
        print(f".env file       : {env_path} (loaded)")
    else:
        env_vals = {}
        print(f".env file       : NOT FOUND (using OS environment only)")

    model_type = os.getenv("MODEL_TYPE", "mlp")
    sequence_length = os.getenv("SEQUENCE_LENGTH", str(SEQUENCE_LENGTH))
    labels_count = os.getenv("LABELS_COUNT", "?")

    print(f"MODEL_TYPE env  : {model_type}", end="")
    if model_type not in SUPPORTED_MODEL_TYPES:
        print(f"  ← WARNING: unsupported; expected one of {SUPPORTED_MODEL_TYPES}", end="")
    elif model_type == "mlp":
        print("  ← NOTE: set MODEL_TYPE=temporal_landmark for WLASL temporal models", end="")
    print()

    print(f"SEQUENCE_LENGTH : {sequence_length}")
    print(f"LABELS_COUNT    : {labels_count}")
    return {"model_type": model_type, "sequence_length": sequence_length, "labels_count": labels_count}


print(f"Python: {sys.version}")
print(f"Executable: {sys.executable}")
print(f"Expected model input dim: {MODEL_INPUT_DIM}")
print(f"Expected temporal sequence length: {SEQUENCE_LENGTH}")

env_vars = _check_env()

cv2 = _import_module("cv2")
if cv2 is not None:
    cap = cv2.VideoCapture(0)
    print(f"Camera opened: {cap.isOpened()}")
    if cap.isOpened():
        ret, frame = cap.read()
        print(f"Frame read: {ret}, shape: {frame.shape if ret else 'N/A'}")
    cap.release()

mp = _import_module("mediapipe")
if mp is not None:
    print(f"MediaPipe version: {getattr(mp, '__version__', 'unknown')}")
    try:
        hands = mp.solutions.hands.Hands()
        print("MediaPipe Hands: OK")
        hands.close()
    except Exception as error:
        print(f"MediaPipe Hands FAILED: {error}")

protobuf = _import_module("google.protobuf")
if protobuf is not None:
    print(f"protobuf version: {getattr(protobuf, '__version__', 'unknown')}")

tf = _import_module("tensorflow")
if tf is not None:
    print(f"TensorFlow version: {tf.__version__}")
    model_path = PROJECT_ROOT / "models" / "gesture_model.h5"
    label_map_path = PROJECT_ROOT / "models" / "label_map.json"
    norm_stats_path = PROJECT_ROOT / "models" / "norm_stats.npz"
    metrics_path = PROJECT_ROOT / "models" / "temporal_metrics.json"
    demo_marker_path = PROJECT_ROOT / "models" / "gesture_model.demo"
    print(f"Model file exists: {model_path.exists()}")
    print(f"Model file size: {model_path.stat().st_size if model_path.exists() else 'N/A'} bytes")
    print(f"Norm stats exists: {norm_stats_path.exists()}")
    print(f"Demo marker exists: {demo_marker_path.exists()}")
    if demo_marker_path.exists():
        print("  ← WARNING: demo marker present; app will run in demo mode")

    label_count = None
    try:
        with label_map_path.open(encoding="utf-8") as file_obj:
            label_map_data = json.load(file_obj)
            label_count = len(label_map_data)
        print(f"Label map loaded: {label_count} labels")

        # Cross-check LABELS_COUNT env vs label_map
        env_labels = env_vars.get("labels_count", "?")
        if env_labels.isdigit() and int(env_labels) != label_count:
            print(
                f"  ← MISMATCH: LABELS_COUNT env={env_labels} but label_map has {label_count} entries"
            )
    except Exception as exc:
        print(f"Label map load FAILED: {exc}")

    if norm_stats_path.exists():
        try:
            import numpy as np
            norm_data = np.load(str(norm_stats_path))
            mean_shape = norm_data["mean"].shape
            std_shape = norm_data["std"].shape
            expected = (MODEL_INPUT_DIM,)
            print(
                f"Norm stats shape: mean={mean_shape} std={std_shape} "
                f"— contract OK: {mean_shape == expected and std_shape == expected}"
            )
        except Exception as exc:
            print(f"Norm stats load FAILED: {exc}")

    try:
        model = tf.keras.models.load_model(str(model_path))
        input_dim = model_input_dim(model.input_shape)
        output_count = model_output_count(model.output_shape)
        sequence_length = model_sequence_length(model.input_shape)
        print(f"Model loaded: OK - input shape: {model.input_shape}")
        print(f"Model output shape: {model.output_shape}")
        print(f"Input contract OK: {input_dim == MODEL_INPUT_DIM}")
        print(
            "Temporal contract OK: "
            f"{sequence_length == SEQUENCE_LENGTH if sequence_length is not None else 'N/A'}"
        )
        print(f"Output-label contract OK: {output_count == label_count}")

        # Cross-check sequence length vs env
        env_seq = env_vars.get("sequence_length", str(SEQUENCE_LENGTH))
        if env_seq.isdigit() and sequence_length is not None and int(env_seq) != sequence_length:
            print(
                f"  ← MISMATCH: SEQUENCE_LENGTH env={env_seq} but model has sequence_length={sequence_length}"
            )
    except Exception as error:
        print(f"Model load FAILED: {error}")

    if metrics_path.exists():
        try:
            with metrics_path.open(encoding="utf-8") as file_obj:
                metrics = json.load(file_obj)
            print(f"Metrics model type: {metrics.get('model_type', TEMPORAL_MODEL_TYPE)}")
            print(f"Metrics arch: {metrics.get('arch', 'N/A')}")
            print(f"Metrics classes: {metrics.get('classes', 'N/A')}")
            print(f"Metrics samples: {metrics.get('samples', 'N/A')}")
            print(f"Metrics sequence_length: {metrics.get('sequence_length', 'N/A')}")
            print(f"Eval top-1 accuracy: {metrics.get('eval_top1_accuracy', 'N/A')}")
            print(f"Eval top-5 accuracy: {metrics.get('eval_top5_accuracy', 'N/A')}")
            print(f"Eval macro F1: {metrics.get('eval_macro_f1', 'N/A')}")
            print(f"Metrics-label contract OK: {metrics.get('classes') == label_count}")
            signer_overlap = metrics.get("signer_overlap")
            if signer_overlap:
                print(f"Signer overlap report: {signer_overlap}")
        except Exception as exc:
            print(f"Metrics load FAILED: {exc}")
    else:
        print(f"Metrics file: NOT FOUND at {metrics_path}")

