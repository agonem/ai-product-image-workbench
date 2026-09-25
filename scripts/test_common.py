"""Regression checks for inherited launcher environment collisions."""

import os
import unittest
from unittest.mock import patch

from common import environment


class EnvironmentTest(unittest.TestCase):
    def test_removes_double_underscore_server_namespace_case_insensitively(self):
        for name in ("SERVER__HOST", "SERVER__PORT", "server__port", "Server__Other"):
            with self.subTest(name=name), patch.dict(os.environ, {name: "conflicting"}):
                self.assertNotIn(name.upper(), {key.upper() for key in environment()})

    def test_preserves_project_and_unrelated_settings(self):
        settings = {
            "BUSINESS_HOST": "127.0.0.1",
            "BUSINESS_PORT": "18080",
            "SERVER_PORT": "19090",
            "OTHER_SERVER__PORT": "keep",
        }
        with patch.dict(os.environ, settings):
            result = environment()
            for key, value in settings.items():
                self.assertEqual(value, result[key])

    def test_does_not_modify_parent_environment(self):
        with patch.dict(os.environ, {"SERVER__PORT": "invalid-port"}):
            before = dict(os.environ)
            environment()
            self.assertTrue(before == dict(os.environ), "Parent environment was mutated")


if __name__ == "__main__":
    unittest.main()
