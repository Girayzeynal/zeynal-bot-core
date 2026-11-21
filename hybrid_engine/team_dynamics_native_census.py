"""Read-only census of real period observations inside original NBA snapshots.

Do not turn original-game history averages into newly issued forecasts.
The original snapshot and input-cut source pins, clocks and original source
archive identity must be re-audited before any history evidence is counted.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from team_dynamics_evidence import build, digest

VERSION='NATIVE_ORIGINAL_PREGAME_TEAM_DYNAMICS_CENSUS_V1'


def profile(snapshot, original, cut):
    if digest(snapshot)!=original['snapshot_sha256']:
        raise ValueError('DYNAMICS_QUALITY_SNAPSHOT_PIN_CONFLICT')
    ref=snapshot['input_asset']
    if digest(cut)!=ref['sha256']:
        raise ValueError('DYNAMICS_ORIGINAL_INPUT_ASSET_PIN_CONFLICT')
    if (cut['target']['fixture_id']!=snapshot['fixture_id'] or
        cut['target']['fixture_start_utc']!=snapshot['fixture_start_utc'] or
        cut['target']['home_team_id']!=snapshot['home']['provider_id'] or
        cut['target']['away_team_id']!=snapshot['away']['provider_id'] or
        cut['cutoff_utc']!=snapshot['feature_cutoff_utc'] or
        not 0<cut['cutoff_utc']<=snapshot['prediction_generated_at_utc']<snapshot['fixture_start_utc']):
        raise ValueError('DYNAMICS_ORIGINAL_CUT_IDENTITY_CLOCK_CONFLICT')
    if (cut['target']['league']!=snapshot['league'] or
        cut['target']['season']!=snapshot['season'] or
        cut['evaluation_class']!='PIT_PROVEN_BACKTEST'):
        raise ValueError('DYNAMICS_NATIVE_STRICT_SCOPE_REQUIRED')
    request=dict(league=snapshot['league'],season=snapshot['season'],
        fixture_id=snapshot['fixture_id'],home_team_id=snapshot['home']['provider_id'],
        away_team_id=snapshot['away']['provider_id'],
        decision_utc=snapshot['prediction_generated_at_utc'],
        tipoff_utc=snapshot['fixture_start_utc'])
    history=[]
    for row in cut['history']:
        observed=row['observed_at_utc'];ingested=row['ingested_at_utc']
        if type(observed) is not int or type(ingested) is not int or not (
            row['fixture_start_utc']<observed<=ingested<=cut['cutoff_utc']):
            raise ValueError('DYNAMICS_HISTORICAL_ARRIVAL_AFTER_FROZEN_CUT')
        history.append(dict(league=row['league'],season=row['season'],fixture_id=row['fixture_id'],
            fixture_start_utc=row['fixture_start_utc'],
            home_team_id=row['home_team_id'],away_team_id=row['away_team_id'],
            available_at_utc=ingested,source_catalog_sha256=row['source_catalog_sha256'],
            periods=row['periods']))
    research=build(request,history,evidence_basis='SHA_PINNED_ORIGINAL_CUT_AUDITED_SOURCE_RECEIPTS')
    return research


def brief(report):
    def side(label):
        x=report[label];h=x['all_games']['per_quarter_for'];v=x['by_venue']
        return dict(team_id=x['team_id'],n=x['observations'],
            observed_scoring_quarter_means=None if h is None else [round(i['mean'],3) for i in h],
            observed_home_games=v['home']['n'],observed_away_games=v['away']['n'],
            opponent_count=len(x['by_opponent']),
            player_injury_coach_context_verified=False)
    return dict(fixture_id=report['fixture_id'],
        observed_source_fixtures=report['num_native_history_fixtures'],
        original_head_to_head_count=report['original_head_to_head_count'],
        home=side('target_home'),away=side('target_away'))


def inspect(quality,ledger,assets,*,limit=8):
    from hybrid_engine.prediction_audit import Assets,audit_snapshot
    from live_analysis_ledger import LiveAnalysisLedger
    q=Path(quality).expanduser().absolute()
    dbp=Path(ledger).expanduser().absolute()
    root=Path(assets).expanduser().absolute()
    if (q.is_symlink() or dbp.is_symlink() or root.is_symlink() or
        not q.is_file() or not dbp.is_file() or not root.is_dir() or q.stat().st_size>64*1024*1024):
        raise ValueError('DYNAMICS_EXISTING_READONLY_NATIVE_INPUTS_REQUIRED')
    wrapper=json.loads(q.read_text())
    if digest(wrapper.get('payload'))!=wrapper.get('sha256'):
        raise ValueError('DYNAMICS_SIGNED_ORIGINAL_REPORT_REQUIRED')
    payload=wrapper['payload'];audit=payload['archive_audit'];perf=audit['performance']
    if (payload['format']!='PHASE92_READ_ONLY_QUALITY_REPORT_V1' or
        audit['performance_status']!='READ_ONLY_NATIVE_VERIFIED' or perf['status']!='VERIFIED_LIVE_REPORT'):
        raise ValueError('DYNAMICS_NATIVE_QUALITY_REPORT_REQUIRED')
    forecasts=[f for f in perf['forecasts'] if f['league']=='NBA']
    if len(forecasts)>1000:
        raise ValueError('DYNAMICS_ARCHIVE_BUDGET')
    cases=[];source=Assets(root)
    with closing(sqlite3.connect(dbp.as_uri()+'?mode=ro',uri=True,timeout=.3)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        for record in forecasts:
            key=(record['league'],record['fixture_id'],record['model_digest'])
            data=db.execute('SELECT CASE WHEN length(CAST(payload AS BLOB))<=524288 THEN payload END, sha256 FROM live_analysis_snapshots WHERE league=? AND fixture_id=? AND model_digest=?',key).fetchone()
            if not data or data[0] is None:
                raise ValueError('DYNAMICS_PINNED_ORIGINAL_LEDGER_MISSING')
            snapshot=LiveAnalysisLedger._decode(data[0],data[1],expected=key)
            audit_result=audit_snapshot(snapshot,root,replay=False)
            if audit_result.get('frozen_history_features_reconstructed') is not True:
                raise ValueError('DYNAMICS_NATIVE_INPUT_RECONSTRUCTION_UNVERIFIED')
            original_cut=source.read(snapshot['input_asset'])
            cases.append(brief(profile(snapshot,record,original_cut)))
    return dict(format=VERSION,original_quality_report_sha256=wrapper['sha256'],
        original_native_forecasts=len(forecasts),
        native_profiles=len(cases),
        profiles_with_both_team_histories=sum(bool(c['home']['n'] and c['away']['n']) for c in cases),
        total_original_history_fixture_observations=sum(c['observed_source_fixtures'] for c in cases),
        sampled_profiles=cases[:limit],
        observed_source_counts_are_not_independent_fixture_universe=True,
        current_player_injury_coach_context_available=False,
        directional_betting_accuracy=None,
        no_retrospective_replacement_predictions=True,
        original_forecasts_changed=False,positive_original_cases_changed=False,
        production_changed=False,
        warning='READONLY TEAM-SPECIFIC HISTORICAL PERIOD COVERAGE ONLY. NOT AN NBA MATCH FORECAST. PLAYER, INJURY AND COACH CONTEXT STILL NOT VERIFIED.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('report','ledger','assets'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--examples',type=int,default=8)
    args=parser.parse_args()
    if not 0<=args.examples<=54:
        raise ValueError('DYNAMICS_EXAMPLE_BUDGET')
    print(json.dumps(inspect(args.report,args.ledger,args.assets,limit=args.examples),
                     ensure_ascii=False,sort_keys=True,indent=2))


if __name__=='__main__':main()
