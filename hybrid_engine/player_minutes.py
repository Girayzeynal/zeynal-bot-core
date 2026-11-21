"""Prospectively archived rotation priors from past boxes, never target minutes.

Expected minutes are a research projection, not a confirmed lineup. The existing
score model is untouched. Ambiguous availability and identity fail closed.
"""
from copy import deepcopy
import math
from pathlib import Path
import re
import time

import numpy as np
from core.team_identity import digest
from hybrid_engine.boxes import publish_json
from hybrid_engine.data import Abstain, local_path

VERSION='NBA_PAST_ROTATION_MINUTES_SHADOW_V1'
SIDES=('home','away')


def stamp(value):
    if type(value) is not int or value<=0: raise ValueError('POSITIVE_UTC_INTEGER_REQUIRED')
    return value


def historical_minutes(row):
    if row.get('data_kind')!='POSTGAME_ACTUAL_NOT_PREMATCH_LINEUP':
        raise ValueError('EXPLICIT_PAST_BOX_MINUTES_KIND_REQUIRED')
    if row.get('did_not_play') is True: return 0.
    value=row.get('minutes_display')
    if type(value) is not str or not re.fullmatch(r'\d{1,2}(?::[0-5]\d)?',value):
        raise ValueError('BOUNDED_HISTORICAL_DISPLAY_MINUTES_REQUIRED')
    parts=value.split(':'); minutes=int(parts[0])+(int(parts[1])/60 if len(parts)==2 else 0)
    if not 0<=minutes<=48: raise ValueError('REGULATION_PLAYER_MINUTES_REQUIRED')
    return minutes


def capped_rotation(weights):
    """Deterministic proportional prior, total 240, each player's prior <=48."""
    x=np.asarray(weights,dtype=float)
    if x.ndim!=1 or not 6<=len(x)<=30 or not np.isfinite(x).all() or np.any(x<0) or np.sum(x>0)<6:
        raise Abstain('INSUFFICIENT_KNOWN_REPLACEMENT_ROTATION')
    out=np.zeros_like(x); active=x>0; remaining=240.
    for _ in range(len(x)+1):
        proposal=x[active]/x[active].sum()*remaining
        indices=np.flatnonzero(active); hit=proposal>48
        if not np.any(hit): out[indices]=proposal; break
        out[indices[hit]]=48; active[indices[hit]]=False; remaining=240-out.sum()
        if not active.any(): raise Abstain('ROTATION_CAPACITY_UNIDENTIFIED')
    if not np.isfinite(out).all() or abs(out.sum()-240)>1e-7 or np.any(out>48+1e-8):
        raise ValueError('ROTATION_MINUTES_CONSERVATION')
    return out.tolist()


