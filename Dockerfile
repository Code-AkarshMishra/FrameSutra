# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Build React frontend
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

# Copy frontend source
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline 2>/dev/null || npm install

COPY frontend/ ./
RUN npm run build
# Output: /app/frontend/dist/


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Python backend with local ML models
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS backend

# System deps: FFmpeg (required for audio/video processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ffprobe \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (heaviest first for layer caching)
COPY Requirements.txt .

# Install torch CPU-only first to avoid downloading CUDA (~2GB saved)
RUN pip install --no-cache-dir \
    torch==2.2.2+cpu torchvision==0.17.2+cpu torchaudio==2.2.2+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Install rest of requirements
RUN pip install --no-cache-dir -r Requirements.txt

# Copy project source
COPY api.py main.py check_setup.py ./
COPY core/ ./core/
COPY utils/ ./utils/

# Copy built frontend into static/ folder so FastAPI can serve it
COPY --from=frontend-builder /app/frontend/dist/ ./static/

# Pre-create persistent directories
RUN mkdir -p uploads downloads .cache vector_db

# Expose the port Railway will use
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Start the FastAPI server
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
