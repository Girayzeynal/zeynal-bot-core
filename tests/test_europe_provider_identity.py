"""Synthetic provider events plus separately preserved public official receipts.

These tests do not authenticate to The Odds API or deliver Telegram messages.
"""
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.europe_provider_identity import binding_evidence,side_for,RULE
from hybrid_engine.provider_bridge import matches,odds_observations
from hybrid_engine.provider_identity import bind,verify_detail
from tests.test_provider_bridge import SNAPSHOT
from tests.test_team_identity import documents
from tests.test_season_archive_audit import NOW


def rows():
    return [dict(code='BES',name='Besiktas Istanbul',abbreviatedName='Besiktas',
                 editorialName='Besiktas',clubPermanentName='Besiktas Istanbul',
                 clubPermanentAlias='Besiktas Istanbul',city='ISTANBUL',tvCode='BJK',isVirtual=False),
            dict(code='MAD',name='Real Madrid',abbreviatedName='Real Madrid',
                 editorialName='Real',clubPermanentName='Real Madrid',city='Madrid',isVirtual=False)]


def snapshot(league='EUROLEAGUE',*,at=NOW,clubs=None):
    s=deepcopy(SNAPSHOT);s.update(league=league,season='2026/2027',fixture_start_utc=at+7200,
        home=dict(provider_id='BES',official_name='Besiktas Istanbul'),
        away=dict(provider_id='MAD',official_name='Real Madrid'))
    docs=documents(league,at=at,rows=rows() if clubs is None else clubs)
    s['european_team_catalog']=dict(documents=docs,sha256=digest(docs))
    return s


def receipt(document,url,at=NOW):
    return dict(provider='THE_ODDS_API',status='DOCUMENT_RECEIVED',http_status=200,
        source_url=url,document=document,document_sha256=digest(document),observed_at_utc=at,ingested_at_utc=at)


def source_pair(s,*,offset=0,at=NOW):
    sport='basketball_euroleague' if s['league']=='EUROLEAGUE' else 'basketball_eurocup'
    base='https://api.the-odds-api.com/v4/sports/'+sport+'/events'
    iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
    e=dict(id='SYNTHETIC_EVENT_ONLY',sport_key=sport,home_team='Beşiktaş J.K.',away_team='Real Madrid',
           commence_time=iso(s['fixture_start_utc']+offset))
    discovery=receipt([deepcopy(e)],base,at)
    e['bookmakers']=[dict(key='synthetic',title='SYNTHETIC ONLY',last_update=iso(at-1),markets=[
        dict(key='h2h',outcomes=[dict(name=e['home_team'],price=1.9),dict(name=e['away_team'],price=1.9)]),
        dict(key='spreads',outcomes=[dict(name=e['home_team'],point=-3.5,price=1.9),dict(name=e['away_team'],point=3.5,price=1.9)]),
        dict(key='totals',outcomes=[dict(name='Over',point=170.5,price=1.9),dict(name='Under',point=170.5,price=1.9)]),
        dict(key='team_totals',outcomes=[dict(name='Over',description=e['home_team'],point=86.5,price=1.9),
                                       dict(name='Under',description=e['home_team'],point=86.5,price=1.9)])])]
    return discovery,receipt(e,base+'/'+e['id']+'/odds',at)


def dubai_partizan_snapshot():
    official=[
        dict(code='DUB',name='Dubai Basketball',abbreviatedName='Dubai Basketball',
             editorialName='Dubai Basketball',clubPermanentName='Dubai Basketball',
             city='DUBAI',tvCode='DUB',isVirtual=False),
        dict(code='PAR',name='Partizan Mozzart Bet Belgrade',abbreviatedName='Partizan',
             editorialName='Partizan',clubPermanentName='Partizan Mozzart Bet Belgrade',
             city='BELGRADE',tvCode='PAR',isVirtual=False)]
    s=snapshot(clubs=official)
    s['home']=dict(provider_id='DUB',official_name='Dubai Basketball')
    s['away']=dict(provider_id='PAR',official_name='Partizan Mozzart Bet Belgrade')
    return s


def dubai_partizan_receipts(s,*,home='Dubai Basketball',away='KK Partizan NIS',offset=0):
    iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
    base='https://api.the-odds-api.com/v4/sports/basketball_euroleague/events'
    e=dict(id='SYNTHETIC_DUBAI_PAR_ONLY',sport_key='basketball_euroleague',
           home_team=home,away_team=away,commence_time=iso(s['fixture_start_utc']+offset))
    discovery=receipt([deepcopy(e)],base)
    e['bookmakers']=[dict(key='synthetic',title='SYNTHETIC ONLY',
       last_update=iso(NOW-1),markets=[dict(key='totals',last_update=iso(NOW-1),
       outcomes=[dict(name='Over',point=158.5,price=1.91),
                 dict(name='Under',point=158.5,price=1.91)])])]
    return discovery,receipt(e,base+'/'+e['id']+'/odds')


