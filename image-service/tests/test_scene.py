import hashlib
import io
import ssl

import pytest
from image_service.background import BackgroundError, BackgroundResult
from image_service.scene import process_scene
from image_service.worker import Api
from PIL import Image


def png(color, mode="RGB"):
    stream = io.BytesIO()
    Image.new(mode, (64, 64), color).save(stream, format="PNG")
    return stream.getvalue()


class LocalApi:
    def __init__(self):
        self.inputs = {"product": png("red"), "alpha": png(255, "L")}
        self.outputs = []

    def call(self, method, path, **kwargs):
        if method == "GET":
            return self.inputs[path.split("/")[-1]]
        if method == "POST":
            return None
        data = kwargs["data"]
        self.outputs.append(data)
        image = Image.open(io.BytesIO(data))
        return {
            "object_key": "outputs/test/" + path.split("/")[-1],
            "sha256": hashlib.sha256(data).hexdigest(),
            "width": image.width,
            "height": image.height,
        }


class Adapter:
    def __init__(self, fail_at=None):
        self.count = 0
        self.fail_at = fail_at

    def generate(self, request):
        self.count += 1
        if self.count == self.fail_at:
            raise BackgroundError("PROVIDER_HTTP_429", retryable=True)
        data = png((10 * self.count, 30, 40))
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


def payload(api):
    return {
        "schema_version": 2,
        "task_id": "task",
        "attempt_id": "attempt",
        "correlation_id": "task",
        "feature_type": "SCENE",
        "scene_custom_prompt": "empty table",
        "layout": {"product": {"x": 0.2, "y": 0.2, "width": 0.5, "height": 0.5}},
        "output": {"aspect_ratio": "1:1", "resolution": "1K", "format": "png", "count": 3},
        **{
            name + "_asset": {
                "asset_id": key,
                "sha256": hashlib.sha256(api.inputs[key]).hexdigest(),
            }
            for name, key in [("product", "product"), ("product_alpha", "alpha")]
        },
    }


def test_three_distinct_calls_and_original_source_provenance():
    api, adapter = LocalApi(), Adapter()
    request = payload(api)
    result = process_scene(api, request, "lease", adapter)
    assert adapter.count == 3 and len(result["artifacts"]) == 3
    assert len({v["sha256"] for v in result["artifacts"]}) == 3
    assert len(api.outputs) == 9
    for item in result["background_generations"]:
        assert item["provenance"]["product_sha256"] == request["product_asset"]["sha256"]
        assert item["provenance"]["review_status"] == "PENDING"


def test_failure_never_returns_partial_success():
    api = LocalApi()
    with pytest.raises(BackgroundError):
        process_scene(api, payload(api), "lease", Adapter(fail_at=2))


def test_lost_lease_stops_before_billable_call():
    api, adapter = LocalApi(), Adapter()
    with pytest.raises(ValueError):
        process_scene(api, payload(api), "lease", adapter, cancelled=lambda: True)
    assert adapter.count == 0


def test_bad_source_hash_fails_before_provider():
    api, adapter = LocalApi(), Adapter()
    request = payload(api)
    request["product_asset"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        process_scene(api, request, "lease", adapter)
    assert adapter.count == 0


def test_worker_https_keeps_certificate_validation():
    api = Api("https://localhost:9443", "x" * 32, environment="production")
    try:
        context = api.client._transport._pool._ssl_context
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    finally:
        api.close()


def test_production_worker_rejects_http():
    with pytest.raises(ValueError):
        Api("http://localhost:8080", "x" * 32, environment="production")
