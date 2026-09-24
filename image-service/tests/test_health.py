import pytest
from httpx import ASGITransport, AsyncClient

from image_service.app import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.mark.anyio
async def test_health_matches_internal_v1_contract(client):
    response = await client.get("/internal/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "UP",
        "service": "image-service",
        "api_version": "v1",
    }


@pytest.mark.anyio
async def test_does_not_pretend_image_tasks_are_implemented(client):
    response = await client.post("/internal/v1/tasks", json={})
    assert response.status_code == 404


@pytest.mark.anyio
async def test_does_not_expose_public_api_or_docs(client):
    for path in ("/api/v1/health", "/docs", "/openapi.json"):
        response = await client.get(path)
        assert response.status_code == 404
