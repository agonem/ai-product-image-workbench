import hashlib

import pytest
from PIL import Image, ImageDraw

from image_service.real_review import build_review, guided_alpha


def test_connected_background_hole_and_text_exclusion_preserve_subject():
    image = Image.new("RGB", (20, 20), (239, 239, 239))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 15, 15), fill=(70, 50, 30))
    draw.rectangle((7, 7, 12, 12), fill=(239, 239, 239))
    draw.point((18, 1), fill="black")
    before = image.tobytes()
    mask = guided_alpha(
        image, background=[239] * 3, tolerance=6, seeds=[[9, 9]], exclude=[[17, 0, 20, 3]]
    )
    assert mask.getpixel((0, 0)) == mask.getpixel((9, 9)) == 0
    assert mask.getpixel((18, 1)) == 0
    assert mask.getpixel((5, 5)) == 255
    assert image.tobytes() == before
    closed = guided_alpha(image, background=[239] * 3, tolerance=6, seeds=[], exclude=[])
    assert closed.getpixel((9, 9)) == 255


@pytest.mark.parametrize(
    "change",
    [
        {"seeds": [[99, 0]]},
        {"tolerance": True},
        {"exclude": [[0, 0, 99, 9]]},
        {"background": [-1, 0, 0]},
    ],
)
def test_invalid_segmentation_parameters_fail(change):
    params = {"background": [255] * 3, "tolerance": 6, "seeds": [], "exclude": []}
    with pytest.raises(ValueError):
        guided_alpha(Image.new("RGB", (20, 20)), **(params | change))


def test_private_bundle_originals_hashes_reference_isolation_and_no_overwrite(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("product", "gift", "reference"):
        image = Image.new("RGB", (20, 20), "white")
        ImageDraw.Draw(image).rectangle((4, 4, 15, 15), fill="red")
        image.save(inputs / (name + ".png"))
    layer = {
        "background": [255] * 3,
        "tolerance": 6,
        "seeds": [],
        "exclude": [],
        "transform": {"crop": [2, 2, 18, 18], "scale": 0.8, "angle": 5},
        "position": [10, 10],
        "regions": {"edge": [2, 2, 18, 18]},
    }
    profile = {"sample_id": "SAMPLE-TEST", "canvas": [100, 100], "product": layer, "gift": layer}
    output = tmp_path / "result"
    report = build_review(inputs, output, profile)
    assert report["review_status"] == "PENDING" and not report["synthetic"]
    assert len(report["layers"]) == 2
    for item in report["sources"]:
        assert (output / item["file"]).read_bytes() == (inputs / item["name"]).read_bytes()
        assert hashlib.sha256((output / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    for layer in report["layers"]:
        original = Image.open(output / layer["original_file"]).convert("RGB")
        subject = Image.open(output / layer["subject_layer_file"])
        assert subject.convert("RGB").tobytes() == original.tobytes()
    first = (output / "composite.png").read_bytes()
    Image.new("RGB", (20, 20), "blue").save(inputs / "reference.png")
    build_review(inputs, tmp_path / "second", profile)
    assert first == (tmp_path / "second/composite.png").read_bytes()
    with pytest.raises(FileExistsError):
        build_review(inputs, output, profile)
