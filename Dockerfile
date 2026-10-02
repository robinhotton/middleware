# =============================================================================
# Stage 1 : Build des dependances
# =============================================================================
FROM python:3.13-slim AS builder

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# =============================================================================
# Stage 2 : Image runtime minimale
# =============================================================================
FROM python:3.13-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl=8.* && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /sbin/nologin appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --chown=appuser:appuser run.py gunicorn.conf.py ./
COPY --chown=appuser:appuser src/ ./src/

RUN mkdir -p /app/logs && chown appuser:appuser /app/logs

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f "http://localhost:8000/health" || exit 1

CMD ["gunicorn", "src.main:app", "--config", "gunicorn.conf.py"]
