import unittest
from sharp_guard import MarketSnapshot, audit_market


class SharpGuardTests(unittest.TestCase):
    def test_missing_and_stale_fail_closed(self):
        self.assertEqual(audit_market([], now_utc=1000).status, 'NO_EDGE')
        a = MarketSnapshot('A', 'TOTAL', 225.5, 1.9, 1.9, 100, 'provider')
        b = MarketSnapshot('A', 'TOTAL', 221.5, 1.9, 1.9, 200, 'provider')
        self.assertEqual(audit_market([a, b], now_utc=2000).status, 'NO_EDGE')

    def test_line_move_is_not_sharp_confirmation(self):
        a = MarketSnapshot('A', 'TOTAL', 225.5, 1.9, 1.9, 100, 'provider')
        b = MarketSnapshot('A', 'TOTAL', 221.5, 1.9, 1.9, 200, 'provider')
        r = audit_market([a, b], now_utc=210)
        self.assertEqual(r.status, 'OBSERVED_ONLY')
        self.assertEqual(r.movement, -4)
        self.assertFalse(r.sharp_confirmed)

    def test_mixed_sources_do_not_create_fake_movement(self):
        a = MarketSnapshot('A', 'TOTAL', 225.5, 1.9, 1.9, 100, 'provider1')
        b = MarketSnapshot('A', 'TOTAL', 221.5, 1.9, 1.9, 200, 'provider2')
        self.assertEqual(audit_market([a, b], now_utc=210).status, 'NO_EDGE')

    def test_invalid_price_is_rejected(self):
        a = MarketSnapshot('A', 'TOTAL', 225.5, 1.0, 1.9, 100, 'provider')
        self.assertEqual(audit_market([a], now_utc=210).status, 'NO_EDGE')


if __name__ == '__main__':
    unittest.main()
