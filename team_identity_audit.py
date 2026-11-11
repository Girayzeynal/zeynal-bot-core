"""Opt-in participant coverage report for every configured/requested league."""
import argparse
import json
import time

from core.league_identity import league_catalog,normalize_name
from core.team_identity import TeamIdentityRegistry,IdentityRefusal
from providers.season_participants import SeasonParticipantProvider


def audit_teams(*,year=2026,live=False,provider=None):
    if type(year) is not int or not 2000<=year<=2100 or type(live) is not bool:
        raise ValueError('INVALID_TEAM_AUDIT_CONFIGURATION')
    result={};loader=provider or SeasonParticipantProvider();registry=TeamIdentityRegistry()
    for code,spec in league_catalog().items():
        row=dict(provider=spec.provider,participants=None,official_names_matched=None,ambiguous_alias_keys=None)
        if not spec.provider: row.update(status='PARTICIPANT_ADAPTER_NOT_CONFIGURED')
        elif not live: row.update(status='DRY_RUN_NO_NETWORK')
        else:
            try:
                b=loader.load(code,year);count=registry.ingest(b,trusted_sha256=b['sha256']);at=int(time.time())
                teams=registry.participants(code,f'{year}/{year+1}',asof_utc=at);matched=0;keys={}
                for t in teams:
                    try: matched+=registry.resolve(code,t.season_id,t.official_name,asof_utc=at).internal_id==t.internal_id
                    except IdentityRefusal: pass
                    for name,kind,language,start,end in t.aliases:
                        keys.setdefault(normalize_name(name),set()).add(t.internal_id)
                row.update(status='SEASON_PARTICIPANTS_DISCOVERED',participants=count,official_names_matched=matched,
                    ambiguous_alias_keys=sum(len(ids)>1 for ids in keys.values()),snapshot_sha256=b['sha256'],source_pins=b['payload']['source_pins'])
            except (ValueError,KeyError,TypeError,OSError) as exc:
                row.update(status=str(exc) if isinstance(exc,ValueError) else 'PARTICIPANT_SOURCE_UNAVAILABLE')
        result[code]=row
    return dict(year=year,leagues=result,match_coverage_is_not_prediction_accuracy=True,
        prospective_predictions_created=0,production_database_accessed=False,calibration_status='NOT_ESTABLISHED')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--year',type=int,default=2026);p.add_argument('--live',action='store_true')
    args=p.parse_args(argv)
    try: print(json.dumps(audit_teams(year=args.year,live=args.live),sort_keys=True));return 0
    except ValueError as exc: print(json.dumps(dict(status='TEAM_AUDIT_REFUSED',reason=str(exc))));return 2


if __name__=='__main__':raise SystemExit(main())
