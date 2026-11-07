"""Retrospective research preparation report. No original forecasts are rewritten."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import subprocess
import time
from nba_research_store import ResearchStore
from historical_research import examples_from_store
from shadow_ridge import train,walk_forward


def read_store(database):
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as db:
        ids=json.loads(db.execute("SELECT value FROM metadata WHERE key='team_ids'").fetchone()[0])
    # Avoid initializing or migrating the inspected store.
    store=object.__new__(ResearchStore);store.path=str(database);store.team_ids=set(ids)
    return store


def export_live_periods(database,destination):
    """Actual-time materialization for future FAZ31 captures, never old cutoffs."""
    from period_feature_layer import materialize_period,export_observations
    from faz32_collect import write_json
    store=read_store(database);records=[]
    for r in store.select(int(time.time()),'PROSPECTIVE'):
        p=r['payload']
        records.append(materialize_period(p['summary'],source_observed_utc=p['source_observed_utc'],source_evidence_sha256=r['sha256'],
            input_ref=dict(research_observation_id=r['observation_id'],ingested_utc=p['ingested_utc'])))
    records=export_observations(records)
    sha=write_json(Path(destination),records)
    return dict(path=str(destination),sha256=sha,distinct_games=len(records),usage='FUTURE_CAPTURES_ONLY',predictions_created=0)


def report(database):
    store=read_store(database)
    examples,rejected=examples_from_store(store)
    version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parent,text=True).strip()
    root=Path(__file__).resolve().parent
    changed=subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],cwd=root,text=True).splitlines()
    dirty=any(not row.startswith('?? ') or row.endswith('.py') for row in changed)
    if len(examples)>=100 and dirty:
        trained=dict(status='NOT_TRAINED',reason='CLEAN_SOURCE_COMMIT_REQUIRED')
        folds=dict(status='CLEAN_SOURCE_COMMIT_REQUIRED',folds=[],models_promoted=False)
    else:
        trained=train(examples,version,research=True)
        folds=walk_forward(examples,version,research=True)
    result=dict(coverage=store.coverage(),retrospective_examples=len(examples),original_prospective_feature_label_pairs_created=0,
        excluded=Counter(r['reason'] for r in rejected),excluded_details=rejected,
        missing_features=Counter(m for r in rejected for m in r['missing']),
        training=trained,historical_walk_forward=folds,source_version=version,source_worktree_dirty=dirty,
        examples=examples,required_examples=100,additional_ready_examples_needed=max(0,100-len(examples)),
        usage='RETROSPECTIVE_RESEARCH_ONLY',production_promoted=False,
        live_eligibility='Research source-clock reconstruction is not an original precomputed forecast')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('database');p.add_argument('--export-live-periods');args=p.parse_args()
    result=export_live_periods(args.database,args.export_live_periods) if args.export_live_periods else report(args.database)
    print(json.dumps(result,sort_keys=True,allow_nan=False))
