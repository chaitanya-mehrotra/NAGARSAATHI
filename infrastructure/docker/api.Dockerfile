FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/services/api:/app/services/worker \
    PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install only the declared dependencies; the code runs from source (it reads config/ and
# fixtures/ relative to the project root), so the project itself is not installed.
COPY pyproject.toml alembic.ini ./
RUN python -m pip install --upgrade pip && \
    python -c "import subprocess,sys,tomllib; deps=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; subprocess.check_call([sys.executable,'-m','pip','install',*deps])"

COPY config/ ./config/
COPY fixtures/ ./fixtures/
COPY services/ ./services/
COPY scripts/ ./scripts/

RUN useradd -m -u 1000 nagarsaathi && \
    mkdir -p /app/.local/media && \
    chown -R nagarsaathi:nagarsaathi /app

USER nagarsaathi

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -f http://127.0.0.1:8000/api/v1/health/ready || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
