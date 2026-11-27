"""Malformed sibling data must not erase independent valid native evidence."""
from copy import deepcopy
from datetime import datetime,timezone
from email.utils import format_datetime
import io
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch
from urllib.error import HTTPError

from core.team_identity import digest
from hybrid_engine.provider_access import ProviderAccess,get_document
from hybrid_engine.provider_bridge import odds_observations,ProviderBridge
from hybrid_engine.native_player_props import parse
from hybrid_engine.api_basketball_odds import inspect_receipt
from tests.test_provider_bridge import NOW,SNAPSHOT,SECRET,FakeProvider,receipt,priced_event
from tests.test_provider_identity import discovery,detail
from tests.test_native_player_props import player_market


class PartialNativeContracts(TestCase):
    def test_partial_primary_survives_real_bridge_coverage_and_native_journal(self):
        with TemporaryDirectory() as folder,patch('time.time',return_value=NOW):
            getter=FakeProvider();getter.document['bookmakers'].insert(0,dict(key='broken',title='Broken',markets=None))
            getter.document['bookmakers'].insert(0,None)
            access=ProviderAccess({'THE_ODDS_API':SECRET},getter=getter,clock=lambda:NOW)
            bridge=ProviderBridge(access,folder,clock=lambda:NOW)
            p=bridge.collect(SNAPSHOT)['providers']['THE_ODDS_API']
            self.assertEqual(len(p['observations']),1)
            self.assertEqual(bridge.read_receipt(p['source_pin'])['document'],getter.document)
            self.assertTrue(p['market_coverage']['admitted_quote_counts'])

    def test_bad_team_price_siblings_do_not_erase_valid_book(self):
        for broken in (None,'incomplete',[],42):
            event=priced_event();event['bookmakers'].insert(0,broken)
            rows,rejected=odds_observations(receipt(event),SNAPSHOT)
            self.assertEqual(len(rows),1);self.assertGreater(rejected,0)
        event=priced_event();event['bookmakers'][0]['markets'].insert(0,None)
        rows,rejected=odds_observations(receipt(event),SNAPSHOT)
        self.assertEqual(len(rows),1);self.assertGreater(rejected,0)

    def test_bad_player_price_siblings_do_not_erase_valid_price_pair(self):
        with patch('time.time',return_value=NOW):
            d=detail();d['source_url']=d['source_url'].replace('markets=totals','markets=player_points')
            d['document']['bookmakers'][0]['markets']=[dict(key='player_points',outcomes=None),player_market()]
            d['document']['bookmakers'].insert(0,None)
            d['document']['bookmakers'].insert(0,dict(key='broken',title='Broken',markets=None))
            d['document_sha256']=digest(d['document'])
            result=parse(discovery(),d,SNAPSHOT)
            self.assertEqual(len(result['rows']),1)
            self.assertFalse(result['player_identity_verified']);self.assertFalse(result['settlement_verified'])

    def test_ambiguous_duplicate_book_or_market_never_selects_one_favorable_price(self):
        event=priced_event();conflict=deepcopy(event['bookmakers'][0]);conflict['markets'][0]['outcomes'][0]['price']=9.9
        event['bookmakers'].append(conflict)
        rows,rejected=odds_observations(receipt(event),SNAPSHOT)
        self.assertFalse(rows);self.assertGreater(rejected,0)
        event=priced_event();m=deepcopy(event['bookmakers'][0]['markets'][0]);m['outcomes'][0]['price']=9.9
        event['bookmakers'][0]['markets'].append(m)
        rows,rejected=odds_observations(receipt(event),SNAPSHOT)
        self.assertFalse(rows);self.assertGreater(rejected,0)
        event=priced_event();event['bookmakers'].append(deepcopy(event['bookmakers'][0]))
        self.assertEqual(len(odds_observations(receipt(event),SNAPSHOT)[0]),1)

    def test_bad_backup_price_siblings_preserve_native_labels_without_freshness_claim(self):
        fake=FakeProvider()
        fixture=receipt(dict(errors=[],response=fake.games),'API_BASKETBALL',
            'https://v1.basketball.api-sports.io/games?league=12&season=2026-2027')
        book=dict(id=1,name='Synthetic',bets=[None,dict(id=2,name='Home/Away',values=[None,dict(value='Home',odd='1.90')])])
        event=dict(league=dict(id=12,season='2026-2027'),game=dict(id=123),bookmakers=[None,book])
        prices=receipt(dict(errors=[],response=[event]),'API_BASKETBALL','https://v1.basketball.api-sports.io/odds?game=123')
        result=inspect_receipt(fixture,prices,SNAPSHOT,league_id=12,season='2026-2027',game_id=123,now=NOW)
        self.assertEqual(len(result['rows']),1);self.assertFalse(result['current_prices_verified'])

    def test_invalid_failure_payload_and_retry_hint_still_cool_down(self):
        for result in (None,[],dict(status='PROVIDER_HTTP_ERROR',retry_after_seconds=None),
                       dict(status='PROVIDER_HTTP_ERROR',retry_after_seconds='broken')):
            getter=Mock(return_value=result)
            access=ProviderAccess({'THE_ODDS_API':SECRET},getter=getter,clock=lambda:NOW)
            first=access.get('THE_ODDS_API','/v4/sports/')
            second=access.get('THE_ODDS_API','/v4/sports/')
            self.assertNotEqual(first['status'],'DOCUMENT_RECEIVED')
            self.assertEqual(second['status'],'PROVIDER_COOLDOWN');getter.assert_called_once()

    def test_http_date_retry_after_is_respected_and_credential_not_exposed(self):
        retry=format_datetime(datetime.fromtimestamp(NOW+900,timezone.utc),usegmt=True)
        error=HTTPError('https://api.the-odds-api.com/v4/sports/',503,'Service unavailable',
            {'Retry-After':retry},io.BytesIO(b'not retained'))
        opener=Mock();opener.open.side_effect=error
        with patch('time.time',return_value=NOW),patch('hybrid_engine.provider_access.build_opener',return_value=opener):
            result=get_document('THE_ODDS_API','https://api.the-odds-api.com/v4/sports/',SECRET,timeout=1)
        self.assertEqual(result['retry_after_seconds'],900)
        self.assertNotIn(SECRET,str(result))
