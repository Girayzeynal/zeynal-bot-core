import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from providers.espn_live_smoke import main


class ESPNSmokeCLITests(unittest.TestCase):
    def test_bad_date_rejected(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["20260230"]), 2)
            self.assertEqual(main([]), 2)

    def test_unavailable_response_fails_closed(self):
        async def unavailable(date):
            raise RuntimeError("unavailable")
        output = io.StringIO()
        with patch("providers.espn_live_smoke.check_scoreboard", unavailable):
            with redirect_stdout(output):
                self.assertEqual(main(["20261031"]), 1)
        self.assertIn('"status": "error"', output.getvalue())

    def test_verified_response_succeeds(self):
        async def available(date):
            return {"status": "verified_response", "date_yyyymmdd": date,
                    "completed_events_count": 0}
        output = io.StringIO()
        with patch("providers.espn_live_smoke.check_scoreboard", available):
            with redirect_stdout(output):
                self.assertEqual(main(["20261031"]), 0)
        self.assertIn('"verified_response"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
