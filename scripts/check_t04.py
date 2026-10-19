"""ACC-T04-DEV: isolated PostgreSQL + real Java HTTP; no real accounts or images."""

import base64
import hashlib
import http.client
import json
import secrets
import socket
import struct
import subprocess
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.error import HTTPError
from urllib.request import Request

from check_t05 import HTTP, RuntimeCheck, png
from common import ROOT, business_jar, environment, process_options, stop, tool


def account(username, user_id, password):
    salt = secrets.token_bytes(16)
    return {
        "username": username,
        "user_id": user_id,
        "salt": salt.hex(),
        "password_hash": hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000).hex(),
    }


class LocalCheck(RuntimeCheck):
    def __init__(self, env, work):
        super().__init__(env, work)
        self.password = secrets.token_urlsafe(24)
        accounts = work / "accounts.json"
        accounts.write_text(
            json.dumps(
                [
                    account("alice", "alice_id", self.password),
                    account("bob", "bob_id", self.password),
                ]
            ),
            encoding="utf-8",
        )
        self.env.update(
            {
                "SPRING_PROFILES_ACTIVE": "dev-local",
                "APP_ENV": "development",
                "DEV_ACCOUNTS_FILE": str(accounts),
                "DEV_SESSION_SECONDS": "60",
                "OBJECT_MAX_BYTES": "2048",
                "OBJECT_MAX_PIXELS": "100",
            }
        )

    def http(self, method, path, *, token=None, body=None, data=None, mime=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        if body is not None:
            data, mime = json.dumps(body).encode(), "application/json"
        if mime:
            headers["Content-Type"] = mime
        try:
            response = HTTP.open(
                Request(self.base + path, data=data, headers=headers, method=method), timeout=15
            )
        except HTTPError as error:
            response = error
        with response:
            value = response.read()
            if "application/json" in response.headers.get("Content-Type", ""):
                value = json.loads(value)
            return response.status, value, response.headers

    def login(self, name):
        status, value, headers = self.http(
            "POST", "/api/v1/auth/login", body={"username": name, "password": self.password}
        )
        assert status == 200, ("login", status)
        assert value["mode"] == "development-only" and headers["Cache-Control"] == "no-store"
        return value["access_token"]


def chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def verify(run):
    alice, bob = run.login("alice"), run.login("bob")
    assert run.http("GET", "/api/v1/auth/me", token=alice)[1]["id"] == "alice_id"
    for name in ("alice", "unknown"):
        assert (
            run.http(
                "POST", "/api/v1/auth/login", body={"username": name, "password": "wrong-password"}
            )[0]
            == 401
        )
    for token in (None, run.user_token, run.worker_token):
        assert run.http("GET", "/api/v1/projects", token=token)[0] == 401
    assert run.http("POST", "/internal/v1/work/claim", token=alice)[0] == 401
    assert (
        run.http("POST", "/api/v1/projects", token=alice, body={"name": "A", "owner_id": "bob_id"})[
            0
        ]
        == 400
    )
    projects = []
    for token in (alice, bob):
        status, project, _ = run.http(
            "POST", "/api/v1/projects", token=token, body={"name": "Synthetic project"}
        )
        assert status == 201
        projects.append(project["id"])
    project = projects[0]
    assert len(run.http("GET", "/api/v1/projects", token=alice)[1]) == 1
    assert run.http("GET", f"/api/v1/projects/{project}", token=bob)[0] == 404
    endpoint = f"/api/v1/projects/{project}/assets?kind=PRODUCT"
    assert run.http("POST", endpoint, token=bob, data=png(), mime="image/png")[0] == 404
    before = run.sql("SELECT count(*) FROM assets")
    # ADR-20260930-D: the content decides the type and metadata is kept; unknown, damaged and
    # oversized inputs are still refused before anything is stored.
    malformed = [
        (b"not an image", "image/png", 415),
        (png()[:-6], "image/png", 422),
        (png() + b"trailer", "image/png", 422),
        (b"x" * 2049, "image/png", 413),
        (
            png()[:8]
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 100000, 3, 8, 2, 0, 0, 0))
            + png()[33:],
            "image/png",
            413,
        ),
    ]
    for data, mime, expected in malformed:
        status, value, _ = run.http("POST", endpoint, token=alice, data=data, mime=mime)
        assert status == expected, ("invalid upload", expected, status)
        assert "secret" not in json.dumps(value) and "object_key" not in json.dumps(value)
    assert (
        run.http(
            "POST", endpoint.replace("PRODUCT", "ALPHA"), token=alice, data=png(), mime="image/png"
        )[0]
        == 400
    )
    assert run.sql("SELECT count(*) FROM assets") == before
    accepted = [
        (png(), "image/jpeg"),  # declared type wrong: the PNG content wins
        (
            png()[:-12] + chunk(b"zTXt", b"note\0\0" + zlib.compress(b"x" * 10000)) + png()[-12:],
            "application/octet-stream",
        ),
    ]
    for data, mime in accepted:
        status, value, _ = run.http("POST", endpoint, token=alice, data=data, mime=mime)
        assert status == 201, ("accepted upload", status, value)
        content = run.http("GET", f"/api/v1/assets/{value['id']}/content", token=alice)[1]
        assert content == data, "original bytes must be kept unchanged"
    assert int(run.sql("SELECT count(*) FROM assets")) == int(before) + len(accepted)
    print(
        "PASS ACC-T04-DEV A1/A2/A3/A5: local identity, project isolation and invalid uploads",
        flush=True,
    )

    def upload(kind):
        result = run.http(
            "POST", endpoint.replace("PRODUCT", kind), token=alice, data=png(), mime="image/png"
        )
        assert result[0] == 201, ("upload", result[0])
        return result[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        images = list(executor.map(upload, ("PRODUCT", "GIFT")))
    assert images[0]["id"] != images[1]["id"]
    for asset in images:
        assert asset["sha256"] == hashlib.sha256(png()).hexdigest()
        assert "review_status" not in asset and "object_key" not in asset
        path = f"/api/v1/assets/{asset['id']}"
        assert run.http("GET", path, token=bob)[0] == 404
        assert run.http("GET", path + "/content", token=bob)[0] == 404
        assert run.http("GET", path + "/content")[0] == 401
        status, content, headers = run.http("GET", path + "/content", token=alice)
        assert status == 200 and content == png()
        assert (
            headers["Cache-Control"] == "no-store"
            and headers["X-Content-Type-Options"] == "nosniff"
        )

    jpeg = base64.b64decode((ROOT / "contracts/fixtures/t04-synthetic-jpeg.base64").read_text())
    status, photo, _ = run.http("POST", endpoint, token=alice, data=jpeg, mime="image/jpeg")
    assert status == 201
    assert run.http("GET", photo["content_url"], token=alice)[1] == jpeg
    for query in ("?kind=PRODUCT&kind=GIFT", "?kind=PRODUCT&object_key=escape", ""):
        assert (
            run.http(
                "POST", endpoint.split("?")[0] + query, token=alice, data=png(), mime="image/png"
            )[0]
            == 400
        )
    assert run.http("POST", endpoint, token=alice, data=b"", mime="image/png")[0] == 422
    with closing(http.client.HTTPConnection("127.0.0.1", run.port, timeout=10)) as connection:
        connection.request(
            "POST",
            endpoint,
            body=iter([png()]),
            headers={"Authorization": "Bearer " + alice, "Content-Type": "image/png"},
            encode_chunked=True,
        )
        response = connection.getresponse()
        assert response.status == 201
        response.read()
    count = run.sql("SELECT count(*) FROM assets")
    run.sql("""CREATE FUNCTION reject_asset() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN RAISE EXCEPTION 'test insert failure'; END; $$;
        CREATE TRIGGER reject_asset BEFORE INSERT ON assets
        FOR EACH ROW EXECUTE FUNCTION reject_asset();""")
    assert run.http("POST", endpoint, token=alice, data=png(), mime="image/png")[0] == 500
    assert run.sql("SELECT count(*) FROM assets") == count
    run.sql("DROP TRIGGER reject_asset ON assets")
    files_before = set(run.store.rglob("*.image"))
    with socket.create_connection(("127.0.0.1", run.port)) as connection:
        connection.sendall(
            (
                f"POST {endpoint} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Authorization: Bearer {alice}\r\nContent-Type: image/png\r\n"
                "Content-Length: 100\r\nConnection: close\r\n\r\n"
            ).encode()
            + b"partial"
        )
    time.sleep(0.3)
    assert run.sql("SELECT count(*) FROM assets") == count
    assert set(run.store.rglob("*.image")) == files_before

    held = []
    try:
        for _ in range(2):
            connection = socket.create_connection(("127.0.0.1", run.port))
            held.append(connection)
            connection.sendall(
                (
                    f"POST {endpoint} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    f"Authorization: Bearer {alice}\r\nContent-Type: image/png\r\n"
                    "Content-Length: 100\r\nConnection: close\r\n\r\n"
                ).encode()
                + b"partial"
            )
        deadline = time.monotonic() + 3
        while True:
            status = run.http("POST", endpoint, token=alice, data=b"", mime="image/png")[0]
            if status == 429 or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        assert status == 429, "Concurrent upload budget not enforced"
    finally:
        for connection in held:
            connection.close()
    assert run.sql("SELECT count(*) FROM assets") == count
    print(
        "PASS ACC-T04-DEV A4/A5/A6: JPEG bytes, chunked input and bounded concurrency", flush=True
    )

    # The v4 carrier task makes an 800 x 800 picture, beyond the tiny upload limits above.
    run.close()
    run.env.update({"OBJECT_MAX_BYTES": "20000000", "OBJECT_MAX_PIXELS": "40000000"})
    run.start()
    alice, bob = run.login("alice"), run.login("bob")
    # T05 data are SQL-generated synthetic rows; reassign only the synthetic project's owner.
    run.seed()
    run.sql("UPDATE projects SET owner_id='alice_id' WHERE id='p'")
    saved_token = run.user_token
    run.user_token = alice
    task = run.create("local-task")
    for path, method, body in (
        (f"/api/v4/generation-tasks/{task['id']}", "GET", None),
        (f"/api/v1/tasks/{task['id']}/retry", "POST", {"attempt": 1}),
    ):
        assert run.http(method, path, token=bob, body=body)[0] == 404
    run.worker()
    result = run.state(task)
    assert result["status"] == "SUCCEEDED"
    assert (
        run.http("GET", f"/api/v1/artifacts/{result['artifacts'][0]['id']}/content", token=bob)[0]
        == 404
    )
    run.user_token = saved_token
    print(
        "PASS ACC-T04-DEV A3/A4/A6: original bytes, rollback, "
        "interrupted upload and task ownership",
        flush=True,
    )

    assert run.http("POST", "/api/v1/auth/logout", token=bob)[0] == 204
    assert run.http("GET", "/api/v1/auth/me", token=bob)[0] == 401
    bob = run.login("bob")
    run.sql("UPDATE users SET status='DISABLED' WHERE id='bob_id'")
    assert run.http("GET", "/api/v1/auth/me", token=bob)[0] == 401
    assert (
        run.http("POST", "/api/v1/auth/login", body={"username": "bob", "password": run.password})[
            0
        ]
        == 401
    )
    run.close()
    run.env["DEV_SESSION_SECONDS"] = "2"
    run.start()
    assert run.http("GET", "/api/v1/auth/me", token=alice)[0] == 401
    alice = run.login("alice")
    time.sleep(2.1)
    assert run.http("GET", "/api/v1/auth/me", token=alice)[0] == 401
    assert run.sql("SELECT status FROM users WHERE id='bob_id'") == "DISABLED"
    for _ in range(30):
        limited = run.http(
            "POST", "/api/v1/auth/login", body={"username": "unknown", "password": "wrong-password"}
        )[0]
    assert limited == 429
    print(
        "PASS ACC-T04-DEV A2: logout, disabled accounts, restart, expiry and login rate limit",
        flush=True,
    )


def run_local(env, work):
    work.mkdir(parents=True, exist_ok=True)
    run = LocalCheck(env, work)
    try:
        run.start()
        verify(run)
    finally:
        run.close()
    # Real startup failures, including explicit production environment/profile.
    for index, override in enumerate(
        (
            {"APP_ENV": "production"},
            {"SPRING_PROFILES_ACTIVE": "dev-local,production"},
            {"BUSINESS_HOST": "0.0.0.0"},
            {"DEV_ACCOUNTS_FILE": str(work / "missing.json")},
        )
    ):
        with (work / f"rejected-start-{index}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [tool("java"), "-jar", str(business_jar())],
                env={**run.env, **override},
                stdout=log,
                stderr=subprocess.STDOUT,
                **process_options(),
            )
            try:
                assert process.wait(timeout=30) != 0
            finally:
                stop(process)
    print(
        "PASS ACC-T04-DEV A1/A7: production/missing configuration fail closed; processes stopped",
        flush=True,
    )


if __name__ == "__main__":
    run_local(environment(), ROOT / ".artifacts/t04" / uuid.uuid4().hex)
