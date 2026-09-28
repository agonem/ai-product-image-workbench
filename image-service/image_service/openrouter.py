"""OpenRouter dedicated Images API. No reference images, fallback, or paid-request retry."""

import base64
import hashlib
import io
import json
import time

import httpx
from PIL import Image

from image_service.background import BackgroundError, BackgroundRequest, BackgroundResult

MAX_RESPONSE = 16 * 1024 * 1024
MAX_IMAGE = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000


class OpenRouterAdapter:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.client = httpx.Client(
            base_url="https://openrouter.ai/api/v1/",
            headers={"Authorization": "Bearer " + config.api_key},
            timeout=httpx.Timeout(180, connect=10),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def _json(self, method, path, body=None):
        try:
            with self.client.stream(method, path, json=body) as response:
                if response.status_code != 200:
                    status = response.status_code
                    raise BackgroundError(
                        "PROVIDER_HTTP_" + str(status),
                        retryable=status == 429 or status >= 500,
                        ambiguous=method == "POST" and status >= 500,
                    )
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        raise BackgroundError("RESPONSE_BUDGET", ambiguous=method == "POST")
                return json.loads(data)
        except httpx.RequestError:
            raise BackgroundError(
                "PROVIDER_NETWORK", retryable=True, ambiguous=method == "POST"
            ) from None
        except (ValueError, UnicodeError):
            raise BackgroundError("INVALID_RESPONSE", ambiguous=method == "POST") from None

    def _capabilities(self, parameters):
        models = self._json("GET", "images/models")
        endpoints = self._json("GET", f"images/models/{self.config.model}/endpoints")
        try:
            model = next(item for item in models["data"] if item["id"] == self.config.model)
            architecture = model["architecture"]
            if (
                not isinstance(architecture["input_modalities"], list)
                or not isinstance(architecture["output_modalities"], list)
                or "text" not in architecture["input_modalities"]
                or "image" not in architecture["output_modalities"]
            ):
                raise ValueError()
            selected = [
                item
                for item in endpoints["endpoints"]
                if item["provider_tag"] == self.config.provider_tag
            ]
            if endpoints["id"] != self.config.model or not selected:
                raise ValueError()
            # Every routable endpoint with this tag must support the exact requested values.
            for endpoint in selected:
                for key, value in parameters.items():
                    descriptor = endpoint["supported_parameters"][key]
                    if (
                        descriptor["type"] != "enum"
                        or not isinstance(descriptor["values"], list)
                        or value not in descriptor["values"]
                    ):
                        raise ValueError()
        except (KeyError, TypeError, ValueError, StopIteration):
            raise BackgroundError("UNSUPPORTED_CAPABILITY") from None

    def generate(self, request: BackgroundRequest) -> BackgroundResult:
        if not isinstance(request, BackgroundRequest):
            raise BackgroundError("INVALID_INPUT")
        parameters = {
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "output_format": request.output_format,
        }
        self._capabilities(parameters)
        prompt = "Background only. No products, packaging, logos or text. " + request.prompt
        started = time.monotonic()
        response = self._json(
            "POST",
            "images",
            {
                "model": self.config.model,
                "prompt": prompt,
                **parameters,
                "provider": {"only": [self.config.provider_tag], "allow_fallbacks": False},
            },
        )
        content, width, height = decode_background(response, request)
        usage = response.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        return BackgroundResult(
            content,
            width,
            height,
            {
                "schema_version": 1,
                "provider": "openrouter",
                "model": self.config.model,
                "provider_tag": self.config.provider_tag,
                "prompt": prompt,
                "template_version": request.template_version,
                "parameters": parameters,
                "correlation_id": request.correlation_id,
                "output_source": "openrouter-images-api",
                "sha256": hashlib.sha256(content).hexdigest(),
                "review_status": "PENDING",
                "duration_ms": round((time.monotonic() - started) * 1000),
                "usage": {
                    key: value
                    for key, value in usage.items()
                    if key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
                    and type(value) in (int, float)
                },
            },
        )


def decode_background(response, request):
    try:
        images = response["data"]
        if not isinstance(images, list) or len(images) != 1:
            raise ValueError()
        encoded = images[0]["b64_json"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE + 2) // 3):
            raise ValueError()
        content = base64.b64decode(encoded, validate=True)
        if len(content) > MAX_IMAGE:
            raise ValueError()
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            expected = request.output_format.upper()
            ratio_width, ratio_height = map(int, request.aspect_ratio.split(":"))
            if (
                image.format != expected
                or width * height > MAX_PIXELS
                or max(width, height) > 4096
                or getattr(image, "n_frames", 1) != 1
                or width * ratio_height != height * ratio_width
                or images[0].get("media_type", "image/" + request.output_format)
                != "image/" + request.output_format
            ):
                raise ValueError()
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
        return content, width, height
    except (KeyError, TypeError, ValueError, OSError, Image.DecompressionBombError):
        raise BackgroundError("INVALID_OUTPUT", ambiguous=True) from None
