"""v4 whole-image generation for the gift, scene and selling-point entries (ADR-20260929).

The product image (and the gift image for the gift entry) is sent to the configured model as a
reference; the model returns the whole image. The result is exported locally to the exact size
with a deterministic cover-centre crop, then the verbatim manual text is overlaid by the program.
A re-typeset request reuses a stored model output and never calls the model.

Selling points (ADR-20261008-G): one image per point; image i carries the shared title and point i.
With ``keep_original`` the product image itself, cropped to size, is the base of every image and
no model is called for the picture. A white gift card (``gift_reshoot``, ADR-20261009-N) adds one
call per attempt for the gift alone on white.
"""

import hashlib
import io
import math
import time
import uuid

from PIL import Image, ImageOps

from image_service import giftcard, model_parameters, text_models, typeset
from image_service.background import BackgroundError, BackgroundRequest
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


# Magic wand (ADR-20261008-L): the fixed rules the text model follows, after the agent's own
# settings. The guard below is still appended to whatever it writes.
REWRITE_RULES = (
    "任务：把用户对母婴电商图片的需求改写成一段给 AI 生图模型的中文画面描述，不超过 300 字。"
    "写清场景、构图与商品位置、光线、色调和氛围；只描述画面本身。"
    "提到图片时沿用用户的叫法（如“商品图”“参考图1”“参考图2”“要修改的图”），不要改名或重新编号；"
    "按用户安排每张图的用途（例如以某张参考图为底图、把商品作为赠品加入），不要擅自让商品当主角。"
    "不要要求图中出现任何文字、字母、数字、Logo、水印、价格或标签；"
    "不要改变商品的外形、颜色、Logo、包装文字和数量。"
    "如果用户是在已有图片上修改，只描述要改的地方，并说明其余保持不变。"
    "只输出改写后的描述，不要解释，不要加标题。"
)
DEFAULT_DESIGNER = "你是资深母婴电商视觉设计师，擅长干净、温馨、主体突出的商品图。"

# Look first, then draw (ADR-20261009-P): before the image call a vision-capable text model looks
# at every chat image and writes down what it sees and the plan, as Doubao does in its reply.
# The image model then gets the user's words plus this explicit description.
ANALYSIS_RULES = (
    "任务：先逐张仔细看图，再给 AI 生图模型写一份中文出图说明，不超过 700 字。分两部分写。\n"
    "【看图】逐张说明，用图片名称指代：\n"
    "- 将作为底图的图片：列出所有人物、商品、文字、标志、角标、图标及其大致位置，"
    "并指出画面里哪里是空白区域、约占多大；\n"
    "- 只作为“展示方式”或风格参考的图片：写清要照学的展示形式细节——边框或卡片的形状、颜色、"
    "是否透明、圆角，上面每个圆标、图标、符号（如圆圈里的“+”）的颜色、形状和位置，"
    "以及它在画面中的大致大小和位置；与展示方式无关的内容不用写；\n"
    "- 商品图：商品的外形、颜色、材质、Logo、包装文字和数量。\n"
    "【出图方案】以哪张图为底，加入什么，放在哪个空白位置、约占画面多大，用什么展示形式，"
    "哪些内容必须原样保留。\n"
    "规则：提到图片时沿用用户的叫法（如“商品图”“参考图1”“参考图2”“要修改的图”），"
    "不要改名或重新编号；按用户安排每张图的用途，不要擅自让商品当主角；"
    "不要添加用户和参考图都没有的元素或装饰（如彩带、蝴蝶结、闪光）；"
    "不要要求在图中写新的文字、字母或数字（参考图卡片上的文字说明不画，照搬的简单符号如“+”可以）；"
    "不要改变商品的外形、颜色、Logo、包装文字和数量；"
    "如果是在已有图片上修改，只写要改的地方，并说明其余保持不变。"
    "只输出这份说明，不要客套，不要用 Markdown 标题。"
)
ANALYST = "你是严谨的电商图片分析师，也是资深母婴电商视觉设计师。"
ANALYSIS_ONLY = "只忠实分析和规划，不加入用户没要求的创意。"
ANALYSIS_WAND = "在出图方案里按你的设定把画面写得更专业、更有质感，但不违背用户原话和以上规则。"
ANALYSIS_SIDE = 1024  # the text model sees smaller copies; the image model gets the usual ones


