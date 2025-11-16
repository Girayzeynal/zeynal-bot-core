class Optimizer:
    """
    FAZ-6 optimizer – hafızadaki sonuçlara göre güven ayarı yapar.
    """
    def adjust(self, history: list[dict]) -> dict:
        if not history:
            return {"conf": 0.40}

        confs = [float(item.get("confidence", item.get("conf", 0.4))) for item in history]
        avg_conf = sum(confs) / len(confs)

        # Hafif yukarı/ aşağı oynama
        tuned = max(0.10, min(0.95, avg_conf + 0.05))
        return {"conf": round(tuned, 2)} 
