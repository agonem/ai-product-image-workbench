"""Worker-local receipt journal; never a connection to the Java business database."""

import hashlib
import json
import os
from pathlib import Path


class CorruptJournal(Exception):
    """Stop for operator inspection without deleting or printing the sensitive record."""


class Journal:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root
        self.lock = None

    def __enter__(self):
        self.lock = (self.root / ".lock").open("a+b")
        self.lock.seek(0)
        self.lock.write(b"0")
        self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError("Worker journal is already in use") from None
        return self

    def __exit__(self, *_):
        if self.lock:
            self.lock.close()

    def save(self, attempt: str, lease: str, receipt: dict) -> Path:
        # These IDs come from a validated contract / generated hex lease, never a path.
        if not attempt.isalnum() or not lease.isalnum():
            raise ValueError("Invalid journal identity")
        lease_digest = hashlib.sha256(lease.encode()).hexdigest()
        target = self.root / f"{attempt}-{lease_digest}.json"
        temporary = target.with_suffix(".pending")
        value = {"attempt": attempt, "lease": lease, "receipt": receipt}
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        if os.name != "nt":
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return target

    def pending(self):
        for path in sorted(self.root.glob("*.json")):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("attempt"), str)
                    or not entry["attempt"].isalnum()
                    or not isinstance(entry.get("lease"), str)
                    or not entry["lease"].isalnum()
                    or not isinstance(entry.get("receipt"), dict)
                ):
                    raise ValueError("Invalid journal record")
            except (OSError, ValueError) as error:
                raise CorruptJournal("Inspect private journal before restarting Worker") from error
            yield path, entry

    def acknowledge(self, path: Path):
        path.unlink()
