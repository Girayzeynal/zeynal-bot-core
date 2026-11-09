"""Regression checks for production ledger deployment preflight."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from deployment_ledger_preflight import inspect


class DeploymentLedgerPreflightTests(unittest.TestCase):
    def test_disabled_ledger_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("deployment_ledger_preflight.__file__", str(Path(directory) / "deployment_ledger_preflight.py")):
                problems = inspect(
                    env={"NBA_LEDGER_ENABLED": "false", "NBA_LEDGER_PATH": "/data/nba_prediction_ledger.sqlite"},
                    exists=lambda path: True, is_mount=lambda path: True)
        self.assertIn("NBA_LEDGER_ENABLED is not true", problems)

    def test_unmounted_volume_fails_even_if_directory_exists(self):
        problems = inspect(
            env={"NBA_LEDGER_ENABLED": "true", "NBA_LEDGER_PATH": "/data/nba_prediction_ledger.sqlite"},
            exists=lambda path: True, is_mount=lambda path: False)
        self.assertIn("/data is not a mounted persistent volume", problems)

    def test_missing_modules_fail(self):
        problems = inspect(
            env={"NBA_LEDGER_ENABLED": "true", "NBA_LEDGER_PATH": "/data/nba_prediction_ledger.sqlite"},
            exists=lambda path: str(path).endswith("/data"),
            is_mount=lambda path: True)
        self.assertTrue(any(p.startswith("missing module:") for p in problems))

    def test_ready_configuration_passes(self):
        problems = inspect(
            env={"NBA_LEDGER_ENABLED": "true", "NBA_LEDGER_PATH": "/data/nba_prediction_ledger.sqlite"},
            exists=lambda path: True, is_mount=lambda path: True)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
