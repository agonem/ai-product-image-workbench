"""Private offline real-sample review; no business approval or API integration."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, __version__

from image_service.poc import budget, compose, extract_subject, transform
from image_service.review_render import render_review


def rectangle(value, size):
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(v) is not int for v in value)
        or not 0 <= value[0] < value[2] <= size[0]
        or not 0 <= value[1] < value[3] <= size[1]
    ):
        raise ValueError("invalid rectangle")
    return tuple(value)


def guided_alpha(image, *, background, tolerance, seeds, exclude):
    """Explicit color-connected mask; enclosed areas require recorded background seeds."""
    budget(image.size)
    if (
        image.mode not in ("RGB", "RGBA")
        or type(tolerance) is not int
        or not 0 <= tolerance <= 32
        or len(background) != 3
        or any(type(v) is not int or not 0 <= v <= 255 for v in background)
    ):
        raise ValueError("invalid segmentation settings")
    candidate = Image.new("L", image.size)
    candidate.putdata(
        [
            255 if max(abs(pixel[i] - background[i]) for i in range(3)) <= tolerance else 0
            for pixel in image.convert("RGB").get_flattened_data()
        ]
    )
    width, height = image.size
    for point in seeds:
        if (
            len(point) != 2
            or any(type(v) is not int for v in point)
            or not 0 <= point[0] < width
            or not 0 <= point[1] < height
        ):
            raise ValueError("invalid background seed")
        if candidate.getpixel(tuple(point)) != 255:
            raise ValueError("seed does not match background; review required")
    borders = [(x, y) for x in range(width) for y in (0, height - 1)]
    borders += [(x, y) for y in range(height) for x in (0, width - 1)]
    for point in borders + [tuple(point) for point in seeds]:
        if candidate.getpixel(point) == 255:
            ImageDraw.floodfill(candidate, point, 128)
    alpha = candidate.point(lambda value: 0 if value == 128 else 255)
    draw = ImageDraw.Draw(alpha)
    for box in exclude:
        left, top, right, bottom = rectangle(box, image.size)
        draw.rectangle((left, top, right - 1, bottom - 1), fill=0)
    if alpha.getbbox() is None:
        raise ValueError("empty foreground; review required")
    return alpha


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_review(inputs, output, profile):
    inputs, output = Path(inputs), Path(output)
    budget(profile["canvas"])
    output.mkdir(parents=True, exist_ok=False)
    (output / "originals").mkdir()
    sources, originals = [], {}
    for kind in ("product", "gift", "reference"):
        name = kind + ".png"
        source = inputs / name
        if source.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("source byte budget exceeded")
        raw = source.read_bytes()
        target = output / "originals" / name
        target.write_bytes(raw)
        with Image.open(target) as image:
            budget(image.size)
            image.load()
            size = list(image.size)
            if kind != "reference":
                originals[kind] = image.convert("RGBA")
        sources.append(
            {
                "name": name,
                "file": "originals/" + name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": size,
                "role": "REFERENCE_ONLY" if kind == "reference" else kind.upper(),
            }
        )
        if digest(source) != digest(target):
            raise ValueError("source changed during copy")
    layers, render_layers = [], []
    for kind in ("product", "gift"):
        settings = profile[kind]
        original = originals[kind]
        mask = guided_alpha(
            original,
            **{key: settings[key] for key in ("background", "tolerance", "seeds", "exclude")},
        )
        mask.save(output / (kind + "-alpha.png"))
        subject = extract_subject(original, mask)
        subject.save(output / (kind + "-subject.png"))
        transformed = transform(subject, **settings["transform"])
        transformed.save(output / (kind + "-transformed.png"))
        render_layers.append((transformed, tuple(settings["position"])))
        layers.append(
            {
                "kind": kind,
                "original_file": "originals/" + kind + ".png",
                "original_sha256": digest(output / "originals" / (kind + ".png")),
                "alpha_file": kind + "-alpha.png",
                "alpha_sha256": digest(output / (kind + "-alpha.png")),
                "subject_layer_file": kind + "-subject.png",
                "subject_layer_sha256": digest(output / (kind + "-subject.png")),
                "transformed_file": kind + "-transformed.png",
                "transformed_sha256": digest(output / (kind + "-transformed.png")),
                "parameters": settings,
                "actual_size": list(transformed.size),
            }
        )
    result = compose(Image.new("RGB", tuple(profile["canvas"]), "#e5e9e2"), render_layers)
    result.save(output / "composite.png")
    result.convert("RGB").save(output / "composite.jpg", quality=95, subsampling=0)
    report = {
        "version": "t02-real-review-v1",
        "sample_id": profile["sample_id"],
        "synthetic": False,
        "review_status": "PENDING",
        "pillow_version": __version__,
        "algorithm": "explicit-color-connected-alpha-v1",
        "sources": sources,
        "layers": layers,
        "canvas": profile["canvas"],
        "background_source": "local solid color; no AI; no reference-image pixels",
        "transform_order": "source crop -> uniform LANCZOS resize -> center BICUBIC rotation"
        " -> translation -> alpha composite",
        "hash_semantics": "SHA-256 of encoded file bytes",
        "human_review": {
            key: "PENDING"
            for key in (
                "lion_print",
                "holes_straps",
                "gift_edges_count_shape",
                "text_separation",
                "crop",
                "layout",
                "shadow",
            )
        },
    }
    render_review(output, originals, profile)
    report["outputs"] = [
        {"file": p.name, "sha256": digest(p)}
        for p in sorted(output.iterdir())
        if p.suffix in (".png", ".jpg", ".html")
    ]
    (output / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_review(args.inputs, args.output, json.loads(args.profile.read_text(encoding="utf-8")))
    print("Real sample review bundle created; all visual checks PENDING:", args.output.resolve())
