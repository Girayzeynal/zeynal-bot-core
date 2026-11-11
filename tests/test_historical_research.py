"""Synthetic clocks/labels; these are not real prospective performance samples."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch

from core.team_identity import digest
from historical_research import historical_rows,feature_cut,simulate_history,metrics_report,chronological_evaluation
from research_record_store import ResearchRecordStore,HISTORICAL_DATA,BACKTEST_SIMULATION,LIVE_PREMATCH_PREDICTION
from season_archive_inventory import archive_catalog,validate_catalog
from season_history_discovery import collect_season_history,nba_calendar_days,publish_history,main
from tests.test_season_archive_audit import nba,NOW


def cohort(n=10,late=False):
    bundles=[]
    for i in range(n):
        event=nba(str(401000000+i));event['competitions'][0]['id']=event['id']
        start=int(datetime(2026,10,1+i*2,18,tzinfo=timezone.utc).timestamp())
        event['date']=datetime.fromtimestamp(start,timezone.utc).isoformat()
        at=NOW-1 if late else start+3*3600
        b=archive_catalog({'events':[event]},provider='ESPN',observed_at_utc=at,ingested_at_utc=at)
        bundles.append((b,b['sha256']))
    return bundles


def seed(events=None):
    return dict(leagues=[dict(slug='nba',season={'year':2027},calendarType='day',calendarIsWhitelist=True,
        calendar=['2026-10-01T07:00Z','2026-10-03T07:00Z','2027-01-01T08:00Z'])],events=[nba()] if events is None else events)


def receipt(provider,url,doc):
    return dict(provider=provider,source_url=url,http_status=200,status='DOCUMENT_RECEIVED',document=doc,
        document_sha256=digest(doc),observed_at_utc=NOW-1,ingested_at_utc=NOW-1)


class HistoricalResearchTests(TestCase):
    def setUp(self):
        clock=patch('time.time',return_value=NOW);clock.start();self.addCleanup(clock.stop)

    def test_strict_replay_has_prior_source_evidence_and_never_live_type(self):
        r=simulate_history(cohort(),min_games=2)
        evaluated=[s for s in r['runs'] if s['prediction'] is not None]
        self.assertEqual(len(evaluated),8)
        for s in evaluated:
            self.assertEqual(s['record_type'],BACKTEST_SIMULATION)
            self.assertEqual(s['evaluation_class'],'PIT_PROVEN_BACKTEST')
            self.assertTrue(all(p['ingested_at_utc']<=s['cutoff_utc'] for p in s['features']['source_inputs']))
        self.assertEqual(r['prospective_predictions_created'],0)

    def test_late_archives_are_kept_but_strictly_abstain_not_discarded(self):
        r=simulate_history(cohort(late=True),min_games=2)
        self.assertEqual(r['historical_games'],10)
        self.assertTrue(all(s['evaluation_class']=='ABSTAIN' for s in r['runs']))
        self.assertEqual(metrics_report(r['runs'])['groups'],[])
        research=simulate_history(cohort(late=True),min_games=2,assume_availability=True)
        self.assertEqual(sum(s['prediction'] is not None for s in research['runs']),8)
        self.assertTrue(all(s['evaluation_class']=='AVAILABILITY_ASSUMED_RESEARCH' for s in research['runs'] if s['prediction']))

    def test_target_label_hidden_from_predictor_and_future_result_cannot_change_earlier_prediction(self):
        from historical_research import reference_predict
        bundles=cohort();seen=[]
        def spy(features):
            seen.append(deepcopy(features))
            self.assertNotIn('actual',features);self.assertNotIn('final_scores',features)
            return reference_predict(features)
        with patch('historical_research.reference_predict',side_effect=spy):
            original=simulate_history(bundles,min_games=2)
        changed=deepcopy(bundles);b=changed[-1][0]
        event=b['payload']['raw']['events'][0];event['competitions'][0]['competitors'][0]['score']='116'
        event['competitions'][0]['competitors'][0]['linescores'][0]['value']+=1
        changed[-1]=(archive_catalog(b['payload']['raw'],provider='ESPN',observed_at_utc=b['payload']['observed_at_utc'],ingested_at_utc=b['payload']['ingested_at_utc']),None)
        changed[-1]=(changed[-1][0],changed[-1][0]['sha256'])
        altered=simulate_history(changed,min_games=2)
        self.assertTrue(seen)
        self.assertEqual([s['prediction'] for s in original['runs']],[s['prediction'] for s in altered['runs']])

    def test_duplicate_sources_and_versions_do_not_inflate_matches_or_erase_old_availability(self):
        old=cohort();late=cohort(late=True)
        a=simulate_history(old,min_games=2);b=simulate_history(old+late+old,min_games=2)
        self.assertEqual(a,b)

    def test_per_team_margin_bias_periods_and_probability_metrics(self):
        runs=simulate_history(cohort(),min_games=2)['runs']
        for s in runs:
            if s['prediction']:
                p=s['prediction']
                self.assertAlmostEqual(sum(p['quarters']['home']),p['home'])
                self.assertAlmostEqual(sum(p['halves']['away']),p['away'])
                p['home']+=2;p['away']-=1;p['total']=p['home']+p['away'];p['margin']=p['home']-p['away']
                p['quarters']['home'][0]+=2;p['quarters']['away'][0]-=1
        r=metrics_report(runs);g=r['groups'][0]
        self.assertEqual(g['metrics']['n_games'],8)
        self.assertEqual(g['metrics']['margin_mae'],3)
        self.assertEqual(g['metrics']['home_mae'],2)
        self.assertEqual(g['metrics']['away_mae'],1)
        self.assertIsNone(g['metrics']['home_win_brier'])
        self.assertIsNone(g['metrics']['home_win_log_loss'])
        self.assertEqual(len(g['period_metrics']),6)
        for s in runs:
            if s['prediction']:
                p=s['prediction']
                p['home_win_probability']=0.8
        g=metrics_report(runs)['groups'][0]
        self.assertAlmostEqual(g['metrics']['home_win_brier'],0.04)
        self.assertAlmostEqual(g['metrics']['home_win_log_loss'],0.2231435513142097)
        self.assertEqual(sum(b['n'] for b in g['calibration_curve']),8)

    def test_live_records_rejected_from_simulation_metrics_and_model_versions_not_pooled(self):
        runs=[r for r in simulate_history(cohort(),min_games=2)['runs'] if r['prediction']]
        other=deepcopy(runs[0]);other['model_version']='OTHER_MODEL';runs.append(other)
        self.assertEqual(len(metrics_report(runs)['groups']),2)
        mixed=deepcopy(other);mixed['record_type']=LIVE_PREMATCH_PREDICTION
        with self.assertRaisesRegex(ValueError,'ONLY_SIMULATION'):metrics_report([mixed])
        with self.assertRaisesRegex(ValueError,'DUPLICATE_SIMULATION'):metrics_report([runs[0],runs[0]])

    def test_chronological_roles_and_same_time_boundary_do_not_overlap(self):
        runs=simulate_history(cohort(),min_games=2)['runs']
        report=chronological_evaluation(runs,train_end_utc=runs[4]['fixture_start_utc'],
            validation_end_utc=runs[7]['fixture_start_utc'],test_end_utc=NOW,minimum_train=2,minimum_evaluation=2)
        self.assertEqual([report['periods'][s]['targets'] for s in ('TRAIN','VALIDATION','TEST')],[4,3,3])
        self.assertTrue(report['adequacy'][0]['threshold_met'])
        self.assertFalse(report['automatic_model_update_permitted'])
        assumed=simulate_history(cohort(late=True),min_games=2,assume_availability=True)['runs']
        report=chronological_evaluation(assumed,train_end_utc=runs[4]['fixture_start_utc'],validation_end_utc=runs[7]['fixture_start_utc'],test_end_utc=NOW,minimum_train=2,minimum_evaluation=2)
        self.assertFalse(report['adequacy'][0]['threshold_met'])

    def test_future_or_unordered_partition_and_invalid_configuration_refused(self):
        for args in [(20,10,30),(10,20,NOW+1)]:
            with self.assertRaises(ValueError):chronological_evaluation([],train_end_utc=args[0],validation_end_utc=args[1],test_end_utc=args[2])
        with self.assertRaises(ValueError):simulate_history([],min_games=True)

    def test_early_observation_but_late_ingestion_is_not_available_at_cutoff(self):
        bundles=[]
        for b,pin in cohort():
            p=b['payload'];new=archive_catalog(p['raw'],provider='ESPN',observed_at_utc=p['observed_at_utc'],ingested_at_utc=NOW-1)
            bundles.append((new,new['sha256']))
        self.assertTrue(all(r['prediction'] is None for r in simulate_history(bundles,min_games=2)['runs']))

    def test_native_team_stats_preserved_but_incomplete_possessions_never_become_pace(self):
        b,pin=cohort(1)[0];p=b['payload'];event=p['raw']['events'][0]
        event['competitions'][0]['competitors'][0]['statistics']=[dict(name='fieldGoalsAttempted',displayValue='95'),dict(name='points',displayValue='115')]
        b=archive_catalog(p['raw'],provider='ESPN',observed_at_utc=p['observed_at_utc'],ingested_at_utc=p['ingested_at_utc'])
        row=historical_rows([(b,b['sha256'])])[0][0]
        self.assertEqual(row['team_statistics']['teams']['home']['fieldGoalsAttempted'],95)
        self.assertEqual(row['team_statistics']['scope'],'FINAL_WITH_OT')
        self.assertIsNone(row['pace']);self.assertIsNone(row['efficiency'])
        p=b['payload'];p['raw']['events'][0]['competitions'][0]['competitors'][0]['statistics'][1]['displayValue']='999'
        b=archive_catalog(p['raw'],provider='ESPN',observed_at_utc=p['observed_at_utc'],ingested_at_utc=p['ingested_at_utc'])
        row=historical_rows([(b,b['sha256'])])[0][0]
        self.assertIsNone(row['team_statistics'])
        self.assertEqual(row['team_statistics_status'],'STATISTICS_INVALID_OR_CONFLICTING')

    def test_assumed_and_proven_reports_are_separate_and_overtime_is_not_a_regulation_label(self):
        proven=simulate_history(cohort(),min_games=2)['runs']
        assumed=simulate_history(cohort(late=True),min_games=2,assume_availability=True)['runs']
        self.assertEqual(len(metrics_report(proven+assumed)['groups']),2)
        b,pin=cohort(1)[0];g=b['payload']['raw']['events'][0]
        for team,extra in zip(g['competitions'][0]['competitors'],[12,9]):
            team['linescores']=[dict(value=25) for _ in range(4)]+[dict(value=extra)]
            team['score']=str(100+extra)
        p=b['payload'];ot=archive_catalog(p['raw'],provider='ESPN',observed_at_utc=p['observed_at_utc'],ingested_at_utc=p['ingested_at_utc'])
        r=simulate_history([(ot,ot['sha256'])],min_games=1)['runs'][0]
        self.assertEqual(r['actual'],[100,100])
        self.assertEqual(ot['payload']['fixtures'][0]['final_scores'],[112,109])


class ResearchStoreTests(TestCase):
    def setUp(self):
        clock=patch('time.time',return_value=NOW);clock.start();self.addCleanup(clock.stop)
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'research.sqlite';self.store=ResearchRecordStore(self.path)

    def test_three_namespaces_immutable_idempotent_and_no_production_path(self):
        rows=historical_rows(cohort(1));row=rows[0][0]
        self.assertTrue(self.store.append(HISTORICAL_DATA,'one',row))
        self.assertFalse(self.store.append(HISTORICAL_DATA,'one',row))
        self.assertEqual(len(self.store.read(HISTORICAL_DATA)),1)
        self.assertEqual(self.store.read(BACKTEST_SIMULATION),[])
        self.assertEqual(self.store.read(LIVE_PREMATCH_PREDICTION),[])
        changed=deepcopy(row);changed['final_scores']=[116,109]
        with self.assertRaisesRegex(ValueError,'CONFLICT'):self.store.append(HISTORICAL_DATA,'one',changed)
        with self.assertRaisesRegex(ValueError,'ISOLATED'):ResearchRecordStore('/data/prediction_ledger.sqlite')
        with sqlite3.connect(self.path) as db:
            for sql in ['UPDATE research_records SET sha256="changed"','DELETE FROM research_records']:
                with self.assertRaisesRegex(sqlite3.IntegrityError,'IMMUTABLE'):db.execute(sql)

    def test_historical_simulation_cannot_be_backdated_into_live_namespace(self):
        run=simulate_history(cohort(),min_games=2)['runs'][-1]
        with self.assertRaisesRegex(ValueError,'TYPE_BINDING'):self.store.append(LIVE_PREMATCH_PREDICTION,'fake',run)
        run['record_type']=LIVE_PREMATCH_PREDICTION;run['evaluation_class']='LIVE_RECORDED';run['actual']=None
        with self.assertRaisesRegex(ValueError,'AFTER_CUTOFF_OR_TIPOFF'):self.store.append(LIVE_PREMATCH_PREDICTION,'fake',run)
        self.assertEqual(self.store.read(LIVE_PREMATCH_PREDICTION),[])

    def test_concurrent_retries_insert_exactly_one_immutable_record(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier=Barrier(4);row=historical_rows(cohort(1))[0][0]
        def insert(_):
            barrier.wait(timeout=3)
            return self.store.append(HISTORICAL_DATA,'same-retry',row)
        with ThreadPoolExecutor(max_workers=4) as pool:created=list(pool.map(insert,range(4)))
        self.assertEqual(sum(created),1)
        self.assertEqual(len(self.store.read(HISTORICAL_DATA)),1)

    def test_only_actual_future_cutoff_and_observed_inputs_allow_live_test_record(self):
        p=dict(record_type=LIVE_PREMATCH_PREDICTION,league='NBA',season='2026/2027',fixture_id='SYNTHETIC_ONLY',
            fixture_start_utc=NOW+100,cutoff_utc=NOW+1,model_version='TEST',evaluation_class='LIVE_RECORDED',
            prediction={'home':100,'away':90},
            actual=None,input_clocks=[dict(observed_at_utc=NOW-2,ingested_at_utc=NOW-1)])
        self.assertTrue(self.store.append(LIVE_PREMATCH_PREDICTION,'synthetic',p))
        self.assertEqual(self.store.read(HISTORICAL_DATA),[])
        p['input_clocks'][0]['ingested_at_utc']=NOW+1
        with self.assertRaisesRegex(ValueError,'SOURCE_NOT_AVAILABLE'):self.store.append(LIVE_PREMATCH_PREDICTION,'other',p)

    def test_sql_namespace_constraint_and_foreign_ledger_and_symlink_refused(self):
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT INTO research_records VALUES(?,?,?,?,?)',(LIVE_PREMATCH_PREDICTION,'x',NOW,json.dumps({'record_type':BACKTEST_SIMULATION}),'x'))
        foreign=Path(self.tmp.name)/'foreign.sqlite'
        with sqlite3.connect(foreign) as db:db.execute('CREATE TABLE predictions(x)')
        with self.assertRaisesRegex(ValueError,'FOREIGN'):ResearchRecordStore(foreign)
        link=Path(self.tmp.name)/'link.sqlite';link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError,'ISOLATED'):ResearchRecordStore(link)


class HistoryDiscoveryTests(TestCase):
    def setUp(self):
        clock=patch('time.time',return_value=NOW);clock.start();self.addCleanup(clock.stop)

    def test_calendar_discovers_all_past_days_not_sample_games_and_rejects_wrong_year(self):
        self.assertEqual(nba_calendar_days(seed(),2026,NOW),['20261001','20261003'])
        wrong=seed();wrong['leagues'][0]['season']['year']=2026
        with self.assertRaisesRegex(ValueError,'NOT_VERIFIED'):nba_calendar_days(wrong,2026,NOW)
        wrong=seed();wrong['leagues'][0]['calendar'][0]='2026-06-01T07:00Z'
        with self.assertRaisesRegex(ValueError,'OUTSIDE_SEASON'):nba_calendar_days(wrong,2026,NOW)

    def test_default_dry_run_and_403_are_unknown_not_empty_season(self):
        fetch=Mock(side_effect=AssertionError('NO_NETWORK'))
        self.assertEqual(collect_season_history(fetcher=fetch)['network_requests'],0);fetch.assert_not_called()
        fetch=Mock(return_value=dict(status='SOURCE_ACCESS_DENIED',http_status=403))
        p=collect_season_history(live=True,fetcher=fetch)['payload']
        self.assertEqual(fetch.call_count,2)
        self.assertIsNone(p['leagues']['NBA']['known_completed_games'])
        self.assertFalse(p['leagues']['NBA']['provider_calendar_scan_complete'])

    def test_preseason_filter_preserves_native_bytes_and_old_catalog_format(self):
        pre=nba('401000124');pre['season']['type']=1
        raw={'events':[nba(),pre]}
        b=archive_catalog(raw,provider='ESPN',observed_at_utc=NOW-1,ingested_at_utc=NOW,regular_season_filter=True)
        self.assertEqual(b['payload']['completed_fixtures'],1)
        self.assertEqual(b['payload']['excluded_non_regular_ids'],['401000124'])
        self.assertEqual(b['payload']['raw'],raw)
        self.assertEqual(validate_catalog(b,trusted_sha256=b['sha256']),b['payload'])
        with self.assertRaises(ValueError):archive_catalog(raw,provider='ESPN',observed_at_utc=NOW-1,ingested_at_utc=NOW)

    def test_calendar_collection_checks_every_day_and_preserves_errors(self):
        from tests.test_season_archive_audit import euro
        calls=[]
        def fetch(provider,url):
            calls.append(url)
            if provider=='EUROLEAGUE_LIVE':return receipt(provider,url,dict(data=[euro()],total=1))
            if '20261003' in url:return dict(status='SOURCE_RATE_LIMITED',http_status=429)
            event=nba();event['date']='2026-10-01T18:00:00Z'
            return receipt(provider,url,seed([event]))
        r=collect_season_history(live=True,seed_date='20261001',fetcher=fetch)['payload']
        self.assertEqual(len(calls),3)
        self.assertEqual(r['leagues']['NBA']['known_completed_games'],1)
        self.assertFalse(r['leagues']['NBA']['provider_calendar_scan_complete'])
        self.assertEqual(r['leagues']['NBA']['failed_documents'],1)

    def test_old_euroleague_postseason_remains_in_native_archive_but_not_regular_season_metrics(self):
        from tests.test_season_archive_audit import euro
        regular=euro();playoff=euro();playoff.update(identifier='E2026_2',gameCode=2);playoff['phaseType']['code']='PO'
        raw=dict(data=[regular,playoff],total=2)
        b=archive_catalog(raw,provider='EUROLEAGUE_LIVE',regular_season_filter=True,observed_at_utc=NOW-1,ingested_at_utc=NOW)
        self.assertEqual(b['payload']['completed_fixtures'],1)
        self.assertEqual(b['payload']['excluded_non_regular_ids'],['E2026_2'])
        self.assertEqual(b['payload']['raw'],raw)
        self.assertEqual(validate_catalog(b,trusted_sha256=b['sha256']),b['payload'])

    def test_atomic_local_publication_idempotent_and_derived_count_tampering_refused(self):
        b=collect_season_history(live=True,fetcher=Mock(return_value=dict(status='SOURCE_ACCESS_DENIED')))
        with TemporaryDirectory() as tmp:
            self.assertTrue(publish_history(tmp,b)['created'])
            self.assertFalse(publish_history(tmp,b)['created'])
            self.assertEqual(len(list(Path(tmp).glob('*.json'))),1)
            wrong=deepcopy(b);wrong['payload']['leagues']['NBA']['known_completed_games']=1;wrong['sha256']=digest(wrong['payload'])
            with self.assertRaisesRegex(ValueError,'CENSUS'):publish_history(tmp,wrong)
            wrong=deepcopy(b);wrong['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'PIN_MISMATCH'):publish_history(tmp,wrong)
        with self.assertRaisesRegex(ValueError,'LOCAL_EXISTING'):publish_history('/data',b)

    def test_cli_requires_archive_destination_before_network(self):
        from contextlib import redirect_stdout
        import io
        with patch('season_history_discovery.collect_season_history',side_effect=AssertionError('NO_NETWORK')):
            with redirect_stdout(io.StringIO()):self.assertEqual(main(['--live']),2)
        b=collect_season_history(live=True,fetcher=Mock(return_value=dict(status='SOURCE_ACCESS_DENIED')))
        with TemporaryDirectory() as tmp,patch('season_history_discovery.collect_season_history',return_value=b):
            with redirect_stdout(io.StringIO()):self.assertEqual(main(['--live','--output-dir',tmp]),1)

    def test_failed_atomic_publication_never_leaves_a_complete_archive(self):
        b=collect_season_history(live=True,fetcher=Mock(return_value=dict(status='SOURCE_ACCESS_DENIED')))
        with TemporaryDirectory() as tmp:
            with patch('season_history_discovery.os.link',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):publish_history(tmp,b)
            self.assertEqual(list(Path(tmp).iterdir()),[])