def projection(context,review,rosters,boxes,*,generated_at_utc):
    """Accept only actually available sources. No model is trained here."""
    now=stamp(generated_at_utc); start=stamp(context['fixture_start_utc'])
    if (context['league']!='NBA' or now>int(time.time()) or now>=start or
            type(context.get('original_snapshot_sha256')) is not str or
            re.fullmatch('[0-9a-f]{64}',context['original_snapshot_sha256']) is None or
            review['fixture_id']!=context['fixture_id'] or review['fixture_start_utc']!=start or
            review['original_snapshot_sha256']!=context['original_snapshot_sha256'] or
            review['status']!='CURRENT_SOURCE_OBSERVATIONS' or
            not stamp(review['observed_at_utc'])<=now<stamp(review['valid_until_utc'])):
        raise Abstain('CURRENT_PREMATCH_ROSTER_REVIEW_REQUIRED')
    source_times=[stamp(s['observed_at_utc']) for s in review['sources']]
    if not source_times or max(source_times)>now: raise ValueError('ROSTER_SOURCE_AFTER_PROJECTION')
    if set(rosters['home']['players'])&set(rosters['away']['players']):
        raise ValueError('SAME_PLAYER_ON_BOTH_CURRENT_TEAMS')
    result={}; history=[]; directory_pins={}
    for side in SIDES:
        team=context[side]['provider_id']; directory=rosters[side]
        players=directory['players']; observed=stamp(directory['observed_at_utc'])
        if (directory['team_id']!=team or directory['season']!=context['season'] or observed>now or
                now-observed>300 or len(players)!=len(set(players)) or not 8<=len(players)<=30 or
                any(type(p) is not str or not re.fullmatch('[0-9]{1,15}',p) for p in players) or
                not re.fullmatch('[0-9a-f]{64}',directory['source_sha256'])):
            raise Abstain('FRESH_COMPLETE_TEAM_DIRECTORY_REQUIRED')
        eligible=[]
        for box in boxes:
            if team not in (box['home_team_id'],box['away_team_id']): continue
            if (box['fixture_id']==context['fixture_id'] or box['fixture_start_utc']>=now or
                    box['league']!='NBA' or box['season']!=context['season']):
                raise ValueError('TARGET_OR_FOREIGN_PLAYER_HISTORY_REFUSED')
            available=max(stamp(box['source']['observed_at_utc']),stamp(box['source']['ingested_at_utc']))
            if not box['fixture_start_utc']<available<=now:
                raise ValueError('PLAYER_HISTORY_AVAILABLE_AFTER_PROJECTION')
            if not box.get('regulation_eligible') or box['scope']!='FINAL_WITH_OT': continue
            eligible.append(box)
        if len({b['fixture_id'] for b in eligible})!=len(eligible):
            raise ValueError('DUPLICATE_PLAYER_HISTORY_GAME')
        eligible=sorted(eligible,key=lambda b:(b['fixture_start_utc'],b['fixture_id']))[-6:]
        if len(eligible)<6: raise Abstain('SIX_PAST_REGULATION_BOXES_PER_TEAM_REQUIRED')
        if now-eligible[-1]['fixture_start_utc']>14*86400:
            raise Abstain('PLAYER_ROTATION_HISTORY_STALE')
        values={p:[] for p in players}; present=set()
        for box in eligible:
            rows=[p for p in box['players'] if p['team_id']==team]
            if len(rows)!=len({p['player_id'] for p in rows}): raise ValueError('DUPLICATE_BOX_PLAYER')
            minutes={p['player_id']:historical_minutes(p) for p in rows}
            if abs(sum(minutes.values())-240)>3:
                raise Abstain('PAST_DISPLAY_MINUTES_DO_NOT_RECONCILE')
            present.update(minutes)
            for p in players: values[p].append(minutes.get(p,0.))
            history.append(dict(fixture_id=box['fixture_id'],team_id=team,
                available_at_utc=max(box['source']['observed_at_utc'],box['source']['ingested_at_utc']),box_sha256=digest(box)))
        notes={}; excluded=set()
        for record in review['records']:
            if record['team_id']!=team: continue
            pid=record.get('player_id')
            if not pid or pid not in players: raise Abstain('INCOMPLETE_AVAILABILITY_PLAYER_IDENTITY')
            if stamp(record['status_updated_at_utc'])>now: raise ValueError('FUTURE_PLAYER_STATUS')
            notes.setdefault(pid,[]).append(record)
        for pid,records in notes.items():
            statuses={r['status'] for r in records}
            if len(statuses)!=1: raise Abstain('CONFLICTING_PLAYER_STATUS_NO_MINUTE_GUESS')
            state=next(iter(statuses))
            if state not in ('Out','Available','Suspended'):
                raise Abstain('UNCERTAIN_AVAILABILITY_NO_PLAYING_PROBABILITY_GUESS')
            if state in ('Out','Suspended'):
                sources={r['source'] for r in records}
                if not {'ESPN','NBA_OFFICIAL_PDF'}<=sources:
                    raise Abstain('ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS')
                excluded.add(pid)
        if set(players)-present-excluded:
            raise Abstain('CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY')
        weights=[0. if p in excluded else sum(values[p])/len(eligible) for p in players]
        minutes=capped_rotation(weights)
        result[side]=[dict(player_id=p,expected_minutes=m,status='OUT_SOURCE_CORROBORATED' if p in excluded else
            'PAST_ROTATION_PRIOR_NOT_CONFIRMED_AVAILABLE') for p,m in zip(players,minutes)]
        directory_pins[side]=directory['source_sha256']
        source_times.append(observed)
    payload=dict(format='PROSPECTIVE_PLAYER_MINUTES_V1',version=VERSION,league='NBA',season=context['season'],
        fixture_id=context['fixture_id'],fixture_start_utc=start,
        home_team_id=context['home']['provider_id'],away_team_id=context['away']['provider_id'],
        original_snapshot_sha256=context['original_snapshot_sha256'],generated_at_utc=now,
        observed_at_utc=now,ingested_at_utc=now,source_available_max_utc=max(source_times+[h['available_at_utc'] for h in history]),
        source_review_sha256=digest(review),directory_pins=directory_pins,history=history,
        model_input_kind='PREGAME_PROJECTED_MINUTES_NOT_TARGET_ACTUAL',duration_minutes=48,
        assumptions=['UNREPORTED_AVAILABILITY_IS_NOT_CONFIRMED_AVAILABLE',
            'PAST_SIX_REGULATION_GAMES_PROPORTIONAL_PRIOR',
            'SOURCE_CORROBORATION_IS_NOT_INDEPENDENT_MEDICAL_VERIFICATION',
            'HISTORICAL_DISPLAY_MINUTES_ARE_ROUNDED',
            'NO_LINEUP_OR_MINUTE_UNCERTAINTY_CALIBRATION'],
        actual=None,lineup_verified=False,confidence_index=None,**result)
    return dict(payload=payload,sha256=digest(payload))


