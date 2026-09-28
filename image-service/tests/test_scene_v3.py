import io
import json

import pytest
from PIL import Image
from test_background import Provider, fixture_response, generate, request
from test_scene import Adapter, LocalApi, payload

from image_service.background import BackgroundError
from image_service.scene import fit_background, process_scene


def test_native_background_only_sends_verified_ratio():
    provider = Provider()
    provider.parameters = {"aspect_ratio": provider.parameters["aspect_ratio"]}
    provider.result = fixture_response("JPEG", (120, 80))
    result = generate(provider, request(resolution=None, output_format=None))
    body = json.loads(provider.calls[-1].content)
    assert set(body) == {"model", "prompt", "aspect_ratio", "provider"}
    assert result.width == 120 and result.height == 80


def test_native_ratio_still_requires_route_support():
    provider = Provider()
    provider.parameters = {}
    with pytest.raises(BackgroundError, match="UNSUPPORTED_CAPABILITY"):
        generate(provider, request(resolution=None, output_format=None))
    assert all(c.method == "GET" for c in provider.calls)


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


def test_v3_local_export_and_call_fence():
    api, adapter = LocalApi(), Adapter()
    original_call = api.call
    permits = []

    def call(method, path, **kwargs):
        if "/generation-calls/" in path:
            permits.append(path)
        return original_call(method, path, **kwargs)

    api.call = call
    value = payload(api)
    value["schema_version"] = 3
    value["output"] = {
        "aspect_ratio": "4:3",
        "width": 120,
        "height": 90,
        "format": "jpeg",
        "count": 3,
    }
    result = process_scene(api, value, "lease", adapter)
    assert result["schema_version"] == 3 and len(permits) == 3
    for index in (0, 3, 6):
        with Image.open(io.BytesIO(api.outputs[index])) as image:
            assert image.format == "JPEG" and image.size == (120, 90)
    assert all(
        g["provenance"]["background_transform"]["target_size"] == [120, 90]
        for g in result["background_generations"]
    )
