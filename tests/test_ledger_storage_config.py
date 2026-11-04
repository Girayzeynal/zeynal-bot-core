import os
import tempfile
import unittest
from pathlib import Path

from ledger_storage_config import resolve_prediction_ledger_path


class LedgerStorageConfigTests(unittest.TestCase):
    def test_disabled_does_not_require_mount(self):
        self.assertIsNone(resolve_prediction_ledger_path(
            enabled=False, volume_root="/nonexistent-volume"))

    def test_persistent_path_inside_mount(self):
        with tempfile.TemporaryDirectory() as root:
            path = resolve_prediction_ledger_path(
                enabled=True, volume_root=root,
                configured_path=str(Path(root) / "predictions.sqlite"))
            self.assertEqual(path, str(Path(root) / "predictions.sqlite"))

    def test_outside_volume_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                resolve_prediction_ledger_path(
                    enabled=True, volume_root=root,
                    configured_path="/tmp/ledger.sqlite")

    def test_missing_mount_rejected(self):
        with self.assertRaises(FileNotFoundError):
            resolve_prediction_ledger_path(
                enabled=True, volume_root="/missing-ledger-volume")

    def test_relative_path_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                resolve_prediction_ledger_path(
                    enabled=True, volume_root=root,
                    configured_path="predictions.sqlite")

    def test_missing_parent_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(RuntimeError):
                resolve_prediction_ledger_path(
                    enabled=True, volume_root=root,
                    configured_path=str(Path(root) / "missing" / "ledger.sqlite"))


if __name__ == "__main__":
    unittest.main()
