# DeepVision AI - Production Container for Railway Cloud Deployment
FROM python:3.10-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DATA_DIR=/app/data \
    MODELS_DIR=/app/models \
    EXPORTS_DIR=/app/exports

WORKDIR /app

# Install system dependencies required for OpenCV and image operations in headless Linux
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure data and models folders exist
RUN mkdir -p /app/data /app/models /app/exports

# Pre-cache Deep Learning ONNX models (YuNet Face Detector & SFace Recognizer) at build time
# so the container boots instantly on Railway without network download delays
RUN python -c "from core.model_loader import ensure_models_exist; assert ensure_models_exist(), 'Model download failed during build'"

# Expose default HTTP port
EXPOSE 8000

# Start FastAPI server listening on 0.0.0.0:$PORT
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
