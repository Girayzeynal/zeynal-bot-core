"""Opt-in bounded public reads. No automatic retries, redirects or background jobs."""
from email.utils import parsedate_to_datetime
import json
import time
import urllib.error
import urllib.request

from faz41_evidence import _policy, REGISTRY, REGISTRY_PIN
from faz40_archive import require

MAX_BYTES=4_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('REDIRECT_NOT_ALLOWED')


def fetch(url, *, provider, data_type='OFFICIAL_STAT', format='json', timeout=8,
          registry=REGISTRY, registry_pin=REGISTRY_PIN, opener=None):
    policy=_policy(provider,url,data_type,registry,registry_pin)
    require(type(timeout) in (int,float) and 0<timeout<=15 and format in ('json','rss'),'BOUNDED_REQUEST_REQUIRED')
    if format=='rss':
        now=int(time.time())
        require(data_type in ('NEWS_CLAIM','ANALYST_OPINION') and policy['usage']=='PERMITTED' and
                policy['reviewed_at_utc']<now<=policy['expires_at_utc'],'NEWS_PERMISSION_NOT_ESTABLISHED')
    start=time.monotonic();result=dict(source_url=url,provider=provider,started_at_utc=int(time.time()),
        usage_status=policy['usage'],automatic_retry=False)
    try:
        open_request=(opener or urllib.request.build_opener(NoRedirect())).open
        request=urllib.request.Request(url,headers={'User-Agent':'ZeynalResearch/FAZ41','Accept':'application/json' if format=='json' else 'application/rss+xml'})
        with open_request(request,timeout=timeout) as response:
            result['http_status']=response.status
            require(response.status==200,'HTTP_STATUS_NOT_OK')
            require(response.geturl()==url,'REDIRECT_NOT_ALLOWED')
            media=response.headers.get('Content-Type','').split(';')[0].strip().lower()
            require(media in (('application/json',) if format=='json' else ('application/rss+xml','application/xml','text/xml')),'INVALID_CONTENT_TYPE')
            body=response.read(MAX_BYTES+1);require(len(body)<=MAX_BYTES,'RESPONSE_TOO_LARGE')
            payload=json.loads(body) if format=='json' else body.decode('utf-8')
            require(format!='json' or type(payload) is dict,'JSON_OBJECT_REQUIRED')
            result.update(status='DOCUMENT_RECEIVED',observed_at_utc=int(time.time()),payload=payload)
            date=response.headers.get('Date');result['server_date']=date
            if date:
                try:result['server_clock_delta_seconds']=int(parsedate_to_datetime(date).timestamp())-result['observed_at_utc']
                except (ValueError,TypeError,OverflowError):result['server_clock_delta_seconds']=None
    except urllib.error.HTTPError as ex:
        result.update(status='HTTP_403' if ex.code==403 else 'HTTP_429' if ex.code==429 else 'HTTP_ERROR',
                      http_status=ex.code,retry_after=ex.headers.get('Retry-After'))
    except (TimeoutError,urllib.error.URLError,OSError) as ex:
        result.update(status='TRANSPORT_FAILED',error_type=type(ex).__name__)
    except (ValueError,UnicodeError) as ex:
        result.update(status='INVALID_DOCUMENT',error_type=type(ex).__name__)
    result['finished_at_utc']=int(time.time());result['elapsed_seconds']=round(time.monotonic()-start,6)
    return result
