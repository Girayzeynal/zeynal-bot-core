"""Bounded exact paths for contract-direction audit, not an OT model fitter."""
import hashlib
import numpy as np
from hybrid_engine.assessment_storage import encode_paths,decode_paths,pack,unpack,DTYPES

def capture(distribution):
    p=dict(regulation=encode_paths(distribution.paths),overtime=None)
    if distribution.overtime is not None:
        ot=np.asarray(distribution.overtime)
        if ot.dtype.str not in DTYPES or ot.shape!=(10000,2) or np.any(ot<0) or np.any(ot>1000):
            raise ValueError('MARKET_OT_PATH_SHAPE')
        p['overtime']=dict(dtype=ot.dtype.str,content=pack(ot.tobytes()))
    return p

def replay(p,expected):
    paths=decode_paths(p['regulation'])
    actual=hashlib.sha256(paths.dtype.str.encode()+str(paths.shape).encode()+paths.tobytes()).hexdigest()
    if actual!=expected:raise ValueError('CONTRACT_REGULATION_SAMPLE_PIN_MISMATCH')
    ot=None;data=p.get('overtime')
    if data is not None:
        if data['dtype'] not in DTYPES:raise ValueError('MARKET_OT_PATH_DTYPE')
        dtype=np.dtype(data['dtype']);size=10000*2*dtype.itemsize
        raw=unpack(data['content'],size)
        if len(raw)!=size:raise ValueError('MARKET_OT_PATH_SHAPE')
        ot=np.frombuffer(raw,dtype=dtype).reshape(10000,2)
        reg=paths.sum(axis=1)
        if np.any(ot<0) or np.any(ot>1000) or np.any(ot[reg[:,0]!=reg[:,1]]!=0) or np.any((reg+ot)[:,0]==(reg+ot)[:,1]):
            raise ValueError('MARKET_OT_PATH_COHERENCE')
    return paths,ot

def contract_mass(samples,market,line,include_overtime):
    paths,ot=samples;teams=paths.sum(axis=1)
    if include_overtime:
        if ot is None:raise ValueError('NO_VERIFIED_OVERTIME_SIMULATION_PATHS')
        teams=teams+ot
    if market=='TOTAL':v=teams.sum(axis=1)
    elif market=='WINNER':v=teams[:,0]-teams[:,1]
    else:raise ValueError('MARKET_CONTRACT_SCOPE_UNSUPPORTED')
    return dict(under=float(np.mean(v<line)),push=float(np.mean(v==line)),over=float(np.mean(v>line)))
