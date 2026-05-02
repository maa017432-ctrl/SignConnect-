"""
SignConnect Colab/GPU Training Pipeline
========================================
Run this script in a Google Colab notebook (GPU runtime) or any Linux
machine with a CUDA-capable GPU.

Quick start (Colab):
    1. Mount Google Drive:
           from google.colab import drive; drive.mount('/content/drive')
    2. Install dependencies:
           !pip install -q tensorflow numpy opencv-python-headless mediapipe==0.10.9 protobuf>=3.20.0,<4.0.0
    3. Clone or upload the SignConnect repository to /content/SignConnect.
    4. Run:
           !python /content/SignConnect/scripts/colab_wlasl_pipeline.py --tier 300

The script will:
  * Check GPU availability and warn if none is found.
  * Use Drive-mounted paths for WLASL data, sequences, and model artifacts.
  * Run extraction (resumable) and training in sequence.
  * Export a zipped artifact bundle ready to copy back to your local models/ dir.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


# ── Default Drive paths ───────────────────────────────────────────────────────

DRIVE_ROOT = Path("/content/drive/MyDrive/SignConnectColab")
WLASL_DIR = DRIVE_ROOT / "WLASL"
SEQUENCES_DIR = DRIVE_ROOT / "sequences"
ARTIFACTS_DIR = DRIVE_ROOT / "artifacts"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "models"

ARTIFACT_FILES = [
    "gesture_model.h5",
    "label_map.json",
    "norm_stats.npz",
    "temporal_metrics.json",
    "temporal_confusion_matrix.csv",
    "history.json",
    "training_config.json",
    "per_class_metrics.csv",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(command: list[str], *, check: bool = True) -> int:
    print("\n$ " + " ".join(str(c) for c in command), flush=True)
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if check and result.returncode != 0:
        sys.exit(f"Command failed with exit code {result.returncode}")
    return result.returncode


def _check_gpu() -> bool:
    """Return True if TensorFlow sees at least one GPU."""
    try:
        import tensorflow as tf
        gpus = tf.config.list_physical_devices("GPU")
        if gpus:
            print(f"[GPU] {len(gpus)} GPU(s) detected: {[g.name for g in gpus]}", flush=True)
            try:
                for gpu in gpus:
                    info = tf.config.experimental.get_memory_info(gpu.name)
                    total_gb = info.get("total", 0) / (1024 ** 3)
                    print(f"      {gpu.name} — {total_gb:.1f} GB VRAM", flush=True)
            except Exception:
                pass
            return True
        print("[GPU] WARNING: No GPU detected. Training will be slow on CPU.", flush=True)
        return False
    except ImportError:
        print("[GPU] WARNING: TensorFlow not importable; skipping GPU check.", flush=True)
        return False


def _enable_mixed_precision() -> None:
    """Enable float16 mixed precision if a GPU is available."""
    try:
        import tensorflow as tf
        if tf.config.list_physical_devices("GPU"):
            tf.keras.mixed_precision.set_global_policy("mixed_float16")
            print("[GPU] Mixed precision (float16) enabled.", flush=True)
    except Exception as exc:
        print(f"[GPU] Mixed precision setup skipped: {exc}", flush=True)


def _export_artifacts(run_id: str) -> Path:
    """Zip all trained artifacts into Drive artifacts/<run_id>.zip."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = ARTIFACTS_DIR / f"{run_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename in ARTIFACT_FILES:
            src = MODELS_DIR / filename
            if src.exists():
                zf.write(src, arcname=filename)
                print(f"  + {filename}", flush=True)
            else:
                print(f"  - {filename} (missing, skipped)", flush=True)
    print(f"\nArtifact bundle: {zip_path}", flush=True)
    print("\nTo deploy locally, copy these files to your models/ directory:", flush=True)
    print(f"  unzip -o {zip_path} -d /path/to/SignConnect/models/", flush=True)
    print("Then update .env:", flush=True)
    print("  MODEL_TYPE=temporal_landmark", flush=True)
    print("  SEQUENCE_LENGTH=30", flush=True)
    print("  LABELS_COUNT=<classes>", flush=True)
    return zip_path


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", type=int, default=300, help="Number of WLASL classes to train (default: 300)")
    parser.add_argument("--wlasl-dir", type=Path, default=WLASL_DIR, help="Path to WLASL directory with info.json and videos/")
    parser.add_argument("--sequences-dir", type=Path, default=SEQUENCES_DIR, help="Directory to store/resume extracted sequences")
    parser.add_argument("--epochs", type=int, default=80, help="Training epochs (default: 80)")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size (reduce if OOM; default: 32)")
    parser.add_argument("--arch", choices=["bigru", "bigru_attention"], default="bigru", help="Model architecture")
    parser.add_argument("--split-mode", choices=["official", "signer-grouped", "random-stratified"], default="official")
    parser.add_argument("--augment", action="store_true", help="Apply training augmentation")
    parser.add_argument("--mixed-precision", action="store_true", help="Enable float16 mixed precision for GPU")
    parser.add_argument("--force-extract", action="store_true", help="Re-extract sequences even if NPZ exists")
    parser.add_argument("--skip-extract", action="store_true", help="Skip extraction and go straight to training")
    parser.add_argument("--skip-train", action="store_true", help="Skip training (only extract)")
    parser.add_argument("--run-id", type=str, default="", help="Artifact bundle run ID (default: tier{N})")
    args = parser.parse_args()

    run_id = args.run_id or f"tier{args.tier}"
    wlasl_dir = args.wlasl_dir.resolve()
    sequences_dir = args.sequences_dir.resolve()
    sequences_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = sequences_dir / f"tier{args.tier}_sequences.npz"

    print("=" * 64, flush=True)
    print("SignConnect - Colab/GPU WLASL Pipeline", flush=True)
    print("=" * 64, flush=True)
    print(f"Tier             : {args.tier} classes", flush=True)
    print(f"WLASL dir        : {wlasl_dir}", flush=True)
    print(f"Sequences dir    : {sequences_dir}", flush=True)
    print(f"Dataset path     : {dataset_path}", flush=True)
    print(f"Architecture     : {args.arch}", flush=True)
    print(f"Run ID           : {run_id}", flush=True)

    _check_gpu()
    if args.mixed_precision:
        _enable_mixed_precision()

    if not (wlasl_dir / "info.json").exists():
        sys.exit(
            f"ERROR: WLASL info.json not found at {wlasl_dir / 'info.json'}\n"
            "Mount your Drive and ensure WLASL is at the expected path, or pass --wlasl-dir."
        )

    # ── Extraction ────────────────────────────────────────────────────────────
    if not args.skip_extract:
        print("\n" + "-" * 64, flush=True)
        print(f"Phase 1: Extraction (tier {args.tier})", flush=True)
        print("-" * 64, flush=True)
        min_videos = 20 if args.tier <= 50 else 10
        extract_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "wlasl_to_sequences.py"),
            "--wlasl-dir", str(wlasl_dir),
            "--max-classes", str(args.tier),
            "--min-videos-per-class", str(min_videos),
            "--sequence-length", "30",
            "--min-detected-frames", "6",
            "--checkpoint-every", "50",
            "--progress-every", "10",
            "--output", str(dataset_path),
        ]
        if args.force_extract:
            extract_cmd.append("--force")
        _run(extract_cmd)

    # ── Training ─────────────────────────────────────────────────────────────
    if not args.skip_train:
        if not dataset_path.exists():
            sys.exit(f"ERROR: Dataset not found after extraction: {dataset_path}")
        print("\n" + "-" * 64, flush=True)
        print(f"Phase 2: Training (tier {args.tier}, arch={args.arch})", flush=True)
        print("-" * 64, flush=True)
        train_cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "train_temporal.py"),
            "--data", str(dataset_path),
            "--max-classes", str(args.tier),
            "--min-samples-per-class", "8",
            "--epochs", str(args.epochs),
            "--batch-size", str(args.batch_size),
            "--arch", args.arch,
            "--split-mode", args.split_mode,
        ]
        if args.augment:
            train_cmd.append("--augment")
        _run(train_cmd)

    # ── Artifact export ───────────────────────────────────────────────────────
    print("\n" + "-" * 64, flush=True)
    print("Phase 3: Export artifact bundle", flush=True)
    print("-" * 64, flush=True)
    zip_path = _export_artifacts(run_id)

    print("\n" + "=" * 64, flush=True)
    print("Pipeline complete.", flush=True)
    print(f"Artifact bundle : {zip_path}", flush=True)
    print("=" * 64, flush=True)


if __name__ == "__main__":
    main()
