# syntax=docker/dockerfile:1

# ---- 1. build the React app ----
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. the app: Django + gunicorn, serving the built UI ----
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    APP_VAR_DIR=/data FRONTEND_DIST=/app/frontend-dist \
    HF_HOME=/opt/hf TOKENIZERS_PARALLELISM=false
WORKDIR /app

# CPU-only torch keeps the image far smaller than the default CUDA build.
RUN pip install torch==2.2.2 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Bake the embedding model into the image so the container starts offline.
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('all-MiniLM-L6-v2')"

COPY . .
COPY --from=frontend /frontend/dist /app/frontend-dist
RUN useradd --create-home app && mkdir /data && chown app /data && chmod -R a+rX /opt/hf
USER app
EXPOSE 8000
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz/', timeout=4)"
ENTRYPOINT ["./docker-entrypoint.sh"]
