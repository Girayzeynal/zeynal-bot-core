"""Bounded free-source transport; preserve observation clocks and honor Retry-After."""
from copy import deepcopy
import json
import time

from core.team_identity import digest


class ControlledTransport:
    def __init__(self,primary,*,max_age=240,max_bytes=4*1024*1024,max_cache_bytes=16*1024*1024):
        self.primary=primary;self.max_age=max_age;self.max_bytes=max_bytes;self.budget=max_cache_bytes
        self.cache={};self.cooldowns={};self.failures={}

    def _valid(self,r,provider,url,now):
        return (r.get('status')=='DOCUMENT_RECEIVED' and r.get('http_status')==200 and
            r.get('provider')==provider and r.get('source_url')==url and
            type(r.get('observed_at_utc')) is int and type(r.get('ingested_at_utc')) is int and
            0<r['observed_at_utc']<=r['ingested_at_utc']<=now and
            now-r['observed_at_utc']<=self.max_age and 'document' in r and
            digest(r['document'])==r.get('document_sha256') and len(json.dumps(r).encode())<=self.max_bytes)

    def __call__(self,provider,url):
        now=int(time.time());key=(provider,url)
        for k,(r,size) in list(self.cache.items()):
            if not self._valid(r,*k,now):self.cache.pop(k,None)
        if now<self.cooldowns.get(key,0):
            result=dict(provider=provider,source_url=url,status='SOURCE_COOLDOWN',retry_after_seconds=self.cooldowns[key]-now)
        else:
            result=self.primary(provider,url)
            now=int(time.time())
            if result.get('http_status') in (403,429):
                retry=result.get('retry_after_seconds',300)
                self.cooldowns[key]=now+min(86400,max(1,int(retry)))
            elif result.get('http_status',0)>=500 or result.get('status') in ('SOURCE_NETWORK_ERROR','SOURCE_TOTAL_TIMEOUT'):
                self.failures[key]=min(7,self.failures.get(key,0)+1)
                self.cooldowns[key]=now+min(300,5*2**(self.failures[key]-1))
            if self._valid(result,provider,url,now):
                self.failures.pop(key,None);self.cooldowns.pop(key,None)
                size=len(json.dumps(result).encode())
                while self.cache and sum(s for r,s in self.cache.values())+size>self.budget:
                    self.cache.pop(min(self.cache,key=lambda k:self.cache[k][0]['observed_at_utc']))
                if size<=self.budget:self.cache[key]=(deepcopy(result),size)
                return result
            if result.get('status')=='DOCUMENT_RECEIVED':result=dict(provider=provider,source_url=url,status='INVALID_OR_STALE_SOURCE_REFUSED')
        if key in self.cache:
            cached=deepcopy(self.cache[key][0]);cached['transport_fallback']='FRESH_PINNED_CACHE_SAME_PROVIDER'
            cached['primary_failure']=result['status'];return cached
        return result
