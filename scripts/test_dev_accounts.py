import hashlib
import unittest

from dev_accounts import make_account


class DevelopmentAccountsTest(unittest.TestCase):
    def test_salted_verifier_matches_utf8_password_and_contains_no_plaintext(self):
        password = "Synthetic-密码-12345"
        first, second = make_account("alice", password), make_account("alice", password)
        self.assertEqual(set(first), {"username", "user_id", "salt", "password_hash"})
        self.assertNotEqual(first["salt"], second["salt"])
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(first["salt"]), 600000
        ).hex()
        self.assertEqual(first["password_hash"], expected)
        self.assertNotIn(password, str(first))

    def test_rejects_invalid_names_and_short_passwords(self):
        for name, password in (("../name", "x" * 12), ("alice", "short"), ("Alice", "x" * 12)):
            with self.assertRaises(ValueError):
                make_account(name, password)


if __name__ == "__main__":
    unittest.main()
