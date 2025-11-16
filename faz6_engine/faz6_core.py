# ================================================================
#                      FAZ-6 ÇEKİRDEK (CORE)
# ================================================================

from .memory_unit import load_memory, save_memory
from .optimizer import optimize_prediction
from .ml_brain import ml_evaluate

from .faz6_test import faz6_test_run
from .faz6_auto import faz6_auto_run
from .faz6_risk import faz6_risk_run
from .faz6_edge import faz6_edge_run
from .faz6_real import faz6_real_run


# ================================================================
#  Ortak çıkış formatlayıcı
# ================================================================

def _format_output(mode, status, data, memory=None, detail=None):
    return {
        "mode": mode,
        "status": status,
        "engine": "FAZ-6",
        "detail": detail,
        "result": data,
        "memory_used": memory or {}
    }


# ================================================================
#  TEST MODU
# ================================================================

def run_faz6_test():
    try:
        mem = load_memory()
        raw = faz6_test_run()

        # ML & optimize
        ml = ml_evaluate(raw)
        opt = optimize_prediction(raw)

        save_memory({"test_last": raw})

        return _format_output(
            mode="test",
            status="ok",
            data={"raw": raw, "ml": ml, "optimized": opt},
            memory=mem
        )
    except Exception as e:
        return _format_output("test", "error", None, detail=str(e))


# ================================================================
#  AUTO MODU
# ================================================================

def run_faz6_auto():
    try:
        mem = load_memory()
        raw = faz6_auto_run(memory=mem)

        ml = ml_evaluate(raw)
        opt = optimize_prediction(raw)

        save_memory({"auto_last": opt})

        return _format_output(
            mode="auto",
            status="ok",
            data={"raw": raw, "ml": ml, "optimized": opt},
            memory=mem
        )
    except Exception as e:
        return _format_output("auto", "error", None, detail=str(e))


# ================================================================
#  RISK MODU
# ================================================================

def run_faz6_risk():
    try:
        mem = load_memory()
        raw = faz6_risk_run(memory=mem)

        ml = ml_evaluate(raw)
        opt = optimize_prediction(raw, risk=True)

        save_memory({"risk_last": opt})

        return _format_output(
            mode="risk",
            status="ok",
            data={"raw": raw, "ml": ml, "optimized": opt},
            memory=mem
        )
    except Exception as e:
        return _format_output("risk", "error", None, detail=str(e))


# ================================================================
#  EDGE MODU
# ================================================================

def run_faz6_edge():
    try:
        mem = load_memory()
        raw = faz6_edge_run(memory=mem)

        ml = ml_evaluate(raw)
        opt = optimize_prediction(raw, aggressive=True)

        save_memory({"edge_last": opt})

        return _format_output(
            mode="edge",
            status="ok",
            data={"raw": raw, "ml": ml, "optimized": opt},
            memory=mem
        )
    except Exception as e:
        return _format_output("edge", "error", None, detail=str(e))


# ================================================================
#  REAL MODU (GERÇEK ZAMANLI)
# ================================================================

def run_faz6_real():
    try:
        mem = load_memory()
        raw = faz6_real_run(memory=mem)

        ml = ml_evaluate(raw)
        opt = optimize_prediction(raw, realtime=True)

        save_memory({"real_last": opt})

        return _format_output(
            mode="real",
            status="ok",
            data={"raw": raw, "ml": ml, "optimized": opt},
            memory=mem
        )
    except Exception as e:
        return _format_output("real", "error", None, detail=str(e))
