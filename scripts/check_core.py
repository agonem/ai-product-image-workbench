"""Core loop acceptance (docs/08 §5): cutout candidate -> human confirmation, isolated.

Production-mode Java (HTTPS, disposable PostgreSQL, own JAR/ports), the image service on
loopback with a random token, and a real Chromium page. Synthetic images only; no provider
calls and nothing is approved except by the explicit review request under test.
"""

import json
import os
import secrets
import socket
import ssl
import struct
import subprocess
import time
import zlib
from contextlib import ExitStack
from urllib.error import URLError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener, urlopen

from check_t04_prod import ProductionCheck
from common import ROOT, process_options, stop, tool
from smoke import wait_ready


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def synthetic_png(width=240, height=200, *, shape=(186, 64, 72), blank=False):
    """White background with a solid rectangle 'product'; pure stdlib encoder."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = []
    for y in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            inside = (
                not blank and width * 0.3 <= x < width * 0.7 and height * 0.2 <= y < height * 0.85
            )
            row += bytes(shape) if inside else b"\xff\xff\xff"
        rows.append(bytes(row))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def start_image_service(stack, work, token):
    port = free_port()
    log_path = work / "image-service.log"
    log = stack.enter_context(log_path.open("w", encoding="utf-8"))
    process = subprocess.Popen(
        [tool("uv"), "run", "--frozen", "--directory", str(ROOT / "image-service")]
        + ["python", "-m", "image_service"],
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("OPENROUTER")},
            "IMAGE_HOST": "127.0.0.1",
            "IMAGE_PORT": str(port),
            "IMAGE_SERVICE_TOKEN": token,
        },
        stdout=log,
        stderr=subprocess.STDOUT,
        **process_options(),
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while True:
        if process.poll() is not None:
            raise RuntimeError(f"image service exited; see {log_path}")
        try:
            with urlopen(url + "/internal/v1/health", timeout=2):
                break
        except (URLError, ConnectionError, TimeoutError):
            if time.monotonic() > deadline:
                raise RuntimeError(f"image service not ready; see {log_path}") from None
            time.sleep(0.25)
    return process, url


def cutout_api_checks(run, admin, alice, bob, project):
    """N0-A1..A6 at the API boundary."""
    original = synthetic_png()
    status, product, _ = run.http(
        "POST",
        f"/api/v1/projects/{project}/assets?kind=PRODUCT",
        alice,
        data=original,
        mime="image/png",
    )
    assert status == 201 and product["review_status"] == "PENDING"
    pid = product["id"]
    path = f"/api/v1/assets/{pid}/cutouts"

    # A1: owner-only; admin role does not grant cross-project access.
    for token in (bob, admin):
        assert run.http("POST", path, token, {"tolerance": 12})[0] == 404
        assert run.http("GET", path, token)[0] == 404
    # A2: strict input, never echoed.
    for body in ({}, {"tolerance": 33}, {"tolerance": "12"}, {"tolerance": 12, "x": 1}):
        status, value, _ = run.http("POST", path, alice, body)
        assert status == 400 and value["code"] == "INVALID_CONTRACT", (body, status)

    listing = run.http("GET", f"/api/v1/projects/{project}/assets", alice)[1]["items"]
    assert next(i for i in listing if i["id"] == pid)["cutout_ready"] is False

    # A3: candidate is PENDING, same size, private, and the original is untouched.
    status, candidate, _ = run.http("POST", path, alice, {"tolerance": 12})
    assert status == 201, (status, candidate)
    assert candidate["review_status"] == "PENDING" and candidate["source_asset_id"] == pid
    assert (candidate["width"], candidate["height"]) == (240, 200)
    alpha = run.http("GET", f"/api/v1/assets/{candidate['id']}/content", alice)[1]
    assert alpha[:8] == b"\x89PNG\r\n\x1a\n" and alpha[25] == 0  # 8-bit grayscale
    assert run.http("GET", f"/api/v1/assets/{candidate['id']}/content", admin)[0] == 404
    assert run.http("GET", f"/api/v1/assets/{pid}/content", alice)[1] == original
    assert run.http("GET", f"/api/v1/assets/{pid}/approved-alpha", alice)[0] == 404
    listing = run.http("GET", f"/api/v1/projects/{project}/assets", alice)[1]["items"]
    assert next(i for i in listing if i["id"] == pid)["cutout_ready"] is False
    details = json.loads(
        run.sql(
            "SELECT details FROM audit_events WHERE action='CUTOUT_CANDIDATE_CREATED' "
            f"AND resource_id='{candidate['id']}'"
        )
    )
    assert details == {
        "source_asset_id": pid,
        "algorithm": "white-border-flood-v1",
        "tolerance": 12,
    }

    # A4: only the owner decides; a decision is final for that candidate.
    review = f"/api/v1/assets/{candidate['id']}/review"
    assert run.http("POST", review, bob, {"decision": "APPROVED"})[0] == 404
    assert run.http("POST", review, admin, {"decision": "APPROVED"})[0] == 404
    assert run.http("POST", review, alice, {"decision": "OK"})[0] == 400
    status, approved, _ = run.http("POST", review, alice, {"decision": "APPROVED"})
    assert status == 200 and approved["review_status"] == "APPROVED"
    assert run.http("POST", review, alice, {"decision": "REJECTED"})[0] == 409
    assert run.http("GET", f"/api/v1/assets/{pid}/approved-alpha", alice)[1] == alpha
    listing = run.http("GET", f"/api/v1/projects/{project}/assets", alice)[1]["items"]
    assert next(i for i in listing if i["id"] == pid)["cutout_ready"] is True
    actor = run.sql(
        f"SELECT actor_id FROM audit_events WHERE action='CUTOUT_APPROVED' "
        f"AND resource_id='{candidate['id']}'"
    )
    assert actor == run.http("GET", "/api/v1/local-auth/me", alice)[1]["id"]

    # A5: a later rejected candidate never replaces the confirmed one.
    status, second, _ = run.http("POST", path, alice, {"tolerance": 3})
    assert status == 201 and second["review_status"] == "PENDING"
    assert run.http("GET", f"/api/v1/assets/{pid}/approved-alpha", alice)[1] == alpha
    assert (
        run.http("POST", f"/api/v1/assets/{second['id']}/review", alice, {"decision": "REJECTED"})[
            1
        ]["review_status"]
        == "REJECTED"
    )
    items = run.http("GET", path, alice)[1]["items"]
    assert [i["review_status"] for i in items] == ["REJECTED", "APPROVED"]
    assert run.http("GET", f"/api/v1/assets/{pid}/approved-alpha", alice)[1] == alpha

    # A6: a blank white image is a diagnosable failure; an alpha cannot be a source.
    blank = run.http(
        "POST",
        f"/api/v1/projects/{project}/assets?kind=GIFT",
        alice,
        data=synthetic_png(blank=True),
        mime="image/png",
    )[1]
    status, value, _ = run.http(
        "POST", f"/api/v1/assets/{blank['id']}/cutouts", alice, {"tolerance": 12}
    )
    assert status == 422 and value["code"] == "CUTOUT_NO_FOREGROUND"
    assert "white-border" not in json.dumps(value)
    status, value, _ = run.http(
        "POST", f"/api/v1/assets/{candidate['id']}/cutouts", alice, {"tolerance": 12}
    )
    assert status == 422 and value["code"] == "INVALID_ASSET"
    assert run.sql("SELECT count(*) FROM assets WHERE review_status='APPROVED'") == "1"
    return {"product": pid, "approved_alpha": candidate["id"], "rejected_alpha": second["id"]}


def browser_checks(run, work, certificate, project, stack):
    port = free_port()
    product = work / "browser-product.png"
    product.write_bytes(synthetic_png(320, 280, shape=(64, 120, 186)))
    page_env = {
        k: v
        for k, v in run.env.items()
        if not k.startswith(("DB_", "PGPASSWORD", "RUNTIME_", "PROD_", "SERVER_SSL_", "IMAGE_"))
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
            "T06_ARTIFACTS": str(work / "browser"),
            "CORE_PROJECT": project,
            "CORE_PRODUCT_FILE": str(product),
        }
    )
    output = work / "frontend-dist"
    subprocess.run(
        [tool("npm"), "run", "build", "--", "--outDir", str(output)],
        cwd=ROOT / "frontend",
        env=page_env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    log_path = work / "vite.log"
    log = stack.enter_context(log_path.open("w", encoding="utf-8"))
    vite = subprocess.Popen(
        [tool("npm"), "exec", "--", "vite", "preview", "--host", "127.0.0.1"]
        + ["--port", str(port), "--strictPort", "--outDir", str(output)],
        cwd=ROOT / "frontend",
        env=page_env,
        stdout=log,
        stderr=subprocess.STDOUT,
        **process_options(),
    )
    stack.callback(stop, vite)
    wait_ready(page_env["T06_BASE_URL"], vite, log_path)
    with (work / "browser.log").open("w", encoding="utf-8") as browser_log:
        subprocess.run(
            [tool("npm"), "exec", "--", "playwright", "test", "--config=playwright.core.config.ts"],
            cwd=ROOT / "frontend",
            env=page_env,
            stdout=browser_log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=300,
        )


def run_core_checks(env, work):
    work.mkdir(parents=True)
    token = secrets.token_urlsafe(32)
    run = ProductionCheck({k: v for k, v in env.items() if not k.startswith("OPENROUTER_")}, work)
    certificate = work / "test-public.pem"
    subprocess.run(
        [tool("keytool"), "-exportcert", "-rfc", "-alias", "test", "-keystore"]
        + [str(work / "test.p12"), "-storepass:env", "SERVER_SSL_KEY_STORE_PASSWORD"]
        + ["-file", str(certificate)],
        env=run.env,
        capture_output=True,
        check=True,
    )
    run.client = build_opener(
        ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=str(certificate)))
    )
    evidence = {"mode": "synthetic images, no provider calls"}
    with ExitStack() as stack:
        image, url = start_image_service(stack, work, token)
        stack.callback(stop, image)
        run.env.update({"IMAGE_SERVICE_URL": url, "IMAGE_SERVICE_TOKEN": token})
        stack.callback(run.close)
        run.start()
        admin = run.login("admin")
        for name in ("alice", "bob"):
            assert (
                run.http(
                    "POST",
                    "/api/v1/admin/accounts",
                    admin,
                    {"username": name, "password": run.password, "role": "USER"},
                )[0]
                == 201
            )
        alice, bob = run.login("alice"), run.login("bob")
        project = run.http("POST", "/api/v1/projects", alice, {"name": "core loop"})[1]["id"]
        evidence["api"] = cutout_api_checks(run, admin, alice, bob, project)
        print(
            "PASS N0-A1..A6: cutout candidate, owner-only confirmation, no auto approval",
            flush=True,
        )
        browser_checks(run, work, certificate, project, stack)
        print("PASS N0-B1: page generates, previews and confirms a cutout", flush=True)
        # A7: the image service going away is a clear, retryable condition, not a silent pass.
        stop(image)
        blank_asset = run.sql(
            f"SELECT id FROM assets WHERE project_id='{project}' AND kind='PRODUCT' "
            "ORDER BY created_at LIMIT 1"
        )
        status, value, _ = run.http(
            "POST", f"/api/v1/assets/{blank_asset}/cutouts", alice, {"tolerance": 12}
        )
        assert status == 503 and value["code"] == "CUTOUT_SERVICE_UNAVAILABLE"
        print("PASS N0-A7: unavailable image service reported as 503", flush=True)
        for name in ("java-1.log", "image-service.log"):
            assert token not in (work / name).read_text(errors="replace")
    (work / "core-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
