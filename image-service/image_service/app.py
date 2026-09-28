import os
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from image_service.background import BackgroundError
from image_service.background_config import config_from_mapping
from image_service.openrouter import OpenRouterAdapter

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class HealthResponse(BaseModel):
    status: Literal["UP"] = "UP"
    service: Literal["image-service"] = "image-service"
    api_version: Literal["v1"] = "v1"


@app.get("/internal/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process health only; offline research is not an online generation capability."""
    return HealthResponse()


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openrouter"]
    api_key: str
    model: str
    provider_tag: str


@app.post("/internal/v1/provider/check")
def provider_check(body: CheckRequest, authorization: str | None = Header(default=None)) -> dict:
    """Relay a non-paid capability GET for Java administrators. The route stays disabled
    until PROVIDER_CHECK_TOKEN is explicitly configured on this process."""
    expected = os.getenv("PROVIDER_CHECK_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if authorization != "Bearer " + expected:
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    try:
        config = config_from_mapping(body.model_dump())
        with OpenRouterAdapter(config) as adapter:
            return adapter.inspect()
    except BackgroundError as error:
        # Safe code only; never echo provider bodies or the forwarded key.
        raise HTTPException(status_code=502, detail=error.code) from None
