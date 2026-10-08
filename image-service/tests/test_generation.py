"""v4 whole-image generation: references, prompts, export, text overlay and re-typeset."""

import hashlib
import io
import json

import pytest
from PIL import Image, ImageDraw, ImageFont

from image_service import typeset
from image_service.background import BackgroundError, BackgroundResult
from image_service.contracts import validate_contract
from image_service.generation import (
    _original,
    _reference,
    build_prompt,
    fit_background,
    process_generation,
)
from image_service.worker import process

PRODUCT, GIFT = (190, 70, 80), (60, 110, 200)


def png(color, size=(96, 80)):
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle((30, 20, 66, 70), fill=color)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class LocalApi:
    def __init__(self, inputs):
        self.inputs = inputs
        self.outputs = {}
        self.posts = []

    def call(self, method, path, **kwargs):
        if method == "GET":
            return self.inputs[path.split("/")[-1]]
        if method == "POST":
            self.posts.append(path.split("/work/attempt/")[-1])
            return None
        data = kwargs["data"]
        index = int(path.split("/")[-1])
        self.outputs[index] = data
        with Image.open(io.BytesIO(data)) as image:
            size = image.size
        return {
            "object_key": f"outputs/task/attempt/lease/{index}.image",
            "sha256": hashlib.sha256(data).hexdigest(),
            "width": size[0],
            "height": size[1],
        }


class Adapter:
    """Fake model: paints the first reference onto a coloured canvas, one colour per call."""

    def __init__(self, size=(1024, 768), repeat=False):
        self.requests = []
        self.size = size
        self.repeat = repeat

    def generate(self, request):
        self.requests.append(request)
        shade = 0 if self.repeat else len(self.requests) * 20
        canvas = Image.new("RGB", self.size, (230 - shade, 225, 215))
        with Image.open(io.BytesIO(request.references[0])) as reference:
            canvas.paste(reference.convert("RGB").resize((400, 330)), (500, 300))
        stream = io.BytesIO()
        canvas.save(stream, format="PNG")
        content = stream.getvalue()
        return BackgroundResult(
            content,
            *self.size,
            {
                "schema_version": 1,
                "provider": "openrouter",
                "model": "test/model",
                "provider_tag": "test",
                "prompt": request.prompt,
                "template_version": request.template_version,
                "parameters": {
                    "aspect_ratio": request.aspect_ratio,
                    "input_references": len(request.references),
                },
                "correlation_id": request.correlation_id,
                "output_source": "openrouter-images-api",
                "sha256": hashlib.sha256(content).hexdigest(),
                "review_status": "PENDING",
                "duration_ms": 1,
                "usage": {},
            },
        )


STYLES = [
    {
        "id": sid,
        "name": sid,
        "prompt": f"{sid} mood",
        "title_color": "#223344",
        "badge_color": "#F6E9DA",
        "badge_text_color": "#4A2E1F",
        "accent_color": "#C8814E",
    }
    for sid in ("warm", "green")
]
TEXT = {
    "title": "轻松喂养\nEasy feeding",
    "points": ["Safe", "Anti-colic"],
    "color": "#112233",
    "size": 60,
    "align": "left",
    "box": {"x": 0.04, "y": 0.04, "width": 0.5, "height": 0.6},
}


def request(api, feature="SCENE", count=1, **extra):
    value = {
        "schema_version": 4,
        "event_type": "image.task.requested.v4",
        "event_id": "event",
        "task_id": "task",
        "attempt_id": "attempt",
        "correlation_id": "task",
        "output_object_prefix": "outputs/task/attempt/",
        "feature_type": feature,
        "product_asset": {
            "asset_id": "product",
            "object_key": "originals/p/product.image",
            "sha256": hashlib.sha256(api.inputs["product"]).hexdigest(),
        },
        "presets_version": "presets-v1",
        "output": {
            "aspect_ratio": "1:1",
            "width": 400,
            "height": 400,
            "format": "png",
            "count": count,
        },
    }
    value["template_snapshot"] = {
        "versions": [],
        "output_preset": {"id": "generation_v4", "config": value["output"]},
    }
    if feature == "GIFT":
        value["gift_asset"] = {
            "asset_id": "gift",
            "object_key": "originals/p/gift.image",
            "sha256": hashlib.sha256(api.inputs["gift"]).hexdigest(),
        }
        value["gift_position"] = "BOTTOM_RIGHT"
    elif feature == "SCENE":
        value["scene"] = {"id": "nursery", "name": "婴儿房", "prompt": "a bright nursery"}
    else:
        value["styles"] = STYLES[:count]
        value["text"] = TEXT
    value.update(extra)
    assert not validate_contract("generation-v4-request", value)
    return value


@pytest.fixture()
def font(monkeypatch):
    monkeypatch.setenv("GENERATION_TEXT_FONT", "test-scalable-font")
    monkeypatch.setattr(typeset, "_font", lambda _path, size: ImageFont.load_default(size))


