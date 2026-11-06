from copy import deepcopy
from datetime import datetime,timezone
from unittest import TestCase
from unittest.mock import Mock,patch

from prediction_inputs import digest
from faz40_archive import seal_game
from faz43_nba_refresh import collect,replay_research_fact,BASE
from tests.test_faz32 import summary
from tests.test_faz42_history import NOW


def completed(pid='401900100',start=NOW-86400):
    raw=summary(pid,start);raw.pop('boxscore',None);h=deepcopy(raw['header']);h['date']=h['competitions'][0]['date'];return raw,h


class NBARefreshTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.existing_raw,self.old=completed('401900001',NOW-2*86400)
        self.existing=seal_game(self.existing_raw,league='NBA',season_end_year=2027,source_observed_utc=NOW-1000,
                               ingested_utc=NOW-500,team_ids=['19','2'],usage='SYNTHETIC_TEST')
        self.raw,self.event=completed()

    def collector(self,events=None,raws=None):
        events=events if events is not None else [self.event];raws=raws or {'401900100':self.raw}
        def get(url,provider):
            if '/scoreboard?' in url:payload={'events':events} if 'dates=20261105' in url else {'events':[]}
            else:payload=raws[url.split('event=')[1]]
            return dict(status='DOCUMENT_RECEIVED',source_url=url,provider=provider,http_status=200,payload=payload,observed_at_utc=NOW-10)
        return Mock(side_effect=get)

    def test_default_no_requests_and_original_archive_unchanged(self):
        c=self.collector();before=deepcopy(self.existing);r=collect([self.existing],collector=c)
        c.assert_not_called();self.assertEqual(r['existing_games'],1);self.assertEqual(before,self.existing)

    def test_new_real_structure_is_replayable_retrospective_and_not_model_eligible(self):
        r=collect([self.existing],live=True,collector=self.collector())
        self.assertEqual(r['unique_new_games'],1);self.assertEqual(r['union_period_games'],2)
        self.assertEqual(r['model_eligible_games'],0);self.assertFalse(r['legacy_database_modified'])
        n=replay_research_fact(r['new_games'][0],asof_utc=NOW);self.assertEqual(n['provider_fixture_id'],'401900100')
        self.assertEqual(r['new_games'][0]['payload']['materialized_at_utc'],NOW)
        self.assertEqual(r['player_coverage'][0]['status'],'ABSTAIN_PLAYER_DATA')

    def test_known_game_is_not_fetched_or_counted_twice(self):
        old_raw,old_event=completed('401900001',NOW-86400-3600)
        old=seal_game(old_raw,league='NBA',season_end_year=2027,source_observed_utc=NOW-1000,ingested_utc=NOW-500,team_ids=['19','2'],usage='SYNTHETIC_TEST')
        c=self.collector(events=[old_event,old_event],raws={});r=collect([old,old],live=True,collector=c)
        self.assertEqual(r['existing_games'],1);self.assertEqual(r['unique_new_games'],0)
        self.assertEqual(c.call_count,2)

    def test_scoreboard_summary_conflict_is_abstain_not_a_new_game(self):
        raw=deepcopy(self.raw);t=raw['header']['competitions'][0]['competitors'][0];t['score']=str(int(t['score'])+1);t['linescores'][0]['displayValue']=str(int(t['linescores'][0]['displayValue'])+1)
        r=collect([self.existing],live=True,collector=self.collector(raws={'401900100':raw}))
        self.assertEqual(r['unique_new_games'],0);self.assertIn('SCOREBOARD_SUMMARY_CONFLICT',{x['reason'] for x in r['rejected']})

    def test_rehashed_facts_future_ingestion_and_wrong_origin_are_refused(self):
        r=collect([self.existing],live=True,collector=self.collector());record=r['new_games'][0]
        for field,value in [('published_at_utc',NOW-100000),('ingested_at_utc',NOW+1),('scoreboard_url','https://evil.test/')]:
            x=deepcopy(record);x['payload'][field]=value;x['sha256']=digest(x['payload'])
            with self.subTest(field=field),self.assertRaises(ValueError):replay_research_fact(x,asof_utc=NOW)
        x=deepcopy(record);x['payload']['normalized']['claims']['final_home']+=1;x['sha256']=digest(x['payload'])
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):replay_research_fact(x,asof_utc=NOW)

    def test_budget_bounds_selected_requests_and_reports_deferred_games(self):
        raw2,event2=completed('401900101',NOW-86400+3600)
        c=self.collector(events=[self.event,event2],raws={'401900100':self.raw,'401900101':raw2})
        r=collect([self.existing],live=True,max_new_games=1,collector=c)
        self.assertEqual(r['discovered_missing_games'],2);self.assertEqual(r['deferred_by_budget'],1);self.assertEqual(c.call_count,3)
        for opts in [dict(max_new_games=13),dict(history_days=4),dict(max_new_games=True)]:
            with self.subTest(opts=opts),self.assertRaises(ValueError):collect([],**opts)

    def test_two_provider_ids_for_one_game_do_not_inflate_union(self):
        raw2,event2=completed('401900101')
        r=collect([self.existing],live=True,collector=self.collector(events=[self.event,event2],raws={'401900100':self.raw,'401900101':raw2}))
        self.assertEqual(r['unique_new_games'],1);self.assertEqual(r['union_period_games'],2)
        self.assertEqual(len(r['player_coverage']),1)

    def test_existing_same_provider_id_cannot_change_match_identity(self):
        other,_=completed('401900001',NOW-3*86400)
        sealed=seal_game(other,league='NBA',season_end_year=2027,source_observed_utc=NOW-1000,
                         ingested_utc=NOW-500,team_ids=['19','2'],usage='SYNTHETIC_TEST')
        with self.assertRaisesRegex(ValueError,'PROVIDER_ID_CONFLICT'):collect([self.existing,sealed])

    def test_http_403_is_not_a_completed_sample_or_probability(self):
        c=Mock(side_effect=lambda url,provider:dict(status='HTTP_403',http_status=403,source_url=url))
        r=collect([self.existing],live=True,collector=c)
        self.assertEqual(r['unique_new_games'],0);self.assertEqual(r['prospective_records_created'],0)
        self.assertTrue(all(s['status']=='HTTP_403' for s in r['sources']))

    def test_equal_final_and_quarters_with_different_overtime_count_is_a_conflict(self):
        records=[]
        for extra in ([10],[0,10]):
            raw=deepcopy(self.existing_raw)
            for t in raw['header']['competitions'][0]['competitors']:
                ot=extra if t['homeAway']=='home' else ([8] if len(extra)==1 else [0,8])
                values=[25]*4+ot;t['linescores']=[dict(displayValue=str(v)) for v in values];t['score']=str(sum(values))
            records.append(seal_game(raw,league='NBA',season_end_year=2027,source_observed_utc=NOW-1000,
                                    ingested_utc=NOW-500,team_ids=['19','2'],usage='SYNTHETIC_TEST'))
        with self.assertRaisesRegex(ValueError,'CONFLICTING_EXISTING_FINAL'):collect(records)
