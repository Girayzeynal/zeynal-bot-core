class FAZ6Balance:
    """
    FAZ-6 modları (test, auto, risk, edge, real) arasındaki
    mikro denge ve karşılaştırma katmanı.
    """

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

        # En yüksek güvenirlik
        return max(self.history, key=lambda x: x["confidence"])

    def reset(self):
        self.history = []
