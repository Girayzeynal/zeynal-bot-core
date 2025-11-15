# FAZ-6 EDGE MODÜLÜ
# Avantaj (edge) analizi yaparak daha mantıklı tahmin üretir.

def run_faz6_edge(context: dict = None) -> dict:
    """
    FAZ-6 Edge modülü.
    Takımların güç dengesi ve performans farkını analiz ederek
    'edge' değeri hesaplar.
    """
    if context is None:
        context = {}

    # Örnek edge hesaplama sistemi
    import random

    # Güç dengesi
    home_power = random.uniform(0.40, 0.80)
    away_power = random.uniform(0.30, 0.75)

    edge_value = round(home_power - away_power, 3)

    # Edge pozitif → ev sahibi avantajlı
    # Edge negatif → deplasman avantajlı
    pick = "HOME" if edge_value > 0 else "AWAY"

    confidence = round(min(0.95, 0.60 + abs(edge_value)), 2)

    return {
        "status": "ok",
        "module": "FAZ-6 EDGE",
        "edge_value": edge_value,
        "pick": pick,
        "confidence": confidence,
        "context": context,
    }