def api():
    return LocalApi({"product": png(PRODUCT), "gift": png(GIFT)})


def test_scene_sends_product_reference_and_exports_exact_size():
    local, adapter = api(), Adapter()
    receipt = process_generation(local, request(local), "lease", adapter)
    assert not validate_contract("generation-v4-completed", receipt)
    sent = adapter.requests[0]
    assert sent.references == (local.inputs["product"],)
    assert sent.aspect_ratio == "1:1" and sent.resolution is None
    assert "a bright nursery" in sent.prompt and "exact product" in sent.prompt
    assert local.posts == ["heartbeat", "generation-calls/0"]
    with Image.open(io.BytesIO(local.outputs[0])) as final:
        assert final.size == (400, 400) and final.format == "PNG"
    generation = receipt["generations"][0]
    assert generation["base"]["kind"] == "BACKGROUND" and generation["base"]["ordinal"] == 1
    assert generation["provenance"]["transform"]["source_size"] == [1024, 768]
    assert generation["provenance"]["inputs"] == {
        "product_sha256": request(local)["product_asset"]["sha256"]
    }
    assert generation["provenance"]["text_rendered"] is False


def test_gift_sends_both_references_and_position():
    local, adapter = api(), Adapter()
    receipt = process_generation(local, request(local, "GIFT"), "lease", adapter)
    sent = adapter.requests[0]
    assert sent.references == (local.inputs["product"], local.inputs["gift"])
    assert "Reference image 2 is the free gift" in sent.prompt and "bottom-right" in sent.prompt
    assert "gift_sha256" in receipt["generations"][0]["provenance"]["inputs"]


def test_selling_points_one_style_per_image_with_verbatim_text(font):
    local, adapter = api(), Adapter()
    receipt = process_generation(local, request(local, "SELLING_POINT", count=2), "lease", adapter)
    assert not validate_contract("generation-v4-completed", receipt)
    assert [r.prompt.count("warm mood") for r in adapter.requests] == [1, 0]
    assert [r.prompt.count("green mood") for r in adapter.requests] == [0, 1]
    assert "top-left area" in adapter.requests[0].prompt
    assert local.posts.count("heartbeat") == 2
    for ordinal in (0, 1):
        with Image.open(io.BytesIO(local.outputs[ordinal])) as final:
            colours = {
                c for _, c in final.convert("RGB").crop((16, 16, 216, 256)).getcolors(1 << 16)
            }
        assert (0x11, 0x22, 0x33) in colours  # title drawn in the requested colour
        # Style badge colour (drawn slightly translucent) behind the points.
        assert any(
            max(abs(a - b) for a, b in zip(c, (0xF6, 0xE9, 0xDA), strict=True)) <= 12
            for c in colours
        )
    assert all(g["provenance"]["text_rendered"] for g in receipt["generations"])


def capture_text(monkeypatch):
    drawn = []
    render = typeset.render

    def spy(image, text, palette, font):
        drawn.append((text, palette))
        return render(image, text, palette, font)

    monkeypatch.setattr(typeset, "render", spy)
    return drawn


def test_selling_points_one_image_per_point_in_one_style(font, monkeypatch):
    """ADR-20261008-G: image i shows the shared title and point i; every prompt uses the one
    chosen style and asks the model to express that point without writing it."""
    drawn = capture_text(monkeypatch)
    local, adapter = api(), Adapter()
    value = request(local, "SELLING_POINT", count=2, styles=STYLES[:1], per_point=True)
    receipt = process_generation(local, value, "lease", adapter)
    assert not validate_contract("generation-v4-completed", receipt)
    assert [r.prompt.count("warm mood") for r in adapter.requests] == [1, 1]
    assert "selling point" in adapter.requests[0].prompt
    assert "Safe." in adapter.requests[0].prompt and "Anti-colic" not in adapter.requests[0].prompt
    assert "Anti-colic." in adapter.requests[1].prompt and "Safe." not in adapter.requests[1].prompt
    assert all("Do not add any text" in r.prompt for r in adapter.requests)
    assert [text["points"] for text, _ in drawn] == [["Safe"], ["Anti-colic"]]
    assert {text["title"] for text, _ in drawn} == {TEXT["title"]}
    assert [palette["badge_color"] for _, palette in drawn] == ["#F6E9DA", "#F6E9DA"]
    assert local.posts.count("generation-calls/0") == local.posts.count("generation-calls/1") == 1


def keep_original_request(local, **extra):
    value = request(local, "SELLING_POINT", count=2, per_point=True, keep_original=True, **extra)
    value.pop("styles")
    assert not validate_contract("generation-v4-request", value)
    return value


