# SignConnect

SignConnect is an AI-based real-time sign language translator built with Flask, OpenCV, MediaPipe, TensorFlow/Keras, gTTS, and SQLite.

## Features

- Real-time webcam stream for hand gesture translation
- MediaPipe hand landmark extraction and model-based classification
- Demo mode when model file is missing or invalid
- Text-to-speech output with online and offline fallback
- Translation history stored in SQLite and viewable in UI

## Setup

1. Create the Python 3.11 virtual environment expected by the launch scripts:
   - `py -3.11 -m venv .venv311`
2. Install dependencies:
   - `.venv311\Scripts\python.exe -m pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and adjust values.
4. Run:
   - `.\run.ps1`
5. Open:
   - `http://localhost:5000`

## Environment Notes

- Use Python 3.11 with the project-local `.venv311` environment.
- This Windows setup uses TensorFlow CPU execution. AMD GPU training is not expected to work with this TensorFlow stack.
- `mediapipe==0.10.9` is pinned with `protobuf<4` to avoid known protobuf compatibility problems.
- To check the runtime environment before debugging the app, run:
  - `.venv311\Scripts\python.exe scripts\diagnose.py`

## Model Training (Overview)

1. Collect labeled hand landmark samples or processed frame data.
2. Train a Keras model that outputs probabilities for the labels in `models/label_map.json`.
3. Export model to `models/gesture_model.h5`.
4. Keep `models/label_map.json` aligned with output indices.
5. Keep the input feature contract at `126` values: two hands x 21 landmarks x 3 coordinates.

For WLASL temporal training:

1. Audit local data: `.venv311\Scripts\python.exe scripts\audit_wlasl.py`
2. Extract sequences: `.venv311\Scripts\python.exe scripts\wlasl_to_sequences.py --max-classes 50`
3. Train temporal model: `.venv311\Scripts\python.exe scripts\train_temporal.py --max-classes 50`
4. Set `MODEL_TYPE=temporal_landmark` and `SEQUENCE_LENGTH=30` before running the app with the temporal model.
5. Review `models\temporal_metrics.json` and `models\temporal_confusion_matrix.csv`; do not use random frame accuracy as the source of truth.

To run the staged path end-to-end, use:

`.venv311\Scripts\python.exe scripts\run_wlasl_tiers.py --tiers 50 100 300`

## API Documentation

| Method | Endpoint | Description | Response |
|---|---|---|---|
| GET | `/api/status` | Service health status | `{camera, model, tts}` |
| POST | `/api/translate` | TTS from text body | `{audio_url}` |
| GET | `/api/history` | Last 50 translation entries | `[{...}]` |
| DELETE | `/api/history` | Clears translation table for session testing | `{status}` |
