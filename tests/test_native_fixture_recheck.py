"""Calendar replay and unchanged strict verifier. No live forecasts or Bot API."""
from copy import deepcopy
from datetime import datetime,timezone
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

from core.team_identity import digest
from hybrid_engine.adaptive_data import native_catalog
from hybrid_engine.adaptive_worker import AdaptiveWorker
from hybrid_engine.data import Abstain
from hybrid_engine.native_fixture_recheck import NativeFixtureRecheck,url_for_day,VERSION
from tests.test_season_archive_audit import nba

ROOT=Path(__file__).resolve().parents[1]


class NativeCalendarReplayTests(TestCase):
    def setUp(self):
        raw=gzip.decompress((ROOT/'docs/evidence/nba-provider-calendar-20261119.json.gz').read_bytes())
        packet=json.loads(raw);self.assertEqual(digest(packet['payload']),packet['sha256'])
        self.packet=packet['payload'];self.now=self.packet['observed_at_utc']
        timer=patch('time.time',return_value=self.now);timer.start();self.addCleanup(timer.stop)
        self.receipts={r['source_url']:r for r in self.packet['receipts']}
        correct=self.receipts[url_for_day('20261119')]
        game=native_catalog(correct,'NBA',2026)['payload']['fixtures'][0]
        self.target=dict(league='NBA',season='2026/2027',fixture_id=game['canonical_id'],
            fixture_start_utc=game['start_ts_utc'],home_team_id=game['home_team_id'],
            away_team_id=game['away_team_id'],provider_fixture_ids=game['provider_fixture_ids'])

    def fetch(self,provider,url):
        self.assertEqual(provider,'ESPN');return deepcopy(self.receipts[url])

    def test_recorded_native_midnight_fixture_missing_from_utc_day_is_verified_on_provider_day(self):
        # Native observation replay at its actual recorded capture boundary,
        # not a newly created historical/prospective forecast.
        with self.assertRaisesRegex(Abstain,'EXACT_CURRENT_NATIVE_FIXTURE_REQUIRED'):
            AdaptiveWorker.verify(SimpleNamespace(transport=self.fetch),self.target)
        fetch=Mock(side_effect=self.fetch);recheck=NativeFixtureRecheck(fetch)
        before=deepcopy(self.receipts)
        result=recheck.verify(self.target)
        fetch.assert_called_once_with('ESPN',url_for_day('20261119'))
        original=self.receipts[url_for_day('20261119')]
        for key,value in original.items():self.assertEqual(result[key],value)
        witness=result['runtime_fixture_recheck']
        self.assertEqual(witness['format'],VERSION)
        self.assertEqual(witness['provider_calendar_day'],'20261119')
        self.assertEqual(witness['validator_utc_day'],'20261120')
        self.assertEqual(witness['target_fixture_id'],self.target['fixture_id'])
        self.assertEqual(witness['policy_sha256'],recheck.policy_sha256)
        self.assertEqual(before,self.receipts)

    def test_changed_team_clock_provider_id_canonical_id_and_season_remain_blocked(self):
        recheck=NativeFixtureRecheck(self.fetch)
        for key,value in [('fixture_id','f'*64),('home_team_id','999'),('away_team_id','999'),
                ('fixture_start_utc',self.target['fixture_start_utc']+60),
                ('provider_fixture_ids',['999999999']),('season','2025/2026')]:
            with self.subTest(key=key),self.assertRaises((Abstain,ValueError)):
                recheck.verify(dict(self.target,**{key:value}))

    def test_mismatched_source_url_or_provider_is_not_relabelled(self):
        for key,value in [('source_url',url_for_day('20261120')),('provider','OTHER')]:
            r=deepcopy(self.receipts[url_for_day('20261119')]);r[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'SOURCE_BINDING_REQUIRED'):
                NativeFixtureRecheck(Mock(return_value=r)).verify(self.target)

    def test_body_tamper_and_stale_future_receipts_are_not_made_fresh(self):
        original=self.receipts[url_for_day('20261119')]
        variants=[]
        bad=deepcopy(original);bad['document']['events']=[];variants.append(bad)
        for observed,ingested in [(self.now-301,self.now-301),(self.now+1,self.now+1)]:
            variants.append(dict(original,observed_at_utc=observed,ingested_at_utc=ingested))
        for bad in variants:
            with self.subTest(clocks=bad.get('observed_at_utc')),self.assertRaises((ValueError,KeyError)):
                NativeFixtureRecheck(Mock(return_value=bad)).verify(self.target)


