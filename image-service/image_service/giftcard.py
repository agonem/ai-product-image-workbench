"""Program-drawn gift card for the gift entry (ADR-20261008-H).

A white rounded card with a green "+" badge on its top edge holds the gift and, optionally, a short
verbatim label under it. The card is placed by the gift position on the exported image. The page
mirrors this geometry for its preview (frontend/src/workbench/generation.ts, giftCardBox).

- Original background: the gift photo is fitted whole, never cut out.
- White background (ADR-20261009-N, replacing the program cut-out of ADR-20261008-J): the model
  re-photographs the gift alone on white (one call per attempt, see generation.py). Here its
  backdrop is levelled to pure white, the picture is trimmed to the item with its own soft shadow
  and enlarged, and the edges fade into the white card, so no outline or seam is drawn. When the
  model did not return a white backdrop the picture is shown whole like a photo.
"""

import io

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from image_service import typeset

# Card width as a share of the output width.
SHARES = {"S": 0.22, "M": 0.28, "L": 0.34}
BADGE = (62, 155, 95)
LABEL = (43, 43, 43)
EDGE = (232, 232, 232)
WHITE = (255, 255, 255, 255)
MIN_LABEL_PX = 9
# Shapes (card corners, badge, plus sign, photo corners) are drawn this many times larger and
# scaled down, because Pillow draws circles and rounded corners with hard, stair-stepped edges.
SUPERSAMPLE = 4
# A model backdrop at least this light in every channel counts as white and is levelled to 255.
WHITE_BACKDROP = 225
# After levelling, pixels this far below white (darker or coloured) belong to the item or its
# shadow; fainter ones are backdrop.
INK = 14


def geometry(card, width, height, position):
    """Card rectangle (output pixels) for a gift position; the badge sits on its top edge."""
    cw = max(24, round(SHARES[card["size"]] * width))
    pad = max(2, round(cw * 0.08))
    top = max(3, round(cw * 0.12))
    image_h = round(cw * 0.62)
    label_h = round(cw * 0.2) if card.get("label") else 0
    ch = top + image_h + label_h + pad
    margin = round(0.04 * min(width, height))
    x = margin if position in ("LEFT", "BOTTOM_LEFT") else width - margin - cw
    y = height - margin - ch if position.startswith("BOTTOM") else (height - ch) // 2
    return {
        "x": x,
        "y": y,
        "width": cw,
        "height": ch,
        "pad": pad,
        "top": top,
        "image_height": image_h,
        "label_height": label_h,
        "badge_radius": max(3, round(cw * 0.1)),
        "corner": max(2, round(cw * 0.12)),
    }


def clear_area(box, width, height, position):
    """How much of the picture the model must leave empty for the card (whole percent)."""
    margin = round(0.04 * min(width, height))
    across = (box["width"] + margin) / width
    down = (box["height"] + box["badge_radius"] + margin) / height
    if not position.startswith("BOTTOM"):
        down = (box["height"] + box["badge_radius"]) / height
    return round(min(1, across) * 100), round(min(1, down) * 100)


def _gift(raw):
    """The gift photo upright, transparent areas on white; never cut out (ADR-20260929)."""
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ("PNG", "JPEG"):
            raise ValueError("unsupported gift format")
        image.load()
        upright = ImageOps.exif_transpose(image)
        rgba = upright.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    return flat


def _smooth(size, paint):
    """A transparent layer whose shapes have anti-aliased edges: ``paint(draw, scale)`` draws
    at SUPERSAMPLE times the size (coordinates multiplied by ``scale``), then the layer is
    averaged down with premultiplied alpha so edges blend instead of darkening."""
    big = Image.new("RGBA", (size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE), (0, 0, 0, 0))
    paint(ImageDraw.Draw(big), SUPERSAMPLE)
    return big.convert("RGBa").resize(size, Image.Resampling.BOX).convert("RGBA")


def _rounded_mask(size, radius):
    """An anti-aliased rounded-rectangle mask (L)."""
    layer = _smooth(
        size,
        lambda draw, k: draw.rounded_rectangle(
            (0, 0, size[0] * k - 1, size[1] * k - 1), radius * k, fill=(255, 255, 255, 255)
        ),
    )
    return layer.getchannel("A")


