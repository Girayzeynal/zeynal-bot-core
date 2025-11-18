import math

def calculate_test_predictions(games):
    """
    FAZ-6 TEST ENGINE (Optimized for FAZ-7 Transition)

    - Güven hesaplaması stabil
    - Edge dalgalanması minimize edildi
    - Stake dağılımı risk kontrollü
    - CPU yükü hafifletildi
    """

    predictions = []

    for g in games:
        home = g["home"]
        away = g["away"]
        stats = g["stats"]

        # 1) Güven skoru (FAZ-6 stabil core’dan alınan normalize altyapı)
        conf = (stats["power"] * 0.55) + (stats["form"] * 0.25) + (stats["momentum"] * 0.20)
        conf = round(max(0.50, min(conf, 0.85)), 2)

        # 2) Edge hesaplaması (FAZ-7 uyumlu stabilizasyon)
        edge = round((conf - 0.50) * 0.20, 3)

        # 3) Stake dağılımı — FAZ-6 için optimize, FAZ-7 için uygun
        stake = round(((conf - 0.50) * 3.8) + 0.65, 3)
        stake = max(0.65, min(stake, 2.65))

        # 4) Oyun tipi — otomatik seçim (spread / total / moneyline)
        if stats["type"] == "spread":
            pick = stats["team"] + " " + str(stats["line"])
        elif stats["type"] == "total":
            pick = stats["direction"] + " " + str(stats["line"])
        else:
            pick = stats["team"] + " moneyline"

        predictions.append({
            "match": f"{away}@{home}",
            "pick": pick,
            "conf": conf,
            "edge": edge,
            "stake": stake,
            "league": stats["league"]
        })

    return predictions 
