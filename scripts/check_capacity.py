"""Capacity check for PRD-G10 / ACC-17 (ADR-20260930-F): mock model, zero paid calls.

Production-mode Java (HTTPS, disposable PostgreSQL) and the real v4 Worker, whose model is the
acceptance mock with a fixed pause standing in for model latency. On this machine it measures:

1. overhead - what the system itself adds per image (model pause 0);
2. burst - 12 single-image tasks submitted at the same moment, with 1 and with 3 Worker slots;
3. day - one day's volume (150 images, 80 tasks of 1, 2 or 4 images) end to end with 2 slots.

Every task must succeed exactly once: one attempt, one paid-call permit per image, no duplicate
outputs. Real model latency is not measured here; the report projects the three-minute target
from the measured overhead and an assumed model latency. Nothing here is a platform promise.
"""

import base64
import json
import math
import secrets
import ssl
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from check_core import GIFT_RGB, PRODUCT_RGB, Core, find_font, synthetic_png
from check_t04_prod import ProductionCheck
from common import stop, tool

BURST_TASKS = 12
BURST_DELAY = 3.0  # seconds; the stand-in model latency for the burst runs
TARGET_SECONDS = 180  # PRD-G10: an acceptable wait of three minutes
DAY_MIX = [("GIFT", 2, 25), ("SCENE", 4, 15), ("SCENE", 1, 40)]  # 50 + 60 + 40 = 150 images


def percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(share * len(ordered)) - 1)]


class Capacity:
    def __init__(self, core, users):
        self.core, self.run, self.users = core, core.run, users

    def body(self, user, feature, count):
        product, gift, project = user["product"], user["gift"], user["project"]
        output = {
            "aspect_ratio": "1:1",
            "width": 800,
            "height": 800,
            "format": "png",
            "count": count,
        }
        if feature == "SCENE":
            return {
                "project_id": project,
                "feature_type": "SCENE",
                "product_asset_id": product,
                "scene_preset": "nursery",
                "output": output,
            }
        body = {
            "project_id": project,
            "feature_type": "GIFT",
            "product_asset_id": product,
            "gift_asset_id": gift,
            "gift_position": "BOTTOM_RIGHT",
            "background": {"mode": "SOLID", "color": "#F4F0E8"},
            "output": output,
        }
        if self.core.font:
            body["text"] = {
                "title": "下单即送\n防撞护角",
                "points": ["安全材质", "易清洗"],
                "color": "#112233",
                "size": 56,
                "align": "left",
                "box": {"x": 0.04, "y": 0.04, "width": 0.46, "height": 0.4},
            }
        return body

    def submit(self, jobs):
        """Posts every (user, feature, count) at once; returns {task id: image count}."""

        def post(job):
            user, feature, count = job
            body = self.body(user, feature, count)
            status, task = self.core.post(user["token"], "/api/v4/generation-tasks", body)
            assert status == 202, (status, task)
            return task["id"], count

        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return dict(pool.map(post, jobs))

    def settle(self, tasks, timeout):
        ids = ",".join(f"'{task}'" for task in tasks)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            done = self.run.sql(
                f"SELECT count(*) FROM generation_tasks WHERE id IN ({ids}) "
                "AND status IN ('SUCCEEDED','FAILED')"
            )
            if int(done) == len(tasks):
                return
            time.sleep(0.5)
        raise AssertionError(f"capacity tasks did not finish within {timeout}s")

    def measure(self, tasks):
        ids = ",".join(f"'{task}'" for task in tasks)
        rows = json.loads(
            self.run.sql(
                "SELECT jsonb_agg(jsonb_build_object("
                "'id', t.id, 'status', t.status, "
                "'created', extract(epoch FROM t.created_at), "
                "'started', extract(epoch FROM a.started_at), "
                "'ended', extract(epoch FROM a.ended_at), "
                "'attempts', (SELECT count(*) FROM task_attempts x WHERE x.task_id=t.id), "
                "'fences', (SELECT count(*) FROM generation_call_fences f "
                "WHERE f.attempt_id=a.id), "
                "'composites', (SELECT count(*) FROM artifacts r "
                "WHERE r.attempt_id=a.id AND r.kind='COMPOSITE'))) "
                "FROM generation_tasks t JOIN task_attempts a ON a.id=t.current_attempt_id "
                f"WHERE t.id IN ({ids})"
            )
        )
        for row in rows:
            count = tasks[row["id"]]
            # Exactly once: one attempt, one paid-call permit and one result per image.
            assert row["status"] == "SUCCEEDED", row
            assert row["attempts"] == 1 and row["fences"] == count == row["composites"], row
        waits = [row["started"] - row["created"] for row in rows]
        runs = [row["ended"] - row["started"] for row in rows]
        totals = [row["ended"] - row["created"] for row in rows]
        per_image = [(row["ended"] - row["started"]) / tasks[row["id"]] for row in rows]
        span = max(row["ended"] for row in rows) - min(row["created"] for row in rows)

        def spread(values):
            return {
                "p50": round(statistics.median(values), 2),
                "p95": round(percentile(values, 0.95), 2),
                "max": round(max(values), 2),
            }

        return {
            "tasks": len(rows),
            "images": sum(tasks.values()),
            "succeeded": len(rows),
            "span_seconds": round(span, 2),
            "queue_wait": spread(waits),
            "processing": spread(runs),
            "processing_per_image": spread(per_image),
            "submit_to_result": spread(totals),
        }

    def scenario(self, stack, name, *, slots, delay, waves, gap=0.0, timeout=600):
        worker = self.core.worker(
            once=False,
            extra={"WORKER_CONCURRENCY": str(slots), "MOCK_DELAY_SECONDS": str(delay)},
        )
        process, log = worker
        stack.callback(log.close)
        try:
            tasks = {}
            for index, jobs in enumerate(waves):
                if index and gap:
                    time.sleep(gap)
                tasks.update(self.submit(jobs))
            self.settle(tasks, timeout)
            assert process.poll() is None, "Worker exited; inspect worker.log"
        finally:
            stop(process)
        result = {"slots": slots, "model_delay_seconds": delay, **self.measure(tasks)}
        print(f"capacity {name}: {json.dumps(result, ensure_ascii=False)}", flush=True)
        return result


