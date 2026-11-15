"""Opt-in EuroLeague bridge using existing frozen models and append-only captures.

Never trains in a Telegram request. Existing five-game replay remains the fallback;
new requests use an explicitly isolated ForwardRegistry and fresh official identity.
"""
import asyncio
import html
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.elite_render import split_blocks
from hybrid_engine.frozen_archive import norm
from hybrid_engine.forward_validation import capture, verified_catalog
from hybrid_engine.prospective_results import OFFICIAL
from telegram_delivery import tsi


def names(document):
    return {g['identifier']:(g['local']['club'].get('name') or g['local']['club'].get('editorialName') or g['local']['club']['code'],
                              g['road']['club'].get('name') or g['road']['club'].get('editorialName') or g['road']['club']['code'])
            for g in document['data']}


class LiveEuroLeagueService:
    def __init__(self,archive,registry,fetcher,fallback):
        self.archive=archive;self.registry=registry;self.fetcher=fetcher;self.fallback=fallback
        self.lock=asyncio.Lock()

    def _pair(self,payload):
        for ref in payload['assets']:
            value=self.registry.read_asset(ref)
            if value.get('provider')=='EUROLEAGUE_LIVE' and value.get('source_url')==OFFICIAL:
                catalog=verified_catalog(value,max_age=None)
                matches=[g for g in catalog['payload']['fixtures'] if g==payload['fixture']]
                if len(matches)!=1:raise ValueError('EL_CAPTURE_NATIVE_IDENTITY')
                return names(value['document'])[payload['fixture']['provider_fixture_ids'][0]]
        raise ValueError('EL_CAPTURE_NATIVE_SOURCE_REQUIRED')

    def _find(self,day,home,away):
        for item in self.registry.independent_records():
            p=item['payload'];h,a=self._pair(p)
            start=datetime.fromtimestamp(p['fixture']['start_ts_utc'],ZoneInfo('Europe/Istanbul'))
            if start.date().isoformat()==day and norm(home)==norm(h) and norm(away)==norm(a):return item,(h,a)
        return None,None

    def _render(self,item,pair,*,new):
        p=item['payload'];m=p['components'].get('BAYES_QMC',{})
        if m.get('status')!='FORECAST_CREATED':
            return dict(status='ABSTAIN',html='Bayesian/QMC için yeterli doğrulanmış veri yok; tahmin üretilmedi.')
        q=m['prediction'];bands=m['intervals'];esc=html.escape
        title=('<b>ZEYNAL | EUROLEAGUE HİBRİT ARAŞTIRMA</b>\n'+esc(pair[0])+' – '+esc(pair[1])+
               '\n'+tsi(p['fixture']['start_ts_utc'])+' | Normal süre, 40 dk\n'+
               ('Yeni maç öncesi kayıt.' if new else 'ARŞİV REPLAY: Yeni PREMATCH tahmini üretilmedi.'))
        score=f"<b>SKOR PROJEKSİYONU</b>\n{q['home']:.2f} – {q['away']:.2f}\nToplam {q['total']:.2f} | Fark (ev) {q['margin']:+.2f}"
        periods='<b>PERİYOT ANALİZİ</b>'
        for label,values in [(str(i+1)+'Q',v) for i,v in enumerate(q['quarters'])]+[(str(i+1)+'H',v) for i,v in enumerate(q['halves'])]:
            periods+=f'\n{label}: {values[0]:.2f} – {values[1]:.2f} | Toplam {sum(values):.2f}'
        ranges='<b>TAHMİN ARALIKLARI</b>\nHam dağılım; gerçekleşen kapsama veya güven garantisi değildir.'
        for key,label in [('TOTAL','Maç toplamı'),('HOME','Ev toplamı'),('AWAY','Deplasman toplamı'),('MARGIN','Fark')]:
            b=bands.get('markets',{}).get(key)
            if b:ranges+=f"\n{label}: P50 {b['p50']:.1f} | P25–P75 {b['p25']:.1f}–{b['p75']:.1f} | P05–P95 {b['p05']:.1f}–{b['p95']:.1f}"
        audit=('<b>MODEL DENETİMİ</b>\nNOT_CALIBRATED | Güven endeksi yok.\nPiyasa verisi doğrulanamadı; barem, yön veya edge yok.'+
               '\nKadro, sakatlık, rotasyon ve ölçülmüş tempo doğrulanmadı; modele eklenmedi.'+
               '\nEnsemble değil; dondurulmuş Bayesian/QMC bileşeni.\nModel: '+esc(q['model'])+
               '\nYöntem: '+esc(q['metadata']['method'])+' | Gerçek örnek: '+str(bands['scenarios'])+
               '\nSürüm: '+esc(p['version'])+'\nTahmin üretimi: '+tsi(p['prediction_generated_at_utc'])+
               '\nİlk kalıcı arşiv: '+tsi(item['publication']['first_archived_at_utc'])+
               '\nKaynak: '+OFFICIAL+'\nSHA-256: '+digest(p))
        parts=split_blocks([title,score,periods,ranges,audit])
        return dict(status='FORWARD_EUROLEAGUE_OK',html_parts=parts,html=parts[0],new_record=new,
                    forecast_sha256=digest(p),timeline=dict(prediction_generated_at_utc=p['prediction_generated_at_utc'],
                    first_archived_at_utc=item['publication']['first_archived_at_utc'],response_prepared_at_utc=int(time.time()),
                    reused_forecast=not new))

    async def analyze(self,league,day,home,away):
        async with self.lock:
            if league.upper()!='EUROLEAGUE':return await self.fallback.analyze(league,day,home,away)
            try:
                datetime.strptime(day,'%Y-%m-%d')
                old,pair=await asyncio.to_thread(self._find,day,home,away)
                if old:return self._render(old,pair,new=False)
                # Preserve the established five-game archive route.
                if self.archive.find(league,day,home,away):return await self.fallback.analyze(league,day,home,away)
                receipt=await asyncio.to_thread(self.fetcher,'EUROLEAGUE_LIVE',OFFICIAL)
                cat=verified_catalog(receipt);pairs=names(receipt['document']);now=int(time.time())
                targets=[g for g in cat['payload']['fixtures'] if
                    datetime.fromtimestamp(g['start_ts_utc'],ZoneInfo('Europe/Istanbul')).date().isoformat()==day and
                    tuple(map(norm,pairs[g['provider_fixture_ids'][0]]))==(norm(home),norm(away))]
                if len(targets)!=1:return dict(status='ABSTAIN',html='Resmî EuroLeague fikstürü tarih ve ev/deplasman sırasıyla tekil doğrulanamadı; tahmin üretilmedi.')
                g=targets[0]
                if g['completed'] or g['start_ts_utc']<=now+1800:
                    return dict(status='ABSTAIN',html='Maç başladı, tamamlandı veya 30 dakikalık güvenli üretim penceresi kapandı. Yeni PREMATCH üretilmedi.')
                captured=await asyncio.to_thread(capture,self.archive,self.registry,receipt,fetcher=self.fetcher,maximum=1,fixture_id=g['canonical_id'])
                if not captured or captured[0]['status'] not in ('CAPTURED','REUSED'):
                    return dict(status='ABSTAIN',html='Doğrulanmış tarihsel veri/model veya arşiv koşulları yetersiz; tahmin yayınlanmadı.')
                item,pair=await asyncio.to_thread(self._find,day,home,away)
                if item is None or not item['publication']['eligible_for_prospective_audit']:
                    return dict(status='ABSTAIN',html='Maç öncesi kalıcı kayıt kanıtı yok; tahmin yayınlanmadı.')
                return self._render(item,pair,new=captured[0]['status']=='CAPTURED')
            except (ValueError,KeyError,TypeError,OSError):
                return dict(status='ABSTAIN',html='EuroLeague kaynak/model/arşiv doğrulaması başarısız. Yeni tahmin yayınlanmadı.')
