"""T04 production account API: disposable PostgreSQL, real HTTPS, synthetic identities."""

import hashlib
import json
import secrets
import ssl
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from check_t04 import account
from check_t05 import RuntimeCheck, png
from common import ROOT, business_jar, environment, process_options, stop, tool


class ProductionCheck(RuntimeCheck):
    def __init__(self, env, work):
        super().__init__(env, work)
        # New passwords are 6-15 characters (user decision); 15 here keeps a CJK prefix.
        self.password = "合成-" + secrets.token_urlsafe(9)
        bootstrap = account("admin", "unused", self.password)
        bootstrap.pop("user_id")
        self.bootstrap = work / "bootstrap.json"
        self.bootstrap.write_text(json.dumps(bootstrap), encoding="utf-8")
        tls_password = secrets.token_urlsafe(24)
        certificate = work / "test.p12"
        with (work / "keytool.log").open("w") as log:
            subprocess.run(
                [
                    tool("keytool"),
                    "-genkeypair",
                    "-alias",
                    "test",
                    "-keyalg",
                    "RSA",
                    "-keystore",
                    str(certificate),
                    "-storetype",
                    "PKCS12",
                    "-storepass:env",
                    "TEST_TLS_PASSWORD",
                    "-dname",
                    "CN=localhost",
                    "-validity",
                    "1",
                    "-ext",
                    "SAN=ip:127.0.0.1",
                ],
                env={**self.env, "TEST_TLS_PASSWORD": tls_password},
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        self.env.update(
            {
                "SPRING_PROFILES_ACTIVE": "prod-local",
                "APP_ENV": "production",
                "SERVER_SSL_ENABLED": "true",
                "SERVER_SSL_KEY_STORE": certificate.as_uri(),
                "SERVER_SSL_KEY_STORE_PASSWORD": tls_password,
                "PROD_BOOTSTRAP_FILE": str(self.bootstrap),
                "PROD_LOGIN_LIMIT": "60",
            }
        )
        self.base = f"https://127.0.0.1:{self.port}"
        context = ssl.create_default_context()
        # Only this disposable certificate is untrusted; never configure the product this way.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.client = build_opener(ProxyHandler({}), HTTPSHandler(context=context))

    def http(self, method, path, token=None, body=None, data=None, mime=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        if body is not None:
            data, mime = json.dumps(body).encode(), "application/json"
        if mime:
            headers["Content-Type"] = mime
        try:
            response = self.client.open(
                Request(self.base + path, data=data, headers=headers, method=method), timeout=20
            )
        except HTTPError as error:
            response = error
        with response:
            value = response.read()
            if "application/json" in response.headers.get("Content-Type", ""):
                value = json.loads(value)
            return response.status, value, response.headers

    def call(self, method, path, **kwargs):
        return self.http(method, path)[:2]

    def login(self, name, password=None):
        status, value, headers = self.http(
            "POST",
            "/api/v1/local-auth/login",
            body={"username": name, "password": password or self.password},
        )
        assert status == 200, ("login", status)
        assert value["mode"] == "production-local"
        assert headers["Cache-Control"] == "no-store"
        return value["access_token"]


def verify(run):
    base = "/api/v1/local-auth"
    admin = run.login("admin")
    admin_id = run.http("GET", base + "/me", admin)[1]["id"]
    for name in ("admin", "missing"):
        assert (
            run.http(
                "POST", base + "/login", body={"username": name, "password": "incorrect-password"}
            )[0]
            == 401
        )
    for token in (None, run.user_token, run.worker_token):
        assert run.http("GET", base + "/me", token)[0] == 401
    assert run.http("POST", "/api/v1/auth/login", body={})[0] == 404
    assert run.http("POST", "/internal/v1/work/claim", admin)[0] == 401
    accounts = "/api/v1/admin/accounts"
    ids = []
    for name in ("alice", "bob"):
        status, value, _ = run.http(
            "POST", accounts, admin, {"username": name, "password": run.password, "role": "USER"}
        )
        assert status == 201 and "password_hash" not in value
        ids.append(value["id"])
    alice, bob = run.login("alice"), run.login("bob")
    assert run.http("GET", accounts, alice)[0] == 403
    assert (
        run.http(
            "POST", accounts, alice, {"username": "evil", "password": run.password, "role": "ADMIN"}
        )[0]
        == 403
    )
    assert (
        run.http(
            "POST", accounts, admin, {"username": "alice", "password": run.password, "role": "USER"}
        )[0]
        == 409
    )
    # New passwords must be 6-15 characters.
    for bad in ("short", "x" * 16):
        body = {"username": "bad", "password": bad, "role": "USER"}
        assert run.http("POST", accounts, admin, body)[0] == 400, len(bad)
    assert (
        run.http(
            "POST",
            accounts,
            admin,
            {"username": "bad", "password": run.password, "role": "USER", "extra": 1},
        )[0]
        == 400
    )
    assert len(run.http("GET", accounts, admin)[1]["items"]) == 3
    assert run.http("GET", accounts + "?after=x&after=y", admin)[0] == 400
    assert run.http("GET", accounts + "?unknown=x", admin)[0] == 400
    # Audit failure must roll back the newly created identity and its credential together.
    before = run.sql("SELECT count(*) FROM users")
    run.sql("""CREATE FUNCTION reject_local_audit() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN IF NEW.action='LOCAL_CREATE' THEN RAISE EXCEPTION 'synthetic failure';
        END IF; RETURN NEW; END; $$;
        CREATE TRIGGER reject_local_audit BEFORE INSERT ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_local_audit();""")
    assert (
        run.http(
            "POST",
            accounts,
            admin,
            {"username": "rollback", "password": run.password, "role": "USER"},
        )[0]
        == 500
    )
    assert run.sql("SELECT count(*) FROM users") == before
    assert run.sql("SELECT count(*) FROM local_credentials WHERE username='rollback'") == "0"
    run.sql("DROP TRIGGER reject_local_audit ON audit_events")
    assert (
        run.http("POST", accounts + f"/{admin_id}/status", admin, {"status": "DISABLED"})[0] == 409
    )
    assert run.sql("SELECT count(*) FROM local_credentials WHERE role='ADMIN'") == "1"
    token_hash = hashlib.sha256(alice.encode()).hexdigest()
    assert run.sql(f"SELECT count(*) FROM local_sessions WHERE token_hash='{token_hash}'") == "1"
    print(
        "PASS P1/P2: independent identity, no defaults, admin management, strict input", flush=True
    )

    project = run.http("POST", "/api/v1/projects", alice, {"name": "synthetic"})[1]["id"]
    endpoint = f"/api/v1/projects/{project}/assets?kind=PRODUCT"
    status, asset, _ = run.http("POST", endpoint, alice, data=png(), mime="image/png")
    assert status == 201
    for token in (bob, admin):
        assert run.http("GET", f"/api/v1/projects/{project}", token)[0] == 404
        assert run.http("GET", asset["content_url"], token)[0] == 404
    assert run.http("GET", asset["content_url"], alice)[1] == png()
    run.sql(
        f"INSERT INTO generation_tasks(id,project_id,product_asset_id,feature_type,created_by,"
        f"idempotency_key,request_sha256,request_snapshot_json) VALUES ('private_task','{project}',"
        f"'{asset['id']}','SCENE','{ids[0]}','key','{'a' * 64}','{{}}')"
    )
    for token in (bob, admin):
        assert run.http("GET", "/api/v1/tasks/private_task", token)[0] == 404
        assert run.http("POST", "/api/v1/tasks/private_task/retry", token, {"attempt": 1})[0] == 404
    print("PASS P5: production project/asset/task isolation, no admin read bypass", flush=True)

    run.close()
    run.bootstrap.write_text("invalid bootstrap must not be consumed again", encoding="utf-8")
    run.start()
    assert run.http("GET", base + "/me", alice)[0] == 200
    # Race login using the old password against an administrator reset.
    race_password = secrets.token_urlsafe(9)
    with ThreadPoolExecutor(max_workers=2) as pool:
        login_future = pool.submit(
            run.http, "POST", base + "/login", None, {"username": "bob", "password": run.password}
        )
        reset_future = pool.submit(
            run.http,
            "POST",
            accounts + f"/{ids[1]}/password",
            admin,
            {"new_password": race_password},
        )
        login_result = login_future.result()
        assert reset_future.result()[0] == 204
    assert login_result[0] in (200, 401)
    if login_result[0] == 200:
        assert run.http("GET", base + "/me", login_result[1]["access_token"])[0] == 401
    assert run.http("GET", base + "/me", bob)[0] == 401
    bob = run.login("bob", race_password)
    for _ in range(19):
        run.login("bob", race_password)
    status, limited, _ = run.http(
        "POST", base + "/login", body={"username": "bob", "password": race_password}
    )
    assert status == 429 and limited["code"] == "SESSION_LIMIT_REACHED"
    new_password = secrets.token_urlsafe(9)
    assert (
        run.http(
            "POST",
            base + "/password",
            alice,
            {"current_password": "wrong", "new_password": new_password},
        )[0]
        == 401
    )
    second = run.login("alice")
    assert (
        run.http(
            "POST",
            base + "/password",
            alice,
            {"current_password": run.password, "new_password": new_password},
        )[0]
        == 204
    )
    for token in (alice, second):
        assert run.http("GET", base + "/me", token)[0] == 401
    alice = run.login("alice", new_password)
    assert (
        run.http("POST", accounts + f"/{ids[0]}/password", bob, {"new_password": run.password})[0]
        == 403
    )
    assert (
        run.http("POST", accounts + f"/{ids[0]}/password", admin, {"new_password": run.password})[0]
        == 204
    )
    assert run.http("GET", base + "/me", alice)[0] == 401
    alice = run.login("alice")
    assert run.http("POST", accounts + f"/{ids[0]}/status", admin, {"status": "DISABLED"})[0] == 204
    assert run.http("GET", base + "/me", alice)[0] == 401
    assert (
        run.http("POST", base + "/login", body={"username": "alice", "password": run.password})[0]
        == 401
    )
    assert run.http("POST", accounts + f"/{ids[0]}/status", admin, {"status": "ACTIVE"})[0] == 204
    alice = run.login("alice")
    assert run.http("POST", base + "/logout", alice)[0] == 204
    assert run.http("GET", base + "/me", alice)[0] == 401
    alice = run.login("alice")
    run.sql(
        f"UPDATE local_sessions SET expires_at=now()-interval '1 second' WHERE user_id='{ids[0]}'"
    )
    assert run.http("GET", base + "/me", alice)[0] == 401

    # Two administrators racing to disable one another must leave an active administrator.
    value = run.http(
        "POST",
        accounts,
        admin,
        {"username": "otheradmin", "password": run.password, "role": "ADMIN"},
    )[1]
    other = run.login("otheradmin")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda pair: run.http(
                    "POST", accounts + f"/{pair[1]}/status", pair[0], {"status": "DISABLED"}
                )[0],
                [(admin, value["id"]), (other, admin_id)],
            )
        )
    assert sorted(outcomes) == [204, 401], outcomes
    assert (
        run.sql(
            "SELECT count(*) FROM local_credentials c JOIN users u ON u.id=c.user_id "
            "WHERE c.role='ADMIN' AND u.status='ACTIVE'"
        )
        == "1"
    )
    assert int(run.sql("SELECT count(*) FROM audit_events WHERE action LIKE 'LOCAL_%'")) >= 10
    print(
        "PASS P3/P4: durable sessions, password/status revocation, expiry, admin race, audit",
        flush=True,
    )

    # Exhaust the shared persisted window; a restart must not reset it.
    run.sql("UPDATE local_auth_throttle SET window_started=now(), attempts=600")
    run.close()
    run.start()
    assert (
        run.http("POST", base + "/login", body={"username": "unknown", "password": run.password})[0]
        == 429
    )
    print("PASS P3: shared login throttle survives restart", flush=True)
    run.sql("UPDATE local_auth_throttle SET window_started=now()-interval '61 seconds'")
    assert (
        run.http("POST", base + "/login", body={"username": "unknown", "password": run.password})[0]
        == 401
    )