class EuropeanProviderIdentityTests(TestCase):
    def setUp(self):
        timer=patch('time.time',return_value=NOW);timer.start();self.addCleanup(timer.stop)

    def test_legal_name_uses_official_bes_and_bjk_preserves_original_clocks_and_content(self):
        s=snapshot();before=deepcopy(s);d,q=source_pair(s)
        e,b=bind(d,s);self.assertEqual(b['payload']['rule'],RULE)
        self.assertEqual(b['payload']['mode'],'OFFICIAL_TEAM_ALIASES_EXACT_START')
        self.assertEqual(b['payload']['delta_seconds'],0);self.assertEqual(b['payload']['team_identity']['home_team_id'],'BES')
        self.assertFalse(b['payload']['team_identity']['fuzzy_matching']);self.assertEqual(s,before)
        self.assertEqual(e['home_team'],'Beşiktaş J.K.');self.assertEqual(verify_detail(d,q,s),b)

    def test_winner_handicap_total_and_team_total_all_use_same_identity_evidence(self):
        s=snapshot();d,q=source_pair(s);before=deepcopy(q)
        observations,rejected=odds_observations(q,s,discovery=d)
        self.assertEqual(rejected,0);self.assertEqual(len(observations),4)
        self.assertEqual({o['payload']['quotes'][0]['market'] for o in observations},{'WINNER','HOME_HANDICAP','TOTAL','HOME'})
        self.assertTrue(all(o['payload']['calibration_status']=='NOT_CALIBRATED' for o in observations))
        self.assertEqual(q,before)

    def test_exact_2026_dubai_partizan_nis_alias_accepts_native_event_and_quotes(self):
        s=dubai_partizan_snapshot()
        original=deepcopy(s)
        discovery,detail=dubai_partizan_receipts(s)
        self.assertTrue(matches(discovery['document'][0],s))
        self.assertEqual(side_for('KK Partizan NIS',s),'away')
        event,binding=bind(discovery,s)
        self.assertEqual(event['away_team'],'KK Partizan NIS')
        self.assertEqual(binding['payload']['rule'],'EUROPE_EXACT_HISTORIC_PARTIZAN_NIS_PAR_V2')
        self.assertEqual(binding['payload']['delta_seconds'],0)
        self.assertEqual(binding['payload']['team_identity']['historic_label_target'],'EUROLEAGUE_LIVE:PAR')
        self.assertEqual(verify_detail(discovery,detail,s),binding)
        observations,rejected=odds_observations(detail,s,discovery=discovery)
        self.assertEqual(rejected,0)
        self.assertEqual(len(observations),1)
        self.assertEqual(s,original)
        self.assertEqual(observations[0]['payload']['calibration_status'],'NOT_CALIBRATED')

    def test_partizan_historic_alias_refuses_other_spelling_team_id_season_and_clock(self):
        s=dubai_partizan_snapshot()
        for label in ('Partizan NIS','KK Partizan 2026','KK Partizan Mozzart NIS'):
            with self.subTest(label=label):
                d,_=dubai_partizan_receipts(s,away=label)
                self.assertFalse(matches(d['document'][0],s))
        bad=deepcopy(s);bad['away']['provider_id']='BES'
        self.assertFalse(matches(dubai_partizan_receipts(bad)[0]['document'][0],bad))
        old=deepcopy(s);old['season']='2025/2026'
        self.assertFalse(matches(dubai_partizan_receipts(old)[0]['document'][0],old))
        for offset in (1,600,-600):
            d,_=dubai_partizan_receipts(s,offset=offset)
            with self.subTest(offset=offset),self.assertRaises(ValueError):bind(d,s)
        d,_=dubai_partizan_receipts(s,home='KK Partizan NIS',away='Dubai Basketball')
        self.assertFalse(matches(d['document'][0],s))
        d,_=dubai_partizan_receipts(s)
        d['document'].append(deepcopy(d['document'][0]))
        d['document_sha256']=digest(d['document'])
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):bind(d,s)

    def test_existing_official_partizan_name_retains_v1_binding(self):
        s=dubai_partizan_snapshot()
        d,q=dubai_partizan_receipts(s,away='Partizan Mozzart Bet Belgrade')
        e,b=bind(d,s)
        self.assertEqual(b['payload']['rule'],RULE)
        self.assertNotIn('historic_label',b['payload']['team_identity'])
        self.assertEqual(verify_detail(d,q,s),b)

    def test_source_aliases_work_without_general_fuzzy_or_sponsor_guessing(self):
        s=snapshot()
        for label in ('BJK','Beşiktaş','Besiktas Istanbul','Beşiktaş JK'):
            self.assertEqual(side_for(label,s),'home')
        for label in ('Besiktas New Sponsor','Besiktas JKK','Besiktas J.K. Istanbul','Besiktas JK Youth'):
            with self.subTest(label=label),self.assertRaises(ValueError):side_for(label,s)

    def test_legal_alias_requires_bes_id_and_official_bjk_evidence(self):
        for field,value in (('tvCode','NOT_BJK'),('code','OTHER')):
            clubs=rows();clubs[0][field]=value;s=snapshot(clubs=clubs)
            with self.subTest(field=field),self.assertRaises(ValueError):side_for('Beşiktaş J.K.',s)

    def test_ambiguous_official_stem_is_refused(self):
        clubs=rows();clubs[1]['editorialName']='Besiktas';s=snapshot(clubs=clubs)
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):side_for('Beşiktaş J.K.',s)

    def test_other_league_or_season_catalog_cannot_certify_this_fixture(self):
        for league,year in (('EUROCUP',2026),('EUROLEAGUE',2025)):
            s=snapshot();docs=documents(league,year,at=NOW,rows=rows())
            s['european_team_catalog']=dict(documents=docs,sha256=digest(docs))
            with self.subTest(league=league,year=year),self.assertRaises(ValueError):binding_evidence(s)

    def test_wrong_rival_reversed_pair_and_nonzero_start_offsets_refused(self):
        s=snapshot()
        for offset in (1,-600,600,86400):
            d,_=source_pair(s,offset=offset)
            with self.subTest(offset=offset),self.assertRaises(ValueError):bind(d,s)
        for change in ('rival','reversed'):
            d,_=source_pair(s);e=d['document'][0]
            if change=='rival':e['away_team']='Another Club'
            else:e['home_team'],e['away_team']=e['away_team'],e['home_team']
            d['document_sha256']=digest(d['document'])
            with self.subTest(change=change),self.assertRaises(ValueError):bind(d,s)

    def test_duplicate_event_and_changed_detail_id_are_refused(self):
        s=snapshot();d,q=source_pair(s);d['document'].append(deepcopy(d['document'][0]));d['document_sha256']=digest(d['document'])
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):bind(d,s)
        d,q=source_pair(s);q['document']['id']='OTHER';q['document_sha256']=digest(q['document'])
        with self.assertRaisesRegex(ValueError,'IDENTITY_CONFLICT'):verify_detail(d,q,s)

    def test_stale_future_hash_or_target_id_conflict_cannot_enable_alias_matching(self):
        for change in ('stale','future','bundle_pin','body_pin','target_id'):
            s=snapshot();bundle=s['european_team_catalog']
            if change in ('stale','future'):
                for r in bundle['documents'].values():r['observed_at_utc']=r['ingested_at_utc']=NOW+1 if change=='future' else NOW-301
                bundle['sha256']=digest(bundle['documents'])
            elif change=='bundle_pin':bundle['sha256']='0'*64
            elif change=='body_pin':bundle['documents']['clubs']['document']['data'][0]['tvCode']='CHANGED';bundle['sha256']=digest(bundle['documents'])
            else:s['home']['provider_id']='MAD'
            with self.subTest(change=change),self.assertRaises(ValueError):side_for('Beşiktaş J.K.',s)

    def test_without_catalog_legal_alias_not_accepted_but_existing_exact_names_work(self):
        s=snapshot();s.pop('european_team_catalog');d,_=source_pair(s)
        self.assertFalse(matches(d['document'][0],s))
        d['document'][0]['home_team']='Besiktas Istanbul';d['document_sha256']=digest(d['document'])
        self.assertEqual(bind(d,s)[1]['payload']['mode'],'EXACT_SCHEDULE_MATCH')

    def test_tipoff_is_not_relaxed_by_official_alias(self):
        s=snapshot();d,_=source_pair(s)
        with patch('time.time',return_value=s['fixture_start_utc']):
            with self.assertRaises(ValueError):bind(d,s)

    def test_native_official_catalog_supports_alias_but_not_claim_of_authenticated_odds(self):
        path=Path(__file__).resolve().parents[1]/'docs/evidence/europe-provider-alias-phase956-20261117.json.gz'
        packet=json.loads(gzip.decompress(path.read_bytes()))
        self.assertEqual(digest(packet['payload']),packet['sha256']);p=packet['payload']
        self.assertFalse(p['actual_odds_api_authentication_verified']);self.assertFalse(p['actual_telegram_delivery_verified'])
        docs=p['official_documents'];at=max(r['ingested_at_utc'] for r in docs.values())
        with patch('time.time',return_value=at):
            s=snapshot(at=at);s['european_team_catalog']=dict(documents=docs,sha256=digest(docs))
            self.assertEqual(side_for('Beşiktaş J.K.',s),'home')
            self.assertEqual(side_for('Real Madrid',s),'away')
            self.assertEqual(binding_evidence(s)['catalog_sha256'],p['catalog_sha256'])
