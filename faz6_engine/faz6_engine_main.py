# ================================================================
#                      FAZ-6 ANA MOTOR  (TAM SÜRÜM)
# ================================================================

from .faz6_core import (
    run_faz6_test,
    run_faz6_auto,
    run_faz6_risk,
    run_faz6_edge,
    run_faz6_real,
)

from .faz6_balance import run_faz6_balance


def run_faz6_engine(mode: str = "auto", context: dict | None = None) -> dict:
    """
    FAZ-6 ana motoru - tüm modları tek çatıdan yönetir.

    Kullanılabilir Modlar:
        test / auto / risk / edge / real / balance
    """

    if context is None:
        context = {}

    mode = mode.lower().strip()

    if mode == "test":
        return run_faz6_test()

    if mode == "auto":
        return run_faz6_auto()

    if mode == "risk":
        return run_faz6_risk()

    if mode == "edge":
        return run_faz6_edge()

    if mode == "real":
        return run_faz6_real()

    if mode == "balance":
        return run_faz6_balance(context=context, mode="auto")

    return {
        "status": "error",
        "module": "FAZ-6 ENGINE",
        "detail": f"Geçersiz FAZ-6 modu: {mode}",
        "context": context,
}
