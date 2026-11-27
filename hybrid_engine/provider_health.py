"""Bounded diagnostics of the running isolated bridge, never credential output.

Read-only modes do not query providers. Explicit authorized `providers check`
uses the existing shared access budget for fixed sports/account endpoints.
Neither mode admits a price, fits a model, or edits a first forecast.
"""
import asyncio
import time

from hybrid_engine.isolated_execution import optional_source_thread
from hybrid_engine.provider_access import KEYS

STORAGE_SECONDS=1.5
PROBE_SECONDS=7.
SAFE_STATUS=frozenset(('DOCUMENT_RECEIVED','AUTHENTICATION_FAILED','ACCESS_OR_PLAN_DENIED',
    'RATE_LIMITED','ENDPOINT_OR_COVERAGE_UNAVAILABLE','PROVIDER_HTTP_ERROR',
    'PROVIDER_NETWORK_OR_RESPONSE_ERROR','PROVIDER_RESPONSE_SIZE_LIMIT','PROVIDER_SECRET_ECHO_REFUSED',
    'PROVIDER_RECEIPT_INVALID','PROVIDER_RESPONSE_AFTER_DEADLINE','PROVIDER_TIME_BUDGET',
    'PROVIDER_ACCESS_LOCK_BUSY','PROVIDER_COOLDOWN','PROVIDER_QUOTA_EXHAUSTED',
    'LOCAL_DAILY_REQUEST_BUDGET','KEY_NOT_AVAILABLE_IN_TEST_PROCESS'))


def probe(access,expires):
    """Return only fixed statuses; never native document/error/account bodies."""
    rows={}
    for provider,path in (('THE_ODDS_API','/v4/sports/'),('API_BASKETBALL','/status')):
        if access.configuration().get(provider)!='CONFIGURED_NOT_TESTED':
            rows[provider]=dict(status='KEY_NOT_AVAILABLE_IN_TEST_PROCESS');continue
        remaining=expires-time.monotonic()
        if remaining<=.05:
            rows[provider]=dict(status='PROVIDER_TIME_BUDGET');continue
        result=access.get(provider,path,deadline=time.time()+min(3.,remaining))
        state=result.get('status')
        row=dict(status=state if state in SAFE_STATUS else 'UNVERIFIED_PROVIDER_RESPONSE')
        http=result.get('http_status')
        if type(http) is int and 100<=http<=599:row['http_status']=http
        if state=='DOCUMENT_RECEIVED':
            document=result.get('document')
            if provider=='THE_ODDS_API':
                row['status']='SPORTS_CATALOG_RECEIVED' if isinstance(document,list) else 'INVALID_PROVIDER_SCHEMA'
            elif (isinstance(document,dict) and not document.get('errors') and
                    isinstance(document.get('response'),dict) and document['response']):
                row['status']='ACCOUNT_STATUS_RECEIVED'
            else:
                row['status']='PROVIDER_REPORTED_ERROR'
                from hybrid_engine.provider_diagnostics import failure
                row['error_codes']=failure(result,'ACCOUNT_STATUS')['error_codes']
        rows[provider]=row
    return rows


