"""Indexed, read-only view of an existing current-assessment protocol.

Do not change the hash-pinned producer just to repair the Telegram reader.
Reuse exactly its registry, policy validation and joint-path verification.
"""
from hybrid_engine.current_assessment import CurrentAssessments


class IndexedMarketReader(CurrentAssessments):
    def __init__(self, existing):
        self.root=existing.root
        self.registry=existing.registry
        self.worker=existing.worker
        self.study=existing.study
        self.last_report=None

    def latest(self, context):
        return self.latest_display(context)
