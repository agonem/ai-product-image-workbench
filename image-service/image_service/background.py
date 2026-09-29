"""Internal image-generation adapter boundary; not a Worker contract.

Since ADR-20260929 (v4), requests carry up to four reference images (the product and optionally
the gift) for whole-image generation; a request without references stays valid for adapter tests.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol

PNG_SIGNATURE = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A])
JPEG_SIGNATURE = bytes([0xFF, 0xD8, 0xFF])


class BackgroundError(Exception):
    def __init__(self, code, *, retryable=False, ambiguous=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class BackgroundRequest:
    prompt: str = field(repr=False)
    template_version: str
    correlation_id: str
    aspect_ratio: str
    resolution: str | None
    output_format: str | None
    references: tuple = field(default=(), repr=False)

    def __post_init__(self):
        if (
            not isinstance(self.prompt, str)
            or not 1 <= len(self.prompt.strip()) <= 4000
            or re.search(r"https?://|data:|file:|base64", self.prompt, re.I)
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[\w.-]{1,100}", value)
                for value in (self.template_version, self.correlation_id)
            )
            or not isinstance(self.aspect_ratio, str)
            or not re.fullmatch(r"[1-9][0-9]?:[1-9][0-9]?", self.aspect_ratio)
            or self.resolution not in (None, "512", "1K", "2K", "4K")
            or self.output_format not in (None, "png", "jpeg")
            or (self.resolution is None) != (self.output_format is None)
            or not isinstance(self.references, tuple)
            or len(self.references) > 4
            or any(
                not isinstance(item, bytes)
                or not 0 < len(item) <= 10 * 1024 * 1024
                or not (item[:8] == PNG_SIGNATURE or item[:3] == JPEG_SIGNATURE)
                for item in self.references
            )
        ):
            raise BackgroundError("INVALID_INPUT")


@dataclass(frozen=True)
class BackgroundResult:
    content: bytes = field(repr=False)
    width: int
    height: int
    provenance: dict = field(repr=False)


class BackgroundAdapter(Protocol):
    def generate(self, request: BackgroundRequest) -> BackgroundResult: ...
