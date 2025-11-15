from .faz6_core import FAZ6Core

def run_faz6_engine(mode: str = "test") -> str:
    """
    FAZ-6 Motor Ana Çalıştırıcısı.
    """
    try:
        engine = FAZ6Core()

        sample_data = {
            "home_pts": 55,
            "away_pts": 50
        }

        prediction = engine.analyze(sample_data)

        return (
            f"🧠 FAZ-6 Engine Çalıştı!\n"
            f"🎯 Tahmini Skor: {prediction['predicted_score']}\n"
            f"🔐 Güven: {prediction['confidence']}\n"
            f"Mod: {mode}"
        )

    except Exception as e:
        return f"❌ FAZ-6 çalıştırma hatası: {e}"
