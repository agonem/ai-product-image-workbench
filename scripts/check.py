"""Run the same non-mutating checks locally and in CI. Install dependencies first."""

import subprocess

from common import ROOT, environment, maven, tool


def main() -> None:
    env = environment()
    checks = [
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
    print("\nAll T01 checks passed. Run python scripts/smoke.py for live HTTP checks.")


if __name__ == "__main__":
    main()
