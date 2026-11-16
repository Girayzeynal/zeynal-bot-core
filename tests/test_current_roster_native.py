"""Pinned public-source replay, not a forecast or real Telegram delivery."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from unittest import TestCase

from core.team_identity import digest
from hybrid_engine.current_roster import CurrentRosterReview

PACKET=Path(__file__).resolve().parents[1]/'docs/evidence/roster-phase927-native-20261116.tar.gz'
PIN='3cec9af4bf16a1884e26851a6ddc0a973fdd9309bea7500d16b21c29c89191b3'


def native_cases():
    body=PACKET.read_bytes()
    if hashlib.sha256(body).hexdigest()!=PIN: raise ValueError('ROSTER_NATIVE_PACKET_PIN')
    values={}
    with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as tar:
        for member in tar.getmembers():
            if not member.isfile() or member.size>4*1024*1024 or member.name not in (
                'manifest.json','cases/401909994.json','cases/401909995.json'):
                raise ValueError('ROSTER_NATIVE_PACKET_MEMBER')
            if member.name in values: raise ValueError('DUPLICATE_ROSTER_PACKET_MEMBER')
            values[member.name]=tar.extractfile(member).read()
    manifest=json.loads(values['manifest.json'])
    cases=[]
    for name,pin in manifest['files'].items():
        if hashlib.sha256(values[name]).hexdigest()!=pin: raise ValueError('ROSTER_NATIVE_MEMBER_PIN')
        cases.append(json.loads(values[name]))
    return manifest,cases


class NativeRosterReplayTests(TestCase):
    def test_packet_is_public_source_observation_not_invented_historical_forecast(self):
        manifest,cases=native_cases(); self.assertEqual(len(cases),2)
        self.assertEqual(manifest['predictions_created'],0); self.assertFalse(manifest['actual_telegram_delivery_verified'])
        for case in cases:
            self.assertTrue(case['context']['source_probe']); self.assertIsNone(case['context']['original_snapshot_sha256'])
            self.assertIsNone(case['context']['prediction_generated_at_utc'])
            self.assertEqual(digest(case['review']['payload']),case['review']['sha256'])

    def test_every_native_source_body_and_actual_capture_clock_is_pinned(self):
        _,cases=native_cases()
        for case in cases:
            for r in case['receipts']:
                body=bytes.fromhex(r['body_hex'])
                self.assertEqual(hashlib.sha256(body).hexdigest(),r['body_sha256'])
                self.assertLessEqual(r['started_at_utc'],r['observed_at_utc'])
                self.assertLessEqual(r['observed_at_utc'],case['review']['payload']['observed_at_utc'])

    def test_native_replay_exercises_real_optional_pdf_worker_without_network(self):
        _,cases=native_cases()
        for case in cases:
            by_url={r['url']:r for r in case['receipts']}
            def getter(url,*,deadline):
                r=deepcopy(by_url[url]); r['body']=bytes.fromhex(r.pop('body_hex')); return r
            with self.subTest(fixture=case['context']['provider_fixture_ids']),TemporaryDirectory() as tmp:
                service=CurrentRosterReview(Path(tmp)/'replay',getter=getter,
                    clock=lambda:case['review']['payload']['observed_at_utc'])
                review=service.review(case['context'])
                self.assertEqual(review['status'],'CURRENT_SOURCE_OBSERVATIONS')
                self.assertGreater(len(review['records']),0)
                self.assertFalse(review['model_adjustment_applied']); self.assertFalse(review['actual_telegram_delivery_verified'])
                self.assertIsNone(review['prediction_utc'])
                official=[r for r in review['records'] if r['source']=='NBA_OFFICIAL_PDF']
                expected=[r for r in case['review']['payload']['records'] if r['source']=='NBA_OFFICIAL_PDF']
                if importlib.util.find_spec('pdfplumber') is not None:
                    self.assertEqual(official,expected)
                else:
                    self.assertEqual(review['official_extraction_status'],'PDF_DEPENDENCY_MISSING')
                    self.assertEqual(official,[])
