"""Exercise the prepared-model staging -> preflight -> hybrid service startup chain.

No network, Telegram bot token, production disk, or prediction delivery.
"""
import tempfile
import unittest
from pathlib import Path

from hybrid_engine.prepared_preflight import check
from hybrid_engine.stage_archived_model import stage
from hybrid_engine.live_nba import LiveNBAHybridService, PreparedBayes


PACKET = Path(__file__).resolve().parents[1] / 'docs/evidence/nba-phase843-prospective-native-20261113.tar.gz'


class ResearchStartupChainTests(unittest.TestCase):
    def test_staged_pinned_model_starts_isolated_hybrid_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models = root / 'models'
            research = root / 'research'
            models.mkdir()
            research.mkdir()
            staged = stage(str(PACKET), str(models))
            readiness = check(staged['path'], staged['sha256'], str(research))
            self.assertEqual(readiness['status'], 'RESEARCH_PREPARED_ARTIFACT_VALID')
            prepared = PreparedBayes(staged['path'], trusted_sha256=staged['sha256'])
            service = LiveNBAHybridService(str(research), prepared)
            self.assertEqual(service.prepared.sha256, staged['sha256'])
            self.assertTrue((research / 'nba-hybrid.sqlite').exists())
            self.assertFalse((models / 'nba-hybrid.sqlite').exists())
            self.assertFalse(staged['production_promotion'])
            self.assertFalse(readiness['calibrated'])


if __name__ == '__main__':
    unittest.main()
