FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/main/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && playwright install --with-deps chromium

COPY backend /app/backend

EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.main.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