def test_keep_original_puts_text_on_the_cropped_product_image_without_a_model(font, monkeypatch):
    drawn = capture_text(monkeypatch)
    local = api()
    receipt = process_generation(local, keep_original_request(local), "lease", None)
    assert not validate_contract("generation-v4-completed", receipt)
    assert local.posts == []  # no heartbeat, no paid-call permit
    bases = [g["base"]["sha256"] for g in receipt["generations"]]
    assert bases[0] == bases[1]  # one cropped original for every image
    assert local.outputs[2] == local.outputs[3]
    assert local.outputs[0] != local.outputs[1]  # different points
    for generation in receipt["generations"]:
        provenance = generation["provenance"]
        assert provenance["output_source"] == "original"
        assert provenance["source_transform"]["source_size"] == [96, 80]
        assert provenance["source_transform"]["target_size"] == [400, 400]
        assert provenance["transform"]["crop"] == [0, 0, 400, 400]  # base is already exact
        assert "model" not in provenance and "prompt" not in provenance
    with Image.open(io.BytesIO(local.outputs[2])) as base:
        assert base.size == (400, 400)
        # The product rectangle of the original survives unchanged in colour.
        assert base.convert("RGB").getpixel((200, 250)) == PRODUCT
    assert [text["points"] for text, _ in drawn] == [["Safe"], ["Anti-colic"]]
    # No style: the text colour comes from the request, the badges are white.
    assert drawn[0][1] == {
        "badge_color": "#FFFFFF",
        "badge_text_color": TEXT["color"],
        "accent_color": TEXT["color"],
    }


def test_keep_original_skips_the_provider_entirely(font, monkeypatch):
    from image_service import providers

    def forbidden(*_args, **_kwargs):
        raise AssertionError("keep-original must never build a model client")

    monkeypatch.setattr(providers, "model_adapter", forbidden)
    local = api()
    receipt = process(local, keep_original_request(local), "lease", False, provider_config=None)
    assert receipt["event_type"] == "image.task.completed.v4", receipt


def test_keep_original_base_is_upright_and_transparency_becomes_white():
    image = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((80, 20, 120, 80), fill=PRODUCT + (255,))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    data, transform = _original(stream.getvalue(), 100, 100)
    with Image.open(io.BytesIO(data)) as base:
        assert base.mode == "RGB" and base.size == (100, 100)
        assert base.getpixel((2, 2)) == (255, 255, 255)
        assert base.getpixel((50, 50)) == PRODUCT
    assert transform["source_size"] == [200, 100] and transform["crop"] == [50, 0, 150, 100]
    photo = Image.new("RGB", (120, 60), "white")
    ImageDraw.Draw(photo).rectangle((0, 0, 20, 60), fill=PRODUCT)
    exif = Image.Exif()
    exif[0x0112] = 6
    data, transform = _original(jpeg(photo, exif=exif.tobytes()), 60, 120)
    assert transform["source_size"] == [60, 120]


def test_identical_model_outputs_are_rejected():
    local = api()
    with pytest.raises(ValueError, match="duplicate"):
        process_generation(local, request(local, count=2), "lease", Adapter(repeat=True))


def test_text_without_font_fails_before_any_paid_call(monkeypatch):
    monkeypatch.delenv("GENERATION_TEXT_FONT", raising=False)
    local, adapter = api(), Adapter()
    with pytest.raises(typeset.FontUnavailable):
        process_generation(local, request(local, "SELLING_POINT"), "lease", adapter)
    assert adapter.requests == [] and local.posts == []


def test_overflowing_text_fails_without_truncation(font):
    local = api()
    long_text = dict(
        TEXT,
        points=["Very long point ok"] * 6,
        box={"x": 0.4, "y": 0.0, "width": 0.1, "height": 0.05},
    )
    with pytest.raises(typeset.TextOverflow):
        process_generation(
            local, request(local, "SELLING_POINT", text=long_text), "lease", Adapter()
        )
    assert 0 not in local.outputs


def test_retypeset_reuses_stored_output_without_model(font):
    local, adapter = api(), Adapter()
    first = process_generation(local, request(local, "SELLING_POINT"), "lease", adapter)
    base = local.outputs[1]
    local.inputs["base"] = base
    again = request(
        local,
        "SELLING_POINT",
        text=dict(TEXT, title="新标题", align="right"),
        base_image={
            "asset_id": "base",
            "object_key": "outputs/task/attempt/lease/1.image",
            "sha256": hashlib.sha256(base).hexdigest(),
        },
        source={"task_id": "earlier", "ordinal": 0},
    )
    local.outputs.clear()
    local.posts.clear()
    receipt = process_generation(local, again, "lease", None)
    assert not validate_contract("generation-v4-completed", receipt)
    provenance = receipt["generations"][0]["provenance"]
    assert provenance["output_source"] == "retypeset"
    assert provenance["inputs"]["base_sha256"] == hashlib.sha256(base).hexdigest()
    assert local.outputs[1] == base and local.posts == []
    assert local.outputs[0] != first  # new text, same model output


