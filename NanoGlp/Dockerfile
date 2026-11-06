# ==============================================================================
# NANOLAB Edirne GLP AI Operasyonel Planlama & Numune Takip Sistemi
# FAZ 10 — Multi-Stage Production Dockerfile (React Vite Build + FastAPI Single-Port)
# ==============================================================================

# 1. Aşama: Frontend (React + Vite) Derlemesi
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. Aşama: Backend (FastAPI + SQLite WAL + PyMuPDF + OpenPyXL + python-docx)
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENV=production \
    APP_ENV=production \
    DATABASE_URL=sqlite:////app/backend/data/nanolab_glp.db \
    UPLOAD_DIR=/app/backend/uploads

WORKDIR /app

# Sistem bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python bağımlılıkları
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r ./backend/requirements.txt

# Backend kaynak kodu ve referans Excel
COPY backend/ ./backend/
COPY ["Study Status last version (2).xlsx", "./Study Status last version (2).xlsx"]

# Derlenmiş Frontend statik dosyalarını (frontend/dist) kopyala
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Kalıcı veri ve yükleme dizinleri
RUN mkdir -p /app/backend/data /app/backend/uploads

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
