"""T09 isolated production TLS chain. Mock default; --t09-real explicitly spends provider calls."""

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import time
import uuid
from contextlib import ExitStack
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
        state = run.http("GET", f"/api/v2/scene-tasks/{task}", alice)[1]
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
        print(
            "PASS S1/S2/S3/S4: browser -> Java -> outbox -> HTTPS Worker -> private outputs; "
            + ("REAL provider" if real else "MOCK provider only"),
            flush=True,
        )
        print("Review:", work / "review/review.html", flush=True)


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
        return response.status, json.loads(response.read())


def failure_checks(run, certificate, alice, previous):
    body = json.loads(
        run.sql(f"SELECT request_snapshot_json FROM generation_tasks WHERE id='{previous}'")
    )
    body["output"]["format"] = "jpeg"
    body["output"]["count"] = 4
    assert post(run, "/api/v2/scene-tasks", alice, body, key=uuid.uuid4().hex)[0] == 422
    body["output"]["count"] = 3
    key = uuid.uuid4().hex
    status, task = post(run, "/api/v2/scene-tasks", alice, body, key=key)
    assert status == 202
    assert post(run, "/api/v2/scene-tasks", alice, body, key=key)[1]["id"] == task["id"]
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
    status, altered = post(run, "/api/v2/scene-tasks", alice, body, key=uuid.uuid4().hex)
    assert status == 202
    worker(run, certificate, False, tamper=True)
    rejected = run.http("GET", f"/api/v1/tasks/{altered['id']}", alice)[1]
    assert rejected["status"] == "FAILED" and rejected["artifacts"] == []
    assert rejected["error"]["code"] == "OUTPUT_VALIDATION_FAILED"
    (run.work / "failure-evidence.json").write_text(
        json.dumps(
            {
                "mode": "MOCK",
                "partial_failure_hidden": True,
                "idempotent_submission": True,
                "old_attempt_ignored": True,
                "jpeg_retry_count": 3,
                "incomplete_receipt_rejected": True,
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
