"""Canvas export (ADR-20261010-W): a board composed into one picture, no model."""

import hashlib
import io

import pytest
from PIL import Image, ImageFont

from image_service import typeset
from image_service.compose import compose, process_composition
from image_service.contracts import validate_contract
from image_service.worker import process

RED, BLUE = (200, 40, 40), (40, 70, 200)


def solid(color, size=(100, 50), fmt="PNG", orientation=None):
    image = Image.new("RGB", size, color)
    stream = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(stream, format=fmt, exif=exif)
    else:
        image.save(stream, format=fmt)
    return stream.getvalue()


class LocalApi:
    def __init__(self, inputs):
        self.inputs = inputs
        self.outputs = {}

    def call(self, method, path, **kwargs):
        if method == "GET":
            return self.inputs[path.split("/")[-1]]
        if method == "POST":
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


def frozen(api, name):
    return {
        "asset_id": name,
        "object_key": f"originals/p/{name}.image",
        "sha256": hashlib.sha256(api.inputs[name]).hexdigest(),
    }


def request(api, layers, background="#FFF6EC", size=(400, 400)):
    value = {
        "schema_version": 4,
        "event_type": "image.task.requested.v4",
        "event_id": "event",
        "task_id": "task",
        "attempt_id": "attempt",
        "correlation_id": "task",
        "output_object_prefix": "outputs/task/attempt/",
        "feature_type": "COMPOSE",
        "frame_id": "f:board",
        "compose": {"background": background, "layers": layers},
        "presets_version": "presets-v1",
        "output": {
            "aspect_ratio": "1:1",
            "width": size[0],
            "height": size[1],
            "format": "png",
            "count": 1,
        },
    }
    value["template_snapshot"] = {
        "versions": [],
        "output_preset": {"id": "generation_v4", "config": value["output"]},
    }
    assert not validate_contract("generation-v4-request", value)
    return value


@pytest.fixture()
def font(monkeypatch):
    monkeypatch.setenv("GENERATION_TEXT_FONT", "test-scalable-font")
    monkeypatch.setattr(typeset, "_font", lambda _path, size: ImageFont.load_default(size))


