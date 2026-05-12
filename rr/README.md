# SignConnect

SignConnect is an AI-based real-time sign language translator built with Flask, OpenCV, MediaPipe, TensorFlow/Keras, gTTS, and SQLite.

## Features

- Real-time webcam stream for hand gesture translation
- MediaPipe hand landmark extraction and model-based classification
- Demo mode when model file is missing or invalid
- Text-to-speech output with online and offline fallback
- Translation history stored in SQLite and viewable in UI

## Setup

1. Create a Python 3.10+ virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and adjust values.
4. Run:
   - `python app.py`
5. Open:
   - `http://localhost:5000`

## Model Training (Overview)

1. Collect labeled hand landmark samples or processed frame data.
2. Train a Keras model that outputs probabilities for 31 labels.
3. Export model to `models/gesture_model.h5`.
4. Keep `models/label_map.json` aligned with output indices.

## API Documentation

| Method | Endpoint | Description | Response |
|---|---|---|---|
| GET | `/api/status` | Service health status | `{camera, model, tts}` |
| POST | `/api/translate` | TTS from text body | `{audio_url}` |
| GET | `/api/history` | Last 50 translation entries | `[{...}]` |
| DELETE | `/api/history` | Clears translation table for session testing | `{status}` |
