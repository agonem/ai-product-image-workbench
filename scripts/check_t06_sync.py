"""Private test-only file rendezvous; all database work stays in Python."""

import json
import re
import time


def expire_sessions(run, hashes):
    if (
        not isinstance(hashes, list)
        or len(hashes) != 2
        or any(
            not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in hashes
        )
        or len(set(hashes)) != 2
    ):
        raise ValueError("Expected two distinct session hashes")
    selected = "token_hash IN (" + ",".join("'" + value + "'" for value in hashes) + ")"
    if (
        run.sql(
            "SELECT count(*) FROM local_sessions WHERE "
            + selected
            + " AND expires_at>clock_timestamp()"
        )
        != "2"
    ):
        raise RuntimeError("Selected sessions must both exist and be active before injection")
    if (
        run.sql(
            "WITH changed AS (UPDATE local_sessions SET "
            "expires_at=clock_timestamp()-interval '1 second' WHERE "
            + selected
            + " AND expires_at>clock_timestamp() RETURNING token_hash) SELECT count(*) FROM changed"
        )
        != "2"
    ):
        raise RuntimeError("Exact session expiry update failed")
    if (
        run.sql(
            "SELECT count(*) FROM local_sessions WHERE "
            + selected
            + " AND expires_at<=clock_timestamp()"
        )
        != "2"
    ):
        raise RuntimeError("Same sessions were not verified expired")
    return {"verified_hashes": hashes, "expired_count": 2}


def coordinate(run, directory, process):
    phases = ["expire", "seed"]
    deadline = time.monotonic() + 180
    while process.poll() is None:
        if time.monotonic() > deadline:
            raise TimeoutError("Browser coordinator timed out")
        if phases:
            phase = phases[0]
            request = directory / (phase + ".request.json")
            if request.exists():
                if request.stat().st_size > 4096:
                    raise ValueError("Oversized test synchronization request")
                payload = json.loads(request.read_text(encoding="utf-8"))
                if phase == "expire":
                    if not isinstance(payload, dict) or set(payload) != {"hashes"}:
                        raise ValueError("Invalid expiry synchronization request")
                    result = expire_sessions(run, payload["hashes"])
                else:
                    if payload != {}:
                        raise ValueError("Invalid seed synchronization request")
                    run.sql(
                        "INSERT INTO users(id,status) SELECT 'zz_page_'||n,'ACTIVE' "
                        "FROM generate_series(1,101) n; "
                        "INSERT INTO local_credentials(user_id,username,salt,password_hash,role) "
                        "SELECT 'zz_page_'||n,'page_'||n,c.salt,c.password_hash,'USER' "
                        "FROM generate_series(1,101) n CROSS JOIN local_credentials c "
                        "WHERE c.username='alice'"
                    )
                    result = {
                        "account_count": int(run.sql("SELECT count(*) FROM local_credentials"))
                    }
                temporary = directory / (phase + ".done.tmp")
                temporary.write_text(json.dumps(result), encoding="utf-8")
                temporary.replace(directory / (phase + ".done.json"))
                phases.pop(0)
                print("PASS Python browser synchronization:", phase, flush=True)
        time.sleep(0.05)
    if process.returncode != 0 or phases:
        raise RuntimeError("Browser test failed or synchronization phases incomplete")
