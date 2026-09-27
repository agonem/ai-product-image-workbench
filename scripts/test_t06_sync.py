import unittest

from check_t06_sync import expire_sessions


class Database:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def sql(self, value):
        self.calls.append(value)
        return next(self.results)


class SessionSyncTest(unittest.TestCase):
    def test_exact_same_active_sessions_verified_before_and_after(self):
        run = Database(["2", "2", "2"])
        hashes = ["a" * 64, "b" * 64]
        self.assertEqual(
            expire_sessions(run, hashes), {"verified_hashes": hashes, "expired_count": 2}
        )
        self.assertEqual(len(run.calls), 3)
        for statement in run.calls:
            self.assertTrue(all(value in statement for value in hashes))

    def test_invalid_or_duplicate_hash_cannot_reach_sql(self):
        for hashes in (["x' OR true--", "b" * 64], ["a" * 64] * 2, []):
            run = Database([])
            with self.assertRaises(ValueError):
                expire_sessions(run, hashes)
            self.assertEqual(run.calls, [])

    def test_missing_active_session_stops_before_update(self):
        run = Database(["1"])
        with self.assertRaises(RuntimeError):
            expire_sessions(run, ["a" * 64, "b" * 64])
        self.assertEqual(len(run.calls), 1)

    def test_failed_update_or_readback_never_acknowledges_expiry(self):
        for results in (["2", "1"], ["2", "2", "1"]):
            with self.assertRaises(RuntimeError):
                expire_sessions(Database(results), ["a" * 64, "b" * 64])
