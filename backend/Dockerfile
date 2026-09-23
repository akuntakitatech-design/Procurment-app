# =============================================================
# ProcureFlow / Procurement — Backend API (FastAPI + MariaDB + R2)
# Base directory di Coolify: /backend  |  Build pack: Dockerfile  |  Port: 8000
# =============================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    STORAGE_LOCAL_PATH=/app/data/uploads

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/memory /app/data/uploads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT}/api/_healthcheck >/dev/null || exit 1

# production_bootstrap: memuat seluruh layer, menjalankan uvicorn (proxy headers aktif)
CMD ["python", "production_bootstrap.py"]
