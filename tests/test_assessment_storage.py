"""Legacy/new stored distribution equivalence, bounded expansion and queue progress."""
from copy import deepcopy
import json
from unittest import TestCase
from unittest.mock import patch

import numpy as np
from core.team_identity import digest
from hybrid_engine.assessment_storage import encode_paths,decode_paths,pack,unpack,native_asset,restore_native
from hybrid_engine.current_assessment import POLICY
from hybrid_engine.data import Abstain
from tests import test_analysis_revision as fixture


class AssessmentStorageTests(TestCase):
    def setUp(self):
        self.h=fixture.AssessmentTests('runTest');self.h.setUp();self.addCleanup(self.h.doCleanups)

    def test_legacy_publication_remains_readable_and_unchanged_beside_compressed_refresh(self):
        def legacy(samples):return dict(format='INTEGER_JOINT_REGULATION_PATHS_V1',dtype=samples.dtype.str,samples=samples.tolist())
        with patch('hybrid_engine.current_assessment.encode_paths',side_effect=legacy), \
                patch('hybrid_engine.current_assessment.native_asset',side_effect=lambda r:r):
            old,_=self.h.capture()
        before=self.h.files();snapshot,paths=self.h.assess.market_context(self.h.original)
        self.assertEqual(snapshot['intervals']['sample_sha256'],old['intervals']['sample_sha256'])
        raw=paths.paths.copy();new_asset=encode_paths(raw)
        self.assertTrue(np.array_equal(raw,decode_paths(new_asset)))
        self.assertLess(len(json.dumps(new_asset)),len(json.dumps(legacy(raw))))
        self.h.h.now+=POLICY['refresh_seconds'];new,_=self.h.capture()
        self.assertEqual(new['original_snapshot_sha256'],old['original_snapshot_sha256'])
        self.assertEqual(len(self.h.assess.registry.records()),2)
        for name,value in before.items():self.assertEqual((self.h.root/name).read_bytes(),value)

    def test_endianness_and_integer_width_do_not_change_paths(self):
        rng=np.random.default_rng(17)
        for dtype in ('<i4','>i4','<i8','>i8'):
            x=rng.integers(0,70,size=(10000,4,2)).astype(dtype)
            restored=decode_paths(encode_paths(x))
            self.assertEqual(x.dtype.str,restored.dtype.str)
            self.assertEqual(x.tobytes(),restored.tobytes())

    def test_decompression_and_source_pin_limits_reject_corruption(self):
        asset=native_asset(self.h.receipt)
        self.assertEqual(restore_native(asset),self.h.receipt)
        self.assertEqual(asset['receipt_sha256'],digest(self.h.receipt))
        bad=deepcopy(asset);bad['receipt_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'NATIVE_RECEIPT_PIN'):restore_native(bad)
        with self.assertRaisesRegex(ValueError,'COMPRESSED_ASSET_LIMIT'):unpack(pack(b'x'*10000),9999)
        bad=encode_paths(np.zeros((10000,4,2),dtype='int64'));bad['samples_b64']=pack(b'x'*640001)
        with self.assertRaisesRegex(ValueError,'COMPRESSED_ASSET_LIMIT'):decode_paths(bad)

    def test_blocked_early_fixtures_cannot_starve_later_eligible_games(self):
        cases=[dict(self.h.case,target=dict(self.h.target,fixture_id=str(i))) for i in range(4)]
        self.h.worker.cases=lambda:cases
        def capture(case,*args):
            if case['target']['fixture_id'] in ('0','1'):raise Abstain('CURRENT_TEST_MISSING_INPUT')
            return dict(fixture=case['target']),True
        with patch.object(self.h.assess,'_capture',side_effect=capture) as attempt:
            self.h.assess.tick();self.h.h.now+=60;self.h.assess.tick()
        self.assertEqual([c.args[0]['target']['fixture_id'] for c in attempt.call_args_list],['0','1','2','3'])

    def test_capture_retry_does_not_scan_unrelated_publications(self):
        with patch.object(self.h.assess.registry,'records',side_effect=AssertionError('UNRELATED_ARCHIVE_SCAN')):
            first,new=self.h.capture();self.assertTrue(new)
            second,new=self.h.capture();self.assertFalse(new);self.assertEqual(first,second)
