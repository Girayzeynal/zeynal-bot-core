from unittest import TestCase
from unittest.mock import Mock

from faz41_source_smoke import run,PLAN


class LiveOptInTests(TestCase):
    def test_default_has_no_network_side_effect_or_fake_prospective_record(self):
        collector=Mock();r=run(collector=collector)
        collector.assert_not_called();self.assertEqual(r['network_requests'],0)
        self.assertEqual(r['prospective_records_created'],0)

    def test_blocked_providers_are_reported_separately_from_model_success(self):
        collector=Mock(side_effect=lambda url,provider:dict(source_url=url,provider=provider,status='HTTP_403',http_status=403))
        r=run(live=True,collector=collector)
        self.assertEqual(collector.call_count,len(PLAN));self.assertEqual(r['observations'],[])
        self.assertEqual(r['nba_espn_cross_check'],'NOT_PERFORMED');self.assertEqual(r['official_prematch_lineups'],0)
