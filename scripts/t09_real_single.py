"""Explicit one-call paid probe. A persistent intent prevents uncertain automatic resends."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "image-service"))
from image_service.background import BackgroundError, BackgroundRequest  # noqa: E402
from image_service.background_config import load_config  # noqa: E402
from image_service.openrouter import OpenRouterAdapter  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = load_config()
    request = BackgroundRequest(
        prompt=(
            "Empty pale oak tabletop in a quiet nursery, neutral cream wall, "
            "soft upper-left daylight, front three-quarter slightly downward camera. "
            "Clear central space and support surface near lower edge. "
            "No objects, people, products, letters or logos."
        ),
        template_version="scene-single-v3",
        correlation_id="t09-a-single",
        aspect_ratio="1:1",
        resolution=None,
        output_format=None,
    )
    with OpenRouterAdapter(config) as adapter:
        adapter._capabilities({"aspect_ratio": request.aspect_ratio})
        # Never delete or overwrite this intent, including after a timeout.
        with (args.output / "paid-intent.json").open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "model": config.model,
                    "provider": config.provider_tag,
                    "calls_authorized": 1,
                    "automatic_resend": False,
                },
                stream,
            )
        try:
            result = adapter.generate(request)
        except BackgroundError as error:
            (args.output / "result.json").write_text(
                json.dumps({"status": "FAILED", "code": error.code, "ambiguous": error.ambiguous}),
                encoding="utf-8",
            )
            raise SystemExit(
                "Single probe failed; inspect safe result, no automatic resend"
            ) from None
    name = "background.png" if result.content.startswith(b"\x89PNG") else "background.jpeg"
    (args.output / name).write_bytes(result.content)
    (args.output / "result.json").write_text(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "width": result.width,
                "height": result.height,
                "file": name,
                "sha256": hashlib.sha256(result.content).hexdigest(),
                "provenance": result.provenance,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"REAL single background: {result.width}x{result.height}; {name}; visual PENDING")


if __name__ == "__main__":
    main()
