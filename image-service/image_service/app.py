from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class HealthResponse(BaseModel):
    status: Literal["UP"] = "UP"
    service: Literal["image-service"] = "image-service"
    api_version: Literal["v1"] = "v1"


@app.get("/internal/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process health only; image processing and providers are not implemented."""
    return HealthResponse()
