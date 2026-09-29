"""OpenRouter dedicated Images API: optional reference images, no fallback, no paid retry."""

import base64
import hashlib
import io
import json
import time

import httpx
from PIL import Image

from image_service.background import (
    PNG_SIGNATURE,
    BackgroundError,
    BackgroundRequest,
    BackgroundResult,
)
from image_service.egress import route

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
            proxy=route(config, "https://openrouter.ai"),
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

    def _capabilities(self, parameters, references=0):
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
                or (references and "image" not in architecture["input_modalities"])
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
                if references:
                    limit = endpoint["supported_parameters"]["input_references"]
                    if limit["type"] != "range" or int(limit["max"]) < references:
                        raise ValueError()
        except (KeyError, TypeError, ValueError, StopIteration):
            raise BackgroundError("UNSUPPORTED_CAPABILITY") from None

    def inspect(self):
        """Non-paid capability summary for administrators; performs GET requests only."""
        models = self._json("GET", "images/models")
        endpoints = self._json("GET", f"images/models/{self.config.model}/endpoints")
        try:
            model = next(item for item in models["data"] if item["id"] == self.config.model)
            architecture = model["architecture"]
            selected = [
                {
                    "provider_tag": item["provider_tag"],
                    "supported_parameters": item["supported_parameters"],
                }
                for item in endpoints["endpoints"]
                if item["provider_tag"] == self.config.provider_tag
            ]
            if endpoints["id"] != self.config.model:
                raise ValueError()
        except (KeyError, TypeError, ValueError, StopIteration):
            raise BackgroundError("UNSUPPORTED_CAPABILITY") from None
        return {
            "model": self.config.model,
            "provider_tag": self.config.provider_tag,
            "input_modalities": architecture.get("input_modalities", []),
            "output_modalities": architecture.get("output_modalities", []),
            "endpoints": selected,
        }

    def generate(self, request: BackgroundRequest) -> BackgroundResult:
        if not isinstance(request, BackgroundRequest):
            raise BackgroundError("INVALID_INPUT")
        parameters = {
            "aspect_ratio": request.aspect_ratio,
        }
        if request.resolution is not None:
            parameters.update(resolution=request.resolution, output_format=request.output_format)
        self._capabilities(parameters, len(request.references))
        prompt = request.prompt
        body = {
            "model": self.config.model,
            "prompt": prompt,
            **parameters,
            "provider": {"only": [self.config.provider_tag], "allow_fallbacks": False},
        }
        if request.references:
            # Official shape: base64 data URLs as image_url references (image-to-image).
            body["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:"
                        + ("image/png" if item[:8] == PNG_SIGNATURE else "image/jpeg")
                        + ";base64,"
                        + base64.b64encode(item).decode("ascii")
                    },
                }
                for item in request.references
            ]
        started = time.monotonic()
        response = self._json("POST", "images", body)
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
                "parameters": {**parameters, "input_references": len(request.references)},
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
            expected = request.output_format.upper() if request.output_format else None
            ratio_width, ratio_height = map(int, request.aspect_ratio.split(":"))
            if (
                image.format not in ("PNG", "JPEG")
                or (expected is not None and image.format != expected)
                or width * height > MAX_PIXELS
                or max(width, height) > 4096
                or getattr(image, "n_frames", 1) != 1
                or (expected is not None and width * ratio_height != height * ratio_width)
                or images[0].get("media_type", "image/" + image.format.lower())
                != "image/" + image.format.lower()
            ):
                raise ValueError()
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
        return content, width, height
    except (KeyError, TypeError, ValueError, OSError, Image.DecompressionBombError):
        raise BackgroundError("INVALID_OUTPUT", ambiguous=True) from None
