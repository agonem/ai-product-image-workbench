"""Worker transport safety and withdrawn routes."""

import ssl
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from image_service import app as app_module
from image_service.worker import Api, concurrency, journal_root


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
