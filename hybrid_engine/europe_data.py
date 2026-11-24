"""Current European provider observations; never mutate or retrain an issued forecast."""
import argparse
import html
import json
import re
import threading
import time
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
from bs4 import BeautifulSoup
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Cut,local_path
from hybrid_engine.europe_source_probe import fetch,inspect,PATHS,BASE
from hybrid_engine.provider_bridge import render as render_provider
from telegram_delivery import tsi


class EuropeanEvidenceCapacityError(ValueError):
    pass


def context(view,league):
    g=view['fixture'];p=view['payload'];q=view['prediction']
    return dict(format='EUROPE_ARCHIVED_FORECAST_VIEW_CONTEXT_V1',league=league,season=f"{g['season_start_year']}/{g['season_start_year']+1}",
        fixture_id=g['canonical_id'],provider_fixture_ids=g['provider_fixture_ids'],fixture_start_utc=g['start_ts_utc'],
        home=dict(provider_id=g['home_team_id'],official_name=view['pair'][0]),
        away=dict(provider_id=g['away_team_id'],official_name=view['pair'][1]),
        prediction_generated_at_utc=view['generated'],first_archived_at_utc=view['archived'],
        model_version=q['model'],model_digest=view['version'],intervals=view['bands'],
        parameter_fit_cutoff_utc=q.get('metadata',{}).get('fit_cutoff_utc'),
        input_clocks=[dict(ingested_at_utc=p.get('source_available_max_utc',p.get('source_data_time_utc')))],
        original_forecast_sha256=view['forecast_sha256'])


def article_rows(receipt,ctx,now):
    """Official source text only, NOT independently verified player availability."""
    if receipt.get('status')!='RECEIVED':return []
    import hashlib
    if hashlib.sha256(receipt['body'].encode()).hexdigest()!=receipt['body_sha256']:
        raise ValueError('EUROPE_NEWS_BODY_PIN')
    from hybrid_engine.europe_source_probe import allowed
    if not allowed(receipt['url'],ctx['league']) or not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=now:
        raise ValueError('EUROPE_NEWS_SOURCE_CLOCK')
    soup=BeautifulSoup(receipt['body'],'html.parser');articles=[]
    for tag in soup.find_all('script',type='application/ld+json')[:20]:
        try:node=json.loads(tag.string or tag.get_text())
        except (ValueError,TypeError):continue
        nodes=node if isinstance(node,list) else node.get('@graph',[node]) if isinstance(node,dict) else []
        articles.extend(n for n in nodes if isinstance(n,dict) and n.get('@type') in ('NewsArticle','Article'))
    results=[]
    for a in articles:
        headline=a.get('headline','');body=a.get('articleBody')
        if not isinstance(headline,str) or 'injur' not in headline.lower() or not isinstance(body,str):continue
        try:
            at=datetime.fromisoformat(a['datePublished'].replace('Z','+00:00'))
            if at.tzinfo is None:continue
            published=int(at.timestamp())
        except (ValueError,KeyError,TypeError):continue
        if not 0<published<=now<ctx['fixture_start_utc'] or now-published>48*3600:continue
        text=BeautifulSoup(body,'html.parser').get_text(' ',strip=True)
        from core.league_identity import normalize_name
        for side in ('home','away'):
            team=ctx[side]['official_name']
            if normalize_name(team) not in normalize_name(text):continue
            # Preserve the source's words; do not turn text into invented OUT,
            # lineup/minute or player-ID records.
            start=text.casefold().find(team.casefold())
            if start<0:continue
            results.append(dict(team_id=ctx[side]['provider_id'],team=team,
                note=text[max(0,start-80):start+900],headline=headline[:220],published_at_utc=published,
                source_url=receipt['url'],body_sha256=receipt['body_sha256'],
                status='OFFICIAL_NEWS_TEXT_NOT_VERIFIED_MATCH_AVAILABILITY'))
    return results[:4]


