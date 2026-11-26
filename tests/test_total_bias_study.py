from copy import deepcopy

import pytest

from hybrid_engine.total_bias_study import compare


def test_fits_only_on_past_predictions_and_pre_cutoff_label_versions():
    rows, folds = [], []
    for i, error in enumerate([10, -2, 3]):
        key, cutoff = str(i), (i+1)*100
        rows.append(dict(fixture_id=key, role='TEST', trace=dict(fold=i, prediction_utc=cutoff),
                         start_utc=cutoff+1, prediction={'total':200+error}, actual=[100,100]))
        labels = [dict(fixture_id='0', label=[90,110], available_utc=190),
                  dict(fixture_id='1', label=[100,100], available_utc=300)]
        folds.append(dict(fold=i, test_cutoff=cutoff, test_ids=[key], label_version_pins={'train':labels}))
    cohort = dict(model_rows={'BAYES_QMC':rows}, folds=folds)
    result = compare(cohort)
    assert [f['median_error'] for f in result['folds']] == [None,10,10]
    assert result['archive']['within_minus2_plus3'] == 2
    assert result['paired_original']['mae'] == 2.5
    assert result['paired_corrected']['mae'] == 9.5
    revised = deepcopy(cohort)
    revised['model_rows']['BAYES_QMC'][0]['actual'] = [80,80]
    assert compare(revised)['paired_corrected'] == result['paired_corrected']
    folds[2]['test_ids'].append('0')
    with pytest.raises(ValueError, match='more than one'):
        compare(cohort)
