"""Isolated regression: never rewrite existing research plans on source revisions."""
import tempfile
import unittest
from pathlib import Path

from hybrid_engine.research_protocol_namespace import namespace


class ResearchNamespaceTests(unittest.TestCase):
    def test_new_pin_never_rewrites_old_trial_or_originals(self):
        with tempfile.TemporaryDirectory() as td:
            legacy=Path(td)/"nba-research-v3-integrity-v2"
            legacy.mkdir()
            sentinel=legacy/"plan.json"
            sentinel.write_bytes(b"IMMUTABLE_PREVIOUS_STUDY")
            a=namespace(td,"nba-v3",policy={"version":"v1"},
                        source_pins={"model":"a"*64})
            b=namespace(td,"nba-v3",policy={"version":"v1"},
                        source_pins={"model":"b"*64})
            self.assertNotEqual(a,b)
            self.assertEqual(a,namespace(td,"nba-v3",policy={"version":"v1"},
                                         source_pins={"model":"a"*64}))
            self.assertFalse(a.exists())
            self.assertFalse(b.exists())
            self.assertEqual(sentinel.read_bytes(),b"IMMUTABLE_PREVIOUS_STUDY")

    def test_three_league_model_policies_create_distinct_study_paths(self):
        with tempfile.TemporaryDirectory() as td:
            from hybrid_engine.adaptive_research import AdaptiveResearch, POLICY as AP, source_pins as AS
            from hybrid_engine.issue90_research import Research, POLICY as VP, pins as VS
            from hybrid_engine.current_assessment import CurrentAssessments, POLICY as CP
            ad=namespace(td,"adaptive-v2",policy=AP,source_pins=AS())
            v3=namespace(td,"nba-v3",policy=VP,source_pins=VS())
            cur=namespace(td,"current-assessment",policy=CP,source_pins=VS())
            self.assertEqual(len({str(ad),str(v3),str(cur)}),3)
            self.assertEqual(AdaptiveResearch(ad).plan(create=True)['payload']['policy'],AP)
            self.assertEqual(Research(v3,object()).plan()['payload']['policy'],VP)
            self.assertEqual(CurrentAssessments(cur,object(),object()).plan(create=True)['payload']['policy'],CP)
            self.assertTrue(str(ad).startswith(td))
            self.assertTrue(str(v3).startswith(td))
            self.assertTrue(str(cur).startswith(td))

    def test_untrusted_source_pin_or_unknown_scope_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,"UNKNOWN_FAMILY"):
                namespace(td,"production",policy={"version":"1"},
                          source_pins={"x":"a"*64})
            with self.assertRaisesRegex(ValueError,"PINS_CONTRACT"):
                namespace(td,"adaptive-v2",policy={"version":"1"},
                          source_pins={"x":42})
