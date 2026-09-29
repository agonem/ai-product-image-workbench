#!/usr/bin/env bash
# Post-deployment check on the server. Makes no model call and changes no data.
set -euo pipefail
cd "$(dirname "$0")"
set -a
. ./.env
set +a
BASE="https://${SERVER_IP}:${HTTPS_PORT}"
CA=workbench-ca.crt
fail() { echo "FAIL: $*" >&2; exit 1; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

docker compose ps
# Java needs up to a minute after "up"; wait until the API answers through nginx.
for _ in $(seq 60); do
  [ "$(status --cacert "$CA" "$BASE/api/v1/local-auth/me")" = 401 ] && break
  sleep 3
done
page=$(curl -fsS --cacert "$CA" "$BASE/") || fail "page is not reachable over trusted HTTPS: $BASE/"
grep -q '<div id="app">' <<<"$page" || fail "unexpected page content"
echo "ok   page over HTTPS with the internal CA"

code=$(status --cacert "$CA" "$BASE/api/v1/local-auth/me")
[ "$code" = 401 ] || fail "API through nginx should answer 401 without login, got $code (docker compose logs business)"
echo "ok   nginx -> Java over verified TLS"

code=$(status --cacert "$CA" -X POST "$BASE/internal/v1/work/claim")
[ "$code" = 404 ] || fail "Worker endpoints must not be reachable from outside, got $code"
echo "ok   internal Worker endpoints are not exposed"

code=$(status "http://${SERVER_IP}:${HTTP_PORT}/")
[ "$code" = 301 ] || fail "HTTP should redirect to HTTPS, got $code"
echo "ok   HTTP redirects to HTTPS"

face=$(docker compose exec -T -w /app/image-service worker /app/image-service/.venv/bin/python -c '
import os
from PIL import ImageFont
font = ImageFont.truetype(
    os.environ["GENERATION_TEXT_FONT"], 20, index=int(os.environ["GENERATION_TEXT_FONT_INDEX"])
)
print(" ".join(font.getname()))')
[[ "$face" == *"CJK SC"* ]] || fail "worker text font is '$face', expected Noto Sans CJK SC"
echo "ok   worker font: $face"

# After Java is ready the Worker's next poll (backoff at most 30 s) must succeed.
ready_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sleep 35
if docker compose logs --since "$ready_at" worker | grep -q worker_retry; then
  fail "worker cannot reach the business service (docker compose logs worker)"
fi
echo "ok   worker is polling the business service"

# Public model endpoints, direct (no key needed to connect). Only warn: only the endpoint in use
# has to be reachable, and a model marked "use proxy" goes through the proxy set in the pages.
docker compose exec -T -w /app/image-service worker /app/image-service/.venv/bin/python -c '
import httpx
for url in ("https://openrouter.ai/api/v1/models", "https://api.openai.com/v1/models",
            "https://generativelanguage.googleapis.com/v1beta/models"):
    host = url.split("/")[2]
    try:
        status = httpx.get(url, trust_env=False, timeout=20).status_code
        print("ok   worker reaches", host, "(HTTP %d)" % status)
    except httpx.HTTPError as error:
        print("WARN worker cannot reach", host, "(" + type(error).__name__ + ");",
              "directly; set the proxy in the model settings page and tick use proxy")' || true

echo "PASS: deployment checks. Next: log in, configure the provider, generate one image per entry."
