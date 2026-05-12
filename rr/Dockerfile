# ── Stage 1: build deps ────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System libraries needed by OpenCV and MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime image ─────────────────────────────────────────────────
FROM python:3.11-slim

LABEL maintainer="SignConnect"
LABEL description="AI-powered real-time sign language translator"

WORKDIR /app

# Only the runtime system libraries (not build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Persistent volumes — mount these to keep data between container restarts
VOLUME ["/app/database", "/app/data", "/app/models", "/app/static/audio"]

EXPOSE 5000

ENV HOST=0.0.0.0 \
    PORT=5000 \
    LOG_LEVEL=INFO \
    DEBUG=false

# Use waitress for production HTTP serving inside the container.
# WebSocket support falls back to long-polling (sufficient for most deployments).
# For full WebSocket support, mount a reverse proxy that handles the upgrade.
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--threads=8", "--call", "app:create_app"]
