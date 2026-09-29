"""OpenAI / Gemini formats (official and third-party): requests, parsing, errors, routing."""

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from image_service import providers
from image_service.background import BackgroundError, BackgroundRequest
from image_service.background_config import ModelConfig, config_from_mapping
from image_service.egress import proxy_for


def png(color=(200, 30, 40), size=(64, 48)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def request(references=None, ratio="4:3"):
    references = (png(),) if references is None else references
    return BackgroundRequest(
        prompt="Show this exact product on a wooden table.",
        template_version="generation-v4-scene",
        correlation_id="attempt-0",
        aspect_ratio=ratio,
        resolution=None,
        output_format=None,
        references=tuple(references),
    )


OPENAI = ModelConfig("sk-test-openai", "gpt-image-2", None, "openai")
RELAY = ModelConfig("relay-key", "gpt-image-2", None, "openai-compatible", "http://10.2.2.110:3000")
GEMINI = ModelConfig("g-key", "models/gemini-2.5-flash-image", None, "gemini")


def openai_ok(seen):
    def handler(req):
        seen.append(req)
        return httpx.Response(
            200,
            json={
                "data": [{"b64_json": base64.b64encode(png(size=(96, 64))).decode()}],
                "usage": {"input_tokens": 10, "total_tokens": 12, "details": {"x": 1}},
            },
        )

    return handler


def test_endpoint_roots_and_sizes():
    assert providers.endpoint_root(OPENAI) == "https://api.openai.com/v1"
    assert providers.endpoint_root(GEMINI) == "https://generativelanguage.googleapis.com/v1beta"
    assert providers.endpoint_root(RELAY) == "http://10.2.2.110:3000/v1"
    assert (
        providers.endpoint_root(
            ModelConfig("k", "m", None, "openai-compatible", "https://r.example/v1/")
        )
        == "https://r.example/v1"
    )
    assert (
        providers.endpoint_root(
            ModelConfig("k", "m", None, "gemini-compatible", "https://r.example")
        )
        == "https://r.example/v1beta"
    )
    assert [providers.openai_size(r) for r in ("1:1", "4:3", "3:4", "16:9", "2:3")] == [
        "1024x1024",
        "1536x1024",
        "1024x1536",
        "1536x1024",
        "1024x1536",
    ]


@pytest.mark.parametrize(
    ("mapping", "valid"),
    [
        ({"provider": "openai", "api_key": "k", "model": "gpt-image-2"}, True),
        ({"provider": "gemini", "api_key": "k", "model": "gemini-2.5-flash-image"}, True),
        (
            {
                "provider": "openai-compatible",
                "api_key": "k",
                "model": "m",
                "base_url": "http://192.168.1.5:3000",
            },
            True,
        ),
        (
            {
                "provider": "gemini-compatible",
                "api_key": "k",
                "model": "m",
                "base_url": "https://relay.example.com",
            },
            True,
        ),
        (
            {"provider": "openai", "api_key": "k", "model": "gpt-image-2", "provider_tag": "x"},
            False,
        ),
        (
            {"provider": "openai", "api_key": "k", "model": "m", "base_url": "https://a.example"},
            False,
        ),
        ({"provider": "openai-compatible", "api_key": "k", "model": "m"}, False),
        (
            {
                "provider": "openai-compatible",
                "api_key": "k",
                "model": "m",
                "base_url": "http://8.8.8.8/v1",
            },
            False,
        ),
        (
            {
                "provider": "gemini-compatible",
                "api_key": "k",
                "model": "m",
                "base_url": "https://u:p@relay.example.com",
            },
            False,
        ),
        ({"provider": "unknown", "api_key": "k", "model": "m"}, False),
    ],
)
def test_lease_configuration_shapes(mapping, valid):
    if valid:
        config = config_from_mapping(mapping)
        assert config.provider == mapping["provider"]
    else:
        with pytest.raises(BackgroundError, match="CONFIGURATION"):
            config_from_mapping(mapping)


def test_openai_edits_send_every_reference_as_multipart():
    seen = []
    adapter = providers.OpenAIImagesAdapter(OPENAI, transport=httpx.MockTransport(openai_ok(seen)))
    with adapter:
        result = adapter.generate(request(references=(png(), png((20, 60, 200)))))
    sent = seen[0]
    body = sent.content.decode("latin-1")
    assert str(sent.url) == "https://api.openai.com/v1/images/edits"
    assert sent.headers["authorization"] == "Bearer sk-test-openai"
    assert body.count('name="image[]"') == 2
    assert 'name="size"\r\n\r\n1536x1024' in body and 'name="model"\r\n\r\ngpt-image-2' in body
    assert (result.width, result.height) == (96, 64)
    provenance = result.provenance
    assert provenance["output_source"] == "openai-images-api" and provenance["provider"] == "openai"
    assert provenance["parameters"] == {
        "aspect_ratio": "4:3",
        "size": "1536x1024",
        "input_references": 2,
    }
    assert provenance["usage"] == {"input_tokens": 10, "total_tokens": 12}
    assert "endpoint" not in provenance and "sk-test" not in json.dumps(provenance)


def test_openai_relay_uses_its_base_url_and_records_only_the_host():
    seen = []
    adapter = providers.OpenAIImagesAdapter(RELAY, transport=httpx.MockTransport(openai_ok(seen)))
    with adapter:
        result = adapter.generate(request(references=()))
    assert str(seen[0].url) == "http://10.2.2.110:3000/v1/images/generations"
    assert json.loads(seen[0].content)["size"] == "1536x1024"
    assert result.provenance["endpoint"] == "http://10.2.2.110:3000"


@pytest.mark.parametrize(
    ("status", "retryable", "ambiguous"),
    [(401, False, False), (429, True, False), (503, True, True)],
)
def test_http_errors_are_fixed_codes(status, retryable, ambiguous):
    transport = httpx.MockTransport(lambda _req: httpx.Response(status, text="secret body"))
    with providers.OpenAIImagesAdapter(OPENAI, transport=transport) as adapter:
        with pytest.raises(BackgroundError) as error:
            adapter.generate(request())
    assert error.value.code == f"PROVIDER_HTTP_{status}"
    assert (error.value.retryable, error.value.ambiguous) == (retryable, ambiguous)


def test_openai_answer_without_an_image_never_succeeds():
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, json={"data": []}))
    with providers.OpenAIImagesAdapter(OPENAI, transport=transport) as adapter:
        with pytest.raises(BackgroundError, match="INVALID_OUTPUT"):
            adapter.generate(request())


