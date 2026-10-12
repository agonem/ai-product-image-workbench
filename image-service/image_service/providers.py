"""Official OpenAI / Gemini image APIs and third-party endpoints in the same formats.

Same boundaries as the OpenRouter adapter: the reference images go only to the configured
endpoint, a paid call is never retried automatically, responses are size-bounded, errors carry
fixed codes (no provider bodies), and every result stays pending human review.

- OpenAI format: POST {root}/images/edits (multipart, one ``image[]`` per reference) or
  {root}/images/generations without references; the image is ``data[0].b64_json``. The size is
  the supported orientation (1024x1024, 1536x1024 or 1024x1536); the exact output size is then
  exported locally, as for every provider.
- Gemini format: POST {root}/models/{model}:generateContent with the prompt and ``inline_data``
  references, ``responseModalities`` TEXT+IMAGE and ``imageConfig.aspectRatio``; the image is
  the first ``inlineData`` part of the first candidate.

The model's stored official parameters (ADR-20261012-AB) are added to the request as they are;
none may replace what the system sets for the call (model, prompt, images, size, count, format).
DeepSeek (official) serves text models only, so it has no image adapter.
"""

import base64
import hashlib
import json
import time
from urllib.parse import urlsplit

import httpx

from image_service import openrouter
from image_service.background import (
    PNG_SIGNATURE,
    BackgroundError,
    BackgroundRequest,
    BackgroundResult,
    merge_parameters,
)
from image_service.egress import route

OFFICIAL_ROOTS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}
# What the system sets for each image call; stored parameters never replace it.
OPENAI_IMAGE_FIELDS = (
    "model",
    "prompt",
    "n",
    "size",
    "image",
    "image[]",
    "mask",
    "response_format",
    "output_format",
    "stream",
    "resolution",
)
GEMINI_IMAGE_FIELDS = (
    "contents",
    "generationConfig.responseModalities",
    "generationConfig.imageConfig",
)
TIMEOUT = httpx.Timeout(300, connect=10)


def endpoint_root(config):
    """API root for a configuration; a third-party base URL gains the usual version path."""
    if config.provider in OFFICIAL_ROOTS:
        return OFFICIAL_ROOTS[config.provider]
    base = config.base_url.rstrip("/")
    if config.provider == "openai-compatible":
        return base if base.endswith("/v1") else base + "/v1"
    return base if base.endswith(("/v1beta", "/v1")) else base + "/v1beta"


def model_adapter(config):
    """The adapter for a configuration's provider type (looked up at call time for tests)."""
    if config.provider == "openrouter":
        return openrouter.OpenRouterAdapter(config)
    if config.provider in ("openai", "openai-compatible"):
        return OpenAIImagesAdapter(config)
    if config.provider in ("gemini", "gemini-compatible"):
        return GeminiAdapter(config)
    raise BackgroundError("CONFIGURATION")


def openai_size(aspect_ratio):
    """Nearest orientation every OpenAI image model and most relays accept."""
    width, height = map(int, aspect_ratio.split(":"))
    if width * 10 > height * 11:
        return "1536x1024"
    if height * 10 > width * 11:
        return "1024x1536"
    return "1024x1024"


def _mime(content):
    return "image/png" if content[:8] == PNG_SIGNATURE else "image/jpeg"


def _numbers(usage):
    if not isinstance(usage, dict):
        return {}
    return {key: value for key, value in usage.items() if type(value) in (int, float)}


