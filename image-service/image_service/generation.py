"""v4 whole-image generation for the gift, scene and selling-point entries (ADR-20260929).

The product image (and the gift image for the gift entry) is sent to the configured model as a
reference; the model returns the whole image. The result is exported locally to the exact size
with a deterministic cover-centre crop, then the verbatim manual text is overlaid by the program.
A re-typeset request reuses a stored model output and never calls the model.

Selling points (ADR-20261008-G): one image per point; image i carries the shared title and point i.
With ``keep_original`` the product image itself, cropped to size, is the base of every image and
no model is called.
"""

import hashlib
import io
import math
import time
import uuid

from PIL import Image, ImageOps

from image_service import giftcard, typeset
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
# "Keep the original background" (ADR-20261008-H): the product image may be a finished picture
# with people, several items, text and graphics. The earlier wording called it a white-background
# product photo and forbade "other products", and the model removed a second child (task 1b6a4798).
KEEP_ORIGINAL = (
    "Reference image 1 is the original product image. It may already be a finished picture with "
    "people, several product items, text, logos and graphics. Keep everything in it exactly as it "
    "is and where it is: every person, every item, all text and graphics, the layout, colours, "
    "lighting and background. Do not remove, move, resize, recentre, crop or redraw anything."
)
KEEP_ORIGINAL_TEXT = (
    "Do not add any new text, letters, numbers, watermarks, stickers, badges or logos; keep the "
    "existing ones in reference image 1 unchanged."
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
SIDES = {"LEFT": "left", "CENTER": "centre", "RIGHT": "right"}
DEFAULT_PALETTE = {"badge_color": "#FFFFFF"}


def _raw(api, request, lease, field):
    return _fetch(api, request, lease, request[field])


def _fetch(api, request, lease, asset):
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


def _original(raw, width, height):
    """The product image as the base for keep-original selling images: upright, transparent
    areas on white, then the same cover-centre crop as model outputs. Returns the PNG of the
    cropped image and how it was cut from the original."""
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ("PNG", "JPEG"):
            raise ValueError("unsupported original format")
        if image.format == "JPEG":
            # Decode large JPEGs at a reduced scale, never below the output size.
            image.draft("RGB", (width, height))
        image.load()
        upright = ImageOps.exif_transpose(image)
        if upright.mode in ("RGBA", "LA", "PA") or (
            upright.mode == "P" and "transparency" in upright.info
        ):
            rgba = upright.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
        else:
            flat = upright.convert("RGB")
        cropped, transform = fit_background(flat, width, height)
    return encode(cropped, "png"), transform


def _text_for(request, ordinal):
    """The text drawn on image ``ordinal``: per-point tasks show the title and that one point."""
    text = request.get("text")
    if text and request.get("per_point") and "base_image" not in request:
        return {**text, "points": [text["points"][ordinal]]}
    return text


def _style(request, ordinal):
    styles = request["styles"]
    return styles[0] if request.get("per_point") else styles[ordinal]


def _text_area(box, product_position=None):
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
    if product_position:
        # The user chose the side (ADR-20261008-H); the text area still stays clean.
        return f"{clear} Place the product in the {SIDES[product_position]} part of the image."
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


def _gift_parts(request):
    """Gift entry: the gift is drawn by the model, or a card area is left empty for it."""
    position = POSITIONS[request["gift_position"]]
    background = request.get("background")
    original = background is not None and background["mode"] == "ORIGINAL"
    card = request.get("gift_card")
    if card:
        output = request["output"]
        width, height = output["width"], output["height"]
        box = giftcard.geometry(card, width, height, request["gift_position"])
        across, down = giftcard.clear_area(box, width, height, request["gift_position"])
        parts = [
            f"Keep the {position} area of the image, about {across}% of the width and {down}% "
            "of the height, completely empty plain background: a gift card will be added there "
            "later. Keep the product and everything else out of that area."
        ]
    elif original:
        parts = [
            "Reference image 2 is the free gift item. Show it exactly as it is (same shape, "
            "colours, markings and quantity), clearly smaller than the product, in empty space "
            f"at the {position} of the image, without covering any person, product, text or "
            "logo. Match its lighting and shadow to the picture."
        ]
    else:
        parts = [
            "Reference image 2 is the free gift item. Show it exactly as it is (same shape, "
            "colours, markings and quantity), clearly smaller than the product, placed at the "
            f"{position} of the image, near the product without covering it."
        ]
    return parts


def _custom_prompt(request):
    """Conversational generation (ADR-20261008-I): the user's words, plus the guard every entry
    keeps (business rule 1): the product stays exactly as photographed and no text is drawn."""
    editing = "edit_image" in request
    product = 2 if editing else 1
    parts = []
    if editing:
        parts.append(
            "Reference image 1 is the current picture to modify. Change only what the "
            "instruction asks for and keep everything else in it as it is."
        )
    parts.append(f"Reference image {product} is the product.")
    for index, _ in enumerate(request.get("references", [])):
        parts.append(f"Reference image {product + 1 + index} is an extra reference from the user.")
    parts.append(f"Instruction from the user: {request['prompt']}")
    parts.append(
        f"Whatever changes, keep the product from reference image {product} exactly as it is: "
        "the same shape, proportions, colours, materials, logo, printed text, markings and "
        "number of items."
    )
    parts.append(
        "Do not add any new text, letters, numbers, watermarks, stickers, badges or logos"
        + ("; keep existing text in reference image 1 unchanged." if editing else ".")
    )
    return " ".join(parts)


def build_prompt(request, ordinal):
    feature = request["feature_type"]
    if feature == "CUSTOM":
        return _custom_prompt(request)
    background = request.get("background") if feature == "GIFT" else None
    if background is not None and background["mode"] == "ORIGINAL":
        # ADR-20261008-H: everything in the product image stays; only the gift is added.
        return " ".join([KEEP_ORIGINAL, *_gift_parts(request), KEEP_ORIGINAL_TEXT])
    parts = [PRESERVE]
    if feature == "GIFT":
        parts += _gift_parts(request)
        if background is None:
            parts.append("Clean, soft, bright studio background.")
        elif background["mode"] == "SOLID":
            parts.append(
                f"Plain seamless studio background in the solid colour {background['color']}."
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
        style = _style(request, ordinal)
        parts.append(f"Setting and mood: {style['prompt']}. The product is the clear hero.")
        if request.get("per_point"):
            point = request["text"]["points"][ordinal]
            parts.append(
                "Express this selling point through the setting, props or composition, without "
                f"writing it anywhere in the image: {point}."
            )
    if request.get("style_prompt"):
        parts.append(f"Additional style: {request['style_prompt']}.")
    if request.get("text"):
        parts.append(_text_area(request["text"]["box"], request.get("product_position")))
    parts += [QUALITY, NO_TEXT]
    return " ".join(parts)


def _palette(request, ordinal):
    text = request["text"]
    if request.get("styles"):
        style = _style(request, ordinal)
        return {key: style[key] for key in ("badge_color", "badge_text_color", "accent_color")}
    return {**DEFAULT_PALETTE, "badge_text_color": text["color"], "accent_color": text["color"]}


def process_generation(api, request, lease, adapter, *, cancelled=None):
    started = time.monotonic()
    output = request["output"]
    count, width, height = output["count"], output["width"], output["height"]
    text = request.get("text")
    card = request.get("gift_card")
    # Fail on deployment problems before any billable call is made.
    font = typeset.font_path() if text or (card and card.get("label")) else None
    inputs = {"product_sha256": request["product_asset"]["sha256"]}
    retypeset = "base_image" in request
    original = not retypeset and bool(request.get("keep_original"))
    if retypeset:
        base_raw = _raw(api, request, lease, "base_image")
        inputs["base_sha256"] = request["base_image"]["sha256"]
    elif original:
        base_raw, source_transform = _original(
            _raw(api, request, lease, "product_asset"), width, height
        )
    else:
        references = [_reference(_raw(api, request, lease, "product_asset"))]
        if "edit_image" in request:
            # Conversational edit: the picture being changed comes first (ADR-20261008-I).
            references.insert(0, _reference(_raw(api, request, lease, "edit_image")))
            inputs["edit_sha256"] = request["edit_image"]["sha256"]
        if request.get("references"):
            references += [
                _reference(_fetch(api, request, lease, item)) for item in request["references"]
            ]
            inputs["reference_sha256"] = [item["sha256"] for item in request["references"]]
    if "gift_asset" in request:
        inputs["gift_sha256"] = request["gift_asset"]["sha256"]
        if card:
            # The card shows the gift photo itself; the model never draws it (ADR-20261008-H).
            box = giftcard.geometry(card, width, height, request["gift_position"])
            sticker, offset = giftcard.render(
                _raw(api, request, lease, "gift_asset"), card, box, font
            )
        elif not retypeset and not original:
            references.append(_reference(_raw(api, request, lease, "gift_asset")))
    artifacts, generations, hashes = [], [], set()
    for ordinal in range(count):
        if retypeset:
            content = base_raw
            provenance = {"schema_version": 1, "output_source": "retypeset"}
        elif original:
            content = base_raw
            provenance = {
                "schema_version": 1,
                "output_source": "original",
                "source_transform": source_transform,
            }
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
        # Keep-original images share one base by design; model outputs must all differ.
        if digest in hashes and not original:
            raise ValueError("duplicate generated image")
        hashes.add(digest)
        with Image.open(io.BytesIO(content)) as image:
            budget(image.size)
            final, transform = fit_background(image.convert("RGBA"), width, height)
        if card:
            final = giftcard.apply(final, sticker, offset)
        if text:
            final = typeset.render(
                final, _text_for(request, ordinal), _palette(request, ordinal), font
            )

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