def test_prompt_never_asks_the_model_for_text():
    local = api()
    for feature in ("GIFT", "SCENE"):
        prompt = build_prompt(request(local, feature), 0)
        assert "Do not add any text" in prompt and "keep its shape" in prompt


def test_worker_maps_v4_errors(monkeypatch, font):
    import image_service.openrouter as openrouter

    class Failing(Adapter):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(openrouter, "OpenRouterAdapter", lambda config: Failing())
    local = api()
    long_text = dict(TEXT, box={"x": 0.4, "y": 0.0, "width": 0.05, "height": 0.03})
    receipt = process(
        local,
        request(local, "SELLING_POINT", text=long_text),
        "lease",
        False,
        provider_config={"api_key": "k" * 20, "model": "vendor/model", "provider_tag": "openai"},
    )
    assert receipt["error"]["code"] == "TEXT_OVERFLOW" and receipt["error"]["retryable"] is False
    assert not validate_contract("generation-v4-failed", receipt)
    monkeypatch.delenv("GENERATION_TEXT_FONT")
    receipt = process(
        local,
        request(local, "SELLING_POINT"),
        "lease",
        False,
        provider_config={"api_key": "k" * 20, "model": "vendor/model", "provider_tag": "openai"},
    )
    assert receipt["error"] == {
        "code": "GENERATION_FAILED",
        "safe_message": "TEXT_FONT_UNAVAILABLE",
        "retryable": True,
    }
    fixture = process(local, request(local), "lease", True)
    assert fixture["error"]["code"] == "INVALID_CONTRACT"


def test_reference_image_bytes_must_be_images():
    from image_service.background import BackgroundRequest

    with pytest.raises(BackgroundError):
        BackgroundRequest(
            prompt="x",
            template_version="t",
            correlation_id="c",
            aspect_ratio="1:1",
            resolution=None,
            output_format=None,
            references=(b"not an image",),
        )


@pytest.mark.parametrize(
    ("box", "zone"),
    [
        (
            {"x": 0.05, "y": 0.05, "width": 0.46, "height": 0.5},
            "right part of the image, to the right of the first 51%",
        ),
        (
            {"x": 0.55, "y": 0.05, "width": 0.4, "height": 0.5},
            "left part of the image, within the first 55%",
        ),
        (
            {"x": 0.1, "y": 0.02, "width": 0.8, "height": 0.2},
            "lower part of the image, below the top 22%",
        ),
        (
            {"x": 0.1, "y": 0.8, "width": 0.8, "height": 0.15},
            "upper part of the image, above the bottom 20%",
        ),
    ],
)
def test_text_features_name_where_the_products_go(box, zone):
    local = api()
    prompt = build_prompt(request(local, "GIFT", text=dict(TEXT, box=box)), 0)
    assert zone in prompt and "nothing overlaps the text area" in prompt


def test_cover_records_geometry():
    image, record = fit_background(Image.new("RGB", (120, 80)), 80, 80)
    assert image.size == (80, 80)
    assert record == {
        "strategy": "cover-center-v1",
        "source_size": [120, 80],
        "resized_size": [120, 80],
        "crop": [20, 0, 100, 80],
        "target_size": [80, 80],
    }


def test_lost_lease_stops_before_billable_call():
    local, adapter = api(), Adapter()
    with pytest.raises(ValueError):
        process_generation(local, request(local), "lease", adapter, cancelled=lambda: True)
    assert adapter.requests == [] and local.posts == [] and local.outputs == {}


def test_bad_source_hash_fails_before_provider():
    local, adapter = api(), Adapter()
    value = request(local, "GIFT")
    value["gift_asset"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        process_generation(local, value, "lease", adapter)
    assert adapter.requests == [] and local.posts == []


def test_unusable_font_setup_fails_before_any_paid_call(monkeypatch):
    local, adapter = api(), Adapter()
    monkeypatch.setenv("GENERATION_TEXT_FONT", "/missing/font.ttc")
    with pytest.raises(typeset.FontUnavailable):
        process_generation(local, request(local, "SELLING_POINT"), "lease", adapter)
    monkeypatch.setenv("GENERATION_TEXT_FONT_INDEX", "x")
    with pytest.raises(typeset.FontUnavailable):
        typeset.font_path()
    assert adapter.requests == [] and local.posts == []


def test_font_index_selects_a_face_in_a_collection(monkeypatch):
    seen = []
    monkeypatch.setattr(
        typeset.ImageFont, "truetype", lambda path, size, index=0: seen.append(index) or None
    )
    monkeypatch.setenv("GENERATION_TEXT_FONT", "fonts.ttc")
    monkeypatch.setenv("GENERATION_TEXT_FONT_INDEX", "2")
    assert typeset.font_path() == "fonts.ttc" and seen == [2]


def jpeg(image, **options):
    stream = io.BytesIO()
    image.save(stream, format="JPEG", **options)
    return stream.getvalue()


def test_small_plain_originals_are_sent_unchanged():
    raw = png(PRODUCT)
    assert _reference(raw) == raw


def test_phone_photos_are_turned_upright_before_the_model_sees_them():
    # Stored landscape with EXIF orientation 6 (rotate 90° clockwise to view): shown portrait.
    image = Image.new("RGB", (120, 60), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 20, 60), fill=PRODUCT)
    exif = Image.Exif()
    exif[0x0112] = 6
    raw = jpeg(image, exif=exif.tobytes())
    with Image.open(io.BytesIO(_reference(raw))) as sent:
        assert sent.format == "PNG" and sent.size == (60, 120)
        # The red band that was on the left is on top once upright.
        assert sent.convert("RGB").getpixel((30, 5))[0] > 150
        assert not sent.getexif().get(0x0112)


