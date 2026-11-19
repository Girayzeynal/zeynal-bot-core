"""Classification must not equate G League absence with injury."""
import unittest
from hybrid_engine.nba_injury_rows import classify_official_absence

class InjuryReasonClassificationTests(unittest.TestCase):
    def test_g_league_not_medical(self):
        for reason in ('GLeague-OnAssignment','GLeague-Two-Way','G League - On Assignment'):
            self.assertEqual(classify_official_absence({'status':'Out','reason':reason}),
                             'G_LEAGUE_OR_ASSIGNMENT')
    def test_medical_and_unclassified(self):
        self.assertEqual(classify_official_absence({'status':'Out','reason':'Injury/Illness-LeftKneeSprain'}),
                         'INJURY_OR_ILLNESS')
        self.assertEqual(classify_official_absence({'status':'Out','reason':'Unknown'}),
                         'OTHER_OR_UNCLASSIFIED')
    def test_unrecognized_status(self):
        self.assertEqual(classify_official_absence({'status':'NOT YET SUBMITTED','reason':'Injury'}),
                         'UNRECOGNIZED_STATUS')

if __name__=='__main__':
    unittest.main()
