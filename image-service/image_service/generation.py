"""v4 whole-image generation for the gift, scene and selling-point entries (ADR-20260929).

The product image (and the gift image for the gift entry) is sent to the configured model as a
reference; the model returns the whole image. The result is exported locally to the exact size
with a deterministic cover-centre crop, then the verbatim manual text is overlaid by the program.
A re-typeset request reuses a stored model output and never calls the model.
"""

import hashlib
import io
import math
import time
import uuid

from PIL import Image, ImageOps

from image_service import typeset
from image_service.background import BackgroundRequest
from image_service.poc import budget


def encode(image, fmt):
    output = io.BytesIO()
    image = image.convert("RGB") if fmt == "jpeg" else image
    image.save(
        output, format=fmt.upper(), **({"quality": 95, "subsampling": 0} if fmt == "jpeg" else {})
    )
    return output.getvalue()


def fit_background(image, width, height):
    """Deterministic cover-centre crop to the exact export size; the geometry is recorded."""
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


REFERENCE_SIDE = 1536  # references are downscaled for transfer only; outputs are unaffected
ORIENTATION = 0x0112  # EXIF tag
# Originals are capped at 100 megapixels by the business service; allow them explicitly instead
# of Pillow's generic decompression-bomb default.
Image.MAX_IMAGE_PIXELS = 120_000_000
PRESERVE = (
    "Reference image 1 is the product photographed on a white background. Show this exact "
    "product: keep its shape, proportions, colours, materials, logo, printed text, markings and "
    "the number of items unchanged. Do not redesign, relabel, crop or duplicate it, and do not "
    "add other products."
)
NO_TEXT = (
    "Do not add any text, letters, numbers, watermarks, stickers, badges or logos other than "
    "those already printed on the items."
)
QUALITY = (
    "Professional e-commerce main image for baby products: soft realistic lighting, natural "
    "contact shadows, sharp focus on the product."
)
POSITIONS = {
    "BOTTOM_RIGHT": "bottom-right",
    "BOTTOM_LEFT": "bottom-left",
    "RIGHT": "right side",
    "LEFT": "left side",
}
DEFAULT_PALETTE = {"badge_color": "#FFFFFF"}


def _raw(api, request, lease, field):
    asset = request[field]
    raw = api.call(
        "GET",
        f"/internal/v1/work/{request['attempt_id']}/assets/{asset['asset_id']}",
        lease=lease,
        binary=True,
    )
    if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
        raise ValueError("source hash mismatch")
    return raw


def _reference(raw):
    """The model's copy of an original: the original bytes when they are small, upright and in
    a plain colour mode; otherwise an upright, RGB(A), downscaled PNG. Originals may carry EXIF
    orientation (phone photos), CMYK or 16-bit data and up to 100 megapixels (ADR-20260930-D)."""
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ("PNG", "JPEG"):
            raise ValueError("unsupported reference format")
        upright = image.getexif().get(ORIENTATION, 1) == 1
        plain = image.mode in ("RGB", "RGBA", "L", "LA", "P")
        small = max(image.size) <= REFERENCE_SIDE and len(raw) <= 4 * 1024 * 1024
        if upright and plain and small:
            return raw
        if image.format == "JPEG":
            # Decode large JPEGs at a reduced scale (never below the reference size).
            image.draft("RGB", (REFERENCE_SIDE, REFERENCE_SIDE))
        image.load()
        copy = ImageOps.exif_transpose(image)
        transparent = copy.mode in ("RGBA", "LA", "PA") or (
            copy.mode == "P" and "transparency" in copy.info
        )
        copy = copy.convert("RGBA" if transparent else "RGB")
        copy.thumbnail((REFERENCE_SIDE, REFERENCE_SIDE), Image.Resampling.LANCZOS)
        stream = io.BytesIO()
        copy.save(stream, format="PNG")
        return stream.getvalue()


def _text_area(box):
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    horizontal = "left" if cx < 0.4 else "right" if cx > 0.6 else "centre"
    vertical = "top" if cy < 0.4 else "bottom" if cy > 0.6 else "middle"
    area = (
        "centre" if (horizontal, vertical) == ("centre", "middle") else f"{vertical}-{horizontal}"
    )
    clear = (
        f"Keep the {area} area of the image (about {round(box['width'] * 100)}% of the width and "
        f"{round(box['height'] * 100)}% of the height) as clean, uncluttered background for text "
        "that will be added later, and keep the products out of that area."
    )
    # Calibration (2026-09-29): naming where the products go is followed far more reliably
    # than only asking to avoid the text area.
    if horizontal == "left":
        edge = _pct(box["x"] + box["width"])
        zone = f"the right part of the image, to the right of the first {edge} of the width"
    elif horizontal == "right":
        zone = f"the left part of the image, within the first {_pct(box['x'])} of the width"
    elif vertical == "top":
        edge = _pct(box["y"] + box["height"])
        zone = f"the lower part of the image, below the top {edge} of the height"
    elif vertical == "bottom":
        zone = f"the upper part of the image, above the bottom {_pct(1 - box['y'])} of the height"
    else:
        return clear
    return f"{clear} Place every product entirely in {zone}, so nothing overlaps the text area."


