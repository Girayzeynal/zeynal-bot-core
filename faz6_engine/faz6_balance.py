# FAZ-6 BALANCE MODÜLÜ
# Tüm modların sonuçlarını toplayıp en dengeli seçeneği döndürür.

class FAZ6Balance:
    """
    FAZ-6 modları (test, auto, risk, edge, real) arasındaki
    mikro denge ve karşılaştırma katmanı.
    """

    def __init__(self):
        self.history = []

    def update(self, mode: str, score: float, confidence: float):
        """
        Bir moddan gelen çıktıyı hafızaya ekler.
        """
        entry = {
            "mode": mode,
            "score": score,
            "confidence": confidence
        }
        self.history.append(entry)

    def get_best(self) -> dict:
        """
        Tüm modlar arasından en yüksek güvenilirliğe sahip olanı döndürür.
        """
        if not self.history:
            return {"mode": "none", "score": 0, "confidence": 0}

        return max(self.history, key=lambda x: x["confidence"])

    def reset(self):
        """
        Yeni çalışma için hafızayı sıfırlar.
        """
        self.history = []


# BAĞIMSIZ ÇALIŞAN FONKSİYON
def run_faz6_balance(context: dict = None) -> dict:
    """
    FAZ-6 Balance çalıştırılır.
    """
    if context is None:
        context = {}

    balance = FAZ6Balance()

    # Örnek veri – ileride gerçek mod verileri buraya gelecek
    balance.update("test", 100, 0.40)
    balance.update("auto", 104, 0.44)
    balance.update("risk", 112, 0.38)
    balance.update("edge", 108, 0.46)
    balance.update("real", 107, 0.45)

    best = balance.get_best()

    return {
        "status": "ok",
        "module": "FAZ-6 BALANCE",
        "best_mode": best["mode"],
        "best_score": best["score"],
        "confidence": best["confidence"],
        "context": context,
    }