def _image_names(request):
    """What the chat page calls each input image, in the order they are sent (ADR-20261009-M).
    The user writes these names; numbering the inputs differently made "参考图1" read as the
    first input, i.e. the product (tasks c47dffee, 9a21795f, bc71d56b)."""
    names = ["要修改的图"] if "edit_image" in request else []
    names.append("商品图")
    names += [f"参考图{index + 1}" for index in range(len(request.get("references", [])))]
    return names


def _rewrite_messages(request):
    agent = request.get("agent")
    persona = f"你是{agent['name']}。{agent['instructions']}" if agent else DEFAULT_DESIGNER
    situation = "这是在已生成的图片上修改" if "edit_image" in request else "这是生成新图"
    names = "、".join(f"“{name}”" for name in _image_names(request))
    user = f"需求：{request['prompt']}\n（{situation}；提供的图片：{names}。）"
    return persona + "\n\n" + REWRITE_RULES, user


def _analysis_messages(request):
    agent = request.get("agent")
    if request.get("rewrite"):
        persona = f"你是{agent['name']}。{agent['instructions']}" if agent else DEFAULT_DESIGNER
        rules = ANALYSIS_RULES + ANALYSIS_WAND
    else:
        persona, rules = ANALYST, ANALYSIS_RULES + ANALYSIS_ONLY
    situation = "这是在已生成的图片上修改" if "edit_image" in request else "这是生成新图"
    names = "、".join(f"“{name}”" for name in _image_names(request))
    user = f"需求：{request['prompt']}\n（{situation}；下面依次是图片：{names}。）"
    return persona + "\n\n" + rules, user


def _analysis_copy(reference):
    """A smaller upright RGB JPEG of an input for the text model to look at."""
    with Image.open(io.BytesIO(reference)) as image:
        image.load()
        rgba = image.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    flat.thumbnail((ANALYSIS_SIDE, ANALYSIS_SIDE), Image.Resampling.LANCZOS)
    return encode(flat, "jpeg")


