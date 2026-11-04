"""Decision gates must survive the FAZ22 -> FAZ23 boundary."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from faz22_engine import Faz22Engine
from faz23_engine import Faz23Engine


class DecisionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.engine = Faz23Engine(str(Path(self.folder.name) / "snapshots.sqlite"))

    def core(self, **overrides):
        meta = dict(confidence_pct=90.0, risk="LOW", uncertainty_level="DÜŞÜK",
                    expected_total=230.0, market_total=210.0,
                    edge_flag="STRONG_EDGE", sim_std=12.0)
        meta.update(overrides)
        return SimpleNamespace(ctx=SimpleNamespace(league="NBA"), meta=meta, notes=[])

    def assert_blocked(self, core):
        result = self.engine.apply_decision(core)
        self.assertEqual(result.meta["analysis_status"], "NO_STRONG_SIGNAL")
        self.assertEqual(result.meta["strong_signals"], [])

    def test_upstream_lock_and_risk_adjusted_confidence_cannot_be_bypassed(self):
        for league in ("NBA", "EUROLEAGUE"):
            for overrides in ({"edge_flag": "NO_EDGE"}, {"confidence_pct": 65.0}):
                with self.subTest(league=league, overrides=overrides):
                    core = self.core(**overrides)
                    core.ctx.league = league
                    core = Faz22Engine().score_and_finalize(core)
                    self.assertLess(core.meta["final_confidence"], 60)
                    self.assert_blocked(core)

    def test_faz23_requires_explicit_finalized_gate(self):
        self.assert_blocked(self.core())

    def test_valid_upstream_signal_remains_available(self):
        core = Faz22Engine().score_and_finalize(self.core())
        self.assertEqual(core.meta["analysis_status"], "STRONG_SIGNAL")
        result = self.engine.apply_decision(core)
        self.assertEqual(result.meta["strong_signals"], ["MAÇ SONU ÜST"])

    def test_nonfinite_or_out_of_range_gate_and_market_values_are_blocked(self):
        template = Faz22Engine().score_and_finalize(self.core())
        cases = {
            "final_confidence": (None, True, float("nan"), float("inf"), 101, -1),
            "confidence_lock": (True, None, "False", 0),
            "risk": (None, "UNKNOWN", "HIGH"),
            "uncertainty_level": (None, "UNKNOWN", "YÜKSEK"),
            "analysis_status": (None, "NO_STRONG_SIGNAL", "FORCE_SIGNAL"),
            "market_total": (True, "210", float("inf"), 0, -1),
            "expected_total": (True, "230", float("inf"), 0, -1),
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    core = copy.deepcopy(template)
                    core.meta[field] = value
                    self.assert_blocked(core)

    def test_segment_rejected_by_faz22_cannot_be_reintroduced(self):
        core = Faz22Engine().score_and_finalize(self.core(
            expected_1h=110.5, market_1h=105.0, sim_std=50.0))
        # MS passes at edge=20; 1Y edge=5.5 fails its std-based threshold.
        self.assertEqual([s["segment"] for s in core.meta["strong_signals"]], ["MS"])
        self.assertEqual(self.engine.apply_decision(core).meta["strong_signals"],
                         ["MAÇ SONU ÜST"])


if __name__ == "__main__":
    unittest.main()
