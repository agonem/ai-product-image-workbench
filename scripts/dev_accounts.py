"""Create a new private development account file; passwords never appear in arguments."""

import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
import sys
import uuid
from pathlib import Path


def make_account(username, password):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", username) or not 12 <= len(password) <= 128:
        raise ValueError("Use a lowercase account name and a 12-128 character password")
    salt = secrets.token_bytes(16)
    return {
        "username": username,
        "user_id": uuid.uuid4().hex,
        "salt": salt.hex(),
        "password_hash": hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, 600000
        ).hex(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("local-data/dev-accounts.json"))
    parser.add_argument("--username", action="append", required=True)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Automation only: one password per account on standard input",
    )
    args = parser.parse_args()
    if len(args.username) > 100 or len(set(args.username)) != len(args.username):
        parser.error("Specify 1-100 distinct usernames")
    records = []
    for name in args.username:
        password = (
            sys.stdin.readline().rstrip("\r\n")
            if args.password_stdin
            else getpass.getpass(f"Development password for {name}: ")
        )
        records.append(make_account(name, password))
    args.file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Refuse to overwrite an existing identity file, including symlinks.
    descriptor = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(records, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    print(
        "Private development account file created. Restrict its OS permissions; do not commit it."
    )


if __name__ == "__main__":
    main()
