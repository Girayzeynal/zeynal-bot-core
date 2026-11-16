"""Manufactured past-box/prospective-minute cases; no real forecast claims."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Abstain
from hybrid_engine.player_minutes import projection,validate_minutes,MinutesArchive,historical_minutes,capped_rotation
from hybrid_engine.player_inputs import validate_witness

NOW=int(datetime(2026,11,16,16,tzinfo=timezone.utc).timestamp())


def inputs(fixture='future',start=None,now=NOW):
    start=now+3600 if start is None else start
    context=dict(league='NBA',season='2026/2027',fixture_id=fixture,fixture_start_utc=start,
        original_snapshot_sha256='a'*64,home=dict(provider_id='1'),away=dict(provider_id='2'))
    review=dict(status='CURRENT_SOURCE_OBSERVATIONS',fixture_id=fixture,fixture_start_utc=start,
        original_snapshot_sha256='a'*64,observed_at_utc=now-10,valid_until_utc=now+290,
        sources=[dict(observed_at_utc=now-10)],records=[])
    rosters={}; boxes=[]
    for side,team,base in [('home','1',100),('away','2',200)]:
        players=[str(base+i) for i in range(8)]
        rosters[side]=dict(team_id=team,season='2026/2027',players=players,
            observed_at_utc=now-10,source_sha256='b'*64)
        for i in range(6):
            past=now-(i+1)*86400
            boxes.append(dict(league='NBA',season='2026/2027',fixture_id=team+'-past-'+str(i),fixture_start_utc=past,
                home_team_id=team,away_team_id='3',scope='FINAL_WITH_OT',regulation_eligible=True,
                source=dict(observed_at_utc=past+10800,ingested_at_utc=past+10801),
                players=[dict(player_id=p,team_id=team,minutes_display='30',did_not_play=False,
                    data_kind='POSTGAME_ACTUAL_NOT_PREMATCH_LINEUP') for p in players]))
    return dict(context=context,review=review,rosters=rosters,boxes=boxes,generated_at_utc=now-5)


def archive_inputs(root,data):
    packet=projection(**data)
    b={k:deepcopy(data[k]) for k in ('context','review','rosters','boxes')}
    b.update(format='PLAYER_MINUTES_INPUT_WITNESSES_V1',projection_sha256=packet['sha256'],original_cut_sha256='c'*64)
    publish_json(Path(root)/('inputs-'+packet['sha256']+'.json'),dict(payload=b,sha256=digest(b)))
    publication,_=MinutesArchive(Path(root)/'minutes').record(packet)
    return publication


class PlayerMinutesTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW); self.timer.start(); self.addCleanup(self.timer.stop)

    def test_full_minutes_are_model_priors_and_do_not_mutate_sources(self):
        data=inputs(); before=deepcopy(data); p=projection(**data)['payload']
        self.assertEqual(data,before)
        for s in ('home','away'):
            self.assertAlmostEqual(sum(r['expected_minutes'] for r in p[s]),240)
            self.assertTrue(all(r['expected_minutes']==30 for r in p[s]))
        self.assertFalse(p['lineup_verified']); self.assertIsNone(p['confidence_index'])
        self.assertIn('UNREPORTED_AVAILABILITY_IS_NOT_CONFIRMED_AVAILABLE',p['assumptions'])

    def test_only_both_source_out_observations_remove_player_and_redistribute(self):
        data=inputs(); data['review']['records']=[dict(team_id='1',player_id='100',status='Out',
            source=s,status_updated_at_utc=NOW-10) for s in ('ESPN','NBA_OFFICIAL_PDF')]
        p=projection(**data)['payload']; self.assertEqual(p['home'][0]['expected_minutes'],0)
        self.assertAlmostEqual(sum(r['expected_minutes'] for r in p['home']),240)
        self.assertTrue(all(r['expected_minutes']<=48 for r in p['home']))

    def test_absence_already_in_past_rotation_does_not_get_a_second_points_penalty(self):
        data=inputs()
        for b in data['boxes']:
            if b['home_team_id']=='1':
                b['players'][0].update(minutes_display=None,did_not_play=True)
                for p in b['players'][1:]: p['minutes_display']='34'
        prior=projection(**data)['payload']['home']
        data['review']['records']=[dict(team_id='1',player_id='100',status='Out',source=s,
            status_updated_at_utc=NOW-10) for s in ('ESPN','NBA_OFFICIAL_PDF')]
        updated=projection(**data)['payload']['home']
        self.assertEqual([r['expected_minutes'] for r in prior],[r['expected_minutes'] for r in updated])

    def test_single_source_out_unknown_identity_and_ambiguous_status_abstain(self):
        for rows in ([dict(team_id='1',player_id='100',status='Out',source='ESPN',status_updated_at_utc=NOW-10)],
                     [dict(team_id='1',player_id=None,status='Out',source='NBA_OFFICIAL_PDF',status_updated_at_utc=NOW-10)],
                     [dict(team_id='1',player_id='100',status='Questionable',source='ESPN',status_updated_at_utc=NOW-10)]):
            data=inputs(); data['review']['records']=rows
            with self.assertRaises(Abstain): projection(**data)

    def test_conflicting_status_is_not_given_an_invented_playing_probability(self):
        data=inputs(); data['review']['records']=[dict(team_id='1',player_id='100',status=s,
            source=source,status_updated_at_utc=NOW-10) for s,source in [('Out','ESPN'),('Available','NBA_OFFICIAL_PDF')]]
        with self.assertRaisesRegex(Abstain,'CONFLICTING'): projection(**data)

    def test_future_source_target_box_and_mismatched_fixture_are_rejected(self):
        for key in ('future','target','fixture'):
            data=inputs()
            if key=='future': data['boxes'][0]['source']['ingested_at_utc']=NOW+1
            elif key=='target': data['boxes'][0]['fixture_id']='future'
            else: data['review']['fixture_start_utc']+=1
            with self.subTest(key=key),self.assertRaises((ValueError,Abstain)): projection(**data)

    def test_incomplete_and_overtime_history_cannot_be_used_as_regulation_minutes(self):
        for key in ('missing','ot','duplicate','wrong_sum'):
            data=inputs()
            if key=='missing': data['boxes'].pop(0)
            elif key=='ot': data['boxes'][0]['regulation_eligible']=False
            elif key=='duplicate': data['boxes'].append(deepcopy(data['boxes'][0]))
            else: data['boxes'][0]['players'][0]['minutes_display']='2'
            with self.subTest(key=key),self.assertRaises((ValueError,Abstain)): projection(**data)

    def test_unseen_current_roster_player_is_not_assigned_guessed_minutes(self):
        data=inputs(); data['rosters']['home']['players'][0]='999'
        with self.assertRaisesRegex(Abstain,'WITHOUT_PRIOR'): projection(**data)

    def test_minute_parser_preserves_rounding_and_does_not_infer_dnp(self):
        row=dict(data_kind='POSTGAME_ACTUAL_NOT_PREMATCH_LINEUP',minutes_display='32:30')
        self.assertEqual(historical_minutes(row),32.5)
        for value in ('DNP','--','49','32:99',True):
            with self.assertRaises(ValueError): historical_minutes(dict(row,minutes_display=value))
        self.assertEqual(historical_minutes(dict(row,did_not_play=True,minutes_display=None)),0)

    def test_cap_algorithm_conserves_minutes_with_no_player_over_48(self):
        m=capped_rotation([40,10,10,10,10,10,10,10]); self.assertAlmostEqual(sum(m),240)
        self.assertLessEqual(max(m),48)
        with self.assertRaises(Abstain): capped_rotation([1,1,1,1,1,0,0,0])

    def test_no_after_tipoff_or_future_clock_projection(self):
        for now in (NOW+1,NOW+3600,True):
            d=inputs(); d['generated_at_utc']=now
            with self.assertRaises((ValueError,Abstain)): projection(**d)

    def test_schema_rejects_actual_minutes_boolean_nan_and_hash_tampering(self):
        original=projection(**inputs())
        for key in ('actual','bool','nan','pin','sum','out'):
            w=deepcopy(original); p=w['payload']
            if key=='actual': p['model_input_kind']='POSTGAME_ACTUAL'
            elif key=='bool': p['home'][0]['expected_minutes']=True
            elif key=='nan':
                p['home'][0]['expected_minutes']=float('nan')
                with self.assertRaises(ValueError): validate_minutes(w,asof_utc=NOW)
                continue
            elif key=='sum': p['home'][0]['expected_minutes']=29
            elif key=='out': p['home'][0]['status']='OUT_SOURCE_CORROBORATED'
            else: w['sha256']='0'*64
            if key!='pin': w['sha256']=digest(p)
            with self.subTest(key=key),self.assertRaises(ValueError): validate_minutes(w,asof_utc=NOW)

    def test_first_publication_is_immutable_and_not_replaced_by_redisplay(self):
        w=projection(**inputs())
        with TemporaryDirectory() as tmp:
            a=MinutesArchive(tmp); p,new=a.record(w); self.assertTrue(new)
            files={f:f.read_bytes() for f in Path(tmp).glob('*')}
            with patch('time.time',return_value=NOW+100):
                again,new=a.record(w)
            self.assertFalse(new); self.assertEqual(p,again)
            self.assertEqual(files,{f:f.read_bytes() for f in Path(tmp).glob('*')})

    def test_after_tipoff_first_archive_and_invalid_publication_hash_are_rejected(self):
        w=projection(**inputs())
        with TemporaryDirectory() as tmp:
            a=MinutesArchive(tmp)
            with patch('time.time',return_value=NOW+3600),self.assertRaises(ValueError): a.record(w)
            a.record(w); p=next(Path(tmp).glob('minutes-*')); raw=json.loads(p.read_text())
            raw['payload']['first_archived_at_utc']=NOW+3600; raw['sha256']=digest(raw['payload']); p.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError,'AFTER_TIPOFF'): a.read(p)

    def test_witness_replay_detects_changed_history_or_projected_minutes(self):
        with TemporaryDirectory() as tmp:
            publication=archive_inputs(tmp,inputs()); p=validate_witness(publication,tmp)
            self.assertEqual(p['fixture_id'],'future')
            path=next(Path(tmp).glob('inputs-*')); w=json.loads(path.read_text())
            w['payload']['boxes'][0]['players'][0]['minutes_display']='31'; w['sha256']=digest(w['payload'])
            path.write_text(json.dumps(w))
            with self.assertRaisesRegex(ValueError,'REPLAY_CONFLICT'): validate_witness(publication,tmp)

    def test_same_player_cannot_be_on_both_current_teams(self):
        data=inputs(); data['rosters']['away']['players'][0]='100'
        with self.assertRaisesRegex(ValueError,'BOTH_CURRENT_TEAMS'): projection(**data)

    def test_rehashed_packet_cannot_put_same_player_on_both_teams(self):
        w=projection(**inputs()); w['payload']['away'][0]['player_id']='100'; w['sha256']=digest(w['payload'])
        with self.assertRaisesRegex(ValueError,'BOTH_CURRENT_TEAMS'): validate_minutes(w,asof_utc=NOW)
