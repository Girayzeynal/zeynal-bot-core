# ================================================================
#                FAZ-6 ANA MOTOR – GELİŞTİRİLMİŞ SÜRÜM
# ================================================================

from .faz6_core import (
    run_faz6_test,
    run_faz6_auto,
    run_faz6_risk,
    run_faz6_edge,
    run_faz6_real,
)

from .faz6_balance import run_faz6_balance


def _safe_run(func, mode, context):
    """
    Tüm FAZ-6 fonksiyonlarını güvenli şekilde çalıştıran koruyucu.
    Motor çökse bile stabil çıktı üretir.
    """

    try:
        raw = func() if context is None else func()

        # Motorların çoğu raw dict döner — hepsini standart formata sokuyoruz.
        return {
            "status": "ok",
            "mode": mode,
            "engine": "FAZ-6",
            "result": raw,
            "context_used": context or {},
        }

    except Exception as e:
        return {
            "status": "error",
            "mode": mode,
            "engine": "FAZ-6",
            "detail": str(e),
            "context_used": context or {},
        }


def run_faz6_engine(mode: str = "auto", context: dict | None = None) -> dict:
    """
    FAZ-6 ana motoru – tüm modları tek çatıdan yönetir.
    Dönen değer main.py ile %100 uyumludur.
    """

    if context is None:
        context = {}

    mode = mode.lower().strip()

    # MODE ROUTER
    if mode == "test":
        return _safe_run(run_faz6_test, mode, context)

    if mode == "auto":
        return _safe_run(run_faz6_auto, mode, context)

    if mode == "risk":
        return _safe_run(run_faz6_risk, mode, context)

    if mode == "edge":
        return _safe_run(run_faz6_edge, mode, context)

    if mode == "real":
        return _safe_run(run_faz6_real, mode, context)

    if mode == "balance":
        # Balance modu özel: context’i aktif aktarır
        try:
            raw = run_faz6_balance(context=context, mode="auto")
            return {
                "status": "ok",
                "mode": "balance",
                "engine": "FAZ-6",
                "result": raw,
                "context_used": context,
            }
        except Exception as e:
            return {
                "status": "error",
                "mode": "balance",
                "engine": "FAZ-6",
                "detail": str(e),
                "context_used": context,
            }

    # GEÇERSİZ MOD
    return {
        "status": "error",
        "engine": "FAZ-6",
        "detail": f"Geçersiz FAZ-6 modu: {mode}",
        "context_used": context,
    }
