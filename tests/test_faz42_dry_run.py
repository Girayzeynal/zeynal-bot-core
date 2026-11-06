from unittest import TestCase
from unittest.mock import Mock,patch

from faz42_dry_run import run,plan
from tests.test_faz42_history import NOW


class DiscoveryDryRunTests(TestCase):
    def test_default_has_no_network_storage_or_scheduler_side_effect(self):
        collector=Mock();r=run(collector=collector)
        collector.assert_not_called();self.assertEqual(r['prospective_records_created'],0)
        self.assertEqual(r['network_requests'],0)

    def test_dynamic_us_calendar_and_official_competition_paths(self):
        p=plan(NOW);self.assertEqual(len(p),5)
        self.assertIn('dates=20261106',p[0]['url'])
        self.assertIn('/U/seasons/U2026/',p[-1]['url'])

    def test_blocked_provider_is_not_reported_as_prediction_success(self):
        collector=Mock(side_effect=lambda url,provider:dict(status='HTTP_403',http_status=403,source_url=url,provider=provider))
        r=run(live=True,collector=collector,model={'not':'used'})
        self.assertEqual(collector.call_count,5);self.assertEqual(r['unique_upcoming_games'],0)
        self.assertEqual(r['unpersisted_predictions'],0);self.assertEqual(r['prospective_records_created'],0)
        self.assertTrue(all(s['status']=='HTTP_403' for s in r['sources']))
