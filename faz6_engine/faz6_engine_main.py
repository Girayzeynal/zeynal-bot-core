# =============================
# FAZ-6 ANA MOTOR (DÜZELTİLDİ)
# =============================

from faz6_engine.faz6_core import (
    run_faz6_test,
    run_faz6_auto,
    run_faz6_risk,
    run_faz6_edge,
    run_faz6_real,
)
from faz6_engine.faz6_balance import run_faz6_balance


def run_faz6_engine(mode="test", context=None):
    """
    FAZ-6 ana seçim motoru.
    Tüm modları tek çatıdan yönetir:
    
    test / auto / risk / edge / real / balance
    """

    if context is None:
        context = {}

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
        return run_faz6_balance(mode="auto")

    return {
        "status": "error",
        "detail": f"Bilinmeyen FAZ-6 modu: {mode}",
    } 
