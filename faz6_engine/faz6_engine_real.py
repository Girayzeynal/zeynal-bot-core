"""
FAZ-6 Engine - Real Mode
Gerçek maç verisi ile çalışan FAZ-6 ana modudur.
NBA form datasını okuyarak tahmini skor, pace, güç farkı
ve güven yüzdesi üretir.
"""

from nba_fetcher import get_team_form
from nba_models import TeamStats


def calculate_realmode_score(home: TeamStats, away: TeamStats):
    """
    RealMode skor hesaplama fonksiyonu.
    Takım formu + güç farkı + pace + varyans ile tahmin üretir.
    """

    # Temel tempo hesabı (ortalama pace)
    pace = (home.pace + away.pace) / 2

    # Güç farkı
    power_diff = home.power - away.power

    # Ortalama skor tabanı
    base_score = (home.avg_score + away.avg_score) / 2

    # FAZ-6 formülü:
    # pace'in %10'u + power_diff'in 0.8 katsayılı etkisi
    est_score = base_score + (pace * 0.10) + (power_diff * 0.8)

    # Tahmini kazanan
    winner = home.code if home.power > away.power else away.code

    # Güven yüzdesi varyans hesabı
    variance = abs(power_diff) / 20
    confidence = min(1.0, 0.30 + variance)

    return {
        "score": round(est_score),
        "pace": round(pace, 2),
        "power_diff": round(power_diff, 2),
        "confidence": round(confidence, 2),
        "winner": winner
    }


def run_faz6_real(home_code: str = "LAL", away_code: str = "BOS") -> str:
    """
    ANA FONKSİYON
    Telegram bot tarafından çağrılır.
    Gerçek takım kodları ile RealMode çalıştırır.
    """

    # Takım form verilerini çek
    home = get_team_form(home_code)
    away = get_team_form(away_code)

    # Sonucu hesapla
    result = calculate_realmode_score(home, away)

    # Telegram metni
    text = f"""
🧠 *FAZ-6 RealMode Sonuçları*

🏀 {home.code} vs {away.code}
🎯 Tahmini Skor: {result['score']}
⏱ Tempo: {result['pace']}
💪 Güç Farkı: {result['power_diff']}
🔒 Güven: {result['confidence']}
🏆 Kazanan: {result['winner']}

Mod: real
"""

    return text


# Manuel test için (lokalde çalıştırmak istersen)
if __name__ == "__main__":
    print(run_faz6_real())
