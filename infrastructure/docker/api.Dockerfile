FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies (including libpq and geos/gdal essentials if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata & install Python dependencies
COPY pyproject.toml alembic.ini ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install ".[dev]" passlib[bcrypt] python-multipart

# Copy application source code and configuration
COPY config/ ./config/
COPY services/ ./services/
COPY scripts/ ./scripts/

# Create non-root user and persistent media directory
RUN useradd -m -u 1000 nagarsaathi && \
    mkdir -p /app/.local/media && \
    chown -R nagarsaathi:nagarsaathi /app

USER nagarsaathi

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -f http://127.0.0.1:8000/api/v1/health/ready || exit 1

CMD ["uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
