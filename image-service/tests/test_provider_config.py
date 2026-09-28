"""Lease-delivered provider configuration and the non-paid capability check relay."""

import base64

import pytest
from fastapi.testclient import TestClient

from image_service import app as app_module
from image_service.background import BackgroundError, BackgroundResult
from image_service.background_config import OpenRouterConfig, config_from_mapping


def test_config_from_mapping_accepts_valid_claim():
    config = config_from_mapping(
        {"api_key": "sk-test-1234567890", "model": "vendor/model-1", "provider_tag": "openai"}
    )
    assert (config.api_key, config.model, config.provider_tag) == (
        "sk-test-1234567890",
        "vendor/model-1",
        "openai",
    )


@pytest.mark.parametrize(
    "mapping",
    [
        {"model": "vendor/model-1", "provider_tag": "openai"},
        {"api_key": "k", "provider_tag": "openai"},
        {"api_key": "k", "model": "no-slash", "provider_tag": "openai"},
        {"api_key": "k", "model": "vendor/model-1", "provider_tag": "bad tag"},
    ],
)
def test_config_from_mapping_rejects_invalid_claim(mapping):
    with pytest.raises(BackgroundError) as error:
        config_from_mapping(mapping)
    assert error.value.code == "CONFIGURATION"


class LocalApi:
    """Minimal Worker transport double; scene processing only needs assets and outputs."""

    def __init__(self):
        self.inputs = {}
        self.outputs = []

    def call(self, method, path, **kwargs):
        if method == "GET":
            return self.inputs[path.split("/")[-1]]
        if method == "POST":
            return None
        self.outputs.append(kwargs["data"])
        return {"object_key": "outputs/test/x", "sha256": "0" * 64, "width": 4, "height": 4}


def scene_request():
    return {
        "schema_version": 3,
        "task_id": "task",
        "attempt_id": "attempt",
        "correlation_id": "task",
        "feature_type": "SCENE",
        "scene_custom_prompt": "empty table",
        "layout": {"product": {"x": 0.2, "y": 0.2, "width": 0.5, "height": 0.5}},
        "output": {"aspect_ratio": "1:1", "width": 256, "height": 256, "format": "png", "count": 1},
        "product_asset": {"asset_id": "a", "sha256": "0" * 64},
        "product_alpha_asset": {"asset_id": "b", "sha256": "0" * 64},
    }


@pytest.fixture()
def worker_stubs(monkeypatch):
    import io

    from PIL import Image

    def png(color):
        stream = io.BytesIO()
        Image.new("RGB", (64, 64), color).save(stream, format="PNG")
        return stream.getvalue()

    captured = {}

    class RecordingAdapter:
        def __init__(self, config):
            captured["config"] = config

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def generate(self, request):
            data = png((10, 30, 40))
            return BackgroundResult(
                data,
                64,
                64,
                {
                    "provider": "test-only",
                    "model": "mock-image",
                    "prompt": request.prompt,
                    "parameters": {},
                    "correlation_id": request.correlation_id,
                    "review_status": "PENDING",
                },
            )

    def fake_scene(api, request, lease, adapter, *, cancelled=None):
        captured["adapter"] = adapter
        return {"schema_version": 3, "event_type": "image.task.completed.v3", "artifacts": []}

    monkeypatch.setattr("image_service.openrouter.OpenRouterAdapter", RecordingAdapter)
    monkeypatch.setattr("image_service.scene.process_scene", fake_scene)
    return captured


def test_worker_prefers_leased_config_over_environment(worker_stubs, monkeypatch):
    from image_service.worker import process

    def forbidden():
        raise AssertionError("environment config must not be loaded when a lease config exists")

    monkeypatch.setattr("image_service.background_config.load_config", forbidden)
    process(
        LocalApi(),
        scene_request(),
        "lease",
        False,
        provider_config={
            "provider": "openrouter",
            "api_key": "sk-test-1234567890",
            "model": "vendor/claimed",
            "provider_tag": "openai",
        },
    )
    config = worker_stubs["config"]
    assert (config.api_key, config.model, config.provider_tag) == (
        "sk-test-1234567890",
        "vendor/claimed",
        "openai",
    )


def test_worker_without_lease_config_uses_environment(worker_stubs, monkeypatch):
    from image_service.worker import process

    sentinel = OpenRouterConfig(api_key="k", model="vendor/env", provider_tag="openai")
    monkeypatch.setattr("image_service.background_config.load_config", lambda: sentinel)
    process(LocalApi(), scene_request(), "lease", False)
    assert worker_stubs["config"] is sentinel


