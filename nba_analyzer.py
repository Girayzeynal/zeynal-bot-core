from typing import List
from nba_models import NBAGameState, NBATeamStatsLite


# -------------------------------------------------------------
#  SIMÜLASYON SONUÇ ANALİZİ
# -------------------------------------------------------------
def analyze_sim_results(results: List[dict]) -> str:
    """
    SimEngine çıktısını (game sim sonuçları) formatlı hale getirir.
    """
    lines = ["📊 *FAZ-4 Simülasyon Özeti*"]

    for r in results:
        home = r.get("home")
        away = r.get("away")
        pick = r.get("pick")
        home_prob = r.get("home_prob")
        total_avg = r.get("total_avg")
        pace = r.get("pace_est")

        lines.append(
            f"\n🏀 {home} vs {away}\n"
            f"🔢 Tahmin Edilen Üst: {total_avg}\n"
            f"⏱ Pace Tahmini: {pace}\n"
            f"🎯 Kazanma: {pick} (%{int(home_prob * 100)})"
        )

    return "\n".join(lines)


# -------------------------------------------------------------
#  PLANLANMIŞ (SCHEDULED) MAÇ ANALİZİ
# -------------------------------------------------------------
def analyze_scheduled_games(games: List[NBAGameState]) -> str:
    if not games:
        return "Bugün NBA’de planlanan maç yok."

    lines = ["📅 *NBA – Bugünkü Maçlar*"]

    for g in games:
        line = f"🏀 {g.home_team} vs {g.away_team} – Tipoff (UTC): {g.tipoff_utc.strftime('%H:%M')}"
        lines.append(line)

    return "\n".join(lines)


# -------------------------------------------------------------
#  CANLI MAÇ ANALİZİ
# -------------------------------------------------------------
def analyze_live_games(games: List[NBAGameState]) -> str:
    if not games:
        return "Şu anda canlı NBA maçı bulunmuyor."

    lines = ["🔥 *NBA – Canlı Maçlar*"]

    for g in games:
        if g.home_stats and g.away_stats:
            hs: NBATeamStatsLite = g.home_stats
            aw: NBATeamStatsLite = g.away_stats

            # Tempo tahmini
            if hs.pace_est and aw.pace_est:
                pace = round((hs.pace_est + aw.pace_est) / 2, 1)
            else:
                pace = "?"

            line = (
                f"🏀 {g.home_team} ({hs.pts}) – {g.away_team} ({aw.pts})\n"
                f"⏱ Pace Tahmini: {pace}"
            )
            lines.append(line)

        else:
            lines.append(
                f"⌛ {g.home_team} vs {g.away_team} (Canlı skor yükleniyor...)"
            )

    return "\n".join(lines)


# -------------------------------------------------------------
#  BİTMİŞ MAÇ ANALİZİ
# -------------------------------------------------------------
def analyze_finished_games(games: List[NBAGameState]) -> str:
    if not games:
        return "Bugün bitmiş NBA maçı yok."

    lines = ["🏁 *NBA – Bitmiş Maçlar*"]

    for g in games:
        hs = g.home_stats
        aw = g.away_stats

        if hs and aw:
            if hs.pts > aw.pts:
                winner = g.home_team
            elif aw.pts > hs.pts:
                winner = g.away_team
            else:
                winner = "Berabere"

            line = (
                f"🏀 {g.home_team} ({hs.pts}) – {g.away_team} ({aw.pts}) "
                f"(Kazan: {winner})"
            )
            lines.append(line)

        else:
            lines.append(
                f"🏀 {g.home_team} vs {g.away_team} (Detay bulunamadı)"
            )

    return "\n".join(lines)
