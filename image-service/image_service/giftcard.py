"""Program-drawn gift card for the gift entry (ADR-20261008-H).

A white rounded card with a green "+" badge on its top edge holds the original gift image (fitted
whole, never cut out) and, optionally, a short verbatim label under it. The card is placed by the
gift position on the exported image, so the gift always looks exactly like its photo. The page
mirrors this geometry for its preview (frontend/src/workbench/generation.ts, giftCardBox).

With the white background (ADR-20261008-J) the gift is separated from a plain photo backdrop
(the product is never cut out), cropped to its outline and enlarged; light gifts get a thin grey
outline and a soft shadow so they stay visible on white. When the backdrop is not plain enough the
card keeps the original photo background and says so in the receipt.
"""

import io

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from image_service import typeset

# Card width as a share of the output width.
SHARES = {"S": 0.22, "M": 0.28, "L": 0.34}
BADGE = (62, 155, 95)
LABEL = (43, 43, 43)
EDGE = (232, 232, 232)
MIN_LABEL_PX = 9
# Backdrop separation (white card background); working size and limits, see separate().
WORK_SIDE = 360
OUTLINE = (190, 197, 207)


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


def _side(pixels, xs, height):
    """Backdrop colour down one image edge: per-row median, smoothed over 15 rows."""
    rows = [
        [sorted(pixels[x, y][c] for x in xs)[len(xs) // 2] for c in range(3)] for y in range(height)
    ]
    out = []
    for y in range(height):
        window = rows[max(0, y - 7) : y + 8]
        out.append([sorted(row[c] for row in window)[len(window) // 2] for c in range(3)])
    return out


def separate(photo):
    """Mask (L, photo size) of the gift on a plain backdrop, or None when unsure.

    The backdrop is modelled per row from the left and right edges (copes with a wall/table
    horizon and light falloff). A pixel belongs to the gift when its colour tone differs from the
    backdrop, or it is clearly brighter, or much darker than a shadow would be. Everything not
    reachable from the edges is the gift (holes included); small islands such as printed words
    on the backdrop are dropped; thin strips such as a contact line are opened away.
    """
    small = photo.copy()
    small.thumbnail((WORK_SIDE, WORK_SIDE), Image.Resampling.LANCZOS)
    w, h = small.size
    if w < 16 or h < 16:
        return None
    px = small.load()
    left, right = _side(px, range(0, 4), h), _side(px, range(w - 4, w), h)
    score = Image.new("L", (w, h), 0)
    sp = score.load()
    for y in range(h):
        lrow, rrow = left[y], right[y]
        for x in range(w):
            t = x / (w - 1)
            r, g, b = px[x, y]
            br = lrow[0] + (rrow[0] - lrow[0]) * t
            bg = lrow[1] + (rrow[1] - lrow[1]) * t
            bb = lrow[2] + (rrow[2] - lrow[2]) * t
            lum, blum = (r + g + b) / 3 + 1, (br + bg + bb) / 3 + 1
            chroma = (
                abs(r / lum - br / blum) + abs(g / lum - bg / blum) + abs(b / lum - bb / blum)
            ) * 600
            bright = lum - blum
            if bright < -10:
                # A shadow on the backdrop is darker and a little greyer: weigh tone less.
                chroma *= 0.5
            sp[x, y] = max(0, min(255, int(max(chroma, bright * 2.2, -bright - 55))))
    score = score.filter(ImageFilter.GaussianBlur(1.2))
    ring = [(x, y) for x in range(w) for y in (0, 1, 2, h - 3, h - 2, h - 1)]
    ring += [(x, y) for y in range(3, h - 3) for x in (0, 1, 2, w - 3, w - 2, w - 1)]
    edge = sorted(score.getpixel(point) for point in ring)
    noise = edge[int(len(edge) * 0.9)]
    if noise > 45:
        return None  # busy backdrop: keep the photo as it is
    threshold = max(20, min(90, noise + 18))
    # Close small gaps in the outline so the backdrop fill cannot leak inside.
    solid = score.point(lambda v: 255 if v > threshold else 0).filter(ImageFilter.MaxFilter(5))
    backdrop = solid.point(lambda v: 0 if v else 255)
    bp = backdrop.load()
    for point in ring:
        if bp[point] == 255:
            ImageDraw.floodfill(backdrop, point, 128)
    outside = backdrop.point(lambda v: 255 if v == 128 else 0)
    # Closing can trap a sliver of backdrop against the outline (e.g. between the gift and its
    # contact shadow). Give back backdrop-like pixels in a narrow band along the outside only,
    # so the fill still cannot reach deep into a light gift.
    band = outside.filter(ImageFilter.MaxFilter(17))
    low = score.point(lambda v: 255 if v <= threshold else 0)
    region = ImageChops.lighter(outside, ImageChops.multiply(low, band))
    rp = region.load()
    for point in ring:
        if rp[point] == 255:
            ImageDraw.floodfill(region, point, 128)
    gift = region.point(lambda v: 0 if v == 128 else 255)
    gift = gift.filter(ImageFilter.MinFilter(7)).filter(ImageFilter.MaxFilter(7))
    # Keep the large parts (a set of several items stays); printed words are small islands.
    coarse = gift.resize((max(1, w // 3), max(1, h // 3)), Image.Resampling.NEAREST)
    cw_, ch_ = coarse.size
    parts = []
    for y in range(ch_):
        for x in range(cw_):
            if coarse.getpixel((x, y)) == 255:
                before = coarse.histogram()[100]
                ImageDraw.floodfill(coarse, (x, y), 100)
                parts.append(((x, y), coarse.histogram()[100] - before))
                coarse = coarse.point(lambda v: 101 if v == 100 else v)
    largest = max((area for _, area in parts), default=0)
    if not largest:
        return None
    for point, area in parts:
        if area >= 0.2 * largest:
            ImageDraw.floodfill(coarse, point, 200)
    keep = coarse.point(lambda v: 255 if v == 200 else 0).resize((w, h), Image.Resampling.NEAREST)
    mask = ImageChops.multiply(gift, keep.filter(ImageFilter.MaxFilter(9)))
    share = sum(mask.histogram()[128:]) / (w * h)
    if not 0.03 <= share <= 0.9:
        return None
    return mask.filter(ImageFilter.GaussianBlur(0.8)).resize(photo.size, Image.Resampling.BILINEAR)


def _is_light(photo, mask):
    """A light gift (cream, off-white...) needs an outline to stand out on white."""
    grey = photo.convert("L")
    solid = mask.point(lambda v: 255 if v > 200 else 0)
    histogram = grey.histogram(mask=solid)
    total = sum(histogram)
    return bool(total) and sum(i * n for i, n in enumerate(histogram)) / total > 195


def _cutout(gift, room_w, room_h, cw):
    """The separated gift on white, cropped to its outline and enlarged to the image area."""
    mask = separate(gift)
    if mask is None:
        return None
    bbox = mask.point(lambda v: 255 if v > 40 else 0).getbbox()
    if not bbox:
        return None
    pad = round(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 0.04)
    bbox = (
        max(0, bbox[0] - pad),
        max(0, bbox[1] - pad),
        min(gift.width, bbox[2] + pad),
        min(gift.height, bbox[3] + pad),
    )
    light = _is_light(gift, mask)
    piece, alpha = gift.crop(bbox), mask.crop(bbox)
    # Leave room for the outline and shadow inside the image area.
    margin = max(2, round(cw * 0.03))
    scale = min((room_w - 2 * margin) / piece.width, (room_h - 2 * margin) / piece.height)
    size = (max(1, round(piece.width * scale)), max(1, round(piece.height * scale)))
    piece = piece.resize(size, Image.Resampling.LANCZOS)
    alpha = alpha.resize(size, Image.Resampling.LANCZOS)
    tile = Image.new("RGBA", (room_w, room_h), (255, 255, 255, 0))
    at = ((room_w - size[0]) // 2, (room_h - size[1]) // 2)
    full = Image.new("L", tile.size, 0)
    full.paste(alpha, at)
    # Soft shadow for every gift; light ones are stronger and get a thin grey outline.
    drop = Image.new("L", tile.size, 0)
    drop.paste(full, (0, max(1, round(cw * 0.02))))
    blur = max(1, round(cw * 0.025))
    strength = 70 if light else 40
    shadow = Image.new("RGBA", tile.size, (60, 64, 72, 255))
    shadow.putalpha(
        drop.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: v * strength // 255)
    )
    tile.alpha_composite(shadow)
    if light:
        width = max(1, round(cw * 0.008)) * 2 + 1
        ring = Image.new("RGBA", tile.size, OUTLINE + (255,))
        ring.putalpha(full.filter(ImageFilter.MaxFilter(width)).point(lambda v: v * 220 // 255))
        tile.alpha_composite(ring)
    body = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    body.paste(piece.convert("RGBA"), at)
    body.putalpha(full)
    tile.alpha_composite(body)
    return tile, light


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
    """The card as a transparent sticker; returns (sticker, top-left offset, what was drawn)."""
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
    gift = _gift(gift_raw)
    room_w, room_h = cw - 2 * box["pad"], box["image_height"]
    white = card.get("background") == "WHITE"
    cut = _cutout(gift, room_w, room_h, cw) if white else None
    info = {"background": "WHITE" if white else "ORIGINAL", "separated": False, "light": False}
    if cut is not None:
        tile, light = cut
        sticker.alpha_composite(tile, (left + box["pad"], top + box["top"]))
        info.update(separated=True, light=light)
    else:
        # The gift photo, fitted whole inside the image area with softly rounded corners.
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
    return sticker, (box["x"] - margin, box["y"] - radius - margin), info


def apply(image, sticker, offset):
    """Places the card on an exported image (RGB or RGBA); returns RGBA."""
    result = image.convert("RGBA")
    layer = Image.new("RGBA", result.size, (0, 0, 0, 0))
    layer.paste(sticker, offset, sticker)
    return Image.alpha_composite(result, layer)
