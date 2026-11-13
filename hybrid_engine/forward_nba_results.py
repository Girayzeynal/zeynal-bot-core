"""Read an isolated NBA ledger; append finals/reports without changing snapshots."""
import argparse
from contextlib import closing
import json
import sqlite3

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.decision_audit import FinalArchive,score_audit
from season_archive_collect import fetch_document


def read_confirmed(path):
    path=local_path(path)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute('SELECT s.payload,s.sha256,r.snapshot_sha256,r.completed_utc FROM live_analysis_snapshots s JOIN live_analysis_commit_receipts r USING(league,fixture_id,model_digest)').fetchall()
    output=[]
    for raw,pin,receipt_pin,archived in rows:
        p=json.loads(raw)
        if digest(p)!=pin or pin!=receipt_pin or p['league']!='NBA':raise ValueError('NBA_FORWARD_SNAPSHOT_PIN')
        if not p['prediction_generated_at_utc']<=p['created_at_utc']<=archived<p['fixture_start_utc']:raise ValueError('NBA_FORWARD_COMMIT_CLOCK')
        output.append(dict(snapshot=p,snapshot_sha256=pin))
    return output


def collect(ledger,output_directory,*,fetcher=fetch_document):
    records=read_confirmed(ledger);root=local_path(output_directory);root.mkdir(parents=True,exist_ok=True)
    finals=FinalArchive(root/'finals');captures=[]
    for record in records:
        p=record['snapshot'];pid=p['provider_fixture_ids'][0]
        if not str(pid).isascii() or not str(pid).isdigit():raise ValueError('NBA_FORWARD_PROVIDER_ID')
        receipt=fetcher('ESPN','https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+pid)
        if receipt.get('status')!='DOCUMENT_RECEIVED':captures.append(dict(fixture_id=p['fixture_id'],status='SOURCE_UNAVAILABLE'));continue
        captures.append(finals.ingest(receipt,p))
    report=score_audit(records,finals.read([r['snapshot'] for r in records]));report.update(captures=captures,calibration_fit=False)
    path=root/('comparison-'+digest(report)+'.json');publish_json(path,dict(payload=report,sha256=digest(report)))
    return dict(path=str(path),settled=report['settled_independent_forecasts'],pending=report['pending_independent_forecasts'])


def report_euroleague(registry):
    """Post-result report for the new batch, kept outside first-capture records."""
    from collections import defaultdict
    import numpy as np
    from hybrid_engine.evaluation import summarize
    from hybrid_engine.intervals import empirical_coverage
    rows=defaultdict(list);bands=defaultdict(list);pending=0
    for item in registry.records():
        p=item['payload'];fid=p['fixture']['canonical_id'];files=list(registry.root.glob('outcome-'+fid+'-*.json'))
        if not files:pending+=1;continue
        w=json.loads(files[0].read_text());o=w['payload']
        if digest(o)!=w['sha256'] or o['forecast_sha256']!=digest(p):raise ValueError('FORWARD_COMPARISON_PIN')
        registry.read_asset(o['source'])
        if not item['publication']['eligible_for_prospective_audit']:continue
        q=np.asarray([o['periods'][s][:4] for s in ('home','away')]).T
        for name,m in p['components'].items():
            if m['status']!='FORECAST_CREATED':continue
            rows[name].append(dict(fixture_id=fid,start_utc=p['fixture']['start_ts_utc'],actual=q.sum(axis=0).tolist(),
                actual_quarters=q.tolist(),prediction=m['prediction'],seconds=0.,markets={}))
            bands[name].append((m['intervals'],o['periods']))
    metrics={name:summarize(values) for name,values in rows.items()}
    for m in metrics.values():m.pop('runtime_seconds',None)
    report=dict(format='FORWARD_EUROLEAGUE_COMPARISON_V1',metrics=metrics,pending=pending,
        coverage={name:empirical_coverage(values) for name,values in bands.items()},
        market_status='MARKET_UNAVAILABLE',calibration_status='UNCALIBRATED',calibration_fit=False,production_changed=False)
    path=registry.root/('report-'+digest(report)+'.json');publish_json(path,dict(payload=report,sha256=digest(report)))
    return dict(path=str(path),pending=pending,metrics=metrics)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ledger',required=True);p.add_argument('--output-directory',required=True);a=p.parse_args()
    print(json.dumps(collect(a.ledger,a.output_directory)))


if __name__=='__main__':main()