def _custom_prompt(request, brief=None, analysis=None):
    """Conversational generation (ADR-20261008-I): the user's words, plus the guard every entry
    keeps (business rule 1): the product stays exactly as photographed and no text is drawn.
    With an agent its settings guide the picture; after a rewrite the brief replaces the words.
    The inputs are introduced by the names the page shows, so the user's words map onto them;
    what each image is for (base picture, added item, style example) is the user's choice."""
    names = _image_names(request)
    order = []
    for number, name in enumerate(names, 1):
        role = {
            "要修改的图": " (the current picture to modify; the user may call it 这张图 or 当前图)",
            "商品图": " (the product)",
        }.get(name, "")
        order.append(f"input image {number} = 「{name}」{role}")
    parts = [
        "The input images, in order: " + "; ".join(order) + ". The user's words (Chinese) "
        "refer to the images by exactly these names"
        + (
            f", so 「参考图1」 means input image {names.index('参考图1') + 1}, not input image 1."
            if "参考图1" in names
            else "."
        )
    ]
    parts.append(
        "The user decides what each image is for: a 参考图 may be the base picture to build on, "
        "an item to add, or only an example of style or layout, and the product may be the main "
        "subject or an added item such as a gift. Follow the user's words instead of assuming "
        "that the product is always the main subject."
    )
    # Task c0b4d7de (2026-10-09): with the roles right, the model still cleared the base
    # picture's logo, title and badges to make room for the gift card. Same wording as the gift
    # entry's "keep original" prompt (ADR-20261008-H), plus where additions go (ADR-20261009-O).
    parts.append(
        "When the words build on one picture (for example 在参考图1的基础上), that picture is the "
        "base: keep everything in it exactly as it is and where it is - every person, item, "
        "text, logo, badge, icon and graphic, the layout, colours, lighting and background. Do "
        "not remove, move, resize, cover, recentre, crop or redraw anything in it. Put anything "
        "added only into empty background space of the base picture (pick the emptiest area, "
        "such as an empty bottom corner) and make it small enough to fit there without covering "
        "any person, product, text, logo or badge."
    )
    # Task 9c5a50ca (2026-10-09): "copy only that way of showing it" was too vague - the card
    # came out translucent, with a ribbon bow and without the example's green plus badge.
    parts.append(
        "When a picture is only an example of how something should be shown (for example "
        "展示方式可以参考参考图2), find that presentation in it and reproduce it faithfully: the "
        "same frame or card, its shape, colour and opacity, and every badge, icon or symbol on "
        "it (such as a plus sign in a circle) in the same position, with the user's item inside "
        "instead of the example's. Do not copy that picture's people, products, words or "
        "background, and do not add decorations the example does not have (no ribbons, bows, "
        "gift wrap, tags, stickers or sparkles) unless the user asks for them."
    )
    if "edit_image" in request:
        parts.append(
            "Change only what the user asks for in 「要修改的图」 and keep everything else in it "
            "as it is."
        )
    agent = request.get("agent")
    if brief is not None:
        writer = agent["name"] if agent else "the designer"
        source = (
            "after looking at every input image"
            if request.get("analyze")
            else "from the user's request"
        )
        parts.append(f"Brief written by {writer} {source} (same image names): {brief}")
    else:
        if agent:
            parts.append(
                f"Design direction from the chosen designer {agent['name']} (where it conflicts "
                f"with the user's words, follow the user): {agent['instructions']}"
            )
        parts.append(f"Instruction from the user: {request['prompt']}")
        if analysis is not None:
            # ADR-20261009-P: what a vision model saw in the images, and its plan.
            parts.append(
                "Image analysis and plan, written after looking at every input image (same "
                "image names; follow its details, and where it conflicts with the user's words "
                f"follow the user): {analysis}"
            )
    parts.append(
        "Wherever the product from 「商品图」 appears, keep it exactly as photographed: the same "
        "shape, proportions, colours, materials, logo, printed text, markings and number of "
        "items. Items taken from a 参考图 keep their look as well."
    )
    parts.append(
        "Do not write any new words, letters or numbers and add no watermarks; simple symbols "
        "copied from an example, such as a plus sign in a badge, are allowed, and an added gift "
        "card or label stays without a caption. This never means removing anything that is "
        "already in the base picture: its text, logos, badges and icons stay exactly as they "
        "are."
    )
    return " ".join(parts)


def build_prompt(request, ordinal, brief=None, analysis=None):
    feature = request["feature_type"]
    if feature == "CUSTOM":
        return _custom_prompt(request, brief, analysis)
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


# ADR-20261009-N: the white gift card shows the gift re-photographed alone on white by the model
# instead of a program cut-out (dark outlines, leftover backdrop strips on non-white photos).
GIFT_WHITE = (
    "Reference image 1 shows a free gift item, possibly on a coloured or busy background and "
    "possibly with words or other objects around it. Show exactly this item alone as a clean "
    "e-commerce product photo on a pure white (#FFFFFF) seamless background. Keep the item "
    "exactly as it is: the same shape, proportions, colours, materials, logo, printed text, "
    "markings and number of pieces; do not redesign, relabel, crop or duplicate it. Remove "
    "everything that is not part of the item: the original background, words printed on the "
    "background, props, hands and other products. Centre it in the same view as the reference, "
    "filling about 80% of the frame. Soft even studio light with a light, natural shadow under "
    "the item, so that a white or cream item still stands out from the white background. Do not "
    "add any text, letters, numbers, watermarks, stickers, badges, frames or borders."
)
# Fields of the gift call's provenance kept in the receipt (no secrets are ever in it).
RESHOOT_FIELDS = (
    "provider",
    "provider_tag",
    "model",
    "endpoint",
    "prompt",
    "template_version",
    "parameters",
    "correlation_id",
    "output_source",
    "sha256",
    "duration_ms",
    "usage",
)