def test_cmyk_and_very_large_originals_become_rgb_reference_copies():
    cmyk = jpeg(Image.new("CMYK", (80, 60), (0, 80, 60, 10)))
    with Image.open(io.BytesIO(_reference(cmyk))) as sent:
        assert sent.mode == "RGB" and sent.size == (80, 60)
    large = jpeg(Image.new("RGB", (6000, 4000), PRODUCT), quality=70)
    with Image.open(io.BytesIO(_reference(large))) as sent:
        assert max(sent.size) == 1536 and sent.size[0] > sent.size[1]


def test_transparent_originals_keep_their_alpha():
    image = Image.new("RGBA", (2000, 1000), (0, 0, 0, 0))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    with Image.open(io.BytesIO(_reference(stream.getvalue()))) as sent:
        assert sent.mode == "RGBA" and sent.size == (1536, 768)


# ADR-20261008-H: gift card, "keep original background" prompt and product position.


def gift_request(local, **extra):
    value = request(local, "GIFT", **extra)
    assert not validate_contract("generation-v4-request", value)
    return value


def test_gift_card_on_the_original_needs_no_model(font):
    local = api()
    value = gift_request(
        local,
        background={"mode": "ORIGINAL"},
        gift_card={"size": "M", "label": "洗头刷"},
        keep_original=True,
    )
    receipt = process_generation(local, value, "lease", None)
    assert not validate_contract("generation-v4-completed", receipt)
    assert local.posts == []  # no heartbeat, no paid-call permit
    provenance = receipt["generations"][0]["provenance"]
    assert provenance["output_source"] == "original"
    assert provenance["inputs"]["gift_sha256"] == value["gift_asset"]["sha256"]
    with Image.open(io.BytesIO(local.outputs[0])) as final:
        rgb = final.convert("RGB")
        assert rgb.getpixel((150, 150)) == PRODUCT  # the original is untouched outside the card
        assert rgb.getpixel((280, 381)) == (255, 255, 255)  # white card (x 272..384)
        assert rgb.getpixel((333, 276)) == (62, 155, 95)  # green badge (off its white "+")
        gift_colours = {c for _, c in rgb.crop((281, 284, 375, 353)).getcolors(1 << 16)}
        assert any(max(abs(a - b) for a, b in zip(c, GIFT, strict=True)) < 30 for c in gift_colours)


def test_gift_card_with_a_model_sends_only_the_product(font):
    local, adapter = api(), Adapter()
    value = gift_request(
        local, background={"mode": "SOLID", "color": "#FFFFFF"}, gift_card={"size": "S"}
    )
    receipt = process_generation(local, value, "lease", adapter)
    assert not validate_contract("generation-v4-completed", receipt)
    sent = adapter.requests[0]
    assert sent.references == (local.inputs["product"],)
    assert "gift card" in sent.prompt and "bottom-right area" in sent.prompt
    assert "Reference image 2" not in sent.prompt
    with Image.open(io.BytesIO(local.outputs[0])) as final:
        # S card: 88 px wide at x 296..384; its badge is green.
        assert final.convert("RGB").getpixel((344, 315)) == (62, 155, 95)


def test_gift_card_label_that_cannot_fit_fails_before_any_paid_call(font):
    local, adapter = api(), Adapter()
    value = gift_request(local, gift_card={"size": "S", "label": "超长超长超长超长超长"})
    value["output"].update(width=64, height=64)
    with pytest.raises(typeset.TextOverflow):
        process_generation(local, value, "lease", adapter)
    assert adapter.requests == [] and local.posts == []


def test_keeping_the_original_background_keeps_every_person_and_item():
    local = api()
    prompt = build_prompt(gift_request(local, background={"mode": "ORIGINAL"}), 0)
    assert "every person" in prompt and "Do not remove, move" in prompt
    assert "white background" not in prompt and "do not add other products" not in prompt
    assert "Reference image 2 is the free gift" in prompt and "bottom-right" in prompt


