"""
FAZ-6 Engine Main
Bu dosya FAZ-6’nın merkezidir.
Tüm modlar buradan yönetilir: auto, risk, edge ve real.
"""

from faz6_engine.faz6_core import run_faz6_auto
from faz6_engine.optimizer import run_faz6_risk
from faz6_engine.ml_brain import run_faz6_edge
from faz6_engine.faz6_engine_real import run_faz6_real


def run(mode: str = "auto"):
    """
    Ana FAZ-6 çalıştırıcısı.
    Telegram bot burayı çağırır.
    """

    mode = mode.lower().strip()

    if mode == "auto":
        return run_faz6_auto()

    elif mode == "risk":
        return run_faz6_risk()

    elif mode == "edge":
        return run_faz6_edge()

    elif mode == "real":
        # Varsayılan örnek maç: LAL vs BOS
        return run_faz6_real("LAL", "BOS")

    else:
        return f"❌ Bilinmeyen FAZ-6 modu: {mode}"
