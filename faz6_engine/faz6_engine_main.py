from .memory_unit import MemoryUnit
from .ml_brain import MLBrain
from .optimizer import Optimizer


class FAZ6Core:
    """
    FAZ-6 temel çekirdeği.
    Hafıza + ML tahmini + optimize edilmiş ayarlama.
    """
    def __init__(self):
        self.memory = MemoryUnit()
        self.brain = MLBrain()
        self.optimizer = Optimizer()

    def analyze(self, stats: dict) -> dict:
        """
        Temel tahmin fonksiyonu (FAZ-6 ortak çekirdeği).
        """
        base = self.brain.simple_predict(stats)
        return base

    def learn(self, result: dict) -> dict:
        """
        Hafıza + optimizasyon döngüsü.
        """
        self.memory.save(result)
        return self.optimizer.adjust(self.memory.get_all())


# =====================================================
#       FAZ-6 MODLARI – Standart JSON Protokolü
# =====================================================

def _std_ok(module: str, score: int, conf: float, mod: str, extra=None):
    """
    Tüm FAZ-6 modları için ortak JSON dönüş protokolü.
    """
    return {
        "status": "ok",
        "module": module,
        "score": score,
        "confidence": conf,
        "mod": mod,
        "context": extra or {}
    }


# =====================================================
#                  MOD: TEST
# =====================================================

def run_faz6_test() -> dict:
    """
    FAZ-6 TEST modu – düşük risk, sade tahmin
    """
    core = FAZ6Core()
    stats = {"pts": 105, "pace": 97, "power": 0.25}

    result = core.analyze(stats)

    score = result.get("score", 105)
    conf = result.get("conf", 0.25)

    return _std_ok("FAZ-6 TEST", score, conf, "test")


# =====================================================
#                  MOD: AUTO
# =====================================================

def run_faz6_auto() -> dict:
    """
    FAZ-6 AUTO – otomatik öğrenme modu
    """
    core = FAZ6Core()
    stats = {"pts": 108, "pace": 99, "power": 0.45}

    base = core.analyze(stats)
    adj = core.learn(base)

    score = base.get("score", 108)
    conf = adj.get("conf", 0.40)

    return _std_ok("FAZ-6 AUTO", score, conf, "auto")


# =====================================================
#                  MOD: RISK
# =====================================================

def run_faz6_risk() -> dict:
    """
    Yüksek risk modu – agresif tahmin
    """
    core = FAZ6Core()
    stats = {"pts": 112, "pace": 103, "power": 0.65}

    base = core.analyze(stats)

    score = base.get("score", 112)
    conf = 0.55

    return _std_ok("FAZ-6 RISK", score, conf, "risk")


# =====================================================
#                  MOD: EDGE
# =====================================================

def run_faz6_edge() -> dict:
    """
    Edge modu – ML + güç dengesi analizi
    """
    core = FAZ6Core()
    stats = {"pts": 110, "pace": 101, "power": 0.52}

    base = core.analyze(stats)

    score = base.get("score", 110)
    conf = 0.50

    return _std_ok("FAZ-6 EDGE", score, conf, "edge")


# =====================================================
#                  MOD: REAL
# =====================================================

def run_faz6_real() -> dict:
    """
    Gerçek maç tahmin modu (REAL)
    """
    core = FAZ6Core()
    stats = {"pts": 107, "pace": 100, "power": 0.40}

    base = core.analyze(stats)
    adj = core.learn(base)

    score = base.get("score", 107)
    conf = adj.get("conf", 0.45)

    return _std_ok("FAZ-6 REAL", score, conf, "real") 
