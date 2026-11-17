"""Bounded anonymous official European injury-page discovery; not a model run."""
import argparse,hashlib,json,re,time
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import requests
from bs4 import BeautifulSoup

_COOLDOWN={}
BASE='https://www.euroleaguebasketball.net'
PATHS={'EUROLEAGUE':('/en/euroleague/injury-report/','/euroleague/injury-report/'),
       'EUROCUP':('/en/eurocup/news/','/eurocup/news/')}


def allowed(url,league):
    u=urlsplit(url);part='euroleague' if league=='EUROLEAGUE' else 'eurocup'
    return (u.scheme=='https' and u.netloc in ('www.euroleaguebasketball.net','euroleaguebasketball.net') and not u.query and not u.fragment and
            re.fullmatch(r'/(?:en/)?'+part+r'/(?:injury-report/|news/(?:[a-zA-Z0-9-]+/)?)',u.path) is not None)


def fetch(url,league,*,deadline):
    if not allowed(url,league):return dict(status='SOURCE_URL_REFUSED')
    if deadline-time.monotonic()<.1:return dict(status='SOURCE_DEADLINE')
    at=int(time.time());host=urlsplit(url).netloc.removeprefix('www.')
    if at<_COOLDOWN.get(host,0):return dict(status='SOURCE_COOLDOWN',url=url,retry_after_seconds=_COOLDOWN[host]-at)
    try:
        with requests.get(url,timeout=(2,min(5,max(.1,deadline-time.monotonic()))),stream=True,allow_redirects=False) as r:
            if r.status_code in (301,302,307,308):
                target=urljoin(url,r.headers.get('Location',''))
                return dict(status='SOURCE_REDIRECT',http_status=r.status_code,url=url,
                            location=target if allowed(target,league) else None)
            if r.status_code!=200:
                delay=r.headers.get('Retry-After','300')
                delay=min(3600,max(30,int(delay))) if delay.isdigit() else 300
                if r.status_code in (403,429):_COOLDOWN[host]=int(time.time())+delay
                return dict(status='SOURCE_HTTP_ERROR',http_status=r.status_code,url=url,retry_after_seconds=delay,observed_at_utc=at,ingested_at_utc=int(time.time()))
            chunks=[];size=0
            for block in r.iter_content(32768):
                size+=len(block)
                if size>2*1024*1024:return dict(status='SOURCE_SIZE_BUDGET')
                if time.monotonic()>deadline:return dict(status='SOURCE_DEADLINE')
                chunks.append(block)
            raw=b''.join(chunks)
        return dict(status='RECEIVED',url=url,observed_at_utc=at,ingested_at_utc=int(time.time()),
                    body_sha256=hashlib.sha256(raw).hexdigest(),body=raw.decode('utf-8'))
    except Exception:return dict(status='SOURCE_NETWORK_OR_RESPONSE_ERROR',url=url)


def inspect(receipt,league):
    if receipt.get('status')!='RECEIVED':return dict(receipt)
    soup=BeautifulSoup(receipt['body'],'html.parser');articles=[]
    for tag in soup.find_all('script',type='application/ld+json')[:20]:
        try:articles.append(json.loads(tag.string or tag.get_text()))
        except (ValueError,TypeError):continue
    links=[]
    for tag in soup.find_all('a',href=True):
        url=urljoin(receipt['url'],tag['href']).split('#')[0]
        if allowed(url,league) and 'injur' in url.lower() and url not in links:links.append(url)
    body=soup.get_text(' ',strip=True)
    return dict(status='INSPECTED',url=receipt['url'],body_sha256=receipt['body_sha256'],
                observed_at_utc=receipt['observed_at_utc'],title=soup.title.get_text() if soup.title else None,
                injury_links=links[:16],jsonld=articles[:4],
                script_ids=[t.get('id') for t in soup.find_all('script',id=True)][:10],
                text_sample=body[:600],body_bytes=len(receipt['body'].encode()))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-directory',required=True);a=p.parse_args()
    root=Path(a.output_directory);root.mkdir(parents=True,exist_ok=True);deadline=time.monotonic()+35;results=[]
    for league,paths in PATHS.items():
        queue=[BASE+x for x in paths];seen=set()
        while queue and len(seen)<4 and time.monotonic()<deadline:
            url=queue.pop(0)
            if url in seen:continue
            seen.add(url);receipt=fetch(url,league,deadline=deadline);summary=inspect(receipt,league)
            summary['league']=league;results.append(summary)
            if receipt.get('status')=='RECEIVED':
                (root/(receipt['body_sha256']+'.json')).write_text(json.dumps(receipt,ensure_ascii=False))
                queue.extend(summary['injury_links'][:2])
            if receipt.get('status')=='SOURCE_REDIRECT' and receipt.get('location'):queue.insert(0,receipt['location'])
            print(json.dumps(summary,ensure_ascii=False),flush=True)
    (root/'summary.json').write_text(json.dumps(dict(results=results,forecast_changed=False,production_changed=False),ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
