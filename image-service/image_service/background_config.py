"""Server-only explicit configuration; never auto-load frontend or project .env files."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from image_service.background import BackgroundError
from image_service.egress import private_http_host, valid_proxy

PROVIDERS = ("openrouter", "openai", "gemini", "openai-compatible", "gemini-compatible")


@dataclass(frozen=True)
class ModelConfig:
    """One model endpoint. provider_tag is OpenRouter-only; base_url is third-party only."""

    api_key: str = field(repr=False)
    model: str
    provider_tag: str | None = None
    provider: str = "openrouter"
    base_url: str | None = None
    # None: environment configuration (MODEL_PROXY_URL applies); "": leased model, direct;
    # otherwise the leased model's proxy URL (may contain credentials, never logged).
    proxy: str | None = field(default=None, repr=False)
    # Stored model parameters as sorted (name, value) pairs, e.g. (("quality", "high"),) or
    # (("temperature", "0.7"),) (ADR-20261009-Q).
    parameters: tuple = ()


# Older name kept for existing imports; environment configuration is always OpenRouter.
OpenRouterConfig = ModelConfig


def load_config(environment=None):
    env = private_environment() if environment is None else environment
    key = env.get("OPENROUTER_API_KEY", "").strip()
    filename = env.get("OPENROUTER_API_KEY_FILE", "").strip()
    model = env.get("OPENROUTER_MODEL", "").strip()
    provider = env.get("OPENROUTER_PROVIDER_TAG", "").strip()
    try:
        if bool(key) == bool(filename):
            raise ValueError()
        if filename:
            path = Path(filename)
            if not path.is_absolute():
                raise ValueError()
            with path.open("rb") as source:
                raw = source.read(4097)
            if len(raw) > 4096:
                raise ValueError()
            key = raw.decode("utf-8").strip()
        if (
            not re.fullmatch(r"[\x21-\x7e]{1,4096}", key)
            or not re.fullmatch(r"[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+", model)
            or not re.fullmatch(r"[a-zA-Z0-9_./-]{1,100}", provider)
        ):
            raise ValueError()
    except (OSError, UnicodeError, ValueError):
        raise BackgroundError("CONFIGURATION") from None
    return OpenRouterConfig(key, model, provider)


def valid_base_url(value):
    """https anywhere; http only to a literal private IPv4 address. Same rule as Java."""
    if len(value) > 300 or not re.fullmatch(r"https?://[\x21-\x7e]+", value):
        return False
    parts = urlsplit(value)
    try:
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        return False
    if not parts.hostname or "@" in parts.netloc or parts.query or parts.fragment:
        return False
    return parts.scheme == "https" or private_http_host(value)


def config_from_mapping(mapping):
    """Validate a lease-delivered model configuration (any provider type)."""
    try:
        provider = str(mapping.get("provider", "openrouter"))
        key = str(mapping["api_key"]).strip()
        model = str(mapping["model"]).strip()
        tag = mapping.get("provider_tag")
        base = mapping.get("base_url")
        proxy = mapping.get("proxy_url", "")
        parameters = mapping.get("parameters") or {}
        if (
            not isinstance(parameters, dict)
            or len(parameters) > 10
            or any(
                not re.fullmatch(r"[a-z_]{1,40}", str(name))
                or not isinstance(value, str)
                or not re.fullmatch(r"[\w.-]{1,20}", value)
                for name, value in parameters.items()
            )
        ):
            raise ValueError()
        if (
            provider not in PROVIDERS
            or not re.fullmatch(r"[\x21-\x7e]{1,4096}", key)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}", model)
            # OpenRouter image models carry a routing tag (the adapter insists); a text model
            # may leave routing to OpenRouter (ADR-20261008-L). Other providers have none.
            or (tag is not None and provider != "openrouter")
            or (tag is not None and not re.fullmatch(r"[a-zA-Z0-9_./-]{1,100}", str(tag)))
            or (
                provider == "openrouter"
                and not re.fullmatch(r"[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+", model)
            )
            or provider.endswith("-compatible") != (isinstance(base, str) and valid_base_url(base))
            or (proxy != "" and not valid_proxy(proxy))
        ):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BackgroundError("CONFIGURATION") from None
    return ModelConfig(key, model, tag, provider, base, proxy, tuple(sorted(parameters.items())))


def private_environment():
    """Only an explicitly selected server file; never shell-evaluate or interpolate values."""
    env = dict(os.environ)
    filename = env.get("OPENROUTER_ENV_FILE")
    if filename:
        try:
            if not Path(filename).is_absolute():
                raise ValueError()
            with Path(filename).open("rb") as source:
                raw = source.read(16385)
            if len(raw) > 16384:
                raise ValueError()
            allowed = {
                "OPENROUTER_API_KEY",
                "OPENROUTER_API_KEY_FILE",
                "OPENROUTER_MODEL",
                "OPENROUTER_PROVIDER_TAG",
            }
            for line in raw.decode("utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, separator, value = line.partition("=")
                if separator and key.strip() in allowed:
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    env.setdefault(key.strip(), value)
        except (OSError, UnicodeError, ValueError):
            raise BackgroundError("CONFIGURATION") from None
    return env


if __name__ == "__main__":
    try:
        load_config()
    except BackgroundError:
        print("BLOCKED: required private OpenRouter configuration missing or invalid; no call made")
        raise SystemExit(2) from None
    print("Configuration syntax valid; credentials, model and provider NOT verified; no call made")
