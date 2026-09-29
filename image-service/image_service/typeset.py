"""Deterministic text overlay for v4 images (ADR-20260929).

Only the verbatim manual text is drawn: an optional multi-line title and up to six selling-point
"pills" with a check mark, stacked top-down inside the user's text box. The requested title size
is the maximum; the layout shrinks uniformly to fit and fails instead of truncating.
"""

import os

from PIL import Image, ImageDraw, ImageFont

# Smallest title size (px) still treated as readable; points scale with the title.
MIN_TITLE_PX = 12


class TextOverflow(ValueError):
    """The text cannot fit its box at the minimum readable size; never truncated."""


class FontUnavailable(RuntimeError):
    """Text was requested but the deployment font is missing or unusable (retryable)."""


def font_path():
    path = os.getenv("GENERATION_TEXT_FONT", "")
    if not path:
        raise FontUnavailable("GENERATION_TEXT_FONT is not configured")
    return path


def rgb(value):
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def _stroke(size):
    return max(1, round(size / 36))


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError as error:
        raise FontUnavailable("configured text font is unusable") from error


def _layout(draw, text, size, path):
    """Measure every element at one title size; returns (fonts, elements, width, height)."""
    title_font = _font(path, size)
    point_size = max(10, round(size * 0.55))
    point_font = _font(path, point_size)
    spacing = round(size * 0.2)
    elements, height, width = [], 0, 0
    title = text.get("title")
    if title:
        box = draw.multiline_textbbox(
            (0, 0), title, font=title_font, spacing=spacing, stroke_width=_stroke(size)
        )
        elements.append(("title", box, box[2] - box[0], box[3] - box[1], title))
    points = text.get("points") or []
    pill_h = round(point_size * 1.9)
    icon = round(point_size * 1.15)
    pad = round(point_size * 0.6)
    for point in points:
        box = draw.textbbox((0, 0), point, font=point_font)
        elements.append(("point", box, (box[2] - box[0]) + icon + pad * 3, pill_h, point))
    gaps = []
    for index, element in enumerate(elements):
        if index:
            previous = elements[index - 1][0]
            gaps.append(round(size * 0.55) if previous == "title" else round(point_size * 0.6))
        width = max(width, element[2])
    height = sum(element[3] for element in elements) + sum(gaps)
    geometry = {"spacing": spacing, "pill_h": pill_h, "icon": icon, "pad": pad, "gaps": gaps}
    return (title_font, point_font), elements, width, height, geometry


def render(image, text, palette, path):
    """Return an RGBA copy of ``image`` with ``text`` drawn inside its normalized box."""
    canvas = image.convert("RGBA")
    width, height = canvas.size
    box = text["box"]
    left, top = box["x"] * width, box["y"] * height
    box_w, box_h = box["width"] * width, box["height"] * height
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    low, high, best = MIN_TITLE_PX, int(text["size"]), None
    while low <= high:  # the layout grows monotonically with the title size
        size = (low + high) // 2
        measured = _layout(draw, text, size, path)
        if measured[2] <= box_w and measured[3] <= box_h:
            best, low = measured, size + 1
        else:
            high = size - 1
    if best is None:
        raise TextOverflow("text does not fit its box at the minimum readable size")
    (title_font, point_font), elements, _, _, geometry = best
    color = rgb(text["color"])
    align = text["align"]
    y = top
    for index, (kind, bbox, element_w, element_h, content) in enumerate(elements):
        if index:
            y += geometry["gaps"][index - 1]
        if align == "left":
            x = left
        elif align == "right":
            x = left + box_w - element_w
        else:
            x = left + (box_w - element_w) / 2
        if kind == "title":
            draw.multiline_text(
                (round(x - bbox[0]), round(y - bbox[1])),
                content,
                font=title_font,
                fill=color + (255,),
                spacing=geometry["spacing"],
                align=align,
                # A thin same-colour stroke gives the title a semibold weight without a bold file.
                stroke_width=_stroke(title_font.size),
                stroke_fill=color + (255,),
            )
        else:
            _pill(
                draw, (x, y), (element_w, element_h), bbox, content, point_font, geometry, palette
            )
        y += element_h
    return Image.alpha_composite(canvas, layer)


def _pill(draw, origin, size, bbox, content, font, geometry, palette):
    x, y = origin
    width, height = size
    pad, icon = geometry["pad"], geometry["icon"]
    draw.rounded_rectangle(
        (round(x), round(y), round(x + width), round(y + height)),
        radius=height // 2,
        fill=rgb(palette["badge_color"]) + (235,),
    )
    cx, cy = x + pad, y + (height - icon) / 2
    draw.ellipse(
        (round(cx), round(cy), round(cx + icon), round(cy + icon)),
        fill=rgb(palette["accent_color"]) + (255,),
    )
    stroke = max(2, round(icon / 8))
    draw.line(
        [
            (cx + icon * 0.27, cy + icon * 0.53),
            (cx + icon * 0.44, cy + icon * 0.70),
            (cx + icon * 0.74, cy + icon * 0.34),
        ],
        fill=(255, 255, 255, 255),
        width=stroke,
        joint="curve",
    )
    text_x = cx + icon + pad * 0.8 - bbox[0]
    text_y = y + (height - (bbox[3] - bbox[1])) / 2 - bbox[1]
    draw.text(
        (round(text_x), round(text_y)),
        content,
        font=font,
        fill=rgb(palette["badge_text_color"]) + (255,),
    )
