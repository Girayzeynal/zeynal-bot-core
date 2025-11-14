# heavy_sim_engine.py
# FAZ-5 - Heavy Simulation Çekirdeği (NBA)
#
# Girdi:  nba_fetcher.fetch_nba_live_games() -> List[NBAGameState]
# Çıktı:  nba_analyzer.analyze_sim_results ile uyumlu dict listesi

from typing import List, Dict, Any
from statistics import mean, pstdev
import random

from nba_models import NBAGameState, NBATeamStatsLite


def _estimate_team_mu_sigma(team: NBATeamStatsLite) -> (float, float):
    """
    Takım için ortalama skor (mu) ve standart sapma (sigma) tahmini.
    Şimdilik sade bir model:
    - mu  : sezon ortalama sayı (pts)
    - sigma: pace'e göre ayarlanan değişkenlik
    """
    if not team:
        # Fallback
        return 110.0, 10.0

    base_pts = team.pts or 110.0
    pace = team.pace_est or 100.0

    # Pace arttıkça varyans biraz artsın
    sigma = 8.0 + (pace - 100.0) / 12.0
    sigma = max(6.0, min(15.0, sigma))

    return base_pts, sigma


def simulate_game_heavy(game: NBAGameState, n_sims: int = 5000) -> Dict[str, Any]:
    """
    Tek maç için heavy simülasyon.
    NBAGameState içindeki home_stats / away_stats kullanılır.
    Çıktı, sim_engine.simulate_game yapısına BENZER tutuldu ki
    nba_analyzer.analyze_sim_results ile direkt uyumlu olsun.
    """
    hs: NBATeamStatsLite = game.home_stats
    aw: NBATeamStatsLite = game.away_stats

    home_mu, home_sigma = _estimate_team_mu_sigma(hs)
    away_mu, away_sigma = _estimate_team_mu_sigma(aw)

    home_scores = []
    away_scores = []
    totals = []
    margins = []
    home_wins = 0

    for _ in range(n_sims):
        h = random.gauss(home_mu, home_sigma)
        a = random.gauss(away_mu, away_sigma)

        # Aşırı uçları kırp
        h = max(60.0, min(160.0, h))
        a = max(60.0, min(160.0, a))

        home_scores.append(h)
        away_scores.append(a)
        totals.append(h + a)
        margins.append(h - a)

        if h > a:
            home_wins += 1

    home_prob = home_wins / n_sims
    total_avg = mean(totals)
    total_std = pstdev(totals) if len(totals) > 1 else 0.0
    margin_avg = mean(margins)

    # Pace tahmini (varsa)
    if hs and aw and hs.pace_est and aw.pace_est:
        pace_est = round((hs.pace_est + aw.pace_est) / 2.0, 1)
    else:
        pace_est = None

    # Skor tahmini: ortalama skorları yuvarla
    score_est = f"{int(round(mean(home_scores)))}-{int(round(mean(away_scores)))}"

    # Güven skorunu 0–100 arası ölçekle
    # 0.5'ten ne kadar uzaksa o kadar güven.
    conf_raw = min(1.0, abs(home_prob - 0.5) * 2.0)
    confidence = int(round(50 + conf_raw * 50))  # 50–100 aralığı

    pick = game.home_team if home_prob >= 0.5 else game.away_team

    return {
        "home": game.home_team,
        "away": game.away_team,
        "pick": pick,
        "home_prob": round(home_prob, 3),
        "total_avg": round(total_avg, 1),
        "total_std": round(total_std, 1),
        "pace_est": pace_est,
        "score_est": score_est,
        "margin_avg": round(margin_avg, 1),
        "confidence": confidence,
    }


def run_heavy_sim(games: List[NBAGameState], n_sims: int = 5000) -> List[Dict[str, Any]]:
    """
    Birden fazla maç için heavy simülasyon çalıştırır.
    """
    results: List[Dict[str, Any]] = []
    for g in games:
        try:
            r = simulate_game_heavy(g, n_sims=n_sims)
            results.append(r)
        except Exception:
            # Tek maç patlarsa tüm sim'i bozmasın
            continue
    return results
