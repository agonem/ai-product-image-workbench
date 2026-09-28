"""Isolated acceptance process only: mocked provider, real Worker and HTTPS Java transport."""

import hashlib
import io
import os
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "image-service"))
from image_service import background_config, openrouter, worker  # noqa: E402
from image_service.background import BackgroundError, BackgroundResult  # noqa: E402


class TestProvider:
    def __init__(self, _):
        self.count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def generate(self, request):
        self.count += 1
        if os.getenv("T09_TEST_FAIL") == "true" and self.count == 2:
            raise BackgroundError("PROVIDER_HTTP_429", retryable=True)
        data = io.BytesIO()
        Image.new("RGB", (256, 256), (170 + self.count * 10, 185, 200)).save(
            data, format=(request.output_format or "png").upper()
        )
        content = data.getvalue()
        return BackgroundResult(
            content,
            256,
            256,
            {
                "schema_version": 1,
                "provider": "mock-acceptance-only",
                "provider_tag": "mock",
                "model": "mock/background",
                "prompt": request.prompt,
                "template_version": request.template_version,
                "parameters": {
                    "aspect_ratio": request.aspect_ratio,
                    **(
                        {"resolution": request.resolution, "output_format": request.output_format}
                        if request.resolution
                        else {}
                    ),
                },
                "correlation_id": request.correlation_id,
                "output_source": "mock-not-real-generation",
                "sha256": hashlib.sha256(content).hexdigest(),
                "review_status": "PENDING",
                "duration_ms": 0,
                "usage": {},
            },
        )


if __name__ == "__main__":
    # This explicit test entry point is never imported by product code.
    background_config.load_config = lambda: None
    openrouter.OpenRouterAdapter = TestProvider
    if os.getenv("T09_TEST_TAMPER") == "true":
        original_process = worker.process

        def tampered_process(*args, **kwargs):
            receipt = original_process(*args, **kwargs)
            receipt["artifacts"] = receipt["artifacts"][:1]
            return receipt

        worker.process = tampered_process
    worker.main()
