import hmac
import io
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from PIL import Image
from pydantic import BaseModel

from image_service.poc import budget, segment_white

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Technical transport limit for one uploaded original, not a platform or business rule.
MAX_CUTOUT_BYTES = 67108864


class HealthResponse(BaseModel):
    status: Literal["UP"] = "UP"
    service: Literal["image-service"] = "image-service"
    api_version: Literal["v1"] = "v1"


@app.get("/internal/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process health only; offline research is not an online generation capability."""
    return HealthResponse()


def _candidate(raw: bytes, tolerance: int) -> bytes:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("PNG", "JPEG"):
                raise HTTPException(status_code=422, detail="INVALID_ASSET")
            budget(image.size)
            image.load()
            rgb = image.convert("RGB")
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=413, detail="CUTOUT_BUDGET") from None
    except (OSError, Image.DecompressionBombError):
        raise HTTPException(status_code=422, detail="INVALID_ASSET") from None
    try:
        alpha = segment_white(rgb, tolerance)
    except ValueError:
        raise HTTPException(status_code=422, detail="CUTOUT_NO_FOREGROUND") from None
    output = io.BytesIO()
    alpha.save(output, format="PNG")
    return output.getvalue()


@app.post("/internal/v1/cutout")
async def cutout(request: Request) -> Response:
    """White-background cutout CANDIDATE for human review, called only by Java.

    The route stays disabled (404) until IMAGE_SERVICE_TOKEN is configured. Only a single-channel
    alpha PNG is returned; the original is never modified and errors never echo the request.
    """
    expected = os.getenv("IMAGE_SERVICE_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode(), ("Bearer " + expected).encode()):
        raise HTTPException(status_code=401, detail="UNAUTHORIZED")
    params = dict(request.query_params)
    tolerance = params.pop("tolerance", "")
    if params or not tolerance.isdigit() or not 0 <= int(tolerance) <= 32:
        raise HTTPException(status_code=400, detail="INVALID_CONTRACT")
    raw = await request.body()
    if not raw or len(raw) > MAX_CUTOUT_BYTES:
        raise HTTPException(status_code=413, detail="CUTOUT_BUDGET")
    # Border flood fill is CPU bound; keep the event loop responsive for health checks.
    content = await run_in_threadpool(_candidate, raw, int(tolerance))
    return Response(content=content, media_type="image/png", headers={"Cache-Control": "no-store"})
