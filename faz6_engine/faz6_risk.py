# FAZ-6 RISK MODÜLÜ
# Daha agresif, yüksek varyanslı tahminler üretir.

def run_faz6_risk(context: dict = None) -> dict:
    """
    FAZ-6 Risk modülü.
    Yüksek varyanslı skor tahmini üretir.
    """
    if context is None:
        context = {}

    # Örnek agresif tahmin sistemi
    import random

    base_score = random.randint(95, 115)
    volatility = random.uniform(0.10, 0.25)  # Risk daha yüksek

    score = round(base_score * (1 + volatility), 1)
    confidence = max(0.25, min(0.60, 0.55 - volatility))

    return {
        "status": "ok",
        "module": "FAZ-6 RISK",
        "score": score,
        "confidence": round(confidence, 2),
        "context": context,
    }
