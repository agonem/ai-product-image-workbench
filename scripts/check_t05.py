"""T05 integration checks against an explicitly configured disposable PostgreSQL database.

Uses real Java and Python processes, synthetic PNGs and per-run database schemas. Since
ADR-20261019-AD every task is a v4 task; the carrier is a gift picture on the original background
with a program-drawn card, which calls no model and gives the same result every time.
Called by check_db.py locally; CI can call directly with DB_TEST_* for its disposable service.
"""

import copy
import hashlib
import json
import os
import secrets
import socket
import struct
import subprocess
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from common import ROOT, business_jar, environment, process_options, stop, tool

HTTP = build_opener(ProxyHandler({}))


def png(width=4, height=3, rgb=(130, 190, 160)):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + bytes(rgb) * width) * height))
        + chunk(b"IEND", b"")
    )


# The synthetic originals of the v4 carrier task (a product and a gift photo).
PRODUCT = png(64, 64, (200, 120, 90))
GIFT = png(48, 48, (90, 140, 210))


class RuntimeCheck:
    def __init__(self, env, work):
        self.env = env.copy()
        self.work = work
        self.schema = "runtime_" + uuid.uuid4().hex
        self.user_token, self.worker_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        database = urlsplit(self.env["DB_TEST_URL"].removeprefix("jdbc:"))
        pg_bin = self.env.get("PG_BIN")
        if pg_bin:
            self.psql = str(Path(pg_bin) / ("psql.exe" if os.name == "nt" else "psql"))
        elif os.name == "nt":
            self.psql = str(ROOT / ".tools/postgresql-17.11/pgsql/bin/psql.exe")
        else:
            self.psql = tool("psql")
        self.pg_command = [
            self.psql,
            "-h",
            database.hostname,
            "-p",
            str(database.port or 5432),
            "-U",
            self.env["DB_TEST_USER"],
            "-d",
            database.path.lstrip("/"),
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        self.pg_env = {**self.env, "PGPASSWORD": self.env["DB_TEST_PASSWORD"]}
        self.sql(f"CREATE SCHEMA {self.schema}", scoped=False)
        separator = "&" if "?" in self.env["DB_TEST_URL"] else "?"
        self.store = work / "objects"
        self.store.mkdir()
        self.env.update(
            {
                "SPRING_PROFILES_ACTIVE": "runtime",
                "DB_URL": self.env["DB_TEST_URL"] + separator + "currentSchema=" + self.schema,
                "DB_USER": self.env["DB_TEST_USER"],
                "DB_PASSWORD": self.env["DB_TEST_PASSWORD"],
                "BUSINESS_HOST": "127.0.0.1",
                "BUSINESS_PORT": str(self.port),
                "RUNTIME_USER_ID": "u",
                "RUNTIME_API_TOKEN": self.user_token,
                "RUNTIME_WORKER_TOKEN": self.worker_token,
                "OBJECT_STORE_ROOT": str(self.store),
                "WORK_LEASE_SECONDS": "30",
                "WORK_MAX_DELIVERIES": "3",
                "WORK_BACKOFF_SECONDS": "1",
                "WORK_SWEEP_MILLIS": "100",
                "WORKER_API_URL": self.base,
            }
        )
        self.process = None
        self.log = None
        self.starts = 0

    def sql(self, sql, *, scoped=True):
        statement = (f"SET search_path TO {self.schema}; " if scoped else "") + sql
        result = subprocess.run(
            [*self.pg_command, "-c", statement],
            env=self.pg_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return result.stdout.strip().splitlines()[-1]

    def start(self):
        self.starts += 1
        self.log = (self.work / f"java-{self.starts}.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [tool("java"), "-jar", str(business_jar())],
            env=self.env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            **process_options(),
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Runtime exited; inspect java-{self.starts}.log")
            try:
                if self.call("GET", "/api/v1/health", auth=None)[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.2)
        raise RuntimeError("Runtime startup timeout")

    def close(self):
        if self.process:
            stop(self.process)
        if self.log:
            self.log.close()
        self.process = None

    def call(self, method, path, body=None, *, auth="user", lease=None, key=None, raw=None):
        headers = {}
        if auth is not None:
            headers["Authorization"] = "Bearer " + (
                self.worker_token if auth == "worker" else self.user_token
            )
        if lease:
            headers["X-Lease-Token"] = lease
        if key:
            headers["Idempotency-Key"] = key
        data = raw
        if raw is not None:
            headers["Content-Type"] = "application/octet-stream"
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = HTTP.open(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            value = response.read()
            if "application/json" in response.headers.get("Content-Type", ""):
                value = json.loads(value)
            return response.status, value

    def seed(self):
        (self.store / "fixtures").mkdir()
        rows = []
        for name, project, kind, image, side in (
            ("product", "p", "PRODUCT", PRODUCT, 64),
            ("gift", "p", "GIFT", GIFT, 48),
            ("foreign", "q", "PRODUCT", PRODUCT, 64),
        ):
            (self.store / "fixtures" / f"{name}.png").write_bytes(image)
            sha = hashlib.sha256(image).hexdigest()
            rows.append(
                f"('{name}','{project}','{kind}','fixtures/{name}.png','{sha}',{side},{side})"
            )
        self.sql(
            """
            INSERT INTO users(id,status) VALUES ('u','ACTIVE'),('v','ACTIVE');
            INSERT INTO projects(id,owner_id,name)
              VALUES ('p','u','synthetic T05'),('q','v','foreign');
            INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES """
            + ",".join(rows)
        )

    def request(self, position="BOTTOM_RIGHT", count=1):
        """A gift picture on the original background with the gift in a card: no model call."""
        return {
            "project_id": "p",
            "feature_type": "GIFT",
            "product_asset_id": "product",
            "gift_asset_id": "gift",
            "gift_position": position,
            "background": {"mode": "ORIGINAL"},
            "gift_card": {"size": "M"},
            "output": {
                "aspect_ratio": "1:1",
                "width": 800,
                "height": 800,
                "format": "png",
                "count": count,
            },
        }

    def create(self, key=None, **request):
        status, value = self.call(
            "POST",
            "/api/v4/generation-tasks",
            self.request(**request),
            key=key or uuid.uuid4().hex,
        )
        assert status == 202, (status, value)
        return value

    def state(self, task):
        status, value = self.call("GET", f"/api/v4/generation-tasks/{task['id']}")
        assert status == 200, value
        return value

    def results(self, task):
        """Finished pictures of a task (model outputs kept for re-typesetting are not counted)."""
        return self.sql(
            f"SELECT count(*) FROM artifacts WHERE task_id='{task['id']}' AND kind='COMPOSITE'"
        )

    def claim(self):
        status, value = self.call("POST", "/internal/v1/work/claim", auth="worker")
        assert status == 200, (status, value)
        return value

    def expire(self, claim, exhausted=False):
        attempt = claim["request"]["attempt_id"]
        self.sql(
            "UPDATE outbox_events SET lease_until=now()-interval '1 second',"
            "available_at=now()-interval '1 second'"
            + (",publish_attempts=3" if exhausted else "")
            + f" WHERE attempt_id='{attempt}'"
        )

    def receipt(self, claim, artifact=None):
        """A hand-made v4 receipt: the right shape, for checking how Java treats its timing."""
        request = claim["request"]
        stored = artifact or {
            "object_key": "outputs/missing",
            "sha256": "0" * 64,
            "width": 800,
            "height": 800,
        }
        return {
            "schema_version": 4,
            "event_type": "image.task.completed.v4",
            "event_id": uuid.uuid4().hex,
            "task_id": request["task_id"],
            "attempt_id": request["attempt_id"],
            "correlation_id": request["correlation_id"],
            "duration_ms": 0,
            "artifacts": [{"ordinal": 0, "kind": "COMPOSITE", **stored}],
            "generations": [
                {
                    "ordinal": 0,
                    "base": {"ordinal": 1, "kind": "BACKGROUND", **stored},
                    "provenance": {
                        "schema_version": 1,
                        "output_source": "original",
                        "sha256": stored["sha256"],
                        "inputs": {"product_sha256": request["product_asset"]["sha256"]},
                        "transform": {},
                        "text_rendered": False,
                        "review_status": "PENDING",
                    },
                }
            ],
        }

    def send_receipt(self, claim, body):
        return self.call(
            "POST",
            f"/internal/v1/work/{claim['request']['attempt_id']}/receipt",
            body,
            auth="worker",
            lease=claim["lease_token"],
        )

    def worker(self, *, crash=None, journal="worker", expected=0):
        env = {**self.env, "WORKER_JOURNAL_ROOT": str(self.work / journal)}
        env.pop("T05_TEST_CRASH_AT", None)
        if crash:
            env["T05_TEST_CRASH_AT"] = crash
        command = [
            tool("uv"),
            "run",
            "--frozen",
            "--directory",
            "image-service",
            "python",
            "-m",
            "image_service.worker",
            "--once",
        ]
        if crash:
            command.append("--test-hooks")
        with (self.work / "worker.log").open("a", encoding="utf-8") as log:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=30,
                **process_options(),
            )
        assert result.returncode == expected, "Worker exit mismatch; inspect worker.log"


def verify(run):
    tasks_path = "/api/v4/generation-tasks"
    assert run.call("POST", tasks_path, run.request(), auth=None)[0] == 401
    assert run.call("POST", "/internal/v1/work/claim")[0] == 401
    assert run.call("GET", f"{tasks_path}/unknown", auth="worker")[0] == 401
    denied = run.request()
    denied["project_id"] = "q"
    denied["product_asset_id"] = "foreign"
    assert run.call("POST", tasks_path, denied, key="denied")[0] == 404
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = list(executor.map(lambda _: run.create("idempotent"), range(4)))
    task = tasks[0]
    assert len({value["id"] for value in tasks}) == 1
    assert run.sql("SELECT count(*) FROM generation_tasks") == "1"
    assert run.sql("SELECT count(*) FROM outbox_events") == "1"
    changed = run.request(position="BOTTOM_LEFT")
    assert run.call("POST", tasks_path, changed, key="idempotent")[0] == 409
    run.sql("""
        CREATE FUNCTION injected_failure() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN RAISE EXCEPTION 'injected transaction failure'; END; $$;
        CREATE TRIGGER test_outbox_failure BEFORE INSERT ON outbox_events
        FOR EACH ROW EXECUTE FUNCTION injected_failure();
    """)
    assert run.call("POST", tasks_path, run.request(), key="rollback")[0] == 500
    run.sql("DROP TRIGGER test_outbox_failure ON outbox_events; DROP FUNCTION injected_failure()")
    assert run.sql("SELECT count(*) FROM generation_tasks") == "1"
    print("PASS auth, concurrent idempotency, conflicting payload and atomic rollback", flush=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(
            executor.map(
                lambda _: run.call("POST", "/internal/v1/work/claim", auth="worker"), range(2)
            )
        )
    assert sorted(value[0] for value in claims) == [200, 204]
    claim = next(value[1] for value in claims if value[0] == 200)
    attempt = claim["request"]["attempt_id"]
    assert run.state(task)["status"] == "RUNNING"
    assert (
        run.call(
            "POST",
            f"/internal/v1/work/{attempt}/heartbeat",
            auth="worker",
            lease=claim["lease_token"],
        )[0]
        == 204
    )
    assert (
        run.call(
            "GET",
            f"/internal/v1/work/{attempt}/assets/foreign",
            auth="worker",
            lease=claim["lease_token"],
        )[0]
        == 404
    )
    run.sql(
        "UPDATE outbox_events SET lease_until=now()-interval '1 second',"
        "available_at=now()+interval '30 seconds' "
        f"WHERE attempt_id='{attempt}'"
    )
    assert run.call("POST", "/internal/v1/work/claim", auth="worker")[0] == 204
    run.expire(claim)
    second = run.claim()
    assert second["request"] == claim["request"]
    assert second["lease_token"] != claim["lease_token"]
    assert (
        run.call(
            "PUT",
            f"/internal/v1/work/{attempt}/outputs/0",
            raw=png(),
            auth="worker",
            lease=claim["lease_token"],
        )[0]
        == 410
    )
    assert run.send_receipt(claim, run.receipt(claim))[1]["disposition"] == "IGNORED"
    status, artifact = run.call(
        "PUT",
        f"/internal/v1/work/{attempt}/outputs/0",
        raw=png(),
        auth="worker",
        lease=second["lease_token"],
    )
    assert status == 200, artifact
    bad = run.receipt(second, artifact)
    bad["artifacts"][0]["sha256"] = "0" * 64
    assert run.send_receipt(second, bad)[1]["disposition"] == "REJECTED"
    assert run.send_receipt(second, bad)[1]["disposition"] == "REJECTED"
    conflict = copy.deepcopy(bad)
    conflict["duration_ms"] = 1
    assert run.send_receipt(second, conflict)[0] == 409
    assert run.state(task)["error"]["code"] == "OUTPUT_VALIDATION_FAILED"
    with ThreadPoolExecutor(max_workers=2) as executor:
        retries = list(
            executor.map(
                lambda _: run.call("POST", f"/api/v1/tasks/{task['id']}/retry", {"attempt": 1}),
                range(2),
            )
        )
    assert all(status == 202 and value["attempt"] == 2 for status, value in retries)
    assert run.sql("SELECT count(*) FROM task_attempts") == "2"
    # A stored original that no longer matches its hash: the Worker cannot read it, so the
    # attempt fails visibly and may be retried once the file is back.
    original = run.store / "fixtures" / "product.png"
    original.write_bytes(png(64, 64, (0, 0, 0)))
    run.worker()
    failed = run.state(task)
    assert failed["status"] == "FAILED" and failed["error"]["code"] == "GENERATION_FAILED"
    original.write_bytes(PRODUCT)
    assert run.call("POST", f"/api/v1/tasks/{task['id']}/retry", {"attempt": 2})[0] == 202
    run.worker()
    success = run.state(task)
    assert success["status"] == "SUCCEEDED" and success["attempt"] == 3
    artifact_id = success["artifacts"][0]["id"]
    content = run.call("GET", f"/api/v1/artifacts/{artifact_id}/content")[1]
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    stored = run.sql(f"SELECT sha256 FROM artifacts WHERE id='{artifact_id}'")
    assert hashlib.sha256(content).hexdigest() == stored
    assert run.call("GET", f"/api/v1/artifacts/{artifact_id}/content", auth=None)[0] == 401
    assert "object_key" not in json.dumps(success)
    assert run.results(task) == "1"
    print(
        "PASS leases, backoff, stale receipt, content verification, "
        "retry and real Worker success/failure",
        flush=True,
    )

    late = copy.deepcopy(bad)
    late["event_id"] = uuid.uuid4().hex
    assert run.send_receipt(second, late)[1]["disposition"] == "IGNORED"
    assert run.state(task)["status"] == "SUCCEEDED"

    missing = run.create()
    missing_claim = run.claim()
    missing_receipt = run.receipt(missing_claim)
    missing_receipt["artifacts"][0]["object_key"] = (
        missing_claim["request"]["output_object_prefix"] + missing_claim["lease_token"] + "/0.image"
    )
    assert run.send_receipt(missing_claim, missing_receipt)[1]["disposition"] == "REJECTED"
    assert run.state(missing)["status"] == "FAILED"
    assert run.results(missing) == "0"
    print("PASS old-attempt receipt isolation and missing-file rejection", flush=True)

    for position, count in (("LEFT", 1), ("BOTTOM_LEFT", 2)):
        independent = run.create(position=position, count=count)
        run.worker()
        assert run.state(independent)["status"] == "SUCCEEDED"
        assert run.results(independent) == str(count)
    durable = run.create()
    run.close()
    run.start()
    run.worker()
    assert run.state(durable)["status"] == "SUCCEEDED"
    print("PASS independent requests and Java restart outbox recovery", flush=True)

    for point in ("after-claim", "after-output", "after-journal", "after-ack"):
        item = run.create()
        journal = "journal-" + point
        run.worker(crash=point, journal=journal, expected=91)
        if point in {"after-claim", "after-output"}:
            run.sql(
                "UPDATE outbox_events SET lease_until=now()-interval '1 second',"
                "available_at=now()-interval '1 second' "
                f"WHERE task_id='{item['id']}'"
            )
        run.worker(journal=journal)
        assert run.state(item)["status"] == "SUCCEEDED", point
        assert run.results(item) == "1"
        assert not list((run.work / journal).glob("*.json"))
        print(f"PASS Worker crash recovery {point}", flush=True)

    exhausted = run.create()
    claim = run.claim()
    run.expire(claim, exhausted=True)
    deadline = time.monotonic() + 5
    while run.state(exhausted)["status"] != "FAILED" and time.monotonic() < deadline:
        time.sleep(0.1)
    assert run.state(exhausted)["status"] == "FAILED"
    assert run.send_receipt(claim, run.receipt(claim))[1]["disposition"] == "IGNORED"
    assert run.call("POST", f"/api/v1/tasks/{exhausted['id']}/retry", {"attempt": 1})[0] == 202
    run.worker()
    assert run.state(exhausted)["status"] == "SUCCEEDED"
    print("PASS bounded lease exhaustion and explicit retry", flush=True)


def run_runtime(env, work):
    work.mkdir(parents=True, exist_ok=True)
    run = RuntimeCheck(env, work)
    try:
        run.start()
        run.seed()
        verify(run)
    finally:
        run.close()
    print("T05 runtime integration passed; Java/Worker processes stopped.", flush=True)


if __name__ == "__main__":
    root = ROOT / ".artifacts/t05" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    run_runtime(environment(), root)
