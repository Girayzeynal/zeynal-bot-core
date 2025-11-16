class MLBrain:
    """
    FAZ-6 için basit tahmin beyni.
    Şimdilik dummy hesap, ileride gerçek modelle değiştirilebilir.
    """
    def simple_predict(self, stats: dict) -> dict:
        pts = float(stats.get("pts", 100))
        pace = float(stats.get("pace", 100))
        power = float(stats.get("power", 0.5))

        score = pts * (pace / 100.0) * (0.9 + power * 0.2)
        conf = 0.30 + power * 0.4

        return {
            "score": int(round(score)),
            "conf": float(round(conf, 2)),
        } 
