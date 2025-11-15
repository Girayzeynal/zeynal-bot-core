from .faz6_core import (
    run_faz6_test,
    run_faz6_auto,
    run_faz6_risk,
    run_faz6_edge,
    run_faz6_real,
)


def run_faz6_engine(mode: str = "test") -> str:
    """
    Telegram için FAZ-6 metin çıktısını üreten ana fonksiyon.
    main.py burayı çağırıyor.
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
    else:
        # bilinmeyen mod gelirse güvenli fallback
        data = run_faz6_test()

    score = data.get("score", 105)
    confidence = data.get("confidence", 0.25)
    mod = data.get("mod", mode)

    text = (
        "🧠 FAZ-6 Engine Çalıştı!\n"
        f"🎯 Tahmini Skor: {score}\n"
        f"🔐 Güven: {confidence}\n"
        f"Mod: {mod}"
    )
    return text


# Eski alışkanlıklar için kısayol (main.py 'run' ismini kullanıyorsa)
def run(mode: str = "test") -> str:
    return run_faz6_engine(mode) 
