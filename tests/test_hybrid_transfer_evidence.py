"""Historical transfer evidence must not leak future team identity."""
import unittest
from hybrid_engine.transfer_evidence import roster_membership

class TransferEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.cutoff=1794700000
        self.old=dict(player_id='p1',team_id='old-team',effective_from='2026-07-01',
                      effective_until='2026-11-10',published_at_utc=self.cutoff-100,
                      source_url='https://example.org/old')
        self.new=dict(player_id='p1',team_id='new-team',effective_from='2026-11-10',
                      published_at_utc=self.cutoff-50,
                      source_url='https://example.org/new')

    def resolve(self,day,events=None):
        return roster_membership([self.old,self.new] if events is None else events,
                                 player_id='p1',as_of_date=day,known_at_utc=self.cutoff)

    def test_transfer_date_boundary(self):
        self.assertEqual(self.resolve('2026-11-09')['team_id'],'old-team')
        self.assertEqual(self.resolve('2026-11-10')['team_id'],'new-team')

    def test_future_published_evidence_does_not_leak(self):
        later=dict(self.new,published_at_utc=self.cutoff+1)
        self.assertEqual(self.resolve('2026-11-11',[later])['status'],'MEMBERSHIP_UNVERIFIED')

    def test_conflicting_team_membership_abstains(self):
        conflicting=dict(self.new,team_id='third-team')
        self.assertEqual(self.resolve('2026-11-11',[self.new,conflicting])['status'],
                         'CONFLICTING_TEAM_MEMBERSHIP')

    def test_membership_is_not_game_eligibility(self):
        result=self.resolve('2026-11-11')
        self.assertFalse(result['roster_confirmed'])
        self.assertFalse(result['eligible_to_play_verified'])
        self.assertFalse(result['model_minutes_adjustment_allowed'])

if __name__=='__main__':
    unittest.main()