def _with_alpha(image, mask):
    """``image`` as RGBA with ``mask`` as its own alpha (straight alpha, colours untouched)."""
    rgba = image.convert("RGBA")
    rgba.putalpha(mask)
    return rgba


def _photo_tile(photo, room_w, room_h, cw):
    """A picture fitted whole inside the image area with softly rounded corners."""
    photo = photo.copy()
    photo.thumbnail((room_w, room_h), Image.Resampling.LANCZOS)
    mask = _rounded_mask(photo.size, max(1, round(cw * 0.04)))
    tile = Image.new("RGBA", (room_w, room_h), (255, 255, 255, 0))
    # The tile is empty, so a plain paste keeps straight alpha (a masked paste would darken edges).
    tile.paste(
        _with_alpha(photo, mask), ((room_w - photo.width) // 2, (room_h - photo.height) // 2)
    )
    return tile


def _backdrop(picture):
    """Median colour of a thin ring along the picture's edges."""
    w, h = picture.size
    ring = max(2, round(min(w, h) * 0.02))
    values = [[], [], []]
    for box in ((0, 0, w, ring), (0, h - ring, w, h), (0, 0, ring, h), (w - ring, 0, w, h)):
        for channel, band in enumerate(picture.crop(box).split()):
            values[channel].extend(band.tobytes())
    return [sorted(v)[len(v) // 2] for v in values]


def _white_tile(picture, room_w, room_h, cw):
    """The model's white-background gift, trimmed to the item and enlarged into the image area.

    Returns (tile, backdrop_was_white). The backdrop is levelled to pure white per channel (the
    item keeps its relative tones and the model's own soft shadow), the picture is trimmed to
    what differs from white, and the edges fade out so nothing marks the card.
    """
    rgb = picture.convert("RGB")
    backdrop = _backdrop(rgb)
    if min(backdrop) < WHITE_BACKDROP:
        return _photo_tile(rgb, room_w, room_h, cw), False
    rgb = Image.merge(
        "RGB",
        [
            band.point(lambda v, top=top: min(255, round(v * 255 / top)))
            for band, top in zip(rgb.split(), backdrop, strict=True)
        ],
    )
    r, g, b = rgb.split()
    # The darkest channel catches both darker and coloured pixels.
    ink = ImageOps.invert(ImageChops.darker(ImageChops.darker(r, g), b))
    solid = ink.point(lambda v: 255 if v > INK else 0)
    # Drop single specks of noise before measuring the item.
    solid = solid.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    bbox = solid.getbbox() or (0, 0, rgb.width, rgb.height)
    pad = round(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 0.06)
    bbox = (
        max(0, bbox[0] - pad),
        max(0, bbox[1] - pad),
        min(rgb.width, bbox[2] + pad),
        min(rgb.height, bbox[3] + pad),
    )
    piece = rgb.crop(bbox)
    margin = max(2, round(cw * 0.03))
    scale = min((room_w - 2 * margin) / piece.width, (room_h - 2 * margin) / piece.height)
    size = (max(1, round(piece.width * scale)), max(1, round(piece.height * scale)))
    piece = piece.resize(size, Image.Resampling.LANCZOS)
    # Fade the outer edge into the white card: any trace of off-white backdrop disappears.
    fade = max(1, round(min(size) * 0.06))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle((fade, fade, size[0] - 1 - fade, size[1] - 1 - fade), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(fade / 2))
    tile = Image.new("RGBA", (room_w, room_h), (255, 255, 255, 0))
    tile.paste(_with_alpha(piece, mask), ((room_w - size[0]) // 2, (room_h - size[1]) // 2))
    return tile, True


def _label_font(draw, label, box, font_path):
    """Largest label size that fits the card width; refuses rather than truncating."""
    room = box["width"] - 2 * box["pad"]
    size = max(MIN_LABEL_PX, round(box["width"] * 0.11))
    while size >= MIN_LABEL_PX:
        font = typeset._font(font_path, size)
        stroke = typeset._stroke(size)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font, stroke_width=stroke)
        if right - left <= room and bottom - top <= box["label_height"]:
            return font, stroke, (left, top, right, bottom)
        size -= 1
    raise typeset.TextOverflow("gift card label does not fit")


def check_label(card, box, font_path):
    """The label must fit the card; checked before the gift's paid call (same rule as render)."""
    if card.get("label"):
        _label_font(ImageDraw.Draw(Image.new("RGBA", (1, 1))), card["label"], box, font_path)


def render(gift_raw, card, box, font_path, white=None):
    """The card as a transparent sticker; returns (sticker, top-left offset, what was drawn).

    ``white`` is the model's re-shot of the gift on white with its provenance (ADR-20261009-N);
    without it the gift photo is shown as it is."""
    cw, ch, radius = box["width"], box["height"], box["badge_radius"]
    margin = max(2, round(cw * 0.06))
    shadow_y = max(1, round(cw * 0.015))
    sticker = Image.new("RGBA", (cw + 2 * margin, ch + radius + 2 * margin), (0, 0, 0, 0))
    left, top = margin, margin + radius
    # Soft shadow under the card.
    shadow = Image.new("RGBA", sticker.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (left, top + shadow_y, left + cw - 1, top + ch - 1 + shadow_y),
        box["corner"],
        fill=(0, 0, 0, 46),
    )
    sticker.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, round(cw * 0.03)))))
    # The white card with a thin grey edge, anti-aliased.
    sticker.alpha_composite(
        _smooth(
            sticker.size,
            lambda d, k: d.rounded_rectangle(
                (left * k, top * k, (left + cw) * k - 1, (top + ch) * k - 1),
                box["corner"] * k,
                fill=(255, 255, 255, 255),
                outline=EDGE + (255,),
                width=k,
            ),
        )
    )
    draw = ImageDraw.Draw(sticker)
    room_w, room_h = cw - 2 * box["pad"], box["image_height"]
    info = {"background": card.get("background", "ORIGINAL")}
    if white is not None:
        picture, provenance = white
        tile, levelled = _white_tile(picture, room_w, room_h, cw)
        info.update(reshoot=provenance, white_backdrop=levelled)
    else:
        tile = _photo_tile(_gift(gift_raw), room_w, room_h, cw)
    sticker.alpha_composite(tile, (left + box["pad"], top + box["top"]))
    label = card.get("label")
    if label:
        font, stroke, (bl, bt, br, bb) = _label_font(draw, label, box, font_path)
        band_top = top + box["top"] + room_h
        draw.text(
            (
                left + (cw - (br - bl)) / 2 - bl,
                band_top + (box["label_height"] - (bb - bt)) / 2 - bt,
            ),
            label,
            font=font,
            fill=LABEL + (255,),
            stroke_width=stroke,
            stroke_fill=LABEL + (255,),
        )
    # Green "+" badge centred on the top edge, with a white ring; anti-aliased (2026-10-09:
    # drawn directly, its edges were visibly stair-stepped at about 44 px across).
    cx, cy = left + cw / 2, top
    ring = max(1, radius * 0.18)
    inner = radius - ring
    arm, thick = inner * 0.55, max(1.0, inner * 0.28)

    def badge(d, k):
        x, y = cx * k, cy * k
        d.ellipse((x - radius * k, y - radius * k, x + radius * k, y + radius * k), fill=WHITE)
        d.ellipse((x - inner * k, y - inner * k, x + inner * k, y + inner * k), fill=BADGE + (255,))
        a, t = arm * k, thick * k / 2
        d.rounded_rectangle((x - a, y - t, x + a, y + t), t, fill=WHITE)
        d.rounded_rectangle((x - t, y - a, x + t, y + a), t, fill=WHITE)

    sticker.alpha_composite(_smooth(sticker.size, badge))
    return sticker, (box["x"] - margin, box["y"] - radius - margin), info


def apply(image, sticker, offset):
    """Places the card on an exported image (RGB or RGBA); returns RGBA."""
    result = image.convert("RGBA")
    layer = Image.new("RGBA", result.size, (0, 0, 0, 0))
    # Plain paste onto the empty layer keeps the sticker's straight alpha; pasting with itself
    # as the mask would square the alpha of soft edges and leave a dark fringe.
    layer.paste(sticker, offset)
    return Image.alpha_composite(result, layer)
