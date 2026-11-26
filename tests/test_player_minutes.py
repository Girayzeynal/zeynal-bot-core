"""Manufactured past-box/prospective-minute cases; no real forecast claims."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Abstain
from hybrid_engine.player_minutes import projection,validate_minutes,MinutesArchive,historical_minutes,capped_rotation
from hybrid_engine.current_roster import status_relationship,render_review
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

    def test_pinned_official_only_out_can_explain_rotation_but_cannot_archive(self):
        # A fully identified real-authority PDF status can diagnose downstream
        # readiness. It must not silently weaken the archived two-source policy.
        data=inputs()
        url='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-16_10_45AM.pdf'
        data['review'].update(official_pdf_clock_verified=True,official_stage='FIXTURE_ROWS',
            official_code='SOURCE_ROWS_MATCHED_NOT_MEDICALLY_VERIFIED',
            official_report=dict(source_url=url,report_timestamp_utc=NOW-900))
        data['review']['sources'].append(dict(url=url,observed_at_utc=NOW-10))
        data['review']['records']=[dict(team_id='1',player_id='100',status='Out',
            source='NBA_OFFICIAL_PDF',identity_status='EXACT_ESPN_ROSTER_MATCH',
            status_updated_at_utc=NOW-900)]
        with self.assertRaisesRegex(Abstain,'ABSENCE_REQUIRES_BOTH'):
            projection(**data)
        probe=projection(**data,diagnostic_official_only=True)
        p=probe['payload']
        self.assertEqual(p['provisional_official_only_player_ids'],['100'])
        self.assertEqual(p['model_input_kind'],'UNARCHIVABLE_OFFICIAL_ONLY_DIAGNOSTIC')
        self.assertEqual(p['home'][0]['expected_minutes'],0)
        self.assertEqual(p['home'][0]['status'],'OUT_OFFICIAL_ONLY_DIAGNOSTIC_NOT_CORROBORATED')
        self.assertAlmostEqual(sum(row['expected_minutes'] for row in p['home']),240)
        with self.assertRaisesRegex(ValueError,'PLAYER_MINUTES_PIT_CLOCK_OR_KIND'):
            validate_minutes(probe,asof_utc=NOW)
        with TemporaryDirectory() as tmp,self.assertRaises(ValueError):
            MinutesArchive(tmp).record(probe)

    def test_official_only_diagnostic_never_trusts_unpinned_or_stale_source(self):
        data=inputs()
        url='https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-16_10_45AM.pdf'
        data['review'].update(official_pdf_clock_verified=True,official_stage='FIXTURE_ROWS',
            official_code='SOURCE_ROWS_MATCHED_NOT_MEDICALLY_VERIFIED',
            official_report=dict(source_url=url,report_timestamp_utc=NOW-900))
        data['review']['sources'].append(dict(url=url,observed_at_utc=NOW-10))
        data['review']['records']=[dict(team_id='1',player_id='100',status='Out',
            source='NBA_OFFICIAL_PDF',identity_status='EXACT_ESPN_ROSTER_MATCH',
            status_updated_at_utc=NOW-900)]
        for kind in ('unverified','wrong_date','stale','no_receipt','unmatched_identity','wrong_clock','conflict'):
            altered=deepcopy(data)
            if kind=='unverified':altered['review']['official_pdf_clock_verified']=False
            elif kind=='wrong_date':
                altered['review']['official_report']['source_url']=url.replace('2026-11-16','2026-11-15')
            elif kind=='stale':
                altered['review']['official_report']['source_url']=url.replace('10_45AM','10_00AM')
                altered['review']['official_report']['report_timestamp_utc']=NOW-3600
                altered['review']['records'][0]['status_updated_at_utc']=NOW-3600
            elif kind=='no_receipt':altered['review']['sources'].pop()
            elif kind=='unmatched_identity':altered['review']['records'][0]['identity_status']='PLAYER_ID_NOT_VERIFIED'
            elif kind=='wrong_clock':altered['review']['records'][0]['status_updated_at_utc']+=60
            else:
                altered['review']['records'].append(dict(team_id='1',player_id='100',status='Available',
                    source='ESPN',status_updated_at_utc=NOW-10))
            with self.subTest(kind=kind),self.assertRaises(Abstain):
                projection(**altered,diagnostic_official_only=True)

    def test_espn_day_to_day_and_nba_uncertain_is_not_an_out_available_conflict(self):
        for official in ('Probable','Questionable','Doubtful'):
            data=inputs()
            data['review']['records']=[
                dict(team_id='1',player_id='100',source='ESPN',status='Day-To-Day',
                     status_updated_at_utc=NOW-20),
                dict(team_id='1',player_id='100',source='NBA_OFFICIAL_PDF',status=official,
                     status_updated_at_utc=NOW-10)]
            self.assertEqual(status_relationship(data['review']['records']),
                'BROAD_TRACKER_WITH_UNCERTAIN_OFFICIAL_NOT_CONTRADICTORY')
            with self.subTest(status=official),self.assertRaisesRegex(
                    Abstain,'UNCERTAIN_AVAILABILITY_NO_PLAYING_PROBABILITY_GUESS'):
                projection(**data)

    def test_true_player_status_conflict_still_stops_projection(self):
        records=[dict(team_id='1',player_id='100',source='ESPN',status='Out',
                      status_updated_at_utc=NOW-20),
                 dict(team_id='1',player_id='100',source='NBA_OFFICIAL_PDF',status='Available',
                      status_updated_at_utc=NOW-10)]
        self.assertEqual(status_relationship(records),'CONFLICTING_STATUS_DESIGNATIONS')
        data=inputs();data['review']['records']=records
        with self.assertRaisesRegex(Abstain,'CONFLICTING_PLAYER_STATUS_NO_MINUTE_GUESS'):
            projection(**data)
        records[0]['status']='Day-To-Day'
        self.assertEqual(status_relationship(records),'CONFLICTING_STATUS_DESIGNATIONS')

    def test_telegram_ambiguous_status_display_is_not_misleading(self):
        records=[
            dict(team_id='1',player_id='100',team_name='Test Home',player_name='A B',
                 source='ESPN',status='Day-To-Day',status_updated_at_utc=NOW-60,
                 note='',identity_status='SOURCE_PLAYER_ID'),
            dict(team_id='1',player_id='100',team_name='Test Home',player_name='B,A',
                 source='NBA_OFFICIAL_PDF',status='Questionable',status_updated_at_utc=NOW-30,
                 note='',identity_status='EXACT_ESPN_ROSTER_MATCH')]
        review=dict(status='CURRENT_SOURCE_OBSERVATIONS',observed_at_utc=NOW,
                    records=records,sources=[],warnings=[])
        shown=render_review(review)
        self.assertIn('kesin çelişki değildir',shown)
        self.assertNotIn('Kaynak durumları uyuşmuyor',shown)
        records[1]['status']='Out'
        shown=render_review(review)
        self.assertIn('Kaynak durumları uyuşmuyor',shown)

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

    def test_new_minutes_publication_respects_five_minute_cutoff(self):
        for lead in (301,300,299):
            w=projection(**inputs(start=NOW+lead))
            with TemporaryDirectory() as tmp:
                a=MinutesArchive(tmp)
                if lead==301:
                    self.assertTrue(a.record(w)[1])
                else:
                    with self.assertRaisesRegex(ValueError,'AFTER_PREMATCH_CUTOFF'):
                        a.record(w)
                    self.assertFalse(list(Path(tmp).glob('minutes-*')))

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

    def test_latest_directory_access_is_part_of_source_availability_clock(self):
        data=inputs()
        data['rosters']['home']['observed_at_utc']=NOW-6
        packet=projection(**data)['payload']
        self.assertEqual(packet['source_available_max_utc'],NOW-6)


def test_missing_recent_player_uses_older_same_team_games_only_with_official_availability():
    data=inputs()
    data['rosters']['home']['players'].append('999')
    data['review'].update(official_pdf_clock_verified=True,official_stage='FIXTURE_ROWS',
                          official_code='SOURCE_ROWS_MATCHED_NOT_MEDICALLY_VERIFIED')
    data['review']['records']=[dict(team_id='1',player_id='999',status='Available',
        source='NBA_OFFICIAL_PDF',identity_status='EXACT_ESPN_ROSTER_MATCH',status_updated_at_utc=NOW-20)]
    for i in range(3):
        older=deepcopy(data['boxes'][0])
        earlier=NOW-(7+i)*86400
        older.update(fixture_id='older-'+str(i),fixture_start_utc=earlier,
                     source=dict(observed_at_utc=earlier+12000,ingested_at_utc=earlier+12001))
        older['players'][0]['player_id']='999'
        data['boxes'].append(older)
    with patch('time.time',return_value=NOW), TemporaryDirectory() as folder:
        observed=projection(**data)
        assert observed['payload']['extended_rotation_player_ids']==['999']
        assert sum(p['expected_minutes'] for p in observed['payload']['home'])==pytest.approx(240)
        assert validate_witness(archive_inputs(folder,data),folder)==observed['payload']
        for box in data['boxes'][-3:]:
            box['home_team_id']='4'  # Native minutes on another club do not transfer.
            box['players'][0]['team_id']='4'
        with pytest.raises(Abstain,match='CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY'):
            projection(**data)