def test_worker_rejects_invalid_leased_config(worker_stubs):
    from image_service.worker import process

    with pytest.raises(BackgroundError) as error:
        process(
            LocalApi(),
            scene_request(),
            "lease",
            False,
            provider_config={"api_key": "k", "model": "no-slash", "provider_tag": "openai"},
        )
    assert error.value.code == "CONFIGURATION"


def test_check_route_disabled_without_token(monkeypatch):
    monkeypatch.delenv("PROVIDER_CHECK_TOKEN", raising=False)
    client = TestClient(app_module.app)
    assert (
        client.post(
            "/internal/v1/provider/check",
            json={"provider": "openrouter", "api_key": "k", "model": "m/n", "provider_tag": "t"},
        ).status_code
        == 404
    )


def test_check_route_relays_capability_get_only(monkeypatch):
    received = {}

    class FakeAdapter:
        def __init__(self, config):
            received["config"] = config

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def inspect(self):
            received["inspected"] = True
            return {"model": received["config"].model, "endpoints": []}

    monkeypatch.setenv("PROVIDER_CHECK_TOKEN", "t" * 32)
    monkeypatch.setattr("image_service.app.OpenRouterAdapter", FakeAdapter)
    client = TestClient(app_module.app)
    ok = client.post(
        "/internal/v1/provider/check",
        headers={"Authorization": "Bearer " + "t" * 32},
        json={
            "provider": "openrouter",
            "api_key": "sk-relay-1234567890",
            "model": "vendor/model-1",
            "provider_tag": "openai",
        },
    )
    assert ok.status_code == 200 and ok.json() == {"model": "vendor/model-1", "endpoints": []}
    assert received["config"].api_key == "sk-relay-1234567890"
    wrong = client.post(
        "/internal/v1/provider/check",
        headers={"Authorization": "Bearer " + "f" * 32},
        json={"provider": "openrouter", "api_key": "k", "model": "m/n", "provider_tag": "t"},
    )
    assert wrong.status_code == 401
    unknown = client.post(
        "/internal/v1/provider/check",
        headers={"Authorization": "Bearer " + "t" * 32},
        json={
            "provider": "openrouter",
            "api_key": "k",
            "model": "m/n",
            "provider_tag": "t",
            "x": 1,
        },
    )
    assert unknown.status_code == 422


def test_paid_test_route_requires_token_and_relays_one_generation(monkeypatch):
    import hashlib
    import io

    from PIL import Image

    received = {}

    class FakeAdapter:
        def __init__(self, config):
            received["config"] = config

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def generate(self, request):
            received["request"] = request
            stream = io.BytesIO()
            Image.new("RGB", (8, 8), (1, 2, 3)).save(stream, format="PNG")
            content = stream.getvalue()
            return BackgroundResult(
                content,
                8,
                8,
                {
                    "provider": "test-only",
                    "model": received["config"].model,
                    "prompt": request.prompt,
                    "parameters": {},
                    "correlation_id": request.correlation_id,
                    "review_status": "PENDING",
                    "duration_ms": 7,
                },
            )

    monkeypatch.setenv("PROVIDER_CHECK_TOKEN", "p" * 32)
    monkeypatch.setattr("image_service.app.OpenRouterAdapter", FakeAdapter)
    client = TestClient(app_module.app)
    body = {
        "provider": "openrouter",
        "api_key": "sk-relay-1234567890",
        "model": "vendor/model-1",
        "provider_tag": "openai",
        "prompt": "Internal paid connectivity test.",
        "aspect_ratio": "1:1",
    }
    assert (
        client.post(
            "/internal/v1/provider/test",
            headers={"Authorization": "Bearer " + "x" * 32},
            json=body,
        ).status_code
        == 401
    )
    monkeypatch.delenv("PROVIDER_CHECK_TOKEN")
    assert client.post("/internal/v1/provider/test", json=body).status_code == 404
    monkeypatch.setenv("PROVIDER_CHECK_TOKEN", "p" * 32)
    ok = client.post(
        "/internal/v1/provider/test",
        headers={"Authorization": "Bearer " + "p" * 32},
        json=body,
    )
    assert ok.status_code == 200
    result = ok.json()
    content = base64.b64decode(result["content_base64"])
    assert (
        result["width"],
        result["height"],
        result["media_type"],
        result["model"],
        result["duration_ms"],
        result["review_status"],
    ) == (8, 8, "image/png", "vendor/model-1", 7, "PENDING")
    assert result["sha256"] == hashlib.sha256(content).hexdigest()
    assert received["request"].aspect_ratio == "1:1"
    assert received["request"].resolution is None and received["request"].output_format is None
    bad = client.post(
        "/internal/v1/provider/test",
        headers={"Authorization": "Bearer " + "p" * 32},
        json={**body, "aspect_ratio": "bad"},
    )
    assert bad.status_code == 502
