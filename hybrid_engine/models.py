"""Offline partial pooling and optional boosted regressors; no Telegram-time training."""
from copy import deepcopy
import math
import time

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain, available_at, ml_vector, regulation
from hybrid_engine.distributions import Budget, Forecast, gaussian_forecast, quarter_weights


def _exposure(entry, fixture_start, duration):
    if (not entry or type(entry['observed_at_utc']) is not int or type(entry['ingested_at_utc']) is not int or
            not 0 < entry['observed_at_utc'] <= entry['ingested_at_utc'] < fixture_start):
        raise ValueError('PREMATCH_PLAYER_EXPOSURE_CLOCK_REQUIRED')
    out = {}
    for side in ('home', 'away'):
        players = entry[side]
        if (not players or len({p['player_id'] for p in players}) != len(players) or
                any(type(p['player_id']) is not str or not p['player_id'].strip() for p in players)):
            raise ValueError('UNIQUE_PLAYER_EXPOSURES_REQUIRED')
        values = {p['player_id']: float(p['expected_minutes'])/duration for p in players}
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in values.values()) or abs(sum(values.values())-5) > 1e-6:
            raise ValueError('FULL_TEAM_PROJECTED_MINUTES_REQUIRED')
        out[side] = values
    return out


class HierarchicalStrength:
    """Empirical-Bayes normal league/team attack/defense hierarchy with conjugate covariance.

    Noise variance is empirical training variance; normal prior scales are explicit research
    hyperparameters, not tuned on test matches. Player coefficients require *pregame projected*
    exposures for every training game; final box-score minutes do not satisfy that contract.
    """
    def __init__(self, *, minimum_games=30, team_prior_sd=4., player_prior_sd=2.):
        if type(minimum_games) is not int or minimum_games < 2 or not 0 < team_prior_sd <= 30 or not 0 < player_prior_sd <= 30:
            raise ValueError('VALID_HIERARCHICAL_PRIORS_REQUIRED')
        self.minimum_games = minimum_games; self.team_prior_sd = team_prior_sd
        self.player_prior_sd = player_prior_sd; self.fitted = False

    def fit(self, rows, *, cutoff_utc, mode, projected_exposures=None):
        if type(cutoff_utc) is not int or not 0 < cutoff_utc <= int(time.time()):
            raise ValueError('REAL_HISTORICAL_TRAINING_CUTOFF_REQUIRED')
        if len(rows) < self.minimum_games: raise Abstain('INSUFFICIENT_HIERARCHICAL_TRAINING_GAMES')
        identities = {(r['league'], r['season']) for r in rows}
        if len(identities) != 1 or len({r['fixture_id'] for r in rows}) != len(rows):
            raise ValueError('UNIQUE_SINGLE_SEASON_TRAINING_REQUIRED')
        if any(regulation(r) is None or r['fixture_start_utc'] >= cutoff_utc or
               not r['fixture_start_utc'] < available_at(r, mode) <= cutoff_utc for r in rows):
            raise ValueError('TRAINING_LABEL_NOT_AVAILABLE_BEFORE_CUTOFF')
        self.identity = next(iter(identities)); self.mode = mode; self.cutoff = cutoff_utc
        self.teams = sorted({r[s+'_team_id'] for r in rows for s in ('home', 'away')})
        self.team_index = {t: i for i, t in enumerate(self.teams)}
        self.duration = 48 if self.identity[0] == 'NBA' else 40
        self.exposures = {}
        if projected_exposures is not None:
            if not all(r['fixture_id'] in projected_exposures for r in rows):
                raise Abstain('INCOMPLETE_PREMATCH_PLAYER_EXPOSURE_ARCHIVE')
            self.exposures = {r['fixture_id']: _exposure(projected_exposures[r['fixture_id']], r['fixture_start_utc'], self.duration) for r in rows}
        self.players = sorted({p for e in self.exposures.values() for side in e.values() for p in side})
        self.player_index = {p: i for i, p in enumerate(self.players)}
        size = 2+2*len(self.teams)+len(self.players)
        if size > 512: raise Abstain('HIERARCHICAL_PARAMETER_MEMORY_BUDGET')
        X, y = [], []
        for r in rows:
            for side, own, opponent, label in [('home', r['home_team_id'], r['away_team_id'], regulation(r)[0]),
                                               ('away', r['away_team_id'], r['home_team_id'], regulation(r)[1])]:
                v, _ = self._vector(own, opponent, side == 'home', self.exposures.get(r['fixture_id'], {}).get(side))
                X.append(v); y.append(label)
        X = np.array(X); y = np.array(y)
        self.noise_variance = max(1., float(np.var(y, ddof=1)))
        prior_sd = np.r_[30., 3., np.full(2*len(self.teams), self.team_prior_sd), np.full(len(self.players), self.player_prior_sd)]
        prior_precision = 1/(prior_sd*prior_sd)
        prior_mean = np.zeros(size); prior_mean[0] = y.mean()
        precision = X.T@X/self.noise_variance+np.diag(prior_precision)
        self.covariance = np.linalg.inv(precision)
        self.coefficients = np.linalg.solve(precision, X.T@y/self.noise_variance+prior_precision*prior_mean)
        self.training_ids = sorted(r['fixture_id'] for r in rows)
        self.training_available_max = max(available_at(r, mode) for r in rows)
        self.training_digest = digest([dict(id=r['fixture_id'], scores=regulation(r),
            source=r['source_catalog_sha256'], available=available_at(r, mode)) for r in rows])
        self.artifact_digest = digest(self.artifact())
        self.fitted = True
        return self

    def _vector(self, own, opponent, home, players=None):
        v = np.zeros(2+2*len(self.teams)+len(self.players)); v[0] = 1; v[1] = float(home)
        extra_variance = 0.
        for tid, offset in ((own, 2), (opponent, 2+len(self.teams))):
            if tid in self.team_index: v[offset+self.team_index[tid]] = 1
            else: extra_variance += self.team_prior_sd**2
        if players:
            for pid, weight in players.items():
                if pid in self.player_index: v[2+2*len(self.teams)+self.player_index[pid]] = weight
                else: extra_variance += self.player_prior_sd**2*weight*weight
        return v, extra_variance

    def predict(self, cut, *, budget=Budget(), method='MC', projected_exposure=None):
        if not self.fitted: raise Abstain('NO_HIERARCHICAL_MODEL')
        if (cut.target['league'], cut.target['season']) != self.identity or cut.cutoff_utc < self.cutoff or cut.evaluation_class != self.mode:
            raise ValueError('MODEL_SEASON_OR_CUTOFF_CONFLICT')
        exposures = None
        if self.players:
            if projected_exposure is None: raise Abstain('PREMATCH_PLAYER_MINUTES_UNAVAILABLE')
            exposures = _exposure(projected_exposure, cut.cutoff_utc+1, self.duration)
        vectors, extra = [], []
        for side, other in [('home', 'away'), ('away', 'home')]:
            v, e = self._vector(cut.target[side+'_team_id'], cut.target[other+'_team_id'], side == 'home', None if exposures is None else exposures[side])
            vectors.append(v); extra.append(e)
        x = np.array(vectors); means = x@self.coefficients
        covariance = x@self.covariance@x.T+np.diag(self.noise_variance+np.array(extra))
        std = np.sqrt(np.diag(covariance)); rho = float(covariance[0, 1]/np.prod(std))
        if np.any(means <= 0) or np.any(means > 300): raise Abstain('HIERARCHICAL_SCORE_OUT_OF_RANGE')
        f = gaussian_forecast(means, std, quarter_weights(cut), budget=budget, method=method,
                              correlation=rho, model='BAYES_TEAM_ATTACK_DEFENSE_V1')
        f.metadata.update(artifact_digest=self.artifact_digest, training_games=len(self.training_ids),
            fit_cutoff_utc=self.cutoff, noise_variance=self.noise_variance,
            coefficient_posterior_covariance='CONJUGATE_GAUSSIAN_EMPIRICAL_BAYES',
            player_effect='PREMATCH_EXPOSURE_FITTED' if self.players else 'NO_VERIFIED_PREMATCH_PLAYER_EXPOSURES')
        return f

    def artifact(self):
        return dict(format='BAYES_HIERARCHY_ARTIFACT_V1', identity=self.identity, teams=self.teams, players=self.players,
            coefficients=self.coefficients.tolist(), covariance=self.covariance.tolist(),
            noise_variance=self.noise_variance, cutoff_utc=self.cutoff, mode=self.mode,
            training_ids=self.training_ids, training_available_max=self.training_available_max, training_digest=self.training_digest,
            prior_scales=dict(team=self.team_prior_sd, player=self.player_prior_sd))


