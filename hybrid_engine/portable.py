"""Bounded numeric tree inference. Optional ML libraries are used only for offline export.

No pickle, online fitting, categorical trees, missing features or arbitrary callbacks.
Exports must be checked against native predictions before use in any future release.
"""
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from core.team_identity import digest
from hybrid_engine.data import Abstain, local_path, ml_vector
from hybrid_engine.models import BoostedScores


def export_portable(model):
    if not model.fitted: raise Abstain('NO_FITTED_OFFLINE_ML_MODEL')
    native = []
    if model.backend == 'LIGHTGBM':
        native = [m.booster_.dump_model() for m in model.estimators]
    else:
        with TemporaryDirectory(prefix='hybrid-export-') as directory:
            for i, m in enumerate(model.estimators):
                path = Path(directory)/('side-'+str(i)+'.json'); m.save_model(str(path), format='json')
                native.append(json.loads(path.read_text()))
    payload = dict(format='HYBRID_PORTABLE_NUMERIC_TREES_V1', backend=model.backend,
        identity=list(model.identity), evidence_class=model.evidence_class,
        fit_cutoff_utc=model.cutoff, training_ids=model.training_ids, native_models=native,
        training_artifact=model.artifact_digest,
        residual_std=None if model.residual_std is None else model.residual_std.tolist(),
        residual_correlation=model.residual_correlation,
        scale_cutoff_utc=getattr(model, 'scale_cutoff', None),
        scale_validation_ids=getattr(model, 'scale_validation_ids', []))
    return dict(payload=payload, sha256=digest(payload))


def _light_tree(node, depth=0):
    if depth > 8: raise ValueError('PORTABLE_TREE_DEPTH_BUDGET')
    if 'leaf_value' in node:
        value = float(node['leaf_value'])
        if not math.isfinite(value): raise ValueError('NONFINITE_TREE_LEAF')
        return value
    feature = node['split_feature']; threshold = float(node['threshold'])
    if type(feature) is not int or not 0 <= feature < 30 or not math.isfinite(threshold) or node['decision_type'] != '<=':
        raise ValueError('ONLY_FINITE_NUMERIC_PORTABLE_SPLITS_SUPPORTED')
    return (feature, threshold, _light_tree(node['left_child'], depth+1), _light_tree(node['right_child'], depth+1))


class PortableBoostedScores(BoostedScores):
    @classmethod
    def from_artifact(cls, artifact, *, trusted_sha256):
        p = artifact['payload']
        if digest(p) != trusted_sha256 or artifact['sha256'] != trusted_sha256:
            raise ValueError('PORTABLE_MODEL_TRUSTED_DIGEST_MISMATCH')
        if p['format'] != 'HYBRID_PORTABLE_NUMERIC_TREES_V1': raise ValueError('PORTABLE_MODEL_FORMAT')
        self = cls(p['backend']); self.identity = tuple(p['identity']); self.evidence_class = p['evidence_class']
        self.cutoff = p['fit_cutoff_utc']; self.training_ids = p['training_ids']
        self.artifact_digest = p['training_artifact']; self.portable_digest = trusted_sha256
        self.residual_std = None if p['residual_std'] is None else np.array(p['residual_std'], dtype=float)
        self.residual_correlation = p['residual_correlation']
        self.scale_cutoff = p['scale_cutoff_utc']; self.scale_validation_ids = p['scale_validation_ids']
        if self.residual_std is not None and (self.residual_std.shape != (2,) or not np.isfinite(self.residual_std).all() or np.any(self.residual_std <= 0)):
            raise ValueError('INVALID_PORTABLE_RESIDUAL_SCALE')
        if len(p['native_models']) != 2: raise ValueError('TWO_TEAM_MODELS_REQUIRED')
        self.trees = []
        for native in p['native_models']:
            if self.backend == 'LIGHTGBM':
                if native['objective'] != 'regression': raise ValueError('PORTABLE_REGRESSION_ONLY')
                if not 1 <= len(native['tree_info']) <= 200: raise ValueError('PORTABLE_TREE_COUNT_BUDGET')
                self.trees.append([_light_tree(t['tree_structure']) for t in native['tree_info']])
            else:
                if not 1 <= len(native['oblivious_trees']) <= 200: raise ValueError('PORTABLE_TREE_COUNT_BUDGET')
                trees = []
                for tree in native['oblivious_trees']:
                    splits = []
                    for split in tree.get('splits') or []:
                        index = split['float_feature_index']; border = float(split['border'])
                        if split['split_type'] != 'FloatFeature' or type(index) is not int or not 0 <= index < 30 or not math.isfinite(border):
                            raise ValueError('PORTABLE_CATBOOST_NUMERIC_ONLY')
                        splits.append((index, border))
                    leaves = np.array(tree['leaf_values'], dtype=float)
                    if len(splits) > 8 or len(leaves) != 2**len(splits) or not np.isfinite(leaves).all():
                        raise ValueError('INVALID_PORTABLE_OBLIVIOUS_TREE')
                    trees.append((splits, leaves))
                scale, bias = native['scale_and_bias']
                if len(bias) != 1 or not all(math.isfinite(float(v)) for v in (scale, bias[0])):
                    raise ValueError('INVALID_PORTABLE_SCALE_BIAS')
                self.trees.append((trees, float(scale), float(bias[0])))
        self.fitted = True
        return self

    @classmethod
    def load(cls, path, *, trusted_sha256):
        path = local_path(path)
        if path.stat().st_size > 4*1024*1024: raise ValueError('PORTABLE_ARTIFACT_FILE_BUDGET')
        return cls.from_artifact(json.loads(path.read_text()), trusted_sha256=trusted_sha256)

    def _scores(self, cut):
        if (cut.target['league'], cut.target['season']) != self.identity or cut.evaluation_class != self.evidence_class or cut.cutoff_utc < self.cutoff:
            raise ValueError('ML_PREDICTION_SCOPE_OR_CUTOFF_CONFLICT')
        x = np.asarray(ml_vector(cut), dtype=float)
        if x.shape != (30,) or not np.isfinite(x).all(): raise Abstain('FINITE_COMPLETE_ML_FEATURES_REQUIRED')
        scores = []
        for model in self.trees:
            if self.backend == 'LIGHTGBM':
                score = 0.
                for tree in model:
                    while isinstance(tree, tuple):
                        feature, border, left, right = tree; tree = left if x[feature] <= border else right
                    score += tree
            else:
                trees, scale, bias = model; score = 0.; values = x.astype(np.float32)
                for splits, leaves in trees:
                    index = sum((int(values[feature] > border) << bit) for bit, (feature, border) in enumerate(splits))
                    score += leaves[index]
                score = scale*score+bias
            scores.append(score)
        out = np.array(scores)
        if not np.isfinite(out).all() or np.any(out <= 0) or np.any(out > 300): raise Abstain('ML_SCORE_OUT_OF_RANGE')
        return out

    def fit(self, *args, **kwargs): raise ValueError('PORTABLE_INFERENCE_NEVER_TRAINS')
