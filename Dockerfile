FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dipendenze prima del codice per sfruttare la cache dei layer.
COPY pyproject.toml README.md ./
COPY core ./core
COPY apps ./apps
COPY data ./data
COPY docs ./docs
COPY scripts ./scripts
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 1000 opennews \
    && chown -R opennews:opennews /app

USER opennews

EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
