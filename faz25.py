"""Opt-in local NBA polling, bounded retries and FAZ24 collection. No deployment."""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from providers.espn_adapter import ESPN_BASE
from providers.espn_scheduled_fixture import parse_scheduled_nba_fixture
from prediction_ledger import PredictionLedger


@contextmanager
def exclusive(database):
    with open(str(database)+'.faz25.lock','a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            yield False;return
        try: yield True
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


def validate_schedule(payloads):
    fixtures, starts = {}, {}
    for payload in payloads:
        if not isinstance(payload,dict) or not isinstance(payload.get('events'),list):
            raise ValueError('schedule unavailable or malformed')
        for raw in payload['events']:
            row=parse_scheduled_nba_fixture(raw)
            if row is None:
                try:
                    status=raw['competitions'][0].get('status',raw.get('status'))['type']
                    if (status.get('state'),status.get('completed')) in (('post',True),('in',False)): continue
                except (KeyError,TypeError,IndexError,AttributeError): pass
                raise ValueError('unverifiable schedule event')
            key=row['provider_fixture_id']
            start=(row['start_ts_utc'],row['home_team_id'],row['away_team_id'])
            if key in fixtures and fixtures[key] != row: raise ValueError('conflicting schedule identity')
            if start in starts and starts[start] != key: raise ValueError('alias fixture IDs at same start')
            for previous in fixtures.values():
                if previous['provider_fixture_id'] != key and previous['start_ts_utc']==row['start_ts_utc'] and set((previous['home_team_id'],previous['away_team_id'])).intersection((row['home_team_id'],row['away_team_id'])):
                    raise ValueError('same-team schedule start conflict')
            starts[start]=key;fixtures[key]=row
    return sorted(fixtures.values(),key=lambda r:(r['start_ts_utc'],r['provider_fixture_id']))


class Poller:
    def __init__(self, database, *, timeout=180, max_fixtures=2, lead_seconds=21600):
        if timeout <= 0 or type(max_fixtures) is not int or not 1 <= max_fixtures <= 10 or not 300 <= lead_seconds <= 86400:
            raise ValueError('invalid polling limits')
        self.ledger=PredictionLedger(str(database));self.timeout=timeout
        self.max_fixtures=max_fixtures;self.lead=lead_seconds
        with self.ledger._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS faz25_attempts (
                task TEXT PRIMARY KEY, attempts INTEGER NOT NULL, next_utc INTEGER NOT NULL,
                status TEXT NOT NULL, error_type TEXT, observed_utc INTEGER NOT NULL)''')

    def due(self, task):
        with self.ledger._connect() as db:
            row=db.execute('SELECT next_utc FROM faz25_attempts WHERE task=?',(task,)).fetchone()
        return row is None or row[0] <= int(time.time())

    def record(self, task, status, error=None):
        now=int(time.time())
        with self.ledger._connect() as db:
            row=db.execute('SELECT attempts FROM faz25_attempts WHERE task=?',(task,)).fetchone()
            attempts=(row[0] if row else 0)+1
            delay=min(3600,60*2**min(attempts-1,6)) if error else 300
            db.execute('INSERT OR REPLACE INTO faz25_attempts VALUES (?,?,?,?,?,?)',
                       (task,attempts,now+delay,status,error,now))

    async def attempt(self, task, action):
        try:
            result=await asyncio.wait_for(action(),timeout=self.timeout)
            status=result.get('status','collected')
            error=None if status in ('collected','accepted','awaiting_tipoff','awaiting_final') else 'UnverifiedResult'
            self.record(task,status,error)
            return dict(task=task,status=status)
        except (ValueError,TypeError,KeyError,RuntimeError,OSError,sqlite3.Error,asyncio.TimeoutError) as exc:
            self.record(task,'retry_pending',type(exc).__name__)
            return dict(task=task,status='retry_pending',error_type=type(exc).__name__)

    async def tick(self, *, schedule, collect, reconcile):
        with exclusive(self.ledger.db_path) as acquired:
            if not acquired: return dict(status='busy',actions=[])
            actions=[]
            with self.ledger._connect() as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='faz24_stages'").fetchone()
                known=db.execute('SELECT fixture_id FROM faz24_stages').fetchall() if exists else []
            # Result work is independent of schedule service availability.
            with self.ledger._connect() as db:
                next_times=dict(db.execute("SELECT task,next_utc FROM faz25_attempts"))
            known.sort(key=lambda row:next_times.get('result:'+row[0],0))
            result_attempts=0
            for (fixture,) in known:
                with self.ledger._connect() as db:
                    done=db.execute("SELECT 1 FROM outcomes WHERE league='NBA' AND fixture_id=?",(fixture,)).fetchone()
                task='result:'+fixture
                if not done and self.due(task) and result_attempts < self.max_fixtures:
                    result_attempts+=1
                    actions.append(await self.attempt(task,lambda f=fixture:reconcile(f)))
            if not self.due('schedule'): return dict(status='schedule_cooldown',actions=actions)
            try:
                rows=validate_schedule(await asyncio.wait_for(schedule(),timeout=self.timeout))
                self.record('schedule','available')
            except (ValueError,TypeError,RuntimeError,OSError,asyncio.TimeoutError) as exc:
                self.record('schedule','retry_pending',type(exc).__name__)
                return dict(status='schedule_unavailable',error_type=type(exc).__name__,actions=actions)
            processed=0
            for row in rows:
                now=int(time.time());fixture=row['provider_fixture_id'];task='collect:'+fixture
                if not now < row['start_ts_utc'] <= now+self.lead: continue
                with self.ledger._connect() as db:
                    existing=db.execute("SELECT 1 FROM predictions WHERE league='NBA' AND fixture_id=?",(fixture,)).fetchone()
                if existing or not self.due(task): continue
                if processed >= self.max_fixtures: break
                actions.append(await self.attempt(task,lambda r=row:collect(r)))
                processed+=1
            return dict(status='polled',scheduled_fixtures=len(rows),actions=actions,
                        observed_utc=int(time.time()),provider='ESPN')


def backup(database, destination):
    """Consistent, owner-only, no-clobber local snapshot for explicit external transfer."""
    import os
    import tempfile
    import hashlib
    destination=Path(destination)
    with tempfile.TemporaryDirectory(dir=destination.parent) as folder:
        temporary=Path(folder)/'ledger.sqlite'
        with sqlite3.connect('file:'+str(Path(database).resolve())+'?mode=ro',uri=True) as source:
            with sqlite3.connect(temporary) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone() != ('ok',): raise ValueError('backup integrity failure')
        os.chmod(temporary,0o600)
        # Hard-link publication is atomic and refuses an existing destination.
        os.link(temporary,destination)
    return dict(status='backed_up',sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),external_uploaded=False)


class BaselineUnavailable(ValueError):
    pass


async def refresh_baseline(adapter, history, store, team, team_id):
    """Reuse date-scoped verified history; team schedule endpoints may omit finals."""
    from baseline.team_baseline_store import TeamBaseline
    games=await history.fetch_verified_games(team_id,as_of_utc=datetime.now(timezone.utc),
        days=21,minimum=6,regular_season_only=True)
    if games is None: raise BaselineUnavailable('insufficient verified finals')
    selected=games[-10:]
    for game in selected:
        evidence=await adapter.fetch_pace_evidence(game)
        if evidence is None: raise BaselineUnavailable('box-score evidence unavailable')
        home=game['home_team_id']==team_id
        if not home and game['away_team_id']!=team_id: raise BaselineUnavailable('wrong team')
        store.append_game('NBA',team,
            game['actual_home'] if home else game['actual_away'],
            game['actual_away'] if home else game['actual_home'],evidence['pace'],home,
            ts_utc=game['start_ts_utc'],game_id=game['provider_fixture_id'],
            source=evidence['method'],timestamp_precision='exact',pace_evidence=evidence)
    data=store.compute_dynamic_baseline('NBA',team,len(selected))
    if data is None: raise BaselineUnavailable('historical aggregate unavailable')
    baseline=TeamBaseline('NBA',team,data['n_games'],data['pts_for'],data['pts_against'],
                          data['pace'],data['stdev_total'],int(time.time()))
    store.put(baseline)
    return baseline


async def run(args):
    import subprocess
    repo=Path(__file__).resolve().parent
    version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=repo,text=True):
        raise ValueError('clean source checkout required')
    from providers.espn_adapter import ESPNAdapter
    from baseline.team_baseline_store import TeamBaselineStore,TeamBaselineBootstrapper
    from faz13_engine import Faz13Engine,PrematchRequest
    from faz23_engine import Faz23Engine
    from faz24 import collect
    from providers.espn_bound_results import reconcile_bound_result
    import tempfile
    adapter=ESPNAdapter(allow_estimated_pace=True)
    store=TeamBaselineStore(args.baselines);poller=Poller(args.database)
    engine=Faz13Engine('','',baseline_store=store);engine.espn=adapter
    from providers.espn_scoreboard_history import ESPNScoreboardHistory
    history=ESPNScoreboardHistory()
    day_cache={}
    fetch_day=history._fetch_day
    async def cached_day(day):
        if day not in day_cache:
            events=await fetch_day(day)
            if events is not None: day_cache[day]=events
            return events
        return day_cache[day]
    history._fetch_day=cached_day
    async def schedule():
        day=datetime.now(timezone.utc).date()
        return [await adapter._get_json(f'{ESPN_BASE}/scoreboard?dates={(day+timedelta(days=i)):%Y%m%d}')
                for i in (-1,0,1)]
    async def collect_one(row):
        teams=await adapter._load_teams()
        names={}
        for side in ('home','away'):
            matches=[t['team']['abbreviation'] for t in (teams or [])
                     if str(t.get('team',{}).get('id'))==row[side+'_team_id']]
            if len(matches)!=1: raise ValueError('source team directory unavailable or ambiguous')
            names[side]=matches[0]
            baseline=await refresh_baseline(adapter,history,store,names[side],row[side+'_team_id'])
            if baseline is None: raise ValueError('verified baseline unavailable')
            series=store.get_series('NBA',names[side],baseline.n_games)
            for record in series:
                ev=record.pace_evidence
                if not ev or not 0 <= int(time.time())-ev['snapshot']['observed_at_utc'] <= 21600:
                    raise ValueError('source observations stale or unverified')
        date=datetime.fromtimestamp(row['start_ts_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()
        with tempfile.TemporaryDirectory() as folder:
            finalizer=Faz23Engine(str(Path(folder)/'decisions.sqlite'))
            result=await collect(engine=engine,request=PrematchRequest(0,'NBA',date,names['home'],names['away']),
                adapter=adapter,ledger=poller.ledger,model_version=version,finalizer=finalizer,expected_fixture=row)
            if result['fixture'] != row: raise ValueError('resolved schedule changed')
            return result
    failed=False
    try:
        for cycle in range(args.cycles):
            day_cache.clear()
            result=await poller.tick(schedule=schedule,collect=collect_one,
                reconcile=lambda fixture:reconcile_bound_result(adapter=adapter,ledger=poller.ledger,fixture_id=fixture))
            failed = failed or result['status']=='schedule_unavailable' or any(a['status']=='retry_pending' for a in result['actions'])
            print(json.dumps(result,sort_keys=True),flush=True)
            if cycle+1<args.cycles: await asyncio.sleep(args.interval)
    finally:
        await adapter.aclose()
        await history.aclose()
    return int(failed)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('poll');q.add_argument('database');q.add_argument('baselines')
    q.add_argument('--cycles',type=int,default=1);q.add_argument('--interval',type=int,default=300)
    q=sub.add_parser('backup');q.add_argument('database');q.add_argument('destination')
    args=p.parse_args(argv)
    try:
        if args.command=='backup': print(json.dumps(backup(args.database,args.destination)))
        else:
            if not 1<=args.cycles<=288 or args.interval<60: raise ValueError('bounded cycles and interval >=60 required')
            return asyncio.run(run(args))
        return 0
    except (ValueError,OSError,sqlite3.Error,RuntimeError) as exc:
        print(json.dumps(dict(status='failed',error_type=type(exc).__name__)));return 1


if __name__=='__main__': raise SystemExit(main())
