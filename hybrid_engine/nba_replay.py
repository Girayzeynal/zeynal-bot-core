"""Read-only FAZ 84.3 NBA snapshots. No prediction, training, download or extraction."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import html
import json
import math
from pathlib import Path,PurePosixPath
import tarfile
import time
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine.data import local_path
from hybrid_engine.elite_render import split_blocks
from hybrid_engine.frozen_archive import norm
from projection_integrity import assert_projection
from season_archive_inventory import archive_catalog
from telegram_delivery import tsi

DEFAULT_PACKET=Path(__file__).resolve().parents[1]/'docs/evidence/nba-phase843-prospective-native-20261113.tar.gz'
PACKET_SHA256='9e95f0d849f530325ef881e389179796577a82c65c4aa3be798bbaa2bf3700b3'
CAPTURE_SHA256='b81a02d1194884ccf97356e085bb5931e9f9b64085ecacc7c211b71378ea3118'
CAPTURE_MEMBER='capture-optimized-'+CAPTURE_SHA256+'.json'
TSI=ZoneInfo('Europe/Istanbul')


def utc(stamp):return datetime.fromtimestamp(stamp,timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def validate_case(case):
    p=case['snapshot']
    if digest(p)!=case['snapshot_sha256']:raise ValueError('NBA_REPLAY_SNAPSHOT_SHA256')
    if (case['status']!='ANALYSIS_OK' or p['league']!='NBA' or p['provider']!='ESPN' or p['production'] is not False or
        p['record_type']!='LIVE_PREMATCH_PREDICTION' or p['scope']!='REGULATION_ONLY' or p['actual'] is not None):
        raise ValueError('NBA_REPLAY_RECORD_KIND')
    for s in ('home','away'):
        if case[s]!=p[s]['official_name']:raise ValueError('NBA_REPLAY_OFFICIAL_NAME')
    clocks=('parameter_fit_cutoff_utc','feature_cutoff_utc','simulation_completed_at_utc',
        'source_data_time_utc','prediction_generated_at_utc','created_at_utc','fixture_start_utc')
    if any(type(p.get(k)) is not int or p[k]<=0 for k in clocks):raise ValueError('NBA_REPLAY_UTC_CLOCK_TYPE')
    if (not p['parameter_fit_cutoff_utc']<=p['feature_cutoff_utc']<=p['simulation_completed_at_utc']<=p['prediction_generated_at_utc']<=p['created_at_utc']<p['fixture_start_utc'] or
        p['source_data_time_utc']>p['prediction_generated_at_utc'] or p['record_deadline_utc']!=p['fixture_start_utc']):
        raise ValueError('NBA_REPLAY_PRETIPOFF_CLOCK')
    if not p['input_clocks']:raise ValueError('NBA_REPLAY_INPUT_CLOCKS_REQUIRED')
    for r in p['input_clocks']:
        if (any(type(r.get(k)) is not int for k in ('observed_at_utc','ingested_at_utc')) or
            not 0<r['observed_at_utc']<=r['ingested_at_utc']<=p['prediction_generated_at_utc']):raise ValueError('NBA_REPLAY_INPUT_AFTER_PREDICTION')
    if max(r['ingested_at_utc'] for r in p['input_clocks'])!=p['source_data_time_utc']:raise ValueError('NBA_REPLAY_SOURCE_TIME_CONFLICT')
    if p['calibration_status']!='NOT_CALIBRATED' or p['prediction']['calibration_status']!='NOT_CALIBRATED' or p['confidence']['value'] is not None:
        raise ValueError('NBA_REPLAY_UNVERIFIED_CALIBRATION')
    assert_projection(p['prediction']);assert_projection(p['mc_qmc']['mc'])
    if p['mc_qmc']['qmc_sample_sha256']!=p['intervals']['sample_sha256']:raise ValueError('NBA_REPLAY_SAMPLE_PIN')
    for bands in (p['intervals'],p['mc_qmc']['mc_bands']):
        if bands['status']!='RAW_MODEL_QUANTILES_NOT_CALIBRATED' or type(bands['scenarios']) is not int or bands['scenarios']<10000:
            raise ValueError('NBA_REPLAY_ORIGINAL_DISTRIBUTION_REQUIRED')
        for b in bands['markets'].values():
            values=[b[k] for k in ('p05','p10','p25','p50','p75','p90','p95')]
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in values) or values!=sorted(values):
                raise ValueError('NBA_REPLAY_QUANTILE_ORDER')
    return p


def verify_native_identity(receipt,p):
    url=receipt.get('source_url','')
    if (not url.startswith('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?') or
        url not in {r.get('source_url') for r in p['input_clocks']} or receipt.get('provider')!='ESPN' or receipt.get('status')!='DOCUMENT_RECEIVED' or
        receipt.get('http_status')!=200 or digest(receipt['document'])!=receipt['document_sha256'] or
        not 0<receipt['observed_at_utc']<=receipt['ingested_at_utc']<=p['prediction_generated_at_utc']):return False
    c=archive_catalog(receipt['document'],provider='ESPN',season_start_year=int(p['season'].split('/')[0]),
        observed_at_utc=receipt['observed_at_utc'],ingested_at_utc=receipt['ingested_at_utc'])
    candidates=[g for g in c['payload']['fixtures'] if g['canonical_id']==p['fixture_id']]
    if len(candidates)!=1:return False
    g=candidates[0]
    if (g['completed'] or g['start_ts_utc']!=p['fixture_start_utc'] or
        set(g['provider_fixture_ids'])!=set(p['provider_fixture_ids']) or
        any(g[s+'_team_id']!=p[s]['provider_id'] for s in ('home','away'))):return False
    for event in receipt['document']['events']:
        if str(event['id']) not in p['provider_fixture_ids']:continue
        teams={t['homeAway']:t['team'] for t in event['competitions'][0]['competitors']}
        return all(str(teams[s]['id'])==p[s]['provider_id'] and teams[s]['displayName']==p[s]['official_name'] for s in ('home','away'))
    return False


class NBAReplayArchive:
    def __init__(self,packet=DEFAULT_PACKET):
        self.packet=local_path(packet)
        if not self.packet.is_file() or self.packet.stat().st_size>16*1024*1024:raise ValueError('NBA_REPLAY_PACKET_REQUIRED_OR_TOO_LARGE')
        h=hashlib.sha256()
        with self.packet.open('rb') as stream:
            for part in iter(lambda:stream.read(65536),b''):h.update(part)
        if h.hexdigest()!=PACKET_SHA256:raise ValueError('NBA_REPLAY_PACKET_SHA256')
        with tarfile.open(self.packet,'r:gz') as archive:
            members=archive.getmembers();names=[m.name for m in members]
            if len(names)!=len(set(names)) or len(names)>512 or sum(m.size for m in members)>128*1024*1024:
                raise ValueError('NBA_REPLAY_PACKET_MEMBER_BUDGET')
            for m in members:
                path=PurePosixPath(m.name)
                if not m.isfile() or path.is_absolute() or '..' in path.parts or m.size>5*1024*1024:raise ValueError('NBA_REPLAY_UNSAFE_MEMBER')
            capture=json.load(archive.extractfile(CAPTURE_MEMBER))
            if digest(capture)!=CAPTURE_SHA256 or len(capture['cases'])!=4:raise ValueError('NBA_REPLAY_CAPTURE_PIN_OR_COUNT')
            cases=capture['cases'];seen=set()
            for case in cases:
                p=validate_case(case)
                if p['fixture_id'] in seen:raise ValueError('NBA_REPLAY_DUPLICATE_FIXTURE')
                seen.add(p['fixture_id'])
            refs={ref['file']:ref['sha256'] for case in cases for ref in case['snapshot']['source_assets']}
            verified={}
            # Read pinned native receipts one at a time; no extraction or 100 MiB
            # in-memory packet. Other snapshot assets remain covered by packet pin.
            for m in members:
                if not m.name.startswith('live-nba-optimized/assets/') or PurePosixPath(m.name).name not in refs:continue
                receipt=json.load(archive.extractfile(m))
                for case in cases:
                    p=case['snapshot']
                    if (p['fixture_id'] in verified or PurePosixPath(m.name).name not in {ref['file'] for ref in p['source_assets']} or
                        '/scoreboard?' not in receipt.get('source_url','')):continue
                    if digest(receipt)!=refs[PurePosixPath(m.name).name]:raise ValueError('NBA_REPLAY_NATIVE_RECEIPT_PIN')
                    if verify_native_identity(receipt,p):verified[p['fixture_id']]={k:receipt[k] for k in ('source_url','document_sha256','observed_at_utc','ingested_at_utc')}
            if len(verified)!=4:raise ValueError('NBA_REPLAY_NATIVE_FIXTURE_IDENTITY')
        self._cases=deepcopy(cases);self._native=verified;self.capture_created_at_utc=capture['created_at_utc']

    def cases(self):return deepcopy(self._cases)

    def has_pair(self,home,away):
        return any(norm(c['home'])==norm(home) and norm(c['away'])==norm(away) for c in self._cases)

    async def list_nba_games(self,day):
        datetime.strptime(day,'%Y-%m-%d')
        return [dict(id=c['snapshot']['provider_fixture_ids'][0],start=datetime.fromtimestamp(c['snapshot']['fixture_start_utc'],TSI),
            home=c['home'],away=c['away'],status='ARŞİV REPLAY — güncel maç durumu değil') for c in self._cases
            if datetime.fromtimestamp(c['snapshot']['fixture_start_utc'],TSI).date().isoformat()==day]

    async def analyze(self,league,day,home,away):
        if league.upper()!='NBA':return dict(status='ABSTAIN',html='NBA_REPLAY_SCOPE_REQUIRED',new_record=False)
        datetime.strptime(day,'%Y-%m-%d')
        pairs=[c for c in self._cases if norm(c['home'])==norm(home) and norm(c['away'])==norm(away)]
        match=[c for c in pairs if datetime.fromtimestamp(c['snapshot']['fixture_start_utc'],TSI).date().isoformat()==day]
        if not match:
            message='NBA_REPLAY_NOT_FOUND: Bu maç için doğrulanmış NBA arşiv kaydı yok. Yeni tahmin üretilmedi.'
            if len(pairs)==1:
                p=pairs[0]['snapshot'];correct=datetime.fromtimestamp(p['fixture_start_utc'],TSI).date().isoformat()
                message='FIXTURE_LOCAL_DATE_MISMATCH: Komut tarihi TSİ günüdür. Doğru tarih: '+correct+'; UTC başlangıcı: '+utc(p['fixture_start_utc'])+'. Tarih sessizce değiştirilmedi.'
            return dict(status='ABSTAIN',html=html.escape(message),new_record=False)
        if len(match)!=1:raise ValueError('NBA_REPLAY_AMBIGUOUS_FIXTURE')
        case=deepcopy(match[0]);p=validate_case(case);native=deepcopy(self._native[p['fixture_id']]);parts=render_replay(case,native)
        return dict(status='NBA_ARCHIVE_REPLAY_OK',html=parts[0],html_parts=parts,new_record=False,snapshot=p,
            prediction=deepcopy(p['prediction']),intervals=deepcopy(p['intervals']),mc_qmc=deepcopy(p['mc_qmc']),
            snapshot_sha256=case['snapshot_sha256'],packet_sha256=PACKET_SHA256,
            verified_fixture_source=native,
            timeline=dict(prediction_generated_at_utc=p['prediction_generated_at_utc'],snapshot_created_at_utc=p['created_at_utc'],
                first_archived_at_utc=None,archive_published_at_utc=None,tipoff_utc=p['fixture_start_utc'],
                snapshot_sha256=case['snapshot_sha256'],reused_forecast=True,telegram_reply_at_utc=None,telegram_sent_at_utc=None,
                replay_completed_at_utc=int(time.time())))


def render_replay(case,native):
    p=case['snapshot'];v=p['prediction'];esc=lambda x:html.escape(str(x));pair=lambda q:f'{q[0]:.2f} – {q[1]:.2f}'
    blocks=['<b>ZEYNAL | NBA ARŞİV REPLAY</b>\n'+esc(case['home'])+' – '+esc(case['away'])+'\nBaşlangıç: '+tsi(p['fixture_start_utc'])+
        '\nUTC: '+utc(p['fixture_start_utc'])+'\nYeni PREMATCH tahmini değildir; orijinal kayıt yeniden gösteriliyor.\nNormal süre; uzatma hariç.',
        '<b>ORİJİNAL SKOR PROJEKSİYONU</b>\n'+pair([v['home'],v['away']])+f"\nToplam: {v['total']:.2f} | Ev farkı: {v['margin']:+.2f}\nModel ev handikabı: {v['home_handicap']:+.2f} (piyasa çizgisi değil)"]
    periods='<b>KAYITLI PERİYOTLAR</b>'
    for name,score in [(str(i+1)+'Q',q) for i,q in enumerate(v['quarters'])]+[(str(i+1)+'H',q) for i,q in enumerate(v['halves'])]:
        periods+='\n'+name+': '+pair(score)+f' | Toplam {sum(score):.2f}'
    blocks.append(periods)
    bands='<b>ORİJİNAL QMC ARALIKLARI</b>'
    for market,b in p['intervals']['markets'].items():
        bands+=f"\n{market}: P50 {b['p50']:g} | P25–P75 {b['p25']:g}–{b['p75']:g}\nP10–P90 {b['p10']:g}–{b['p90']:g} | P05–P95 {b['p05']:g}–{b['p95']:g}"
    bands+='\nAralıklar arşivdeki ham dağılımdır; gerçekleşme veya güven garantisi değildir.';blocks.append(bands)
    mc=p['mc_qmc']['mc'];mb=p['mc_qmc']['mc_bands']['markets']['TOTAL'];qb=p['intervals']['markets']['TOTAL']
    text='<b>KAYITLI MC / QMC</b>\nYeni simülasyon çalıştırılmadı.'
    for name,summary,b in [('QMC',v,qb),('MC',mc,mb)]:
        meta=summary['metadata'];text+=f"\n{name}: {esc(meta['method'])}, n={meta['scenarios']}, seed={meta['seed']}\nSkor {pair([summary['home'],summary['away']])} | Toplam {summary['total']:.2f}\nToplam P50 {b['p50']:g} | P25–P75 {b['p25']:g}–{b['p75']:g} | P05–P95 {b['p05']:g}–{b['p95']:g}"
        text+='\nHam normal süre olasılığı (kalibre edilmedi): Ev / eşitlik / dep '+ ' / '.join(f'%{100*x:.2f}' for x in summary['winner'])
    text+='\nBunlar güven yüzdesi veya doğrulanmış başarı oranı değildir.';blocks.append(text)
    blocks.append('<b>KALİBRASYON VE KAYNAK</b>\nNOT_CALIBRATED\nGüven endeksi: hesaplanamadı.\nPiyasa verisi doğrulanamadı; barem/edge/öneri üretilmedi.\nEksik: '+esc(', '.join(p['missing_data']))+
        '\nModel: '+esc(p['model_version'])+'\nModel SHA: '+p['model_digest']+'\nKimliği doğrulanan kaynak: '+esc(native['source_url'])+
        '\nOrijinal fixture_source_url alanı: '+esc(p['fixture_source_url'])+'\nİki alan farklıysa kaynaklar arasından gerçek maç kimliği eşleştirilmiştir; eski alan değiştirilmedi.')
    blocks.append('<b>ORİJİNAL ZAMANLAR VE BÜTÜNLÜK</b>\n'+ '\n'.join(label+': '+utc(p[key])+' | '+tsi(p[key]) for label,key in
        [('Üretim','prediction_generated_at_utc'),('Snapshot','created_at_utc'),('Veri','source_data_time_utc')])+
        '\nSnapshot SHA-256: '+case['snapshot_sha256']+'\nPaket SHA-256: '+PACKET_SHA256+
        '\nVaryant: capture-optimized; dört maç, dört kayıt. İlk varyant arşivleri değiştirilmedi.')
    return split_blocks(blocks)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--packet',default=str(DEFAULT_PACKET));args=parser.parse_args()
    archive=NBAReplayArchive(args.packet)
    print(json.dumps(dict(status='VERIFIED_READ_ONLY_REPLAY',packet_sha256=PACKET_SHA256,
        cases=[dict(home=c['home'],away=c['away'],snapshot_sha256=c['snapshot_sha256'],
            command='/analyze NBA '+datetime.fromtimestamp(c['snapshot']['fixture_start_utc'],TSI).date().isoformat()+' '+c['home']+' vs '+c['away']) for c in archive.cases()],
        new_predictions=0,archive_writes=0,actual_telegram_delivery_verified=False)))


if __name__=='__main__':main()
