# =============================================================================
# Consultant AI Workbench - Worker Dockerfile
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

ENV PATH="/app/.venv/bin:$PATH"

CMD ["arq", "app.workers.queue.WorkerSettings"]
