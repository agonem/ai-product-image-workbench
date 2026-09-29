import base64
import io
import json

import httpx
import pytest
from PIL import Image

from image_service.background import BackgroundError, BackgroundRequest
from image_service.background_config import load_config
from image_service.openrouter import OpenRouterAdapter


def config(**overrides):
    return load_config(
        {
            "OPENROUTER_API_KEY": "test-secret-not-real",
            "OPENROUTER_MODEL": "test/image",
            "OPENROUTER_PROVIDER_TAG": "test-provider",
            **overrides,
        }
    )


def request(**overrides):
    return BackgroundRequest(
        **{
            "prompt": "An empty studio background",
            "template_version": "test-v1",
            "correlation_id": "test-1",
            "aspect_ratio": "4:3",
            "resolution": "1K",
            "output_format": "png",
            **overrides,
        }
    )


def fixture_response(fmt="PNG", size=(40, 30)):
    stream = io.BytesIO()
    Image.new("RGB", size, "white").save(stream, format=fmt)
    return {
        "data": [
            {
                "b64_json": base64.b64encode(stream.getvalue()).decode(),
                "media_type": "image/" + fmt.lower(),
            }
        ]
    }


class Provider:
    def __init__(self):
        self.calls = []
        self.parameters = {
            key: {"type": "enum", "values": values}
            for key, values in {
                "aspect_ratio": ["4:3"],
                "resolution": ["1K"],
                "output_format": ["png", "jpeg"],
            }.items()
        }
        self.architecture = {"input_modalities": ["text"], "output_modalities": ["image"]}
        self.result = fixture_response()
        self.status = 200
        self.timeout = False

    def __call__(self, req):
        self.calls.append(req)
        if req.url.path.endswith("/images/models"):
            return httpx.Response(
                200, json={"data": [{"id": "test/image", "architecture": self.architecture}]}
            )
        if req.url.path.endswith("/endpoints"):
            return httpx.Response(
                200,
                json={
                    "id": "test/image",
                    "endpoints": [
                        {"provider_tag": "test-provider", "supported_parameters": self.parameters}
                    ],
                },
            )
        if self.timeout:
            raise httpx.ReadTimeout("secret-provider-diagnostic", request=req)
        return httpx.Response(self.status, json=self.result)


def generate(provider, value=None):
    with OpenRouterAdapter(config(), transport=httpx.MockTransport(provider)) as adapter:
        return adapter.generate(value or request())


@pytest.mark.parametrize("fmt", ["png", "jpeg"])
def test_text_only_generation_and_provenance(fmt):
    provider = Provider()
    provider.result = fixture_response(fmt.upper())
    result = generate(provider, request(output_format=fmt))
    body = json.loads(provider.calls[-1].content)
    assert set(body) == {
        "model",
        "prompt",
        "aspect_ratio",
        "resolution",
        "output_format",
        "provider",
    }
    assert body["provider"] == {"only": ["test-provider"], "allow_fallbacks": False}
    assert result.provenance["review_status"] == "PENDING"
    assert result.provenance["model"] == "test/image"
    assert result.provenance["correlation_id"] == "test-1"
    assert result.width == 40 and result.height == 30
    assert "test-secret" not in repr(result)


@pytest.mark.parametrize("key", ["aspect_ratio", "resolution", "output_format"])
def test_missing_endpoint_capability_prevents_post(key):
    provider = Provider()
    del provider.parameters[key]
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        generate(provider)
    assert all(call.method == "GET" for call in provider.calls)


def test_non_image_model_prevents_generation():
    provider = Provider()
    provider.architecture["output_modalities"] = ["text"]
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        generate(provider)


@pytest.mark.parametrize(
    "status,retryable",
    [(401, False), (402, False), (400, False), (429, True), (500, True), (502, True)],
)
def test_safe_http_errors_without_automatic_retry(status, retryable):
    provider = Provider()
    provider.status = status
    provider.result = {"error": "test-secret-not-real and private prompt"}
    with pytest.raises(BackgroundError) as caught:
        generate(provider)
    assert caught.value.retryable is retryable
    assert "secret" not in str(caught.value)
    assert sum(call.method == "POST" for call in provider.calls) == 1


def test_timeout_is_ambiguous_and_safe():
    provider = Provider()
    provider.timeout = True
    with pytest.raises(BackgroundError) as caught:
        generate(provider)
    assert caught.value.ambiguous is True
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"data": []},
        {"data": [{"url": "http://localhost"}]},
        {"data": [{"b64_json": "invalid"}]},
        fixture_response(size=(30, 40)),
        fixture_response("JPEG"),
    ],
)
def test_invalid_output_never_succeeds(result):
    provider = Provider()
    provider.result = result
    with pytest.raises(BackgroundError, match="INVALID_OUTPUT"):
        generate(provider)


