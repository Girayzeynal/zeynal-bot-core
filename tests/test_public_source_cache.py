"""Free-source cache reuse/coalescing preserves witness clocks and exact URLs."""
from copy import deepcopy
import threading
from unittest import TestCase
from unittest.mock import Mock,patch

from core.team_identity import digest
from hybrid_engine.source_policy import ControlledTransport


def receipt(url='https://test.invalid/a',now=100):
    doc={'native':'synthetic'}
    return dict(provider='TEST',source_url=url,status='DOCUMENT_RECEIVED',http_status=200,
        document=doc,document_sha256=digest(doc),observed_at_utc=now,ingested_at_utc=now)


class PublicSourceCacheTests(TestCase):
    def test_opted_in_short_reuse_preserves_every_receipt_byte_and_expires(self):
        getter=Mock(side_effect=lambda p,u:receipt(u,int(self.now)))
        self.now=100;source=ControlledTransport(getter,reuse_seconds=30)
        with patch('time.time',side_effect=lambda:self.now):
            first=source('TEST','https://test.invalid/a');pin=digest(first)
            self.now=129;second=source('TEST','https://test.invalid/a')
            self.assertEqual(digest(second),pin);getter.assert_called_once()
            second['document']['native']='mutated by caller'
            self.assertEqual(digest(source('TEST','https://test.invalid/a')),pin)
            self.now=131;third=source('TEST','https://test.invalid/a')
            self.assertEqual(third['observed_at_utc'],131);self.assertEqual(getter.call_count,2)

    def test_same_endpoint_concurrent_read_is_one_request_even_without_opt_in(self):
        entered=threading.Event();release=threading.Event();second_checked=threading.Event();answers=[]
        def primary(*args):entered.set();release.wait(2);return receipt()
        source=ControlledTransport(primary);original=source._cached
        def cached(*args):
            value=original(*args)
            if threading.current_thread().name=='waiter':second_checked.set()
            return value
        source._cached=cached
        def run():answers.append(source('TEST','https://test.invalid/a'))
        with patch('time.time',return_value=100):
            owner=threading.Thread(target=run,name='owner');waiter=threading.Thread(target=run,name='waiter')
            try:
                owner.start();self.assertTrue(entered.wait(1));waiter.start()
                self.assertTrue(second_checked.wait(1));release.set()
            finally:
                release.set();owner.join(3)
                if waiter.ident is not None:waiter.join(3)
        self.assertEqual(len(answers),2);self.assertEqual(source.requests_made,1)
        self.assertEqual(answers[0],answers[1]);self.assertFalse(source.inflight)

    def test_rate_limit_and_503_retry_after_apply_to_same_origin_not_other_host(self):
        for http in (429,503):
            getter=Mock(return_value=dict(status='SOURCE_HTTP_ERROR',http_status=http,retry_after_seconds=600))
            source=ControlledTransport(getter)
            with patch('time.time',return_value=100):
                source('TEST','https://test.invalid/a')
                result=source('TEST','https://test.invalid/b')
                self.assertEqual(result['status'],'SOURCE_COOLDOWN');self.assertEqual(result['retry_after_seconds'],600)
                getter.assert_called_once();source('TEST','https://other.invalid/a')
                self.assertEqual(getter.call_count,2)

    def test_403_endpoint_scope_does_not_claim_whole_origin_is_forbidden(self):
        getter=Mock(return_value=dict(status='SOURCE_ACCESS_DENIED',http_status=403,retry_after_seconds='broken'))
        with patch('time.time',return_value=100):
            source=ControlledTransport(getter);source('TEST','https://test.invalid/a')
            self.assertEqual(source('TEST','https://test.invalid/a')['status'],'SOURCE_COOLDOWN')
            source('TEST','https://test.invalid/b');self.assertEqual(getter.call_count,2)

    def test_malformed_or_exceptional_transport_does_not_escape_or_repeat_immediately(self):
        for value in (None,[],dict(status='SOURCE_HTTP_ERROR',http_status=503,retry_after_seconds=None)):
            getter=Mock(return_value=value);source=ControlledTransport(getter)
            with patch('time.time',return_value=100):
                source('TEST','https://test.invalid/a')
                self.assertEqual(source('TEST','https://test.invalid/a')['status'],'SOURCE_COOLDOWN')
                getter.assert_called_once();self.assertFalse(source.inflight)
        getter=Mock(side_effect=RuntimeError('not logged'));source=ControlledTransport(getter)
        with patch('time.time',return_value=100):
            self.assertEqual(source('TEST','https://test.invalid/a')['status'],'SOURCE_NETWORK_ERROR')
            self.assertFalse(source.inflight)

    def test_a_cache_entry_cannot_cross_url_or_survive_its_freshness_clock(self):
        self.now=100;getter=Mock(side_effect=lambda p,u:receipt(u,100))
        source=ControlledTransport(getter,reuse_seconds=30,max_age=30)
        with patch('time.time',side_effect=lambda:self.now):
            source('TEST','https://test.invalid/a');source('TEST','https://test.invalid/b')
            self.assertEqual(getter.call_count,2)
            self.now=131
            self.assertEqual(source('TEST','https://test.invalid/a')['status'],'INVALID_OR_STALE_SOURCE_REFUSED')
        with self.assertRaises(ValueError):ControlledTransport(getter,reuse_seconds=31,max_age=30)
