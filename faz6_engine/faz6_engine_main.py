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
        Temel tahmin fonksiyonu.
        MLBrain çıktısını normalize eder.
        """
        base = self.brain.simple_predict(stats)

        # Çıktı dict değilse, sar.
        if not isinstance(base, dict):
            base = {
                "score": float(base),
                "conf": 0.5,
            }

        # Eksik alanları güvenli default ile doldur.
        if "score" not in base:
            base["score"] = stats.get("pts", 0)
        if "conf" not in base:
            base["conf"] = stats.get("power", 0.30)

        return base

    def learn(self, result: dict) -> dict:
        """
        Hafıza + optimizasyon döngüsü.
        """
        self.memory.save(result)
        adj = self.optimizer.adjust(self.memory.get_all())

        if not isinstance(adj, dict):
            adj = {}

        if "conf" not in adj:
            adj["conf"] = result.get("conf", 0.40)

        return adj


# =====================================================
#                ORTAK JSON PROTOKOLÜ
# =====================================================

def _std_ok(module: str, score: int, conf: float, mod: str, extra=None) -> dict:
    """
    Tüm FAZ-6 modları için ortak cevap formatı.
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
#                FAZ-6 MODLARI
# =====================================================

def run_faz6_test() -> dict:
    """
    FAZ-6 TEST modu.
    Sistem düzgün ayağa kalkıyor mu diye basit ping.
    """
    core = FAZ6Core()
    stats = {"pts": 105, "pace": 97, "power": 0.25}
    result = core.analyze(stats)

    score = result.get("score", 105)
    conf = result.get("conf", 0.25)

    return _std_ok("FAZ-6 TEST", score, conf, "test")


def run_faz6_auto() -> dict:
    """
    Otomatik öğrenme modu (AUTO).
    """
    core = FAZ6Core()
    stats = {"pts": 108, "pace": 99, "power": 0.45}

    base = core.analyze(stats)
    adj = core.learn(base)

    score = base.get("score", 108)
    conf = adj.get("conf", base.get("conf", 0.40))

    return _std_ok("FAZ-6 AUTO", score, conf, "auto")


def run_faz6_risk() -> dict:
    """
    Yüksek risk modu (RISK).
    """
    core = FAZ6Core()
    stats = {"pts": 112, "pace": 103, "power": 0.65}

    base = core.analyze(stats)

    score = base.get("score", 112)
    # Risk modu, bilinçli yüksek risk – güven biraz daha düşük tutulabilir
    conf = min(0.70, base.get("conf", 0.55))

    return _std_ok("FAZ-6 RISK", score, conf, "risk")


def run_faz6_edge() -> dict:
    """
    Edge modu – ML + güç dengesi analizi (EDGE).
    """
    core = FAZ6Core()
    stats = {"pts": 110, "pace": 101, "power": 0.52}

    base = core.analyze(stats)

    score = base.get("score", 110)
    conf = base.get("conf", 0.50)

    return _std_ok("FAZ-6 EDGE", score, conf, "edge")


def run_faz6_real() -> dict:
    """
    Gerçek maç tahmin modu (REAL).
    """
    core = FAZ6Core()
    stats = {"pts": 107, "pace": 100, "power": 0.40}

    base = core.analyze(stats)
    adj = core.learn(base)

    score = base.get("score", 107)
    conf = adj.get("conf", base.get("conf", 0.45))

    return _std_ok("FAZ-6 REAL", score, conf, "real")


def run_faz6_balance() -> dict:
    """
    Bakiye/denge odaklı mod (BALANCE).
    Daha temkinli, daha düşük güç, orta güven.
    """
    core = FAZ6Core()
    stats = {"pts": 102, "pace": 96, "power": 0.30}

    base = core.analyze(stats)
    adj = core.learn(base)

    score = base.get("score", 102)
    # Balance modu: aşırıya kaçmayan güven.
    conf = min(0.60, adj.get("conf", base.get("conf", 0.50)))

    return _std_ok("FAZ-6 BALANCE", score, conf, "balance")


# =====================================================
#                ANA DISPATCHER
# =====================================================

def run_faz6_engine(mode: str = "auto", context: dict = None) -> str:
    """
    Ana FAZ-6 dispatcher.
    main.py içinden:
        run_faz6_engine(mode="test")
        run_faz6_engine(mode="auto")
        ...
    şeklinde çağrılır.

    Dışarıya TELEGRAM'a uygun, okunabilir string döner.
    İçeride JSON protokolünü kullanır.
    """
    if context is None:
        context = {}

    mode_key = (mode or "auto").strip().lower()

    handlers = {
        "test": run_faz6_test,
        "auto": run_faz6_auto,
        "risk": run_faz6_risk,
        "edge": run_faz6_edge,
        "real": run_faz6_real,
        "balance": run_faz6_balance,
    }

    handler = handlers.get(mode_key)
    if handler is None:
        return f"FAZ-6 ENGINE HATA ❌\nBilinmeyen mod: {mode!r}"

    result = handler()

    # Ek context bilgisi eklenmek istenirse:
    if context:
        existing_ctx = result.get("context") or {}
        existing_ctx.update(context)
        result["context"] = existing_ctx

    # Telegram'a gidecek düzgün text formatı:
    module = result.get("module", "FAZ-6")
    score = result.get("score", "-")
    conf = result.get("confidence", 0.0)
    mod = result.get("mod", mode_key)

    lines = [
        f"🧠 {module}",
        f"⚙️ Mod: {mod.upper()}",
        f"📊 Skor: {score}",
        f"✅ Güven: %{int(conf * 100)}",
    ]

    return "FAZ-6 ENGINE SONUÇ ✅\n" + "\n".join(lines)
