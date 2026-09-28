"""Server-only explicit configuration; never auto-load frontend or project .env files."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from image_service.background import BackgroundError


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str = field(repr=False)
    model: str
    provider_tag: str


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


def config_from_mapping(mapping):
    """Validate a lease-delivered provider configuration; same shapes as load_config."""
    try:
        key = str(mapping["api_key"]).strip()
        model = str(mapping["model"]).strip()
        provider = str(mapping["provider_tag"]).strip()
        if (
            not re.fullmatch(r"[\x21-\x7e]{1,4096}", key)
            or not re.fullmatch(r"[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+", model)
            or not re.fullmatch(r"[a-zA-Z0-9_./-]{1,100}", provider)
        ):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise BackgroundError("CONFIGURATION") from None
    return OpenRouterConfig(key, model, provider)


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
