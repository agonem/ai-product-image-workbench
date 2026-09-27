"""Reproducible synthetic-only review package; no user uploads are consumed."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps, __version__

from image_service.poc import (
    MAX_PIXELS,
    MAX_SIDE,
    compose,
    extract_subject,
    segment_white,
    transform,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite originals or an earlier run.
    product = Image.new("RGB", (256, 320), "white")
    drawing = ImageDraw.Draw(product)
    drawing.rounded_rectangle(
        (40, 40, 212, 275), radius=18, fill="#87acb0", outline="#183942", width=4
    )
    drawing.rectangle((57, 90, 195, 228), fill="#fffaf0", outline="#183942", width=2)
    drawing.text((67, 108), "SYNTHETIC\nTEST LOGO\nABC-123\n250 mL", fill="#102730", spacing=12)
    drawing.line((58, 252, 192, 252), fill="#183942", width=3)
    gift = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    drawing = ImageDraw.Draw(gift)
    drawing.ellipse(
        (18, 18, 142, 142), fill=(214, 147, 77, 210), outline=(86, 50, 24, 255), width=3
    )
    drawing.text((47, 65), "TEST\nGIFT", fill=(50, 24, 12, 255), spacing=6)
    product.save(output / "original-product.png")
    gift.save(output / "original-gift.png")
    sources = [
        {"file": name, "sha256": digest(output / name)}
        for name in ("original-product.png", "original-gift.png")
    ]
    # Read the saved source bytes, rather than a segmentation provider's RGB output.
    with Image.open(output / "original-product.png") as image:
        original = image.copy()
    alpha = segment_white(original)
    alpha.save(output / "product-alpha.png")
    candidate = Image.new("RGBA", original.size, (255, 0, 255, 255))
    candidate.putalpha(alpha)
    candidate.save(output / "candidate-rgb-discarded.png")
    subject = extract_subject(original, candidate)
    subject.save(output / "subject-from-original.png")
    parameters = {"crop": [24, 20, 230, 280], "scale": 0.75, "angle": 17}
    transformed = transform(subject, **parameters)
    transformed.save(output / "transformed-product.png")
    with Image.open(output / "original-gift.png") as image:
        # Existing source alpha is retained; the candidate contributes no additional masking.
        gift_subject = extract_subject(image, Image.new("L", image.size, 255))
    gift_subject.getchannel("A").save(output / "gift-alpha.png")
    transformed_gift = transform(gift_subject, scale=0.8, angle=-12)
    transformed_gift.save(output / "transformed-gift.png")
    background = Image.new("RGBA", (640, 480), "#eee7d8")
    drawing = ImageDraw.Draw(background)
    for y in range(0, 480, 40):
        drawing.line((0, y, 640, y), fill="#d7d4c3", width=1)
    background.save(output / "synthetic-background.png")
    result = compose(background, [(transformed, (130, 100)), (transformed_gift, (455, 280))])
    result.save(output / "composite.png")
    result.convert("RGB").save(output / "composite.jpg", quality=95, subsampling=0)
    edges = alpha.filter(ImageFilter.FIND_EDGES)
    overlay = Image.new("RGBA", original.size, (220, 20, 30, 0))
    overlay.putalpha(edges)
    edge_review = Image.alpha_composite(original.convert("RGBA"), overlay)
    edge_review.save(output / "edges-pending-review.png")
    previews = [
        ("ORIGINAL / SYNTHETIC", original),
        ("EXTRACTED ALPHA", alpha),
        ("SOURCE RGB + ALPHA", subject),
        ("CROP / SCALE / ROTATE", transformed),
        ("EDGES: HUMAN REVIEW PENDING", edge_review),
        ("COMPOSITE / SYNTHETIC ONLY", result),
    ]
    sheet = Image.new("RGB", (960, 760), "#f6f6f2")
    drawing = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(previews):
        x, y = index % 3 * 320, index // 3 * 380
        drawing.text((x + 12, y + 12), label, fill="#162d34")
        thumbnail = ImageOps.contain(image.convert("RGBA"), (296, 332))
        sheet.paste(thumbnail, (x + (320 - thumbnail.width) // 2, y + 38), thumbnail)
    sheet.save(output / "comparison.png")
    report = {
        "poc_version": "t02-synthetic-v1",
        "synthetic": True,
        "review_status": "PENDING",
        "sources": sources,
        "pillow_version": __version__,
        "segmentation": {
            "algorithm": "border-connected-near-white-v1",
            "tolerance": 12,
            "quality_status": "EXPERIMENTAL_NOT_REAL_PRODUCT_VALIDATED",
        },
        "alpha": {
            "product_sha256": digest(output / "product-alpha.png"),
            "gift_sha256": digest(output / "gift-alpha.png"),
            "gift_source": "original transparency",
        },
        "order": [
            "crop in original coordinates",
            "uniform scale, half-up integer dimensions",
            "counterclockwise rotation at center, expand",
            "translation",
            "alpha composite",
        ],
        "layers": [
            {
                "source": "original-product.png",
                **parameters,
                "position": [130, 100],
                "actual_size": list(transformed.size),
            },
            {
                "source": "original-gift.png",
                "crop": [0, 0, 160, 160],
                "scale": 0.8,
                "angle": -12,
                "position": [455, 280],
                "actual_size": list(transformed_gift.size),
            },
        ],
        "resampling": {"resize": "LANCZOS", "rotate": "BICUBIC"},
        "canvas": {"width": 640, "height": 480, "platform_preset": None},
        "technical_budget": {"max_side": MAX_SIDE, "max_pixels": MAX_PIXELS, "max_layers": 16},
        "exports": [
            {"file": name, "sha256": digest(output / name)}
            for name in ("composite.png", "composite.jpg")
        ],
        "jpeg": {"quality": 95, "subsampling": 0},
        "human_review": {
            key: "PENDING" for key in ("edges", "logo_text", "colors", "gift", "crop", "layout")
        },
        "limitations": [
            "No real product samples",
            "No learned segmentation or AI generation",
            "White/transparent/fur/reflection quality unvalidated",
            "No API or Worker integration",
        ],
    }
    assert all(digest(output / item["file"]) == item["sha256"] for item in sources)
    (output / "manifest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output / "review.html").write_text(
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>T02 合成素材预研 · 待人工确认</title><style>
body{max-width:1100px;margin:32px auto;font:18px sans-serif;line-height:1.7;padding:16px}
img{max-width:100%}a{margin-right:16px}</style>
<h1>T02 合成素材预研 · 待人工确认</h1>
<p>所有图片由程序绘制，仅证明处理链路。不是用户商品，也不是真实生成成功。</p>
<p>请核对：主体边缘、测试文字、颜色、赠品、裁切范围、排版。全部视觉项待人工确认；真实商品样本仍缺失。</p>
<img src="comparison.png" alt="原图、alpha、来自原图的主体、变换、边缘和合成对照">
<p><a href="original-product.png">商品合成原图</a><a href="original-gift.png">赠品合成原图</a>
<a href="manifest.json">参数与哈希</a><a href="composite.png">PNG</a>
<a href="composite.jpg">JPEG</a></p>
<p>顺序：原图坐标裁切→等比例缩放→中心逆时针旋转→平移合成。候选分割的 RGB 被丢弃。
缩放、旋转与 JPEG 压缩会改变像素，不作逐像素相同承诺。</p></html>""",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory; existing paths rejected"
    )
    args = parser.parse_args()
    generate(args.output)
    print("Synthetic-only review bundle; human review PENDING:", args.output.resolve())
