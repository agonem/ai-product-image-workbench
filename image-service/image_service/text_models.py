"""Text models that rewrite a brief for an agent ("magic wand", ADR-20261008-L).

Same boundaries as the image adapters: only the configured endpoint is contacted (through the
model's own proxy setting), the call is never retried here, the response is size-bounded and
errors carry fixed codes without provider bodies. The rewritten brief is only a prompt for the
image model; the product guard is appended afterwards by the generation code.

- OpenRouter: POST https://openrouter.ai/api/v1/chat/completions. The routing tag is only a
  preference (other providers of the model are used when that one does not serve it); without
  a tag OpenRouter chooses. Only the brief travels here, never an image.
- OpenAI format (official or third-party): POST {root}/chat/completions.
- Gemini format (official or third-party): POST {root}/models/{model}:generateContent.
"""

import json
import re

import httpx

from image_service.background import BackgroundError
from image_service.egress import route
from image_service.providers import endpoint_root

MAX_RESPONSE = 1024 * 1024
MAX_OUTPUT = 1000
TIMEOUT = httpx.Timeout(90, connect=10)


def _request(config, system, user):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if config.provider == "openrouter":
        body = {"model": config.model, "messages": messages, "max_tokens": 800, "temperature": 0.7}
        if config.provider_tag:
            body["provider"] = {"order": [config.provider_tag], "allow_fallbacks": True}
        return (
            "https://openrouter.ai/api/v1/chat/completions",
            {"Authorization": "Bearer " + config.api_key},
            body,
        )
    if config.provider in ("openai", "openai-compatible"):
        return (
            endpoint_root(config) + "/chat/completions",
            {"Authorization": "Bearer " + config.api_key},
            {"model": config.model, "messages": messages, "max_tokens": 800, "temperature": 0.7},
        )
    if config.provider in ("gemini", "gemini-compatible"):
        return (
            endpoint_root(config) + f"/models/{config.model}:generateContent",
            {"x-goog-api-key": config.api_key},
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"maxOutputTokens": 800, "temperature": 0.7},
            },
        )
    raise BackgroundError("CONFIGURATION")


def _text(config, response):
    if config.provider in ("gemini", "gemini-compatible"):
        parts = response["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    content = response["choices"][0]["message"]["content"]
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content


def clean(text):
    """One plain brief: no code fences or wrapping quotes, tidy spacing, bounded length."""
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    text = text.strip().strip("\"'“”「」").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_OUTPUT].strip()


def rewrite(config, system, user, *, transport=None):
    """Returns (brief, usage) from one text-model call."""
    url, headers, body = _request(config, system, user)
    try:
        with (
            httpx.Client(
                timeout=TIMEOUT,
                follow_redirects=False,
                trust_env=False,
                proxy=route(config, url),
                transport=transport,
            ) as client,
            client.stream("POST", url, headers=headers, json=body) as response,
        ):
            if response.status_code != 200:
                status = response.status_code
                raise BackgroundError(
                    "PROVIDER_HTTP_" + str(status), retryable=status == 429 or status >= 500
                )
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_RESPONSE:
                    raise BackgroundError("RESPONSE_BUDGET")
            payload = json.loads(data)
    except httpx.RequestError:
        raise BackgroundError("PROVIDER_NETWORK", retryable=True) from None
    except (ValueError, UnicodeError):
        raise BackgroundError("INVALID_RESPONSE") from None
    try:
        brief = clean(_text(config, payload))
    except (KeyError, IndexError, TypeError, AttributeError):
        raise BackgroundError("INVALID_RESPONSE") from None
    if not brief:
        raise BackgroundError("INVALID_RESPONSE")
    usage = payload.get("usage") or payload.get("usageMetadata") or {}
    numbers = {k: v for k, v in usage.items() if isinstance(v, int | float)}
    return brief, numbers