def test_private_config_missing_ambiguous_and_file_loading(tmp_path):
    with pytest.raises(BackgroundError, match="CONFIGURATION"):
        load_config({})
    secret = tmp_path / "private.key"
    secret.write_text("test-file-secret", encoding="utf-8")
    loaded = config(OPENROUTER_API_KEY="", OPENROUTER_API_KEY_FILE=str(secret))
    assert "test-file-secret" not in repr(loaded)
    with pytest.raises(BackgroundError, match="CONFIGURATION"):
        config(OPENROUTER_API_KEY_FILE=str(secret))


@pytest.mark.parametrize(
    "value", ["https://example.com/product.png", "data:image/png;base64,abc", ""]
)
def test_image_references_and_empty_prompts_rejected(value):
    with pytest.raises(BackgroundError):
        request(prompt=value)


def test_extra_asset_fields_rejected():
    with pytest.raises(TypeError):
        request(product_asset={"key": "private"})


def test_string_capability_list_is_not_an_allowlist():
    provider = Provider()
    provider.parameters["aspect_ratio"]["values"] = "4:3"
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        generate(provider)


def test_encoded_output_budget_before_decode(monkeypatch):
    monkeypatch.setattr("image_service.openrouter.MAX_IMAGE", 1)
    with pytest.raises(BackgroundError, match="INVALID_OUTPUT"):
        generate(Provider())


def test_response_budget(monkeypatch):
    monkeypatch.setattr("image_service.openrouter.MAX_RESPONSE", 10)
    with pytest.raises(BackgroundError, match="RESPONSE_BUDGET"):
        generate(Provider())


def test_oversized_key_file_is_rejected(tmp_path):
    secret = tmp_path / "private.key"
    secret.write_bytes(b"x" * 4097)
    with pytest.raises(BackgroundError, match="CONFIGURATION"):
        config(OPENROUTER_API_KEY="", OPENROUTER_API_KEY_FILE=str(secret))


def reference_png():
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(stream, format="PNG")
    return stream.getvalue()


def reference_provider():
    provider = Provider()
    provider.parameters = {
        "aspect_ratio": {"type": "enum", "values": ["4:3"]},
        "input_references": {"type": "range", "min": 0, "max": 16},
    }
    provider.architecture = {"input_modalities": ["text", "image"], "output_modalities": ["image"]}
    return provider


def test_reference_images_are_sent_as_data_urls():
    provider = reference_provider()
    image = reference_png()
    result = generate(
        provider, request(resolution=None, output_format=None, references=(image, image))
    )
    body = json.loads(provider.calls[-1].content)
    assert [item["type"] for item in body["input_references"]] == ["image_url", "image_url"]
    url = body["input_references"][0]["image_url"]["url"]
    assert url == "data:image/png;base64," + base64.b64encode(image).decode()
    assert "Background only" not in body["prompt"]
    assert result.provenance["parameters"] == {"aspect_ratio": "4:3", "input_references": 2}
    assert "base64" not in repr(result)


@pytest.mark.parametrize("gap", ["parameter", "modality", "limit"])
def test_references_require_declared_capability(gap):
    provider = reference_provider()
    if gap == "parameter":
        del provider.parameters["input_references"]
    elif gap == "modality":
        provider.architecture["input_modalities"] = ["text"]
    else:
        provider.parameters["input_references"]["max"] = 1
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        generate(
            provider,
            request(
                resolution=None,
                output_format=None,
                references=(reference_png(), reference_png()),
            ),
        )
    assert all(call.method == "GET" for call in provider.calls)


def test_native_ratio_only_sends_verified_parameters():
    provider = Provider()
    provider.parameters = {"aspect_ratio": provider.parameters["aspect_ratio"]}
    provider.result = fixture_response("JPEG", (120, 80))
    result = generate(provider, request(resolution=None, output_format=None))
    body = json.loads(provider.calls[-1].content)
    assert set(body) == {"model", "prompt", "aspect_ratio", "provider"}
    assert result.width == 120 and result.height == 80


def test_native_ratio_still_requires_route_support():
    provider = Provider()
    provider.parameters = {}
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        generate(provider, request(resolution=None, output_format=None))
    assert all(c.method == "GET" for c in provider.calls)


@pytest.mark.parametrize(
    "value", ["ftp://proxy:21", "http://", "http://proxy:3128/path", "http://proxy:99999"]
)
def test_invalid_explicit_proxy_is_a_configuration_error(monkeypatch, value):
    monkeypatch.setenv("OPENROUTER_PROXY_URL", value)
    with pytest.raises(BackgroundError, match="CONFIGURATION"):
        OpenRouterAdapter(config())


def test_explicit_proxy_is_used_and_ambient_proxy_ignored(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid:1")
    monkeypatch.delenv("OPENROUTER_PROXY_URL", raising=False)
    with OpenRouterAdapter(config()) as adapter:
        assert not adapter.client._mounts
    monkeypatch.setenv("OPENROUTER_PROXY_URL", "http://egress.internal:3128")
    with OpenRouterAdapter(config()) as adapter:
        assert list(adapter.client._mounts.values())[0] is not None
