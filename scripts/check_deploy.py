"""Deployment rehearsal without Docker: deploy/init.sh output drives a real prod-local Java.

Proves the generated keystore, internal CA (name-constrained), master key file, worker token and
first-admin verifier work together. Container images, nginx and the compose network are only
exercised on the target server (see deploy/README.md).
"""

import http.client
import json
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
from contextlib import ExitStack

from check_t04_prod import ProductionCheck
from common import ROOT, tool

SERVER_IP = "10.20.30.40"


class Pinned(http.client.HTTPSConnection):
    """Connect to the local Java but verify the certificate for a chosen name (like the Worker)."""

    def __init__(self, port, context, name):
        super().__init__(name, port, context=context, timeout=15)
        self.name = name

    def connect(self):
        raw = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.name)


def call(port, ca, method, path, body=None, token=None, name="business"):
    connection = Pinned(port, ssl.create_default_context(cafile=str(ca)), name)
    headers = {"Authorization": "Bearer " + token} if token else {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw) if raw.startswith(b"{") else raw
    finally:
        connection.close()


def rehearse(env, work):
    work.mkdir(parents=True)
    target = work / "deploy"
    ignored = shutil.ignore_patterns("secrets", "data", ".env", "workbench-ca.crt")
    shutil.copytree(ROOT / "deploy", target, ignore=ignored)
    (work / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/prod_accounts.py", work / "scripts")
    password = "rh-" + secrets.token_urlsafe(9)
    init_env = {**env, "PYTHON": sys.executable, "MSYS_NO_PATHCONV": "1"}
    subprocess.run(
        [tool("bash"), "init.sh", SERVER_IP, "admin"],
        cwd=target,
        input=password + "\n",
        text=True,
        env=init_env,
        capture_output=True,
        check=True,
    )
    again = subprocess.run(
        [tool("bash"), "init.sh", SERVER_IP, "admin"],
        cwd=target,
        input="",
        text=True,
        env=init_env,
        capture_output=True,
    )
    assert again.returncode == 1, "init.sh must refuse to overwrite an installation"
    private = target / "secrets"
    compose = (target / "compose.yaml").read_text(encoding="utf-8")
    for name in re.findall(r"file: \./secrets/(\S+)", compose):
        assert (private / name).is_file(), name
    assert f"SERVER_IP={SERVER_IP}" in (target / ".env").read_text(encoding="utf-8")
    assert (target / "workbench-ca.crt").read_bytes() == (private / "ca.pem").read_bytes()
    assert not (private / "business.key").exists(), "the business key lives only in the p12"
    print("PASS DEPLOY-1: init.sh creates every referenced secret once and refuses reruns")

    def read(name):
        return (private / name).read_text(encoding="utf-8").strip()

    run = ProductionCheck({k: v for k, v in env.items() if not k.startswith("OPENROUTER_")}, work)
    run.env.pop("PROVIDER_MASTER_KEY", None)
    run.env.update(
        {
            "SERVER_SSL_KEY_STORE": (private / "business.p12").as_uri(),
            "SERVER_SSL_KEY_STORE_TYPE": "PKCS12",
            "SERVER_SSL_KEY_STORE_PASSWORD": read("keystore_password"),
            "RUNTIME_WORKER_TOKEN": read("worker_token"),
            "PROVIDER_MASTER_KEY_FILE": str(private / "provider_master_key"),
            "PROD_BOOTSTRAP_FILE": str(private / "bootstrap" / "admin.json"),
        }
    )
    ca = private / "ca.pem"
    with ExitStack() as stack:
        stack.callback(run.close)
        run.start()
        # The Worker and nginx verify Java as "business"; any other name must fail.
        try:
            call(run.port, ca, "GET", "/api/v1/health", name="localhost")
            raise AssertionError("certificate accepted for a name outside the constraints")
        except ssl.SSLCertVerificationError:
            pass
        status, login = call(
            run.port,
            ca,
            "POST",
            "/api/v1/local-auth/login",
            {"username": "admin", "password": password},
        )
        assert status == 200 and login["mode"] == "production-local", status
        admin = login["access_token"]
        assert call(run.port, ca, "GET", "/api/v1/local-auth/me", token=admin)[0] == 200
        # The generated master key encrypts a stored provider key (mock value, never used).
        mock = "mock-" + secrets.token_urlsafe(24)
        face = {"name": "rehearsal", "kind": "openrouter", "api_key": mock, "use_proxy": False}
        status, saved = call(run.port, ca, "POST", "/api/v1/admin/model-interfaces", face, admin)
        assert status == 201 and mock not in json.dumps(saved), status
        config = {
            "interface_id": saved["id"],
            "name": "rehearsal",
            "model": "test/mock-model",
            "provider_tag": "mock",
            "enabled": False,
        }
        status, model = call(run.port, ca, "POST", "/api/v1/admin/provider-configs", config, admin)
        assert status == 201 and mock not in json.dumps(model), status
        # The generated Worker token is accepted; the admin session is not a Worker credential.
        worker = read("worker_token")
        assert call(run.port, ca, "POST", "/internal/v1/work/claim", {}, worker)[0] == 204
        assert call(run.port, ca, "POST", "/internal/v1/work/claim", {}, admin)[0] == 401
    print("PASS DEPLOY-2: prod-local Java runs on the generated keystore, key and first admin")


if __name__ == "__main__":
    raise SystemExit("Run python scripts/check_db.py --deploy-only")
