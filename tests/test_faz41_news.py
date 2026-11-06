from copy import deepcopy
from email.utils import formatdate
from unittest import TestCase
from unittest.mock import patch

import faz41_news as n
import faz41_evidence as e
from prediction_inputs import digest
from tests.test_faz41_evidence import NOW,FIXTURE

URL='https://news.example/rss/feed'
ARTICLE='https://news.example/news/one'


class NewsTests(TestCase):
    def setUp(self):
        self.clock=patch('time.time',return_value=NOW+1);self.clock.start();self.addCleanup(self.clock.stop)
        self.registry={'NEWS':dict(owner='PUBLISHER',host='news.example',paths=['/rss/'],types=['NEWS_CLAIM','ANALYST_OPINION'],
            level='COMMENTARY',usage='PERMITTED',permission_ref='https://licence.example/synthetic-grant',reviewed_at_utc=NOW-100,expires_at_utc=NOW+1000)}
        self.pin=digest(self.registry);self.bindings={ARTICLE:FIXTURE['canonical_id']};self.binding_pin=digest(self.bindings)

    def raw(self,published=NOW-20):
        return {'rss':f'<rss><channel><item><title>Analyst suggests a rotation change</title><link>{ARTICLE}</link><pubDate>{formatdate(published,usegmt=True)}</pubDate></item></channel></rss>'}

    def capture(self,raw=None,**updates):
        args=dict(fixture=FIXTURE,bindings=self.bindings,bindings_pin=self.binding_pin,provider='NEWS',source_url=URL,
            observed_at_utc=NOW-10,ingested_at_utc=NOW-5,data_type='ANALYST_OPINION',usage='SYNTHETIC_TEST',registry=self.registry,registry_pin=self.pin)
        args.update(updates)
        with patch('time.time',return_value=NOW):return n.capture_rss(raw or self.raw(),**args)

    def replay(self,o,**updates):
        args=dict(fixture=FIXTURE,cutoff_utc=NOW+1,maximum_age_seconds=60,registry=self.registry,registry_pin=self.pin,
                  bindings=self.bindings,bindings_pin=self.binding_pin)
        args.update(updates);return n.replay_rss(o,**args)

    def test_commentary_remains_unverified_and_does_not_create_injury_or_lineup(self):
        p=self.replay(self.capture())
        self.assertEqual(p['evidence_level'],'COMMENTARY');self.assertEqual(p['claims']['claim_status'],'UNVERIFIED_SOURCE_CLAIM')
        for kind in ('OFFICIAL_LINEUP','INJURY_REPORT'):
            with self.assertRaisesRegex(ValueError,'NEWS_IS_NOT'):self.capture(data_type=kind)

    def test_unknown_permission_cannot_capture_news(self):
        self.registry['NEWS']['usage']='UNKNOWN';self.pin=digest(self.registry)
        with self.assertRaisesRegex(ValueError,'PERMISSION'):self.capture()

    def test_explicit_fixture_binding_and_trusted_pin_are_required(self):
        for bindings,pin in [({},digest({})),({ARTICLE:'other'},digest({ARTICLE:'other'})),(self.bindings,'0'*64)]:
            with self.subTest(bindings=bindings),self.assertRaises(ValueError):self.capture(bindings=bindings,bindings_pin=pin)

    def test_future_publication_stale_publication_and_naive_dates_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'PUBLICATION_CHRONOLOGY'):self.capture(self.raw(NOW))
        with self.assertRaisesRegex(ValueError,'STALE_PUBLICATION'):self.replay(self.capture(self.raw(NOW-1000)))
        raw=self.raw();raw['rss']=raw['rss'].replace(formatdate(NOW-20,usegmt=True),'Fri, 06 Nov 2026 12:00:00')
        with self.assertRaisesRegex(ValueError,'TIMEZONE'):self.capture(raw)

    def test_entities_duplicate_binding_and_invalid_xml_are_rejected(self):
        for text in ['<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>','<rss>',self.raw()['rss'].replace('</channel>',self.raw()['rss'].split('<channel>')[1].split('</channel>')[0]+'</channel>')]:
            with self.subTest(text=text[:30]),self.assertRaises(ValueError):self.capture({'rss':text})

    def test_rehashed_headline_cannot_bypass_replay(self):
        o=self.capture();o['payload']['claims']['headline']='confirmed lineup';o['sha256']=digest(o['payload'])
        with self.assertRaisesRegex(ValueError,'CANNOT_REPLAY'):self.replay(o)
