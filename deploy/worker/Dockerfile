# Python generation Worker. Build context: repository root.
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
# Noto Sans CJK (SIL OFL) for the Chinese text overlay.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.5
WORKDIR /app
COPY contracts contracts
COPY image-service/pyproject.toml image-service/uv.lock image-service/
RUN cd image-service && uv sync --frozen --no-dev --no-install-project
COPY image-service/image_service image-service/image_service
COPY deploy/worker/entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
