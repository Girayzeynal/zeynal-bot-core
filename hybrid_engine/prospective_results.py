"""Append official results and comparisons alongside immutable pregame records."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import local_path
from hybrid_engine.evaluation import summarize
from hybrid_engine.frozen_archive import FrozenArchive,read_gzip
from hybrid_engine.source_policy import ControlledTransport
from season_archive_collect import fetch_document
from season_archive_inventory import archive_catalog
from hybrid_engine.statistics import calibration_curve,paired_cluster_interval,paired_winner_interval
from hybrid_engine.markets import wilson

OFFICIAL='https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games'


class ProspectiveResults:
    def __init__(self,archive,directory):
        self.archive=archive;self.path=local_path(directory)

    def _catalog(self,receipt,now):
        if (receipt.get('provider')!='EUROLEAGUE_LIVE' or receipt.get('source_url')!=OFFICIAL or
            receipt.get('status')!='DOCUMENT_RECEIVED' or receipt.get('http_status')!=200 or
            digest(receipt['document'])!=receipt['document_sha256'] or
            not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now):raise ValueError('OFFICIAL_RESULT_RECEIPT_REQUIRED')
        return archive_catalog(receipt['document'],provider='EUROLEAGUE_LIVE',season_start_year=2026,
            observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'])

    def ingest(self,receipt):
        now=int(time.time());catalog=self._catalog(receipt,now)
        self.path.mkdir(parents=True,exist_ok=True)
        raw=(json.dumps(receipt,sort_keys=True,allow_nan=False)+'\n').encode();z=gzip.compress(raw,mtime=0)
        source=self.path/('source-'+hashlib.sha256(z).hexdigest()+'.json.gz')
        try:
            with source.open('xb') as f:f.write(z)
        except FileExistsError:
            if source.read_bytes()!=z:raise ValueError('RESULT_SOURCE_CONFLICT')
        final={g['canonical_id']:g for g in catalog['payload']['fixtures'] if g['completed'] and g['periods'] is not None}
        inserted=[];pending=[]
        existing=self.outcomes()
        for fid,p in self.archive.records.items():
            g=final.get(fid)
            if g is None:pending.append(fid);continue
            old=p['fixture']
            if (any(g[k]!=old[k] for k in ('start_ts_utc','home_team_id','away_team_id')) or
                not set(g['provider_fixture_ids'])&set(old['provider_fixture_ids']) or
                not p['created_at_utc']<g['start_ts_utc']<receipt['observed_at_utc']):raise ValueError('FINAL_IDENTITY_OR_CLOCK_CONFLICT')
            actual=[sum(g['periods'][s][:4]) for s in ('home','away')]
            if fid in existing:
                prior=existing[fid]
                if prior['periods']!=g['periods'] or prior['final_with_ot']!=g['final_scores']:raise ValueError('OFFICIAL_RESULT_CORRECTION_REQUIRES_REVIEW')
                continue
            r=dict(format='OFFICIAL_FROZEN_FORECAST_RESULT_V1',fixture_id=fid,provider_fixture_ids=g['provider_fixture_ids'],
                scope='REGULATION_ONLY',actual=actual,final_with_ot=g['final_scores'],periods=g['periods'],
                forecast_sha256=digest(p),created_at_utc=now,source_file=source.name,
                source_sha256=hashlib.sha256(z).hexdigest(),source_document_sha256=receipt['document_sha256'],
                observed_at_utc=receipt['observed_at_utc'],fixture_start_utc=g['start_ts_utc'])
            publish_json(self.path/('result-'+digest(r)+'.json'),dict(payload=r,sha256=digest(r)))
            inserted.append(fid)
        return dict(inserted=inserted,pending=pending,source=source.name,source_observed_at_utc=receipt['observed_at_utc'])

    def outcomes(self):
        result={}
        if not self.path.exists():return result
        for f in sorted(self.path.glob('result-*.json')):
            d=json.loads(f.read_text());r=d['payload'];fid=r['fixture_id']
            if digest(r)!=d['sha256'] or f.stem!='result-'+d['sha256']:raise ValueError('RESULT_PAYLOAD_PIN')
            p=self.archive.records.get(fid)
            if p is None or digest(p)!=r['forecast_sha256']:raise ValueError('RESULT_FORECAST_PIN')
            source=local_path(self.path/r['source_file'])
            if source.parent!=self.path or hashlib.sha256(source.read_bytes()).hexdigest()!=r['source_sha256']:raise ValueError('RESULT_SOURCE_PIN')
            receipt=read_gzip(source);catalog=self._catalog(receipt,int(time.time()))
            if (receipt['document_sha256']!=r['source_document_sha256'] or receipt['observed_at_utc']!=r['observed_at_utc'] or
                r['created_at_utc']<receipt['ingested_at_utc']):raise ValueError('RESULT_TRACE_CONFLICT')
            candidates=[g for g in catalog['payload']['fixtures'] if g['canonical_id']==fid and g['completed'] and g['periods']]
            if len(candidates)!=1:raise ValueError('OFFICIAL_FINAL_MISSING')
            g=candidates[0]
            if (g['periods']!=r['periods'] or g['final_scores']!=r['final_with_ot'] or
                [sum(g['periods'][s][:4]) for s in ('home','away')]!=r['actual'] or
                g['start_ts_utc']!=p['fixture']['start_ts_utc'] or not p['created_at_utc']<g['start_ts_utc']<receipt['observed_at_utc']):
                raise ValueError('OFFICIAL_FINAL_SCORE_OR_CLOCK_CONFLICT')
            if fid in result and result[fid]['actual']!=r['actual']:raise ValueError('CONFLICTING_FINAL_VERSIONS')
            result[fid]=r
        return result

    def comparison(self):
        outcomes=self.outcomes();models=defaultdict(list)
        for fid,p in self.archive.records.items():
            if fid not in outcomes:continue
            o=outcomes[fid];q=np.array([o['periods'][s][:4] for s in ('home','away')]).T
            for name,m in p['models'].items():
                if m['status']!='FORECAST_CREATED':continue
                models[name].append(dict(fixture_id=fid,start_utc=p['fixture']['start_ts_utc'],actual=o['actual'],actual_quarters=q.tolist(),
                    prediction=m['prediction'],seconds=m['prediction']['metadata'].get('elapsed_seconds',0.),markets={}))
        summaries={n:summarize(rows) for n,rows in models.items()};per_fixture=[]
        for n,rows in models.items():
            valid=[r for r in rows if r['prediction']['winner'] is not None]
            hits=sum(int(np.argmax(r['prediction']['winner']))==(0 if r['actual'][0]>r['actual'][1] else 1 if r['actual'][0]==r['actual'][1] else 2) for r in valid)
            summaries[n]['winner_accuracy']=dict(n=len(valid),correct=hits,rate=hits/len(valid) if valid else None,wilson_95=wilson(hits,len(valid)))
            summaries[n]['winner_calibration']={key:calibration_curve([r['prediction']['winner'][i] for r in valid],
                [int((0 if r['actual'][0]>r['actual'][1] else 1 if r['actual'][0]==r['actual'][1] else 2)==i) for r in valid])
                for i,key in enumerate(('home','tie','away'))}
            summaries[n]['bias_classification']='DESCRIPTIVE_OVERPREDICTION' if summaries[n]['team_scores']['bias']>0 else 'DESCRIPTIVE_UNDERPREDICTION'
            summaries[n]['bias_classification_is_significance_claim']=False
            for row in rows:
                q=np.asarray(row['prediction']['quarters'])-np.asarray(row['actual_quarters']);team=q.sum(axis=0)
                per_fixture.append(dict(fixture_id=row['fixture_id'],model=n,actual=row['actual'],
                    home_error=float(team[0]),away_error=float(team[1]),total_error=float(team.sum()),margin_error=float(team[0]-team[1]),
                    quarter_errors=q.tolist(),half_errors=[q[:2].sum(axis=0).tolist(),q[2:].sum(axis=0).tolist()]))
        return dict(format='FROZEN_PROSPECTIVE_COMPARISON_V1',settled_games=len(outcomes),pending_games=len(self.archive.records)-len(outcomes),
            models=summaries,scope='REGULATION_ONLY',per_fixture_errors=per_fixture,
            paired_vs_faz13={n:dict(points=paired_cluster_interval(models.get('FAZ13_MC',[]),rows),
                winner=paired_winner_interval(models.get('FAZ13_MC',[]),rows)) for n,rows in models.items() if n!='FAZ13_MC'},
            calibration_fit_performed=False,confidence_index=None,
            recommendation='COLLECT_MORE_DISJOINT_PROSPECTIVE_CASES;DO_NOT_FIT_ON_THIS_TEST_SET',
            superiority_claim=False,production_changed=False)


class ResearchReports:
    def __init__(self,results):self.results=results
    def read(self,league=None,fixture_id=None):
        if league and league.upper() not in ('NBA','EUROLEAGUE','EUROCUP'):raise ValueError('UNKNOWN_LEAGUE')
        outcomes=self.results.outcomes();rows=[]
        if league is None or league.upper()=='EUROLEAGUE':
            for fid,p in self.results.archive.records.items():
                if fixture_id and fixture_id not in (fid,p['fixture']['provider_fixture_id']):continue
                for n,m in p['models'].items():
                    if m['status']=='FORECAST_CREATED':rows.append(dict(name=n,fixture=p['fixture'],model=m,actual=outcomes.get(fid,{}).get('actual')))
        comparison=self.results.comparison() if league is None or league.upper()=='EUROLEAGUE' else dict(settled_games=0,pending_games=0,models={})
        return dict(rows=rows,comparison=comparison,research_only=True)
    def render_accuracy(self,r):
        c=r['comparison'];lines=['ZEYNAL | İZOLE PROSPEKTİF ARAŞTIRMA | Normal süre',f"Sonuçlanan maç: {c['settled_games']} | Bekleyen: {c['pending_games']}"]
        if not c['models']:lines.append('Doğrulanmış final yok; performans ve kalibrasyon hesaplanmadı.')
        for n,m in c['models'].items():lines.append(f"{n} | n={m['n']} | MAE {m['team_scores']['mae']:.2f} | RMSE {m['team_scores']['rmse']:.2f}")
        lines.append('Araştırma kayıtlarıdır; üretim başarı oranı veya doğrulanmış güven yüzdesi değildir.')
        return '\n'.join(lines)
    def render_compare(self,r):
        if not r['rows']:return 'Bu lig/maç için izole araştırma kaydı yok.'
        lines=['ZEYNAL | DONDURULMUŞ MODEL KARŞILAŞTIRMASI | Araştırma']
        for row in r['rows']:
            p=row['model']['prediction'];a=row['actual']
            lines.append(f"{row['name']} | {p['home']:.2f} – {p['away']:.2f} | "+('Sonuç bekleniyor' if a is None else f'Gerçek {a[0]} – {a[1]}'))
        return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive-directory',required=True);p.add_argument('--output-directory',required=True)
    p.add_argument('--derive-intervals',action='store_true')
    args=p.parse_args();archive=FrozenArchive(args.archive_directory);results=ProspectiveResults(archive,args.output_directory)
    receipt=ControlledTransport(fetch_document)('EUROLEAGUE_LIVE',OFFICIAL)
    capture=results.ingest(receipt);report=dict(capture=capture,comparison=results.comparison())
    if args.derive_intervals:
        from hybrid_engine.intervals import derive_frozen_bands,empirical_coverage
        path,bands=derive_frozen_bands(archive,results.path/'derived-intervals');outcomes=results.outcomes();cases={}
        for item in bands['items']:
            if item['fixture_id'] not in outcomes:continue
            for model,b in item['models'].items():cases.setdefault(model,[]).append((b,outcomes[item['fixture_id']]['periods']))
        report['interval_diagnostics']=dict(path=str(path),coverage={n:empirical_coverage(v) for n,v in cases.items()},
            intervals_pre_registered_before_results=False,confidence_calibration_proven=False)
    target=local_path(args.output_directory)/('comparison-'+digest(report)+'.json');publish_json(target,report)
    print(json.dumps(dict(path=str(target),**report)))


if __name__=='__main__':main()