async def inspect(bridge,*,include_storage=False,check=False):
    report=dict(format='ISOLATED_RUNNING_PROVIDER_HEALTH_V1',scope='RUNNING_TEST_PROCESS',
        observed_at_utc=int(time.time()),providers={},storage_status='NOT_REQUESTED',
        probe_status='NOT_REQUESTED',diagnostic_provider_queries_requested=bool(check),
        forecasts_changed=False,actual_market_coverage_verified=False,
        actual_telegram_delivery_verified=False,production_changed=False)
    if bridge is None:
        report['status']='PROVIDER_BRIDGE_NOT_LOADED';return report
    try:
        report['providers']=bridge.access.runtime_status()
        report['status']='READ_ONLY_PROCESS_SNAPSHOT'
    except (ValueError,KeyError,TypeError,OSError,RuntimeError):
        report['status']='PROVIDER_STATUS_UNAVAILABLE_NOT_ZERO'
    if check:
        try:
            expires=time.monotonic()+PROBE_SECONDS
            report['probe']=await asyncio.wait_for(optional_source_thread(probe,bridge.access,expires),PROBE_SECONDS)
            report['probe_status']='CHECK_COMPLETED'
        except asyncio.TimeoutError:report['probe_status']='PROBE_TIMEOUT_NOT_VERIFIED'
        except (ValueError,KeyError,TypeError,OSError,RuntimeError):
            report['probe_status']='PROBE_FAILED_NOT_VERIFIED'
        # Show counters/quota after this check, or explicit BUSY/unknown when
        # its native worker outlives the await deadline. Never keep stale zero.
        try:
            report['providers']=bridge.access.runtime_status()
            report['status']='PROVIDER_CHECK_PROCESS_SNAPSHOT'
        except (ValueError,KeyError,TypeError,OSError,RuntimeError):
            report['status']='PROVIDER_STATUS_UNAVAILABLE_NOT_ZERO'
    if include_storage:
        try:
            raw=await asyncio.wait_for(optional_source_thread(bridge.storage_status),STORAGE_SECONDS)
            if not isinstance(raw,dict):raise ValueError('PROVIDER_STORAGE_STATUS_SCHEMA')
            names=('files','bytes','legacy_files','segmented_files','segments','segment_maximum_files','maximum_files')
            report['storage']={k:raw[k] for k in names if type(raw.get(k)) is int and raw[k]>=0}
            report['storage_status']=raw['status'] if raw.get('status') in ('AVAILABLE','LOCAL_EVIDENCE_STORAGE_FULL') else 'UNVERIFIED_STORAGE_STATUS'
        except asyncio.TimeoutError:report['storage_status']='STORAGE_READ_TIMEOUT'
        except (ValueError,KeyError,TypeError,OSError,RuntimeError):report['storage_status']='STORAGE_READ_UNAVAILABLE'
    return report


def render(report):
    lines=['SAĞLAYICI BAĞLANTILARI | ÇALIŞAN İZOLE SÜREÇ',report['status'],
        'Bu görünüm FAZ17 başlangıç satırından ayrı ProviderBridge durumudur.',
        'CONFIGURED_NOT_TESTED anahtarın yüklendiğini belirtir; kaynak kontrolü aşağıda ayrıca gösterilir.']
    providers=report['providers']
    for provider in KEYS:
        state=providers.get(provider,{})
        configuration=state.get('configuration')
        if configuration not in ('CONFIGURED_NOT_TESTED','KEY_NOT_AVAILABLE_IN_TEST_PROCESS'):
            configuration='UNVERIFIED_PROVIDER_CONFIGURATION'
        lines.append(provider+': '+configuration)
        if state.get('snapshot_status')=='BUSY':
            lines.append('Kaynak erişimi sürüyor; sayaç kilidi beklenmedi. Kullanım/kota şu anda bilinmiyor.')
        else:
            calls=state.get('local_calls_today');limit=state.get('local_daily_limit')
            remaining=state.get('provider_reported_remaining')
            display=lambda n:str(n) if type(n) is int and n>=0 else 'bilinmiyor'
            lines.append('Yerel istek '+display(calls)+'/'+display(limit)+
                ' · sağlayıcının bildirdiği kalan '+display(remaining))
        result=report.get('probe',{}).get(provider)
        if result:
            lines.append('Temel kaynak kontrolü: '+result['status']+
                (' · HTTP '+str(result['http_status']) if 'http_status' in result else ''))
            if result.get('error_codes'):lines.append('Kaynak hata sınıfı: '+', '.join(result['error_codes']))
    if report['storage_status']!='NOT_REQUESTED':
        lines.append('Yerel sağlayıcı kanıtı: '+report['storage_status'])
        storage=report.get('storage',{})
        if 'files' in storage:lines.append('Toplam belge: '+str(storage['files']))
        if 'segment_maximum_files' in storage:
            lines.append('SHA bölüm başına belge sınırı: '+str(storage['segment_maximum_files']))
        elif 'maximum_files' in storage:lines.append('Eski depo belge sınırı: '+str(storage['maximum_files']))
    if report['probe_status']=='NOT_REQUESTED':
        lines.extend(['Bu tanılama API isteği yapmadı; anahtarın yüklü olması bağlantı kanıtı değildir.',
            'Temel katalog/hesap kontrolü: /test providers check'])
    else:
        lines.extend(['Kontrol: '+report['probe_status'],
            'Kontrol mevcut ortak kota/önbellek/bekleme kurallarını kullanır; yeni abonelik yok.',
            'Katalog/hesap yanıtı maç, fiyat, Nesine veya ödeme kapsamını doğrulamaz.'])
    return lines
