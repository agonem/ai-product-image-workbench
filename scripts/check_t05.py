"""T05 integration checks against an explicitly configured disposable PostgreSQL database.

Uses real Java and Python processes, synthetic PNGs and per-run database schemas.
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


def png():
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + bytes([130, 190, 160]) * 4) * 3))
        + chunk(b"IEND", b"")
    )


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
        image = png()
        (self.store / "fixtures").mkdir()
        for name in ("product", "alpha", "gift", "foreign"):
            (self.store / "fixtures" / f"{name}.png").write_bytes(image)
        sha = hashlib.sha256(image).hexdigest()
        self.sql("""
            INSERT INTO users(id,status) VALUES ('u','ACTIVE'),('v','ACTIVE');
            INSERT INTO projects(id,owner_id,name)
              VALUES ('p','u','synthetic T05'),('q','v','foreign');
            INSERT INTO templates(id,type,name) VALUES ('layout','layout','fixture only');
            INSERT INTO template_versions(id,template_id,version,config_json,created_by,
              published_by,published_at)
              VALUES ('layout_v1','layout',1,'{}','u','u',now());
            UPDATE templates SET published_version_id='layout_v1',state='PUBLISHED';
            INSERT INTO output_presets(id,config_json)
              VALUES ('t05_transport_fixture','{"purpose":"synthetic transport test"}');
        """)
        for name, project, kind in (
            ("product", "p", "PRODUCT"),
            ("gift", "p", "GIFT"),
            ("foreign", "q", "PRODUCT"),
        ):
            self.sql(f"""
                INSERT INTO assets(id,project_id,kind,object_key,sha256,
              width,height)
                VALUES ('{name}','{project}','{kind}','fixtures/{name}.png','{sha}',4,3);
            """)
        self.sql(f"""
            INSERT INTO assets(id,project_id,kind,source_asset_id,object_key,sha256,
              width,height,review_status)
            VALUES ('alpha','p','ALPHA','product','fixtures/alpha.png','{sha}',4,3,'APPROVED');
        """)

    def request(self, feature="SCENE"):
        value = {
            "project_id": "p",
            "product_asset_id": "product",
            "feature_type": feature,
            "output_preset_id": "t05_transport_fixture",
            "layout": {"product": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8}},
        }
        if feature == "SCENE":
            value["scene_custom_prompt"] = "synthetic transport fixture"
        elif feature == "GIFT":
            value.update(gift_asset_id="gift", template_version_id="layout_v1")
            value["layout"]["gift"] = {"x": 0.7, "y": 0.7, "width": 0.2, "height": 0.2}
        else:
            value.update(selling_points=["人工测试"], layout_template_version_id="layout_v1")
        return value

    def create(self, key=None, feature="SCENE"):
        status, value = self.call(
            "POST", "/api/v1/tasks", self.request(feature), key=key or uuid.uuid4().hex
        )
        assert status == 202, (status, value)
        return value

    def state(self, task):
        status, value = self.call("GET", f"/api/v1/tasks/{task['id']}")
        assert status == 200, value
        return value

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
        request = claim["request"]
        return {
            "schema_version": 1,
            "event_type": "image.task.completed.v1",
            "event_id": uuid.uuid4().hex,
            "task_id": request["task_id"],
            "attempt_id": request["attempt_id"],
            "correlation_id": request["correlation_id"],
            "artifacts": [
                {
                    "ordinal": 0,
                    "kind": "COMPOSITE",
                    **(
                        artifact
                        or {
                            "object_key": "outputs/missing",
                            "sha256": "0" * 64,
                            "width": 4,
                            "height": 3,
                        }
                    ),
                }
            ],
            "duration_ms": 0,
            "background_generation": None,
        }

    def send_receipt(self, claim, body):
        return self.call(
            "POST",
            f"/internal/v1/work/{claim['request']['attempt_id']}/receipt",
            body,
            auth="worker",
            lease=claim["lease_token"],
        )

    def worker(self, *, fixture=True, crash=None, journal="worker", expected=0):
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
        if fixture:
            command.append("--fixture")
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
    assert run.call("POST", "/api/v1/tasks", run.request(), auth=None)[0] == 401
    assert run.call("POST", "/internal/v1/work/claim")[0] == 401
    assert run.call("GET", "/api/v1/tasks/unknown", auth="worker")[0] == 401
    denied = run.request()
    denied["project_id"] = "q"
    denied["product_asset_id"] = "foreign"
    assert run.call("POST", "/api/v1/tasks", denied, key="denied")[0] == 404
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = list(executor.map(lambda _: run.create("idempotent"), range(4)))
    task = tasks[0]
    assert len({value["id"] for value in tasks}) == 1
    assert run.sql("SELECT count(*) FROM generation_tasks") == "1"
    assert run.sql("SELECT count(*) FROM outbox_events") == "1"
    changed = run.request()
    changed["scene_custom_prompt"] += " changed"
    assert run.call("POST", "/api/v1/tasks", changed, key="idempotent")[0] == 409
    run.sql("""
        CREATE FUNCTION injected_failure() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN RAISE EXCEPTION 'injected transaction failure'; END; $$;
        CREATE TRIGGER test_outbox_failure BEFORE INSERT ON outbox_events
        FOR EACH ROW EXECUTE FUNCTION injected_failure();
    """)
    assert run.call("POST", "/api/v1/tasks", run.request(), key="rollback")[0] == 500
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
    run.worker(fixture=False)
    failed = run.state(task)
    assert failed["status"] == "FAILED" and failed["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert run.call("POST", f"/api/v1/tasks/{task['id']}/retry", {"attempt": 2})[0] == 202
    run.worker()
    success = run.state(task)
    assert success["status"] == "SUCCEEDED" and success["attempt"] == 3
    artifact_id = success["artifacts"][0]["id"]
    assert run.call("GET", f"/api/v1/artifacts/{artifact_id}/content")[1] == png()
    assert run.call("GET", f"/api/v1/artifacts/{artifact_id}/content", auth=None)[0] == 401
    assert "object_key" not in json.dumps(success)
    assert run.sql("SELECT count(*) FROM artifacts") == "1"
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
    assert run.sql(f"SELECT count(*) FROM artifacts WHERE task_id='{missing['id']}'") == "0"
    print("PASS old-attempt receipt isolation and missing-file rejection", flush=True)

    for feature in ("GIFT", "SELLING_POINT"):
        independent = run.create(feature=feature)
        run.worker()
        assert run.state(independent)["status"] == "SUCCEEDED"
    durable = run.create()
    run.close()
    run.start()
    run.worker()
    assert run.state(durable)["status"] == "SUCCEEDED"
    print("PASS independent feature requests and Java restart outbox recovery", flush=True)

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
        assert run.sql(f"SELECT count(*) FROM artifacts WHERE task_id='{item['id']}'") == "1"
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
