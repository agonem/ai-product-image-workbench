"""Canvas export (ADR-20261010-W): a board of the conversation canvas composed into one picture.

No model is called. The board is filled with its background colour, then the layers are drawn in
order, bottom first. A picture is turned upright and scaled into its box (x, y, width and height
are shares of the board; whatever lies outside the board is cut off). Text uses the deployment
font with the selling-point rules (``typeset.render``): lines break only where the user broke
them and the block shrinks to fit its box, failing below 12 px instead of truncating.
"""

import hashlib
import io
import time
import uuid

from PIL import Image, ImageOps

from image_service import typeset
from image_service.generation import _fetch, budget, encode, fit_background

# Originals may be up to 100 megapixels (ADR-20260930-D); a picture never needs more than this.
PICTURE_SIDE = 4096


def _upright(raw):
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ("PNG", "JPEG"):
            raise ValueError("unsupported picture format")
        if image.format == "JPEG":
            image.draft("RGB", (PICTURE_SIDE, PICTURE_SIDE))
        image.load()
        upright = ImageOps.exif_transpose(image).convert("RGBA")
    upright.thumbnail((PICTURE_SIDE, PICTURE_SIDE), Image.Resampling.LANCZOS)
    return upright


def _paste(board, picture, layer):
    """Scale ``picture`` into the layer's box, drawing only the part that lies on the board."""
    width, height = board.size
    left, top = layer["x"] * width, layer["y"] * height
    box_w, box_h = layer["width"] * width, layer["height"] * height
    x0, y0 = max(0, round(left)), max(0, round(top))
    x1, y1 = min(width, round(left + box_w)), min(height, round(top + box_h))
    if x1 <= x0 or y1 <= y0:
        return
    # The visible part of the box, in the picture's own pixels.
    sx, sy = picture.width / box_w, picture.height / box_h
    # Shares such as 0.55 x 400 = 220.00000000000003 land a hair outside: keep within the picture.
    source = (
        max(0.0, (x0 - left) * sx),
        max(0.0, (y0 - top) * sy),
        min(picture.width, (x1 - left) * sx),
        min(picture.height, (y1 - top) * sy),
    )
    piece = picture.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS, box=source)
    board.alpha_composite(piece, dest=(x0, y0))


def _text(board, layer, font):
    width = board.width
    spec = {
        "title": layer["text"],
        "points": [],
        "color": layer["color"],
        "size": max(1, round(layer["size"] * width)),
        "align": layer["align"],
        "box": {key: layer[key] for key in ("x", "y", "width", "height")},
    }
    return typeset.render(board, spec, {}, font)


def compose(request, fetch, font=None):
    """The composed board as RGBA; ``fetch(image)`` returns the bytes of a frozen picture."""
    output = request["output"]
    width, height = output["width"], output["height"]
    budget((width, height))
    background = typeset.rgb(request["compose"]["background"]) + (255,)
    board = Image.new("RGBA", (width, height), background)
    for layer in request["compose"]["layers"]:
        if "image" in layer:
            _paste(board, _upright(fetch(layer["image"])), layer)
        else:
            board = _text(board, layer, font)
    return board


def process_composition(api, request, lease):
    started = time.monotonic()
    layers = request["compose"]["layers"]
    texts = sum(1 for layer in layers if "text" in layer)
    # Fail on a deployment problem before reading anything.
    font = typeset.font_path() if texts else None
    board = compose(request, lambda image: _fetch(api, request, lease, image), font)
    content = encode(board, request["output"]["format"])
    digest = hashlib.sha256(content).hexdigest()
    with Image.open(io.BytesIO(content)) as image:
        _, transform = fit_background(image.convert("RGBA"), image.width, image.height)

    def put(index, kind):
        info = api.call(
            "PUT",
            f"/internal/v1/work/{request['attempt_id']}/outputs/{index}",
            lease=lease,
            data=content,
        )
        if info["sha256"] != digest:
            raise ValueError("stored output hash mismatch")
        return {"ordinal": index, "kind": kind, **info}

    artifact = put(0, "COMPOSITE")
    # The composed picture is its own base: no model output exists.
    base = put(1, "BACKGROUND")
    provenance = {
        "schema_version": 1,
        "output_source": "composition",
        "sha256": digest,
        "inputs": {
            "layer_sha256": [layer["image"]["sha256"] for layer in layers if "image" in layer]
        },
        "transform": transform,
        "text_rendered": False,
        "review_status": "PENDING",
        "composition": {"layers": len(layers), "text_layers": texts},
    }
    return {
        "schema_version": 4,
        "event_type": "image.task.completed.v4",
        "event_id": uuid.uuid4().hex,
        **{key: request[key] for key in ("task_id", "attempt_id", "correlation_id")},
        "duration_ms": round((time.monotonic() - started) * 1000),
        "artifacts": [artifact],
        "generations": [{"ordinal": 0, "base": base, "provenance": provenance}],
    }
