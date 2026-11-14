"""Safety and cutoff contracts for independent roster evidence."""
import unittest
from hybrid_engine.roster_evidence import assess_roster_evidence

class RosterEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.prediction = 1794700000
        self.tipoff = self.prediction + 3600

    def record(self, status='QUESTIONABLE', published=None, player='player-1'):
        return dict(team_id='team-1', player_id=player, status=status,
                    published_at_utc=self.prediction if published is None else published,
                    source_url='https://example.org/report')

    def test_pre_prediction_record_is_partial_not_confirmed_lineup(self):
        result = assess_roster_evidence([self.record()], prediction_utc=self.prediction,
                                        fixture_start_utc=self.tipoff)
        self.assertEqual(len(result['records']), 1)
        self.assertFalse(result['rotation_verified'])
        self.assertFalse(result['minutes_adjustment_allowed'])
        self.assertEqual(result['confirmed_starters'], [])

    def test_late_or_unattributed_report_is_rejected(self):
        late = self.record(published=self.prediction+1)
        bad = self.record(player='player-2')
        bad['source_url'] = ''
        result = assess_roster_evidence([late, bad], prediction_utc=self.prediction,
                                        fixture_start_utc=self.tipoff)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['rejected_count'], 2)

    def test_conflicting_statuses_are_withheld(self):
        result = assess_roster_evidence([self.record('OUT'), self.record('AVAILABLE')],
                                        prediction_utc=self.prediction,
                                        fixture_start_utc=self.tipoff)
        self.assertEqual(result['records'], [])
        self.assertEqual(result['conflict_count'], 1)

    def test_invalid_cutoff_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_roster_evidence([], prediction_utc=self.tipoff,
                                   fixture_start_utc=self.tipoff)

if __name__ == '__main__':
    unittest.main()
