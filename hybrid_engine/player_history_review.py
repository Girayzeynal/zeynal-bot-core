"""Low-frequency historical-player diagnostics, never a live injury score.

The existing native box pilot fits in the serial background worker only. A
Telegram view reads the cached result; it never fits, fetches or changes an
original/registered model. Missing prospective minutes are reported separately.
"""
import time
import re

from hybrid_engine.data import local_path
from telegram_delivery import tsi


class HistoricalPlayerReview:
    def __init__(self,directory,reader=None):
        if reader is None:
            from hybrid_engine.player_box_pilot import run_readonly
            reader=run_readonly
        self.root=local_path(directory);self.reader=reader;self.last_report=None;self.next_check=0

    def tick(self,*,cases=(),case_loader=None):
        now=int(time.time())
        if now<self.next_check:return self.last_report or dict(status='HISTORICAL_PLAYER_RECHECK_PENDING')
        if case_loader is not None:cases=case_loader()
        if any(0<c['target']['fixture_start_utc']-now<=900 for c in cases):
            # This optional diagnostic must not delay a pending five-minute
            # publication. Keep the previous study and clocks if there is one.
            self.next_check=now+60
            return dict(status='HISTORICAL_PLAYER_DEFERRED_NEAR_PUBLICATION',previous_report_kept=True)
        self.next_check=now+300
        try:
            report=self.reader(self.root,now_utc=now)
            if (not isinstance(report,dict) or not isinstance(report.get('status'),str) or
                    not re.fullmatch('[A-Z_0-9]{1,120}',report['status'])):
                raise ValueError('HISTORICAL_PLAYER_REPORT_SCHEMA')
        except (ValueError,KeyError,TypeError,OSError) as exc:
            report=dict(status='HISTORICAL_PLAYER_READ_FAILED',error_type=type(exc).__name__)
        self.last_report=dict(report,observed_at_utc=now,live_player_effect_applied=False,
            production_enabled=False,network_requests_made=0,original_forecasts_modified=False)
        if report.get('status')=='REAL_HISTORICAL_BOX_MODEL_FITTED_RESEARCH_ONLY':self.next_check=now+6*3600
        return self.last_report

    def snapshot(self):
        if self.last_report is None:return dict(status='NOT_OBSERVED_NOT_ZERO')
        keys=('status','observed_at_utc','verified_player_box_games','historical_player_training_games',
            'fitted_players','estimated_parameters','live_player_effect_applied','production_enabled')
        return {k:self.last_report[k] for k in keys if k in self.last_report}

    def render(self):
        lines=['GEÇMİŞ OYUNCU DAKİKALARI | AYRI MODEL DENETİMİ']
        p=self.last_report
        if not p:return '\n'.join(lines+['Bu süreçte henüz okunmadı; geçmiş veri sayısı sıfır sayılmaz.'])
        lines.extend(['Durum: '+p['status'],'Kontrol: '+tsi(p['observed_at_utc'])])
        if p.get('verified_player_box_games') is not None:
            lines.append('Native geçmiş oyuncu box maçı: '+str(p['verified_player_box_games']))
        if p.get('historical_player_training_games') is not None:
            lines.append('Geçmiş model eğitimi: '+str(p['historical_player_training_games'])+
                ' maç · Fitted oyuncu: '+str(p.get('fitted_players',0)))
        strict=p.get('retrospective_validation',{}).get('strict',{})
        if strict:lines.append('Zamanı doğrulanmış ayrık test: '+str(strict.get('matched_test_games',0))+' · '+strict['status'])
        if p.get('player_coefficients_not_individually_identified'):
            lines.append('Oyuncu katsayıları tek tek ayırt edilemedi; düzenlileştirilmiş ilişki modeli.')
        contrast=p.get('contrast_candidate')
        if contrast:
            lines.append('Ayrı dakika-kontrast adayı: '+contrast['status'])
            if contrast.get('players') is not None:
                lines.append('Seçilen oyuncu terimi '+str(contrast['players'])+' · Parametre '+str(contrast['parameters'])+
                    ' / Gözlem '+str(contrast['score_observations'])+' · Canlı terfi yok')
        lines.extend(['Geçmiş gerçek dakika eğitimi ile güncel maç öncesi dakika kanıtı farklıdır.',
            'Bu denetim kadro/sakatlık etkisini aktif skora uygulamaz; güven endeksi yok.'])
        return '\n'.join(lines)
