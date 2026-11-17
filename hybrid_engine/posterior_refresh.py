"""Offline conjugate update of a frozen team hierarchy, with fixed noise.

The native cut stores only the target teams' recent matches, not the complete
original training set. Never pretend these 19-ish rows are a full league refit.
Reuse the original posterior sufficient statistics and add distinct past games.
Revised labels require a separate full refit; old contributions cannot be erased.
"""
from copy import deepcopy

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import STRICT, Abstain, available_at, regulation

VERSION = 'OFFLINE_FIXED_NOISE_TEAM_POSTERIOR_REFRESH_V1'


def refresh(prepared, cut):
    a = prepared.payload['model']
    if (cut.evaluation_class != STRICT or tuple(a['identity']) != (cut.target['league'], cut.target['season']) or
            not a['cutoff_utc'] <= cut.cutoff_utc < cut.target['fixture_start_utc'] or
            cut.target['fixture_id'] in a['training_ids']):
        raise ValueError('POSTERIOR_REFRESH_SCOPE_OR_CUTOFF')
    trace = {r['fixture_id']: r for r in prepared.payload['training_rows']}
    if set(trace) != set(a['training_ids']): raise ValueError('POSTERIOR_REFRESH_ORIGINAL_TRAINING_TRACE')
    seen = set(); additions = []
    for row in cut.history:
        if (row['fixture_id'] == cut.target['fixture_id'] or row['fixture_id'] in seen or
                (row['league'], row['season']) != tuple(a['identity']) or
                not row['fixture_start_utc'] < available_at(row, STRICT) <= cut.cutoff_utc or
                regulation(row) is None):
            raise ValueError('POSTERIOR_REFRESH_HISTORY_LEAKAGE_OR_DUPLICATION')
        seen.add(row['fixture_id'])
        if row['fixture_id'] in trace:
            if regulation(row) != trace[row['fixture_id']]['regulation_scores']:
                raise Abstain('PAST_LABEL_REVISION_REQUIRES_FULL_REFIT')
            continue
        if any(row[s+'_team_id'] not in a['teams'] for s in ('home','away')):
            raise Abstain('NEW_TEAM_REQUIRES_FULL_HIERARCHY_REFIT')
        additions.append(row)
    model = deepcopy(prepared.model)
    x = []; y = []
    for row in sorted(additions, key=lambda r: (available_at(r, STRICT), r['fixture_id'])):
        for j, (side, other) in enumerate((('home','away'),('away','home'))):
            v, _ = model._vector(row[side+'_team_id'], row[other+'_team_id'], side == 'home')
            x.append(v); y.append(regulation(row)[j])
    if additions:
        x = np.asarray(x); y = np.asarray(y)
        precision = np.linalg.inv(model.covariance)
        updated = precision+x.T@x/model.noise_variance
        rhs = precision@model.coefficients+x.T@y/model.noise_variance
        model.covariance = np.linalg.inv(updated)
        model.coefficients = np.linalg.solve(updated, rhs)
    model.cutoff = cut.cutoff_utc
    model.training_ids = sorted(set(a['training_ids'])|{r['fixture_id'] for r in additions})
    model.training_available_max = max([a['training_available_max']]+[available_at(r, STRICT) for r in additions])
    model.training_digest = digest(dict(original_artifact=prepared.sha256,
        updates=[dict(id=r['fixture_id'], scores=regulation(r), source=r['source_catalog_sha256'],
                      available_at_utc=available_at(r, STRICT)) for r in sorted(additions, key=lambda r:r['fixture_id'])]))
    model.team_prior_sd = a['prior_scales']['team']; model.player_prior_sd = a['prior_scales']['player']
    model.artifact_digest = digest(model.artifact())
    return model, dict(version=VERSION, original_prepared_sha256=prepared.sha256,
        original_fit_cutoff_utc=a['cutoff_utc'], updated_cutoff_utc=cut.cutoff_utc,
        update_ids=sorted(r['fixture_id'] for r in additions), updates=len(additions),
        original_training_games=len(a['training_ids']), total_training_games=len(model.training_ids),
        fixed_noise_variance=model.noise_variance,
        policy='ADD_DISTINCT_ORIGINAL_CUT_GAMES_TO_FROZEN_POSTERIOR_WITH_FIXED_NOISE',
        full_league_refit=False, unseen_latest_league_games_not_fetched=True,
        player_effect_fitted=False, measured_pace_fitted=False, calibration_fit=False)
