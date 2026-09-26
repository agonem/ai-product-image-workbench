"""Verify migrations against a disposable native PostgreSQL cluster, never an existing DB."""

import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from common import ROOT, business_jar, environment, maven, process_options, stop, tool


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main() -> None:
    fallback = ROOT / ".tools/postgresql-17.11/pgsql/bin"
    pg_bin = Path(os.environ.get("PG_BIN", str(fallback))).resolve()
    suffix = ".exe" if os.name == "nt" else ""
    initdb, pg_ctl = [pg_bin / (name + suffix) for name in ("initdb", "pg_ctl")]
    if not initdb.is_file() or not pg_ctl.is_file():
        raise RuntimeError("Set PG_BIN to PostgreSQL 17 bin; see docs/09. No existing DB is used.")
    subprocess.run([str(pg_bin / ("postgres" + suffix)), "--version"], check=True)
    work = (
        ROOT / ".artifacts/postgres" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3))
    )
    work.mkdir(parents=True)
    data = work / "data"
    password_file = work / "init-password"
    password = secrets.token_urlsafe(32)
    password_file.write_text(password, encoding="utf-8")
    if os.name != "nt":
        password_file.chmod(0o600)
    env = environment()
    port = free_port()
    started = False
    try:
        with (work / "initdb.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                [
                    str(initdb),
                    "-D",
                    str(data),
                    "-U",
                    "workbench_test",
                    "--auth-host=scram-sha-256",
                    "--auth-local=scram-sha-256",
                    "--pwfile=" + str(password_file),
                    "--encoding=UTF8",
                    "--locale=C",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        password_file.unlink()
        subprocess.run(
            [
                str(pg_ctl),
                "-D",
                str(data),
                "-l",
                str(work / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {port}",
                "-w",
                "start",
            ],
            env=env,
            check=True,
        )
        started = True
        env.update(
            {
                "DB_TEST_URL": f"jdbc:postgresql://127.0.0.1:{port}/postgres",
                "DB_TEST_USER": "workbench_test",
                "DB_TEST_PASSWORD": password,
            }
        )
        if "--t06-prod-only" in sys.argv:
            from check_t06_prod import run_production_pages

            run_production_pages(env, work / "t06-prod")
            return
        if "--t04-prod-only" in sys.argv:
            from check_t04_prod import run_production

            run_production(env, work / "t04-prod")
            return
        if "--t06-only" in sys.argv:
            from check_t06 import run_workbench

            run_workbench(env, work / "t06")
            return
        print("DATABASE: isolated PostgreSQL; diagnostics:", work, flush=True)
        subprocess.run(
            [
                *maven(),
                f"-Dworkbench.final-name={business_jar().stem}",
                "-Pdatabase-tests",
                "verify",
            ],
            cwd=ROOT / "business-service",
            env=env,
            check=True,
        )
        env.update(
            {
                "SPRING_PROFILES_ACTIVE": "database",
                "DB_URL": env["DB_TEST_URL"],
                "DB_USER": env["DB_TEST_USER"],
                "DB_PASSWORD": password,
                "BUSINESS_HOST": "127.0.0.1",
                "BUSINESS_PORT": str(free_port()),
            }
        )
        java = [tool("java"), "-jar", str(business_jar())]
        with (work / "business.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                java, env=env, stdout=log, stderr=subprocess.STDOUT, **process_options()
            )
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Database profile exited; see business.log")
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{env['BUSINESS_PORT']}/api/v1/health", timeout=1
                        ) as response:
                            assert response.status == 200
                            break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise RuntimeError("Database profile health timeout")
            finally:
                stop(process)
        probe_env = {**env, "PGPASSWORD": password}
        migration = subprocess.run(
            [
                str(pg_bin / ("psql" + suffix)),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                "workbench_test",
                "-d",
                "postgres",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "SELECT count(*) FROM public.flyway_schema_history "
                "WHERE version IN ('1','2','3') AND success",
            ],
            env=probe_env,
            capture_output=True,
            text=True,
            check=True,
        )
        if migration.stdout.strip() != "3":
            raise RuntimeError("Database profile did not apply V1/V2/V3")
        from check_t05 import run_runtime

        run_runtime(env, work / "t05")
        from check_t04 import run_local

        run_local(env, work / "t04")
        from check_t04_prod import run_production

        run_production(env, work / "t04-prod")
        for key in ("DB_URL", "DB_USER", "DB_PASSWORD"):
            env.pop(key, None)
        with (work / "missing-config.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                java, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=45, **process_options()
            )
        if result.returncode == 0:
            raise RuntimeError("Database profile silently accepted missing configuration")
        print(
            "PASS: migrations, constraints, concurrent idempotency, "
            "database startup and missing-config failure."
        )
    finally:
        password_file.unlink(missing_ok=True)
        if started:
            subprocess.run(
                [str(pg_ctl), "-D", str(data), "-m", "fast", "-w", "stop"], env=env, check=True
            )
        print("Disposable cluster stopped. Retained diagnostics:", work)


if __name__ == "__main__":
    main()
