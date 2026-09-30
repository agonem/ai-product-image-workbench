"""Worker transport safety and withdrawn request versions."""

import ssl
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from image_service import app as app_module
from image_service.contracts import validate_contract
from image_service.worker import Api, concurrency, journal_root, process


class LocalApi:
    def __init__(self):
        self.calls = []

    def call(self, method, path, **kwargs):
        self.calls.append((method, path))
        raise AssertionError("a withdrawn request must not read assets or write outputs")


def test_worker_https_keeps_certificate_validation():
    api = Api("https://localhost:9443", "x" * 32, environment="production")
    try:
        context = api.client._transport._pool._ssl_context
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    finally:
        api.close()


def test_production_worker_rejects_http():
    with pytest.raises(ValueError):
        Api("http://localhost:8080", "x" * 32, environment="production")


@pytest.mark.parametrize(("version", "contract"), [(2, "scene-failed"), (3, "scene-v3-failed")])
def test_withdrawn_scene_versions_fail_without_provider_call(monkeypatch, version, contract):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a withdrawn scene batch must never reach the provider")

    monkeypatch.setattr("image_service.openrouter.OpenRouterAdapter", forbidden)
    monkeypatch.setattr("image_service.background_config.load_config", forbidden)
    api = LocalApi()
    request = {
        "schema_version": version,
        "task_id": "task",
        "attempt_id": "attempt",
        "correlation_id": "task",
        "feature_type": "SCENE",
    }
    receipt = process(api, request, "lease", False, provider_config={"api_key": "k"})
    assert receipt["event_type"] == f"image.task.failed.v{version}"
    assert receipt["error"]["code"] == "INVALID_CONTRACT"
    assert receipt["error"]["retryable"] is False
    assert api.calls == []
    assert not validate_contract(contract, receipt)


def test_cutout_route_is_withdrawn(monkeypatch):
    # ADR-20260929 removed cutout; even with the old token set the route no longer exists.
    monkeypatch.setenv("IMAGE_SERVICE_TOKEN", "t" * 32)
    client = TestClient(app_module.app)
    response = client.post(
        "/internal/v1/cutout?tolerance=8",
        headers={"Authorization": "Bearer " + "t" * 32},
        content=b"\x89PNG",
    )
    assert response.status_code == 404


@pytest.mark.parametrize(("raw", "slots"), [(None, 1), ("1", 1), (" 3 ", 3), ("8", 8)])
def test_worker_concurrency_defaults_to_one_slot(monkeypatch, raw, slots):
    if raw is None:
        monkeypatch.delenv("WORKER_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("WORKER_CONCURRENCY", raw)
    assert concurrency() == slots


@pytest.mark.parametrize("raw", ["0", "9", "-1", "two", ""])
def test_worker_concurrency_rejects_out_of_range_values(monkeypatch, raw):
    monkeypatch.setenv("WORKER_CONCURRENCY", raw)
    with pytest.raises(SystemExit):
        concurrency()


def test_each_slot_has_its_own_journal_and_slot_zero_keeps_the_original():
    root = Path("/data/journal")
    assert journal_root(root, 0) == root
    assert journal_root(root, 2) == root / "slot-2"
    assert len({journal_root(root, slot) for slot in range(8)}) == 8