def run_production(env, work):
    work.mkdir(parents=True, exist_ok=True)
    run = ProductionCheck(env, work)
    try:
        run.start()
        verify(run)
    finally:
        run.close()
    empty_schema = run.schema + "_empty"
    run.sql(f"CREATE SCHEMA {empty_schema}", scoped=False)
    for index, override in enumerate(
        (
            {"APP_ENV": "development"},
            {"SERVER_SSL_ENABLED": "false"},
            {"SPRING_PROFILES_ACTIVE": "prod-local,dev-local"},
            {
                "DB_URL": run.env["DB_URL"].replace(run.schema, empty_schema),
                "PROD_BOOTSTRAP_FILE": str(work / "missing.json"),
            },
        )
    ):
        with (work / f"rejected-{index}.log").open("w") as log:
            process = subprocess.Popen(
                [tool("java"), "-jar", str(business_jar())],
                env={**run.env, **override},
                stdout=log,
                stderr=subprocess.STDOUT,
                **process_options(),
            )
            try:
                assert process.wait(timeout=40) != 0
            finally:
                stop(process)
    print(
        "PASS P1/P6: invalid production configurations fail closed; processes stopped", flush=True
    )
    logs = "".join(
        path.read_text(encoding="utf-8", errors="replace") for path in work.glob("*.log")
    )
    assert run.password not in logs and run.worker_token not in logs


if __name__ == "__main__":
    run_production(environment(), ROOT / ".artifacts/t04-prod" / uuid.uuid4().hex)
