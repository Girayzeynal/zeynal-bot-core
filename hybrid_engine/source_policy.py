"""Bounded free-source transport; source clocks never refresh on a cache hit."""
from copy import deepcopy
import json
import threading
import time
from urllib.parse import urlsplit

from core.team_identity import digest
from hybrid_engine.provider_access import retry_delay


class ControlledTransport:
    def __init__(self,primary,*,max_age=240,max_bytes=4*1024*1024,max_cache_bytes=16*1024*1024,reuse_seconds=0):
        if not 0<=reuse_seconds<=max_age:raise ValueError('SOURCE_REUSE_WITHIN_FRESHNESS_REQUIRED')
        self.primary=primary;self.max_age=max_age;self.max_bytes=max_bytes;self.budget=max_cache_bytes
        self.reuse_seconds=reuse_seconds;self.cache={};self.cooldowns={};self.failures={}
        self.host_cooldowns={};self.inflight={};self.lock=threading.Lock();self.requests_made=0;self.cache_hits=0

    def _valid(self,r,provider,url,now):
        try:
            return (isinstance(r,dict) and r.get('status')=='DOCUMENT_RECEIVED' and r.get('http_status')==200 and
                r.get('provider')==provider and r.get('source_url')==url and
                type(r.get('observed_at_utc')) is int and type(r.get('ingested_at_utc')) is int and
                0<r['observed_at_utc']<=r['ingested_at_utc']<=now and
                now-r['observed_at_utc']<=self.max_age and 'document' in r and
                digest(r['document'])==r.get('document_sha256') and len(json.dumps(r).encode())<=self.max_bytes)
        except (TypeError,ValueError):return False

    def _cached(self,key,now):
        entry=self.cache.get(key)
        if entry and self._valid(entry[0],*key,now):return deepcopy(entry[0])
        self.cache.pop(key,None)
        return None

    def _fallback(self,key,result,now):
        cached=self._cached(key,now)
        if cached is None:return result
        cached.update(transport_fallback='FRESH_PINNED_CACHE_SAME_PROVIDER',primary_failure=result['status'])
        return cached

    def __call__(self,provider,url):
        key=(provider,url);host=(provider,urlsplit(url).netloc);now=int(time.time())
        with self.lock:
            cached=self._cached(key,now)
            if cached and self.reuse_seconds and now-cached['observed_at_utc']<=self.reuse_seconds:
                self.cache_hits+=1;return cached
            until=max(self.cooldowns.get(key,0),self.host_cooldowns.get(host,0))
            if now<until:
                return self._fallback(key,dict(provider=provider,source_url=url,status='SOURCE_COOLDOWN',retry_after_seconds=until-now),now)
            event=self.inflight.get(key);owner=event is None
            if owner:self.inflight[key]=event=threading.Event()
        if not owner:
            # Bounded coalescing, not a second request or a detached worker.
            event.wait(1.)
            with self.lock:
                now=int(time.time());cached=self._cached(key,now)
                if cached is not None:self.cache_hits+=1;return cached
                return dict(provider=provider,source_url=url,status='SOURCE_REQUEST_ALREADY_RUNNING_OR_FAILED')
        try:
            with self.lock:self.requests_made+=1
            try:result=self.primary(provider,url)
            except Exception:result=dict(status='SOURCE_NETWORK_ERROR')
            if not isinstance(result,dict) or not isinstance(result.get('status'),str):
                result=dict(status='SOURCE_NETWORK_ERROR')
            now=int(time.time())
            with self.lock:
                if self._valid(result,provider,url,now):
                    self.failures.pop(key,None);self.cooldowns.pop(key,None)
                    size=len(json.dumps(result).encode())
                    for k,(r,_) in list(self.cache.items()):
                        if now-r['observed_at_utc']>self.max_age:self.cache.pop(k,None)
                    while self.cache and sum(s for _,s in self.cache.values())+size>self.budget:
                        self.cache.pop(min(self.cache,key=lambda k:self.cache[k][0]['observed_at_utc']))
                    if size<=self.budget:self.cache[key]=(deepcopy(result),size)
                    return result
                code=result.get('http_status');code=code if type(code) is int else 0
                if code in (403,429):
                    delay=max(1,retry_delay(result.get('retry_after_seconds'),now=now,maximum=86400))
                    self.cooldowns[key]=now+delay
                    if code==429:self.host_cooldowns[host]=now+delay
                elif code>=500 or result.get('status') in ('SOURCE_NETWORK_ERROR','SOURCE_TOTAL_TIMEOUT'):
                    self.failures[key]=min(7,self.failures.get(key,0)+1)
                    delay=max(min(300,5*2**(self.failures[key]-1)),
                        retry_delay(result.get('retry_after_seconds'),now=now,default=0,maximum=86400))
                    self.cooldowns[key]=now+delay;self.host_cooldowns[host]=now+delay
                if result.get('status')=='DOCUMENT_RECEIVED':
                    result=dict(provider=provider,source_url=url,status='INVALID_OR_STALE_SOURCE_REFUSED')
                return self._fallback(key,result,now)
        finally:
            with self.lock:
                self.inflight.pop(key,None);event.set()
