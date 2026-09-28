"""Offline deterministic image research; never marks business assets approved."""

import math

from PIL import Image, ImageChops, ImageDraw

# Offline experiment resource limits, not platform or business image rules.
MAX_SIDE = 4096
MAX_PIXELS = 4_194_304


def budget(size):
    width, height = size
    if min(width, height) < 1 or max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
        raise ValueError("image resource budget exceeded")


def segment_white(image: Image.Image, tolerance: int = 12) -> Image.Image:
    """Experimental border-connected near-white removal, not a production segmenter."""
    budget(image.size)
    if image.mode != "RGB" or type(tolerance) is not int or not 0 <= tolerance <= 32:
        raise ValueError("expected RGB and integer tolerance in 0..32")
    red, green, blue = image.split()
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    candidate = minimum.point(lambda value: 255 if value >= 255 - tolerance else 0)
    width, height = image.size
    borders = [(x, y) for x in range(width) for y in (0, height - 1)]
    borders.extend((x, y) for y in range(height) for x in (0, width - 1))
    for point in borders:
        if candidate.getpixel(point) == 255:
            ImageDraw.floodfill(candidate, point, 128)
    alpha = candidate.point(lambda value: 0 if value == 128 else 255)
    if alpha.getbbox() is None:
        raise ValueError("no foreground; manual review required")
    return alpha


def extract_subject(original: Image.Image, candidate: Image.Image) -> Image.Image:
    """Candidate RGB is discarded; source transparency can never be resurrected."""
    budget(original.size)
    if original.mode not in ("RGB", "RGBA") or candidate.mode not in ("L", "RGBA"):
        raise ValueError("expected RGB/RGBA original and L/RGBA alpha candidate")
    if original.size != candidate.size:
        raise ValueError("alpha dimensions must match original")
    alpha = candidate.getchannel("A") if candidate.mode == "RGBA" else candidate
    result = original.convert("RGBA")
    result.putalpha(ImageChops.multiply(result.getchannel("A"), alpha))
    if result.getchannel("A").getbbox() is None:
        raise ValueError("no foreground; manual review required")
    return result


def transform(subject: Image.Image, *, scale=1.0, angle=0.0, crop=None) -> Image.Image:
    budget(subject.size)
    if subject.mode != "RGBA":
        raise ValueError("expected RGBA subject")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (scale, angle)):
        raise ValueError("finite numeric transform required")
    if scale <= 0 or not -360 <= angle <= 360:
        raise ValueError("invalid scale or angle")
    crop = (0, 0, *subject.size) if crop is None else crop
    if (
        not isinstance(crop, (tuple, list))
        or len(crop) != 4
        or any(type(v) is not int for v in crop)
    ):
        raise ValueError("integer crop coordinates required")
    left, top, right, bottom = crop
    if not (0 <= left < right <= subject.width and 0 <= top < bottom <= subject.height):
        raise ValueError("crop must be inside original coordinates")
    dimensions = ((right - left) * scale, (bottom - top) * scale)
    budget(dimensions)  # Reject before large allocations or integer conversion.
    size = tuple(math.floor(value + 0.5) for value in dimensions)
    budget(size)
    radians = math.radians(angle)
    if angle % 90:
        budget(
            (
                math.ceil(abs(size[0] * math.cos(radians)) + abs(size[1] * math.sin(radians))) + 2,
                math.ceil(abs(size[0] * math.sin(radians)) + abs(size[1] * math.cos(radians))) + 2,
            )
        )
    result = subject.crop(crop).resize(size, Image.Resampling.LANCZOS)
    result = result.rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))
    budget(result.size)
    return result


def compose(background: Image.Image, layers) -> Image.Image:
    budget(background.size)
    if background.mode not in ("RGB", "RGBA") or not 1 <= len(layers) <= 16:
        raise ValueError("expected RGB/RGBA background and 1..16 layers")
    result = background.convert("RGBA")
    for layer, position in layers:
        budget(layer.size)
        if layer.mode != "RGBA" or len(position) != 2 or any(type(v) is not int for v in position):
            raise ValueError("expected RGBA layer and integer position")
        x, y = position
        left, top = max(0, -x), max(0, -y)
        right, bottom = min(layer.width, result.width - x), min(layer.height, result.height - y)
        if left >= right or top >= bottom:
            raise ValueError("layer outside canvas")
        # Do not paste with alpha as a mask: that would multiply alpha a second time.
        result.alpha_composite(layer.crop((left, top, right, bottom)), (max(0, x), max(0, y)))
    return result
