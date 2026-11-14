"""Fixture-scoped injury identity audit does not promote unverified rows."""
import unittest
from hybrid_engine.nba_injury_id_audit import audit_injury_id_mapping

class InjuryIdentityAuditTests(unittest.TestCase):
    def setUp(self):
        self.rows=[
            {'matchup':'DEN@NOP','team':'DenverNuggets','player_name':'Example,One','status':'Out'},
            {'matchup':'DEN@NOP','team':'DenverNuggets','player_name':'Example,Two','status':'Questionable'},
            {'matchup':'BKN@MEM','team':'BrooklynNets','player_name':'Other','status':'Out'}]
        self.teams={'home':'NOP','away':'DEN','DenverNuggets':'DEN'}
    def test_missing_player_is_not_verified(self):
        result=audit_injury_id_mapping(self.rows,fixture_matchup='DEN@NOP',
            team_ids=self.teams,player_ids={('DenverNuggets','Example,One'):'player-1'})
        self.assertEqual(result['mapped_rows'],1)
        self.assertEqual(len(result['missing_player_mapping']),1)
        self.assertEqual(result['other_fixture_rows'],1)
        self.assertFalse(result['identity_mapping_complete'])
        self.assertFalse(result['roster_verified'])
        self.assertFalse(result['telegram_delivery_verified'])
    def test_explicit_mappings_still_not_roster_verified(self):
        result=audit_injury_id_mapping(self.rows,fixture_matchup='DEN@NOP',
            team_ids=self.teams,player_ids={('DenverNuggets','Example,One'):'player-1',
                                            ('DenverNuggets','Example,Two'):'player-2'})
        self.assertTrue(result['identity_mapping_complete'])
        self.assertFalse(result['roster_verified'])
    def test_duplicate_player_mapping_fails(self):
        result=audit_injury_id_mapping(self.rows,fixture_matchup='DEN@NOP',
            team_ids=self.teams,player_ids={('DenverNuggets','Example,One'):'same',
                                            ('DenverNuggets','Example,Two'):'same'})
        self.assertEqual(result['duplicate_player_rows'],1)
        self.assertFalse(result['identity_mapping_complete'])

if __name__=='__main__':
    unittest.main()
