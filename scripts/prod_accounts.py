"""Create one private production ADMIN bootstrap verifier; never pass passwords in arguments."""

import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    password = (
        sys.stdin.readline().rstrip("\r\n")
        if args.password_stdin
        else getpass.getpass("Production bootstrap password: ")
    )
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.username)
        or not 15 <= len(password.encode("utf-16-le")) // 2 <= 128
    ):
        parser.error("Use a lowercase username and a 15-128 character password")
    salt = secrets.token_bytes(16)
    value = {
        "username": args.username,
        "salt": salt.hex(),
        "password_hash": hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, 600000
        ).hex(),
    }
    args.file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output)
        output.flush()
        os.fsync(output.fileno())
    print("Production bootstrap verifier created. Restrict OS permissions; never commit it.")


if __name__ == "__main__":
    main()