def test_pictures_are_placed_in_their_boxes_and_cut_at_the_board():
    api = LocalApi({"red": solid(RED), "blue": solid(BLUE)})
    layers = [
        {"image": frozen(api, "red"), "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.25},
        # Over the red one and a third outside the right edge (200..500 of 400).
        {"image": frozen(api, "blue"), "x": 0.5, "y": 0.2, "width": 0.75, "height": 0.25},
    ]
    board = compose(request(api, layers), lambda image: api.inputs[image["asset_id"]])
    assert board.size == (400, 400)
    assert board.getpixel((5, 5))[:3] == (255, 246, 236)  # the background colour
    assert board.getpixel((100, 60))[:3] == RED
    assert board.getpixel((390, 100))[:3] == BLUE
    assert board.getpixel((220, 100))[:3] == BLUE  # the later layer is on top
    assert board.getpixel((260, 190))[:3] == (255, 246, 236)
    # Shares that are not exact in binary (0.55 x 400 = 220.00000000000003) still draw.
    odd = [{"image": frozen(api, "red"), "x": 0.55, "y": 0.55, "width": 0.4, "height": 0.4}]
    board = compose(request(api, odd), lambda image: api.inputs[image["asset_id"]])
    assert board.getpixel((300, 300))[:3] == RED
    # Entirely off the board: nothing drawn, no error.
    away = [{"image": frozen(api, "red"), "x": -2, "y": 0, "width": 0.5, "height": 0.5}]
    blank = compose(request(api, away), lambda image: api.inputs[image["asset_id"]])
    assert blank.getpixel((0, 0))[:3] == (255, 246, 236)


def test_a_phone_photo_is_turned_upright():
    # Stored landscape (100 x 50) but meant to be seen rotated (EXIF 6): upright it is 50 x 100,
    # so a portrait box gets the whole picture with no distortion.
    api = LocalApi({"photo": solid(RED, fmt="JPEG", orientation=6)})
    layers = [{"image": frozen(api, "photo"), "x": 0, "y": 0, "width": 0.25, "height": 0.5}]
    board = compose(request(api, layers), lambda image: api.inputs[image["asset_id"]])
    pixel = board.getpixel((50, 190))[:3]
    assert all(abs(a - b) < 40 for a, b in zip(pixel, RED, strict=True))


def test_text_is_drawn_with_the_selling_rules(font):
    api = LocalApi({})
    text = {
        "text": "下单即送\n洗头刷",
        "color": "#1E3A5F",
        "size": 0.08,
        "align": "left",
        "x": 0.1,
        "y": 0.1,
        "width": 0.8,
        "height": 0.4,
    }
    board = compose(request(api, [text]), lambda _: b"", "test-scalable-font")
    inked = [
        board.getpixel((x, y))[:3]
        for x in range(40, 360, 4)
        for y in range(40, 200, 4)
        if board.getpixel((x, y))[:3] != (255, 246, 236)
    ]
    assert inked, "the text was drawn inside its box"
    assert board.getpixel((20, 300))[:3] == (255, 246, 236)
    # Too long for its box even at the smallest size: refused, never cut.
    tiny = dict(text, text="很长" * 90, width=0.05, height=0.03)
    with pytest.raises(typeset.TextOverflow):
        compose(request(api, [tiny]), lambda _: b"", "test-scalable-font")


def test_receipt_is_one_picture_bound_to_its_inputs_and_no_model(font):
    api = LocalApi({"red": solid(RED), "blue": solid(BLUE)})
    layers = [
        {"image": frozen(api, "red"), "x": 0, "y": 0, "width": 1, "height": 0.5},
        {
            "text": "赠品",
            "color": "#FFFFFF",
            "size": 0.05,
            "align": "center",
            "x": 0,
            "y": 0.6,
            "width": 1,
            "height": 0.2,
        },
        {"image": frozen(api, "blue"), "x": 0.5, "y": 0.5, "width": 0.5, "height": 0.25},
    ]
    value = request(api, layers)
    receipt = process_composition(api, value, "lease")
    assert not validate_contract("generation-v4-completed", receipt)
    assert [a["kind"] for a in receipt["artifacts"]] == ["COMPOSITE"]
    assert api.outputs[0] == api.outputs[1]  # the picture is its own base
    with Image.open(io.BytesIO(api.outputs[0])) as image:
        assert image.size == (400, 400) and image.format == "PNG"
    provenance = receipt["generations"][0]["provenance"]
    assert provenance["output_source"] == "composition"
    assert provenance["inputs"] == {
        "layer_sha256": [layers[0]["image"]["sha256"], layers[2]["image"]["sha256"]]
    }
    assert provenance["composition"] == {"layers": 3, "text_layers": 1}
    assert provenance["transform"]["crop"] == [0, 0, 400, 400]


def test_the_worker_composes_without_any_provider(monkeypatch):
    api = LocalApi({"red": solid(RED)})
    layers = [{"image": frozen(api, "red"), "x": 0, "y": 0, "width": 1, "height": 0.5}]

    def no_provider(*_args, **_kwargs):
        raise AssertionError("no model may be contacted for a canvas export")

    monkeypatch.setattr("image_service.providers.model_adapter", no_provider)
    receipt = process(api, request(api, layers), "lease", False)
    assert receipt["artifacts"][0]["kind"] == "COMPOSITE"
    # Text that cannot fit is a clear failure, not a cut picture.
    monkeypatch.setenv("GENERATION_TEXT_FONT", "test-scalable-font")
    monkeypatch.setattr(typeset, "_font", lambda _path, size: ImageFont.load_default(size))
    tiny = {
        "text": "很长" * 90,
        "color": "#000000",
        "size": 0.05,
        "align": "left",
        "x": 0,
        "y": 0,
        "width": 0.05,
        "height": 0.03,
    }
    failed = process(api, request(api, [tiny]), "lease", False)
    assert failed["error"]["code"] == "TEXT_OVERFLOW"
