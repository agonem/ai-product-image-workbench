"""Cutout candidate route: token gate, strict input, single-channel alpha, no echo."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from image_service import app as app_module

TOKEN = "c" * 40


def product(fmt="PNG", size=(96, 80), mode="RGB"):
    image = Image.new(mode, size, "white")
    ImageDraw.Draw(image).rectangle((30, 20, 70, 70), fill=(180, 40, 60))
    stream = io.BytesIO()
    image.save(stream, format=fmt)
    return stream.getvalue()


def post(client, body, query="?tolerance=12", token=TOKEN):
    return client.post(
        "/internal/v1/cutout" + query,
        content=body,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/octet-stream"},
    )


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("IMAGE_SERVICE_TOKEN", TOKEN)
    return TestClient(app_module.app)


def test_route_disabled_without_token(monkeypatch):
    monkeypatch.delenv("IMAGE_SERVICE_TOKEN", raising=False)
    assert post(TestClient(app_module.app), product()).status_code == 404
    monkeypatch.setenv("IMAGE_SERVICE_TOKEN", "short")
    assert post(TestClient(app_module.app), product(), token="short").status_code == 404


def test_wrong_token_rejected(client):
    assert post(client, product(), token="x" * 40).status_code == 401


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_candidate_is_single_channel_alpha_of_same_size(client, fmt):
    response = post(client, product(fmt))
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(response.content)) as alpha:
        assert alpha.mode == "L" and alpha.size == (96, 80)
        assert alpha.getpixel((0, 0)) == 0  # border-connected white background removed
        assert alpha.getpixel((50, 45)) == 255  # product kept opaque
        left, top, right, bottom = alpha.getbbox()
        if fmt == "PNG":
            assert (left, top, right, bottom) == (30, 20, 71, 71)
        else:
            # JPEG ringing near edges may widen the candidate; it must still contain the
            # product and stay near it, and a human reviews the edge before any use.
            assert left <= 30 and top <= 20 and right >= 71 and bottom >= 71
            assert left >= 14 and top >= 4 and right <= 87 and bottom <= 80


@pytest.mark.parametrize("query", ["", "?tolerance=33", "?tolerance=-1", "?tolerance=1&x=2"])
def test_invalid_parameters_rejected_without_echo(client, query):
    response = post(client, product(), query=query)
    assert response.status_code == 400
    assert response.json() == {"detail": "INVALID_CONTRACT"}


def test_non_image_and_all_white_are_diagnosable(client):
    corrupt = post(client, b"not an image with secret-marker")
    assert corrupt.status_code == 422 and "secret-marker" not in corrupt.text
    stream = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(stream, format="PNG")
    empty = post(client, stream.getvalue())
    assert empty.status_code == 422 and empty.json() == {"detail": "CUTOUT_NO_FOREGROUND"}


def test_over_budget_image_is_rejected(client):
    assert post(client, product(size=(4097, 8))).status_code == 413
    assert post(client, b"").status_code == 413
