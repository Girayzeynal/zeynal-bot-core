"""Source replay, canonical identity, PIT clocks and explicit research scope."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import faz40_archive as a
from prediction_inputs import digest
from tests import test_faz32 as nba
from tests import test_euroleague_live as euro

NOW=1793944800


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.clock=NOW-20
        self.timer=patch('time.time',side_effect=lambda:self.clock);self.timer.start();self.addCleanup(self.timer.stop)

    def seal(self,raw=None,league='NBA',**changes):
        raw=raw if raw is not None else nba.summary(900010001,NOW-7200)
        teams={'NBA':['19','2'],'EUROLEAGUE':['PAM','PAN'],'EUROCUP':['JLB','WRO']}
        if league!='NBA':teams[league]=[raw[side]['club']['code'] for side in ('local','road')]
        args=dict(league=league,season_end_year=2027,source_observed_utc=NOW-100,
                  ingested_utc=NOW-50,team_ids=teams[league],usage='SYNTHETIC_TEST')
        args.update(changes)
        return a.seal_game(raw,**args)

    def select(self,rows,**changes):
        self.clock=NOW
        args=dict(league='NBA',season_end_year=2027,cutoff_utc=NOW);args.update(changes)
        return a.select_games(rows,**args)

    def test_nba_facts_replay_and_separate_regulation_final_scope(self):
        r=self.seal();p=a.replay_game(r);f=p['facts']
        self.assertEqual(f['regulation_home'],sum(f['quarters_home']))
        self.assertEqual(f['final_home'],f['regulation_home']+sum(f['overtime_home']))
        self.assertEqual(f['regulation_scope'],'REGULATION_ONLY')
        self.assertEqual(f['final_scope'],'FINAL_WITH_OT')
        self.assertEqual(len(self.select([r])),1)

    def test_real_trimmed_euroleague_and_eurocup_sources_have_distinct_namespaces(self):
        rows=[self.seal(euro.source(league)['game'],league) for league in ['EUROLEAGUE','EUROCUP']]
        for league in ['EUROLEAGUE','EUROCUP']:
            selected=self.select(rows,league=league)
            self.assertEqual(len(selected),1);self.assertEqual(selected[0]['facts']['league'],league)
            self.assertEqual(selected[0]['facts']['season_end_year'],2027)

    def test_future_ingestion_or_materialization_is_not_historical_availability(self):
        r=self.seal()
        self.assertEqual(self.select([r],cutoff_utc=NOW-30),[])
        self.assertEqual(len(self.select([r],cutoff_utc=NOW-30,mode='ARCHIVED_SOURCE_CLOCK')),1)

    def test_equal_cutoff_is_excluded_and_strict_source_clock_is_not_backdated(self):
        r=self.seal();self.assertEqual(self.select([r],cutoff_utc=NOW-20),[])
        self.assertEqual(self.select([r],cutoff_utc=NOW-100,mode='ARCHIVED_SOURCE_CLOCK'),[])

    def test_identical_observations_and_provider_aliases_count_once(self):
        raw=nba.summary(900010001,NOW-7200);first=self.seal(raw)
        raw['header']['id']=raw['header']['competitions'][0]['id']='900010002'
        alias=self.seal(raw)
        rows=self.select([first,alias,first])
        self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]['provider_aliases']),2)
        self.assertEqual(self.select([alias,first]),rows)

    def test_same_team_start_with_different_opponent_or_venue_is_refused(self):
        first=self.seal();raw=nba.summary(900010002,NOW-7200)
        raw['header']['competitions'][0]['competitors'][1]['team']['id']='4'
        other=self.seal(raw,team_ids=['19','2','4'])
        with self.assertRaisesRegex(ValueError,'SAME_TEAM_START'):self.select([first,other])
        self.clock=NOW-20  # Both conflicting observations must precede cutoff.
        reversed_game=self.seal(nba.summary(900010002,NOW-7200,True))
        with self.assertRaisesRegex(ValueError,'SAME_TEAM_START'):self.select([first,reversed_game])

    def test_same_provider_id_cannot_move_to_another_fixture(self):
        first=self.seal();later=self.seal(nba.summary(900010001,NOW-3600))
        with self.assertRaisesRegex(ValueError,'PROVIDER_FIXTURE_IDENTITY'):self.select([first,later])

    def test_rehashed_quarter_or_scope_fact_tampering_is_refused(self):
        r=self.seal()
        for field,value in [('quarters_home',[1,2,3,4]),('final_scope','REGULATION_ONLY'),('regulation_home',999)]:
            p=deepcopy(r['payload']);p['facts'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'SEMANTIC'):
                a.replay_game(dict(payload=p,sha256=digest(p)))

    def test_source_or_directory_digest_tampering_is_refused(self):
        r=self.seal();r['payload']['raw']['header']['id']='999'
        with self.assertRaisesRegex(ValueError,'DIGEST'):a.replay_game(r)

    def test_unknown_team_season_nonfinal_and_unverifiable_periods_are_refused(self):
        with self.assertRaises(ValueError):self.seal(team_ids=['2','4'])
        with self.assertRaises(ValueError):self.seal(season_end_year=2026)
        raw=nba.summary(900010001,NOW-7200);raw['header']['competitions'][0]['status']['type']['completed']=False
        with self.assertRaises(ValueError):self.seal(raw)
        raw=nba.summary(900010001,NOW-7200);raw['header']['competitions'][0]['competitors'][0]['linescores'][0]['displayValue']='0'
        with self.assertRaises(ValueError):self.seal(raw)

    def test_live_creation_mixed_synthetic_and_research_samples_are_refused(self):
        with self.assertRaisesRegex(ValueError,'LIVE_RECORD'):self.seal(usage='PROSPECTIVE')
        first=self.seal();second=self.seal(nba.summary(900010002,NOW-3600),usage='RETROSPECTIVE_RESEARCH')
        with self.assertRaisesRegex(ValueError,'MIXED_SYNTHETIC_REAL'):self.select([first,second])

    def test_input_mutation_cannot_change_a_sealed_archive(self):
        raw=nba.summary(900010001,NOW-7200);r=self.seal(raw);before=deepcopy(r)
        raw.clear();self.assertEqual(r,before);a.replay_game(r)

    def test_partition_and_clock_types_are_fail_closed(self):
        for opts in [dict(ingested_utc=True),dict(source_observed_utc=NOW+1),dict(team_ids=[None]),dict(season_end_year=True)]:
            with self.subTest(opts=opts),self.assertRaises(ValueError):self.seal(**opts)
        r=self.seal()
        with self.assertRaisesRegex(ValueError,'MODE'):self.select([r],mode='LIVE')
        with self.assertRaises(ValueError):self.select([r],cutoff_utc=True)

    def test_nba_2027_regular_season_flag_cannot_override_official_date_boundary(self):
        raw=nba.summary(900010001,1790812800)  # 2026-10-01, before official Oct20.
        with self.assertRaisesRegex(ValueError,'OUTSIDE_OFFICIAL_REGULAR_SEASON'):
            self.seal(raw)


if __name__=='__main__':unittest.main()
