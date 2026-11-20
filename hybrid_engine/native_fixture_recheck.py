"""Provider-calendar acquisition for the unchanged native fixture validator.

ESPN scoreboard dates use America/New_York, while fixture clocks remain UTC.
The returned receipt retains the real URL/body/clocks. Its extra witness is
explicit local acquisition metadata, not a native provider assertion.
"""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from core.team_identity import digest
from hybrid_engine import adaptive_worker as native

BASE='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates='
VERSION='NBA_PROVIDER_CALENDAR_RECHECK_V1'


def url_for_day(day):return BASE+day+'&limit=1000'


class NativeFixtureRecheck:
    def __init__(self,transport):
        self.transport=transport
        self._verify=native.AdaptiveWorker.verify
        self._policy=dict(format=VERSION,provider='ESPN',calendar='America/New_York',
            scope='NBA_CURRENT_FIXTURE_RECHECK',native_validation='UNCHANGED_ADAPTIVE_WORKER_VERIFY',
            adapter_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            validator_source_sha256=hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest())
        self.policy_sha256=digest(self._policy)

    def identity(self):return dict(self._policy,policy_sha256=self.policy_sha256)

    def verify(self,target):
        if target['league'].upper()!='NBA':
            return self._verify(SimpleNamespace(transport=self.transport),target)
        stamp=target['fixture_start_utc']
        if type(stamp) is not int or stamp<=0:raise ValueError('NATIVE_RECHECK_UTC_START_REQUIRED')
        start=datetime.fromtimestamp(stamp,timezone.utc)
        utc_day=start.strftime('%Y%m%d')
        provider_day=start.astimezone(ZoneInfo('America/New_York')).strftime('%Y%m%d')
        original_url=url_for_day(utc_day);requested_url=url_for_day(provider_day)

        def acquire(provider,url):
            if provider!='ESPN' or url!=original_url:raise ValueError('NATIVE_RECHECK_UNEXPECTED_QUERY')
            receipt=self.transport(provider,requested_url)
            if receipt.get('provider')!=provider or receipt.get('source_url')!=requested_url:
                raise ValueError('NATIVE_RECHECK_SOURCE_BINDING_REQUIRED')
            return receipt

        # Only acquisition changes. Every original canonical/provider ID,
        # team, season, exact UTC clock, status, score and lead-time check runs.
        receipt=self._verify(SimpleNamespace(transport=acquire),target)
        result=deepcopy(receipt)
        if 'runtime_fixture_recheck' in result:raise ValueError('NATIVE_RECHECK_WITNESS_COLLISION')
        result['runtime_fixture_recheck']=dict(self.identity(),
            evidence_scope='LOCAL_ACQUISITION_METADATA_NOT_NATIVE_PROVIDER_FIELDS',
            target_fixture_id=target['fixture_id'],target_start_utc=stamp,
            validator_utc_day=utc_day,provider_calendar_day=provider_day,
            actual_source_url=receipt['source_url'],document_sha256=receipt['document_sha256'])
        return result
