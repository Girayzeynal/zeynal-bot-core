"""Only an exact NBA-published permanent canonical index may route the fallback."""
import time
from unittest import TestCase
from unittest.mock import MagicMock,patch

from hybrid_engine.current_roster import CurrentRosterReview,native_get,season_index,NBA_COM_INJURY_INDEX
from tests import test_nba_com_injury_index as helper
from tests import test_current_roster as f


class CanonicalNBAIndexTests(TestCase):
    def test_native_client_records_only_the_exact_allowlisted_location_without_following(self):
        for code,url,allowed in ((301,NBA_COM_INJURY_INDEX,True),(308,NBA_COM_INJURY_INDEX,True),
                (301,NBA_COM_INJURY_INDEX+'?token=not-retained',False),
                (301,'https://nba.com.evil.invalid/players/injury-report',False),
                (429,NBA_COM_INJURY_INDEX,False)):
            response=MagicMock();response.status_code=code;response.headers={'Location':url}
            response.__enter__.return_value=response
            with patch('requests.get',return_value=response) as getter:
                result=native_get(season_index('2026/2027'),deadline=time.monotonic()+10)
            self.assertEqual(result.get('canonical_index_redirect_url'),NBA_COM_INJURY_INDEX if allowed else None)
            self.assertIs(getter.call_args.kwargs['allow_redirects'],False)
            self.assertNotIn('not-retained',str(result));getter.assert_called_once()

    def helper(self,*,location=NBA_COM_INJURY_INDEX,mirror=200):
        h=helper.OfficialNBAComDirectoryTests('runTest');h.setUp();self.addCleanup(h.doCleanups)
        h.primary_code=301;h.mirror_code=mirror
        def get(url,*,deadline):
            r=h.get(url,deadline=deadline)
            if url==season_index('2026/2027'):r['canonical_index_redirect_url']=location
            return r
        return h,CurrentRosterReview(h.root/'canonical',getter=get,
            extractor=lambda path,deadline:f.extraction(),clock=lambda:f.NOW,bounded_public_pdf_fallback=True)

    def test_native_permanent_canonical_route_reaches_same_exact_fixture_pdf(self):
        h,service=self.helper();result=service.review(h.context)
        self.assertEqual(result['index_failure']['http_status'],301)
        self.assertEqual(result['canonical_index_redirect_url'],NBA_COM_INJURY_INDEX)
        self.assertEqual(result['official_discovery_mode'],'LIVE_NBA_COM_OFFICIAL_INDEX')
        self.assertTrue(result['latest_report_verified']);self.assertIn(f.PDF_URL,h.calls)
        self.assertFalse(result['forecast_changed']);self.assertFalse(result['model_adjustment_applied'])

    def test_unapproved_or_missing_location_cannot_route_a_301(self):
        for location in (None,'https://evil.invalid/',NBA_COM_INJURY_INDEX+'/'):
            h,service=self.helper(location=location);result=service.review(h.context)
            self.assertEqual(result['official_http_status'],301)
            self.assertNotIn(NBA_COM_INJURY_INDEX,h.calls)
            self.assertFalse(result.get('latest_report_verified',False))

    def test_canonical_301_then_403_is_not_misrepresented_as_two_403_cdn_permission(self):
        h,service=self.helper(mirror=403);result=service.review(h.context)
        self.assertEqual(result['index_failure']['http_status'],301)
        self.assertEqual(result['alternate_index_failure']['http_status'],403)
        self.assertNotIn('public_cdn_probe_attempted',result)
        self.assertFalse(any('/referee/injury/' in url for url in h.calls))
