"""Descriptive diagnostics on already authenticated, chronologically paired forecasts."""
from math import isfinite, sqrt
from statistics import mean, pvariance


def summarize(pairs):
    if not pairs:
        return None
    original_total = [sum(base['prediction'])-sum(base['actual']) for _,base in pairs]
    candidate_total = [sum(candidate['prediction'])-sum(candidate['actual']) for candidate,_ in pairs]
    variance = pvariance(candidate_total)
    per_quarter = []
    for q in range(4):
        residuals = [(sum(candidate['predicted_quarters'][q])-sum(base['predicted_quarters'][q]),
                      sum(candidate['predicted_quarters'][q])-sum(candidate['actual_periods'][s][q] for s in ('home','away')),
                      sum(base['predicted_quarters'][q])-sum(base['actual_periods'][s][q] for s in ('home','away')))
                     for candidate,base in pairs if candidate.get('predicted_quarters') and base.get('predicted_quarters')]
        if residuals:
            shift, updated, original = zip(*residuals)
            per_quarter.append(dict(quarter=q+1,n=len(residuals),mean_score_shift=mean(shift),
                                    candidate_mae=mean(map(abs,updated)),original_mae=mean(map(abs,original))))
    pace = [candidate.get('estimated_possessions') for candidate,_ in pairs]
    pace = [x for x in pace if type(x) in (int,float) and isfinite(x)]
    ages = [candidate.get('parameter_age_seconds') for candidate,_ in pairs]
    ages = [x for x in ages if type(x) is int and x>=0]
    worst = sorted(zip(pairs, original_total, candidate_total),
                   key=lambda record:abs(record[2])-abs(record[1]),reverse=True)[:5]
    return dict(n=len(pairs), original_total_bias=mean(original_total), candidate_total_bias=mean(candidate_total),
                original_total_residual_sd=sqrt(pvariance(original_total)),candidate_total_residual_sd=sqrt(variance),
                mean_total_revision=mean(c-b for b,c in zip(original_total,candidate_total)),
                estimated_possessions_n=len(pace),mean_estimated_possessions=mean(pace) if pace else None,
                parameter_age_range_seconds=[min(ages),max(ages)] if ages else None,quarters=per_quarter,
                largest_regressions=[dict(fixture_id=pair[0].get('fixture_id'),original_error=b,candidate_error=c,
                    estimated_possessions=pair[0].get('estimated_possessions'),
                    parameter_age_seconds=pair[0].get('parameter_age_seconds')) for pair,b,c in worst if abs(c)>abs(b)],
                causal_attribution=False)
