"""Text models that look at the images and write the brief (ADR-20261008-L, ADR-20261009-P).

Same boundaries as the image adapters: only the configured endpoint is contacted (through the
model's own proxy setting), the call is never retried here, the response is size-bounded and
errors carry fixed codes without provider bodies. The brief is only a prompt for the image
model; the product guard is appended afterwards by the generation code.

Since ADR-20261009-P the chat images (downscaled copies, each introduced by its page name) are
sent with the request so the model can describe them before planning; the magic-wand rewrite of
older tasks sends text only.

- OpenRouter: POST https://openrouter.ai/api/v1/chat/completions. The routing tag is only a
  preference (other providers of the model are used when that one does not serve it); without
  a tag OpenRouter chooses.
- OpenAI format (official, DeepSeek official or third-party): POST {root}/chat/completions.
- Gemini format (official or third-party): POST {root}/models/{model}:generateContent.

Only the official parameters the admin filled in for the model are sent (ADR-20261012-AB):
temperature, output budget, thinking and so on are otherwise left to the vendor's defaults.
A thinking model can still use up its output budget before writing anything (OpenRouter then
answers ``finish_reason`` "length" with no content; Gemini ``MAX_TOKENS``). That is
``OUTPUT_LIMIT`` and may be retried (ADR-20261012-Y, the chat failures of 2026-10-12).
"""

import base64
import json
import re

import httpx

from image_service.background import BackgroundError, merge_parameters
from image_service.egress import route
from image_service.providers import endpoint_root

MAX_RESPONSE = 1024 * 1024
MAX_OUTPUT = 1600
TIMEOUT = httpx.Timeout(120, connect=10)


def _mime(content):
    return "image/png" if content[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


# What the system sets for each call; the model's stored parameters never replace it.
CHAT_FIELDS = ("model", "messages", "stream", "provider")
GEMINI_FIELDS = ("contents", "systemInstruction")


def _request(config, system, user, images=()):
    """``images`` are (name, bytes) pairs; each is introduced by its name before the picture."""
    if images:
        parts = [{"type": "text", "text": user}]
        for name, content in images:
            parts.append({"type": "text", "text": f"「{name}」："})
            data = base64.b64encode(content).decode("ascii")
            parts.append(
                {"type": "image_url", "image_url": {"url": f"data:{_mime(content)};base64,{data}"}}
            )
        content = parts
    else:
        content = user
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    if config.provider == "openrouter":
        body = merge_parameters(
            {"model": config.model, "messages": messages}, config.parameters, CHAT_FIELDS
        )
        if config.provider_tag:
            body["provider"] = {"order": [config.provider_tag], "allow_fallbacks": True}
        return (
            "https://openrouter.ai/api/v1/chat/completions",
            {"Authorization": "Bearer " + config.api_key},
            body,
        )
    if config.provider in ("openai", "deepseek", "openai-compatible"):
        return (
            endpoint_root(config) + "/chat/completions",
            {"Authorization": "Bearer " + config.api_key},
            merge_parameters(
                {"model": config.model, "messages": messages}, config.parameters, CHAT_FIELDS
            ),
        )
    if config.provider in ("gemini", "gemini-compatible"):
        parts = [{"text": user}]
        for name, data in images:
            parts.append({"text": f"「{name}」："})
            parts.append(
                {
                    "inline_data": {
                        "mime_type": _mime(data),
                        "data": base64.b64encode(data).decode("ascii"),
                    }
                }
            )
        return (
            endpoint_root(config) + f"/models/{config.model}:generateContent",
            {"x-goog-api-key": config.api_key},
            merge_parameters(
                {
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": parts}],
                },
                config.parameters,
                GEMINI_FIELDS,
            ),
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


def _cut_off(config, response):
    """Whether the model stopped because the output budget ran out."""
    try:
        if config.provider in ("gemini", "gemini-compatible"):
            return response["candidates"][0].get("finishReason") == "MAX_TOKENS"
        return response["choices"][0].get("finish_reason") == "length"
    except (KeyError, IndexError, TypeError, AttributeError):
        return False


def clean(text):
    """One plain brief: no code fences or wrapping quotes, tidy spacing, bounded length."""
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    text = text.strip().strip("\"'“”「」").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_OUTPUT].strip()


def rewrite(config, system, user, *, images=(), transport=None):
    """Returns (brief, usage) from one text-model call; ``images`` are (name, bytes) pairs."""
    url, headers, body = _request(config, system, user, images)
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
        text = _text(config, payload)
    except (KeyError, IndexError, TypeError, AttributeError):
        text = None
    brief = clean(text) if isinstance(text, str) else ""
    if not brief:
        if _cut_off(config, payload):
            raise BackgroundError("OUTPUT_LIMIT", retryable=True)
        raise BackgroundError("INVALID_RESPONSE")
    usage = payload.get("usage") or payload.get("usageMetadata") or {}
    numbers = {k: v for k, v in usage.items() if isinstance(v, int | float)}
    return brief, numbers
