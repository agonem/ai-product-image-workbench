"""Start one local service. Run once in each of three terminals."""

import argparse
import subprocess

from common import ROOT, environment, process_options, stop, tool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["frontend", "business", "image", "worker"])
    args = parser.parse_args()
    commands = {
        "frontend": (["npm", "run", "dev"], ROOT / "frontend"),
        "business": (
            ["java", "-jar", "target/business-service.jar"],
            ROOT / "business-service",
        ),
        "worker": (
            ["uv", "run", "--frozen", "python", "-m", "image_service.worker"],
            ROOT / "image-service",
        ),
        "image": (
            ["uv", "run", "--frozen", "python", "-m", "image_service"],
            ROOT / "image-service",
        ),
    }
    if (
        args.service == "business"
        and not (ROOT / "business-service/target/business-service.jar").is_file()
    ):
        raise RuntimeError("Build first: python scripts/check.py")
    command, cwd = commands[args.service]
    command[0] = tool(command[0])
    process = subprocess.Popen(command, cwd=cwd, env=environment(), **process_options())
    try:
        result = process.wait()
        if result:
            raise SystemExit(result)
    except KeyboardInterrupt:
        pass
    finally:
        stop(process)


if __name__ == "__main__":
    main()
