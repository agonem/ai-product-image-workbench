"""Independent HTTP-polling Worker with lease heartbeats and durable receipt replay."""

import argparse
import hashlib
import os
import ssl
import struct
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from image_service.background import BackgroundError
from image_service.contracts import validate_contract
from image_service.journal import CorruptJournal, Journal


class Api:
    def __init__(self, base: str, token: str, *, environment="development", ca_file=None):
        parts = urlsplit(base)
        if parts.scheme != "https" and not (
            environment == "development"
            and parts.scheme == "http"
            and parts.hostname in {"127.0.0.1", "::1", "localhost"}
        ):
            raise ValueError("Worker requires HTTPS outside development loopback")
        if parts.username or parts.password or parts.query or parts.fragment or len(token) < 32:
            raise ValueError("Invalid Worker connection configuration")
        self.client = httpx.Client(
            base_url=base.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(10, connect=5),
            trust_env=False,
            follow_redirects=False,
            verify=ssl.create_default_context(cafile=ca_file),
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
    version = request.get("schema_version", 1)
    return {
        "schema_version": version,
        "event_type": f"image.task.failed.v{version}",
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


def process(
    api: Api,
    request: dict,
    lease: str,
    fixture: bool,
    *,
    cancelled=None,
    provider_config=None,
    text_provider_config=None,
) -> dict:
    if request.get("schema_version") == 4:
        if fixture:
            return failure(request, "INVALID_CONTRACT", False)
        from image_service import generation, providers, typeset
        from image_service.background_config import config_from_mapping, load_config

        try:
            if "base_image" in request or (
                request.get("keep_original") and not request.get("gift_reshoot")
            ):
                # Text-only re-render of a stored model output, or text on the product image
                # itself (ADR-20261008-G): no provider is contacted. A white gift card on the
                # original picture still has its gift re-shot by the model (ADR-20261009-N).
                return generation.process_generation(api, request, lease, None)
            config = (
                config_from_mapping(provider_config)
                if provider_config is not None
                else load_config()
            )
            # Agent rewrites use the separately bound text model (ADR-20261008-L).
            text_config = (
                config_from_mapping(text_provider_config) if text_provider_config else None
            )
            # The admin-chosen provider type selects OpenRouter, OpenAI or Gemini formats.
            with providers.model_adapter(config) as adapter:
                return generation.process_generation(
                    api, request, lease, adapter, cancelled=cancelled, text_config=text_config
                )
        except typeset.TextOverflow:
            return failure(request, "TEXT_OVERFLOW", False)
        except typeset.FontUnavailable:
            # A deployment problem, not the user's input: retry works once it is fixed.
            receipt = failure(request, "GENERATION_FAILED", True)
            receipt["error"]["safe_message"] = "TEXT_FONT_UNAVAILABLE"
            return receipt
    if request.get("schema_version") in (2, 3):
        # Scene v2/v3 were replaced by v4: a legacy batch fails visibly, never spends a call.
        return failure(request, "INVALID_CONTRACT", False)
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
    if validate_contract(
        "generation-v4-request"
        if request.get("schema_version") == 4
        else "scene-v3-request"
        if request.get("schema_version") == 3
        else "scene-request"
        if request.get("schema_version") == 2
        else "task-request",
        request,
    ):
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
            receipt = process(
                api,
                request,
                lease,
                fixture,
                cancelled=lost.is_set,
                provider_config=claim.get("provider_config"),
                text_provider_config=claim.get("text_provider_config"),
            )
        except BackgroundError as error:
            receipt = failure(
                request, "PROVIDER_UNAVAILABLE", error.retryable and not error.ambiguous
            )
            # Stable allowlisted diagnostics only; never provider bodies, URLs or credentials.
            safe_codes = {
                "CONFIGURATION",
                "UNSUPPORTED_CAPABILITY",
                "INVALID_INPUT",
                "INVALID_OUTPUT",
                "INVALID_RESPONSE",
                "RESPONSE_BUDGET",
                "PROVIDER_NETWORK",
            }
            safe_codes.update(f"PROVIDER_HTTP_{status}" for status in range(400, 600))
            # The magic-wand rewrite reports the same codes with a TEXT_ prefix (ADR-20261008-L),
            # the look-first analysis with VISION_ (ADR-20261009-P).
            base = list(safe_codes)
            safe_codes.update({prefix + code for code in base for prefix in ("TEXT_", "VISION_")})
            if error.code in safe_codes:
                receipt["error"]["safe_message"] = error.code
            if error.code in {"INVALID_OUTPUT", "INVALID_RESPONSE", "RESPONSE_BUDGET"}:
                receipt["error"]["code"] = "OUTPUT_VALIDATION_FAILED"
        except (httpx.HTTPError, ValueError, KeyError):
            receipt = failure(request, "GENERATION_FAILED")
        receipt["duration_ms"] = int((time.monotonic() - started) * 1000)
        if lost.is_set():
            raise RuntimeError("Lease lost; output cannot be confirmed")
        contract = (
            "generation-v4-"
            if request.get("schema_version") == 4
            else "scene-v3-"
            if request.get("schema_version") == 3
            else "scene-"
            if request.get("schema_version") == 2
            else "task-"
        ) + ("completed" if ".completed." in receipt["event_type"] else "failed")
        if validate_contract(contract, receipt):
            raise ValueError("Invalid generated receipt")
        journal.save(request["attempt_id"], lease, receipt)
        crash("after-journal", fixture)
        flush(api, journal, fixture)
    finally:
        stopped.set()
        thread.join(timeout=12)
    return True


MAX_CONCURRENCY = 8


def concurrency() -> int:
    """WORKER_CONCURRENCY: tasks processed side by side (default 1, at most 8).

    Each slot is an independent claim loop with its own receipt journal; the provider quota and
    machine capacity decide a sensible value (ADR-20260930-F capacity check)."""
    raw = os.getenv("WORKER_CONCURRENCY", "1").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_CONCURRENCY:
        raise SystemExit(f"WORKER_CONCURRENCY must be 1..{MAX_CONCURRENCY}")
    return int(raw)


def journal_root(root: Path, slot: int) -> Path:
    # Slot 0 keeps the original directory, so receipts journaled before slots existed replay.
    return root if slot == 0 else root / f"slot-{slot}"


def connect() -> Api:
    return Api(
        os.environ["WORKER_API_URL"],
        os.environ["RUNTIME_WORKER_TOKEN"],
        environment=os.getenv("APP_ENV", "development"),
        ca_file=os.getenv("WORKER_CA_FILE"),
    )


def serve(slot: int, fixture: bool, stop: threading.Event, failures: list):
    """One claim loop of a multi-slot Worker; a corrupt journal stops every slot."""
    try:
        api = connect()
        try:
            with Journal(journal_root(Path(os.environ["WORKER_JOURNAL_ROOT"]), slot)) as journal:
                delay = 1
                while not stop.is_set():
                    try:
                        worked = run_once(api, journal, fixture)
                        delay = 1
                        if not worked:
                            stop.wait(1)
                    except (httpx.HTTPError, ValueError, RuntimeError) as error:
                        print(
                            f"worker_retry slot={slot} error_type={type(error).__name__}",
                            flush=True,
                        )
                        stop.wait(delay)
                        delay = min(delay * 2, 30)
        finally:
            api.close()
    except CorruptJournal:
        failures.append("journal")
        stop.set()
    except Exception as error:  # noqa: BLE001 - reported by type only, then every slot stops
        print(f"worker_stopped slot={slot} error_type={type(error).__name__}", flush=True)
        failures.append("slot")
        stop.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--fixture", action="store_true", help="Synthetic transport acceptance only"
    )
    args = parser.parse_args()
    slots = 1 if args.once else concurrency()
    if slots > 1:
        stop, failures = threading.Event(), []
        threads = [
            threading.Thread(target=serve, args=(slot, args.fixture, stop, failures), daemon=True)
            for slot in range(slots)
        ]
        for thread in threads:
            thread.start()
        try:
            while any(thread.is_alive() for thread in threads):
                for thread in threads:
                    thread.join(timeout=1)
        except KeyboardInterrupt:
            stop.set()
        if "journal" in failures:
            raise SystemExit("Worker stopped: inspect private receipt journal")
        if failures:
            raise SystemExit(1)
        return
    api = connect()
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
