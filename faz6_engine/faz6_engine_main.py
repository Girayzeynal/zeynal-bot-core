from faz6_engine.faz6_core import FAZ6Core
from faz6_engine.faz6_balance import run_faz6_balance
from faz6_engine.faz6_test import run_faz6_test
from faz6_engine.faz6_auto import run_faz6_auto
from faz6_engine.faz6_risk import run_faz6_risk
from faz6_engine.faz6_edge import run_faz6_edge
from faz6_engine.faz6_real import run_faz6_real

# =======================================================
# FAZ-6 ENGINE ANA ÇAĞIRICI
# =======================================================

def run_faz6_engine(mode: str = "test") -> str:
    """
    Telegram için FAZ-6 motoru çıktı üreten fonksiyon.
    """

    if mode == "test":
        data = run_faz6_test()
    elif mode == "auto":
        data = run_faz6_auto()
    elif mode == "risk":
        data = run_faz6_risk()
    elif mode == "edge":
        data = run_faz6_edge()
    elif mode == "real":
        data = run_faz6_real()
    elif mode == "balance":
        data = run_faz6_balance()
    else:
        data = run_faz6_test()

    score = data.get("score", 105)
    confidence = data.get("confidence", 0.25)
    mod = data.get("mod", mode)

    text = (
        "🧠 *FAZ-6 Engine Çalıştı!*\n"
        f"🎯 Tahmini Skor: {score}\n"
        f"🔐 Güven: {confidence}\n"
        f"📘 Mod: {mod}"
    )

    return text


# Eski kullanım için kısayol
def run(mode: str = "test") -> str:
    return run_faz6_engine(mode)
