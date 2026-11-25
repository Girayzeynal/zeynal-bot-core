"""Credential-safe, bounded access to explicitly configured research providers.

Keys are sent only to fixed HTTPS origins in headers. This module never reads
Fly secrets, production .env files, or Telegram credentials. Provider documents
are additional observations, never edits to an issued forecast.
"""
from copy import deepcopy
from email.utils import parsedate_to_datetime
import argparse
import json
import os
from pathlib import Path
import stat
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from core.team_identity import digest

KEYS = {'THE_ODDS_API': ('ODDS_API_KEY', 'THE_ODDS_API_KEY'),
        'API_BASKETBALL': ('API_SPORTS_KEY', 'API_BASKETBALL_KEY')}
ORIGINS = {'THE_ODDS_API': 'https://api.the-odds-api.com',
           'API_BASKETBALL': 'https://v1.basketball.api-sports.io'}
HEADERS = {'THE_ODDS_API': 'x-api-key', 'API_BASKETBALL': 'x-apisports-key'}
MAX_BYTES = 2 * 1024 * 1024
PRIVATE_FILE = '.zeynal-test-providers.env'


def credentials(env=None, path=None):
    """Optional private allowlist file; parse literals, never source shell code."""
    values = dict(os.environ if env is None else env)
    path = Path.home()/PRIVATE_FILE if path is None else Path(path)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o077 or info.st_size > 8192):
            raise ValueError('PRIVATE_PROVIDER_FILE_OWNER_MODE_OR_SIZE')
        allowed = {name for names in KEYS.values() for name in names}
        # Open without following links and recheck the opened inode, including
        # mode/owner, so a replacement between lstat and read cannot be used.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_ino != info.st_ino or opened.st_dev != info.st_dev or
                    opened.st_uid != os.getuid() or opened.st_mode & 0o077 or
                    not stat.S_ISREG(opened.st_mode) or opened.st_size > 8192):
                raise ValueError('PRIVATE_PROVIDER_FILE_CHANGED')
            body = stream.read(8193)
            if len(body) > 8192:
                raise ValueError('PRIVATE_PROVIDER_FILE_SIZE')
        for line in body.splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            name, sep, value = line.partition('=')
            if not sep or name.strip() not in allowed:
                raise ValueError('PRIVATE_PROVIDER_FILE_ALLOWLIST')
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if not value or len(value) > 512 or any(ord(c) < 33 for c in value):
                raise ValueError('INVALID_PRIVATE_PROVIDER_VALUE')
            if not values.get(name.strip()):
                values[name.strip()] = value
    result = {}
    for provider, names in KEYS.items():
        options = {values[n].strip() for n in names if values.get(n, '').strip()}
        if len(options) > 1:
            raise ValueError('CONFLICTING_PROVIDER_KEY_ALIASES')
        if options:
            result[provider] = options.pop()
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def retry_delay(value,*,now,default=300,maximum=3600):
    """RFC Retry-After delta/date, bounded without trusting malformed hints."""
    if type(value) is int:return min(maximum,max(0,value))
    if type(value) is str:
        if value.isdigit() and len(value)<=10:return min(maximum,int(value))
        try:
            date=parsedate_to_datetime(value)
            if date.tzinfo is not None:return min(maximum,max(0,int(date.timestamp()-now)))
        except (ValueError,TypeError,OverflowError):pass
    return default


def get_document(provider, url, key, *, timeout):
    """No secret in URLs, logs, exception strings or returned HTTP bodies."""
    if provider not in ORIGINS or not url.startswith(ORIGINS[provider]+'/'):
        return dict(status='PROVIDER_ORIGIN_REFUSED')
    uri = urlsplit(url)
    if uri.username or uri.password or uri.fragment or 'apikey' in uri.query.lower():
        return dict(status='PROVIDER_URL_REFUSED')
    observed = int(time.time())
    try:
        request = Request(url, headers={HEADERS[provider]: key, 'Accept': 'application/json',
                                       'User-Agent': 'ZEYNAL-Isolated-Research/1'})
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES:
                return dict(status='PROVIDER_RESPONSE_SIZE_LIMIT')
            document = json.loads(raw, parse_constant=lambda _: None)
            # Some services echo authentication parameters even on HTTP 200.
            # Do not persist a response containing this process's credential.
            if key and key.encode() in raw:
                return dict(status='PROVIDER_SECRET_ECHO_REFUSED')
            quota = {}
            for header in ('x-requests-remaining', 'x-requests-used', 'x-requests-last',
                           'x-ratelimit-requests-remaining', 'x-ratelimit-requests-limit'):
                value = response.headers.get(header)
                if value is not None and value.isdigit():
                    quota[header] = int(value)
            return dict(status='DOCUMENT_RECEIVED', http_status=response.status,
                        source_url=url, provider=provider, observed_at_utc=observed,
                        ingested_at_utc=int(time.time()), document=document,
                        document_sha256=digest(document), quota=quota)
    except HTTPError as exc:
        status = ('AUTHENTICATION_FAILED' if exc.code == 401 else
                  'ACCESS_OR_PLAN_DENIED' if exc.code == 403 else
                  'RATE_LIMITED' if exc.code == 429 else
                  'ENDPOINT_OR_COVERAGE_UNAVAILABLE' if exc.code == 404 else
                  'PROVIDER_HTTP_ERROR')
        retry = exc.headers.get('Retry-After', '')
        exc.close()
        return dict(status=status, http_status=exc.code,
                    retry_after_seconds=retry_delay(retry,now=int(time.time())))
    except Exception:
        return dict(status='PROVIDER_NETWORK_OR_RESPONSE_ERROR')


