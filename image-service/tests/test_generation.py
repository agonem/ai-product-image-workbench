"""v4 whole-image generation: references, prompts, export, text overlay and re-typeset."""

import hashlib
import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from image_service import typeset
from image_service.background import BackgroundError, BackgroundResult
from image_service.contracts import validate_contract
from image_service.generation import build_prompt, fit_background, process_generation
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