def gemini_ok(seen, key="inlineData"):
    def handler(req):
        seen.append(req)
        image = {
            "mimeType" if key == "inlineData" else "mime_type": "image/png",
            "data": base64.b64encode(png(size=(80, 60))).decode(),
        }
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "here you go"}, {key: image}]}}],
                "usageMetadata": {"promptTokenCount": 5, "totalTokenCount": 9},
            },
        )

    return handler


@pytest.mark.parametrize("key", ["inlineData", "inline_data"])
def test_gemini_generate_content_with_references(key):
    seen = []
    adapter = providers.GeminiAdapter(GEMINI, transport=httpx.MockTransport(gemini_ok(seen, key)))
    with adapter:
        result = adapter.generate(request(references=(png(), png((0, 0, 255)))))
    sent = seen[0]
    assert str(sent.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash-image:generateContent"
    )
    assert sent.headers["x-goog-api-key"] == "g-key" and "authorization" not in sent.headers
    body = json.loads(sent.content)
    parts = body["contents"][0]["parts"]
    assert parts[0]["text"].startswith("Show this exact product")
    assert [p["inline_data"]["mime_type"] for p in parts[1:]] == ["image/png", "image/png"]
    assert body["generationConfig"] == {
        "responseModalities": ["TEXT", "IMAGE"],
        "imageConfig": {"aspectRatio": "4:3"},
    }
    assert (result.width, result.height) == (80, 60)
    assert result.provenance["output_source"] == "gemini-generate-content"
    assert result.provenance["usage"] == {"promptTokenCount": 5, "totalTokenCount": 9}


def test_gemini_refusal_without_an_image_is_an_invalid_output():
    answer = {"candidates": [{"content": {"parts": [{"text": "I can't help with that."}]}}]}
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, json=answer))
    with providers.GeminiAdapter(GEMINI, transport=transport) as adapter:
        with pytest.raises(BackgroundError, match="INVALID_OUTPUT"):
            adapter.generate(request())


def test_intranet_relays_bypass_the_proxy(monkeypatch):
    monkeypatch.setenv("MODEL_PROXY_URL", "http://egress.internal:3128")
    assert proxy_for("http://10.2.2.110:3000/v1") is None
    assert proxy_for("https://api.openai.com/v1") == "http://egress.internal:3128"
    monkeypatch.delenv("MODEL_PROXY_URL")
    monkeypatch.setenv("OPENROUTER_PROXY_URL", "http://legacy.internal:3128")
    assert proxy_for("https://openrouter.ai") == "http://legacy.internal:3128"


def test_adapter_follows_the_provider_type(monkeypatch):
    monkeypatch.setattr(providers.openrouter, "OpenRouterAdapter", lambda config: "openrouter")
    assert providers.model_adapter(ModelConfig("k", "a/b", "t")) == "openrouter"
    assert isinstance(providers.model_adapter(RELAY), providers.OpenAIImagesAdapter)
    assert isinstance(providers.model_adapter(GEMINI), providers.GeminiAdapter)
