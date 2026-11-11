"""Read-only local archive research. No provider calls or prediction-ledger writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from faz40_archive import seal_game,require
from faz40_research import walk_forward
from nba_research_store import ResearchStore
from providers.euroleague_live import replay_pace_evidence


def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_nba(path,*,usage='RETROSPECTIVE_RESEARCH'):
    path=Path(path).resolve()
    require(Path('/data') not in path.parents and path.is_file(),'RESEARCH_DATABASE_REQUIRED')
    require(not any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')),
            'STATIC_RESEARCH_SNAPSHOT_REQUIRED')
    with path.open('rb') as stream:header=stream.read(100)
    if not header.startswith(b'SQLite format 3\x00'):raise sqlite3.DatabaseError('Invalid research database')
    # A WAL-mode main file without sidecars is not a certified standalone
    # snapshot. Refuse before SQLite can create WAL/SHM beside a read-only file.
    require(header[18:20]==b'\x01\x01','STATIC_RESEARCH_SNAPSHOT_REQUIRED')
    before=file_sha(path)
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        require(db.execute('PRAGMA integrity_check').fetchone()==('ok',),'ARCHIVE_SQLITE_INTEGRITY')
        ids=json.loads(db.execute("SELECT value FROM metadata WHERE key='team_ids'").fetchone()[0])
    # Do not invoke constructor: it creates schema/changes metadata and mode.
    store=object.__new__(ResearchStore);store.path=str(path);store.team_ids=set(ids)
    observations=store.observations();records=[]
    for row in observations:
        p=row['payload'];records.append(seal_game(p['summary'],league='NBA',
            season_end_year=p['summary']['header']['season']['year'],source_observed_utc=p['source_observed_utc'],
            ingested_utc=p['ingested_utc'],team_ids=ids,usage=usage))
    require(file_sha(path)==before,'SOURCE_ARCHIVE_CHANGED')
    return records,dict(source=str(path),sha256=before,unchanged=True,observations=len(observations),
                        distinct_provider_games=len({p['payload']['facts']['event']['provider_fixture_id'] for p in observations}))


def load_euro(path,*,usage='RETROSPECTIVE_RESEARCH'):
    path=Path(path).resolve();before=file_sha(path);doc=json.loads(path.read_text())
    records=[]
    for league in ('EUROLEAGUE','EUROCUP'):
        groups=[g for g in doc['results'] if g['league']==league]
        require(len(groups)==1,'EXPLICIT_EURO_COMPETITION_REQUIRED')
        estimates=groups[0]['estimates']
        teams=sorted({e['snapshot']['game'][side]['club']['code'] for e in estimates for side in ('local','road')})
        for e in estimates:
            replayed=replay_pace_evidence(e);p=e['snapshot']
            require(replayed['league']==league,'EURO_SOURCE_COMPETITION_MISMATCH')
            records.append(seal_game(p['game'],league=league,season_end_year=p['year']+1,
                source_observed_utc=p['observed_at_utc'],ingested_utc=doc['observed_at_utc'],team_ids=teams,usage=usage))
    require(file_sha(path)==before,'SOURCE_ARCHIVE_CHANGED')
    return records,dict(source=str(path),sha256=before,unchanged=True,observations=len(records),
                        catalog_counts_not_used_as_period_samples=True)


def run(nba_database,*,euro_evidence=None,season_end_year=2027,simulations=10000,usage='RETROSPECTIVE_RESEARCH'):
    require(type(simulations) is int and simulations>=10000,'MINIMUM_10000_SIMULATIONS_REQUIRED')
    records,source=load_nba(nba_database,usage=usage);sources=[source]
    if euro_evidence:
        extra,src=load_euro(euro_evidence,usage=usage);records+=extra;sources.append(src)
    reports={}
    for league in ('NBA','EUROLEAGUE','EUROCUP'):
        if usage=='SYNTHETIC_TEST':
            reports[league]={mode:walk_forward(records,league=league,season_end_year=season_end_year,
                mode=mode,simulations=simulations) for mode in ('INGESTION_TIME','ARCHIVED_SOURCE_CLOCK')}
        else:
            games=len({r['payload']['facts']['canonical_id'] for r in records if r['payload']['league']==league and r['payload']['season_end_year']==season_end_year})
            reports[league]={mode:dict(status='ABSTAIN_SOURCE_BOUND_HISTORY_REQUIRED',input_games=games,evaluated_games=0,
                metrics=None,folds=[],availability_policy=mode,usage=usage,prospective_records_created=0,
                migration='Use pinned v2 source evidence through faz47_readiness') for mode in ('INGESTION_TIME','ARCHIVED_SOURCE_CLOCK')}
    for src in sources:require(file_sha(src['source'])==src['sha256'],'SOURCE_ARCHIVE_CHANGED')
    return dict(status='READ_ONLY_RESEARCH_AUDIT_COMPLETE' if usage=='SYNTHETIC_TEST' else 'ABSTAIN_SOURCE_BOUND_HISTORY_REQUIRED',sources=sources,reports=reports,usage=usage,
                simulations_per_eligible_game=simulations,prospective_records_created=0,
                source_attestation='NOT_INDEPENDENTLY_VERIFIED',production_coefficients_changed=False,
                historical_source_clock_is_not_live_performance=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('nba_database');p.add_argument('--euro-evidence')
    p.add_argument('--simulations',type=int,default=10000);p.add_argument('--synthetic',action='store_true');args=p.parse_args()
    try:result=run(args.nba_database,euro_evidence=args.euro_evidence,simulations=args.simulations,
                   usage='SYNTHETIC_TEST' if args.synthetic else 'RETROSPECTIVE_RESEARCH')
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:
        print(json.dumps(dict(status='ARCHIVE_AUDIT_FAILED',error_type=type(exc).__name__,prospective_records_created=0)))
        return 1
    print(json.dumps(result,sort_keys=True,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
