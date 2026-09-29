import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ProductionBootstrapTest(unittest.TestCase):
    def test_private_bootstrap_has_no_cleartext_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bootstrap.json"
            command = [
                sys.executable,
                "scripts/prod_accounts.py",
                "--file",
                str(path),
                "--username",
                "admin",
                "--password-stdin",
            ]
            password = "Synthetic-pw-12"
            result = subprocess.run(command, input=password + "\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, "Production bootstrap command must succeed")
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(value), {"username", "salt", "password_hash"})
            self.assertNotIn(password, str(value) + result.stdout + result.stderr)
            before = path.read_bytes()
            result = subprocess.run(command, input=password + "\n", text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(before, path.read_bytes())

    def test_password_length_is_six_to_fifteen(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = (("12345", False), ("123456", True), ("a" * 15, True), ("a" * 16, False))
            for password, ok in cases:
                path = Path(directory) / f"bootstrap-{len(password)}.json"
                result = subprocess.run(
                    [sys.executable, "scripts/prod_accounts.py", "--file", str(path)]
                    + ["--username", "admin", "--password-stdin"],
                    input=password + "\n",
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode == 0, ok, len(password))
                self.assertEqual(path.exists(), ok)


if __name__ == "__main__":
    unittest.main()
