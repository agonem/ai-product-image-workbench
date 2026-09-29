"""Core acceptance for v4 whole-image generation (ADR-20260929), fully isolated.

Production-mode Java (HTTPS, disposable PostgreSQL, own JAR/ports), a real v4 Worker whose model
is mocked (scripts/mock_provider_worker.py - zero paid calls), synthetic images only. Result
pixels are checked with the image service's Pillow. Nothing is approved by these checks.
"""

import base64
import json
import secrets
import socket
import ssl
import struct
import subprocess
import threading
import time
import uuid
import zlib
from contextlib import ExitStack
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from check_t04_prod import ProductionCheck
from common import ROOT, process_options, stop, tool
from smoke import wait_ready

PRODUCT_RGB, GIFT_RGB, TEXT_RGB = (186, 64, 72), (40, 96, 200), (0x11, 0x22, 0x33)
PIXEL_CHECKER = """
import json, sys
from PIL import Image
path, checks = sys.argv[1], json.loads(sys.argv[2])
with Image.open(path) as image:
    fmt = image.format
    rgb = image.convert("RGB")
result = {"format": fmt, "size": list(rgb.size), "regions": []}
for box, color, tolerance in checks.get("regions", []):
    region = rgb.crop(tuple(box))
    colors = region.getcolors(region.width * region.height) or []
    result["regions"].append(
        any(max(abs(a - b) for a, b in zip(c, color)) <= tolerance for _, c in colors)
    )
print(json.dumps(result))
"""


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def synthetic_png(width=240, height=200, *, shape=PRODUCT_RGB):
    """White background with a solid rectangle item; pure stdlib encoder."""

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
            inside = width * 0.3 <= x < width * 0.7 and height * 0.2 <= y < height * 0.85
            row += bytes(shape) if inside else b"\xff\xff\xff"
        rows.append(bytes(row))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def find_font():
    """Deployment font for text overlay; the harness never ships or commits one."""
    for candidate in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


