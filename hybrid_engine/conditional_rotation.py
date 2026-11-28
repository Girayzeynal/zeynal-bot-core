"""Conditional rotation research using past observed boxes, never a lineup.
No source access, inferred player availability, probability, score, or model admission.
"""
from collections import defaultdict
import re
from core.team_identity import digest
from hybrid_engine.data import Abstain
from hybrid_engine.player_minutes import capped_rotation,historical_minutes,stamp
from hybrid_engine.time_policy import PREMATCH_MINIMUM_LEAD_SECONDS

BLOCKS=frozenset(('ABSENCE_REQUIRES_BOTH_SOURCE_OBSERVATIONS',
    'UNCERTAIN_AVAILABILITY_NO_PLAYING_PROBABILITY_GUESS',
    'CONFLICTING_PLAYER_STATUS_NO_MINUTE_GUESS',
    'CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY'))

def conditional_rotation(context,review,rosters,boxes,*,now):
    """One baseline + one-at-a-time counterfactual for each reported player.
    Unreported players are not claimed available. Unseen roster members are
    disclosed, not treated as confirmed DNP. Scenarios use only historical roles.
    """
    now=stamp(now)
    if (context['league']!='NBA' or now>=context['fixture_start_utc']-PREMATCH_MINIMUM_LEAD_SECONDS
        or review.get('fixture_id')!=context['fixture_id']
        or review.get('original_snapshot_sha256')!=context['original_snapshot_sha256']
        or review.get('fixture_start_utc')!=context['fixture_start_utc']
        or review.get('status')!='CURRENT_SOURCE_OBSERVATIONS'
        or not stamp(review['observed_at_utc'])<=now<stamp(review['valid_until_utc'])):
        raise Abstain('CONDITIONAL_ROTATION_CONTEXT_OR_CLOCK')
    if set(rosters['home']['players'])&set(rosters['away']['players']):
        raise ValueError('SAME_PLAYER_ON_BOTH_CURRENT_TEAMS')
    output={}
    for side in ('home','away'):
        team=context[side]['provider_id']; roster=rosters[side]
        players=roster['players']; observed=stamp(roster['observed_at_utc'])
        if (roster['team_id']!=team or roster['season']!=context['season']
            or not 0<=now-observed<=300 or not 8<=len(players)<=30
            or len(set(players))!=len(players)
            or any(not isinstance(p,str) or not re.fullmatch('[0-9]{1,15}',p) for p in players)
            or not re.fullmatch('[0-9a-f]{64}',roster['source_sha256'])):
            raise Abstain('CONDITIONAL_ROTATION_ROSTER_UNVERIFIED')
        eligible=[]
        for box in boxes:
            if team not in (box['home_team_id'],box['away_team_id']):continue
            if (box['fixture_id']==context['fixture_id'] or box['league']!='NBA'
                or box['season']!=context['season'] or not box['fixture_start_utc']<
                max(stamp(box['source']['observed_at_utc']),stamp(box['source']['ingested_at_utc']))<=now):
                raise ValueError('CONDITIONAL_ROTATION_HISTORY_CLOCK')
            if box['scope']=='FINAL_WITH_OT' and box.get('regulation_eligible') is True:
                eligible.append(box)
        if len({b['fixture_id'] for b in eligible})!=len(eligible):raise ValueError('DUPLICATE_BOX')
        recent=sorted(eligible,key=lambda b:(b['fixture_start_utc'],b['fixture_id']))[-6:]
        if len(recent)!=6 or now-recent[-1]['fixture_start_utc']>14*86400:
            raise Abstain('CONDITIONAL_ROTATION_HISTORY_INCOMPLETE')
        totals=defaultdict(float); seen=set()
        for b in recent:
            rows=[p for p in b['players'] if p['team_id']==team]
            if len(rows)!=len({p['player_id'] for p in rows}):raise ValueError('DUPLICATE_BOX_PLAYER')
            minutes={p['player_id']:historical_minutes(p) for p in rows}
            if abs(sum(minutes.values())-240)>3:raise Abstain('CONDITIONAL_ROTATION_MINUTES_MISMATCH')
            seen.update(minutes)
            for p,m in minutes.items():totals[p]+=m
        missing=sorted(set(players)-seen)
        active=sorted(set(players)&seen)
        weights=[totals[p]/6 for p in active]
        baseline=capped_rotation(weights)
        def scenario(excluded):
            try:
                m=capped_rotation([0. if p in excluded else w for p,w in zip(active,weights)])
            except Abstain:
                return dict(status='INSUFFICIENT_REPLACEMENT_HISTORY',excluded=sorted(excluded))
            return dict(status='HYPOTHETICAL_ROTATION',excluded=sorted(excluded),
                        projected_minutes=dict(zip(active,m)))
        observations={}
        for row in review['records']:
            if row['team_id']!=team:continue
            pid=row.get('player_id')
            if pid not in players:raise Abstain('CONDITIONAL_ROTATION_UNKNOWN_IDENTITY')
            if stamp(row['status_updated_at_utc'])>now:raise ValueError('FUTURE_PLAYER_STATUS')
            observations.setdefault(pid,[]).append(dict(source=row['source'],status=row['status'],
                                                        status_updated_at_utc=row['status_updated_at_utc']))
        excluded_cases=[scenario({p}) for p in sorted(observations) if p in active]
        output[side]=dict(team_id=team,observed_roster_sha256=roster['source_sha256'],
            past_box_sha256=[digest(b) for b in recent],unseen_current_roster_players=missing,
            observations=observations,baseline_hypothetical_minutes=dict(zip(active,baseline)),
            counterfactuals=excluded_cases,
            all_reported_out_counterfactual=scenario(set(observations)&set(active)) if observations else None)
    return dict(format='HISTORICAL_CONDITIONAL_ROTATION_V1',status='RESEARCH_SCENARIOS_ONLY',
        fixture_id=context['fixture_id'],original_snapshot_sha256=context['original_snapshot_sha256'],
        generated_at_utc=now,source_review_sha256=digest(review),teams=output,
        lineup_verified=False,availability_probability=None,score_computed=False,
        training_eligible=False,production_enabled=False,forecast_changed=False)
