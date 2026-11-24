import json
from unittest import TestCase
from unittest.mock import patch
from hybrid_engine.source_inventory import inventory


class SourceInventoryTests(TestCase):
    @patch('hybrid_engine.source_inventory.credentials',return_value={'API_BASKETBALL':'SYNTHETIC_SECRET'})
    def test_inventory_separates_registered_and_verified_and_redacts_key(self, config):
        report=inventory()
        self.assertEqual(report['club_registry_size'],82)
        self.assertEqual(report['clubs_live_checked_in_this_report'],0)
        self.assertEqual(report['club_player_injury_feeds_verified_in_this_report'],0)
        self.assertEqual(report['network_requests'],0)
        self.assertEqual(report['api_configuration']['API_BASKETBALL'],'CONFIGURED_NOT_TESTED')
        self.assertNotIn('SYNTHETIC_SECRET',json.dumps(report))
        self.assertFalse(report['player_effect_applied'])
