"""
FAZ-5 Heavy Engine Ana Modül
Her mod çalıştırıldığında bu dosya devreye girer.
Bu sürüm FAZ-5’in bağımsız, sade, stabil çekirdeğidir.
"""

import random
import math


class EngineCore:
    """FAZ-5'in basit motor sınıfı."""
    def evaluate_match(self, match, mode):
        home, away = match
        score_est = int((home["pts"] + away["pts"]) / 2)
        pace = (home["pace"] + away["pace"]) / 2
        power_diff = home["power"] - away["power"]

        winner = home["code"] if power_diff >= 0 else away["code"]

        return {
            "score_est": score_est,
            "pace": round(pace, 1),
            "power_diff": power_diff,
            "winner": winner
        }


def run_heavy_engine(mode="standard"):
    """
    FAZ-5 motorunu seçilen moda göre çalıştırır.
    Dönüş: string (Telegram için hazır metin)
    """

    core = EngineCore()

    # Örnek dummy paket:
    home = {"code": "LAL", "pts": 110, "pace": 102, "power": 78}
    away = {"code": "BOS", "pts": 104, "pace": 99, "power": 75}

    match = (home, away)

    result = core.evaluate_match(match, mode)

    text = f"""
🛡 *FAZ-5 Heavy Engine Çalıştırıldı*

🏀 {home['code']} vs {away['code']}

🎯 Tahmini Skor: {result['score_est']}
⏱ Tempo (Pace): {result['pace']}
💪 Güç Dengesi: {result['power_diff']}
🏆 Tahmini Kazanan: {result['winner']}
"""

    return text


def main():
    print(run_heavy_engine("standard"))


if __name__ == "__main__":
    main() 
