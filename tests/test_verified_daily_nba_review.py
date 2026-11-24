"""Read-only day audit: old predictions never become new, and no result leakage."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from hybrid_engine.verified_daily_nba_review import audit, describe, proof, V1, ISTANBUL
from ledger_reports import LedgerReports
from tests.test_ledger_reports import fixture
from tests.test_season_archive_audit import START


def row(fixture_id,home,away,actual_home,actual_away,*,day_utc=None,model=V1):
    tip=day_utc or int(datetime(2026,11,24,1,tzinfo=timezone.utc).timestamp())
    return dict(league='NBA',season='2026/2027',fixture_id=fixture_id,
        model_version=model,model_digest='d'*64,
        snapshot_sha256=str(fixture_id).zfill(64),
        fixture_start_utc=tip,prediction_generated_at_utc=tip-1200,
        created_utc=tip-1150,first_archived_at_utc=tip-1130,
        parameter_fit_cutoff_utc=tip-2400,
        label_available_utc=tip+1000,
        home='Home',away='Away',
        prediction=[home,away],
        actual=[actual_home,actual_away],
        actual_periods=dict(home=[actual_home//4]*3+[actual_home-3*(actual_home//4)],
                            away=[actual_away//4]*3+[actual_away-3*(actual_away//4)]),
        final_with_ot=[actual_home,actual_away],predicted_quarters=None,
        intervals=None,winner=None)


class ImmutableDailyNBAReviewTests(TestCase):
    def test_ten_reported_v1_scores_reproduce_exact_daily_mae_no_refit(self):
        # Numeric values copied from the *already settled* original V1 ledger;
        # this synthetic test does not pretend the 10 actual source receipts were
        # downloaded in CI or reconstruct their real quarter breakdown.
        pairs=[
            (115.91042133154735,123.03208062092172,122,108),
            (107.98244233703848,112.26296231704285,125,120),
            (105.31213576776898,113.12717698620138,111,117),
            (115.92449651870324,118.01486608469722,109,109),
            (118.57914059624419,109.02790089868176,111,116),
            (111.07102980318497,114.3738899568929,111,128),
            (107.9737789941841,118.58424360086579,107,123),
            (119.07705240465657,108.52177468825359,109,94),
            (116.67883077927416,107.1904260376266,116,104),
            (116.73083639901405,107.05391831891245,142,116)]
        original=[row(str(i),*values) for i,values in enumerate(pairs)]
        input_copy=deepcopy(original)
        result=audit(dict(status='VERIFIED_LIVE_REPORT',forecasts=original),'2026-11-24')
        self.assertEqual(original,input_copy)
        self.assertEqual(result['selected_forecasts'],10)
        self.assertEqual(result['clock_verified_rows'],10)
        self.assertEqual(len(result['cohorts']),1)
        m=result['cohorts'][0]['summary']
        self.assertEqual(m['n'],10)
        self.assertAlmostEqual(m['total_mae'],13.948457547950046,places=9)
        self.assertAlmostEqual(m['team_score_mae'],8.38487743068902,places=9)
        self.assertAlmostEqual(m['total_bias_forecast_minus_actual'],-3.1570595558287664,places=9)
        self.assertEqual(m['winner_direction'],dict(correct=6,n=9,excluded_regulation_ties=1))
        self.assertEqual(result['cases'][3]['actual_regulation_total'],218)

    def test_missing_or_late_clock_excluded_not_backdated(self):
        r=row('A',110.,112.,100,115)
        for field,value in (('prediction_generated_at_utc',None),
            ('created_utc',r['fixture_start_utc']+1),
            ('first_archived_at_utc',r['fixture_start_utc']),
            ('parameter_fit_cutoff_utc',r['fixture_start_utc'])):
            altered=deepcopy(r);altered[field]=value
            result=audit(dict(status='VERIFIED_LIVE_REPORT',forecasts=[altered]),'2026-11-24')
            self.assertEqual(result['clock_verified_rows'],0)
            self.assertEqual(len(result['excluded']),1)
        self.assertEqual(proof(r),None)
        self.assertTrue(audit(dict(status='VERIFIED_LIVE_REPORT',forecasts=[r]),'2026-11-24')
                        ['cases'][0]['meets_current_five_minute_boundary'])

    def test_kickoff_timezone_filters_only_turkey_date(self):
        start=int(datetime(2026,11,23,22,30,tzinfo=timezone.utc).timestamp())
        self.assertEqual(datetime.fromtimestamp(start,ISTANBUL).date().isoformat(),'2026-11-24')
        result=audit(dict(status='VERIFIED_LIVE_REPORT',
             forecasts=[row('A',100.,100.,99,99,day_utc=start)]),'2026-11-24')
        self.assertEqual(result['unique_fixtures'],1)
        self.assertEqual(audit(dict(status='VERIFIED_LIVE_REPORT',
             forecasts=[row('A',100.,100.,99,99,day_utc=start)]),'2026-11-23')
             ['selected_forecasts'],0)

    def test_overtime_separate_from_regulation_and_does_not_double_count(self):
        r=row('A',115.,118.,109,109)
        r['final_with_ot']=[119,123]
        report=audit(dict(status='VERIFIED_LIVE_REPORT',forecasts=[r]),'2026-11-24')
        self.assertEqual(report['cases'][0]['actual_regulation_total'],218)
        self.assertEqual(report['cases'][0]['final_including_overtime'],[119,123])
        self.assertEqual(report['cohorts'][0]['summary']['winner_direction']['n'],0)
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):
            audit(dict(status='VERIFIED_LIVE_REPORT',forecasts=[r,r]),'2026-11-24')

    def test_separate_model_versions_not_pooled(self):
        a=row('A',100,100,111,112)
        b=row('A',110,115,111,112,model='RESEARCH_V3')
        rpt=dict(status='VERIFIED_LIVE_REPORT',forecasts=[a,b])
        first=audit(rpt,'2026-11-24')
        later=audit(rpt,'2026-11-24',model_version='RESEARCH_V3')
        self.assertEqual(first['cohorts'][0]['summary']['n'],1)
        self.assertEqual(later['cohorts'][0]['summary']['n'],1)

    def test_missing_archive_has_no_fake_success(self):
        r=audit(dict(status='ARCHIVE_UNAVAILABLE',forecasts=[]),'2026-11-24')
        self.assertEqual(r['status'],'UNAVAILABLE_NO_ACCURACY_CLAIM')
        self.assertEqual(r['cohorts'],[])
        self.assertEqual(r['cases'],[])

    def test_reading_actual_verified_sqlite_never_changes_it(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'existing.sqlite'
            fixture(p,settled=True)
            before=hashlib.sha256(p.read_bytes()).hexdigest()
            recorded=LedgerReports(p).read('NBA')
            # The pre-existing generic fixture doesn't carry a generated clock.
            # It must be *excluded* rather than certified retroactively.
            result=audit(recorded,datetime.fromtimestamp(START,ISTANBUL).date().isoformat(),
                         model_version='SYNTHETIC_V0')
            self.assertEqual(result['clock_verified_rows'],0)
            self.assertEqual(result['excluded'][0]['reason'],'PREMATCH_CLOCK_MISSING')
            self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())

    def test_absent_simulation_evidence_is_not_a_confidence_claim(self):
        r=row('B',100,110,107,112)
        result=audit(dict(status='VERIFIED_LIVE_REPORT',forecasts=[r]),'2026-11-24')
        period=result['cohorts'][0]['summary']['period_simulation']
        self.assertIsNone(period['average_off_diagonal_quarter_correlation'])
        self.assertFalse(period['high_path_dependence'])
        self.assertIsNone(result['cohorts'][0]['summary']['confidence_index'])
