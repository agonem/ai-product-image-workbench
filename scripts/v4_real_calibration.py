"""Explicit, user-authorized paid calibration of v4 generation (ADR-20260929, step 3).

Runs a fixed plan of six real model calls with the authorized SAMPLE-001 images through the
real v4 processor (in memory, no database), then writes a side-by-side review page. A paid
intent file is written first; failed calls are recorded and never resent automatically.
Private: outputs go to an ignored directory; the API key is never printed or stored.
"""

import argparse
import hashlib
import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "image-service"))
from image_service import generation  # noqa: E402
from image_service.background import BackgroundError  # noqa: E402
from image_service.background_config import load_config  # noqa: E402
from image_service.openrouter import OpenRouterAdapter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "local-data/samples/SAMPLE-001"
PRESETS = json.loads((ROOT / "contracts/presets.json").read_text(encoding="utf-8"))
STYLES = {item["id"]: item for item in PRESETS["styles"]}
# Calibration-only sample wording, never published or presented as product claims.
TEXT_BOX = {"x": 0.05, "y": 0.05, "width": 0.46, "height": 0.5}
PLAN = [
    ("scene-preset", "SCENE", {"scene": {**PRESETS["scenes"][0]}}),
    (
        "scene-custom",
        "SCENE",
        {"scene": {"prompt": "浅色木桌，窗边柔和自然光，简洁留白"}, "style_prompt": "温暖、干净"},
    ),
    (
        "gift-text",
        "GIFT",
        {
            "gift_position": "BOTTOM_RIGHT",
            "background": {"mode": "SOLID", "color": "#FFF6EC"},
            "text": {
                "title": "下单即送\n防撞护角",
                "points": ["校准测试文字"],
                "color": "#4A2E1F",
                "size": 64,
                "align": "left",
                "box": TEXT_BOX,
            },
        },
    ),
    (
        "gift-plain",
        "GIFT",
        {"gift_position": "BOTTOM_LEFT", "background": {"mode": "GRADIENT", "color": "#EAF4FF"}},
    ),
    (
        "selling",
        "SELLING_POINT",
        {
            "styles": [STYLES["warm"], STYLES["green"]],
            "text": {
                "title": "校准测试标题",
                "points": ["测试卖点一", "测试卖点二", "测试卖点三"],
                "color": "#223344",
                "size": 60,
                "align": "left",
                "box": TEXT_BOX,
            },
        },
    ),
]


class LocalApi:
    def __init__(self, inputs):
        self.inputs, self.outputs = inputs, {}

    def call(self, method, path, **kwargs):
        if method == "GET":
            return self.inputs[path.split("/")[-1]]
        if method == "POST":
            return None
        data = kwargs["data"]
        index = int(path.split("/")[-1])
        self.outputs[index] = data
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            size = image.size
        return {
            "object_key": f"calibration/{index}.image",
            "sha256": hashlib.sha256(data).hexdigest(),
            "width": size[0],
            "height": size[1],
        }


def request(name, feature, extra, inputs):
    count = len(extra.get("styles", [])) or 1
    output = {"aspect_ratio": "1:1", "width": 800, "height": 800, "format": "png", "count": count}
    value = {
        "schema_version": 4,
        "task_id": name,
        "attempt_id": name,
        "correlation_id": name,
        "feature_type": feature,
        "product_asset": {
            "asset_id": "product",
            "sha256": hashlib.sha256(inputs["product"]).hexdigest(),
        },
        "presets_version": PRESETS["version"],
        "output": output,
        **extra,
    }
    if feature == "GIFT":
        value["gift_asset"] = {
            "asset_id": "gift",
            "sha256": hashlib.sha256(inputs["gift"]).hexdigest(),
        }
    return value


def figure(src, caption):
    return f"<figure><img src={src}><figcaption>{caption}</figcaption></figure>"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True)  # must not exist: never overwrite earlier evidence
    os.environ.setdefault("GENERATION_TEXT_FONT", "C:/Windows/Fonts/msyh.ttc")
    config = load_config()
    inputs = {
        "product": (SAMPLE / "product.png").read_bytes(),
        "gift": (SAMPLE / "gift.png").read_bytes(),
    }
    planned = sum(len(extra.get("styles", [])) or 1 for _, _, extra in PLAN)
    (args.output / "paid-intent.json").write_text(
        json.dumps(
            {
                "model": config.model,
                "provider": config.provider_tag,
                "calls_authorized": 6,
                "calls_planned": planned,
                "automatic_resend": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    assert planned == 6
    (args.output / "product.png").write_bytes(inputs["product"])
    (args.output / "gift.png").write_bytes(inputs["gift"])
    results, total = [], 0.0
    with OpenRouterAdapter(config) as adapter:
        for name, feature, extra in PLAN:
            api = LocalApi(inputs)
            try:
                receipt = generation.process_generation(
                    api, request(name, feature, extra, inputs), "lease", adapter
                )
            except BackgroundError as error:
                results.append(
                    {
                        "name": name,
                        "status": "FAILED",
                        "code": error.code,
                        "ambiguous": error.ambiguous,
                    }
                )
                continue
            count = len(receipt["artifacts"])
            files = []
            for index in range(count):
                final, base = f"{name}-{index}.png", f"{name}-{index}-model.png"
                (args.output / final).write_bytes(api.outputs[index])
                (args.output / base).write_bytes(api.outputs[count + index])
                provenance = receipt["generations"][index]["provenance"]
                cost = provenance.get("usage", {}).get("cost", 0)
                total += cost if isinstance(cost, (int, float)) else 0
                files.append(
                    {
                        "final": final,
                        "model_output": base,
                        "duration_ms": provenance.get("duration_ms"),
                        "usage": provenance.get("usage"),
                        "prompt": provenance["prompt"],
                    }
                )
            results.append(
                {"name": name, "status": "SUCCEEDED", "feature": feature, "files": files}
            )
    (args.output / "results.json").write_text(
        json.dumps(
            {"results": results, "total_cost_usd": round(total, 6)}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    rows = []
    for item in results:
        if item["status"] != "SUCCEEDED":
            rows.append(f"<h2>{item['name']} · 失败 {html.escape(item['code'])}</h2>")
            continue
        for entry in item["files"]:
            rows.append(
                f"<h2>{item['name']} · {item['feature']} · 待人工审核</h2><div class=row>"
                f"<figure><img src=product.png><figcaption>商品原图</figcaption></figure>"
                + (
                    "<figure><img src=gift.png><figcaption>赠品原图</figcaption></figure>"
                    if item["feature"] == "GIFT"
                    else ""
                )
                + figure(entry["final"], "最终图（含程序叠字）")
                + figure(entry["model_output"], "模型原始输出")
                + "</div><details><summary>提示词</summary><pre>"
                + html.escape(entry["prompt"])
                + "</pre></details>"
            )
    (args.output / "review.html").write_text(
        "<!doctype html><meta charset=utf-8><title>v4 真实校准 · 待人工审核</title><style>"
        "body{font-family:sans-serif;margin:24px}.row{display:flex;gap:12px;flex-wrap:wrap}"
        "figure{margin:0}img{width:260px;border:1px solid #ccc}pre{white-space:pre-wrap}</style>"
        "<h1>v4 真实校准（6 次授权调用）· 所有结果待人工审核</h1>"
        "<p>请对照原图检查：商品外形、狮子图案、颜色、织带、文字；赠品数量（4 只）与外观。</p>"
        + "".join(rows),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "results": [(r["name"], r["status"]) for r in results],
                "total_cost_usd": round(total, 6),
            }
        )
    )


if __name__ == "__main__":
    main()
