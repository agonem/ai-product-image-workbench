"""Shared local-process helpers; no global environment or system settings are changed."""

import os
import shutil
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"Required tool is missing: {name}. See docs/07.")
    return executable


def environment() -> dict[str, str]:
    # Spring relaxed binding can treat inherited SERVER__PORT as server.port.
    # Isolate this foreign namespace without changing the parent process environment.
    env = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("SERVER__")
    }
    env.setdefault("UV_LINK_MODE", "copy")
    if os.name == "nt" and "jdk.net.unixdomain.tmpdir" not in env.get("JAVA_TOOL_OPTIONS", ""):
        # Some Windows temp directories reject JDK selector Unix-domain sockets.
        # This override is confined to the processes started by these scripts.
        socket_dir = ROOT / ".artifacts" / "java-tmp"
        socket_dir.mkdir(parents=True, exist_ok=True)
        option = f'"-Djdk.net.unixdomain.tmpdir={socket_dir}"'
        env["JAVA_TOOL_OPTIONS"] = f"{env.get('JAVA_TOOL_OPTIONS', '')} {option}".strip()
    return env


def maven() -> list[str]:
    wrapper = ROOT / "business-service" / ("mvnw.cmd" if os.name == "nt" else "mvnw")
    command = [str(wrapper)] if os.name == "nt" else [tool("bash"), str(wrapper)]
    return [*command, "-B", "-ntp"]


def process_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            [tool("taskkill"), "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)