class SyntheticCalendarGuardsTests(TestCase):
    def setUp(self):
        self.now=int(datetime(2026,11,19,12,tzinfo=timezone.utc).timestamp())
        timer=patch('time.time',side_effect=lambda:self.now);timer.start();self.addCleanup(timer.stop)

    def fixture(self,start='2026-11-20T01:00:00+00:00'):
        event=nba('401123456');event['date']=start;comp=event['competitions'][0];comp['date']=start
        state=dict(state='pre',completed=False,name='STATUS_SCHEDULED')
        event['status']=dict(type=deepcopy(state));comp['status']=dict(type=deepcopy(state))
        for team in comp['competitors']:team['score']='0';team.pop('linescores',None)
        receipt=dict(provider='ESPN',source_url=url_for_day('20261119'),status='DOCUMENT_RECEIVED',
            http_status=200,document=dict(events=[event]),observed_at_utc=self.now-1,ingested_at_utc=self.now)
        receipt['document_sha256']=digest(receipt['document'])
        g=native_catalog(receipt,'NBA',2026)['payload']['fixtures'][0]
        target=dict(league='NBA',season='2026/2027',fixture_id=g['canonical_id'],fixture_start_utc=g['start_ts_utc'],
            home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],provider_fixture_ids=g['provider_fixture_ids'])
        return target,receipt

    def test_scheduled_zero_score_and_last_five_minutes_are_still_required(self):
        target,receipt=self.fixture();recheck=NativeFixtureRecheck(Mock(return_value=receipt))
        for offset in (300,299,0,-1):
            self.now=target['fixture_start_utc']-offset
            r=deepcopy(receipt);r.update(observed_at_utc=self.now-1,ingested_at_utc=self.now)
            recheck.transport=Mock(return_value=r)
            with self.subTest(offset=offset),self.assertRaisesRegex(Abstain,'SAFE_WINDOW_CLOSED'):
                recheck.verify(target)

    def test_changed_status_or_nonzero_prematch_score_cannot_pass(self):
        target,receipt=self.fixture()
        for field in ('score','status'):
            r=deepcopy(receipt);event=r['document']['events'][0]
            if field=='score':event['competitions'][0]['competitors'][0]['score']='1'
            else:
                for status in (event['status']['type'],event['competitions'][0]['status']['type']):status['name']='STATUS_IN_PROGRESS'
            r['document_sha256']=digest(r['document'])
            with self.subTest(field=field),self.assertRaises(Abstain):
                NativeFixtureRecheck(Mock(return_value=r)).verify(target)

    def test_same_calendar_day_and_dst_use_actual_provider_url_without_changing_utc_start(self):
        for start,day in [('2026-11-19T23:00:00+00:00','20261119'),
                ('2026-07-20T04:30:00+00:00','20260720'),('2026-07-20T00:30:00+00:00','20260719')]:
            self.now=int(datetime.fromisoformat(start).timestamp())-3600
            target,receipt=self.fixture(start);receipt['source_url']=url_for_day(day)
            fetch=Mock(return_value=receipt);result=NativeFixtureRecheck(fetch).verify(target)
            fetch.assert_called_once_with('ESPN',url_for_day(day))
            self.assertEqual(result['runtime_fixture_recheck']['target_start_utc'],target['fixture_start_utc'])

    def test_european_verification_is_delegated_unchanged(self):
        target=dict(league='EuroCup',season='2026/2027',fixture_start_utc=self.now+3600)
        transport=Mock();recheck=NativeFixtureRecheck(transport)
        receipt=object();verify=Mock(return_value=receipt);recheck._verify=verify
        self.assertIs(recheck.verify(target),receipt)
        self.assertIs(verify.call_args.args[0].transport,transport)
        self.assertIs(verify.call_args.args[1],target)

    def test_real_v2_v3_capture_paths_archive_future_score_without_calibration_or_duplicate(self):
        # Synthetic history/transport; exercises the actual fit, native validator,
        # registry and primary capture paths. Not a device or live forecast claim.
        from hybrid_engine import nba_dynamic
        from hybrid_engine.adaptive_research import AdaptiveResearch
        from hybrid_engine.issue90_research import Research
        from tests.test_adaptive_research import cohort

        target,receipt=self.fixture();rows=cohort(85)
        delta=target['fixture_start_utc']-rows[71][0]['fixture_start_utc']
        for versions in rows:
            r=versions[0];r['season']=target['season'];r['box']['season']=target['season']
            for obj in (r,r['box'],r['box']['source']):
                for key in ('fixture_start_utc','observed_at_utc','ingested_at_utc'):
                    if key in obj:obj[key]+=delta
        original=dict(model_digest='a'*64,prediction=dict(winner=[.6,.1,.3]))
        original_pin=digest(original);fetch=Mock(return_value=receipt)
        recheck=NativeFixtureRecheck(fetch)
        with TemporaryDirectory() as folder:
            root=Path(folder);v2=AdaptiveResearch(root/'v2');plan2=v2.plan(create=True)
            artifact,_=v2.fit(rows,'NBA',target['season'])
            p2,new=v2.capture(target,original_pin,artifact,recheck.verify);self.assertTrue(new)
            worker=SimpleNamespace(verify=recheck.verify)
            v3=Research(root/'v3',worker);plan3=v3.plan();v3.admit(dict(target=target,original=original_pin),plan3)
            model=nba_dynamic.fit(rows,cutoff_utc=self.now)
            forecast=nba_dynamic.predict(model,target,cutoff_utc=self.now)
            case=dict(target=target,original=original_pin,snapshot=original,
                frozen=dict(status='FORECAST_CREATED',prediction=forecast.summary()),code='NBA')
            p3,new=v3.capture(case,model,plan3);self.assertTrue(new)
            self.assertEqual(p3['shadow_status'],'ABSTAIN_CALIBRATION_TRAINING_INSUFFICIENT')
            self.assertIsNone(p3['shadow']);self.assertIsNone(p3['actual'])
            refs=[ref for ref in p3['assets'] if ref['file'].startswith('current-fixture-')]
            self.assertEqual(len(refs),1)
            saved=v3.registry.read_asset(refs[0]);self.assertEqual(saved, recheck.verify(target))
            self.assertEqual(saved['source_url'],url_for_day('20261119'))
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.now+=1
            with patch.object(recheck,'verify',side_effect=AssertionError('NO_NEW_QUERY')):
                q2,new=v2.capture(target,original_pin,artifact,recheck.verify);self.assertFalse(new)
                restarted=Research(root/'v3',worker)
                worker.verify=recheck.verify
                q3,new=restarted.capture(case,model,restarted.plan());self.assertFalse(new)
                self.now=target['fixture_start_utc']+1
                with self.assertRaisesRegex(Abstain,'NO_LATE_ADMISSION'):
                    v2.capture(target,original_pin,artifact,recheck.verify)
                late,new=restarted.capture(case,model,restarted.plan())
                self.assertFalse(new);self.assertEqual(p3,late)
            self.assertEqual(p2,q2);self.assertEqual(p3,q3)
            self.assertEqual(plan2,v2.plan());self.assertEqual(plan3,restarted.plan())
            self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
