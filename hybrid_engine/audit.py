"""Honest source-clock/coverage audit. Publication time is never inferred from tipoff."""
from collections import Counter
from datetime import datetime, timezone

from hybrid_engine.data import STRICT, Abstain, feature_cut, inventory
from hybrid_engine.availability import effective_time


def known_fixture(target, observations, cutoff):
    eligible = [o for o in observations if o['fixture_id'] == target['fixture_id'] and o['league'] == target['league'] and o['season'] == target['season']
        and all(o[k] == target[k] for k in ('fixture_start_utc', 'home_team_id', 'away_team_id'))
        and 0 < o['observed_at_utc'] <= o['ingested_at_utc'] and effective_time(o, 'FIXTURE') <= cutoff]
    if not eligible: raise Abstain('NO_PRE_CUTOFF_FIXTURE_KNOWLEDGE')
    return max(eligible, key=lambda o: (effective_time(o, 'FIXTURE'), o['source_catalog_sha256']))


def source_audit(cohort, provenance):
    report = dict(inventory=inventory(cohort), cohorts={},
        publication_time_policy='LOCAL_OBSERVATION_OR_FIELD_BOUND_PUBLIC_ARCHIVE_WITNESS_NO_START_PLUS_DELAY_IMPUTATION',
        season_completeness='NOT_INFERRED_FROM_OBSERVED_GAME_COUNT',
        source_clock_attestation=('NATIVE_API_ARCHIVE_VERSION_WITNESSES_PLUS_CURRENT_LOCAL_RECEIPTS'
            if provenance.get('archive_binding') else 'LOCAL_PINNED_RECEIPTS_NOT_INDEPENDENT_TIMESTAMP_AUTHORITY'))
    for versions in cohort:
        row = versions[0]; key = row['league']+' '+row['season']
        group = report['cohorts'].setdefault(key, dict(start=[], score_observed=[], score_ingested=[],
            box_observed=[], box_ingested=[], missing=Counter(), strict_feature_abstentions=Counter(),
            strict_feature_eligible=0, fixture_known_before_tipoff=0, strict_joint_eligible=0, source_lag_hours=[]))
        group['start'].append(row['fixture_start_utc'])
        group['score_observed'].append(row['observed_at_utc']); group['score_ingested'].append(row['ingested_at_utc'])
        group['source_lag_hours'].append((max(row['observed_at_utc'], row['ingested_at_utc'])-row['fixture_start_utc'])/3600)
        box = row.get('box')
        if not row.get('periods'): group['missing']['PERIODS'] += 1
        if not box: group['missing']['BOX_STATISTICS'] += 1
        else:
            group['box_observed'].append(box['source']['observed_at_utc'])
            group['box_ingested'].append(box['source']['ingested_at_utc'])
            for field in box['missing']: group['missing'][field] += 1
        known = False
        try: known_fixture(row, provenance.get('fixture_knowledge', []), row['fixture_start_utc']-1); known = True
        except Abstain: pass
        group['fixture_known_before_tipoff'] += int(known)
        try: feature_cut(cohort, row, mode=STRICT)
        except Abstain as exc: group['strict_feature_abstentions'][str(exc)] += 1
        else:
            group['strict_feature_eligible'] += 1; group['strict_joint_eligible'] += int(known)
    for group in report['cohorts'].values():
        for field in ('start', 'score_observed', 'score_ingested', 'box_observed', 'box_ingested'):
            values = group.pop(field)
            group[field+'_range_utc'] = None if not values else [datetime.fromtimestamp(v, timezone.utc).isoformat() for v in (min(values), max(values))]
        values = group.pop('source_lag_hours'); group['score_source_lag_hours'] = dict(minimum=min(values), maximum=max(values))
    return report
