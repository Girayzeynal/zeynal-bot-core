"""Synthetic source contracts; no real model-performance or prospective claims."""
from copy import deepcopy
from datetime import datetime,timezone
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
from faz41_adapters import capture
from faz41_evidence import REGISTRY,fixture_identity
from faz43_pbp import capture_espn_timeline
from faz45_support import support_report,validate_support
from tests.test_faz42_history import NOW,permitted_registry
from tests.test_faz41_adapters import espn
from tests.test_faz43_pbp import game
from tests.test_euroleague_live import source

TARGET=fixture_identity(league='NBA',season_end_year=2027,start_utc=NOW+3600,home_team_id='19',away_team_id='2')


def raws(n=3):
    result=[]
    for i in range(n):
        r=game();r['boxscore']=deepcopy(espn()['boxscore']);h=r['header'];c=h['competitions'][0]
        h['id']=c['id']=str(401900001+i);c['date']=datetime.fromtimestamp(NOW-(5-i)*86400,timezone.utc).isoformat();h['date']=c['date']
        result.append(r)
    return result


def record(raw,kind='OFFICIAL_STAT',*,registry=None,usage='SYNTHETIC_TEST',at=None):
    registry=REGISTRY if registry is None else registry;start=int(datetime.fromisoformat(raw['header']['competitions'][0]['date']).timestamp());at=at or start+10000
    with patch('time.time',return_value=at):
        if kind=='PBP_TIMELINE':return capture_espn_timeline(raw,observed_at_utc=at-100,ingested_at_utc=at-50,usage=usage,registry=registry,registry_pin=digest(registry))
        return capture(raw,provider='ESPN',league='NBA',season_end_year=2027,observed_at_utc=at-100,ingested_at_utc=at-50,
            data_type=kind,usage=usage,registry=registry,registry_pin=digest(registry))


def dataset(registry=None,usage='SYNTHETIC_TEST'):
    r=raws();return r,[record(x,registry=registry,usage=usage) for x in r],[record(x,'PLAYER_MINUTES',registry=registry,usage=usage) for x in r]+[record(x,'PBP_TIMELINE',registry=registry,usage=usage) for x in r]


class SupportResearchTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)
        self.registry=permitted_registry();self.raw,self.scores,self.aux=dataset(self.registry)

    def report(self,scores=None,aux=None,**kw):
        args=dict(cutoff_utc=NOW,minimum_team_games=3,registry=self.registry,registry_pin=digest(self.registry));args.update(kw)
        return support_report(self.scores if scores is None else scores,self.aux if aux is None else aux,TARGET,**args)

    def test_joined_descriptive_minutes_and_pbp_reuse_source_guards(self):
        r=self.report();home=r['teams']['home'];m=home['player_minutes'];p=home['pbp']
        self.assertEqual(r['usable_distinct_games'],dict(PLAYER_MINUTES=3,PBP_TIMELINE=3))
        self.assertEqual(m['status'],'DESCRIPTIVE_FEATURES_AVAILABLE');self.assertEqual(m['features']['games'],3)
        self.assertEqual(m['features']['players'][0]['reported_minutes_sum'],144);self.assertFalse(m['features']['reported_minutes_are_exact_seconds'])
        self.assertEqual(m['target_roster_status'],'NOT_INFERRED');self.assertIsNone(m['player_efficiency']);self.assertIsNone(m['rotation_effect'])
        # 1H: 50-55 (-5); 2H: 47-53 (-6). The change is -1.
        self.assertEqual(p['features']['second_half_minus_first_half_margin_mean'],-1)
        self.assertEqual(home['prematch_roster'],'ABSTAIN_NO_REPLAYABLE_PREMATCH_ROSTER');self.assertEqual(r['prospective_records_created'],0)

    def test_duplicates_and_provider_aliases_cannot_inflate_games(self):
        before=deepcopy(self.aux);a=deepcopy(self.raw[0]);a['header']['id']=a['header']['competitions'][0]['id']='401900099'
        alias=record(a,'PLAYER_MINUTES',registry=self.registry)
        out=self.report(aux=self.aux+self.aux+[alias]);self.assertEqual(out['usable_distinct_games'],dict(PLAYER_MINUTES=3,PBP_TIMELINE=3))
        self.assertEqual(out['teams']['home']['player_minutes']['features']['games'],3);self.assertEqual(self.aux,before)

    def test_late_ingestion_and_equal_cutoff_auxiliary_do_not_backfill_history(self):
        for at in (NOW-10,NOW-1):
            aux=deepcopy(self.aux);aux[0]=record(self.raw[0],'PLAYER_MINUTES',registry=self.registry,at=at)
            r=self.report(aux=aux,cutoff_utc=NOW-10)
            self.assertEqual(r['teams']['home']['player_minutes']['status'],'ABSTAIN_INSUFFICIENT_PLAYER_GAMES')
            self.assertEqual(r['excluded']['AUXILIARY_NOT_AVAILABLE_AT_CUTOFF'],1)

    def test_score_availability_is_required_even_when_player_source_is_old(self):
        scores=deepcopy(self.scores);scores[0]=record(self.raw[0],registry=self.registry,at=NOW-1)
        r=self.report(scores=scores,cutoff_utc=NOW-10)
        self.assertEqual(r['usable_distinct_games']['PLAYER_MINUTES'],2);self.assertEqual(r['excluded']['SCORE_NOT_AVAILABLE_AT_CUTOFF'],2)

    def test_unknown_permission_exposes_inventory_without_numeric_features(self):
        raw,scores,aux=dataset(REGISTRY);r=support_report(scores,aux,TARGET,cutoff_utc=NOW)
        self.assertEqual(r['matched_distinct_games'],dict(PLAYER_MINUTES=3,PBP_TIMELINE=3));self.assertEqual(r['usable_distinct_games'],dict(PLAYER_MINUTES=0,PBP_TIMELINE=0))
        for side in ('home','away'):
            self.assertIsNone(r['teams'][side]['player_minutes']['features']);self.assertIsNone(r['teams'][side]['pbp']['features'])
        self.assertEqual(r['excluded']['SOURCE_PERMISSION_NOT_ESTABLISHED'],6)

    def test_permission_expiry_cannot_be_satisfied_by_observation_time_only(self):
        self.registry['ESPN']['expires_at_utc']=NOW-1;raw,scores,aux=dataset(self.registry)
        r=self.report(scores=scores,aux=aux);self.assertEqual(r['usable_distinct_games']['PLAYER_MINUTES'],0)

    def test_stale_auxiliary_cannot_be_used_through_fresh_score(self):
        r=self.report(maximum_age_seconds=86400)
        self.assertEqual(r['usable_distinct_games']['PLAYER_MINUTES'],0);self.assertEqual(r['excluded']['AUXILIARY_NOT_AVAILABLE_AT_CUTOFF'],6)

    def test_historical_cutoff_never_uses_target_final_or_later_result(self):
        target=self.scores[-1]['payload']['fixture'];cutoff=target['start_utc']-1
        r=support_report(self.scores,self.aux,target,cutoff_utc=cutoff,minimum_team_games=2,registry=self.registry,registry_pin=digest(self.registry))
        self.assertEqual(r['usable_distinct_games']['PLAYER_MINUTES'],2);self.assertEqual(r['excluded']['TARGET_OR_FUTURE_RESULT'],2)
        self.assertNotIn(target['canonical_id'],r['teams']['home']['player_minutes']['features']['canonical_game_ids'])

    def test_future_cutoff_tipoff_and_invalid_window_are_refused(self):
        for kw in [dict(cutoff_utc=NOW+1),dict(cutoff_utc=TARGET['start_utc']),dict(minimum_team_games=3,last_games=2)]:
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.report(**kw)

    def test_missing_pbp_does_not_turn_minutes_into_rotation_or_comeback(self):
        r=self.report(aux=self.aux[:3]);self.assertEqual(r['teams']['home']['player_minutes']['status'],'DESCRIPTIVE_FEATURES_AVAILABLE')
        self.assertIsNone(r['teams']['home']['pbp']['features']);self.assertIn('ABSTAIN',r['teams']['home']['lineup_rotation'])

    def test_auxiliary_without_replayed_score_is_not_a_training_pair(self):
        r=self.report(scores=self.scores[1:]);self.assertEqual(len(r['unmatched_auxiliary_digests']),2);self.assertEqual(r['matched_distinct_games']['PLAYER_MINUTES'],2)
        self.assertIsNone(r['teams']['home']['player_minutes']['features'])

    def test_valid_player_totals_with_conflicting_game_score_are_refused(self):
        raw=deepcopy(self.raw[0]);home=next(t for t in raw['header']['competitions'][0]['competitors'] if t['homeAway']=='home')
        home['score']=str(int(home['score'])+1);home['linescores'][0]['displayValue']=str(int(home['linescores'][0]['displayValue'])+1);home['linescores'][0]['value']=int(home['linescores'][0]['displayValue'])
        block=next(b for b in raw['boxscore']['players'] if b['team']['id']==home['team']['id']);a=block['statistics'][0]['athletes'][0];a['stats'][1]=str(int(a['stats'][1])+1)
        o=record(raw,'PLAYER_MINUTES',registry=self.registry)
        with self.assertRaisesRegex(ValueError,'AUXILIARY_SCORE_CONFLICT'):self.report(aux=[o])

    def test_conflicting_player_revision_is_not_silently_selected(self):
        raw=deepcopy(self.raw[0]);rows=raw['boxscore']['players'][0]['statistics'][0]['athletes'];rows[0]['stats'][1]=str(int(rows[0]['stats'][1])-1);rows[1]['stats'][1]='1'
        o=record(raw,'PLAYER_MINUTES',registry=self.registry)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_SUPPORT'):self.report(aux=self.aux+[o])

    def test_rehashed_timeline_claim_cannot_bypass_raw_source_replay(self):
        aux=deepcopy(self.aux);aux[3]['payload']['claims']['garbage_rule_events']+=1;aux[3]['sha256']=digest(aux[3]['payload'])
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.report(aux=aux)

    def test_pbp_provider_id_cannot_be_reassigned_to_another_tipoff(self):
        raw=deepcopy(self.raw[-1]);raw['header']['id']=raw['header']['competitions'][0]['id']=self.raw[0]['header']['id']
        o=record(raw,'PBP_TIMELINE',registry=self.registry)
        with self.assertRaisesRegex(ValueError,'PROVIDER_FIXTURE_ID_CONFLICT'):self.report(aux=[o])

    def test_mixed_real_synthetic_evidence_is_refused(self):
        o=record(self.raw[0],'PLAYER_MINUTES',registry=self.registry,usage='RETROSPECTIVE_RESEARCH')
        with self.assertRaisesRegex(ValueError,'MIXED'):self.report(aux=[o])

    def test_last_n_is_chronological_and_does_not_change_original_records(self):
        before=deepcopy(self.scores+self.aux);r=self.report(scores=list(reversed(self.scores)),aux=list(reversed(self.aux)),last_games=2,minimum_team_games=2)
        expected=[o['payload']['fixture']['canonical_id'] for o in self.scores[-2:]]
        self.assertEqual(r['teams']['home']['player_minutes']['features']['canonical_game_ids'],expected);self.assertEqual(before,self.scores+self.aux)

    def test_overtime_player_minutes_are_never_labelled_regulation_minutes(self):
        raw=deepcopy(self.raw[0]);c=raw['header']['competitions'][0]
        for t in c['competitors']:
            h=t['homeAway']=='home';points=110 if h else 108;t['score']=str(points)
            t['linescores']=[dict(value=v,displayValue=str(v)) for v in [25]*4+[10 if h else 8]]
            b=next(b for b in raw['boxscore']['players'] if b['team']['id']==t['team']['id'])
            for i,a in enumerate(b['statistics'][0]['athletes']):a['stats']=['53',str(points if i==0 else 0)]
        scores=[record(raw,registry=self.registry)];aux=[record(raw,'PLAYER_MINUTES',registry=self.registry)]
        r=self.report(scores=scores,aux=aux,minimum_team_games=1);m=r['teams']['home']['player_minutes']['features']
        self.assertEqual(m['overtime_games'],1);self.assertEqual(m['scope'],'FINAL_WITH_OT_NOT_REGULATION_PLAYER_SPLIT');self.assertEqual(m['players'][0]['reported_minutes_sum'],53)

    def test_zero_displayed_minutes_are_not_invented_exact_seconds_or_an_appearance_count(self):
        raw=deepcopy(self.raw[0]);block=next(b for b in raw['boxscore']['players'] if b['team']['id']=='19')
        block['statistics'][0]['athletes'].append(dict(athlete=dict(id='19999'),stats=['0','0'],starter=False,didNotPlay=False))
        scores=[record(raw,registry=self.registry)];aux=[record(raw,'PLAYER_MINUTES',registry=self.registry)]
        r=self.report(scores=scores,aux=aux,minimum_team_games=1);features=r['teams']['home']['player_minutes']['features']
        player=next(v for v in features['players'] if v['player_id']=='ESPN:19999')
        self.assertNotIn('appearances',player);self.assertEqual(player['boxscore_entries'],1);self.assertEqual(player['explicit_played_status_entries'],1)
        self.assertEqual(player['zero_reported_minutes_entries'],1);self.assertEqual(player['positive_reported_minutes_entries'],0)
        self.assertFalse(features['reported_minutes_are_exact_seconds'])

    def test_euro_missing_participation_status_is_not_filled_from_boxscore_presence(self):
        raw=source('EUROLEAGUE')
        for side in ('local','road'):
            rows=raw['stats'][side]['players'];n=len(rows)-1
            for i,p in enumerate(rows):p['stats']['timePlayed']=0 if i==0 else 12000//n+(i<=12000%n)
        with patch('time.time',return_value=NOW-10):
            score=capture(raw['game'],provider='EUROLEAGUE_LIVE',league='EUROLEAGUE',season_end_year=2027,observed_at_utc=NOW-20,ingested_at_utc=NOW-15,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=digest(self.registry))
            aux=capture(dict(game=raw['game'],stats=raw['stats']),provider='EUROLEAGUE_LIVE',league='EUROLEAGUE',season_end_year=2027,data_type='PLAYER_MINUTES',observed_at_utc=NOW-20,ingested_at_utc=NOW-15,usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=digest(self.registry))
        f=score['payload']['fixture'];target=fixture_identity(league='EUROLEAGUE',season_end_year=2027,start_utc=NOW+3600,home_team_id=f['home_team_id'],away_team_id=f['away_team_id'])
        r=support_report([score],[aux],target,cutoff_utc=NOW,minimum_team_games=1,registry=self.registry,registry_pin=digest(self.registry))
        features=r['teams']['home']['player_minutes']['features'];row=next(v for v in features['players'] if v['zero_reported_minutes_entries'])
        self.assertEqual(row['explicit_played_status_entries'],0);self.assertEqual(row['historical_starter_status'],'NOT_AVAILABLE')
        self.assertNotIn('appearances',row);self.assertTrue(features['reported_minutes_are_exact_seconds'])
