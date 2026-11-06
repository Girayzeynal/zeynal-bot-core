"""Positive grants are invented fixtures only, never source authorization."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from prediction_inputs import digest
from faz41_evidence import REGISTRY,REGISTRY_PIN
from faz44_policy import template,validate_source_policy,read_source_policy,SCOPE
from tests.test_faz42_history import NOW


class ReviewedPolicyTests(TestCase):
    def setUp(self):
        self.timer=patch('time.time',return_value=NOW);self.timer.start();self.addCleanup(self.timer.stop)

    def seal(self,p):return dict(payload=p,sha256=digest(p))

    def grant(self,p,provider):
        r=dict(decision='PERMITTED',reviewer='SYNTHETIC_TEST_REVIEWER',permission_ref='https://licence.example/synthetic-only',
            reviewed_at_utc=NOW-100,expires_at_utc=NOW+1000,document_sha256='a'*64,allowed_purposes=[SCOPE])
        p['reviews'][provider]=r;p['registry'][provider].update(usage='PERMITTED',**{k:r[k] for k in ('permission_ref','reviewed_at_utc','expires_at_utc')})
        return p

    def validate(self,p):
        s=self.seal(p);return validate_source_policy(s,trusted_sha256=s['sha256'])

    def test_default_template_is_exact_unknown_registry_without_grants(self):
        s=template();r=validate_source_policy(s,trusted_sha256=s['sha256'])
        self.assertEqual(r['registry'],REGISTRY);self.assertEqual(r['registry_sha256'],REGISTRY_PIN);self.assertEqual(r['permitted_providers'],[])
        self.assertFalse(r['provider_signature_verified'])

    def test_permitted_needs_explicit_review_and_independent_trusted_pin(self):
        p=self.grant(template()['payload'],'ESPN');r=self.validate(p);self.assertEqual(r['permitted_providers'],['ESPN'])
        s=self.seal(p);s['payload']['registry']['ESPN']['usage']='UNKNOWN';s['sha256']=digest(s['payload'])
        with self.assertRaisesRegex(ValueError,'PIN_MISMATCH'):validate_source_policy(s,trusted_sha256=r['policy_bundle_sha256'])

    def test_permitted_without_review_or_wrong_document_scope_is_refused(self):
        p=self.grant(template()['payload'],'ESPN');p['reviews']={}
        with self.assertRaisesRegex(ValueError,'EXPLICIT_REVIEW'):self.validate(p)
        for field,value in [('allowed_purposes',['PRODUCTION']),('document_sha256','not-a-digest'),('reviewer','')]:
            p=self.grant(template()['payload'],'ESPN');p['reviews']['ESPN'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate(p)

    def test_builtin_origin_owner_path_and_evidence_level_cannot_be_promoted(self):
        for key,value in [('host','evil.example'),('owner','OTHER'),('paths',['/']),('level','OFFICIAL')]:
            p=template()['payload'];p['registry']['ESPN'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'AUTHORITY_IMMUTABLE'):self.validate(p)

    def test_public_news_can_be_registered_but_never_as_official_lineup(self):
        p=template()['payload'];p['registry']['NEWS']=dict(owner='TEST_PUBLISHER',host='news.example',paths=['/rss/'],types=['NEWS_CLAIM','ANALYST_OPINION'],
            level='COMMENTARY',usage='UNKNOWN',permission_ref=None,reviewed_at_utc=None,expires_at_utc=None)
        p=self.grant(p,'NEWS');r=self.validate(p);self.assertEqual(r['permitted_providers'],['NEWS'])
        p['registry']['NEWS']['types']=['OFFICIAL_LINEUP'];p['registry']['NEWS']['level']='OFFICIAL'
        with self.assertRaisesRegex(ValueError,'NEWS_OR_COMMENTARY'):self.validate(p)

    def test_private_ip_and_localhost_news_destinations_are_refused(self):
        for host in ['127.0.0.1','localhost','api.internal','10.0.0.1','user@news.example']:
            p=template()['payload'];p['registry']['NEWS']=dict(p['registry']['ESPN'],host=host,types=['NEWS_CLAIM'])
            with self.subTest(host=host),self.assertRaises(ValueError):self.validate(p)

    def test_same_host_cannot_be_declared_an_independent_owner(self):
        p=template()['payload'];p['registry']['NEWS']=dict(p['registry']['ESPN'],owner='OTHER_OWNER',types=['NEWS_CLAIM'])
        with self.assertRaisesRegex(ValueError,'HOST_OWNER_CONFLICT'):self.validate(p)

    def test_expired_future_or_inconsistent_review_times_are_refused(self):
        for reviewed,expires in [(NOW+1,NOW+1000),(NOW-100,NOW),(NOW-100,NOW-1)]:
            p=self.grant(template()['payload'],'ESPN')
            for obj in [p['registry']['ESPN'],p['reviews']['ESPN']]:obj.update(reviewed_at_utc=reviewed,expires_at_utc=expires)
            with self.subTest(reviewed=reviewed,expires=expires),self.assertRaises(ValueError):self.validate(p)

    def test_unknown_source_cannot_carry_hidden_review_and_policy_cannot_claim_provider_signature(self):
        p=self.grant(template()['payload'],'ESPN');p['registry']['ESPN']['usage']='UNKNOWN'
        with self.assertRaisesRegex(ValueError,'UNAPPROVED'):self.validate(p)
        p=template()['payload'];p['attestation']='OFFICIAL_PROVIDER_SIGNATURE'
        with self.assertRaisesRegex(ValueError,'SCHEMA_OR_SCOPE'):self.validate(p)

    def test_file_loader_is_readonly_and_symlinks_are_refused(self):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'policy.json';s=template();p.write_text(json.dumps(s));before=p.read_bytes()
            r=read_source_policy(p,trusted_sha256=s['sha256']);self.assertEqual(r['permitted_providers'],[]);self.assertEqual(before,p.read_bytes())
            link=Path(folder)/'link';link.symlink_to(p)
            with self.assertRaises(ValueError):read_source_policy(link,trusted_sha256=s['sha256'])
