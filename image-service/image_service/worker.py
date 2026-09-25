"""Independent HTTP-polling Worker with lease heartbeats and durable receipt replay."""

import argparse
import hashlib
import os
import struct
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from image_service.contracts import validate_contract
from image_service.journal import CorruptJournal, Journal


class Api:
    def __init__(self, base: str, token: str):
        parts = urlsplit(base)
        if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("T05 development Worker requires loopback HTTP")
        if parts.username or parts.password or parts.query or parts.fragment or len(token) < 32:
            raise ValueError("Invalid Worker connection configuration")
        self.client = httpx.Client(
            base_url=base.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(10, connect=5),
            trust_env=False,
            follow_redirects=False,
        )

    def call(self, method, path, *, lease=None, body=None, data=None, binary=False):
        headers = {"X-Lease-Token": lease} if lease else {}
        if data is not None:
            headers["Content-Type"] = "application/octet-stream"
        with self.client.stream(method, path, headers=headers, json=body, content=data) as response:
            response.raise_for_status()
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > 67108864:
                    raise ValueError("Worker response exceeds transport budget")
            if response.status_code == 204:
                return None
            if binary:
                return bytes(chunks)
            import json

            return json.loads(chunks)

    def close(self):
        self.client.close()


def crash(point: str, fixture: bool):
    if fixture and os.getenv("T05_TEST_CRASH_AT") == point:
        os._exit(91)


def failure(request, code, retryable=True):
    return {
        "schema_version": 1,
        "event_type": "image.task.failed.v1",
        "event_id": uuid.uuid4().hex,
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "correlation_id": request["correlation_id"],
        "error": {
            "code": code,
            "safe_message": "Worker operation unavailable",
            "retryable": retryable,
        },
        "duration_ms": 0,
    }


def process(api: Api, request: dict, lease: str, fixture: bool) -> dict:
    if not fixture:
        code = "PROVIDER_UNAVAILABLE" if request["feature_type"] == "SCENE" else "GENERATION_FAILED"
        return failure(request, code)
    if request["template_snapshot"]["output_preset"]["id"] != "t05_transport_fixture":
        return failure(request, "INVALID_CONTRACT", False)
    blobs = {}
    for field in ("product_asset", "product_alpha_asset", "gift_asset"):
        if field not in request:
            continue
        asset = request[field]
        if not asset["object_key"].startswith("fixtures/"):
            return failure(request, "INVALID_ASSET", False)
        blobs[field] = api.call(
            "GET",
            f"/internal/v1/work/{request['attempt_id']}/assets/{asset['asset_id']}",
            lease=lease,
            binary=True,
        )
        if hashlib.sha256(blobs[field]).hexdigest() != asset["sha256"]:
            return failure(request, "INVALID_ASSET", False)
    # Explicit transport fixture only: no compositing, AI, or product-image promise.
    image = blobs["product_asset"]
    if image[:8] != b"\x89PNG\r\n\x1a\n" or len(image) < 24:
        return failure(request, "INVALID_ASSET", False)
    width, height = struct.unpack(">II", image[16:24])
    result = api.call(
        "PUT", f"/internal/v1/work/{request['attempt_id']}/outputs/0", lease=lease, data=image
    )
    if (result["width"], result["height"]) != (width, height):
        return failure(request, "OUTPUT_VALIDATION_FAILED")
    crash("after-output", fixture)
    return {
        "schema_version": 1,
        "event_type": "image.task.completed.v1",
        "event_id": uuid.uuid4().hex,
        "task_id": request["task_id"],
        "attempt_id": request["attempt_id"],
        "correlation_id": request["correlation_id"],
        "artifacts": [{"ordinal": 0, "kind": "COMPOSITE", **result}],
        "duration_ms": 0,
        "background_generation": None,
    }


def flush(api: Api, journal: Journal, fixture: bool) -> bool:
    found = False
    for path, entry in journal.pending():
        found = True
        result = api.call(
            "POST",
            f"/internal/v1/work/{entry['attempt']}/receipt",
            lease=entry["lease"],
            body=entry["receipt"],
        )
        if result.get("disposition") not in {"APPLIED", "IGNORED", "REJECTED"}:
            raise ValueError("Invalid receipt acknowledgement")
        crash("after-ack", fixture)
        journal.acknowledge(path)
    return found


def run_once(api: Api, journal: Journal, fixture=False) -> bool:
    if flush(api, journal, fixture):
        return True
    claim = api.call("POST", "/internal/v1/work/claim")
    if claim is None:
        return False
    request = claim["request"]
    lease = claim["lease_token"]
    if validate_contract("task-request", request):
        raise ValueError("Invalid claimed task contract")
    crash("after-claim", fixture)
    stopped = threading.Event()
    lost = threading.Event()
    started = time.monotonic()

    def heartbeat():
        interval = max(0.25, claim["lease_seconds"] / 3)
        while not stopped.wait(interval):
            if time.monotonic() - started > 600:
                lost.set()
                return
            try:
                api.call(
                    "POST", f"/internal/v1/work/{request['attempt_id']}/heartbeat", lease=lease
                )
            except (httpx.HTTPError, ValueError):
                lost.set()
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        try:
            receipt = process(api, request, lease, fixture)
        except (httpx.HTTPError, ValueError, KeyError):
            receipt = failure(request, "GENERATION_FAILED")
        receipt["duration_ms"] = int((time.monotonic() - started) * 1000)
        if lost.is_set():
            raise RuntimeError("Lease lost; output cannot be confirmed")
        contract = (
            "task-completed" if receipt["event_type"].endswith("completed.v1") else "task-failed"
        )
        if validate_contract(contract, receipt):
            raise ValueError("Invalid generated receipt")
        journal.save(request["attempt_id"], lease, receipt)
        crash("after-journal", fixture)
        flush(api, journal, fixture)
    finally:
        stopped.set()
        thread.join(timeout=12)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--fixture", action="store_true", help="Synthetic transport acceptance only"
    )
    args = parser.parse_args()
    api = Api(os.environ["WORKER_API_URL"], os.environ["RUNTIME_WORKER_TOKEN"])
    try:
        with Journal(Path(os.environ["WORKER_JOURNAL_ROOT"])) as journal:
            delay = 1
            while True:
                try:
                    worked = run_once(api, journal, args.fixture)
                    delay = 1
                    if args.once:
                        return
                    if not worked:
                        time.sleep(1)
                except CorruptJournal:
                    raise SystemExit("Worker stopped: inspect private receipt journal") from None
                except (httpx.HTTPError, ValueError, RuntimeError) as error:
                    # Never print URLs, bearer/lease tokens, prompt text, or server response bodies.
                    print(f"worker_retry error_type={type(error).__name__}", flush=True)
                    if args.once:
                        raise SystemExit(1) from None
                    time.sleep(delay)
                    delay = min(delay * 2, 30)
    finally:
        api.close()


if __name__ == "__main__":
    main()
