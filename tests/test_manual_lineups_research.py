"""Synthetic local manual-input tests; no Lineups requests or actual source data."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.team_identity import digest
from hybrid_engine.current_roster import PREFIX
from hybrid_engine.manual_lineups_research import audit,parse_csv,capture,fixture_context
from tests.test_phase91 import ten_game_ledger
from tests.test_season_archive_audit import NOW

HEADER='player,team,opponent,projected_minutes\n'


def context():
    return dict(league='NBA',season='2026/2027',fixture_id='fixture',
        fixture_start_utc=NOW+3600,prediction_generated_at_utc=NOW-60,
        home=dict(provider_id='1',official_name='Home Club'),
        away=dict(provider_id='2',official_name='Away Club'))


def data():
    return (HEADER+'Player One,Home Club,Away Club,32.5\nPlayer Two,Away Club,Home Club,28\n').encode()


def test_manual_partial_rows_do_not_infer_missing_minutes():
    with patch('time.time',return_value=NOW):
        result=audit(data(),context())
    assert result['source_publication_utc'] is None
    assert not result['eligible_for_fit'] and not result['source_document_verified']
    assert result['teams']['home']['projected_total_minutes']==32.5
    assert result['teams']['home']['difference_from_240']==-207.5
    assert result['teams']['home']['rows'][0]['espn_player_id'] is None
    assert not result['teams']['home']['complete_roster_identity']
    assert not result['normalized_to_240']


@pytest.mark.parametrize('bad',[
    HEADER+'Player One,Home Club,Other Club,32\nPlayer Two,Away Club,Home Club,28\n',
    HEADER+'Player One,Home Club,Away Club,49\nPlayer Two,Away Club,Home Club,28\n',
    HEADER+'Player One,Home Club,Away Club,32\nPlayer One,Away Club,Home Club,28\n',
    HEADER+'Player One,Home Club,Away Club,NaN\nPlayer Two,Away Club,Home Club,28\n',
    HEADER+'Player One,Home Club,Away Club,32\n',
])
def test_invalid_manual_rows_refused(bad):
    with pytest.raises(ValueError):parse_csv(bad.encode(),context())


def receipt(root,side,ctx):
    team=ctx[side]
    names=['Player One'] if side=='home' else ['Player Two']
    names += [side+' Reserve '+str(i) for i in range(7)]
    document=dict(team=dict(id=team['provider_id'],displayName=team['official_name']),
        season=dict(year=2027),athletes=[dict(id=str(int(team['provider_id'])*100+i),displayName=n) for i,n in enumerate(names)])
    raw=json.dumps(document).encode()
    metadata=dict(status='RECEIVED',url=PREFIX+'teams/'+team['provider_id']+'/roster?season=2027',
        started_at_utc=NOW-2,observed_at_utc=NOW-1,body_sha256=hashlib.sha256(raw).hexdigest())
    path=root/('source-'+digest(metadata)+'.json')
    path.write_text(json.dumps(dict(metadata,body_hex=raw.hex())))
    return path


def test_replays_existing_roster_and_keeps_absent_rows_unknown(tmp_path):
    ctx=context();h=receipt(tmp_path,'home',ctx);a=receipt(tmp_path,'away',ctx)
    with patch('time.time',return_value=NOW):
        result=audit(data(),ctx,home_roster=h,away_roster=a)
        assert result['teams']['home']['rows'][0]['espn_player_id']=='100'
        assert len(result['teams']['home']['missing_roster_player_ids'])==7
        assert not result['teams']['home']['complete_roster_identity']
        assert not result['eligible_for_fit']
        value=json.loads(h.read_text());value['body_hex']='00';h.write_text(json.dumps(value))
        with pytest.raises(ValueError):audit(data(),ctx,home_roster=h,away_roster=a)


def test_strict_cutoff():
    ctx=context();ctx['fixture_start_utc']=NOW+300
    with patch('time.time',return_value=NOW),pytest.raises(ValueError,match='PREMATCH_WINDOW_CLOSED'):
        audit(data(),ctx)


def test_local_ledger_binding_and_immutable_separate_archive(tmp_path):
    db=tmp_path/'ledger.sqlite';_,games=ten_game_ledger(db,count=2)
    before=db.read_bytes();fixture=games[1]['provider_fixture_ids'][0]
    ctx=fixture_context(db,fixture)
    file=tmp_path/'manual.csv'
    file.write_text(HEADER+'Player One,'+ctx['home']['official_name']+','+ctx['away']['official_name']+',32\n'
                    +'Player Two,'+ctx['away']['official_name']+','+ctx['home']['official_name']+',28\n')
    with patch('time.time',return_value=NOW):
        root=tmp_path/'manual-lineups-research'
        report=capture(db,fixture,file,output_directory=root)
        assert report['context']['fixture_id']==games[1]['canonical_id']
        assert len(list(root.glob('manual-*.json')))==1
        assert not report['eligible_for_fit']
        assert db.read_bytes()==before
        with pytest.raises(ValueError,match='SEPARATE_DIRECTORY'):
            capture(db,fixture,file,output_directory=tmp_path/'minutes')