def test_chosen_product_position_replaces_the_automatic_side():
    local = api()
    auto = build_prompt(request(local, "SELLING_POINT", styles=STYLES[:1]), 0)
    assert "right part of the image" in auto
    left = build_prompt(
        request(local, "SELLING_POINT", styles=STYLES[:1], product_position="LEFT"), 0
    )
    assert "Place the product in the left part of the image" in left
    assert "right part" not in left and "top-left area" in left


# ADR-20261008-I: conversational generation with the user's own words.


def custom_request(local, **extra):
    extra.setdefault("prompt", "把商品放在浅色木桌上，暖色自然光")
    value = request(local, "SCENE", **extra)
    value["feature_type"] = "CUSTOM"
    value.pop("scene")
    assert not validate_contract("generation-v4-request", value)
    return value


def test_custom_prompt_keeps_the_guard_and_sends_the_product(font):
    local, adapter = api(), Adapter()
    receipt = process_generation(local, custom_request(local), "lease", adapter)
    assert not validate_contract("generation-v4-completed", receipt)
    sent = adapter.requests[0]
    assert sent.references == (local.inputs["product"],)
    assert "Instruction from the user: 把商品放在浅色木桌上" in sent.prompt
    assert "keep the product from reference image 1 exactly as it is" in sent.prompt
    assert "Do not add any new text" in sent.prompt
    assert sent.template_version == "generation-v4-custom"


def test_custom_edit_sends_the_picture_first_then_product_and_references(font):
    local, adapter = api(), Adapter()
    local.inputs["earlier"] = png((20, 160, 90), size=(120, 120))
    local.inputs["extra"] = png((240, 200, 40))
    edit = {
        "asset_id": "earlier",
        "object_key": "outputs/t/a/l/0.image",
        "sha256": hashlib.sha256(local.inputs["earlier"]).hexdigest(),
    }
    extra = {
        "asset_id": "extra",
        "object_key": "originals/p/extra.image",
        "sha256": hashlib.sha256(local.inputs["extra"]).hexdigest(),
    }
    value = custom_request(local, edit_image=edit, references=[extra], prompt="背景换成浅蓝色")
    receipt = process_generation(local, value, "lease", adapter)
    assert not validate_contract("generation-v4-completed", receipt)
    sent = adapter.requests[0]
    assert sent.references == (
        local.inputs["earlier"],
        local.inputs["product"],
        local.inputs["extra"],
    )
    assert "Reference image 1 is the current picture to modify" in sent.prompt
    assert "keep the product from reference image 2" in sent.prompt
    assert "Reference image 3 is an extra reference" in sent.prompt
    inputs = receipt["generations"][0]["provenance"]["inputs"]
    assert inputs["edit_sha256"] == edit["sha256"]
    assert inputs["reference_sha256"] == [extra["sha256"]]


# ADR-20261008-J: white card background - the gift is separated from a plain backdrop.


def backdrop_photo(gift=(244, 242, 236), text=True, horizon=True):
    """Beige wall/table backdrop with light falloff, a light rounded gift and printed words."""
    image = Image.new("RGB", (300, 240))
    draw = ImageDraw.Draw(image)
    for y in range(240):
        base = (214, 197, 185) if y < 170 else (234, 216, 206)
        for x in range(300):
            fall = x // 30
            draw.point((x, y), tuple(c - fall for c in base))
    if horizon:
        draw.line((0, 170, 300, 170), fill=(196, 180, 166), width=2)
    draw.rounded_rectangle((70, 70, 230, 190), 40, fill=gift)
    if text:
        for i in range(6):
            draw.rectangle((200 + i * 14, 12, 208 + i * 14, 24), fill=(60, 50, 45))
    return image


def test_separate_finds_a_light_gift_on_a_two_tone_backdrop():
    from image_service import giftcard

    photo = backdrop_photo()
    mask = giftcard.separate(photo)
    assert mask is not None
    assert mask.getpixel((150, 130)) > 200  # the gift
    assert mask.getpixel((20, 120)) < 40 and mask.getpixel((20, 220)) < 40  # wall and table
    assert mask.getpixel((236, 18)) < 40  # printed words are not the gift
    assert mask.getpixel((150, 172)) > 200  # the horizon behind the gift stays gift
    assert mask.getpixel((260, 171)) < 40  # the horizon line elsewhere is backdrop
    assert giftcard._is_light(photo, mask)


def test_separate_gives_up_on_a_busy_backdrop():
    import random

    from image_service import giftcard

    rng = random.Random(7)
    photo = Image.new("RGB", (200, 160))
    for y in range(160):
        for x in range(200):
            photo.putpixel((x, y), tuple(rng.randrange(256) for _ in range(3)))
    assert giftcard.separate(photo) is None


def card_on_original(local, background, **card):
    return gift_request(
        local,
        background={"mode": "ORIGINAL"},
        gift_card={"size": "M", "background": background, **card},
        keep_original=True,
    )


