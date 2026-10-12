"""Model parameters and the pages' clarity options (ADR-20261009-Q, ADR-20261012-AB)."""

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
SEEDREAM = ModelConfig(
    "k" * 20, "bytedance-seed/seedream-5-0-pro", "seed", parameters=(("seed", 42),)
)


def test_stored_parameters_then_the_chosen_clarity():
    assert model_parameters.for_call(GPT, task()) == (("quality", "low"),)
    assert model_parameters.for_call(GPT, task(resolution="1K")) == (("quality", "low"),)
    # ADR-20261012-AB: clarity is the task's alone; without one nothing about it is sent.
    assert model_parameters.for_call(SEEDREAM, task()) == (("seed", 42),)
    assert model_parameters.for_call(SEEDREAM, task(resolution="2K")) == (
        ("resolution", "2K"),
        ("seed", 42),
    )
    # The output size is separate: a large size alone asks nothing more of the model.
    assert model_parameters.for_call(SEEDREAM, task(1600, 1600)) == (("seed", 42),)
    assert model_parameters.for_call(None, task(resolution="2K")) == ()


def test_a_clarity_the_model_cannot_do_fails_before_any_call():
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        model_parameters.for_call(GPT, task(resolution="2K"))  # gpt-image has no 2K setting
    lite = ModelConfig("k" * 20, "bytedance-seed/seedream-5-0-lite", "seed")
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        model_parameters.for_call(lite, task(resolution="1K"))  # 2K only
    # The gift re-shot is small inside the card: the clarity does not apply to it.
    assert model_parameters.for_call(GPT, task(resolution="2K"), gift=True) == (("quality", "low"),)


def test_the_catalog_matches_the_interface_type_and_model():
    def named(kind, model, purpose="IMAGE"):
        return model_parameters.parameter_set(kind, model, purpose).get("id")

    assert named("openrouter", "openai/gpt-image-2.5-flare") == "openrouter-gpt-image-2.5"
    assert named("openai", "gpt-image-2") == "openai-gpt-image"
    assert named("openrouter", "google/gemini-3.1-flash-image") == "openrouter-gemini-image"
    assert named("gemini", "gemini-3.1-flash-image") == "gemini-image"
    assert named("openrouter", "google/gemini-2.5-flash-image") == "openrouter-gemini-2.5-image"
    assert named("openrouter", "deepseek/deepseek-v4.1-flash", "TEXT") == "openrouter-text"
    assert named("deepseek", "deepseek-flash", "TEXT") == "deepseek-text"
    assert named("deepseek", "deepseek-flash") is None


def test_leased_parameters_are_checked():
    base = {"provider": "openrouter", "model": "a/b", "provider_tag": "t", "api_key": "k" * 20}
    config = config_from_mapping(
        {**base, "parameters": {"quality": "high", "reasoning.effort": "low", "seed": 7}}
    )
    assert config.parameters == (("quality", "high"), ("reasoning.effort", "low"), ("seed", 7))
    assert config_from_mapping({**base, "parameters": {"temperature": 0.7}}).parameters == (
        ("temperature", 0.7),
    )
    assert config_from_mapping({**base, "provider": "deepseek", "provider_tag": None}).provider == (
        "deepseek"
    )
    for bad in (
        {"Quality ": "high"},
        {"quality": "a b"},
        {"quality": None},
        {"quality": [1]},
        {"a.b.c.d.e": 1},
        {"temperature": float("nan")},
        ["quality"],
    ):
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
        result = adapter.generate(request((("moderation", "low"), ("quality", "high"))))
        for bad in ((("resolution", "2K"),), (("size", "1024x1024"),), (("model", "x"),)):
            with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
                adapter.generate(request(bad))
    form = seen[0].content.decode("latin-1")
    assert 'name="quality"\r\n\r\nhigh' in form and 'name="moderation"\r\n\r\nlow' in form
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
    # Stored official parameters join the generation config (ADR-20261012-AB).
    with providers.GeminiAdapter(
        config, transport=httpx.MockTransport(image_answer(seen, gemini=True))
    ) as adapter:
        adapter.generate(request((("generationConfig.temperature", 0.4),)))
        with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
            adapter.generate(request((("generationConfig.responseModalities", "IMAGE"),)))
    assert json.loads(seen[1].content)["generationConfig"]["temperature"] == 0.4
    assert result.provenance["parameters"]["resolution"] == "2K"


def test_openrouter_sends_and_checks_the_parameters():
    seen = []
    supported = {
        "aspect_ratio": {"type": "enum", "values": ["1:1"]},
        "resolution": {"type": "enum", "values": ["1K", "2K"]},
        "input_references": {"type": "range", "min": 0, "max": 4},
        "output_compression": {"type": "range", "min": 0, "max": 100},
        "seed": {"type": "boolean"},
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
        # Ranges and plain "supported" markers are checked too (ADR-20261012-AB).
        for bad in ((("output_compression", 101),), (("quality", "high"),), (("n", 2),)):
            with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
                adapter.generate(request(bad))
        checked = len(seen)
        adapter.generate(request((("output_compression", 80), ("seed", 42))))
    assert json.loads(seen[sent - 1].content)["resolution"] == "2K"
    assert all(call.method == "GET" for call in seen[sent:checked])
    sent_body = json.loads(seen[-1].content)
    assert sent_body["output_compression"] == 80 and sent_body["seed"] == 42


def test_text_models_send_the_temperature_only_when_filled_in():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "好"}}]})

    config = ModelConfig(
        "k" * 20, "vendor/text", "openai", proxy="", parameters=(("temperature", 0.2),)
    )
    text_models.rewrite(config, "s", "u", transport=httpx.MockTransport(handler))
    plain = ModelConfig("k" * 20, "vendor/text", "openai", proxy="")
    text_models.rewrite(plain, "s", "u", transport=httpx.MockTransport(handler))
    # ADR-20261012-AB: blank means the vendor's default, no longer 0.7.
    assert seen[0]["temperature"] == 0.2 and "temperature" not in seen[1]
