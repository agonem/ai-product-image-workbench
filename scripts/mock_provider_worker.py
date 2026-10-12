"""Isolated acceptance only: real v4 Worker with a mock model, never imported by product code.

The mock "model" paints the reference images it receives onto a coloured canvas (product large
on the left-centre, gift small at the bottom-right), so checks can prove that the originals were
really sent as references. Outputs are labelled mock-acceptance-only in provenance.
"""

import hashlib
import io
import os
import sys
import threading
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "image-service"))
from image_service import background_config, providers, text_models, worker  # noqa: E402
from image_service.background import BackgroundError, BackgroundResult  # noqa: E402

CALLS = {"count": 0}
LOCK = threading.Lock()  # WORKER_CONCURRENCY > 1 runs several generate() calls at once


class MockModel:
    def __init__(self, config=None):
        self.model = config.model if config is not None else "mock/model"
        self.tag = (config.provider_tag if config is not None else None) or "mock"
        self.provider = config.provider if config is not None else "openrouter"
        self.route = "proxy" if getattr(config, "proxy", None) else "direct"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def generate(self, request):
        with LOCK:
            CALLS["count"] += 1
            call = CALLS["count"]
        if os.getenv("MOCK_FAIL_AT") == str(call):
            raise BackgroundError("PROVIDER_HTTP_429", retryable=True)
        # Capacity checks stand in for model latency with a fixed pause (no paid call is made).
        time.sleep(float(os.getenv("MOCK_DELAY_SECONDS", "0")))
        rw, rh = map(int, request.aspect_ratio.split(":"))
        size = (1024, round(1024 * rh / rw)) if rw >= rh else (round(1024 * rw / rh), 1024)
        canvas = Image.new("RGB", size, (200 + call % 40, 220, 235))
        slots = [
            (round(size[0] * 0.45), round(size[1] * 0.35), 0.4),
            (round(size[0] * 0.75), round(size[1] * 0.72), 0.2),
        ]
        if request.template_version == "generation-v4-gift-white":
            # The gift re-shot on white (ADR-20261009-N): the gift photo, centred on white.
            canvas = Image.new("RGB", size, (252, 252, 250))
            slots = [(round(size[0] * 0.2), round(size[1] * 0.2), 0.6)]
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
                "provider": f"mock-acceptance-only:{self.provider}:{self.route}",
                "provider_tag": self.tag,
                "model": self.model,
                "prompt": request.prompt,
                "template_version": request.template_version,
                "parameters": {
                    "aspect_ratio": request.aspect_ratio,
                    "input_references": len(request.references),
                    # Quality or resolution the real adapter would send (ADR-20261009-Q).
                    **dict(request.parameters),
                },
                "correlation_id": request.correlation_id,
                "output_source": "mock-acceptance-only",
                "sha256": hashlib.sha256(content).hexdigest(),
                "review_status": "PENDING",
                "duration_ms": 0,
                "usage": {},
            },
        )


def mock_rewrite(config, system, user, *, images=(), max_tokens=800):
    """Deterministic stand-in for the text model: no paid call (ADR-20261008-L). With images it
    plays the look-first analysis (ADR-20261009-P) and names what it was shown."""
    need = user.splitlines()[0].removeprefix("需求：")
    if "模拟改写失败" in need or "模拟分析失败" in need:
        # A text model that the provider does not serve (the 2026-10-08 404).
        raise BackgroundError("PROVIDER_HTTP_404")
    if "模拟思考过长" in need and not os.getenv("MOCK_THINKING_DONE"):
        # A thinking model that used its whole output budget before answering (2026-10-12).
        raise BackgroundError("OUTPUT_LIMIT", retryable=True)
    persona = system.split("。")[0].removeprefix("你是")
    if images:
        names = "、".join(name for name, _ in images)
        if "看图" in persona or "分析师" in persona:
            return f"[看图分析：{names}] {need}，底图内容原样保留", {}
        return f"[{persona}看图改写：{names}] {need}，柔和自然光，奶油色调", {}
    return f"[{persona}改写] {need}，柔和自然光，奶油色调", {}


if __name__ == "__main__":
    text_models.rewrite = mock_rewrite
    background_config.load_config = lambda: None
    # Every provider type (OpenRouter, OpenAI, Gemini, third-party) is served by the mock.
    providers.model_adapter = MockModel
    worker.main()
