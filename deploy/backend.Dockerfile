FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Playwright's bundled Node needs libatomic; slim images do not ship it, and
# `playwright install --with-deps` only covers Chromium OS libs — not this one.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/main/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && playwright install --with-deps chromium

COPY backend /app/backend

EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.main.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
