"""Isolated Telegram baseline gate regression tests without bot startup."""
import ast
import math
import pathlib
import time
import types
import unittest
from typing import Any


def load_gate():
    path = pathlib.Path(__file__).resolve().parents[1] / "main.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in module.body
                if isinstance(item, ast.FunctionDef) and item.name == "baseline_is_usable")
    isolated = ast.Module(body=[node], type_ignores=[])
    namespace = {"Any": Any, "math": math}
    exec(compile(ast.fix_missing_locations(isolated), str(path), "exec"), namespace)
    return namespace["baseline_is_usable"]


class TelegramBaselineGateTests(unittest.TestCase):
    def test_valid_baseline_and_invalid_statistics(self):
        gate = load_gate()
        now = time.time()
        valid = dict(n_games=6, updated_ts=now - 60, pts_for=110,
                     pts_against=105, pace=99, stdev_total=12)
        self.assertTrue(gate(types.SimpleNamespace(**valid), now))
        for field, bad in (("n_games", 5), ("n_games", True),
                           ("updated_ts", now + 100), ("updated_ts", now - 9 * 86400),
                           ("pts_for", float("nan")), ("pts_against", float("inf")),
                           ("pace", 0), ("pace", float("nan")),
                           ("stdev_total", -1), ("stdev_total", float("inf"))):
            with self.subTest(field=field, bad=bad):
                self.assertFalse(gate(types.SimpleNamespace(**dict(valid, **{field: bad})), now))
        self.assertFalse(gate(None, now))


if __name__ == "__main__":
    unittest.main()
