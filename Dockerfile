FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY src ./src
ENV VITE_API_BASE_URL=/api
RUN npm run build

FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NAGARSAATHI_DEVICE=cpu \
    NAGARSAATHI_DATA_DIR=/var/data \
    YOLO_MODEL_PATH=backend/models/nagarsaathi-combined-v3.pt \
    MODEL_METADATA_PATH=backend/combined_model_metadata.json \
    YOLO_AUTOINSTALL=false \
    OMP_NUM_THREADS=2
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-api.txt /app/backend/requirements-api.txt
RUN pip install --no-cache-dir -r backend/requirements-api.txt
COPY backend /app/backend
COPY --from=frontend /build/dist /app/dist
RUN mkdir -p /var/data && chown -R 1000:1000 /var/data /app
USER 1000:1000
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn backend.server:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --limit-concurrency 8"]
