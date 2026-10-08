"""Program-drawn gift card for the gift entry (ADR-20261008-H).

A white rounded card with a green "+" badge on its top edge holds the original gift image (fitted
whole, never cut out) and, optionally, a short verbatim label under it. The card is placed by the
gift position on the exported image, so the gift always looks exactly like its photo. The page
mirrors this geometry for its preview (frontend/src/workbench/generation.ts, giftCardBox).
"""

import io

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from image_service import typeset

# Card width as a share of the output width.
SHARES = {"S": 0.22, "M": 0.28, "L": 0.34}
BADGE = (62, 155, 95)
LABEL = (43, 43, 43)
EDGE = (232, 232, 232)
MIN_LABEL_PX = 9


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


def render(gift_raw, card, box, font_path):
    """The card as a transparent sticker; returns (sticker, top-left offset on the output)."""
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
    draw = ImageDraw.Draw(sticker)
    draw.rounded_rectangle(
        (left, top, left + cw - 1, top + ch - 1),
        box["corner"],
        fill=(255, 255, 255, 255),
        outline=EDGE + (255,),
    )
    # The gift photo, fitted whole inside the image area with softly rounded corners.
    gift = _gift(gift_raw)
    room_w, room_h = cw - 2 * box["pad"], box["image_height"]
    gift.thumbnail((room_w, room_h), Image.Resampling.LANCZOS)
    mask = Image.new("L", gift.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, gift.width - 1, gift.height - 1), max(1, round(cw * 0.04)), fill=255
    )
    sticker.paste(
        gift,
        (
            left + box["pad"] + (room_w - gift.width) // 2,
            top + box["top"] + (room_h - gift.height) // 2,
        ),
        mask,
    )
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
    # Green "+" badge centred on the top edge, with a white ring.
    cx, cy = left + cw / 2, top
    ring = max(1, round(radius * 0.18))
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(255, 255, 255, 255))
    inner = radius - ring
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=BADGE + (255,))
    arm, thick = inner * 0.55, max(1, round(inner * 0.28))
    draw.rounded_rectangle(
        (cx - arm, cy - thick / 2, cx + arm, cy + thick / 2), thick / 2, fill=(255, 255, 255, 255)
    )
    draw.rounded_rectangle(
        (cx - thick / 2, cy - arm, cx + thick / 2, cy + arm), thick / 2, fill=(255, 255, 255, 255)
    )
    return sticker, (box["x"] - margin, box["y"] - radius - margin)


def apply(image, sticker, offset):
    """Places the card on an exported image (RGB or RGBA); returns RGBA."""
    result = image.convert("RGBA")
    layer = Image.new("RGBA", result.size, (0, 0, 0, 0))
    layer.paste(sticker, offset, sticker)
    return Image.alpha_composite(result, layer)
