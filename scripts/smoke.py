"""Start all three services, check real HTTP contracts, and always stop our processes."""

import json
import os
import socket
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from common import ROOT, environment, process_options, stop, tool

HTTP = build_opener(ProxyHandler({}))


def read(url: str) -> bytes:
    with HTTP.open(url, timeout=3) as response:
        return response.read()


def wait_ready(url: str, process: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service exited ({process.returncode}); see {log}")
        try:
            read(url)
            return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    raise RuntimeError(f"Service did not become ready at {url}; see {log}")


def expect_health(url: str, service: str) -> None:
    actual = json.loads(read(url))
    expected = {"status": "UP", "service": service, "api_version": "v1"}
    if actual != expected:
        raise AssertionError(f"Health contract mismatch at {url}: {actual!r}")
    print(f"PASS {url} -> {service}", flush=True)


def main() -> None:
    business_port = int(os.getenv("SMOKE_BUSINESS_PORT", "18080"))
    image_port = int(os.getenv("SMOKE_IMAGE_PORT", "18001"))
    frontend_port = int(os.getenv("SMOKE_FRONTEND_PORT", "15173"))
    ports = (business_port, image_port, frontend_port)
    if len(set(ports)) != 3:
        raise ValueError("Smoke ports must be different")
    for port in ports:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))

    jar = ROOT / "business-service/target/business-service.jar"
    if not jar.is_file():
        raise RuntimeError("Build first: python scripts/check.py")
    base = f"http://127.0.0.1:{business_port}"
    internal = f"http://127.0.0.1:{image_port}"
    frontend = f"http://127.0.0.1:{frontend_port}"
    env = environment()
    env.update(
        {
            "BUSINESS_HOST": "127.0.0.1",
            "BUSINESS_PORT": str(business_port),
            "IMAGE_HOST": "127.0.0.1",
            "IMAGE_PORT": str(image_port),
            "DEV_HOST": "127.0.0.1",
            "DEV_PORT": str(frontend_port),
            "DEV_API_TARGET": base,
        }
    )
    services = [
        ("business", [tool("java"), "-jar", str(jar)], ROOT, f"{base}/api/v1/health"),
        (
            "image",
            [tool("uv"), "run", "--frozen", "python", "-m", "image_service"],
            ROOT / "image-service",
            f"{internal}/internal/v1/health",
        ),
        ("frontend", [tool("npm"), "run", "dev"], ROOT / "frontend", frontend),
    ]
    log_dir = ROOT / ".artifacts/smoke"
    log_dir.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        for name, command, cwd, url in services:
            log_path = log_dir / f"{name}.log"
            log = stack.enter_context(log_path.open("w", encoding="utf-8"))
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                **process_options(),
            )
            stack.callback(stop, process)
            wait_ready(url, process, log_path)
        expect_health(f"{base}/api/v1/health", "business-service")
        expect_health(f"{internal}/internal/v1/health", "image-service")
        expect_health(f"{frontend}/api/v1/health", "business-service")
        if '<div id="app"></div>' not in read(frontend).decode("utf-8"):
            raise AssertionError("Frontend HTML entry is missing")
        try:
            read(f"{base}/api/v1/tasks")
        except HTTPError as error:
            if error.code != 404:
                raise
        else:
            raise AssertionError("An unimplemented task endpoint unexpectedly exists")
        print("PASS frontend HTML and unimplemented task boundary", flush=True)
    print(f"Live HTTP smoke passed; child processes stopped. Logs: {log_dir}")


if __name__ == "__main__":
    main()
