"""Run the same non-mutating checks locally and in CI. Install dependencies first."""

import subprocess
import sys

from common import ROOT, environment, maven, tool


def main() -> None:
    env = environment()
    checks = [
        ([sys.executable, "-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py"], ROOT),
        ([tool("npm"), "run", "check"], ROOT / "frontend"),
        ([*maven(), "verify"], ROOT / "business-service"),
        ([tool("uv"), "lock", "--check", "--project", "image-service"], ROOT),
        (
            [
                tool("uv"),
                "run",
                "--frozen",
                "--project",
                "image-service",
                "ruff",
                "check",
                "image-service",
                "scripts",
            ],
            ROOT,
        ),
        (
            [
                tool("uv"),
                "run",
                "--frozen",
                "--project",
                "image-service",
                "ruff",
                "format",
                "--check",
                "image-service",
                "scripts",
            ],
            ROOT,
        ),
        (
            [
                tool("uv"),
                "run",
                "--frozen",
                "--project",
                "image-service",
                "pytest",
                "image-service/tests",
            ],
            ROOT,
        ),
    ]
    for command, cwd in checks:
        print(f"\nCHECK ({cwd.name}): {' '.join(command)}", flush=True)
        subprocess.run(command, cwd=cwd, env=env, check=True)
    print("\nCode and contract checks passed. HTTP: python scripts/smoke.py.")
    print("Database checks NOT included: run python scripts/check_db.py separately.")


if __name__ == "__main__":
    main()
