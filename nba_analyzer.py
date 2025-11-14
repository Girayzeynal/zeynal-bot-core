"""
FAZ-4 – NBA Analyzer (İskelet)

Bu dosya:
- nba_fetcher’dan gelen NBAGameState verisini alır
- Basit analizler üretir
- Telegram botun /nba_today ve /nba_live komutları için temiz metin döndürür
"""

from typing import List
from nba_models import NBAGameState, NBATeamStatsLite


def analyze_scheduled_games(games: List[NBAGameState]) -> str:
    """
    Henüz başlamamış (scheduled) maçlar için basit özet.
    İleride model skor tahmini eklenecek.
    """
    if not games:
        return "Bugün NBA’de planlanan maç bulunmuyor."

    lines = ["📅 *NBA – Bugünkü Maçlar*"]
    for g in games:
        line = f"• {g.home_team} vs {g.away_team} — Tipoff (UTC): {g.tipoff_utc.strftime('%H:%M')}"
        lines.append(line)

    return "\n".join(lines)


def analyze_live_games(games: List[NBAGameState]) -> str:
    """
    Canlı maçlar için skor + basit tempo analizi.
    """
    if not games:
        return "Şu anda canlı NBA maçı bulunmuyor."

    lines = ["🔥 *NBA – Canlı Maçlar*"]

    for g in games:
        if g.home_stats and g.away_stats:
            hs = g.home_stats
            aw = g.away_stats
            line = (
                f"• {g.home_team} {hs.pts} – {aw.pts} {g.away_team} "
                f"(Pace: {round((hs.pace_est + aw.pace_est) / 2, 1)})"
            )
            lines.append(line)
        else:
            lines.append(f"• {g.home_team} vs {g.away_team} (Skor verisi yükleniyor...)")

    return "\n".join(lines)


def analyze_finished_games(games: List[NBAGameState]) -> str:
    """Bitmiş maçlar için basit özet."""
    if not games:
        return "Bugün bitmiş NBA maçı yok."

    lines = ["🏁 *NBA – Bitmiş Maçlar*"]

    for g in games:
        hs = g.home_stats
        aw = g.away_stats

        if hs and aw:
            winner = g.home_team if hs.pts > aw.pts else g.away_team
            line = f"• {hs.pts}-{aw.pts} sonucu ile kazanan: {winner}"
        else:
            line = f"• {g.home_team} vs {g.away_team} (detay yok)"

        lines.append(line)

    return "\n".join(lines)
