FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/services/api:/app/services/worker

WORKDIR /app

# libgl1 / libglib2.0-0 are needed by OpenCV, which Ultralytics imports.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
RUN python -m pip install --upgrade pip && \
    python -c "import subprocess,sys,tomllib; deps=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; subprocess.check_call([sys.executable,'-m','pip','install',*deps])"

# CPU-only PyTorch keeps the image a few hundred MB instead of several GB.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install "ultralytics>=8.3,<9"

COPY config/ ./config/
COPY fixtures/ ./fixtures/
COPY models/ ./models/
COPY services/ ./services/

RUN useradd -m -u 1000 nagarsaathi && \
    mkdir -p /app/.local/media /app/.config && \
    chown -R nagarsaathi:nagarsaathi /app

USER nagarsaathi
ENV YOLO_CONFIG_DIR=/app/.config/ultralytics

CMD ["python", "-m", "worker"]
