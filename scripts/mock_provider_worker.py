"""Isolated acceptance only: real v4 Worker with a mock model, never imported by product code.

The mock "model" paints the reference images it receives onto a coloured canvas (product large
on the left-centre, gift small at the bottom-right), so checks can prove that the originals were
really sent as references. Outputs are labelled mock-acceptance-only in provenance.
"""

import hashlib
import io
import os
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "image-service"))
from image_service import background_config, openrouter, worker  # noqa: E402
from image_service.background import BackgroundError, BackgroundResult  # noqa: E402

CALLS = {"count": 0}


class MockModel:
    def __init__(self, config=None):
        self.model = config.model if config is not None else "mock/model"
        self.tag = config.provider_tag if config is not None else "mock"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def generate(self, request):
        CALLS["count"] += 1
        if os.getenv("MOCK_FAIL_AT") == str(CALLS["count"]):
            raise BackgroundError("PROVIDER_HTTP_429", retryable=True)
        rw, rh = map(int, request.aspect_ratio.split(":"))
        size = (1024, round(1024 * rh / rw)) if rw >= rh else (round(1024 * rw / rh), 1024)
        canvas = Image.new("RGB", size, (200 + CALLS["count"] % 40, 220, 235))
        slots = [
            (round(size[0] * 0.45), round(size[1] * 0.35), 0.4),
            (round(size[0] * 0.75), round(size[1] * 0.72), 0.2),
        ]
        for reference, (x, y, fraction) in zip(request.references, slots, strict=False):
            with Image.open(io.BytesIO(reference)) as image:
                side = round(size[0] * fraction)
                piece = image.convert("RGB")
                piece.thumbnail((side, side))
                canvas.paste(piece, (x, y))
        stream = io.BytesIO()
        canvas.save(stream, format="PNG")
        content = stream.getvalue()
        return BackgroundResult(
            content,
            *size,
            {
                "schema_version": 1,
                "provider": "mock-acceptance-only",
                "provider_tag": self.tag,
                "model": self.model,
                "prompt": request.prompt,
                "template_version": request.template_version,
                "parameters": {
                    "aspect_ratio": request.aspect_ratio,
                    "input_references": len(request.references),
                },
                "correlation_id": request.correlation_id,
                "output_source": "mock-acceptance-only",
                "sha256": hashlib.sha256(content).hexdigest(),
                "review_status": "PENDING",
                "duration_ms": 0,
                "usage": {},
            },
        )


if __name__ == "__main__":
    background_config.load_config = lambda: None
    openrouter.OpenRouterAdapter = MockModel
    worker.main()
