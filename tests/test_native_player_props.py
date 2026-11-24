from copy import deepcopy
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from core.team_identity import digest
from hybrid_engine.native_player_props import parse
from hybrid_engine.provider_access import ProviderAccess
from hybrid_engine.provider_bridge import ProviderBridge
from tests.test_provider_bridge import NOW,SNAPSHOT,SECRET,FakeProvider,priced_event,iso
from tests.test_provider_identity import discovery,detail

def player_market():
    return dict(key='player_points',last_update=iso(NOW-5),outcomes=[
        dict(name='Under',description='Synthetic Player',point=20.5,price=1.9),
        dict(name='Over',description='Synthetic Player',point=20.5,price=1.95)])

class PlayerNativeTests(TestCase):
    def test_exact_event_and_paired_prices_not_player_model(self):
        with patch('time.time',return_value=NOW):
            d=detail();d['source_url']+='&markets=player_points' if '?' in d['source_url'] else '?markets=player_points'
            d['document']['bookmakers'][0]['markets']=[player_market()]
            d['document_sha256']=digest(d['document'])
            p=parse(discovery(),d,SNAPSHOT)
            self.assertEqual(len(p['rows']),1)
            self.assertEqual(p['rows'][0]['prices'],dict(under=1.9,over=1.95))
            self.assertFalse(p['player_identity_verified']);self.assertFalse(p['model_input'])
            forged=deepcopy(d);forged['document']['id']='other';forged['document_sha256']=digest(forged['document'])
            with self.assertRaises(ValueError):parse(discovery(),forged,SNAPSHOT)
            d['document']['bookmakers'][0]['markets'][0]['outcomes'][1]['description']='Another Player'
            d['document_sha256']=digest(d['document'])
            self.assertEqual(parse(discovery(),d,SNAPSHOT)['rows'],[])

    def test_opt_in_player_failure_does_not_remove_primary_team_prices(self):
        class Provider(FakeProvider):
            def __call__(self,provider,url,key,*,timeout):
                if 'player_points' in parse_qs(urlsplit(url).query).get('markets',[''])[0]:
                    self.calls.append((provider,url))
                    return dict(status='ACCESS_OR_PLAN_DENIED')
                return super().__call__(provider,url,key,timeout=timeout)
        with TemporaryDirectory() as tmp,patch('time.time',return_value=NOW):
            fake=Provider()
            a=ProviderAccess({'THE_ODDS_API':SECRET},getter=fake,clock=lambda:NOW)
            b=ProviderBridge(a,tmp,player_props=True,clock=lambda:NOW)
            r=b.collect(SNAPSHOT)['providers']['THE_ODDS_API']
            self.assertTrue(r['observations'])
            self.assertEqual(r['player_props']['status'],'ACCESS_OR_PLAN_DENIED')
            self.assertEqual(b.read_receipt(r['source_pin'])['document'],priced_event())
