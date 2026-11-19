"""Read-only prospective EuroLeague reports, distinct from the old five-game cohort."""
from collections import defaultdict
from core.team_identity import digest
from hybrid_engine.live_metrics import metrics
from ledger_reports import render_accuracy,render_compare


class ForwardEuroLeagueReports:
    def __init__(self,service,fallback):self.service=service;self.fallback=fallback

    def read(self,league=None,fixture_id=None):
        if league is None or league.upper()!='EUROLEAGUE':
            return dict(source='fallback',report=self.fallback.read(league,fixture_id))
        rows=[];groups=defaultdict(list)
        for item in self.service.registry.independent_records():
            if not item['publication']['eligible_for_prospective_audit']:continue
            p=item['payload'];g=p['fixture'];fid=g['canonical_id']
            if fixture_id and fixture_id not in [fid,*g['provider_fixture_ids']]:continue
            names=self.service._pair(p);o=self.service.registry.outcome(p)
            for component,m in p['components'].items():
                if m['status']!='FORECAST_CREATED':continue
                q=m['prediction'];model=digest(dict(version=p['version'],component=component))
                r=dict(fixture_id=fid,league='EUROLEAGUE',season=f"{g['season_start_year']}/{g['season_start_year']+1}",model_version=component,model_digest=model,
                    prediction=[q['home'],q['away']],created_utc=p['snapshot_created_at_utc'],snapshot_sha256=digest(p),
                    fixture_start_utc=g['start_ts_utc'],predicted_quarters=q['quarters'],winner=q.get('winner'),intervals=m['intervals'],
                    predicted_halves=q.get('halves'),prediction_generated_at_utc=p['prediction_generated_at_utc'],
                    first_archived_at_utc=item['publication']['first_archived_at_utc'],
                    home=names[0],away=names[1],actual=None if o is None else [sum(o['periods'][s][:4]) for s in ('home','away')])
                if o:
                    receipt=self.service.registry.read_asset(o['source'])
                    r.update(actual_periods=o['periods'],final_with_ot=o['full_final'],label_available_utc=receipt['ingested_at_utc'])
                rows.append(r)
                if o:groups[(component,model)].append(r)
        if fixture_id and not rows:
            return dict(source='fallback',report=self.fallback.read(league,fixture_id))
        summaries=[]
        for (name,model),values in sorted(groups.items()):
            d=metrics(values)
            summaries.append(dict(league='EUROLEAGUE',model_digest=model,model_version=name,n=len(values),
                team_mae=d['team_scores']['mae'],team_rmse=d['team_scores']['rmse'],total_mae=d['total']['mae'],details=d))
        r=dict(status='VERIFIED_LIVE_REPORT',scope='REGULATION_ONLY',groups=summaries,forecasts=rows,
               unique_fixtures=len({r['fixture_id'] for r in rows}),pending=sum(r['actual'] is None for r in rows),
               research_backtests_included=False,query_read_only=True,cohort_policy='FIRST_ISSUED_PER_FIXTURE',confidence_index=None)
        return dict(source='forward',report=r)

    def render_accuracy(self,r):
        if r['source']=='fallback':return self.fallback.render_accuracy(r['report'])
        return ('İZOLE EUROLEAGUE İLERİYE DÖNÜK ARAŞTIRMA\n'+render_accuracy(r['report'])+
                '\nEski beş maçın ayrı üretim/arşiv saati kanıtlanmayan kayıtları bu kohorta dahil değil.')

    def render_compare(self,r):
        if r['source']=='fallback':return self.fallback.render_compare(r['report'])
        return 'İZOLE EUROLEAGUE İLERİYE DÖNÜK ARAŞTIRMA\n'+render_compare(r['report'])
