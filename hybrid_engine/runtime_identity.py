"""Read-only loaded-service/report provenance; no source queries or model changes."""
import os
import re
import time
from pathlib import Path

from core.team_identity import digest


def _pin(value,length):
    return value if type(value) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}',value) else None


def _class(service):
    return type(service).__module__+'.'+type(service).__qualname__ if service is not None else None


def _label(value):
    return value if type(value) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,200}',value) else None


class ObservedAnalysis:
    def __init__(self,base,state):self.base=base;self.state=state
    def __getattr__(self,name):return getattr(self.base,name)

    async def analyze(self,league,*args,**kwargs):
        report=await self.base.analyze(league,*args,**kwargs)
        # Diagnostics must never turn an otherwise valid response into a failed
        # analysis, or affect the ledger / fallback / publication decisions.
        try:self._observe(league,report)
        except (KeyError,TypeError,ValueError,AttributeError):
            self.state['runtime_identity_capture_status']='UNAVAILABLE_REPORT_METADATA'
        return report

    def _observe(self,league,report):
        code=league.upper()
        if code not in ('NBA','EUROLEAGUE','EUROCUP'):return
        p=report.get('snapshot') or report.get('record') or {}
        version=p.get('model_version');model=p.get('model_digest');pin=digest(p) if p else report.get('forecast_sha256')
        if report.get('status')=='FROZEN_REPLAY_OK' and p:
            component=p['models']['BAYES_QMC'];version=component['prediction']['model'];model=component['model_digest']
        if not p and pin:
            for entry in self.state.get('premium_reports',{}).values():
                ctx=entry.get('europe_context',{})
                if ctx.get('original_forecast_sha256')==pin:
                    version=ctx['model_version'];model=ctx['model_digest'];break
        self.state.setdefault('last_analysis_identity',{})[code]=dict(
            observed_at_utc=int(time.time()),service_class=_class(self.base),status=_label(report.get('status')),
            model_version=_label(version),model_digest=_pin(model,64),snapshot_sha256=_pin(pin,64),
            reason=_label(report.get('reason') or (report.get('preflight') or {}).get('reason')),
            fixture_id=_label(p.get('fixture_id') or (p.get('fixture') or {}).get('canonical_id')),
            new_record=report.get('new_record') is True,
            evidence='LAST_REPORT_RETURNED_TO_HANDLER_NOT_TELEGRAM_DELIVERY',actual_telegram_delivery_verified=False)


def describe(state):
    service=state.get('hybrid_nba_service') or state.get('verified_analysis_service')
    chain=[];current=service
    for _ in range(16):
        if current is None:break
        chain.append(_class(current));current=getattr(current,'base',None)
    baseline=state.get('baseline_store');folder=getattr(baseline,'base_dir',None)
    location='NOT_CONFIGURED'
    if folder is not None:
        path=Path(folder).absolute()
        location='DATA_VOLUME_PATH' if path==Path('/data') or Path('/data') in path.parents else 'APPLICATION_FILESYSTEM_PATH'
    return dict(format='READ_ONLY_ANALYSIS_RUNTIME_IDENTITY_V1',reported_release_sha=_pin(os.getenv('ZEYNAL_RELEASE_SHA'),40),
        entry_profile=state.get('entry_profile'),
        service_chain=chain,last_analysis=state.get('last_analysis_identity',{}),
        last_analysis_failure=state.get('last_analysis_failure',{}),
        identity_status='REPORT_OBSERVED' if state.get('last_analysis_identity') else 'SERVICE_LOADED_ANALYSIS_NOT_OBSERVED',
        legacy_baseline_location=location,data_mount_present=os.path.ismount('/data'),
        europe_auto_scheduler_enabled=state.get('europe_auto_scheduler_enabled'),
        provider_queries_scope='THIS_DIAGNOSTIC_ONLY',
        data_mount_scope='CHECKS_LITERAL_/data_NOT_USERLAND_ARCHIVE',
        ledger_path_exposed=False,provider_queries=0,forecasts_recomputed=False,production_changed=False)


def install(state):
    for key in ('verified_analysis_service','hybrid_nba_service'):
        service=state.get(key)
        if service is not None and not isinstance(service,ObservedAnalysis):state[key]=ObservedAnalysis(service,state)
