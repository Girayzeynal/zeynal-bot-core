# heavy_analyzer.py
# FAZ-5 Heavy Simulation Analyzer
# Heavy Simulation sonuçlarını okunabilir metne dönüştürür.

from typing import List


def format_heavy_results(results: List[dict]) -> str:
    """
    Heavy sim sonuçlarını zengin metin olarak döndürür.
    """
    if not results:
        return "⚠️ Ağır simülasyon sonucu bulunamadı."

    lines = ["🔮 *FAZ-5 Ağır NBA Simülasyon Sonuçları*\n"]

    for r in results:
        home = r.get("home")
        away = r.get("away")
        score_est = r.get("score_est")
        pace = r.get("pace_est")
        pick = r.get("pick")
        conf = r.get("confidence")

        lines.append(
            f"🏀 *{home}* vs *{away}*\n"
            f"🎯 Tahmini Toplam Skor: *{score_est}*\n"
            f"⏱️ Tempo (pace): *{pace}*\n"
            f"💡 Tahmini Kazanan: *{pick}* (%{conf})\n"
            f"───────────────\n"
        )

    return "\n".join(lines)
