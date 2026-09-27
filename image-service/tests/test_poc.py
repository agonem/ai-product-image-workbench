import hashlib
import math

import pytest
from PIL import Image, ImageDraw

from image_service.poc import compose, extract_subject, segment_white, transform
from image_service.poc_demo import generate


def test_candidate_rgb_never_enters_subject_and_inputs_unchanged():
    original = Image.new("RGBA", (3, 2), (12, 45, 98, 128))
    candidate = Image.new("RGBA", original.size, (255, 0, 0, 128))
    before = original.tobytes(), candidate.tobytes()
    subject = extract_subject(original, candidate)
    assert subject.getpixel((0, 0)) == (12, 45, 98, 64)
    assert (original.tobytes(), candidate.tobytes()) == before
    other = candidate.copy()
    other.paste((0, 255, 0, 128), (0, 0, 3, 2))
    assert subject.tobytes() == extract_subject(original, other).tobytes()


def test_white_segmentation_only_removes_border_connected_background():
    image = Image.new("RGB", (9, 9), "white")
    ImageDraw.Draw(image).rectangle((2, 2, 6, 6), outline="black", width=1)
    mask = segment_white(image)
    assert mask.mode == "L"
    assert mask.getpixel((0, 0)) == 0
    assert mask.getpixel((4, 4)) == 255  # enclosed white stays part of the subject
    assert mask.getpixel((2, 2)) == 255


def test_explicit_crop_scale_rotate_order_and_source_survives():
    source = Image.new("RGBA", (10, 8), (12, 45, 98, 255))
    before = source.tobytes()
    result = transform(source, crop=(2, 1, 8, 5), scale=2, angle=90)
    assert result.size == (8, 12)
    assert source.size == (10, 8) and source.tobytes() == before


def test_layer_order_and_half_alpha_are_not_squared():
    background = Image.new("RGBA", (4, 4), (0, 0, 0, 255))
    product = Image.new("RGBA", (2, 2), (200, 0, 0, 128))
    gift = Image.new("RGBA", (1, 1), (0, 255, 0, 255))
    result = compose(background, [(product, (1, 1)), (gift, (2, 2))])
    assert result.getpixel((1, 1)) == (100, 0, 0, 255)
    assert result.getpixel((2, 2)) == (0, 255, 0, 255)
    assert background.getpixel((2, 2)) == (0, 0, 0, 255)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scale": 0},
        {"scale": -1},
        {"scale": math.inf},
        {"scale": True},
        {"angle": math.nan},
        {"crop": (-1, 0, 4, 4)},
        {"crop": (0, 0, 0, 4)},
        {"crop": (0, 0, 5, 4)},
        {"scale": 10000},
    ],
)
def test_invalid_or_over_budget_geometry_rejected(kwargs):
    with pytest.raises(ValueError):
        transform(Image.new("RGBA", (4, 4)), **kwargs)


def test_mask_dimensions_and_modes_are_strict():
    with pytest.raises(ValueError):
        extract_subject(Image.new("RGB", (2, 2)), Image.new("RGBA", (3, 2)))
    with pytest.raises(ValueError):
        extract_subject(Image.new("RGB", (2, 2)), Image.new("RGB", (2, 2)))


def test_empty_foreground_is_rejected_not_approved():
    with pytest.raises(ValueError, match="foreground"):
        segment_white(Image.new("RGB", (5, 5), "white"))


def test_review_bundle_keeps_originals_and_exports_real_formats(tmp_path):
    output = tmp_path / "synthetic"
    report = generate(output)
    assert report is not None
    assert report["synthetic"] is True and report["review_status"] == "PENDING"
    for item in report["sources"] + report["exports"]:
        assert hashlib.sha256((output / item["file"]).read_bytes()).hexdigest() == item["sha256"]
    assert report["poc_version"] == "t02-synthetic-v2"
    for layer, source in zip(report["layers"], report["sources"], strict=True):
        assert layer["source"] == layer["original_file"] == source["file"]
        assert layer["original_sha256"] == source["sha256"]
        subject_file = output / layer["subject_layer_file"]
        assert (
            hashlib.sha256(subject_file.read_bytes()).hexdigest() == layer["subject_layer_sha256"]
        )
        with Image.open(subject_file) as image:
            assert image.mode == "RGBA"
    for kind in ("product", "gift"):
        assert (
            report["alpha"][kind + "_sha256"]
            == hashlib.sha256((output / (kind + "-alpha.png")).read_bytes()).hexdigest()
        )
    assert report["layers"][0]["original_sha256"] != report["layers"][0]["subject_layer_sha256"]
    for name, kind in (("composite.png", "PNG"), ("composite.jpg", "JPEG")):
        with Image.open(output / name) as image:
            assert image.format == kind and image.size == (640, 480)
    assert (output / "review.html").is_file()
    with pytest.raises(FileExistsError):
        generate(output)


@pytest.mark.parametrize("tolerance", [-1, 33, True, 1.2])
def test_segmentation_tolerance_rejects_ambiguous_values(tolerance):
    with pytest.raises(ValueError):
        segment_white(Image.new("RGB", (4, 4), "black"), tolerance)


def test_original_transparent_gift_survives_an_opaque_candidate():
    gift = Image.new("RGBA", (4, 4), (40, 70, 90, 128))
    assert extract_subject(gift, Image.new("L", gift.size, 255)).tobytes() == gift.tobytes()


def test_partial_canvas_clipping_is_explicit_and_full_clipping_rejected():
    background = Image.new("RGBA", (4, 4), "black")
    layer = Image.new("RGBA", (2, 2), "red")
    result = compose(background, [(layer, (-1, -1))])
    assert result.getpixel((0, 0)) == (255, 0, 0, 255)
    assert result.getpixel((1, 1)) == (0, 0, 0, 255)
    with pytest.raises(ValueError, match="outside"):
        compose(background, [(layer, (4, 0))])
    with pytest.raises(ValueError):
        compose(background, [(layer, (0, 0))] * 17)
    with pytest.raises(ValueError, match="budget"):
        compose(Image.new("RGBA", (4097, 1)), [(layer, (0, 0))])
