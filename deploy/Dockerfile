# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

ARG TORCH_BACKEND=cpu
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy HF_HOME=/cache/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.10.0
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY src/ ./src/
COPY website/ ./website/
COPY extension/frontend/ ./extension/frontend/
COPY artifacts/ ./artifacts/
COPY deploy/ ./deploy/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev \
    && if [ "$TORCH_BACKEND" = "cu128" ]; then \
         uv pip install --python /app/.venv/bin/python --torch-backend=cu128 \
           --reinstall-package torch 'torch==2.8.0'; \
       elif [ "$TORCH_BACKEND" != "cpu" ]; then exit 1; fi \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /cache/huggingface && chown -R app:app /cache \
    && chmod +x /app/deploy/entrypoint.sh
USER app
EXPOSE 8001
HEALTHCHECK --interval=20s --timeout=5s --start-period=15m --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/ready', timeout=4)"
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "website.api.server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