def projection(overhead):
    """Largest burst (images submitted at once) that still finishes within three minutes."""
    table = []
    for latency in (20, 40, 60, 90):
        per_image = latency + overhead
        rounds = int(TARGET_SECONDS // per_image)
        table.append(
            {
                "assumed_model_seconds": latency,
                "per_image_seconds": round(per_image, 1),
                "day_150_busy_hours_one_slot": round(150 * per_image / 3600, 2),
                "burst_within_3_min": {str(slots): slots * rounds for slots in (1, 2, 3, 4)},
            }
        )
    return table


def run_capacity_checks(env, work):
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
    report = {"mode": "mock model with a fixed pause, synthetic images, zero paid calls"}
    with ExitStack() as stack:
        stack.callback(run.close)
        run.start()
        admin = run.login("admin")
        face = {
            "name": "模拟 OpenRouter",
            "kind": "openrouter",
            "api_key": "mock-" + secrets.token_urlsafe(24),
            "use_proxy": False,
        }
        status, face, _ = run.http("POST", "/api/v1/admin/model-interfaces", admin, face)
        assert status == 201, status
        config = {
            "interface_id": face["id"],
            "name": "模拟主力",
            "model": "test/mock-model",
            "provider_tag": "mock",
            "enabled": True,
        }
        assert run.http("POST", "/api/v1/admin/provider-configs", admin, config)[0] == 201
        users = []
        for name in ("ops1", "ops2", "ops3"):
            body = {"username": name, "password": run.password, "role": "USER"}
            assert run.http("POST", "/api/v1/admin/accounts", admin, body)[0] == 201
            token = run.login(name)
            project = run.http("POST", "/api/v1/projects", token, {"name": name})[1]["id"]
            user = {"token": token, "project": project}
            for kind, shape in (("PRODUCT", PRODUCT_RGB), ("GIFT", GIFT_RGB)):
                status, asset, _ = run.http(
                    "POST",
                    f"/api/v1/projects/{project}/assets?kind={kind}",
                    token,
                    data=synthetic_png(shape=shape),
                    mime="image/png",
                )
                assert status == 201, status
                user[kind.lower()] = asset["id"]
            users.append(user)
        capacity = Capacity(core, users)
        burst = [[(users[i % 3], "GIFT", 1) for i in range(BURST_TASKS)]]

        report["overhead"] = capacity.scenario(
            stack,
            "overhead",
            slots=1,
            delay=0,
            waves=[[(users[i % 3], "GIFT", 1)] for i in range(6)],
            gap=0.2,
        )
        report["burst_1_slot"] = capacity.scenario(
            stack, "burst-1", slots=1, delay=BURST_DELAY, waves=burst
        )
        report["burst_3_slots"] = capacity.scenario(
            stack, "burst-3", slots=3, delay=BURST_DELAY, waves=burst
        )
        day = [
            (users[i % 3], feature, count)
            for feature, count, tasks in DAY_MIX
            for i in range(tasks)
        ]
        day = [day[i::8] for i in range(8)]  # eight mixed waves of ten tasks
        report["day_150_images"] = capacity.scenario(
            stack, "day", slots=2, delay=0.2, waves=day, gap=1.0, timeout=900
        )
        assert report["day_150_images"]["images"] == 150

        one = report["burst_1_slot"]["submit_to_result"]["max"]
        three = report["burst_3_slots"]["submit_to_result"]["max"]
        # Serial with one slot; three slots must actually run side by side.
        assert one >= BURST_TASKS * BURST_DELAY, one
        assert three <= one * 0.6, (one, three)
        overhead = report["overhead"]["processing_per_image"]["p50"]
        report["projection"] = projection(overhead)
    (work / "capacity-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"PASS CAPACITY: overhead {overhead}s/image; burst of {BURST_TASKS} with "
        f"{BURST_DELAY}s model pause: {one}s (1 slot) vs {three}s (3 slots); 150 images in "
        f"{report['day_150_images']['span_seconds']}s with 2 slots; all exactly once",
        flush=True,
    )
    return report
