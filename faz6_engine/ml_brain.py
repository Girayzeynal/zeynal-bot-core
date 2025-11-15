class MLBrain:
    """
    FAZ-6 yapay zekâ beyni.
    Bu versiyon temel matematiktir — gerçek model sonraki adımlarda gelir.
    """

    def simple_predict(self, stats: dict) -> dict:
        try:
            score = stats.get("home_pts", 50) + stats.get("away_pts", 50)
            confidence = min(0.99, abs(stats.get("home_pts", 0) - stats.get("away_pts", 0)) / 20)
            return {
                "predicted_score": score,
                "confidence": round(confidence, 2)
            }
        except:
            return {"predicted_score": None, "confidence": 0.0} 