class BoostedScores:
    """Optional offline ML. Score predictions work without invented probability dispersion."""
    def __init__(self, backend, *, minimum_train=100, iterations=60, seed=20261112):
        if backend not in ('LIGHTGBM', 'CATBOOST'): raise ValueError('UNKNOWN_ML_BACKEND')
        if (type(minimum_train) is not int or minimum_train < 10 or type(iterations) is not int or
                not 1 <= iterations <= 200 or type(seed) is not int or seed < 0):
            raise ValueError('BOUNDED_ML_TRAINING_REQUIRED')
        self.backend = backend; self.minimum_train = minimum_train; self.iterations = iterations
        self.seed = seed; self.fitted = False; self.residual_std = None; self.residual_correlation = 0.

    def fit(self, examples, *, cutoff_utc):
        if type(cutoff_utc) is not int or not 0 < cutoff_utc <= int(time.time()):
            raise ValueError('REAL_HISTORICAL_TRAINING_CUTOFF_REQUIRED')
        if len(examples) < self.minimum_train: raise Abstain('INSUFFICIENT_ML_TRAINING_EXAMPLES')
        if len({(e['cut'].target['league'], e['cut'].target['season'], e['cut'].evaluation_class) for e in examples}) != 1:
            raise ValueError('SINGLE_EVIDENCE_CLASS_AND_SEASON_REQUIRED')
        if len({e['cut'].target['fixture_id'] for e in examples}) != len(examples):
            raise ValueError('DUPLICATE_ML_TRAINING_TARGET')
        if any(e.get('role') != 'TRAIN' for e in examples):
            raise ValueError('ONLY_TRAIN_ROLE_CAN_FIT_MODEL')
        if any(type(e['label_available_utc']) is not int or
               not e['cut'].target['fixture_start_utc'] < e['label_available_utc'] <= cutoff_utc for e in examples):
            raise ValueError('ML_TRAINING_LABEL_LEAKAGE')
        try:
            if self.backend == 'LIGHTGBM':
                from lightgbm import LGBMRegressor
                factory = lambda: LGBMRegressor(n_estimators=self.iterations, max_depth=3, num_leaves=7,
                    min_child_samples=10, learning_rate=.05, reg_lambda=10., n_jobs=1, verbosity=-1,
                    random_state=self.seed, deterministic=True, force_col_wise=True)
            else:
                from catboost import CatBoostRegressor
                factory = lambda: CatBoostRegressor(iterations=self.iterations, depth=3, learning_rate=.05,
                    l2_leaf_reg=10., thread_count=1, loss_function='RMSE', random_seed=self.seed,
                    verbose=False, allow_writing_files=False)
        except ImportError as exc:
            raise Abstain('OPTIONAL_ML_BACKEND_NOT_INSTALLED:'+self.backend) from exc
        X = np.array([ml_vector(e['cut']) for e in examples]); y = np.array([e['label'] for e in examples])
        if (X.shape != (len(examples), 30) or y.shape != (len(examples), 2) or
                not np.isfinite(X).all() or not np.isfinite(y).all() or np.any(y < 0) or np.any(y > 300)):
            raise ValueError('FINITE_BOUNDED_TRAINING_FEATURES_AND_LABELS_REQUIRED')
        self.estimators = [factory() for _ in range(2)]
        for side, model in enumerate(self.estimators): model.fit(X, y[:, side])
        self.identity = (examples[0]['cut'].target['league'], examples[0]['cut'].target['season'])
        self.evidence_class = examples[0]['cut'].evaluation_class
        self.training_ids = sorted(e['cut'].target['fixture_id'] for e in examples)
        self.cutoff = cutoff_utc
        self.artifact_digest = digest(dict(backend=self.backend, iterations=self.iterations, seed=self.seed,
            training=[dict(id=e['cut'].target['fixture_id'], features=ml_vector(e['cut']), label=e['label']) for e in examples], cutoff=cutoff_utc))
        self.fitted = True
        return self

    def _scores(self, cut):
        if not self.fitted: raise Abstain('NO_ML_MODEL_AVAILABLE')
        if (cut.target['league'], cut.target['season']) != self.identity or cut.evaluation_class != self.evidence_class or cut.cutoff_utc < self.cutoff:
            raise ValueError('ML_PREDICTION_SCOPE_OR_CUTOFF_CONFLICT')
        x = np.array([ml_vector(cut)])
        out = np.array([(m.booster_.predict(x, num_threads=1) if self.backend == 'LIGHTGBM' else m.predict(x, thread_count=1))[0]
                        for m in self.estimators])
        if not np.isfinite(out).all() or np.any(out <= 0) or np.any(out > 300):
            raise Abstain('ML_SCORE_OUT_OF_RANGE')
        return out

    def fit_residual_scale(self, validation, *, cutoff_utc, minimum=30):
        if not self.fitted: raise Abstain('NO_ML_MODEL_AVAILABLE')
        if type(cutoff_utc) is not int or not self.cutoff <= cutoff_utc <= int(time.time()):
            raise ValueError('PAST_VALIDATION_CUTOFF_REQUIRED')
        if type(minimum) is not int or minimum < 5: raise ValueError('MINIMUM_VALIDATION_POLICY_REQUIRED')
        if len(validation) < minimum: raise Abstain('INSUFFICIENT_OUT_OF_SAMPLE_RESIDUALS')
        if len({e['cut'].target['fixture_id'] for e in validation}) != len(validation):
            raise ValueError('DUPLICATE_VALIDATION_EXAMPLE')
        if any(e.get('role') != 'VALIDATION' for e in validation):
            raise ValueError('ONLY_VALIDATION_ROLE_CAN_FIT_RESIDUAL_SCALE')
        if any(type(e['label_available_utc']) is not int or
               not e['cut'].target['fixture_start_utc'] < e['label_available_utc'] <= cutoff_utc or
               e['cut'].target['fixture_id'] in self.training_ids for e in validation):
            raise ValueError('RESIDUAL_SCALE_REQUIRES_PAST_HELDOUT_LABELS')
        residuals = np.array([self._scores(e['cut'])-e['label'] for e in validation])
        std = np.sqrt(np.mean(residuals**2, axis=0))
        if np.any(std <= 0): raise Abstain('RESIDUAL_DISPERSION_UNIDENTIFIED')
        centered_std = np.std(residuals, axis=0)
        rho = float(np.corrcoef(residuals.T)[0, 1]) if np.min(centered_std) > 0 else 0.
        # Explicit shrinkage towards independence avoids an unjustified singular joint law.
        self.residual_correlation = rho*len(validation)/(len(validation)+10)
        self.residual_std = std
        self.scale_validation_ids = sorted(e['cut'].target['fixture_id'] for e in validation)
        self.scale_cutoff = cutoff_utc
        return self

    def predict(self, cut, *, budget=Budget(), method='MC'):
        scores = self._scores(cut); weights = quarter_weights(cut)
        if self.residual_std is None:
            f = Forecast(self.backend+'_SCORE_V1', weights/weights.sum(axis=0)*scores,
                         metadata=dict(probability_status='NO_OUT_OF_SAMPLE_RESIDUAL_SCALE'))
        else:
            if cut.cutoff_utc < self.scale_cutoff: raise ValueError('RESIDUAL_SCALE_CUTOFF_LEAKAGE')
            f = gaussian_forecast(scores, self.residual_std, weights, budget=budget, method=method,
                correlation=self.residual_correlation, model=self.backend+'_SCORE_V1')
            f.metadata['probability_status'] = 'PAST_VALIDATION_RESIDUAL_SCALE_NOT_CALIBRATED'
        f.metadata.update(artifact_digest=self.artifact_digest, training_examples=len(self.training_ids),
                          fit_cutoff_utc=self.cutoff, inference_training_performed=False,
                          player_effect='NO_VERIFIED_PREMATCH_PLAYER_EXPOSURES')
        return f
