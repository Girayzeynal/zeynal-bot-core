def run_faz6_test():
    """
    FAZ-6 TEST modu.
    Sistemin çalıştığını doğrulamak için kullanılan basit simülasyon.
    Gerçek veri yerine sabit bir örnek sonuç üretir.
    """

    score = 111               # Test tahmini skor
    confidence = 0.33         # Test güven oranı (sabit)
    mod = "test"

    return {
        "score": score,
        "confidence": confidence,
        "mod": mod
    }