def test_white_card_shows_the_separated_gift_larger(font):
    local = api()
    local.inputs["gift"] = png(GIFT, size=(160, 160))
    receipt = process_generation(local, card_on_original(local, "WHITE"), "lease", None)
    assert not validate_contract("generation-v4-completed", receipt)
    info = receipt["generations"][0]["provenance"]["gift_card"]
    assert info == {"background": "WHITE", "separated": True, "light": False}
    white = Image.open(io.BytesIO(local.outputs[0])).convert("RGB")
    local.outputs.clear()
    receipt = process_generation(local, card_on_original(local, "ORIGINAL"), "lease", None)
    assert receipt["generations"][0]["provenance"]["gift_card"]["separated"] is False
    original = Image.open(io.BytesIO(local.outputs[0])).convert("RGB")

    def gift_pixels(image):
        return sum(
            n
            for n, c in image.crop((272, 271, 384, 384)).getcolors(1 << 16)
            if max(abs(a - b) for a, b in zip(c, GIFT, strict=True)) < 30
        )

    assert gift_pixels(white) > 1.3 * gift_pixels(original)


def test_light_gift_on_white_gets_an_outline(font):
    from image_service import giftcard

    stream = io.BytesIO()
    backdrop_photo(text=False).save(stream, format="PNG")
    card = {"size": "L", "background": "WHITE"}
    box = giftcard.geometry(card, 800, 800, "BOTTOM_RIGHT")
    sticker, _, info = giftcard.render(stream.getvalue(), card, box, None)
    assert info == {"background": "WHITE", "separated": True, "light": True}
    counts = sticker.convert("RGB").getcolors(1 << 18)

    def near(colour, tolerance):
        return sum(
            n
            for n, c in counts
            if max(abs(a - b) for a, b in zip(c, colour, strict=True)) <= tolerance
        )

    # The grey outline colour is drawn; the beige backdrop is gone (only blended edge pixels).
    assert near(giftcard.OUTLINE, 12) > 50
    assert near((214, 197, 185), 6) < 0.005 * sticker.width * sticker.height


def test_a_bold_font_is_drawn_without_the_extra_stroke(monkeypatch):
    """ADR-20261008-K: 方正兰亭圆 中粗 is already bold, so TEXT_FAUX_BOLD=false drops the stroke."""
    assert typeset._stroke(56) == 2
    monkeypatch.setenv("GENERATION_TEXT_FAUX_BOLD", "false")
    assert typeset._stroke(56) == 0
    monkeypatch.setenv("GENERATION_TEXT_FAUX_BOLD", "true")
    assert typeset._stroke(56) == 2


# ADR-20261008-L: agents and the magic-wand rewrite.

AGENT = {"id": "agent-gloria", "name": "Gloria", "instructions": "画面干净，商品是主角"}


def test_agent_settings_guide_the_prompt_without_a_rewrite(font):
    local, adapter = api(), Adapter()
    receipt = process_generation(local, custom_request(local, agent=AGENT), "lease", adapter)
    assert not validate_contract("generation-v4-completed", receipt)
    prompt = adapter.requests[0].prompt
    assert "Design direction from the chosen designer Gloria: 画面干净，商品是主角" in prompt
    assert "Instruction from the user: 把商品放在浅色木桌上" in prompt
    assert "keep the product from reference image 1 exactly" in prompt
    assert receipt["generations"][0]["provenance"]["agent"] == {"name": "Gloria", "id": AGENT["id"]}


def test_magic_wand_rewrites_once_then_every_image_uses_the_brief(font, monkeypatch):
    from image_service import text_models
    from image_service.background_config import ModelConfig

    calls = []

    def fake(config, system, user):
        calls.append((config.model, system, user))
        return "温暖的卧室晨光，商品叠放在床尾，奶油色调", {"total_tokens": 120}

    monkeypatch.setattr(text_models, "rewrite", fake)
    local, adapter = api(), Adapter()
    value = custom_request(local, agent=AGENT, rewrite=True, count=2)
    text = ModelConfig("k" * 20, "vendor/text", "openai")
    receipt = process_generation(local, value, "lease", adapter, text_config=text)
    assert not validate_contract("generation-v4-completed", receipt)
    assert len(calls) == 1 and calls[0][0] == "vendor/text"
    assert calls[0][1].startswith("你是Gloria。画面干净，商品是主角")
    assert "不要要求图中出现任何文字" in calls[0][1]
    assert "需求：把商品放在浅色木桌上" in calls[0][2]
    for sent in adapter.requests:
        assert "Brief written by Gloria from the user's request: 温暖的卧室晨光" in sent.prompt
        assert "Instruction from the user" not in sent.prompt
        assert "keep the product from reference image 1 exactly" in sent.prompt
    agent = receipt["generations"][1]["provenance"]["agent"]
    assert agent["rewritten"].startswith("温暖的卧室晨光") and agent["text_model"] == "vendor/text"
    assert local.posts[0] == "heartbeat"


