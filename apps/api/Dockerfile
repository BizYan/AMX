# =============================================================================
# Consultant AI Workbench - API Dockerfile
# =============================================================================

FROM python:3.12-slim AS production

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/app ./app
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./alembic.ini

RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup appuser

USER appuser

EXPOSE 8000

ENV PATH="/app/.venv/bin:$PATH"

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
