#!/bin/sh
# The Worker token arrives as a file (compose secret) and is exported only inside this process.
set -eu
RUNTIME_WORKER_TOKEN="$(cat /run/secrets/worker_token)"
export RUNTIME_WORKER_TOKEN
cd /app/image-service
exec /app/image-service/.venv/bin/python -m image_service.worker
