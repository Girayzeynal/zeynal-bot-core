# sim_engine.py
# FAZ 3 – Simülasyon çekirdeği (hafif başlangıç)
import random
from statistics import mean, pstdev

def simulate_game(game, n=1000):
    """
    Basit Monte Carlo:
    - Toplam sayı dağılımını OU etrafında küçük sapmalarla örnekler
    - Moneyline oranlarından yaklaşık kazanma olasılığı türetir
    """
    ou = float(game.totals.get("ou", 160.0))
    home_ml = float(game.odds.get("home_ml", 2.0))
    away_ml = float(game.odds.get("away_ml", 2.0))

    inv_home, inv_away = 1.0 / home_ml, 1.0 / away_ml
    ph = inv_home / (inv_home + inv_away)

    total_samples = []
    home_wins = 0
    for _ in range(n):
        sampled_total = random.gauss(mu=ou, sigma=12.5)
        total_samples.append(sampled_total)
        if random.random() < ph:
            home_wins += 1

    total_avg = mean(total_samples)
    total_std = pstdev(total_samples) if len(total_samples) > 1 else 0.0
    home_prob = home_wins / n

    separation = abs(home_prob - 0.5)
    variance_penalty = min(total_std / 20.0, 1.0)
    confidence = max(0.0, min(1.0, separation * (1.0 - variance_penalty)))

    pick = "HOME" if home_prob >= 0.5 else "AWAY"
    return {
        "pick": pick,
        "home_prob": round(home_prob, 3),
        "total_avg": round(total_avg, 1),
        "total_std": round(total_std, 1),
        "confidence": round(confidence, 3),
    }