def validate_minutes(wrapped,*,asof_utc,fixture=None):
    p=wrapped['payload']; pin=wrapped['sha256']; now=stamp(asof_utc)
    if digest(p)!=pin or p['format']!='PROSPECTIVE_PLAYER_MINUTES_V1' or p['league']!='NBA' or p['version']!=VERSION:
        raise ValueError('PLAYER_MINUTES_PIN_OR_FORMAT')
    if (p['model_input_kind']!='PREGAME_PROJECTED_MINUTES_NOT_TARGET_ACTUAL' or p.get('actual') is not None or
            not 0<stamp(p['source_available_max_utc'])<=stamp(p['generated_at_utc'])<=stamp(p['observed_at_utc'])<=
                stamp(p['ingested_at_utc'])<=now or p['generated_at_utc']>=stamp(p['fixture_start_utc']) or
            p['duration_minutes']!=48): raise ValueError('PLAYER_MINUTES_PIT_CLOCK_OR_KIND')
    if fixture is not None and any(p[k]!=fixture[k] for k in ('league','season','fixture_id','fixture_start_utc','home_team_id','away_team_id')):
        raise ValueError('PLAYER_MINUTES_FIXTURE_MISMATCH')
    if {r['player_id'] for r in p['home']}&{r['player_id'] for r in p['away']}:
        raise ValueError('SAME_PLAYER_ON_BOTH_CURRENT_TEAMS')
    for side in SIDES:
        rows=p[side]; ids=[r['player_id'] for r in rows]
        if (not 8<=len(rows)<=30 or len(ids)!=len(set(ids)) or
                any(type(pid) is not str or not pid.strip() for pid in ids) or
                any(type(r['expected_minutes']) not in (int,float) or not math.isfinite(r['expected_minutes']) or
                    not 0<=r['expected_minutes']<=48+1e-8 for r in rows) or
                any(r.get('status') not in ('OUT_SOURCE_CORROBORATED','PAST_ROTATION_PRIOR_NOT_CONFIRMED_AVAILABLE') or
                    r['status']=='OUT_SOURCE_CORROBORATED' and r['expected_minutes']!=0 for r in rows) or
                abs(sum(r['expected_minutes'] for r in rows)-240)>1e-6):
            raise ValueError('COMPLETE_UNIQUE_PLAYER_MINUTES_REQUIRED')
    return deepcopy(p)


class MinutesArchive:
    def __init__(self,directory):
        self.root=local_path(directory); self.root.mkdir(parents=True,exist_ok=True)

    def record(self,wrapped):
        now=int(time.time()); p=validate_minutes(wrapped,asof_utc=now)
        if now>=p['fixture_start_utc']: raise ValueError('PLAYER_MINUTES_CAPTURE_AFTER_TIPOFF')
        publication=dict(format='PLAYER_MINUTES_PUBLICATION_V1',projection=wrapped,first_archived_at_utc=now,
            classification='PREMATCH',eligible_for_fit=True)
        path=self.root/('minutes-'+wrapped['sha256']+'.json')
        if path.exists():
            prior=self.read(path)
            if prior['projection']!=wrapped: raise ValueError('PLAYER_MINUTES_PUBLICATION_CONFLICT')
            return prior,False
        publish_json(path,dict(payload=publication,sha256=digest(publication)))
        return publication,True

    def read(self,path):
        path=local_path(path)
        if path.parent!=self.root or path.stat().st_size>1024*1024: raise ValueError('MINUTES_ARCHIVE_PATH_OR_SIZE')
        wrapped=__import__('json').loads(path.read_text()); p=wrapped['payload']
        if digest(p)!=wrapped['sha256'] or p['format']!='PLAYER_MINUTES_PUBLICATION_V1':
            raise ValueError('PLAYER_MINUTES_PUBLICATION_PIN')
        projection=validate_minutes(p['projection'],asof_utc=int(time.time()))
        if not projection['generated_at_utc']<=stamp(p['first_archived_at_utc'])<projection['fixture_start_utc']:
            raise ValueError('PLAYER_MINUTES_FIRST_ARCHIVE_AFTER_TIPOFF')
        if path.stem!='minutes-'+p['projection']['sha256'] or p['classification']!='PREMATCH' or p['eligible_for_fit'] is not True:
            raise ValueError('PLAYER_MINUTES_PUBLICATION_SCOPE')
        return p

    def first(self):
        selected={}
        for path in sorted(self.root.glob('minutes-*.json')):
            item=self.read(path); key=(item['projection']['payload']['league'],item['projection']['payload']['season'],
                item['projection']['payload']['fixture_id'])
            if key not in selected or item['first_archived_at_utc']<selected[key]['first_archived_at_utc']:
                selected[key]=item
            elif item['first_archived_at_utc']==selected[key]['first_archived_at_utc'] and item['projection']!=selected[key]['projection']:
                raise ValueError('CONFLICTING_FIRST_PLAYER_PROJECTION')
        return list(selected.values())