class EuropeanDataReview:
    def __init__(self,services,bridge,directory,*,getter=fetch,clock=time.time,roster_store=None,native_roster_getter=None,injury_advisory_getter=None,public_news_hub=None):
        self.services=services;self.bridge=bridge;self.root=local_path(directory)
        self.getter=getter;self.clock=clock;self.cache={};self.catalogs={};self.lock=threading.Lock()
        # A shared, explicitly verified packet store. Empty is NOT a live feed.
        # The roster view only reads evidence; numerical model inputs are unchanged.
        self.roster_store=roster_store
        self.native_roster_getter=native_roster_getter
        self.injury_advisory_getter=injury_advisory_getter
        self.public_news_hub=public_news_hub

    def current_identity_context(self,ctx,owner):
        """Separate current association evidence; never alter forecast feature clocks."""
        ctx=deepcopy(ctx)
        if not any(v!='KEY_NOT_AVAILABLE_IN_TEST_PROCESS' for v in self.bridge.access.configuration().values()):return ctx
        from providers.season_participants import participant_urls
        from hybrid_engine.europe_provider_identity import binding_evidence
        key=(ctx['league'],ctx['season']);now=int(self.clock());old=self.catalogs.get(key)
        try:
            if old and now<old['valid_until_utc']:
                bundle=deepcopy(old['bundle'])
            else:
                documents={}
                for name,url in participant_urls(ctx['league'],int(ctx['season'][:4])).items():
                    if int(self.clock())>=ctx['fixture_start_utc']:raise ValueError('TIPOFF_DURING_IDENTITY_REVIEW')
                    documents[name]=owner.fetcher('EUROLEAGUE_LIVE',url)
                bundle=dict(documents=documents,sha256=digest(documents))
            ctx['european_team_catalog']=bundle
            proof=binding_evidence(ctx)
            self.save_source(bundle)
            self.catalogs[key]=dict(bundle=deepcopy(bundle),valid_until_utc=min(
                min(r['observed_at_utc'] for r in bundle['documents'].values())+240,int(self.clock())+120))
            while len(self.catalogs)>4:self.catalogs.pop(next(iter(self.catalogs)))
            ctx['current_team_identity']=dict(status='OFFICIAL_CURRENT_TEAM_CATALOG_VERIFIED',**proof)
        except (ValueError,KeyError,TypeError,OSError,AttributeError) as exc:
            # No fuzzy fallback. Existing exact canonical strings still work;
            # alternative provider names require the full current catalog.
            ctx.pop('european_team_catalog',None)
            ctx['current_team_identity']=dict(status='LOCAL_EUROPE_SOURCE_STORAGE_FULL' if isinstance(exc,EuropeanEvidenceCapacityError)
                else 'CURRENT_TEAM_CATALOG_UNAVAILABLE_EXACT_NAMES_ONLY')
        return ctx

    def resolve(self,ctx):
        pin=ctx['original_forecast_sha256']
        if type(pin) is not str or re.fullmatch('[0-9a-f]{64}',pin) is None:
            raise ValueError('EUROPE_CURRENT_FORECAST_PIN')
        service=self.services[ctx['league']]
        for owner in (service,getattr(service,'previous',None)):
            if owner is None:continue
            from hybrid_engine.europe_premium_ui import publication
            exists=(owner.registry.root/('forecast-'+pin+'.json')).exists()
            for item in (publication(owner.registry,pin),) if exists else ():
                p=item['payload']
                if digest(p)==ctx['original_forecast_sha256']:
                    g=p['fixture'];pair=owner.pair(p) if hasattr(owner,'pair') else owner._pair(p)
                    if (g['canonical_id']!=ctx['fixture_id'] or g['start_ts_utc']!=ctx['fixture_start_utc'] or
                        pair!=(ctx['home']['official_name'],ctx['away']['official_name']) or
                        [g['home_team_id'],g['away_team_id']]!=[ctx['home']['provider_id'],ctx['away']['provider_id']] or
                        p['prediction_generated_at_utc']!=ctx['prediction_generated_at_utc'] or
                        p['version']!=ctx['model_digest'] or p['components']['BAYES_QMC']['intervals']!=ctx['intervals'] or
                        p['source_available_max_utc']!=ctx['input_clocks'][0]['ingested_at_utc']):
                        raise ValueError('EUROPE_CURRENT_CONTEXT_CONFLICT')
                    return owner,p
        archive=getattr(service,'archive',None)
        if archive is not None:
            for p in archive.records.values():
                if digest(p)==ctx['original_forecast_sha256'] and p['fixture']['canonical_id']==ctx['fixture_id']:
                    if ctx['prediction_generated_at_utc'] is not None:raise ValueError('LEGACY_ISSUE_CLOCK_UNPROVEN')
                    return None,p
        raise ValueError('EUROPE_CURRENT_FORECAST_PIN')

    def distribution(self,owner,p,ctx):
        if p.get('format')!='EUROPE_COMPONENT_FORECAST_V1':raise ValueError('EUROPE_REPLAY_FORMAT_UNSUPPORTED')
        prepared=[r for r in p['assets'] if r['file'].startswith('prepared-')]
        training=[r for r in p['assets'] if r['file'].startswith('training-')]
        cuts=[r for r in p['assets'] if r['file'].startswith('cut-')]
        if not len(prepared)==len(training)==len(cuts)==1:raise ValueError('EUROPE_REPLAY_ASSETS')
        w=owner.registry.read_asset(prepared[0]);t=owner.registry.read_asset(training[0]);cut=Cut(**owner.registry.read_asset(cuts[0]))
        if (digest(w['payload'])!=w['sha256'] or w['sha256']!=p['version'] or
            digest(t)!=w['payload']['training_source']['sha256'] or cut.target['fixture_id']!=ctx['fixture_id'] or
            cut.cutoff_utc!=p['feature_cutoff_utc'] or cut.cutoff_utc>ctx['prediction_generated_at_utc']):
            raise ValueError('EUROPE_REPLAY_PARAMETER_OR_CUT_PIN')
        from hybrid_engine.europe_archive_model import restore
        ref=w['payload']['training_source']
        if Path(ref['file']).name!=ref['file']:raise ValueError('EUROPE_REPLAY_TRAINING_PATH')
        model=restore(w,t,ctx)
        forecast=model.predict(cut,method='RQMC_HALTON',bounded_workspace=True)
        from hybrid_engine.intervals import prediction_intervals
        if prediction_intervals(forecast)['sample_sha256']!=ctx['intervals']['sample_sha256']:
            raise ValueError('EUROPE_REPLAY_SAMPLE_PIN')
        q=forecast.summary()
        if any(not np.allclose(q[k],p['components']['BAYES_QMC']['prediction'][k],atol=1e-8,rtol=0)
               for k in ('home','away','total','margin','quarters','halves','winner')):
            raise ValueError('EUROPE_REPLAY_PROJECTION_PIN')
        from hybrid_engine.decision_audit import trace_for
        from hybrid_engine.decision_layer import DecisionDistribution
        return DecisionDistribution(forecast,trace_for(ctx))

    def market(self,ctx,owner,p):
        report=self.bridge.collect(ctx);parts=[render_provider(report)];observations=report['providers'].get('THE_ODDS_API',{}).get('observations',[])
        accepted=0;quote_expiry=None
        if observations:
            from hybrid_engine.current_market_review import admit_odds,evaluate,CurrentReviewJournal
            from hybrid_engine.current_market_render import render_batch
            row=report['providers']['THE_ODDS_API'];discovery=self.bridge.read_receipt(row['discovery_source_pin'])
            detail=self.bridge.read_receipt(row['source_pin'])
            try:
                assessment=None
                if getattr(self.bridge,'assessments',None):
                    try:assessment=self.bridge.assessments.available_market_context(ctx)
                    except (ValueError,KeyError,TypeError,OSError,TimeoutError):
                        parts.append('Güncel aday bağlamı doğrulanamadı: EUROPE_CURRENT_MODEL_CONTEXT_UNAVAILABLE. '
                                     'Bağımsız ilk model fiyat karşılaştırması korunuyor.')
                if getattr(self.bridge,'assessments',None) and assessment is None:
                    parts.append('Güncel değerlendirme yolları hazır/güncel değil; ilk tahminin dağılımı ayrı referans olarak kullanıldı.')
                evaluation_context,distribution=assessment if assessment else (ctx,self.distribution(owner,p,ctx))
                now=int(self.clock())
                from hybrid_engine.settlement_rules import evaluate_bound
                reviews=[evaluate_bound(self.bridge,o,distribution,evaluation_context,asof_utc=now,
                    native_quotes=admit_odds(o,ctx,discovery,detail)) for o in observations]
                if int(self.clock())>=ctx['fixture_start_utc']:raise ValueError('TIPOFF_DURING_PROVIDER_REVIEW')
                batch=CurrentReviewJournal(self.root/'market').record(evaluation_context,distribution,reviews,decision_utc=now)
                from hybrid_engine.market_direction_ui import cards,order,render
                ranked=order([card for review in reviews for card in cards(review,distribution.forecast,
                    tipoff_utc=ctx['fixture_start_utc'],fixture_id=ctx['fixture_id'],batch=batch)])
                label=('GÜNCEL AVRUPA TEMPO/VERİMLİLİK ADAYI' if assessment else 'İLK KAYITLI AVRUPA BAYES MODELİ')
                parts.append('<b>'+label+' | PİYASA KARŞILAŞTIRMASI</b>\n'
                             'Ham normal süre model yönü; kalibre güven endeksi değildir.')
                parts.extend(render(card) for card in ranked[:12])
                if len(ranked)>12:
                    parts.append('Özet kart sınırı: 12 / '+str(len(ranked))+
                                 ' satır; kabul edilen diğer satırlar ayrıntılı değerlendirmede.')
                expiries=[card['valid_until_utc'] for card in ranked
                          if card['current'] and type(card['valid_until_utc']) is int]
                quote_expiry=min(expiries) if expiries else now
                if assessment:
                    from hybrid_engine.time_policy import V3_FRESHNESS_SECONDS,MAXIMUM_V3_MODEL_AGE_SECONDS
                    quote_expiry=min(quote_expiry,
                        evaluation_context['prediction_generated_at_utc']+V3_FRESHNESS_SECONDS,
                        evaluation_context['parameter_fit_cutoff_utc']+MAXIMUM_V3_MODEL_AGE_SECONDS)
                parts.append('Ortak fiyat/model görünümü son geçerlilik: '+tsi(quote_expiry))
                parts.append(render_batch(batch));accepted=len(observations)
            except (ValueError,KeyError,TypeError,OSError):
                parts.append('Kaynak fiyatı veya arşiv dağılımı doğrulanamadı; yüzde/edge üretilmedi. Kod: EUROPE_MARKET_REPLAY_OR_ADMISSION_BLOCKED')
        if not accepted:parts.append('Doğrulanmış ve eşleşmiş piyasa değerlendirmesi yok; barem veya olasılık uydurulmadı.')
        return '\n\n'.join(parts),dict(provider_report=report,admitted_observations=accepted,
            quote_valid_until_utc=quote_expiry)

    def roster(self,ctx):
        # Telegram's European roster callback has a 20s ceiling. Reserve
        # >=8s for the two 4-second native player-identity requests plus
        # rendering/caching. Otherwise a slow news page can hide all results.
        # Bound optional advisory request after the existing two native reads.
        # The 20s Telegram callback must retain headroom for rendering.
        deadline=time.monotonic()+(4 if self.public_news_hub is not None and ctx['league'] in ('EUROLEAGUE','EUROCUP') else 6 if self.injury_advisory_getter is not None and ctx['league']=='EUROLEAGUE' else 9);league=ctx['league'];sources=[];rows=[];seen=set()
        queue=[BASE+path for path in PATHS[league]]
        while queue and len(seen)<3 and time.monotonic()<deadline:
            url=queue.pop(0)
            if url in seen:continue
            seen.add(url);r=self.getter(url,league,deadline=deadline)
            if r.get('status')=='RECEIVED':
                self.save_source(r);meta=inspect(r,league);rows.extend(article_rows(r,ctx,int(self.clock())))
                queue.extend(meta['injury_links'][:2])
                sources.append({k:r[k] for k in ('status','url','body_sha256','observed_at_utc','ingested_at_utc')})
            else:
                sources.append(r)
                if r.get('status')=='SOURCE_REDIRECT' and r.get('location'):queue.insert(0,r['location'])
                if r.get('http_status') in (403,429):break
        # Read the very same fixture-scoped, pre-forecast evidence contract
        # used by the isolated NBA view. Never infer injury or player minutes
        # from a generic news page or from an 82-URL source directory.
        from hybrid_engine.telegram_roster_bridge import read_fixture_roster_evidence
        from hybrid_engine.telegram_premium_ui import roster_section
        evidence=read_fixture_roster_evidence(
            self.roster_store,
            fixture_id=ctx['fixture_id'],
            prediction_utc=ctx['prediction_generated_at_utc'],
            fixture_start_utc=ctx['fixture_start_utc'],
            home_team_id=str(ctx['home']['provider_id']),
            away_team_id=str(ctx['away']['provider_id']))
        verified_records=evidence['records']
        packet_status=('FIXTURE_BOUND_PREFORECAST_PLAYER_STATUS_AVAILABLE'
                       if verified_records else
                       'NO_VERIFIED_PREFORECAST_PLAYER_PACKET')
        evidence_view=roster_section(evidence)
        source_description=('Kaynak türü: resmî haber sayfası + isteğe bağlı ikincil sakatlık adaptörü YAPILANDIRILDI; gerçek veri yanıtı henüz doğrulanmadı.'
            if league=='EUROLEAGUE' and self.injury_advisory_getter is not None else
            'Kaynak türü: resmî haber sayfası; canlı sakatlık/veri sağlayıcı adaptörü bağlı değil.')
        lines=['🏥 <b>GÜNCEL RESMÎ AVRUPA KAYNAĞI</b>','Kontrol: '+tsi(int(self.clock())),
               source_description,
               'Önceden doğrulanmış, maç kimliği ve ilk tahmin zamanı eşleşen oyuncu paketi kontrolü: '+packet_status+'.',
               'İlk tahmin girdisi değildir; kayıtlı skor değiştirilmedi.']
        for s in sources:
            lines.append(html.escape(str(s.get('url',BASE))))
            lines.append('Kaynak durumu: '+html.escape(s['status'])+
                         (' | HTTP '+str(s['http_status']) if s.get('http_status') else ''))
            if s.get('retry_after_seconds'):lines.append('Yeniden deneme için bekleme: '+str(s['retry_after_seconds'])+' sn')
            if s.get('body_sha256'):lines.append('Kaynak SHA: '+s['body_sha256']+' · Erişim: '+tsi(s['observed_at_utc']))
        for row in rows:
            lines.extend(['',html.escape(row['team'])+' · <b>Resmî haber notu</b>',html.escape(row['note']),
                          'Yayın: '+tsi(row['published_at_utc']),html.escape(row['source_url'])])
        native_report=None
        if self.native_roster_getter is not None and int(self.clock())<ctx['fixture_start_utc']:
            from hybrid_engine.europe_native_roster_source import pair as native_pair, render_public
            native_report=native_pair(ctx,getter=self.native_roster_getter,clock=self.clock)
            lines.extend(['',html.escape(render_public(native_report))])
        elif self.native_roster_getter is None:
            lines.append('Resmî sezon oyuncu kimliği adaptörü: YAPILANDIRILMADI.')
        # Independent *current* secondary observations can help diagnose
        # gaps, but they have no fixture-specific official status publication
        # time and must NEVER be inserted into verified_player_records.
        advisory=None
        if league=='EUROLEAGUE' and self.injury_advisory_getter is not None and int(self.clock())<ctx['fixture_start_utc']:
            from hybrid_engine.europe_injury_advisory import bind as bind_injury,render as render_injury
            try:
                secondary_receipt=self.injury_advisory_getter()
                advisory=bind_injury(secondary_receipt,ctx=ctx,native_report=native_report,now=int(self.clock()))
            except (ValueError,TypeError,KeyError,TimeoutError,OSError):
                advisory=dict(status='INJURY_PROVIDER_REVIEW_UNAVAILABLE',player_rows=[],
                              injury_status_verified_for_fixture=False,original_prediction_eligible=False,
                              model_input=False,forecast_changed=False)
            lines.extend(['',html.escape(render_injury(advisory))])
        elif league=='EUROLEAGUE' and self.injury_advisory_getter is not None:
            lines.append('İkincil canlı sakatlık sağlayıcısı: YAPILANDIRILDI ancak maç başladı; geriye dönük yeni sorgu yapılmadı.')
        else:
            lines.append('İkincil canlı sakatlık sağlayıcısı: YAPILANDIRILMADI; kayıtsız oyuncu sağlıklı sayılmaz.')
        # Independent editorial and exact-match club indexes, never a verified
        # player packet. Retain old results and do not touch the model/forecast.
        public_news=None
        if self.public_news_hub is not None and league in ('EUROLEAGUE','EUROCUP'):
            from hybrid_engine.europe_injury_public_sources import render as render_public_news
            try:
                public_news=self.public_news_hub.review(ctx)
            except (ValueError,KeyError,TypeError,TimeoutError,OSError):
                public_news=dict(status='PUBLIC_NEWS_SOURCE_UNAVAILABLE',sources=[],
                                 player_status_verified=False,model_input=False)
            lines.extend(['',html.escape(render_public_news(public_news))])
        from hybrid_engine.europe_player_identity_audit import match_candidates,render_matches
        player_identity_audit=match_candidates(ctx,native_report,public_news)
        lines.extend(['',html.escape(render_matches(player_identity_audit))])
        if verified_records:
            lines.extend(['',evidence_view,
                          'Bu paket ilk tahmin kesitinden önce yayımlanmış kanıtı gösterir; dakika/rotasyon/model etkisi değildir.'])
        if not rows and not verified_records:
            lines.append('Maça bağlı doğrulanmış oyuncu durum kaydı elde edilemedi; eksik oyuncu yok demek değildir.')
        lines.extend(['Haber metni maç kadrosu, ceza uygunluğu veya bağımsız tıbbi doğrulama değildir.',
                      'Oyuncu kimlikleri/ilk beş/dakika/rotasyon etkisi doğrulanmadı; modele uygulanmadı.',
                      'NOT_CALIBRATED · Güven endeksi yok.'])
        return '\n'.join(lines),dict(sources=sources,news_observations=rows,
            verified_player_records=verified_records,verified_player_packet_status=packet_status,
            player_evidence_rejections=evidence['rejected_count'],
            native_season_player_directory=native_report,
            secondary_current_injury_advisory=advisory,
            public_news_candidate_review=public_news,
            public_news_player_identity_audit=player_identity_audit,
            public_news_model_input=False,
            secondary_injury_adapter_attached=(league=='EUROLEAGUE' and self.injury_advisory_getter is not None),
            secondary_injury_last_status=advisory['status'] if advisory else 'NOT_QUERIED',
            match_specific_injury_feed_model_input=False,
            capability=('READ_ONLY_VERIFIED_PREFORECAST_PLAYER_PACKET_AND_OFFICIAL_NEWS'
                        if verified_records else 'OFFICIAL_NEWS_ONLY_NOT_PLAYER_AVAILABILITY_FEED'),
            minutes_and_rotation_model_input=False,forecast_changed=False)

    def save_source(self,p):
        if len(json.dumps(p).encode())>3*1024*1024:raise ValueError('EUROPE_SOURCE_SIZE')
        root=self.root/'sources';root.mkdir(parents=True,exist_ok=True)
        target=root/('source-'+digest(p)+'.json')
        if target.exists():
            if target.stat().st_size>3*1024*1024:raise ValueError('EUROPE_SOURCE_SIZE')
            old=json.loads(target.read_text())
            if old.get('sha256')!=digest(p) or digest(old['payload'])!=digest(p):raise ValueError('EUROPE_SOURCE_PIN')
            return
        files=list(root.glob('source-*.json'))
        size=len((json.dumps(dict(payload=p,sha256=digest(p)),sort_keys=True,allow_nan=False)+'\n').encode())
        if len(files)>=64 or sum(f.stat().st_size for f in files)+size>16*1024*1024:
            raise EuropeanEvidenceCapacityError('EUROPE_SOURCE_STORAGE_BUDGET')
        publish_json(target,dict(payload=p,sha256=digest(p)))

    def review(self,ctx,section):
        if section not in ('market','roster'):raise ValueError('EUROPE_CURRENT_SECTION')
        if ctx['league'] not in self.services:raise ValueError('EUROPE_CURRENT_LEAGUE')
        owner,p=self.resolve(ctx);now=int(self.clock());key=(ctx['original_forecast_sha256'],section)
        old=self.cache.get(key)
        if now>=ctx['fixture_start_utc'] or ctx['prediction_generated_at_utc'] is None:
            return dict(original_forecast_sha256=ctx['original_forecast_sha256'],section=section,observed_at_utc=now,
                valid_until_utc=now,status='POST_TIPOFF_NO_CURRENT_BACKFILL',
                html='Maç başladı veya ilk tahmin zamanı bilinmiyor; yeni kaynak sorgusu yapılmadı.\n'+
                     (old['html'] if old else 'Gösterilebilir güncel kaynak gözlemi yok; ilk tahmin korunuyor.'))
        if old and now<old['valid_until_utc']:return deepcopy(old)
        if not self.lock.acquire(blocking=False):raise ValueError('EUROPE_PROVIDER_REVIEW_BUSY')
        try:
            if section=='market':ctx=self.current_identity_context(ctx,owner)
            try:
                body,details=self.market(ctx,owner,p) if section=='market' else self.roster(ctx)
            except EuropeanEvidenceCapacityError:
                body='Yerel Avrupa kaynak kanıtı deposu dolu; yeni kaynak belgesi arşivlenemedi. Eski kayıtlar korundu.'
                details=dict(local_status='LOCAL_EUROPE_SOURCE_STORAGE_FULL')
            if int(self.clock())>=ctx['fixture_start_utc']:
                body='Maç kaynak kontrolü sırasında başladı; bu gözlem yeni PREMATCH sayılmaz.\n'+body
            r=dict(format='EUROPE_CURRENT_SOURCE_REVIEW_V1',original_forecast_sha256=ctx['original_forecast_sha256'],
                   fixture_id=ctx['fixture_id'],league=ctx['league'],section=section,observed_at_utc=now,
                   context_sha256=digest(ctx),source_context=deepcopy(ctx),
                   valid_until_utc=min(now+120,ctx['fixture_start_utc']),status='CURRENT_OBSERVATIONS_ONLY',
                   html=body,details=details,forecast_changed=False,eligible_for_original_forecast_metrics=False)
            if details.get('local_status'):r['status']=details['local_status']
            root=self.root/'reviews';root.mkdir(parents=True,exist_ok=True)
            files=list(root.glob('review-*.json'));size=len(json.dumps(r).encode())
            stored_size=len((json.dumps(dict(payload=r,sha256=digest(r)),sort_keys=True,allow_nan=False)+'\n').encode())
            if size>2*1024*1024:raise ValueError('EUROPE_REVIEW_SIZE_BUDGET')
            if len(files)>=256 or sum(f.stat().st_size for f in files)+stored_size>16*1024*1024:
                r.update(status='CURRENT_OBSERVATIONS_NOT_PERSISTED',persistence='LOCAL_EUROPE_REVIEW_STORAGE_FULL')
                r['html']='Yerel inceleme deposu dolu; aşağıdaki görünüm yeni bir arşiv kaydı değildir. Eski kayıtlar korundu.\n\n'+body
            else:
                publish_json(root/('review-'+digest(r)+'.json'),dict(payload=r,sha256=digest(r)))
            while self.cache and (len(self.cache)>=32 or sum(len(json.dumps(x).encode()) for x in self.cache.values())+size>4*1024*1024):
                self.cache.pop(next(iter(self.cache)))
            self.cache[key]=r;return deepcopy(r)
        finally:self.lock.release()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-directory',required=True)
    p.add_argument('--league',choices=('EUROLEAGUE','EUROCUP'),required=True);p.add_argument('--fixture-id',required=True)
    a=p.parse_args()
    try:
        from hybrid_engine.europe_live import EuropeanService
        from hybrid_engine.europe_premium_ui import projection
        from hybrid_engine.provider_access import ProviderAccess,credentials
        from hybrid_engine.provider_bridge import ProviderBridge
        from hybrid_engine.source_policy import ControlledTransport
        from season_archive_collect import fetch_document
        root=local_path(a.data_directory);directory=root/'europe'
        service=EuropeanService(a.league,directory/a.league.lower(),directory/'models',ControlledTransport(fetch_document))
        rows=[r for r in service.registry.independent_records() if a.fixture_id in
              [r['payload']['fixture']['canonical_id'],*r['payload']['fixture']['provider_fixture_ids']]]
        if len(rows)!=1:raise ValueError('ONE_ARCHIVED_EUROPEAN_FORECAST_REQUIRED')
        report=service.render(rows[0],new=False);v=projection(report,a.league,service=service);ctx=context(v,a.league)
        access=ProviderAccess(credentials());bridge=ProviderBridge(access,root/'provider-evidence')
        reviewer=EuropeanDataReview({a.league:service},bridge,root/'europe-data')
        results=[]
        for section in ('market','roster'):
            r=reviewer.review(ctx,section);details=r.get('details',{})
            results.append(dict(section=section,status=r['status'],admitted_observations=details.get('admitted_observations',0),
                provider_states={k:v.get('status') for k,v in details.get('provider_report',{}).get('providers',{}).items()},
                provider_details={k:{name:v[name] for name in ('operation','error_codes','requested_season','season_selection',
                    'expected_sport_key','active_basketball_sports','coverage_cache') if name in v}
                    for k,v in details.get('provider_report',{}).get('providers',{}).items()},
                source_states=[{k:s.get(k) for k in ('status','http_status','url','retry_after_seconds')} for s in details.get('sources',[])],
                news_observations=len(details.get('news_observations',[])),verified_player_records=0))
        print(json.dumps(dict(league=a.league,fixture_id=a.fixture_id,results=results,
            configuration=access.configuration(),forecast_changed=False,production_changed=False,actual_telegram_delivery_verified=False),ensure_ascii=False))
        return 0
    except (ValueError,KeyError,TypeError,OSError):
        print(json.dumps(dict(status='EUROPE_DATA_CHECK_BLOCKED',reason='EXISTING_ARCHIVE_OR_PROVIDER_CONFIGURATION_REQUIRED',
                             forecast_changed=False,production_changed=False)))
        return 2


if __name__=='__main__':raise SystemExit(main())
