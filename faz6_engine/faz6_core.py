from .memory_unit import MemoryUnit
from .ml_brain import MLBrain
from .optimizer import Optimizer


class FAZ6Core:
    """
    FAZ-6 temel çekirdeği.
    Hafıza + ML tahmini + Optimize edilmiş ayarlama.
    """
    def __init__(self):
        self.memory = MemoryUnit()
        self.brain = MLBrain()
        self.optimizer = Optimizer()

    def analyze(self, stats: dict) -> dict:
        """
        Temel tahmin fonksiyonu (FAZ-6 için ortak çekirdek).
        """
        base = self.brain.simple_predict(stats)
        return base

    def learn(self, result: dict):
        """
        Hafıza ve optimizasyon döngüsü.
        """
        self.memory.save(result)
        return self.optimizer.adjust(self.memory.get_all())


# ============================================================
#          FAZ-6 ÇALIŞTIRMA MODLARI (EKLİYORUZ)
# ============================================================

def run_faz6_test() -> dict:
    """
    FAZ-6 TEST modu – düşük risk, sade tahmin
    """
    core = FAZ6Core()
    stats = {"pts": 105, "pace": 97, "power": 0.25}
    result = core.analyze(stats)
    return {
        "score": result.get("score", 105),
        "confidence": result.get("conf", 0.25),
        "mod": "test"
    }


def run_faz6_auto() -> dict:
    """
    FAZ-6 AUTO – otomatik öğrenme modu
    """
    core = FAZ6Core()
    stats = {"pts": 108, "pace": 99, "power": 0.45}

    base = core.analyze(stats)
    adj = core.learn(base)

    return {
        "score": base.get("score", 108),
        "confidence": adj.get("conf", 0.40),
        "mod": "auto"
    }


def run_faz6_risk() -> dict:
    """
    Yüksek risk modu – agresif tahmin
    """
    core = FAZ6Core()
    stats = {"pts": 112, "pace": 103, "power": 0.65}

    base = core.analyze(stats)
    return {
        "score": base.get("score", 112),
        "confidence": 0.55,
        "mod": "risk"
    }


def run_faz6_edge() -> dict:
    """
    Edge modu – ML + güç dengesi analizi
    """
    core = FAZ6Core()
    stats = {"pts": 110, "pace": 101, "power": 0.52}

    base = core.analyze(stats)
    return {
        "score": base.get("score", 110),
        "confidence": 0.50,
        "mod": "edge"
    }


def run_faz6_real() -> dict:
    """
    Gerçek maç tahmin modu.
    DataPipe → FAZ6Core → Optimize edilmiş tahmin
    """
    core = FAZ6Core()
    stats = {"pts": 107, "pace": 100, "power": 0.40}

    base = core.analyze(stats)
    adj = core.learn(base)

    return {
        "score": base.get("score", 107),
        "confidence": adj.get("conf", 0.45),
        "mod": "real"
    }
