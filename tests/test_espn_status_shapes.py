import unittest

from providers.espn_status_shapes import summarize_espn_status_shapes


class ESPNStatusShapesTests(unittest.TestCase):
    def test_separate_event_and_competition_status(self):
        events = [
            {"status": {"type": {"state": "post", "completed": True}},
             "competitions": [{"status": {"type": {"state": "post",
                                                   "completed": True}}}]},
            {"status": {"type": {"state": "pre", "completed": False}},
             "competitions": [{"status": {"type": {"state": "in",
                                                   "completed": False}}}]},
        ]
        result = summarize_espn_status_shapes(events)
        self.assertEqual(result["event_status_types"], {
            "state=post,completed=true": 1, "state=pre,completed=false": 1
        })
        self.assertEqual(result["competition_status_types"], {
            "state=in,completed=false": 1, "state=post,completed=true": 1
        })

    def test_untrusted_state_is_bounded(self):
        result = summarize_espn_status_shapes([{
            "status": {"type": {"state": "SECRET-UNTRUSTED", "completed": "yes"}},
            "competitions": [],
        }])
        self.assertNotIn("SECRET-UNTRUSTED", str(result))
        self.assertEqual(result["competition_status_types"], {"missing": 1})


if __name__ == "__main__":
    unittest.main()
