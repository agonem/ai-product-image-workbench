"""Model parameters and the pages' clarity options (ADR-20261009-Q)."""

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from image_service import model_parameters, providers, text_models
from image_service.background import BackgroundError, BackgroundRequest
from image_service.background_config import ModelConfig, config_from_mapping
from image_service.openrouter import OpenRouterAdapter


def png():
    stream = io.BytesIO()
    Image.new("RGB", (80, 60), "white").save(stream, format="PNG")
    return stream.getvalue()


def task(width=800, height=800, **extra):
    return {"output": {"width": width, "height": height}, **extra}


GPT = ModelConfig("k" * 20, "openai/gpt-image-2", "openai", parameters=(("quality", "low"),))
SEEDREAM = ModelConfig("k" * 20, "bytedance-seed/seedream-5-0-pro", "seed")


def test_stored_parameters_then_high_quality_then_the_2k_size():
    assert model_parameters.for_call(GPT, task()) == (("quality", "low"),)
    assert model_parameters.for_call(GPT, task(quality="HIGH")) == (("quality", "high"),)
    assert model_parameters.for_call(SEEDREAM, task()) == ()
    assert model_parameters.for_call(SEEDREAM, task(1600, 1600)) == (("resolution", "2K"),)
    assert model_parameters.for_call(None, task(quality="HIGH")) == ()


def test_clarity_a_model_cannot_do_fails_before_any_call():
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        model_parameters.for_call(GPT, task(1600, 1600))  # gpt-image has no 2K setting
    lite = ModelConfig("k" * 20, "bytedance-seed/seedream-5-0-lite", "seed")
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        model_parameters.for_call(lite, task(quality="HIGH"))  # already 2K, nothing higher
    # The gift re-shot is small inside the card: the large size does not apply to it.
    assert model_parameters.for_call(GPT, task(1600, 1600), gift=True) == (("quality", "low"),)


def test_the_catalog_matches_the_known_models():
    assert model_parameters.family("openai/gpt-image-2.5-flare")["id"] == "gpt-image-2.5"
    assert model_parameters.family("gpt-image-2")["id"] == "gpt-image"
    assert model_parameters.family("google/gemini-3.1-flash-image")["id"] == "gemini-image"
    assert model_parameters.family("google/gemini-3.1-flash-lite-image")["id"] == (
        "gemini-lite-image"
    )
    assert model_parameters.family("google/gemini-2.5-flash-image") == {}
    assert model_parameters.family("deepseek/deepseek-v4.1-flash", "TEXT")["id"] == "text"


def test_leased_parameters_are_checked():
    base = {"provider": "openrouter", "model": "a/b", "provider_tag": "t", "api_key": "k" * 20}
    config = config_from_mapping({**base, "parameters": {"quality": "high"}})
    assert config.parameters == (("quality", "high"),)
    for bad in ({"quality": 3}, {"Quality": "high"}, {"quality": "a b"}, ["quality"]):
        with pytest.raises(BackgroundError, match="CONFIGURATION"):
            config_from_mapping({**base, "parameters": bad})


def request(parameters):
    return BackgroundRequest(
        prompt="Show this exact product on a wooden table.",
        template_version="generation-v4-scene",
        correlation_id="attempt-0",
        aspect_ratio="1:1",
        resolution=None,
        output_format=None,
        references=(png(),),
        parameters=parameters,
    )


def image_answer(seen, gemini=False):
    data = base64.b64encode(png()).decode()

    def handler(req):
        seen.append(req)
        if gemini:
            inline = {"mimeType": "image/png", "data": data}
            parts = [{"inlineData": inline}]
            return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})
        return httpx.Response(200, json={"data": [{"b64_json": data}]})

    return handler


def test_official_openai_sends_the_quality():
    seen = []
    config = ModelConfig("sk-test", "gpt-image-2", None, "openai")
    with providers.OpenAIImagesAdapter(
        config, transport=httpx.MockTransport(image_answer(seen))
    ) as adapter:
        result = adapter.generate(request((("quality", "high"),)))
        with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
            adapter.generate(request((("resolution", "2K"),)))
    assert 'name="quality"\r\n\r\nhigh' in seen[0].content.decode("latin-1")
    assert result.provenance["parameters"]["quality"] == "high"


def test_official_gemini_sends_the_image_size():
    seen = []
    config = ModelConfig("g-key", "gemini-3.1-flash-image", None, "gemini")
    with providers.GeminiAdapter(
        config, transport=httpx.MockTransport(image_answer(seen, gemini=True))
    ) as adapter:
        result = adapter.generate(request((("resolution", "2K"),)))
    image_config = json.loads(seen[0].content)["generationConfig"]["imageConfig"]
    assert image_config == {"aspectRatio": "1:1", "imageSize": "2K"}
    assert result.provenance["parameters"]["resolution"] == "2K"


def test_openrouter_sends_and_checks_the_parameters():
    seen = []
    supported = {
        "aspect_ratio": {"type": "enum", "values": ["1:1"]},
        "resolution": {"type": "enum", "values": ["1K", "2K"]},
        "input_references": {"type": "range", "min": 0, "max": 4},
    }

    def handler(req):
        seen.append(req)
        if req.url.path.endswith("/images/models"):
            architecture = {"input_modalities": ["text", "image"], "output_modalities": ["image"]}
            return httpx.Response(
                200, json={"data": [{"id": "vendor/image", "architecture": architecture}]}
            )
        if req.url.path.endswith("/endpoints"):
            endpoint = {"provider_tag": "seed", "supported_parameters": supported}
            return httpx.Response(200, json={"id": "vendor/image", "endpoints": [endpoint]})
        return image_answer([])(req)

    config = ModelConfig("k" * 20, "vendor/image", "seed")
    with OpenRouterAdapter(config, transport=httpx.MockTransport(handler)) as adapter:
        adapter.generate(request((("resolution", "2K"),)))
        sent = len(seen)
        # A value the endpoint does not list never reaches a paid call.
        with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
            adapter.generate(request((("resolution", "4K"),)))
    assert json.loads(seen[sent - 1].content)["resolution"] == "2K"
    assert all(call.method == "GET" for call in seen[sent:])


def test_text_models_use_the_stored_temperature():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "好"}}]})

    config = ModelConfig(
        "k" * 20, "vendor/text", "openai", proxy="", parameters=(("temperature", "0.2"),)
    )
    text_models.rewrite(config, "s", "u", transport=httpx.MockTransport(handler))
    plain = ModelConfig("k" * 20, "vendor/text", "openai", proxy="")
    text_models.rewrite(plain, "s", "u", transport=httpx.MockTransport(handler))
    assert [body["temperature"] for body in seen] == [0.2, 0.7]
