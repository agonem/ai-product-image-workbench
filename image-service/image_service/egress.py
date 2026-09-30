"""Outbound routing for model calls: an explicit proxy for public endpoints only.

Ambient proxy variables (HTTPS_PROXY, ...) are always ignored by the model clients. An intranet
relay addressed by a private IPv4 literal is reached directly, never through the proxy.
"""

import ipaddress
import os
from urllib.parse import urlsplit

from image_service.background import BackgroundError


def private_http_host(url):
    """True for http(s) URLs whose host is a literal private IPv4 address (10/8, 172.16/12,
    192.168/16); used both to allow intranet http relays and to bypass the proxy for them."""
    try:
        address = ipaddress.IPv4Address(urlsplit(url).hostname or "")
    except ValueError:
        return False
    return any(
        address in ipaddress.IPv4Network(network)
        for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )


def valid_proxy(value):
    """http(s) proxy: optional credentials, host and port only. Same rule as Java."""
    if not isinstance(value, str) or len(value) > 300:
        return False
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
        and all(33 <= ord(c) <= 126 for c in value)
    )


def route(config, url):
    """Proxy for one model call. A leased model carries its own setting ("" = direct); only the
    development-only environment configuration falls back to MODEL_PROXY_URL."""
    explicit = getattr(config, "proxy", None)
    if explicit is not None:
        # An intranet relay is always reached directly, even for a model marked "use proxy".
        return None if not explicit or private_http_host(url) else explicit
    return proxy_for(url)


def proxy_for(url):
    """Proxy for a model endpoint: MODEL_PROXY_URL (or the older OPENROUTER_PROXY_URL)."""
    if private_http_host(url):
        return None
    value = (os.getenv("MODEL_PROXY_URL") or os.getenv("OPENROUTER_PROXY_URL") or "").strip()
    if not value:
        return None
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme in ("http", "https")
            and bool(parts.hostname)
            and parts.path in ("", "/")
            and not parts.query
            and not parts.fragment
        )
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        valid = False
    if not valid:
        raise BackgroundError("CONFIGURATION")
    return value
