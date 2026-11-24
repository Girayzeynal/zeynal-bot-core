from copy import deepcopy
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlsplit
from core.team_identity import digest
from hybrid_engine.provider_access import ProviderAccess
from hybrid_engine.provider_bridge import ProviderBridge
from tests.test_provider_bridge import NOW,SNAPSHOT,SECRET,FakeProvider,receipt

class BackupPriceTests(TestCase):
    def run_case(self,*,primary_ok=False,wrong=False,blocked=False):
        class Getter(FakeProvider):
            def __call__(self,provider,url,key,*,timeout):
                if provider=='THE_ODDS_API' and not primary_ok:
                    self.calls.append((provider,url));return dict(status='RATE_LIMITED')
                if provider=='API_BASKETBALL' and urlsplit(url).path=='/odds':
                    self.calls.append((provider,url))
                    return receipt(dict(errors=[],response=[dict(
                        league=dict(id=12,season='2026-2027'),game=dict(id=999 if wrong else 123),
                        bookmakers=[dict(id=1,name='Synthetic book',bets=[dict(id=2,name='Home/Away',
                            values=[dict(value='Home',odd='1.90'),dict(value='Away',odd='1.95')])])])]),provider,url)
                r=super().__call__(provider,url,key,timeout=timeout)
                if blocked and provider=='API_BASKETBALL' and urlsplit(url).path=='/games':
                    r['document']=dict(errors={'plan':'Restricted','season':'Restricted'},response=[])
                    r['document_sha256']=digest(r['document'])
                return r
        with TemporaryDirectory() as tmp,patch('time.time',return_value=NOW):
            fake=Getter();a=ProviderAccess({'THE_ODDS_API':SECRET,'API_BASKETBALL':SECRET},getter=fake,clock=lambda:NOW)
            b=ProviderBridge(a,tmp,clock=lambda:NOW);snap=deepcopy(SNAPSHOT);before=digest(snap)
            report=b.collect(snap)
            self.assertEqual(digest(snap),before)
            return report,[u for p,u in fake.calls if p=='API_BASKETBALL' and urlsplit(u).path=='/odds']
    def test_primary_failure_attempts_verified_backup_once_without_freshness_claim(self):
        r,c=self.run_case();self.assertEqual(len(c),1)
        b=r['providers']['API_BASKETBALL']['backup_prices']
        self.assertEqual(b['status'],'BACKUP_NATIVE_LABELS_OBSERVED_TIME_UNVERIFIED')
        self.assertEqual(len(b['rows']),2);self.assertFalse(b['current_prices_verified'])
        self.assertFalse(b['model_input'])
    def test_primary_success_does_not_spend_backup_request(self):
        r,c=self.run_case(primary_ok=True);self.assertFalse(c)
        self.assertTrue(r['providers']['THE_ODDS_API']['observations'])
    def test_wrong_fixture_prices_are_refused(self):
        r,c=self.run_case(wrong=True);self.assertEqual(len(c),1)
        self.assertEqual(r['providers']['API_BASKETBALL']['backup_prices']['status'],'BACKUP_PRICE_EVIDENCE_REFUSED')
    def test_plan_restriction_does_not_guess_game_id(self):
        r,c=self.run_case(blocked=True);self.assertFalse(c)
        self.assertNotIn('backup_prices',r['providers']['API_BASKETBALL'])