def test_magic_wand_without_a_text_model_fails_before_any_image_call(font):
    local, adapter = api(), Adapter()
    with pytest.raises(BackgroundError, match="CONFIGURATION"):
        process_generation(local, custom_request(local, rewrite=True), "lease", adapter)
    assert adapter.requests == []


def text_reply(provider, payload, seen):
    import httpx

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("provider", "extra", "payload", "url"),
    [
        (
            "openrouter",
            {"provider_tag": "openai"},
            {
                "choices": [{"message": {"content": "```\n“奶油色卧室，晨光”\n```"}}],
                "usage": {"total_tokens": 9},
            },
            "https://openrouter.ai/api/v1/chat/completions",
        ),
        (
            "openai-compatible",
            {"base_url": "https://relay.example.com"},
            {"choices": [{"message": {"content": [{"type": "text", "text": "奶油色卧室，晨光"}]}}]},
            "https://relay.example.com/v1/chat/completions",
        ),
        (
            "gemini",
            {},
            {"candidates": [{"content": {"parts": [{"text": "奶油色卧室，晨光"}]}}]},
            "https://generativelanguage.googleapis.com/v1beta/models/vendor-text:generateContent",
        ),
    ],
)
def test_text_models_speak_each_format(provider, extra, payload, url):
    from image_service import text_models
    from image_service.background_config import ModelConfig

    seen = []
    config = ModelConfig("k" * 20, "vendor-text", provider=provider, proxy="", **extra)
    if provider == "openrouter":
        config = ModelConfig("k" * 20, "vendor/text", provider=provider, proxy="", **extra)
    brief, _ = text_models.rewrite(
        config, "系统", "需求：x", transport=text_reply(provider, payload, seen)
    )
    assert brief == "奶油色卧室，晨光"
    sent = seen[0]
    assert str(sent.url) == url.replace("vendor-text", config.model)
    body = json.loads(sent.content)
    if provider == "gemini":
        assert sent.headers["x-goog-api-key"] == "k" * 20
        assert body["systemInstruction"]["parts"][0]["text"] == "系统"
    else:
        assert sent.headers["authorization"] == "Bearer " + "k" * 20
        assert body["messages"][0] == {"role": "system", "content": "系统"}
    if provider == "openrouter":
        # The tag is a preference: other providers serve the model when that one does not.
        assert body["provider"] == {"order": ["openai"], "allow_fallbacks": True}


def test_text_model_errors_are_fixed_codes():
    import httpx

    from image_service import text_models
    from image_service.background_config import ModelConfig

    config = ModelConfig("k" * 20, "vendor/text", "openai", proxy="")
    busy = httpx.MockTransport(lambda request: httpx.Response(503, text="secret details"))
    with pytest.raises(BackgroundError) as error:
        text_models.rewrite(config, "s", "u", transport=busy)
    assert error.value.code == "PROVIDER_HTTP_503" and error.value.retryable
    empty = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]})
    )
    with pytest.raises(BackgroundError, match="INVALID_RESPONSE"):
        text_models.rewrite(config, "s", "u", transport=empty)


def test_text_model_without_a_tag_lets_openrouter_route(monkeypatch):
    """The 404 seen on 2026-10-08: a DeepSeek model pinned to the "openai" provider. Untagged
    text models are routed by OpenRouter; image models still need their tag."""
    from image_service import openrouter, text_models
    from image_service.background_config import config_from_mapping

    config = config_from_mapping(
        {"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash", "api_key": "k" * 20}
    )
    assert config.provider_tag is None
    seen = []
    payload = {"choices": [{"message": {"content": "奶油色卧室"}}]}
    brief, _ = text_models.rewrite(config, "s", "u", transport=text_reply("x", payload, seen))
    assert brief == "奶油色卧室" and "provider" not in json.loads(seen[0].content)
    with pytest.raises(BackgroundError, match="CONFIGURATION"):
        openrouter.OpenRouterAdapter(config)


def test_a_failed_rewrite_is_reported_as_the_rewrite(font, monkeypatch):
    from image_service import text_models
    from image_service.background_config import ModelConfig

    def missing(config, system, user):
        raise BackgroundError("PROVIDER_HTTP_404")

    monkeypatch.setattr(text_models, "rewrite", missing)
    local, adapter = api(), Adapter()
    text = ModelConfig("k" * 20, "vendor/text", "openai")
    with pytest.raises(BackgroundError) as error:
        process_generation(
            local, custom_request(local, rewrite=True), "lease", adapter, text_config=text
        )
    assert error.value.code == "TEXT_PROVIDER_HTTP_404"
    assert adapter.requests == []  # no paid image call after a failed rewrite
