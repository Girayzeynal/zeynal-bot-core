"""Optional isolated-bot bridge. Market failures leave frozen score output visible."""
import html
import time

from core.team_identity import digest
from hybrid_engine.market_observations import ObservationStore, fixture_identity, from_espn
from hybrid_engine.market_views import assess, render, replay_nba
from hybrid_engine.prediction_audit import Assets


def nba_panel(snapshot,service,rows,store,*,asof_utc=None):
    from hybrid_engine.decision_audit import trace_for
    from hybrid_engine.decision_layer import QuoteEvidence
    now=int(time.time()) if asof_utc is None else asof_utc
    trace=trace_for(snapshot)
    fixture=fixture_identity({k:trace[k] for k in ('league','season','fixture_id','home_team_id','away_team_id','tipoff_utc')})
    manual=store.read(fixture,asof_utc=now);observations=[];rejected=0
    for row in rows:
        try:
            receipt=Assets(service.assets).read(row['source_ref'])
            native=row['native_observation'];observation=from_espn(native,receipt)
            quote=QuoteEvidence.from_espn(native,trusted_sha256=native['sha256'])
            observations.append((observation,quote))
        except (ValueError,KeyError,TypeError,OSError):
            rejected+=1
    observations.extend((w,None) for w in manual)
    if not observations:
        return dict(html='<b>PİYASA GÖZLEMLERİ</b>\nDoğrulanabilir kaynak kanıtı olan barem yok; model skoru korunuyor.',observations=0,lines=0,rejected=rejected)
    distribution=replay_nba(snapshot,service)
    parts=['<b>KAYNAKTAN BAĞIMSIZ PİYASA ARAŞTIRMASI</b>',
        'Aynı kaynak görüntüsündeki alternatif baremler ayrı tutulur; farklı platformların fiyatları birleştirilmez.',
        'Dağılım: arşivdeki model/girdilerden SHA doğrulamalı tekrar üretim. Yeni tahmin veya kalibrasyon değil.']
    count=0
    for observation,quote in observations:
        view=assess(observation,distribution,asof_utc=now,native_quote=quote)
        parts.append(render(view));count+=len(view['rows'])
    if rejected:parts.append('Kaynak bağı doğrulanamayan gözlem sayısı: '+str(rejected))
    return dict(html='\n\n'.join(parts),observations=len(observations),lines=count,rejected=rejected)


def euroleague_panel(report,archive,store,*,forward_registry=None):
    """Read-only manual lines for frozen / explicitly published forward EL records."""
    from hybrid_engine.decision_layer import DecisionDistribution
    from hybrid_engine.intervals import prediction_intervals
    from hybrid_engine.data import Cut
    now=int(time.time());record=report.get('record')
    if record is not None:
        g=record['fixture']
        fixture=fixture_identity(dict(league='EUROLEAGUE',season=f"{g['season_start_year']}/{g['season_start_year']+1}",
            fixture_id=g['canonical_id'],home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],tipoff_utc=g['start_ts_utc']))
        rows=store.read(fixture,asof_utc=now)
        if not rows:return None
        f=archive.replay(record,'BAYES_QMC')
        trace=dict(fixture,model_version=f.model,model_digest=record['models']['BAYES_QMC']['model_digest'],
            prediction_utc=record['created_at_utc'],inputs_available_max_utc=record['source_data_time_utc'])
        warning='Tarihsel arşiv: üretim ve ilk kalıcı kayıt zamanı ayrı kanıtlanmadı. Bahis kararı değil.'
    elif report.get('status')=='FORWARD_EUROLEAGUE_OK' and forward_registry is not None:
        options=[r for r in forward_registry.records() if digest(r['payload'])==report['forecast_sha256']]
        if len(options)!=1:raise ValueError('MARKET_FORWARD_EL_PUBLICATION_REQUIRED')
        p=options[0]['payload'];g=p['fixture']
        fixture=fixture_identity(dict(league='EUROLEAGUE',season=f"{g['season_start_year']}/{g['season_start_year']+1}",
            fixture_id=g['canonical_id'],home_team_id=g['home_team_id'],away_team_id=g['away_team_id'],tipoff_utc=g['start_ts_utc']))
        rows=store.read(fixture,asof_utc=now)
        if not rows:return None
        from hybrid_engine.forward_validation import frozen_model
        model,artifact=frozen_model(archive)
        cuts=[r for r in p['assets'] if r['file'].startswith('cut-')]
        prepared=[r for r in p['assets'] if r['file'].startswith('prepared-')]
        if len(cuts)!=1 or len(prepared)!=1 or forward_registry.read_asset(prepared[0])!=artifact:
            raise ValueError('MARKET_FORWARD_EL_INPUT_OR_MODEL_PIN')
        f=model.predict(Cut(**forward_registry.read_asset(cuts[0])),method='RQMC_HALTON',bounded_workspace=True)
        if prediction_intervals(f)['sample_sha256']!=p['components']['BAYES_QMC']['intervals']['sample_sha256']:
            raise ValueError('MARKET_FORWARD_EL_SAMPLE_PIN')
        trace=dict(fixture,model_version=f.model,
            model_digest=digest(dict(forward_version=p['version'],component='BAYES_QMC',prepared=prepared[0]['sha256'])),
            prediction_utc=p['prediction_generated_at_utc'],inputs_available_max_utc=p['source_available_max_utc'])
        warning='Önceden yayımlanmış ileri kayıt ve aynı dondurulmuş örnekler; yeni tahmin değil.'
    else:return None
    d=DecisionDistribution(f,trace)
    return '\n\n'.join(['<b>EUROLEAGUE | MANUEL PİYASA GÖZLEMİ</b>',html.escape(warning),
        *[render(assess(w,d,asof_utc=now)) for w in rows]])
