"""Track A read-only local inventory. No download, ledger write or scheduler."""
import argparse
from datetime import datetime,timezone
import json
import sqlite3
from pathlib import Path
import time

from faz40_archive import require
from faz40_archive_audit import load_nba,load_euro,file_sha
from faz41_adapters import capture
from faz42_history import inventory,evaluate


def cached_players(folder):
    root=Path(folder).resolve();paths=[root/'access-initial.json',root/'espn.json',root/'euroleague.json',root/'eurocup.json',
                                    root/'el-stats-debug.json',root/'ec-stats-debug.json']
    proofs={str(p):file_sha(p) for p in paths}
    access={p['name']:p for p in json.loads(paths[0].read_text())};rows=[]
    for name,league,provider in [('espn','NBA','ESPN'),('el','EUROLEAGUE','EUROLEAGUE_LIVE'),('ec','EUROCUP','EUROLEAGUE_LIVE')]:
        if name=='espn':
            stamp=access['espn'];raw=json.loads((root/'espn.json').read_text());observed=stamp['observed_utc']
            require(stamp['source_url']=='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401909922' and
                    raw['header']['id']=='401909922' and stamp['http_status']==200 and stamp['status']=='JSON_RECEIVED','CACHED_SOURCE_MANIFEST_MISMATCH')
        else:
            group='euroleague' if name=='el' else 'eurocup';game=json.loads((root/(group+'.json')).read_text())
            stats=json.loads((root/(name+'-stats-debug.json')).read_text())
            expected='https://api-live.euroleague.net/v2/competitions/'+('E/seasons/E2026/games/87' if name=='el' else 'U/seasons/U2026/games/91')
            require(access[group]['source_url']==expected and access[group]['http_status']==200 and
                    stats['source_url']==expected+'/stats' and stats['status']=='DOCUMENT_RECEIVED','CACHED_SOURCE_MANIFEST_MISMATCH')
            raw=dict(game=game,stats=stats['payload']);observed=max(stats['observed_at_utc'],access[group]['observed_utc'])
        rows.append(capture(raw,provider=provider,league=league,season_end_year=2027,observed_at_utc=observed,
                            ingested_at_utc=int(time.time()),data_type='PLAYER_MINUTES'))
    require(all(file_sha(p)==sha for p,sha in proofs.items()),'CACHED_SOURCE_CHANGED')
    return rows,proofs


def run(nba_database,*,euro_evidence=None,player_cache=None,train_end_utc,validation_end_utc):
    archive,source=load_nba(nba_database);sources=[source]
    if euro_evidence:
        extra,src=load_euro(euro_evidence);archive+=extra;sources.append(src)
    observations=[]
    for item in archive:
        p=item['payload'];f=p['facts']
        observations.append(capture(p['raw'],provider=f['provider'],league=f['league'],season_end_year=f['season_end_year'],
            observed_at_utc=p['source_observed_utc'],ingested_at_utc=int(time.time())))
    cache={}
    if player_cache:
        extra,cache=cached_players(player_cache);observations+=extra
    # Wait a real clock tick: never invent an as-of timestamp after materialization.
    if observations:
        last=max(o['payload']['materialized_at_utc'] for o in observations)
        if int(time.time())<=last:time.sleep(1.05)
    asof=int(time.time());report=inventory(observations,asof_utc=asof)
    reports={league:evaluate(observations,league=league,season_end_year=2027,train_end_utc=train_end_utc,
                            validation_end_utc=validation_end_utc,asof_utc=asof) for league in ('NBA','EUROLEAGUE','EUROCUP')}
    require(all(file_sha(s['source'])==s['sha256'] for s in sources) and all(file_sha(p)==sha for p,sha in cache.items()),'SOURCE_ARCHIVE_CHANGED')
    return dict(status='READ_ONLY_FAZ42_AUDIT',inventory=report,evaluation=reports,sources=sources,cached_source_sha256=cache,
        cache_provenance='RECONSTRUCTED_FROM_UNSIGNED_LOCAL_MANIFEST_NOT_PROSPECTIVE',
        original_archive_timestamps_not_used_as_new_ingestion=True,prospective_records_created=0,
        production_coefficients_changed=False,independent_source_attestation=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('nba_database');p.add_argument('--euro-evidence');p.add_argument('--player-cache')
    p.add_argument('--train-end-utc',type=int,required=True);p.add_argument('--validation-end-utc',type=int,required=True);a=p.parse_args()
    try:r=run(a.nba_database,euro_evidence=a.euro_evidence,player_cache=a.player_cache,train_end_utc=a.train_end_utc,validation_end_utc=a.validation_end_utc)
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as ex:
        print(json.dumps(dict(status='ABSTAIN_AUDIT_FAILED',reason=str(ex) if type(ex) is ValueError else type(ex).__name__)));return 1
    print(json.dumps(r,sort_keys=True,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
