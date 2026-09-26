"""ACC-T06: dev-local Java, disposable fixtures and real Chromium page tests."""

import json
import socket
import subprocess
import uuid
from contextlib import ExitStack

from check_t04 import LocalCheck
from check_t05 import png
from common import ROOT, environment, process_options, stop, tool
from smoke import wait_ready


def verify_api(run):
    run.seed()
    run.sql("UPDATE projects SET owner_id='alice_id' WHERE id='p'")
    run.user_token = run.login("alice")
    bob = run.login("bob")
    paths = ["/api/v1/workbench/options", "/api/v1/projects/p/assets", "/api/v1/projects/p/tasks"]
    for path in paths:
        assert run.call("GET", path, auth=None)[0] == 401
        assert run.call("GET", path, auth="worker")[0] == 401
        assert run.call("GET", path + "?unexpected=1")[0] == 400
    for path in paths[1:]:
        assert run.http("GET", path, token=bob)[0] == 404
        for query in ("?offset=-1", "?offset=10001", "?offset=0&offset=1", "?offset=no"):
            assert run.call("GET", path + query)[0] == 400
    status, options = run.call("GET", paths[0])
    assert status == 200 and options["generation_available"] is False
    assert options["mode"] == "development-only"
    assert options["output_presets"] == [{"id": "t05_transport_fixture", "test_fixture": True}]
    assert options["templates"][0]["id"] == "layout_v1"
    assert "config" not in json.dumps(options)
    run.sql("UPDATE templates SET state='DISABLED' WHERE id='layout'")
    assert run.call("GET", paths[0])[1]["templates"] == []
    run.sql("UPDATE templates SET state='PUBLISHED' WHERE id='layout'")
    status, page, headers = run.http("GET", paths[1], token=run.user_token)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert {a["id"] for a in page["items"]} == {"product", "gift"}
    assert next(a for a in page["items"] if a["id"] == "product")["cutout_ready"]
    assert "object_key" not in json.dumps(page)
    status, uploaded, _ = run.http(
        "POST", paths[1] + "?kind=PRODUCT", token=run.user_token, data=png(), mime="image/png"
    )
    assert status == 201
    page = run.call("GET", paths[1])[1]
    assert not next(a for a in page["items"] if a["id"] == uploaded["id"])["cutout_ready"]
    pending = run.request()
    pending["product_asset_id"] = uploaded["id"]
    assert run.call("POST", "/api/v1/tasks", pending, key="unapproved")[0] == 422
    # Upper pagination boundary must never return an unusable next_offset.
    run.sql("""INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height)
        SELECT 'page_'||n,'p','GIFT','fixtures/page_'||n||'.png',repeat('0',64),4,3
        FROM generate_series(1,10021) AS n""")
    for offset in (9999, 10000):
        boundary = run.call("GET", paths[1] + f"?offset={offset}")[1]
        assert boundary["next_offset"] is None
    run.sql("DELETE FROM assets WHERE id LIKE 'page_%'")
    print(
        "PASS ACC-T06 A2/A3/A6: scoped lists, no-store, configuration and pending alpha", flush=True
    )
    tasks = []
    for feature in ("GIFT", "SCENE", "SELLING_POINT"):
        task = run.create("t06-" + feature, feature)
        assert run.create("t06-" + feature, feature)["id"] == task["id"]
        run.worker()
        assert run.state(task)["status"] == "SUCCEEDED"
        tasks.append(task)
    # Pagination data stays in the disposable schema and is drained by the ordinary Worker.
    for number in range(19):
        run.create(f"history-{number}")
    page = run.call("GET", paths[2])[1]
    assert len(page["items"]) == 20 and page["next_offset"] == 20
    older = run.call("GET", paths[2] + "?offset=20")[1]
    assert len(older["items"]) == 2 and older["next_offset"] is None
    assert not (
        {v["task"]["id"] for v in page["items"]} & {v["task"]["id"] for v in older["items"]}
    )
    assert all(v["test_fixture"] for v in page["items"] + older["items"])
    run.close()
    run.start()
    run.user_token = run.login("alice")
    assert len(run.call("GET", paths[2])[1]["items"]) == 20
    print(
        "PASS ACC-T06 A1/A4/A6/A7: three entries, idempotency, "
        "history paging/restart and fixture labels",
        flush=True,
    )


def run_workbench(env, work):
    work.mkdir(parents=True, exist_ok=True)
    run = LocalCheck(env, work)
    run.env["DEV_SESSION_SECONDS"] = "900"
    with ExitStack() as stack:
        stack.callback(run.close)
        run.start()
        verify_api(run)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        page_env = {
            **run.env,
            "DEV_HOST": "127.0.0.1",
            "DEV_PORT": str(port),
            "DEV_API_TARGET": run.base,
            "T06_BASE_URL": f"http://127.0.0.1:{port}",
            "T06_PASSWORD": run.password,
            "T06_ARTIFACTS": str(work / "browser"),
            "WORKER_JOURNAL_ROOT": str(work / "ordinary-worker"),
        }
        for name, command, cwd in (
            ("vite", [tool("npm"), "run", "dev"], ROOT / "frontend"),
            (
                "worker",
                [tool("uv"), "run", "--frozen", "python", "-m", "image_service.worker"],
                ROOT / "image-service",
            ),
        ):
            log_path = work / f"{name}.log"
            log = stack.enter_context(log_path.open("w", encoding="utf-8"))
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=page_env,
                stdout=log,
                stderr=subprocess.STDOUT,
                **process_options(),
            )
            stack.callback(stop, process)
            if name == "vite":
                wait_ready(page_env["T06_BASE_URL"], process, log_path)
        subprocess.run(
            [tool("npm"), "run", "test:page"], cwd=ROOT / "frontend", env=page_env, check=True
        )
    print("PASS ACC-T06: dev-local API and browser checks; owned services stopped", flush=True)


if __name__ == "__main__":
    run_workbench(environment(), ROOT / ".artifacts/t06" / uuid.uuid4().hex)
