FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install . passlib[bcrypt] python-multipart

COPY config/ ./config/
COPY services/ ./services/

RUN useradd -m -u 1000 nagarsaathi && \
    mkdir -p /app/.local/media && \
    chown -R nagarsaathi:nagarsaathi /app

USER nagarsaathi

CMD ["python", "-m", "services.worker.worker"]
