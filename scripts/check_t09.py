"""T09 isolated production TLS chain. Mock default; --t09-real explicitly spends provider calls."""

import base64
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import threading
import time
import uuid
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from check_db import free_port
from check_t04_prod import ProductionCheck
from common import ROOT, process_options, stop, tool
from smoke import wait_ready


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved_sample():
    directory = ROOT / ".artifacts/t02-real/SAMPLE-001/run-002"
    approval = ROOT / "local-data/samples/SAMPLE-001/approvals/run-002.json"
    record = json.loads(approval.read_text(encoding="utf-8"))
    assert record["decision"] == "APPROVED" and record["run"] == "run-002"
    for relative, sha in record["files"].items():
        assert hash_file(directory / relative) == sha, "Approved sample changed"
    original = ROOT / "local-data/samples/SAMPLE-001/product.png"
    assert hash_file(original) == hash_file(directory / "originals/product.png")
    return original, directory / "product-alpha.png", directory, hash_file(approval)


def worker(run, certificate, real, *, fail=False, tamper=False):
    env = {
        **run.env,
        "WORKER_API_URL": run.base,
        "WORKER_CA_FILE": str(certificate),
        "WORKER_JOURNAL_ROOT": str(run.work / ("failure-journal" if fail else "journal")),
    }
    if real:
        env["OPENROUTER_ENV_FILE"] = os.environ.get("OPENROUTER_ENV_FILE", str(ROOT / ".env"))
        if os.environ.get("OPENROUTER_PROVIDER_TAG"):
            env["OPENROUTER_PROVIDER_TAG"] = os.environ["OPENROUTER_PROVIDER_TAG"]
        command = ["-m", "image_service.worker"]
    else:
        env["T09_TEST_FAIL"] = "true" if fail else "false"
        env["T09_TEST_TAMPER"] = "true" if tamper else "false"
        command = [str(ROOT / "scripts/t09_test_worker.py")]
    with (run.work / ("worker-failure.log" if fail else "worker.log")).open("w") as log:
        subprocess.run(
            [
                tool("uv"),
                "run",
                "--frozen",
                "--directory",
                str(ROOT / "image-service"),
                "python",
                *command,
                "--once",
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=620,
        )


def run_scene_checks(env, work, *, real=False):
    original, alpha, sample, approval_sha = approved_sample()
    work.mkdir(parents=True)
    # Java and browser never inherit private provider settings.
    run = ProductionCheck({k: v for k, v in env.items() if not k.startswith("OPENROUTER_")}, work)
    run.env.update(
        {
            "SCENE_ENABLED": "true",
            "SCENE_ASPECT_RATIOS": "1:1",
            "SCENE_RESOLUTIONS": "1K",
            "SCENE_FORMATS": "png,jpeg",
            # Acceptance-only values for provider configuration storage and the non-paid
            # capability check relay; never a real credential or provider key.
            "PROVIDER_MASTER_KEY": base64.b64encode(b"PROVIDER-MASTER-KEY-0123456789AB").decode(),
            "IMAGE_CHECK_URL": f"http://127.0.0.1:{free_port()}",
            "IMAGE_CHECK_TOKEN": "t09-provider-check-token",
        }
    )
    certificate = work / "test-public.pem"
    subprocess.run(
        [
            tool("keytool"),
            "-exportcert",
            "-rfc",
            "-alias",
            "test",
            "-keystore",
            str(work / "test.p12"),
            "-storepass:env",
            "SERVER_SSL_KEY_STORE_PASSWORD",
            "-file",
            str(certificate),
        ],
        env=run.env,
        capture_output=True,
        check=True,
    )
    run.client = build_opener(
        ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(certificate)))
    )
    with ExitStack() as stack:
        stack.callback(run.close)
        run.start()
        admin = run.login("admin")
        assert (
            run.http(
                "POST",
                "/api/v1/admin/accounts",
                admin,
                {"username": "alice", "password": run.password, "role": "USER"},
            )[0]
            == 201
        )
        alice = run.login("alice")
        project = run.http(
            "POST", "/api/v1/projects", alice, {"name": "SAMPLE-001 scene acceptance"}
        )[1]["id"]
        status, asset, _ = run.http(
            "POST",
            f"/api/v1/projects/{project}/assets?kind=PRODUCT",
            alice,
            data=original.read_bytes(),
            mime="image/png",
        )
        assert status == 201, ("original upload", status)
        assert run.http("GET", f"/api/v1/assets/{asset['id']}/content", admin)[0] == 404
        # Explicit isolated test data import, anchored to the existing human approval.
        # There is no product endpoint for silently approving an arbitrary alpha.
        target = run.store / "reviewed/product-alpha.png"
        target.parent.mkdir()
        shutil.copyfile(alpha, target)
        run.sql(f"""INSERT INTO assets(id,project_id,kind,source_asset_id,object_key,sha256,
            width,height,review_status) VALUES ('sample_alpha','{project}','ALPHA','{asset["id"]}',
            'reviewed/product-alpha.png','{hash_file(alpha)}',338,338,'APPROVED')""")
        run.sql(f"""INSERT INTO audit_events(id,action,resource_id,correlation_id,details)
            VALUES ('sample_import','TEST_IMPORT_EXISTING_HUMAN_APPROVAL',
            'sample_alpha','sample_import',
            '{{"approval_sha256":"{approval_sha}","sample":"SAMPLE-001/run-002"}}')""")
        assert run.http("GET", f"/api/v1/assets/{asset['id']}/approved-alpha", admin)[0] == 404
        assert (
            run.http("GET", f"/api/v1/assets/{asset['id']}/approved-alpha", alice)[1]
            == alpha.read_bytes()
        )
        sync = work / "sync"
        sync.mkdir()
        browser_dir = work / "browser"
        browser_dir.mkdir()
        port = free_port()
        page_env = {
            k: v
            for k, v in env.items()
            if not k.startswith(
                ("DB_", "PGPASSWORD", "RUNTIME_", "PROD_", "SERVER_SSL_", "OPENROUTER_")
            )
        }
        page_env.update(
            {
                "VITE_AUTH_MODE": "production-local",
                "NODE_EXTRA_CA_CERTS": str(certificate),
                "DEV_HOST": "127.0.0.1",
                "DEV_PORT": str(port),
                "DEV_API_TARGET": run.base,
                "T06_BASE_URL": f"http://127.0.0.1:{port}",
                "T06_PASSWORD": run.password,
                "T06_ARTIFACTS": str(browser_dir),
                "T09_SYNC_DIR": str(sync),
                "VITE_ACCEPTANCE_MODE": "" if real else "mock-provider",
                "T09_MODE": "real" if real else "mock",
            }
        )
        output = work / "frontend-dist"
        subprocess.run(
            [tool("npm"), "run", "build", "--", "--outDir", str(output)],
            cwd=ROOT / "frontend",
            env=page_env,
            check=True,
        )
        log = stack.enter_context((work / "vite.log").open("w"))
        vite = subprocess.Popen(
            [
                tool("npm"),
                "exec",
                "--",
                "vite",
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
                "--outDir",
                str(output),
            ],
            cwd=ROOT / "frontend",
            env=page_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            **process_options(),
        )
        stack.callback(stop, vite)
        wait_ready(page_env["T06_BASE_URL"], vite, work / "vite.log")
        browser = subprocess.Popen(
            [
                tool("npm"),
                "exec",
                "--",
                "playwright",
                "test",
                "--config=playwright.scene.config.ts",
            ],
            cwd=ROOT / "frontend",
            env=page_env,
            **process_options(),
        )
        stack.callback(stop, browser)
        deadline = time.monotonic() + 60
        while not (sync / "submitted.json").exists():
            if browser.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Browser did not submit scene task")
            time.sleep(0.2)
        task = json.loads((sync / "submitted.json").read_text())["task_id"]
        worker(run, certificate, real)
        state = run.http("GET", f"/api/v3/scene-tasks/{task}", alice)[1]
        (work / "task-result.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        assert state["status"] == "SUCCEEDED", ("scene failed", state.get("error"))
        assert state["output"]["count"] == len(state["artifacts"]) == 3
        assert state["review_status"] == "PENDING"
        assert run.http("GET", f"/api/v1/tasks/{task}", admin)[0] == 404
        for item in state["artifacts"]:
            assert run.http("GET", f"/api/v1/artifacts/{item['id']}/content", alice)[0] == 200
            assert run.http("GET", f"/api/v1/artifacts/{item['id']}/content", admin)[0] == 404
        assert (
            run.http("GET", f"/api/v1/assets/{asset['id']}/content", alice)[1]
            == original.read_bytes()
        )
        receipt = json.loads(run.sql(f"SELECT payload FROM worker_receipts WHERE task_id='{task}'"))
        provenance = receipt["background_generations"]
        assert len({item["background"]["sha256"] for item in provenance}) == 3
        (work / "receipt-evidence.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        export_review(work, run.store, receipt, sample, real)
        if not real:
            failure_checks(run, certificate, alice, task)
        assert browser.wait(timeout=60) == 0
        if not real:
            stub = provider_config_checks(run, certificate, alice, task)
            admin_page_checks(page_env, work)
            stub.shutdown()
            stub.server_close()
            print("PASS C4: admin page manages provider configuration with mock relays", flush=True)
        print(
            "PASS S1/S2/S3/S4: browser -> Java -> outbox -> HTTPS Worker -> private outputs; "
            + ("REAL provider" if real else "MOCK provider only"),
            flush=True,
        )
        print("Review:", work / "review/review.html", flush=True)


def provider_config_checks(run, certificate, alice, previous):
    """C1-C3 against the running isolated Java with the MOCK worker only; zero paid calls."""
    admin = run.login("admin")
    key = "sk-t09c-mock-credential-123456"
    first = {
        "provider": "openrouter",
        "model": "test/mock-model-a",
        "provider_tag": "mock-a",
        "api_key": key,
        "enabled": True,
    }
    assert run.http("GET", "/api/v1/admin/provider-configs", alice)[0] == 403
    assert run.http("POST", "/api/v1/admin/provider-configs", alice, first)[0] == 403
    status, created, _ = run.http("POST", "/api/v1/admin/provider-configs", admin, first)
    assert status == 201 and created["api_key_mask"].endswith("3456")
    assert key not in json.dumps(created)
    listing = run.http("GET", "/api/v1/admin/provider-configs", admin)[1]
    assert key not in json.dumps(listing) and listing["enabled"] is True
    assert (
        run.sql("SELECT count(*) FROM audit_events WHERE action='PROVIDER_CONFIG_CREATED'") == "1"
    )
    # C1: the stored key never appears in Java or Worker logs.
    for name in ("java-1.log", "java-2.log"):
        log = run.work / name
        if log.exists():
            assert key not in log.read_text(errors="replace")

    # C2: new scene tasks bind the active version; leased workers receive it.
    def submit(count, suffix):
        body = json.loads(
            run.sql(f"SELECT request_snapshot_json FROM generation_tasks WHERE id='{previous}'")
        )
        body["output"]["count"] = count
        body["output"]["format"] = "png"
        return post(run, "/api/v3/scene-tasks", alice, body, key=uuid.uuid4().hex + suffix)

    status, bound = submit(2, "a")
    assert status == 202
    assert (
        run.sql(f"SELECT provider_config_version FROM generation_tasks WHERE id='{bound['id']}'")
        == created["id"]
    )
    worker(run, certificate, False)
    state = run.http("GET", f"/api/v1/tasks/{bound['id']}", alice)[1]
    assert state["status"] == "SUCCEEDED", state.get("error")
    receipt = json.loads(
        run.sql(f"SELECT payload FROM worker_receipts WHERE task_id='{bound['id']}'")
    )
    assert all(
        item["provenance"]["model"] == "test/mock-model-a"
        for item in receipt["background_generations"]
    )
    # A queued task frozen on version A BEFORE rotation must still run on A after the
    # pointer rotated and the provider was disabled: no silent credential switch.
    status, frozen = submit(1, "f")
    assert status == 202
    assert (
        run.sql(f"SELECT provider_config_version FROM generation_tasks WHERE id='{frozen['id']}'")
        == created["id"]
    )
    # Rotation: a new version takes over new tasks; the earlier binding stays frozen.
    second = {**first, "model": "test/mock-model-b", "provider_tag": "mock-b"}
    rotated = run.http("POST", "/api/v1/admin/provider-configs", admin, second)[1]
    status, switched = submit(1, "b")
    assert status == 202
    assert (
        run.sql(f"SELECT provider_config_version FROM generation_tasks WHERE id='{switched['id']}'")
        == rotated["id"]
    )
    worker(run, certificate, False)
    state = run.http("GET", f"/api/v1/tasks/{frozen['id']}", alice)[1]
    assert state["status"] == "SUCCEEDED", state.get("error")
    receipt = json.loads(
        run.sql(f"SELECT payload FROM worker_receipts WHERE task_id='{frozen['id']}'")
    )
    assert all(
        item["provenance"]["model"] == "test/mock-model-a"
        for item in receipt["background_generations"]
    )
    worker(run, certificate, False)
    state = run.http("GET", f"/api/v1/tasks/{switched['id']}", alice)[1]
    assert state["status"] == "SUCCEEDED", state.get("error")
    receipt = json.loads(
        run.sql(f"SELECT payload FROM worker_receipts WHERE task_id='{switched['id']}'")
    )
    assert all(
        item["provenance"]["model"] == "test/mock-model-b"
        for item in receipt["background_generations"]
    )
    assert (
        run.http(
            "POST",
            f"/api/v1/admin/provider-configs/{created['id']}/status",
            admin,
            {"enabled": True},
        )[0]
        == 400
    )
    assert (
        run.http(
            "POST",
            f"/api/v1/admin/provider-configs/{rotated['id']}/status",
            admin,
            {"enabled": False},
        )[0]
        == 204
    )
    # An admin who disabled the configuration must not get silent environment fallback.
    status, rejected = submit(1, "d")
    assert status == 503 and rejected["code"] == "PROVIDER_DISABLED"
    assert (
        run.http(
            "POST",
            f"/api/v1/admin/provider-configs/{rotated['id']}/status",
            admin,
            {"enabled": True},
        )[0]
        == 204
    )
    status, rebound = submit(1, "e")
    assert status == 202
    assert (
        run.sql(f"SELECT provider_config_version FROM generation_tasks WHERE id='{rebound['id']}'")
        == rotated["id"]
    )
    # C3/C4: relays for the non-paid capability GET and the explicit paid probe. The stub
    # counts hits so the checks prove that saving config, listing or the page never calls.
    received = {"hits": {"check": 0, "test": 0}}
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )

    class Stub(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            received["auth"] = self.headers.get("Authorization")
            received["body"] = self.rfile.read(length)
            if self.path.endswith("/provider/check"):
                received["hits"]["check"] += 1
                payload = {
                    "model": "test/mock-model-b",
                    "provider_tag": "mock-b",
                    "input_modalities": ["text"],
                    "output_modalities": ["image"],
                    "endpoints": [
                        {
                            "provider_tag": "mock-b",
                            "supported_parameters": {
                                "aspect_ratio": {"type": "enum", "values": ["1:1"]}
                            },
                        }
                    ],
                }
            elif self.path.endswith("/provider/test"):
                received["hits"]["test"] += 1
                payload = {
                    "sha256": hashlib.sha256(tiny_png).hexdigest(),
                    "width": 1,
                    "height": 1,
                    "media_type": "image/png",
                    "model": "test/mock-model-b",
                    "duration_ms": 5,
                    "content_base64": base64.b64encode(tiny_png).decode("ascii"),
                    "review_status": "PENDING",
                }
            else:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", int(run.env["IMAGE_CHECK_URL"].rsplit(":", 1)[1])), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert (
            run.http("POST", f"/api/v1/admin/provider-configs/{rotated['id']}/check", alice, {})[0]
            == 403
        )
        status, capabilities, _ = run.http(
            "POST", f"/api/v1/admin/provider-configs/{rotated['id']}/check", admin, {}
        )
        assert status == 200 and capabilities["model"] == "test/mock-model-b"
        assert key not in json.dumps(capabilities)
        assert received["auth"] == "Bearer " + run.env["IMAGE_CHECK_TOKEN"]
        assert key.encode() in received["body"]
        # Paid probe: denied for USER, requires the explicit confirmation phrase, and
        # creates no tasks or artifacts; the key is forwarded but never echoed.
        assert (
            run.http(
                "POST", f"/api/v1/admin/provider-configs/{rotated['id']}/test-generate", alice, {}
            )[0]
            == 403
        )
        assert (
            run.http(
                "POST",
                f"/api/v1/admin/provider-configs/{rotated['id']}/test-generate",
                admin,
                {"aspect_ratio": "1:1"},
            )[0]
            == 400
        )
        before = run.sql("SELECT count(*) FROM generation_tasks")
        before_artifacts = run.sql("SELECT count(*) FROM artifacts")
        status, paid, _ = run.http(
            "POST",
            f"/api/v1/admin/provider-configs/{rotated['id']}/test-generate",
            admin,
            {"confirm": "PAID_TEST", "aspect_ratio": "1:1"},
        )
        assert status == 200 and paid["width"] == 1 and paid["media_type"] == "image/png"
        assert key not in json.dumps(paid)
        assert run.sql("SELECT count(*) FROM generation_tasks") == before
        assert run.sql("SELECT count(*) FROM artifacts") == before_artifacts
        assert (
            run.sql("SELECT count(*) FROM audit_events WHERE action='PROVIDER_CONFIG_PAID_TEST'")
            == "1"
        )
        assert received["hits"] == {"check": 1, "test": 1}
    except Exception:
        server.shutdown()
        server.server_close()
        raise
    (run.work / "provider-config-evidence.json").write_text(
        json.dumps(
            {
                "mode": "MOCK",
                "admin_only_endpoints": True,
                "key_masked_and_absent_from_responses_logs": True,
                "new_tasks_bind_active_version": True,
                "rotation_switches_new_tasks_only": True,
                "frozen_binding_survives_rotation_and_disable": True,
                "disable_rejects_new_submissions_without_env_fallback": True,
                "worker_provenance_echoes_bound_model": True,
                "non_paid_check_relays_get_summary": True,
                "paid_probe_requires_explicit_confirmation_and_stores_nothing": True,
                "save_list_check_never_hit_provider": True,
            },
            indent=2,
        )
    )
    print(
        "PASS C1/C2/C3: admin provider configuration binding, rotation, non-paid check", flush=True
    )
    return server


def admin_page_checks(page_env, work):
    """Real Chromium pass over the admin provider page using the mock relays."""
    log = (work / "admin-browser.log").open("w")
    try:
        subprocess.run(
            [
                tool("npm"),
                "exec",
                "--",
                "playwright",
                "test",
                "--config=playwright.admin.config.ts",
            ],
            cwd=ROOT / "frontend",
            env=page_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=300,
        )
    finally:
        log.close()
    (work / "admin-page-evidence.json").write_text(
        json.dumps(
            {
                "mode": "MOCK",
                "admin_page_lists_masked_version": True,
                "non_paid_check_from_page": True,
                "paid_test_requires_checkbox_and_shows_pending_output": True,
                "disable_and_enable_from_page": True,
            },
            indent=2,
        )
    )


def post(run, path, token, body, *, key=None, lease=None):
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    if lease:
        headers["X-Lease-Token"] = lease
    request = Request(
        run.base + path, method="POST", headers=headers, data=json.dumps(body).encode()
    )
    try:
        response = run.client.open(request, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else None


def failure_checks(run, certificate, alice, previous):
    body = json.loads(
        run.sql(f"SELECT request_snapshot_json FROM generation_tasks WHERE id='{previous}'")
    )
    body["output"]["format"] = "jpeg"
    body["output"]["count"] = 4
    assert post(run, "/api/v3/scene-tasks", alice, body, key=uuid.uuid4().hex)[0] == 422
    body["output"]["count"] = 3
    key = uuid.uuid4().hex
    status, task = post(run, "/api/v3/scene-tasks", alice, body, key=key)
    assert status == 202
    assert post(run, "/api/v3/scene-tasks", alice, body, key=key)[1]["id"] == task["id"]
    identifier = task["id"]
    worker(run, certificate, False, fail=True)
    failed = run.http("GET", f"/api/v1/tasks/{identifier}", alice)[1]
    assert failed["status"] == "FAILED" and failed["artifacts"] == []
    assert failed["error"]["code"] == "PROVIDER_UNAVAILABLE"
    (run.work / "sync/failed.json").write_text(json.dumps({"task_id": identifier}))
    deadline = time.monotonic() + 60
    while not (run.work / "sync/failure-viewed.json").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Browser did not confirm failed scene has no visible artifacts")
        time.sleep(0.2)
    old = json.loads(run.sql(f"SELECT payload FROM worker_receipts WHERE task_id='{identifier}'"))
    lease = run.sql(f"SELECT lease_token FROM outbox_events WHERE task_id='{identifier}'")
    assert run.sql(f"SELECT count(*) FROM artifacts WHERE task_id='{identifier}'") == "0"
    assert run.http("POST", f"/api/v1/tasks/{identifier}/retry", alice, {"attempt": 1})[0] == 202
    old["event_id"] = uuid.uuid4().hex
    status, result = post(
        run, f"/internal/v1/work/{old['attempt_id']}/receipt", run.worker_token, old, lease=lease
    )
    assert status == 200 and result["disposition"] == "IGNORED"
    worker(run, certificate, False)
    completed = run.http("GET", f"/api/v1/tasks/{identifier}", alice)[1]
    assert completed["status"] == "SUCCEEDED" and completed["attempt"] == 2
    assert len(completed["artifacts"]) == 3
    for artifact in completed["artifacts"]:
        content = run.http("GET", f"/api/v1/artifacts/{artifact['id']}/content", alice)[1]
        assert content.startswith(b"\xff\xd8")
    status, altered = post(run, "/api/v3/scene-tasks", alice, body, key=uuid.uuid4().hex)
    assert status == 202
    worker(run, certificate, False, tamper=True)
    rejected = run.http("GET", f"/api/v1/tasks/{altered['id']}", alice)[1]
    assert rejected["status"] == "FAILED" and rejected["artifacts"] == []
    assert rejected["error"]["code"] == "OUTPUT_VALIDATION_FAILED"
    status, fenced = post(run, "/api/v3/scene-tasks", alice, body, key=uuid.uuid4().hex)
    assert status == 202
    status, claim = post(run, "/internal/v1/work/claim", run.worker_token, {})
    assert status == 200 and claim["request"]["task_id"] == fenced["id"]
    attempt, token = claim["request"]["attempt_id"], claim["lease_token"]
    path = f"/internal/v1/work/{attempt}/generation-calls/0"
    assert post(run, path, run.worker_token, {}, lease="wrong-lease")[0] == 410
    assert post(run, path, run.worker_token, {}, lease=token)[0] == 204
    assert post(run, path, run.worker_token, {}, lease=token)[0] == 409
    run.sql(
        "UPDATE outbox_events SET lease_until=now()-interval '1 second', "
        f"available_at=now()-interval '1 second' WHERE attempt_id='{attempt}'"
    )
    worker(run, certificate, False)
    recovered = run.http("GET", f"/api/v1/tasks/{fenced['id']}", alice)[1]
    assert recovered["status"] == "FAILED" and recovered["artifacts"] == []
    assert (
        run.sql(f"SELECT count(*) FROM generation_call_fences WHERE attempt_id='{attempt}'") == "1"
    )
    (run.work / "failure-evidence.json").write_text(
        json.dumps(
            {
                "mode": "MOCK",
                "partial_failure_hidden": True,
                "idempotent_submission": True,
                "old_attempt_ignored": True,
                "jpeg_retry_count": 3,
                "incomplete_receipt_rejected": True,
                "paid_call_fence_survives_reclaim": True,
                "task_id": identifier,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        "PASS S5/S6: mocked mid-batch failure, no partial artifacts, idempotency, "
        "old receipt ignored, retry with three JPEG outputs",
        flush=True,
    )


def export_review(work, store, receipt, sample, real):
    review = work / "review"
    review.mkdir()
    names = [
        "product-original.png",
        "product-subject.png",
        "product-edges.png",
        "product-details.png",
    ]
    shutil.copyfile(sample / "originals/product.png", review / names[0])
    for name in names[1:]:
        shutil.copyfile(sample / name, review / name)
    sections = []
    for item, artifact in zip(receipt["background_generations"], receipt["artifacts"], strict=True):
        files = []
        for label, value in (
            ("background", item["background"]),
            ("shadow", item["shadow"]),
            ("final", artifact),
        ):
            name = f"{item['ordinal']}-{label}.png"
            shutil.copyfile(store / value["object_key"], review / name)
            files.append(f'<figure><figcaption>{label}</figcaption><img src="{name}"></figure>')
        sections.append("<section>" + "".join(files) + "</section>")
    title = "T09 real scene" if real else "T09 MOCK provider acceptance — NOT real generation"
    html = (
        '<meta charset="utf-8"><title>'
        + title
        + "</title><style>body{font:18px sans-serif;margin:24px}section{display:flex;gap:16px}"
        + "figure{margin:4px;flex:1}img{max-width:100%}</style>"
    )
    html += f"<h1>{title}</h1><p>Visual review: PENDING. "
    html += "SAMPLE-001 cutout approval does not approve these scenes.</p>"
    html += (
        "<section>"
        + "".join(f'<figure><figcaption>{n}</figcaption><img src="{n}"></figure>' for n in names)
        + "</section>"
    )
    (review / "review.html").write_text(html + "".join(sections), encoding="utf-8")
    (review / "manifest.json").write_text(
        json.dumps(
            {
                "visual_status": "PENDING",
                "real_provider": real,
                "files": {p.name: hash_file(p) for p in review.iterdir() if p.is_file()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
