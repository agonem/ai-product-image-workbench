import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "image_service.app:app",
        host=os.getenv("IMAGE_HOST", "127.0.0.1"),
        port=int(os.getenv("IMAGE_PORT", "8001")),
        server_header=False,
    )
