"""Regression tests: FAZ22 never invents period market lines or bypasses an active lock."""
import unittest
from types import SimpleNamespace

from faz22_engine import Faz22Engine


def core(**overrides):
    meta = dict(
        data_quality="VERIFIED_BASELINE",
        confidence_pct=90.0,
        edge_flag="STRONG_EDGE",
        risk="LOW",
        market_total=200.0,
        expected_total=230.0,
        expected_1h=120.0,
        expected_2h=110.0,
        expected_q1=60.0,
        expected_q2=60.0,
        expected_q3=55.0,
        expected_q4=55.0,
    )
    meta.update(overrides)
    return SimpleNamespace(ctx=SimpleNamespace(league="NBA"), meta=meta, notes=[])


class Faz22PeriodMarketSafetyTests(unittest.TestCase):
    def test_total_market_does_not_imply_half_or_quarter_markets(self):
        result = Faz22Engine().score_and_finalize(core())
        self.assertEqual([s["segment"] for s in result.meta["strong_signals"]], ["MS"])

    def test_explicit_period_market_is_eligible(self):
        result = Faz22Engine().score_and_finalize(core(market_1h=100.0, market_q1=40.0))
        self.assertEqual(
            {s["segment"] for s in result.meta["strong_signals"]},
            {"MS", "1Y", "Q1"},
        )

    def test_active_lock_cannot_emit_strong_signal(self):
        # A weak-edge flag holds the lock; a large market deviation must
        # not be promoted while that lock remains active.
        result = Faz22Engine().score_and_finalize(
            core(edge_flag="NO_EDGE", sim_std=None, edge_distance=None)
        )
        self.assertTrue(result.meta["confidence_lock"])
        self.assertEqual(result.meta["strong_signals"], [])
        self.assertEqual(result.meta["analysis_status"], "NO_STRONG_SIGNAL")


if __name__ == "__main__":
    unittest.main()
