# syntax=docker/dockerfile:1
# -----------------------------------------------------------------------------
# Imagen del agente (API y línea de comandos). Dos etapas:
#   1. builder: instala dependencias con uv en un entorno virtual.
#   2. runtime: solo Python y el entorno; usuario sin privilegios.
# -----------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY vendor vendor
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src src
COPY definitions definitions
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app definitions definitions
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8100
# Aplica migraciones y arranca. En Kubernetes las migraciones irían en un Job aparte.
CMD ["sh", "-c", "agente migrate && uvicorn agente.api.app:app --host 0.0.0.0 --port 8100 --proxy-headers"]
