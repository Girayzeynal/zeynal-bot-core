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
    nodes = [item for item in module.body
             if isinstance(item, ast.FunctionDef)
             and item.name in ("baseline_quality_reason", "baseline_is_usable")]
    isolated = ast.Module(body=nodes, type_ignores=[])
    namespace = {"Any": Any, "math": math}
    exec(compile(ast.fix_missing_locations(isolated), str(path), "exec"), namespace)
    return namespace["baseline_is_usable"]


def load_failure_message():
    path = pathlib.Path(__file__).resolve().parents[1] / "main.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [item for item in module.body
             if (isinstance(item, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id == "BASELINE_REASON_TR"
                 for target in item.targets))
             or (isinstance(item, ast.FunctionDef)
                 and item.name == "baseline_failure_message")]
    namespace = {}
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), namespace)
    return namespace["baseline_failure_message"]


class TelegramBaselineGateTests(unittest.TestCase):
    def test_failure_message_distinguishes_home_and_away(self):
        message = load_failure_message()("insufficient_games", "stale")
        self.assertIn("Ev sahibi: en az 6 uygun maç kaydı gerekiyor", message)
        self.assertIn("Deplasman: takım verisi güncel değil", message)
        self.assertIn("\\n", message)
        self.assertIn("tahmin üretilmez", message)
        self.assertNotIn("bilinmeyen veri sorunu", message)

    def test_failure_message_unknown_reason_fails_explanatorily(self):
        message = load_failure_message()("unknown", "missing")
        self.assertIn("Ev sahibi: bilinmeyen veri sorunu", message)
        self.assertIn("Deplasman: doğrulanmış takım geçmişi bulunamadı", message)

    def test_reason_matches_prediction_gate(self):
        gate = load_gate()
        now = time.time()
        valid = dict(n_games=6, updated_ts=now - 60, pts_for=110,
                     pts_against=105, pace=99, stdev_total=12)
        for field, bad, expected in (
            ("n_games", 5, "insufficient_games"),
            ("n_games", True, "malformed"),
            ("updated_ts", now - 9 * 86400, "stale"),
            ("pts_for", 0, "invalid_scores"),
            ("pace", 0, "invalid_stats"),
            ("stdev_total", float("nan"), "malformed"),
        ):
            with self.subTest(field=field):
                baseline = types.SimpleNamespace(**dict(valid, **{field: bad}))
                self.assertFalse(gate(baseline, now))
                self.assertEqual(gate.__globals__["baseline_quality_reason"](
                    baseline, now), expected)

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