def _pct(value):
    return f"{round(min(1, max(0, value)) * 100)}%"


def build_prompt(request, ordinal):
    feature = request["feature_type"]
    parts = [PRESERVE]
    if feature == "GIFT":
        parts.append(
            "Reference image 2 is the free gift item. Show it exactly as it is (same shape, "
            "colours, markings and quantity), clearly smaller than the product, placed at the "
            f"{POSITIONS[request['gift_position']]} of the image, near the product without "
            "covering it."
        )
        background = request.get("background")
        if background is None:
            parts.append("Clean, soft, bright studio background.")
        elif background["mode"] == "SOLID":
            parts.append(
                f"Plain seamless studio background in the solid colour {background['color']}."
            )
        elif background["mode"] == "ORIGINAL":
            # ADR-20260930-E: the product photo's own background stays as it is.
            parts.append(
                "Keep the background of reference image 1 exactly as it is: the same colour, "
                "surface, lighting and surroundings. Do not replace, extend or restyle it; only "
                "add the gift."
            )
        elif background["mode"] == "GRADIENT":
            parts.append(
                f"Soft smooth gradient studio background based on the colour {background['color']}."
            )
        else:
            parts.append(f"Background: {background['prompt']}.")
    elif feature == "SCENE":
        parts.append(f"Place the product naturally in this setting: {request['scene']['prompt']}.")
    else:
        style = request["styles"][ordinal]
        parts.append(f"Setting and mood: {style['prompt']}. The product is the clear hero.")
    if request.get("style_prompt"):
        parts.append(f"Additional style: {request['style_prompt']}.")
    if request.get("text"):
        parts.append(_text_area(request["text"]["box"]))
    parts += [QUALITY, NO_TEXT]
    return " ".join(parts)


def _palette(request, ordinal):
    text = request["text"]
    if request.get("styles"):
        style = request["styles"][ordinal]
        return {key: style[key] for key in ("badge_color", "badge_text_color", "accent_color")}
    return {**DEFAULT_PALETTE, "badge_text_color": text["color"], "accent_color": text["color"]}


def process_generation(api, request, lease, adapter, *, cancelled=None):
    started = time.monotonic()
    output = request["output"]
    count, width, height = output["count"], output["width"], output["height"]
    text = request.get("text")
    # Fail on deployment problems before any billable call is made.
    font = typeset.font_path() if text else None
    inputs = {"product_sha256": request["product_asset"]["sha256"]}
    retypeset = "base_image" in request
    if retypeset:
        base_raw = _raw(api, request, lease, "base_image")
        inputs["base_sha256"] = request["base_image"]["sha256"]
    else:
        references = [_reference(_raw(api, request, lease, "product_asset"))]
    if "gift_asset" in request:
        inputs["gift_sha256"] = request["gift_asset"]["sha256"]
        if not retypeset:
            references.append(_reference(_raw(api, request, lease, "gift_asset")))
    artifacts, generations, hashes = [], [], set()
    for ordinal in range(count):
        if retypeset:
            content = base_raw
            provenance = {"schema_version": 1, "output_source": "retypeset"}
        else:
            if time.monotonic() - started >= 600 or (cancelled is not None and cancelled()):
                raise ValueError("generation lease or time budget exhausted")
            # Confirm the lease, then take the durable one-time permit for this paid call.
            attempt = request["attempt_id"]
            api.call("POST", f"/internal/v1/work/{attempt}/heartbeat", lease=lease)
            api.call("POST", f"/internal/v1/work/{attempt}/generation-calls/{ordinal}", lease=lease)
            generated = adapter.generate(
                BackgroundRequest(
                    prompt=build_prompt(request, ordinal),
                    template_version="generation-v4-" + request["feature_type"].lower(),
                    correlation_id=f"{attempt}-{ordinal}",
                    aspect_ratio=output["aspect_ratio"],
                    resolution=None,
                    output_format=None,
                    references=tuple(references),
                )
            )
            content = generated.content
            provenance = dict(generated.provenance)
        digest = hashlib.sha256(content).hexdigest()
        if digest in hashes:
            raise ValueError("duplicate generated image")
        hashes.add(digest)
        with Image.open(io.BytesIO(content)) as image:
            budget(image.size)
            final, transform = fit_background(image.convert("RGBA"), width, height)
        if text:
            final = typeset.render(final, text, _palette(request, ordinal), font)

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

        artifacts.append(put(ordinal, "COMPOSITE", encode(final, output["format"])))
        base = put(count + ordinal, "BACKGROUND", content)
        provenance.update(
            sha256=digest,
            inputs=inputs,
            transform=transform,
            text_rendered=bool(text),
            review_status="PENDING",
        )
        generations.append({"ordinal": ordinal, "base": base, "provenance": provenance})
    return {
        "schema_version": 4,
        "event_type": "image.task.completed.v4",
        "event_id": uuid.uuid4().hex,
        **{key: request[key] for key in ("task_id", "attempt_id", "correlation_id")},
        "duration_ms": round((time.monotonic() - started) * 1000),
        "artifacts": artifacts,
        "generations": generations,
    }
