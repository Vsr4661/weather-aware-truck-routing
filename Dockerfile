# --- 1. Build the React app -------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. Django API + the built frontend, served by gunicorn/WhiteNoise -------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=0
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /app/frontend/dist frontend/dist
# Pre-compress assets so WhiteNoise can serve gzip/brotli variants.
RUN python -m whitenoise.compress frontend/dist
RUN useradd --create-home app && chown -R app /app
USER app
WORKDIR /app/backend
EXPOSE 8000
# Requests are I/O-bound (routing + weather APIs), so threads do the heavy lifting.
CMD gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 8 --timeout 90 --access-logfile -