class _Adapter:
    output_source = ""

    def __init__(self, config, *, transport=None, headers=None):
        self.config = config
        self.root = endpoint_root(config)
        self.client = httpx.Client(
            base_url=self.root + "/",
            headers=headers,
            timeout=TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            proxy=route(config, self.root),
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def _post(self, path, **kwargs):
        """One paid POST: bounded body, fixed error codes, never retried here."""
        try:
            with self.client.stream("POST", path, **kwargs) as response:
                if response.status_code != 200:
                    status = response.status_code
                    raise BackgroundError(
                        "PROVIDER_HTTP_" + str(status),
                        retryable=status == 429 or status >= 500,
                        ambiguous=status >= 500,
                    )
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > openrouter.MAX_RESPONSE:
                        raise BackgroundError("RESPONSE_BUDGET", ambiguous=True)
                return json.loads(data)
        except httpx.RequestError:
            raise BackgroundError("PROVIDER_NETWORK", retryable=True, ambiguous=True) from None
        except (ValueError, UnicodeError):
            raise BackgroundError("INVALID_RESPONSE", ambiguous=True) from None

    def _result(self, request, response, parameters, usage, started):
        content, width, height = openrouter.decode_background(response, request)
        provenance = {
            "schema_version": 1,
            "provider": self.config.provider,
            "model": self.config.model,
            "prompt": request.prompt,
            "template_version": request.template_version,
            "parameters": {**parameters, "input_references": len(request.references)},
            "correlation_id": request.correlation_id,
            "output_source": self.output_source,
            "sha256": hashlib.sha256(content).hexdigest(),
            "review_status": "PENDING",
            "duration_ms": round((time.monotonic() - started) * 1000),
            "usage": _numbers(usage),
        }
        if self.config.base_url:
            # Which relay produced the image: scheme and host only, never the path or key.
            parts = urlsplit(self.config.base_url)
            provenance["endpoint"] = f"{parts.scheme}://{parts.netloc}"
        return BackgroundResult(content, width, height, provenance)


class OpenAIImagesAdapter(_Adapter):
    output_source = "openai-images-api"

    def __init__(self, config, *, transport=None):
        super().__init__(
            config, transport=transport, headers={"Authorization": "Bearer " + config.api_key}
        )

    def generate(self, request: BackgroundRequest) -> BackgroundResult:
        if not isinstance(request, BackgroundRequest):
            raise BackgroundError("INVALID_INPUT")
        size = openai_size(request.aspect_ratio)
        fields = {"model": self.config.model, "prompt": request.prompt, "n": 1, "size": size}
        extra = dict(request.parameters)
        merge_parameters(fields, request.parameters, OPENAI_IMAGE_FIELDS)
        started = time.monotonic()
        if request.references:
            files = [
                ("image[]", (f"reference-{index}.{_mime(item)[6:]}", item, _mime(item)))
                for index, item in enumerate(request.references)
            ]
            # Multipart form: every field as text (booleans as the API spells them).
            form = {
                key: str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in fields.items()
            }
            response = self._post("images/edits", data=form, files=files)
        else:
            response = self._post("images/generations", json=fields)
        parameters = {"aspect_ratio": request.aspect_ratio, "size": size, **extra}
        return self._result(request, response, parameters, response.get("usage"), started)


class GeminiAdapter(_Adapter):
    output_source = "gemini-generate-content"

    def __init__(self, config, *, transport=None):
        super().__init__(config, transport=transport, headers={"x-goog-api-key": config.api_key})

    def generate(self, request: BackgroundRequest) -> BackgroundResult:
        if not isinstance(request, BackgroundRequest):
            raise BackgroundError("INVALID_INPUT")
        parts = [{"text": request.prompt}] + [
            {"inline_data": {"mime_type": _mime(item), "data": base64.b64encode(item).decode()}}
            for item in request.references
        ]
        extra = dict(request.parameters)
        image_config = {"aspectRatio": request.aspect_ratio}
        if "resolution" in extra:
            image_config["imageSize"] = extra["resolution"]
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": image_config,
            },
        }
        stored = [(key, value) for key, value in request.parameters if key != "resolution"]
        merge_parameters(body, stored, GEMINI_IMAGE_FIELDS)
        model = self.config.model.removeprefix("models/")
        started = time.monotonic()
        response = self._post(f"models/{model}:generateContent", json=body)
        try:
            candidate = response["candidates"][0]
            image = next(
                part.get("inlineData") or part.get("inline_data")
                for part in candidate["content"]["parts"]
                if isinstance(part, dict) and (part.get("inlineData") or part.get("inline_data"))
            )
            mime = image.get("mimeType") or image.get("mime_type")
            shaped = {"data": [{"b64_json": image["data"], "media_type": mime}]}
        except (KeyError, IndexError, TypeError, AttributeError, StopIteration):
            # A refusal or a text-only answer: the paid call produced no usable image.
            raise BackgroundError("INVALID_OUTPUT", ambiguous=True) from None
        parameters = {"aspect_ratio": request.aspect_ratio, **extra}
        return self._result(request, shaped, parameters, response.get("usageMetadata"), started)
