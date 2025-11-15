from .faz6_core import (
    run_faz6_test,
    run_faz6_auto,
    run_faz6_risk,
    run_faz6_edge,
    run_faz6_real,
)

from faz5_engine.heavy_engine_main import run_heavy_engine
from faz6_engine.faz6_balance import FAZ6Balance


def run_faz6_engine(mode: str = "test") -> dict:
    """
    Telegram için FAZ-6 metin çıktısını üreten ana fonksiyon.
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
        balancer = FAZ6Balance()
        data = balancer.run()
    else:
        data = run_faz6_test()

    score = data.get("score", 105)
    confidence = data.get("confidence", 0.25)
    mod = data.get("mod", mode)

    text = (
        f"🧠 FAZ-6 Engine Çalıştı!\n"
        f"🎯 Tahmini Skor: {score}\n"
        f"🔐 Güven: {confidence}\n"
        f"▶️ Mod: {mod}"
    )

    return text


def run(mode: str = "test") -> str:
    return run_faz6_engine(mode) 
