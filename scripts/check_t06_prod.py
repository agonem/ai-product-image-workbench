"""Production authentication browser checks; isolated DB, JAR, ports and test trust."""

import json
import socket
import ssl
import subprocess
from contextlib import ExitStack
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from check_t04_prod import ProductionCheck
from check_t05 import png
from common import ROOT, process_options, stop, tool
from smoke import wait_ready


def run_production_pages(env, work):
    work.mkdir(parents=True, exist_ok=True)
    run = ProductionCheck(env, work)
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
    # Trust only this run's certificate, preserving hostname and chain validation.
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
        assert run.http("GET", "/api/v1/admin/accounts", alice)[0] == 403
        project = run.http("POST", "/api/v1/projects", alice, {"name": "Alice private"})[1]["id"]
        status, asset, _ = run.http(
            "POST",
            f"/api/v1/projects/{project}/assets?kind=PRODUCT",
            alice,
            data=png(),
            mime="image/png",
        )
        assert status == 201
        assert run.http("GET", f"/api/v1/projects/{project}/assets", admin)[0] == 404
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        page_env = {
            **run.env,
            "VITE_AUTH_MODE": "production-local",
            "NODE_EXTRA_CA_CERTS": str(certificate),
            "DEV_HOST": "127.0.0.1",
            "DEV_PORT": str(port),
            "DEV_API_TARGET": run.base,
            "T06_BASE_URL": f"http://127.0.0.1:{port}",
            "T06_PASSWORD": run.password,
            "T06_ARTIFACTS": str(work / "browser"),
            "T06_PSQL": json.dumps(run.pg_command),
            "T06_SCHEMA": run.schema,
            "T06_PROJECT": project,
            "T06_ASSET": asset["id"],
        }
        output = work / "frontend-dist"
        subprocess.run(
            [tool("npm"), "run", "build", "--", "--outDir", str(output)],
            cwd=ROOT / "frontend",
            env=page_env,
            check=True,
        )
        log_path = work / "vite.log"
        log = stack.enter_context(log_path.open("w", encoding="utf-8"))
        process = subprocess.Popen(
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
        stack.callback(stop, process)
        wait_ready(page_env["T06_BASE_URL"], process, log_path)
        subprocess.run(
            [
                tool("npm"),
                "exec",
                "--",
                "playwright",
                "test",
                "--config=playwright.production.config.ts",
            ],
            cwd=ROOT / "frontend",
            env=page_env,
            check=True,
        )
    print(
        "PASS ACC-T06-PROD: real browser to production Java; isolated processes stopped", flush=True
    )
