"""Explicit latent variance contract; diagnostics are not predictive calibration."""
import math
from dataclasses import asdict
from prematch_monte_carlo import PrematchSimulationInput,PrematchMonteCarloEngine


def variance_contract(home_std,away_std,correlation,shared_pace_std=0):
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (home_std,away_std,correlation,shared_pace_std)):
        raise ValueError('finite numeric covariance inputs required')
    if home_std<=0 or away_std<=0 or not -.95<=correlation<=.95 or not 0<=shared_pace_std<min(home_std,away_std):
        raise ValueError('invalid covariance inputs')
    hr=math.sqrt(home_std**2-shared_pace_std**2);ar=math.sqrt(away_std**2-shared_pace_std**2)
    covariance=correlation*home_std*away_std
    residual=(covariance-shared_pace_std**2)/(hr*ar)
    if not -1<=residual<=1:raise ValueError('impossible shared/residual covariance')
    return dict(home_std=home_std,away_std=away_std,correlation=correlation,shared_pace_std=shared_pace_std,
        covariance=covariance,residual_correlation=residual,
        latent_total_std=math.sqrt(home_std**2+away_std**2+2*covariance),
        latent_margin_std=math.sqrt(home_std**2+away_std**2-2*covariance),
        interpretation='LATENT_NORMAL_BEFORE_ROUNDING_CLIPPING',calibration_status='NOT_ESTABLISHED')


def sensitivity(requests):
    results=[]
    for request in requests:
        if not isinstance(request,PrematchSimulationInput) or type(request.simulations) is not int or request.simulations<10000:
            raise ValueError('explicit Monte Carlo request with at least 10000 draws required')
        contract=variance_contract(request.home_std,request.away_std,request.score_correlation,request.shared_pace_std)
        result=PrematchMonteCarloEngine().simulate(request)
        results.append(dict(config=asdict(request),assumptions=contract,observed_home_std=result.observed_home_std,
            observed_away_std=result.observed_away_std,observed_correlation=result.observed_score_correlation,
            observed_total_std=result.total_std,seed=result.seed,usage='OFFLINE_SENSITIVITY_NOT_PROSPECTIVE_ACCURACY'))
    return results
