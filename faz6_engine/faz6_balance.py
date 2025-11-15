# faz6_balance.py
"""
FAZ-6 Balance Modülü
Tüm modlardan gelen skor + güven değerlerini toplayıp
en dengeli ve en güvenilir tahmini seçen katman.
"""

class FAZ6Balance:
    def __init__(self):
        self.history = []

    def update(self, mode: str, score: float, confidence: float):
        entry = {
            "mode": mode,
            "score": score,
            "confidence": confidence
        }
        self.history.append(entry)

    def get_best(self) -> dict:
        if not self.history:
            return {"mode": "none", "score": 0, "confidence": 0}

        # En yüksek güvene göre seçim yap
        return max(self.history, key=lambda x: x["confidence"])

    def reset(self):
        self.history = []


# =====================================================
#   DIŞARI AÇILAN ANA FONKSİYON (Bot bunu çağırıyor)
# =====================================================

def run_faz6_balance(data: dict = None) -> dict:
    """
    FAZ-6 Engine ana modülü buraya bir dictionary gönderir:
      {"mode": "risk", "score": 110, "confidence": 0.45}

    Bu modül ise en iyi dengeyi döndürür.
    """

    balancer = FAZ6Balance()

    if data:
        balancer.update(
            mode=data.get("mode", "none"),
            score=data.get("score", 0),
            confidence=data.get("confidence", 0)
        )

    best = balancer.get_best()

    return {
        "score_est": best["score"],
        "confidence": best["confidence"],
        "mode": best["mode"]
    } 
