"""One-shot diagnostics for camera, MediaPipe, TensorFlow, and model file."""

import os
import sys

print(f"Python: {sys.version}")
print(f"Executable: {sys.executable}")

# Test 1: Camera
import cv2

cap = cv2.VideoCapture(0)
print(f"Camera opened: {cap.isOpened()}")
if cap.isOpened():
    ret, frame = cap.read()
    print(f"Frame read: {ret}, shape: {frame.shape if ret else 'N/A'}")
cap.release()

# Test 2: MediaPipe
import mediapipe as mp

try:
    hands = mp.solutions.hands.Hands()
    print("MediaPipe Hands: OK")
    hands.close()
except Exception as e:
    print(f"MediaPipe Hands FAILED: {e}")

# Test 3: TensorFlow + Model
import tensorflow as tf

print(f"TensorFlow version: {tf.__version__}")
model_path = "models/gesture_model.h5"
print(f"Model file exists: {os.path.exists(model_path)}")
print(
    f"Model file size: {os.path.getsize(model_path) if os.path.exists(model_path) else 'N/A'} bytes"
)
try:
    model = tf.keras.models.load_model(model_path)
    print(f"Model loaded: OK — input shape: {model.input_shape}")
except Exception as e:
    print(f"Model load FAILED: {e}")
