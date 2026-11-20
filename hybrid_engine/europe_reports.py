"""Read-only combined European listing; unknown legacy publication clocks stay unknown."""
from collections import defaultdict

from core.league_identity import resolve_league
from core.team_identity import digest
from hybrid_engine.live_metrics import metrics
from ledger_reports import render_accuracy,render_compare


class EuropeanReports:
    def __init__(self,service,legacy_results=None,extra_services=()):
        self.service=service;self.legacy_results=legacy_results;self.extra_services=extra_services

    def read(self,league=None,fixture_id=None):
        code=self.service.league
        if league is not None and resolve_league(league).code!=code:raise ValueError('EUROPE_REPORT_LEAGUE_MISMATCH')
        rows=[];cohorts=defaultdict(list);legacy_fids=set()
        if code=='EUROLEAGUE' and self.legacy_results is not None:
            outcomes=self.legacy_results.outcomes()
            for fid,p in self.legacy_results.archive.records.items():
                g=p['fixture'];ids=[g['provider_fixture_id']]
                if fixture_id and fixture_id not in [fid,*ids]:continue
                legacy_fids.add(fid);outcome=outcomes.get(fid)
                snapshot_pin=digest(p)
                for name,m in p['models'].items():
                    if m['status']!='FORECAST_CREATED':continue
                    q=m['prediction'];r=dict(fixture_id=fid,league=code,season=f"{g['season_start_year']}/{g['season_start_year']+1}",
                        model_version=name,model_digest=m.get('model_digest',digest(dict(forecast=snapshot_pin,component=name))),
                        provider_fixture_ids=ids,home=g['home_name'],away=g['away_name'],prediction=[q['home'],q['away']],
                        fixture_start_utc=g['start_ts_utc'],created_utc=p['created_at_utc'],
                        prediction_generated_at_utc=p.get('prediction_generated_at_utc'),first_archived_at_utc=p.get('first_archived_at_utc'),
                        snapshot_sha256=snapshot_pin,actual=None if outcome is None else outcome['actual'],
                        legacy_publication_clock_unrecorded=True,eligible_for_live_performance=False)
                    if outcome:r.update(actual_periods=outcome['periods'],final_with_ot=outcome['final_with_ot'])
                    rows.append(r)
        sources=[(service,item) for service in (self.service,*self.extra_services) for item in service.registry.independent_records()]
        sources.sort(key=lambda v:(v[1]['publication']['first_archived_at_utc'],digest(v[1]['payload'])))
        seen=set(legacy_fids)
        for service,item in sources:
            p=item['payload'];g=p['fixture'];fid=g['canonical_id'];ids=g['provider_fixture_ids']
            if fid in seen or (fixture_id and fixture_id not in [fid,*ids]):continue
            seen.add(fid)
            pair=service.pair(p);outcome=service.registry.outcome(p)
            snapshot_pin=digest(p);label_clock=None
            if outcome and any(m['status']=='FORECAST_CREATED' for m in p['components'].values()):
                # All components share this exact native final witness. Validate
                # and read it once, retaining the same source/identity checks.
                label_clock=service.registry.read_asset(outcome['source'])['ingested_at_utc']
            for name,m in p['components'].items():
                if m['status']!='FORECAST_CREATED':continue
                q=m['prediction'];version=digest(dict(version=p['version'],component=name))
                r=dict(fixture_id=fid,league=code,season=f"{g['season_start_year']}/{g['season_start_year']+1}",
                    model_version=name,model_digest=version,provider_fixture_ids=ids,home=pair[0],away=pair[1],
                    prediction=[q['home'],q['away']],predicted_quarters=q['quarters'],predicted_halves=q['halves'],winner=q.get('winner'),
                    intervals=m['intervals'],fixture_start_utc=g['start_ts_utc'],created_utc=p['snapshot_created_at_utc'],
                    prediction_generated_at_utc=p['prediction_generated_at_utc'],first_archived_at_utc=item['publication']['first_archived_at_utc'],
                    snapshot_sha256=snapshot_pin,actual=None if outcome is None else [sum(outcome['periods'][s][:4]) for s in ('home','away')],
                    eligible_for_live_performance=item['publication']['eligible_for_prospective_audit'])
                if outcome:
                    r.update(actual_periods=outcome['periods'],final_with_ot=outcome['full_final'],label_available_utc=label_clock)
                    if r['eligible_for_live_performance']:cohorts[(r['season'],name,version)].append(r)
                rows.append(r)
        groups=[]
        for (season,name,version),values in sorted(cohorts.items()):
            d=metrics(values);groups.append(dict(league=code,season=season,model_version=name,model_digest=version,n=len(values),
                team_mae=d['team_scores']['mae'],team_rmse=d['team_scores']['rmse'],total_mae=d['total']['mae'],details=d))
        return dict(status='VERIFIED_LIVE_REPORT',league=code,scope='REGULATION_ONLY',forecasts=rows,groups=groups,
            unique_fixtures=len({r['fixture_id'] for r in rows}),pending=sum(r['actual'] is None for r in rows),
            research_backtests_included=False,query_read_only=True,confidence_index=None,
            legacy_fixtures=len(legacy_fids),legacy_publications_excluded_from_live_metrics=True)

    def render_accuracy(self,r):
        # Keep legacy rows visible in listing/compare but never give unknown
        # generation/first-publication times a fabricated live-accuracy history.
        measured=dict(r,forecasts=[v for v in r['forecasts'] if v.get('eligible_for_live_performance')])
        return ('İZOLE '+self.service.league+' HİBRİT ARAŞTIRMA\n'+render_accuracy(measured)+
            '\nİlk kalıcı yayın zamanı ayrı kanıtlanmayan eski kayıtlar canlı metriklere katılmadı.')

    def render_compare(self,r):
        return 'İZOLE '+self.service.league+' HİBRİT ARAŞTIRMA\n'+render_compare(r)


class EuropeanReportRouter:
    def __init__(self,prior,readers):self.prior=prior;self.readers=readers
    def read(self,league=None,fixture_id=None):
        code=resolve_league(league).code if league else 'NBA'
        if code in self.readers:return dict(europe=code,report=self.readers[code].read(code,fixture_id))
        return dict(europe=None,report=self.prior.read(league,fixture_id))
    def render_accuracy(self,r):
        return (self.readers[r['europe']] if r['europe'] else self.prior).render_accuracy(r['report'])
    def render_compare(self,r):
        return (self.readers[r['europe']] if r['europe'] else self.prior).render_compare(r['report'])