class Core:
    def __init__(self, run, work, certificate, font):
        self.run, self.work, self.certificate, self.font = run, work, certificate, font

    def worker(self, *, fail_at=None, font=True, once=True):
        env = {
            k: v
            for k, v in self.run.env.items()
            if not k.startswith(("DB_", "PGPASSWORD", "PROD_", "SERVER_SSL_", "OPENROUTER_"))
        }
        env.update(
            {
                "APP_ENV": "production",
                "WORKER_API_URL": self.run.base,
                "WORKER_CA_FILE": str(self.certificate),
                "WORKER_JOURNAL_ROOT": str(self.work / "journal"),
            }
        )
        if fail_at:
            env["MOCK_FAIL_AT"] = str(fail_at)
        if font and self.font:
            env["GENERATION_TEXT_FONT"] = self.font
        command = [
            tool("uv"),
            "run",
            "--frozen",
            "--directory",
            str(ROOT / "image-service"),
            "python",
            str(ROOT / "scripts/mock_provider_worker.py"),
        ] + (["--once"] if once else [])
        log = (self.work / "worker.log").open("a", encoding="utf-8")
        if not once:
            process = subprocess.Popen(
                command, env=env, stdout=log, stderr=subprocess.STDOUT, **process_options()
            )
            return process, log
        with log:
            subprocess.run(
                command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180
            )
        return None

    def post(self, token, path, body, key=None):
        request = Request(
            self.run.base + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Idempotency-Key": key or uuid.uuid4().hex,
            },
        )
        try:
            response = self.run.client.open(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None

    def get(self, token, task):
        return self.run.http("GET", f"/api/v4/generation-tasks/{task}", token)

    def generate(self, token, body, key=None, **worker):
        status, task = self.post(token, "/api/v4/generation-tasks", body, key)
        assert status == 202, (status, task)
        self.worker(**worker)
        return self.get(token, task["id"])[1]

    def image(self, token, artifact):
        status, data, _ = self.run.http("GET", f"/api/v1/artifacts/{artifact}/content", token)
        assert status == 200
        return data

    def inspect(self, data, regions):
        path = self.work / f"inspect-{secrets.token_hex(4)}.image"
        path.write_bytes(data)
        script = self.work / "pixel_checker.py"
        script.write_text(PIXEL_CHECKER, encoding="utf-8")
        result = subprocess.run(
            [tool("uv"), "run", "--frozen", "--directory", str(ROOT / "image-service")]
            + ["python", str(script), str(path), json.dumps({"regions": regions})],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout.strip().splitlines()[-1])

    def generations(self, task):
        attempt = self.run.sql(f"SELECT current_attempt_id FROM generation_tasks WHERE id='{task}'")
        info = self.run.sql(f"SELECT provider_info FROM task_attempts WHERE id='{attempt}'")
        return attempt, json.loads(info)["generations"]

    def fences(self, attempt):
        return self.run.sql(
            f"SELECT count(*) FROM generation_call_fences WHERE attempt_id='{attempt}'"
        )


def api_checks(core, admin, alice, bob, project):
    """V4-A1..A13 at the API boundary; every model call is the mock."""
    run, evidence, uploads = core.run, {}, {}
    for kind, shape in (("PRODUCT", PRODUCT_RGB), ("GIFT", GIFT_RGB)):
        data = synthetic_png(shape=shape)
        status, asset, _ = run.http(
            "POST",
            f"/api/v1/projects/{project}/assets?kind={kind}",
            alice,
            data=data,
            mime="image/png",
        )
        assert status == 201 and asset["review_status"] == "PENDING"
        uploads[kind] = (asset["id"], data)
    product, gift = uploads["PRODUCT"][0], uploads["GIFT"][0]
    options = run.http("GET", "/api/v1/workbench/options", alice)[1]["generation"]
    assert options["enabled"] and options["max_count"] == 4
    assert {"nursery", "wood_table"} <= {item["id"] for item in options["scene_presets"]}
    assert "prompt" not in json.dumps(options)
    output = {"aspect_ratio": "1:1", "width": 800, "height": 800, "format": "png", "count": 1}
    text = {
        "title": "轻松喂养\n宝宝更舒适",
        "points": ["安全材质", "防胀气设计", "易清洗"],
        "color": "#112233",
        "size": 56,
        "align": "left",
        "box": {"x": 0.04, "y": 0.04, "width": 0.46, "height": 0.56},
    }
    scene = {
        "project_id": project,
        "feature_type": "SCENE",
        "product_asset_id": product,
        "scene_preset": "nursery",
        "output": output,
    }

    # A1: scene, default one image, no cutout, frozen admin binding, product sent as reference.
    state = core.generate(alice, scene, "v4-scene")
    assert state["status"] == "SUCCEEDED", state
    assert state["review_status"] == "PENDING" and state["output"] == output
    assert state["request"]["scene_preset"] == "nursery" and len(state["artifacts"]) == 1
    assert run.sql("SELECT count(*) FROM assets WHERE kind='ALPHA'") == "0"
    attempt, gens = core.generations(state["id"])
    provenance = gens[0]["provenance"]
    assert provenance["model"] == "test/mock-model" and provenance["provider_tag"] == "mock"
    assert provenance["parameters"] == {"aspect_ratio": "1:1", "input_references": 1}
    assert "nursery" in provenance["prompt"] and "exact product" in provenance["prompt"]
    product_sha = run.sql(f"SELECT sha256 FROM assets WHERE id='{product}'")
    assert provenance["inputs"] == {"product_sha256": product_sha}
    assert core.fences(attempt) == "1"
    image = core.image(alice, state["artifacts"][0]["id"])
    checked = core.inspect(image, [[[0, 0, 800, 800], list(PRODUCT_RGB), 6]])
    assert checked["format"] == "PNG" and checked["size"] == [800, 800], checked
    assert checked["regions"] == [True], checked
    history = run.http("GET", f"/api/v1/projects/{project}/tasks", alice)[1]["items"]
    assert next(i for i in history if i["task"]["id"] == state["id"])["generation_v4"] is True
    evidence["scene"] = {"task": state["id"], "provenance_model": provenance["model"]}

    # A2: custom scene, two JPEG images at an exact 3:4 size, each a separate paid permit.
    custom = {k: v for k, v in scene.items() if k != "scene_preset"}
    custom.update(
        scene_prompt="浅色木桌，窗边自然光",
        style_prompt="温暖自然",
        output={"aspect_ratio": "3:4", "width": 600, "height": 800, "format": "jpeg", "count": 2},
    )
    state = core.generate(alice, custom, "v4-scene-2")
    assert state["status"] == "SUCCEEDED" and len(state["artifacts"]) == 2, state
    attempt, gens = core.generations(state["id"])
    assert len({g["base"]["sha256"] for g in gens}) == 2 and core.fences(attempt) == "2"
    for artifact in state["artifacts"]:
        checked = core.inspect(core.image(alice, artifact["id"]), [])
        assert checked["format"] == "JPEG" and checked["size"] == [600, 800]

    # A3: gift + product references, solid background, text overlaid by the program.
    gift_body = {
        "project_id": project,
        "feature_type": "GIFT",
        "product_asset_id": product,
        "gift_asset_id": gift,
        "gift_position": "BOTTOM_RIGHT",
        "background": {"mode": "SOLID", "color": "#F4F0E8"},
        "text": text,
        "output": output,
    }
    state = core.generate(alice, gift_body, "v4-gift")
    if core.font:
        assert state["status"] == "SUCCEEDED", state
        _, gens = core.generations(state["id"])
        provenance = gens[0]["provenance"]
        assert provenance["parameters"]["input_references"] == 2 and provenance["text_rendered"]
        assert "bottom-right" in provenance["prompt"] and "#F4F0E8" in provenance["prompt"]
        assert "top-left area" in provenance["prompt"]
        checked = core.inspect(
            core.image(alice, state["artifacts"][0]["id"]),
            [
                [[0, 0, 800, 800], list(GIFT_RGB), 6],
                [[0, 0, 800, 800], list(PRODUCT_RGB), 6],
                [[32, 32, 400, 480], list(TEXT_RGB), 40],
            ],
        )
        assert checked["regions"] == [True, True, True], checked
        evidence["gift"] = {"task": state["id"], "font": Path(core.font).name}
    else:
        assert state["status"] == "FAILED" and state["error"]["code"] == "GENERATION_FAILED"
        evidence["gift"] = "NOT TESTED: no deployment font on this machine"

    # A4: selling points - one image per selected style, verbatim points on every image.
    selling = {
        "project_id": project,
        "feature_type": "SELLING_POINT",
        "product_asset_id": product,
        "styles": ["warm", "green"],
        "text": text,
        "output": dict(output, count=2),
    }
    state = core.generate(alice, selling, "v4-selling")
    selling_task = state["id"]
    if core.font:
        assert state["status"] == "SUCCEEDED" and len(state["artifacts"]) == 2, state
        _, gens = core.generations(state["id"])
        assert "warm cream" in gens[0]["provenance"]["prompt"]
        assert "sage green" in gens[1]["provenance"]["prompt"]
        badges = ((0xF6, 0xE9, 0xDA), (0xE4, 0xF0, 0xE3))
        for artifact, badge in zip(state["artifacts"], badges, strict=True):
            checked = core.inspect(
                core.image(alice, artifact["id"]),
                [[[32, 32, 400, 480], list(TEXT_RGB), 40], [[32, 32, 400, 480], list(badge), 12]],
            )
            assert checked["regions"] == [True, True], checked

    # A5: contract and policy rejections happen before any work is queued.
    before = run.sql("SELECT count(*) FROM generation_tasks")
    for body, expected in (
        (dict(selling, output=dict(output, count=1)), 422),
        (dict(scene, output=dict(output, height=600)), 422),
        (dict(scene, output=dict(output, count=5)), 422),
        (dict(scene, scene_preset="missing"), 422),
        (dict(scene, product_asset_id=gift), 422),
        (dict(scene, template_version_id="x"), 400),
    ):
        assert core.post(alice, "/api/v4/generation-tasks", body)[0] == expected, body
    assert core.post(bob, "/api/v4/generation-tasks", scene)[0] == 404
    assert run.sql("SELECT count(*) FROM generation_tasks") == before
    # A6: owner-only reads; the admin role grants no cross-project access.
    for token in (bob, admin):
        assert core.get(token, selling_task)[0] == 404
    # A7: idempotency - same key and body returns the task; a changed body conflicts.
    same = core.post(alice, "/api/v4/generation-tasks", scene, "v4-scene")[1]
    assert same["id"] == evidence["scene"]["task"]
    changed = dict(scene, scene_preset="bathroom")
    assert core.post(alice, "/api/v4/generation-tasks", changed, "v4-scene")[0] == 409

    # A8: re-typeset reuses the stored model output - no model call, no paid permit.
    if core.font:
        new_text = dict(text, title="新标题", align="right", color="#445566")
        path = f"/api/v4/generation-tasks/{selling_task}/retypeset"
        status, task = core.post(alice, path, {"ordinal": 1, "text": new_text}, "v4-retype")
        assert status == 202, (status, task)
        assert core.post(bob, path, {"ordinal": 1, "text": new_text})[0] == 404
        assert core.post(alice, path, {"ordinal": 2, "text": new_text})[0] == 409
        core.worker()
        state = core.get(alice, task["id"])[1]
        assert state["status"] == "SUCCEEDED", state
        assert state["source"] == {"task_id": selling_task, "ordinal": 1}
        attempt, gens = core.generations(task["id"])
        _, source_gens = core.generations(selling_task)
        assert gens[0]["provenance"]["output_source"] == "retypeset"
        assert gens[0]["base"]["sha256"] == source_gens[1]["base"]["sha256"]
        assert core.fences(attempt) == "0"
        checked = core.inspect(
            core.image(alice, state["artifacts"][0]["id"]),
            # Right-aligned inside the same text box (x 32..400).
            [[[216, 32, 400, 480], [0x44, 0x55, 0x66], 40]],
        )
        assert checked["regions"] == [True], checked
        evidence["retypeset"] = {"task": task["id"], "source": selling_task}

    # A9: a failed model call publishes nothing and is retryable; the retry succeeds.
    state = core.generate(alice, dict(scene, scene_preset="kitchen"), "v4-fail", fail_at=1)
    assert state["status"] == "FAILED" and state["artifacts"] == [], state
    assert state["error"]["code"] == "PROVIDER_UNAVAILABLE"
    status, retried, _ = run.http(
        "POST", f"/api/v1/tasks/{state['id']}/retry", alice, {"attempt": 1}
    )
    assert status == 202 and retried["attempt"] == 2, (status, retried)
    core.worker()
    assert core.get(alice, state["id"])[1]["status"] == "SUCCEEDED"

    # A10: text without a deployment font fails before any paid call, and is retryable.
    state = core.generate(alice, selling, "v4-nofont", font=False)
    assert state["status"] == "FAILED" and state["error"]["code"] == "GENERATION_FAILED"
    nofont = state["id"]
    attempt = run.sql(f"SELECT current_attempt_id FROM generation_tasks WHERE id='{state['id']}'")
    assert core.fences(attempt) == "0"

    # A11: withdrawn routes are gone; a legacy scene v3 task stays readable but never re-runs.
    for method, path, body in (
        ("POST", "/api/v3/scene-tasks", {}),
        ("GET", f"/api/v3/scene-tasks/{selling_task}", None),
        ("POST", f"/api/v1/assets/{product}/cutouts", {"tolerance": 8}),
        ("GET", f"/api/v1/assets/{product}/cutouts", None),
        ("POST", f"/api/v1/assets/{product}/review", {"decision": "APPROVED"}),
    ):
        assert run.http(method, path, alice, body)[0] == 404, (method, path)
    # Snapshots are immutable, so the legacy row is a copy of the A10 task marked as v3.
    legacy, legacy_attempt = "legacyv3task", "legacyv3attempt"
    run.sql(
        "INSERT INTO generation_tasks(id,project_id,product_asset_id,gift_asset_id,feature_type,"
        "status,created_by,idempotency_key,request_sha256,request_snapshot_json,"
        "template_snapshot_json,worker_snapshot_json,provider_config_version) "
        f"SELECT '{legacy}',project_id,product_asset_id,gift_asset_id,feature_type,'FAILED',"
        "created_by,'legacy-v3',request_sha256,request_snapshot_json,template_snapshot_json,"
        "jsonb_set(worker_snapshot_json,'{schema_version}','3'),provider_config_version "
        f"FROM generation_tasks WHERE id='{state['id']}'; "
        "INSERT INTO task_attempts(id,task_id,attempt_no,status,started_at,ended_at,error_code,"
        f"retryable) VALUES ('{legacy_attempt}','{legacy}',1,'FAILED',now(),now(),"
        "'PROVIDER_UNAVAILABLE',true); "
        f"UPDATE generation_tasks SET current_attempt_id='{legacy_attempt}' WHERE id='{legacy}'"
    )
    assert run.http("GET", f"/api/v1/tasks/{legacy}", alice)[1]["status"] == "FAILED"
    before = run.sql("SELECT count(*) FROM outbox_events")
    assert run.http("POST", f"/api/v1/tasks/{legacy}/retry", alice, {"attempt": 1})[0] == 409
    assert run.sql("SELECT count(*) FROM outbox_events") == before

    # A12: model catalog (ADR-20260929-C). Only OpenRouter / OpenAI / Gemini with their own fields;
    # several enabled models; a task binds the chosen model or the default; a disabled model is
    # refused and the default cannot be disabled; a new key retires the old row but keeps the name,
    # the default and every frozen task binding; the proxy is masked and only models marked "use
    # proxy" receive it (the mock records the route it was given).
    configs = "/api/v1/admin/provider-configs"
    common = {"api_key": "mock-key", "enabled": True, "use_proxy": False}
    for bad in (
        {"name": "x", "provider": "openai", "model": "gpt-image-2", "provider_tag": "x"},
        {"name": "x", "provider": "openai-compatible", "model": "m", "base_url": "https://a.test"},
        {"name": " ", "provider": "gemini", "model": "gemini-2.5-flash-image"},
        {"name": "x", "provider": "unknown", "model": "m"},
    ):
        assert run.http("POST", configs, admin, {**bad, **common})[0] == 400, bad
    gemini_key = "mock-" + secrets.token_urlsafe(24)
    status, gemini, _ = run.http(
        "POST",
        configs,
        admin,
        {
            "name": "Gemini 测试",
            "provider": "gemini",
            "model": "gemini-2.5-flash-image",
            "api_key": gemini_key,
            "enabled": True,
            "use_proxy": True,
        },
    )
    assert status == 201 and not gemini["default"], (status, gemini)
    listing = run.http("GET", configs, admin)[1]
    assert gemini_key not in json.dumps(listing)
    default = next(item for item in listing["items"] if item["default"])
    assert run.http("GET", configs, alice)[0] == 403
    choices = run.http("GET", "/api/v1/workbench/options", alice)[1]["models"]
    assert {m["id"] for m in choices} == {default["id"], gemini["id"]}
    assert "key" not in json.dumps(choices)
    proxy = "/api/v1/admin/network-proxy"
    assert run.http("PUT", proxy, admin, {"proxy_url": "http://proxy.internal:3128/x"})[0] == 400
    body = {"proxy_url": "http://user:secret@proxy.internal:3128"}
    assert run.http("PUT", proxy, admin, body)[0] == 204
    shown = run.http("GET", proxy, admin)[1]
    assert shown["configured"] and shown["mask"] == "http://****@proxy.internal:3128", shown
    assert "secret" not in json.dumps(run.http("GET", configs, admin)[1])
    chosen = core.generate(
        alice, dict(scene, scene_preset="outdoor", model_id=gemini["id"]), "v4-gemini"
    )
    assert chosen["status"] == "SUCCEEDED", chosen
    assert core.generations(chosen["id"])[1][0]["provenance"]["provider"] == (
        "mock-acceptance-only:gemini:proxy"
    )
    fallback = core.generate(alice, dict(scene, scene_preset="bedroom"), "v4-default")
    assert core.generations(fallback["id"])[1][0]["provenance"]["provider"] == (
        "mock-acceptance-only:openrouter:direct"
    )
    assert (
        run.http("POST", f"{configs}/{gemini['id']}/settings", admin, {"enabled": False})[0] == 204
    )
    refused = core.post(alice, "/api/v4/generation-tasks", dict(scene, model_id=gemini["id"]))
    assert refused[0] == 422 and refused[1]["code"] == "MODEL_UNAVAILABLE", refused
    status, body, _ = run.http(
        "POST", f"{configs}/{default['id']}/settings", admin, {"enabled": False}
    )
    assert status == 409 and body["code"] == "DEFAULT_MODEL", (status, body)
    status, rotated, _ = run.http(
        "POST",
        f"{configs}/{default['id']}/key",
        admin,
        {"api_key": "mock-" + secrets.token_urlsafe(20)},
    )
    assert status == 201 and rotated["default"] and rotated["name"] == default["name"], rotated
    assert default["id"] not in {item["id"] for item in run.http("GET", configs, admin)[1]["items"]}
    frozen = run.sql(
        f"SELECT provider_config_version FROM generation_tasks WHERE id='{fallback['id']}'"
    )
    assert frozen == default["id"]
    assert run.http("DELETE", proxy, admin)[0] == 204
    assert run.http("GET", proxy, admin)[1] == {"configured": False}
    evidence["models"] = {"chosen": chosen["id"], "default": fallback["id"]}

    for kind, (asset, data) in uploads.items():
        assert run.http("GET", f"/api/v1/assets/{asset}/content", alice)[1] == data, kind

    # A13: owner deletion (D-08). Others and the admin get 404; a result goes together with the
    # model output behind it; an original used by a queued task is kept; deleted items vanish
    # from every read path while tasks and audit keep their history.
    scene_task = evidence["scene"]["task"]
    artifact = core.get(alice, scene_task)[1]["artifacts"][0]["id"]
    for token in (bob, admin):
        assert run.http("DELETE", f"/api/v1/artifacts/{artifact}", token)[0] == 404
    assert run.http("DELETE", f"/api/v1/artifacts/{artifact}", alice)[0] == 204
    assert run.http("GET", f"/api/v1/artifacts/{artifact}/content", alice)[0] == 404
    detail = core.get(alice, scene_task)[1]
    assert detail["status"] == "SUCCEEDED" and detail["artifacts"] == [] and detail["bases"] == []
    assert run.http("DELETE", f"/api/v1/artifacts/{artifact}", alice)[0] == 404
    retype = {"ordinal": 0, "text": text}
    path = f"/api/v4/generation-tasks/{scene_task}/retypeset"
    assert core.post(alice, path, retype)[0] == 409
    status, queued = core.post(
        alice, "/api/v4/generation-tasks", dict(scene, scene_preset="bedroom")
    )
    assert status == 202 and queued["status"] == "QUEUED", (status, queued)
    for token in (bob, admin):
        assert run.http("DELETE", f"/api/v1/assets/{product}", token)[0] == 404
    status, body, _ = run.http("DELETE", f"/api/v1/assets/{product}", alice)
    assert status == 409 and body["code"] == "ASSET_IN_USE", (status, body)
    core.worker()
    assert core.get(alice, queued["id"])[1]["status"] == "SUCCEEDED"
    assert run.http("DELETE", f"/api/v1/assets/{product}", alice)[0] == 204
    assert run.http("GET", f"/api/v1/assets/{product}/content", alice)[0] == 404
    listed = run.http("GET", f"/api/v1/projects/{project}/assets", alice)[1]["items"]
    assert product not in {item["id"] for item in listed} and gift in {i["id"] for i in listed}
    assert (
        core.post(alice, "/api/v4/generation-tasks", dict(scene, scene_preset="kitchen"))[0] == 422
    )
    status, body, _ = run.http("POST", f"/api/v1/tasks/{nofont}/retry", alice, {"attempt": 1})
    assert status == 409 and body["code"] == "ASSET_DELETED", (status, body)
    assert core.get(alice, queued["id"])[1]["status"] == "SUCCEEDED"
    deleted = run.sql("SELECT count(*) FROM deletions")
    audited = run.sql(
        "SELECT count(*) FROM audit_events WHERE action IN ('ASSET_DELETED','ARTIFACT_DELETED')"
    )
    assert deleted == "3" and audited == "3", (deleted, audited)
    evidence["deletion"] = {"artifact": artifact, "asset": product}
    return evidence


def watch_exit(process, path):
    """Diagnostics: record when and how a page server exits during the page tests."""

    def watch():
        code = process.wait()
        path.write_text(f"{time.strftime('%H:%M:%S')} exit code {code}\n", encoding="utf-8")

    threading.Thread(target=watch, daemon=True).start()


def browser_checks(core, stack):
    """Real Chromium over the rebuilt page; runs once tests-core specs exist."""
    if not any((ROOT / "frontend/tests-core").glob("*.spec.ts")):
        return False
    run, work = core.run, core.work
    port = free_port()
    for name, shape in (("product", PRODUCT_RGB), ("gift", GIFT_RGB)):
        (work / f"browser-{name}.png").write_bytes(synthetic_png(320, 280, shape=shape))
    page_env = {
        k: v
        for k, v in run.env.items()
        if not k.startswith(("DB_", "PGPASSWORD", "RUNTIME_", "PROD_", "SERVER_SSL_"))
    }
    page_env.update(
        {
            "VITE_AUTH_MODE": "production-local",
            "VITE_ACCEPTANCE_MODE": "mock-provider",
            "NODE_EXTRA_CA_CERTS": str(core.certificate),
            "DEV_HOST": "127.0.0.1",
            "DEV_PORT": str(port),
            "DEV_API_TARGET": run.base,
            "T06_BASE_URL": f"http://127.0.0.1:{port}",
            "T06_PASSWORD": run.password,
            "T06_ARTIFACTS": str(work / "browser"),
            "CORE_PRODUCT_FILE": str(work / "browser-product.png"),
            "CORE_GIFT_FILE": str(work / "browser-gift.png"),
            "CORE_FONT": "1" if core.font else "",
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
    watch_exit(vite, work / "vite-exit.log")
    worker, worker_log = core.worker(once=False)
    stack.callback(worker_log.close)
    stack.callback(stop, worker)
    with (work / "browser.log").open("w", encoding="utf-8") as browser_log:
        subprocess.run(
            [tool("npm"), "exec", "--", "playwright", "test", "--config=playwright.core.config.ts"],
            cwd=ROOT / "frontend",
            env=page_env,
            stdout=browser_log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=600,
        )
    return True


def run_core_checks(env, work):
    work.mkdir(parents=True)
    run = ProductionCheck({k: v for k, v in env.items() if not k.startswith("OPENROUTER_")}, work)
    run.env["PROVIDER_MASTER_KEY"] = base64.b64encode(secrets.token_bytes(32)).decode()
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
    core = Core(run, work, certificate, find_font())
    evidence = {"mode": "synthetic images, mock model, zero paid calls"}
    with ExitStack() as stack:
        stack.callback(run.close)
        run.start()
        admin = run.login("admin")
        for name in ("alice", "bob"):
            body = {"username": name, "password": run.password, "role": "USER"}
            assert run.http("POST", "/api/v1/admin/accounts", admin, body)[0] == 201
        # A frozen admin binding proves the lease-delivered configuration reaches the model.
        mock_key = "mock-" + secrets.token_urlsafe(24)
        config = {
            "name": "模拟主力",
            "provider": "openrouter",
            "model": "test/mock-model",
            "provider_tag": "mock",
            "api_key": mock_key,
            "enabled": True,
            "use_proxy": False,
        }
        assert run.http("POST", "/api/v1/admin/provider-configs", admin, config)[0] == 201
        alice, bob = run.login("alice"), run.login("bob")
        project = run.http("POST", "/api/v1/projects", alice, {"name": "v4 core"})[1]["id"]
        evidence["api"] = api_checks(core, admin, alice, bob, project)
        print(
            "PASS V4-A1..A13: three entries, references, text, retypeset, isolation, "
            "withdrawn routes, model catalog and proxy, owner deletion",
            flush=True,
        )
        if browser_checks(core, stack):
            print("PASS V4-B: rebuilt page flows with the mock model", flush=True)
        for log in work.glob("*.log"):
            assert mock_key not in log.read_text(errors="replace"), log.name
    (work / "core-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
