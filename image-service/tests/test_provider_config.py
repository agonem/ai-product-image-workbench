"""Lease-delivered provider configuration for generation Workers."""

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
    """Minimal Worker transport double; generation only needs assets and outputs."""

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


def generation_request():
    return {
        "schema_version": 4,
        "task_id": "task",
        "attempt_id": "attempt",
        "correlation_id": "task",
        "feature_type": "SCENE",
        "output": {"aspect_ratio": "1:1", "width": 256, "height": 256, "format": "png", "count": 1},
        "product_asset": {"asset_id": "a", "sha256": "0" * 64},
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

    def fake_generation(api, request, lease, adapter, *, cancelled=None, text_config=None):
        captured["adapter"] = adapter
        return {"schema_version": 4, "event_type": "image.task.completed.v4", "artifacts": []}

    monkeypatch.setattr("image_service.openrouter.OpenRouterAdapter", RecordingAdapter)
    monkeypatch.setattr("image_service.generation.process_generation", fake_generation)
    return captured


def test_worker_prefers_leased_config_over_environment(worker_stubs, monkeypatch):
    from image_service.worker import process

    def forbidden():
        raise AssertionError("environment config must not be loaded when a lease config exists")

    monkeypatch.setattr("image_service.background_config.load_config", forbidden)
    process(
        LocalApi(),
        generation_request(),
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
    process(LocalApi(), generation_request(), "lease", False)
    assert worker_stubs["config"] is sentinel


def test_worker_rejects_invalid_leased_config(worker_stubs):
    from image_service.worker import process

    with pytest.raises(BackgroundError) as error:
        process(
            LocalApi(),
            generation_request(),
            "lease",
            False,
            provider_config={"api_key": "k", "model": "no-slash", "provider_tag": "openai"},
        )
    assert error.value.code == "CONFIGURATION"


def test_admin_relay_routes_are_withdrawn(monkeypatch):
    # The capability check and paid test relays were removed; even with the old token set
    # the image service exposes no route that accepts a forwarded provider credential.
    monkeypatch.setenv("PROVIDER_CHECK_TOKEN", "t" * 32)
    client = TestClient(app_module.app)
    for path in ("/internal/v1/provider/check", "/internal/v1/provider/test"):
        response = client.post(
            path,
            headers={"Authorization": "Bearer " + "t" * 32},
            json={"provider": "openrouter", "api_key": "k", "model": "m/n", "provider_tag": "t"},
        )
        assert response.status_code == 404