class ProviderAccess:
    """Per-process quota budget, positive cache, and failure cooldown; no retries."""
    def __init__(self, keys, *, getter=get_document, clock=time.time, max_calls=24):
        self._keys = dict(keys)
        self.getter = getter
        self.clock = clock
        self.max_calls = max_calls
        self.cache = {}
        self.cooldown = {}
        self.remaining = {}
        self.remaining_day = {}
        self.calls = {}
        self.lock = threading.Lock()

    def __repr__(self):
        return '<ProviderAccess credentials=REDACTED>'

    def configuration(self):
        return {p: ('CONFIGURED_NOT_TESTED' if self._keys.get(p) else 'KEY_NOT_AVAILABLE_IN_TEST_PROCESS')
                for p in KEYS}

    def _refresh_daily_quota(self, now):
        # API-Sports resets its daily quota at 00:00 UTC. Odds API quota
        # is subscription-period based: never assume it resets daily.
        p = 'API_BASKETBALL'
        day = self.remaining_day.get(p)
        if day is not None and now//86400 > day:
            self.remaining.pop(p, None)
            self.remaining_day.pop(p, None)

    def runtime_status(self):
        """Credential-free diagnostics; never probes a provider or raises quota."""
        now=int(self.clock())
        if not self.lock.acquire(blocking=False):
            # A native HTTP read owns this lock. Never block Telegram's event
            # loop behind it or report unknown counters as zero.
            return {p:dict(configuration=state,snapshot_status='BUSY',local_calls_today=None,
                local_daily_limit=self.max_calls,local_counter_resets_at_utc=(now//86400+1)*86400,
                provider_reported_remaining=None,cooldown_until_utc=None)
                for p,state in self.configuration().items()}
        try:
            self._refresh_daily_quota(now)
            return {p:dict(configuration=state,snapshot_status='READY',local_calls_today=self.calls.get((p,now//86400),0),
                local_daily_limit=self.max_calls,local_counter_resets_at_utc=(now//86400+1)*86400,
                provider_reported_remaining=self.remaining.get(p),cooldown_until_utc=self.cooldown.get(p))
                for p,state in self.configuration().items()}
        finally:self.lock.release()

    def get(self, provider, path, params=None, *, ttl=120, deadline=None):
        if provider not in ORIGINS or not path.startswith('/') or '..' in path or '?' in path or '#' in path:
            return dict(status='PROVIDER_PATH_REFUSED')
        if not self._keys.get(provider):
            return dict(status='KEY_NOT_AVAILABLE_IN_TEST_PROCESS')
        if params and any(n.lower() in ('apikey','api_key','key','token') for n in params):
            return dict(status='CREDENTIAL_QUERY_FORBIDDEN')
        url = ORIGINS[provider]+path+('?' + urlencode(params) if params else '')
        # A queued caller must not inherit the clock from before lock wait.
        # Even callers without an explicit deadline have a bounded lock wait.
        wait=3. if deadline is None else min(3.,deadline-self.clock())
        if wait<=.05:
            return dict(status='PROVIDER_TIME_BUDGET')
        if not self.lock.acquire(timeout=wait):
            return dict(status='PROVIDER_ACCESS_LOCK_BUSY')
        try:
            if deadline is not None and deadline-self.clock()<=.05:
                return dict(status='PROVIDER_TIME_BUDGET')
            now=int(self.clock())
            self._refresh_daily_quota(now)
            old = self.cache.get(url)
            if old and 0 <= now-old['observed_at_utc'] <= ttl:
                # A cache hit must not alter the source receipt or its hash.
                return deepcopy(old)
            if now < self.cooldown.get(provider, 0):
                return dict(status='PROVIDER_COOLDOWN', retry_after_seconds=self.cooldown[provider]-now)
            if self.remaining.get(provider, 1) <= 0:
                return dict(status='PROVIDER_QUOTA_EXHAUSTED')
            if (provider=='THE_ODDS_API' and path.endswith('/odds') and
                    provider in self.remaining and params and 'markets' in params and 'regions' in params):
                cost=len(set(params['markets'].split(',')))*len(set(params['regions'].split(',')))
                if cost>self.remaining[provider]:
                    return dict(status='ODDS_ESTIMATED_CREDIT_BUDGET',estimated_maximum_credits=cost,
                                provider_reported_remaining=self.remaining[provider])
            budget_key = (provider, now//86400)
            if self.calls.get(budget_key, 0) >= self.max_calls:
                return dict(status='LOCAL_DAILY_REQUEST_BUDGET')
            timeout = min(3., deadline-self.clock()) if deadline is not None else 3.
            if timeout <= .05:
                return dict(status='PROVIDER_TIME_BUDGET')
            self.calls = {k: v for k, v in self.calls.items() if k[1] == now//86400}
            self.calls[budget_key] = self.calls.get(budget_key, 0)+1
            try:
                result = self.getter(provider, url, self._keys[provider], timeout=timeout)
            except Exception:
                result = dict(status='PROVIDER_NETWORK_OR_RESPONSE_ERROR')
            if not isinstance(result,dict) or not isinstance(result.get('status'),str):
                result=dict(status='PROVIDER_NETWORK_OR_RESPONSE_ERROR')
            if result.get('status') == 'DOCUMENT_RECEIVED':
                if (result.get('source_url') != url or result.get('provider') != provider or
                        result.get('document_sha256') != digest(result.get('document')) or
                        type(result.get('observed_at_utc')) is not int or
                        type(result.get('ingested_at_utc')) is not int or
                        not 0 < result['observed_at_utc'] <= result['ingested_at_utc'] <= int(self.clock())):
                    return dict(status='PROVIDER_RECEIPT_INVALID')
                quota=result.get('quota')
                quota=quota if isinstance(quota,dict) else {}
                for name in ('x-requests-remaining','x-ratelimit-requests-remaining'):
                    remaining=quota.get(name)
                    if type(remaining) is int and remaining>=0:
                        self.remaining[provider]=remaining
                        self.remaining_day[provider]=int(self.clock())//86400
                # A completed late read may have spent provider credits, but
                # cannot be admitted as an in-budget result or cached as such.
                if deadline is not None and self.clock()>=deadline:
                    return dict(status='PROVIDER_RESPONSE_AFTER_DEADLINE')
                if len(self.cache) >= 12:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[url] = deepcopy(result)
            else:
                self.cooldown[provider] = int(self.clock())+max(30,retry_delay(result.get('retry_after_seconds'),now=int(self.clock()),default=60))
            return result
        finally:
            self.lock.release()


def preflight(*, check=False):
    access = ProviderAccess(credentials())
    states = access.configuration()
    calls = 0
    if check:
        for provider, endpoint in [('THE_ODDS_API', '/v4/sports/'), ('API_BASKETBALL', '/status')]:
            if states[provider] != 'CONFIGURED_NOT_TESTED':
                continue
            result = access.get(provider, endpoint)
            calls += 1
            state = result['status']
            if state == 'DOCUMENT_RECEIVED':
                doc = result['document']
                if provider == 'THE_ODDS_API':
                    state = 'AUTHENTICATED_SPORTS_CATALOG_RECEIVED' if isinstance(doc, list) else 'INVALID_PROVIDER_SCHEMA'
                else:
                    state = ('AUTHENTICATED_ACCOUNT_STATUS_RECEIVED' if isinstance(doc, dict) and
                             not doc.get('errors') and isinstance(doc.get('response'), dict) and doc['response']
                             else 'PROVIDER_REPORTED_ERROR')
            states[provider] = state
    print(json.dumps(dict(providers=states, api_requests_made=calls,
                          production_changed=False, actual_telegram_delivery_verified=False)))


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description='Safe isolated provider diagnostics; no secret values are printed.')
        parser.add_argument('--check', action='store_true', help='Query sports catalogue/account status only.')
        preflight(check=parser.parse_args().check)
    except Exception:
        print(json.dumps(dict(status='PRIVATE_PROVIDER_CONFIGURATION_ERROR', api_requests_made=0)))
        raise SystemExit(2)
