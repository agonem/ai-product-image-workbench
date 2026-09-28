"""Real scene processor; product pixels never enter a generation request."""

import hashlib
import io
import math
import time
import uuid

from PIL import Image, ImageDraw, ImageFilter

from image_service.background import BackgroundRequest
from image_service.poc import budget, compose, extract_subject, transform


def encode(image, fmt):
    output = io.BytesIO()
    image = image.convert("RGB") if fmt == "jpeg" else image
    image.save(
        output, format=fmt.upper(), **({"quality": 95, "subsampling": 0} if fmt == "jpeg" else {})
    )
    return output.getvalue()


def source(api, request, lease, field):
    asset = request[field]
    raw = api.call(
        "GET",
        f"/internal/v1/work/{request['attempt_id']}/assets/{asset['asset_id']}",
        lease=lease,
        binary=True,
    )
    if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
        raise ValueError("source hash mismatch")
    with Image.open(io.BytesIO(raw)) as image:
        budget(image.size)
        image.load()
        return image.copy()


def composite(background, subject, box):
    width, height = background.size
    crop = subject.getchannel("A").getbbox()
    if crop is None or box["x"] + box["width"] > 1 or box["y"] + box["height"] > 1:
        raise ValueError("invalid subject placement")
    scale = min(
        width * box["width"] / (crop[2] - crop[0]), height * box["height"] / (crop[3] - crop[1])
    )
    layer = transform(subject, crop=crop, scale=scale)
    x = round(width * box["x"] + (width * box["width"] - layer.width) / 2)
    y = round(height * box["y"] + height * box["height"] - layer.height)
    shadow = Image.new("RGBA", background.size)
    draw = ImageDraw.Draw(shadow)
    foot = y + layer.height
    radius = max(1, round(layer.height * 0.025))
    draw.ellipse(
        (x + layer.width * 0.12, foot - radius, x + layer.width * 0.88, foot + radius),
        fill=(25, 24, 22, 65),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, radius)))
    result = compose(background, [(shadow, (0, 0)), (layer, (x, y))])
    return (
        result,
        shadow,
        {
            "crop": list(crop),
            "scale": scale,
            "angle": 0,
            "position": [x, y],
            "actual_size": list(layer.size),
            "shadow": "independent soft contact ellipse v1",
        },
    )


def fit_background(image, width, height):
    budget((width, height))
    scale = max(width / image.width, height / image.height)
    size = (math.ceil(image.width * scale), math.ceil(image.height * scale))
    left, top = (size[0] - width) // 2, (size[1] - height) // 2
    crop = (left, top, left + width, top + height)
    return image.resize(size, Image.Resampling.LANCZOS).crop(crop), {
        "strategy": "cover-center-v1",
        "source_size": list(image.size),
        "resized_size": list(size),
        "crop": list(crop),
        "target_size": [width, height],
    }


def process_scene(api, request, lease, adapter, *, cancelled=None):
    started = time.monotonic()
    original = source(api, request, lease, "product_asset")
    mask = source(api, request, lease, "product_alpha_asset")
    subject = extract_subject(original, mask)
    output = request["output"]
    count = output["count"]
    box = request["layout"]["product"]
    prompt = " ".join(
        request.get(field, "")
        for field in ("scene_template_prompt", "scene_custom_prompt", "style_custom_prompt")
    )
    prompt += (
        f" Empty product stage, front three-quarter camera view, soft light from upper left. "
        f"Leave clear product space inside normalized rectangle {box['x']},{box['y']},"
        f"{box['width']},{box['height']}; a continuous support surface at normalized y="
        f"{box['y'] + box['height']}. No people, products, accessories, logos or text."
    )
    artifacts, generations, hashes = [], [], set()
    for ordinal in range(count):
        if time.monotonic() - started >= 600 or (cancelled is not None and cancelled()):
            raise ValueError("scene processing lease or time budget exhausted")
        # Confirm the current lease immediately before each potentially billable call.
        api.call("POST", f"/internal/v1/work/{request['attempt_id']}/heartbeat", lease=lease)
        # Durable server-side fence survives Worker loss and another Worker's reclaim.
        api.call(
            "POST",
            f"/internal/v1/work/{request['attempt_id']}/generation-calls/{ordinal}",
            lease=lease,
        )
        generated = adapter.generate(
            BackgroundRequest(
                prompt=prompt,
                template_version="scene-composite-v1",
                correlation_id=f"{request['attempt_id']}-{ordinal}",
                aspect_ratio=output["aspect_ratio"],
                resolution=None,
                output_format=None,
            )
        )
        digest = hashlib.sha256(generated.content).hexdigest()
        if digest in hashes:
            raise ValueError("duplicate generated background")
        hashes.add(digest)
        with Image.open(io.BytesIO(generated.content)) as image:
            budget(image.size)
            background = image.convert("RGBA")
        background, background_transform = fit_background(
            background, output["width"], output["height"]
        )
        result, shadow, placement = composite(background, subject, box)

        def put(index, kind, data):
            info = api.call(
                "PUT",
                f"/internal/v1/work/{request['attempt_id']}/outputs/{index}",
                lease=lease,
                data=data,
            )
            if info["sha256"] != hashlib.sha256(data).hexdigest():
                raise ValueError("stored output hash mismatch")
            return {"ordinal": index, "kind": kind, **info}

        artifacts.append(put(ordinal, "COMPOSITE", encode(result, output["format"])))
        bg = put(count + ordinal, "BACKGROUND", generated.content)
        shade = put(count * 2 + ordinal, "ALPHA", encode(shadow, "png"))
        generations.append(
            {
                "ordinal": ordinal,
                "background": bg,
                "shadow": shade,
                "provenance": {
                    **generated.provenance,
                    "product_sha256": request["product_asset"]["sha256"],
                    "alpha_sha256": request["product_alpha_asset"]["sha256"],
                    "transform": placement,
                    "background_transform": background_transform,
                    "review_status": "PENDING",
                },
            }
        )
    return {
        "schema_version": 3,
        "event_type": "image.task.completed.v3",
        "event_id": uuid.uuid4().hex,
        **{key: request[key] for key in ("task_id", "attempt_id", "correlation_id")},
        "duration_ms": round((time.monotonic() - started) * 1000),
        "artifacts": artifacts,
        "background_generations": generations,
    }
