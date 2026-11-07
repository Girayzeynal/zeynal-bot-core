"""Descriptive three-way regulation probability scoring, never a calibration claim."""
import math


def probability_metrics(probabilities,outcomes):
    if len(probabilities)!=len(outcomes):raise ValueError('probability/outcome lengths differ')
    if not probabilities:return dict(sample_size=0,brier=None,log_loss=None,home_ece=None,calibration_status='NOT_ESTABLISHED')
    brier=[];loss=[];bins=[[] for _ in range(10)]
    for p,outcome in zip(probabilities,outcomes):
        if outcome not in ('home','away','tie') or set(p)!= {'home','away','tie'} or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in p.values()) or abs(sum(p.values())-1)>1e-9:
            raise ValueError('invalid three-way regulation probability')
        brier.append(sum((p[k]-float(outcome==k))**2 for k in p))
        loss.append(-math.log(max(1e-15,p[outcome])))
        bins[min(9,int(p['home']*10))].append((p['home'],float(outcome=='home')))
    ece=sum(len(b)/len(probabilities)*abs(sum(p for p,y in b)/len(b)-sum(y for p,y in b)/len(b)) for b in bins if b)
    return dict(sample_size=len(probabilities),brier=sum(brier)/len(brier),log_loss=sum(loss)/len(loss),
        home_ece=ece,definition='three_way_Brier_sum; home-event_10_bin_ECE',
        calibration_status='NOT_ESTABLISHED',statistical_claim='NONE_DESCRIPTIVE_ONLY')
