"""Immutable season-scoped identity snapshots; no fuzzy merges or DB writes."""
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import time
from uuid import UUID,uuid5

from core.league_identity import normalize_name,resolve_league


NAMESPACE=UUID('93d92d69-c64b-50b9-88ea-0bb081eb6274')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def internal_team_id(provider,provider_id):
    return str(uuid5(NAMESPACE,provider+':'+provider_id))


@dataclass(frozen=True)
class TeamIdentity:
    internal_id: str
    league_id: str
    season_id: str
    official_name: str
    provider_ids: tuple
    aliases: tuple
    source_digest: str


class IdentityRefusal(ValueError):
    pass


class TeamIdentityRegistry:
    def __init__(self):
        self._snapshots={}
        self._refusals=[]

    @property
    def refusals(self):
        return tuple(deepcopy(self._refusals))

    def ingest(self,snapshot,*,trusted_sha256):
        snapshot=deepcopy(snapshot)
        p=snapshot['payload']
        if set(snapshot)!={'payload','sha256'} or snapshot['sha256']!=trusted_sha256 or digest(p)!=trusted_sha256:
            raise IdentityRefusal('PARTICIPANT_SNAPSHOT_PIN_MISMATCH')
        spec=resolve_league(p['league_id'])
        if (p['format']!='SEASON_PARTICIPANTS_V1' or type(p['year']) is not int or
                p['season_id']!=f"{p['year']}/{p['year']+1}" or type(p['observed_at_utc']) is not int or
                type(p['ingested_at_utc']) is not int or not 0<p['observed_at_utc']<=p['ingested_at_utc']<=int(time.time()) or
                not p['source_pins'] or not p['participants'] or p['participant_count']!=len(p['participants'])):
            raise IdentityRefusal('INVALID_PARTICIPANT_SNAPSHOT')
        if (p.get('membership_basis')!='SEASON_PARTICIPANT_ENDPOINT_NOT_GAME_SAMPLES' or
                p.get('source_attestation')!='LOCAL_HASH_NOT_INDEPENDENT_ATTESTATION'):
            raise IdentityRefusal('SEASON_PARTICIPANT_PROVENANCE_REQUIRED')
        for pin in p['source_pins'].values():
            if (type(pin.get('url')) is not str or not pin['url'].startswith('https://') or
                    type(pin.get('document_sha256')) is not str or len(pin['document_sha256'])!=64 or
                    type(pin['observed_at_utc']) is not int or type(pin['ingested_at_utc']) is not int or
                    not 0<pin['observed_at_utc']<=pin['ingested_at_utc']<=p['ingested_at_utc']):
                raise IdentityRefusal('PARTICIPANT_SOURCE_PIN_INVALID')
        ids=set(); teams=[]
        for row in p['participants']:
            provider,pid=row['provider'],row['provider_id']
            if (provider!=spec.provider or type(pid) is not str or not pid or pid!=pid.strip() or
                    (provider,pid) in ids or row['internal_id']!=internal_team_id(spec.identity_namespace,pid)):
                raise IdentityRefusal('PROVIDER_TEAM_ID_CONFLICT')
            ids.add((provider,pid));normalize_name(row['official_name'])
            variants=[]
            for alias in row['aliases']:
                normalize_name(alias['name'])
                start,end=alias['valid_from_utc'],alias['valid_until_utc']
                if type(start) is not int or start<=0 or (end is not None and (type(end) is not int or end<=start)):
                    raise IdentityRefusal('INVALID_ALIAS_VALIDITY')
                variants.append((alias['name'],alias['kind'],alias['language'],start,end))
            teams.append(TeamIdentity(row['internal_id'],spec.code,p['season_id'],row['official_name'],
                ((provider,pid),),tuple(variants),trusted_sha256))
        key=(spec.code,p['season_id'])
        versions=self._snapshots.setdefault(key,{})
        at=p['ingested_at_utc']
        if at in versions and versions[at][0]!=trusted_sha256:
            raise IdentityRefusal('CONFLICTING_PARTICIPANT_SNAPSHOT_AT_SAME_CLOCK')
        versions[at]=(trusted_sha256,tuple(teams))
        return len(teams)

    def resolve(self,league,season,name,*,asof_utc):
        spec=resolve_league(league); key=normalize_name(name)
        if type(asof_utc) is not int or not 0<asof_utc<=int(time.time()):
            raise IdentityRefusal('INVALID_IDENTITY_CUTOFF')
        versions=self._snapshots.get((spec.code,season),{})
        available=[t for t in versions if t<=asof_utc]
        if not available: return self._refuse('SEASON_PARTICIPANTS_UNAVAILABLE_AT_CUTOFF',spec.code,season,key,(),asof_utc)
        _,teams=versions[max(available)]
        found=[t for t in teams if any(start<=asof_utc and (end is None or asof_utc<end) and
                                      normalize_name(alias)==key for alias,kind,language,start,end in t.aliases)]
        if len(found)!=1:
            return self._refuse('AMBIGUOUS_TEAM_ALIAS' if found else 'TEAM_ALIAS_NOT_REGISTERED',
                                spec.code,season,key,tuple(t.internal_id for t in found),asof_utc)
        return found[0]

    def _refuse(self,reason,league,season,key,candidates,asof):
        self._refusals.append(dict(reason=reason,league=league,season=season,normalized_alias=key,candidates=candidates,
                                  created_at_utc=int(time.time()),query_cutoff_utc=asof))
        self._refusals=self._refusals[-1000:]
        raise IdentityRefusal(reason)

    def participants(self,league,season,*,asof_utc):
        if type(asof_utc) is not int or not 0<asof_utc<=int(time.time()):
            raise IdentityRefusal('INVALID_IDENTITY_CUTOFF')
        spec=resolve_league(league)
        versions=self._snapshots.get((spec.code,season),{})
        available=[t for t in versions if t<=asof_utc]
        return () if not available else versions[max(available)][1]