def _reshoot_gift(api, request, lease, adapter, gift_raw, image_config=None):
    """One paid call per attempt: the gift alone on white. Its permit is ordinal ``count``, after
    the images' own ordinals 0..count-1. Returns (picture, provenance)."""
    attempt, count = request["attempt_id"], request["output"]["count"]
    api.call("POST", f"/internal/v1/work/{attempt}/heartbeat", lease=lease)
    api.call("POST", f"/internal/v1/work/{attempt}/generation-calls/{count}", lease=lease)
    generated = adapter.generate(
        BackgroundRequest(
            prompt=GIFT_WHITE,
            template_version="generation-v4-gift-white",
            correlation_id=f"{attempt}-gift",
            aspect_ratio="1:1",
            resolution=None,
            output_format=None,
            references=(_reference(gift_raw),),
            parameters=model_parameters.for_call(image_config, request, gift=True),
        )
    )
    with Image.open(io.BytesIO(generated.content)) as image:
        budget(image.size)
        picture = image.convert("RGB")
    provenance = {k: v for k, v in generated.provenance.items() if k in RESHOOT_FIELDS}
    provenance["sha256"] = hashlib.sha256(generated.content).hexdigest()
    return picture, provenance


def _palette(request, ordinal):
    text = request["text"]
    if request.get("styles"):
        style = _style(request, ordinal)
        return {key: style[key] for key in ("badge_color", "badge_text_color", "accent_color")}
    return {**DEFAULT_PALETTE, "badge_text_color": text["color"], "accent_color": text["color"]}


def process_generation(
    api, request, lease, adapter, *, cancelled=None, text_config=None, image_config=None
):
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
            # The program draws the card (ADR-20261008-H). Inside it is the gift photo, or on
            # the white background the model's re-shot of the gift alone (ADR-20261009-N).
            box = giftcard.geometry(card, width, height, request["gift_position"])
            gift_raw = _raw(api, request, lease, "gift_asset")
            giftcard.check_label(card, box, font)
            white = None
            if request.get("gift_reshoot") and not retypeset:
                if cancelled is not None and cancelled():
                    raise ValueError("generation lease or time budget exhausted")
                white = _reshoot_gift(api, request, lease, adapter, gift_raw, image_config)
            sticker, offset, card_info = giftcard.render(gift_raw, card, box, font, white)
        elif not retypeset and not original:
            references.append(_reference(_raw(api, request, lease, "gift_asset")))
    brief, agent_info, analysis, analysis_info = None, None, None, None
    if request.get("agent") or request.get("rewrite"):
        agent = request.get("agent") or {}
        agent_info = {"name": agent.get("name", "默认设计师")}
        if agent.get("id"):
            agent_info["id"] = agent["id"]
    look = bool(request.get("analyze")) and not retypeset and not original
    if (request.get("rewrite") or look) and not retypeset and not original:
        # One text-model call per attempt, before any paid image call (ADR-20261008-L). With
        # "analyze" it looks at the images first (ADR-20261009-P); its failures say so.
        prefix = "VISION_" if look else "TEXT_"
        if text_config is None:
            raise BackgroundError(prefix + "CONFIGURATION")
        api.call("POST", f"/internal/v1/work/{request['attempt_id']}/heartbeat", lease=lease)
        if look:
            system, user = _analysis_messages(request)
            images = tuple(zip(_image_names(request), map(_analysis_copy, references), strict=True))
        else:
            (system, user), images = _rewrite_messages(request), ()
        try:
            written, _usage = text_models.rewrite(
                text_config, system, user, images=images, max_tokens=1500 if look else 800
            )
        except BackgroundError as error:
            # Tell the page it was the text step, not the picture, that failed.
            raise BackgroundError(prefix + error.code, retryable=error.retryable) from None
        if request.get("rewrite"):
            brief = written
            agent_info.update(rewritten=written, text_model=text_config.model)
        else:
            analysis = written
        if look:
            analysis_info = {"text": written, "text_model": text_config.model}
    # The model's parameters plus this task's clarity (ADR-20261009-Q), checked before any call.
    parameters = () if retypeset or original else model_parameters.for_call(image_config, request)
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
                    prompt=build_prompt(request, ordinal, brief, analysis),
                    template_version="generation-v4-" + request["feature_type"].lower(),
                    correlation_id=f"{attempt}-{ordinal}",
                    aspect_ratio=output["aspect_ratio"],
                    resolution=None,
                    output_format=None,
                    references=tuple(references),
                    parameters=parameters,
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
        if card:
            provenance["gift_card"] = card_info
        if agent_info is not None and not retypeset:
            provenance["agent"] = agent_info
        if analysis_info is not None:
            provenance["analysis"] = analysis_info
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
