# engines/faz13_engine.py
from __future__ import annotations

from typing import Dict, Any, Optional, Tuple

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper, TeamStatsAdapter


def _risk_label(conf: float, issues: list[str]) -> str:
    # no_team_data varsa güven "gibi" görünmesin diye risk yükselt
    if "no_team_data" in issues:
        return "HIGH"
    if conf >= 75:
        return "LOW"
    if conf >= 60:
        return "MID"
    return "HIGH"


class Faz13Engine:
    def __init__(self, stats_adapter: TeamStatsAdapter):
        self.store = TeamBaselineStore()
        self.bootstrap = TeamBaselineBootstrapper(self.store, stats_adapter)

    def pre_analyze(self, league: str, home: str, away: str) -> Dict[str, Any]:
        issues: list[str] = []

        # ✅ first: try to ensure baseline exists (auto-backfill)
        hb = self.bootstrap.ensure(league, home, min_games=6)
        ab = self.bootstrap.ensure(league, away, min_games=6)

        if not hb:
            issues.append("no_team_data")
        if not ab and "no_team_data" not in issues:
            issues.append("no_team_data")

        # If still missing, do NOT pretend it's fine.
        if not hb or not ab:
            conf = 45.0  # hard drop (honesty mode)
            return {
                "league_profile": league,
                "home": home,
                "away": away,
                "baseline": {
                    "home_baseline_src": "none",
                    "home_baseline_n": 0,
                    "away_baseline_src": "none",
                    "away_baseline_n": 0,
                },
                "signals": {
                    "alt_ust": "NO_EDGE",
                    "tempo_flag": "UNKNOWN",
                    "blowout_risk": "UNKNOWN",
                },
                "meta": {
                    "confidence": conf,
                    "risk": _risk_label(conf, issues),
                    "issues": issues,
                    "mode": "FAZ-13 TEAM-BASELINE REQUIRED",
                },
                "notes": [
                    "UYARI: Team baseline alınamadı → analiz kilitlendi (lig baseline kullanılmıyor).",
                    "Çözüm: TeamStatsAdapter veri kaynağına bağlanmalı veya baselines klasörü doldurulmalı.",
                ],
            }

        # ✅ normal compute (simple skeleton; senin mevcut hesaplarını buraya taşı)
        # Example: expected total ~ avg(pts_for) adjusted by pace, stdev_total from both
        exp_total = (hb.pts_for + ab.pts_for) / 2.0
        sigma = (hb.stdev_total + ab.stdev_total) / 2.0
        conf = 62.8  # keep your existing confidence calc if you have it

        return {
            "league_profile": league,
            "home": home,
            "away": away,
            "baseline": {
                "home_baseline_src": "team",
                "home_baseline_n": hb.n_games,
                "away_baseline_src": "team",
                "away_baseline_n": ab.n_games,
                "mu_total": round(exp_total, 2),
                "sigma_total": round(sigma, 2),
                "pace": round((hb.pace + ab.pace) / 2.0, 3),
            },
            "bands": {
                "ft": [round(exp_total - 6), round(exp_total + 6)],
                "ht": [round((exp_total / 2.0) - 4), round((exp_total / 2.0) + 4)],
                "q": [round((exp_total / 4.0) - 2), round((exp_total / 4.0) + 2)],
            },
            "signals": {
                "alt_ust": "NO_EDGE",  # market FAZ-17 ile netleşir
                "tempo_flag": "NORMAL",
                "blowout_risk": "LOW",
            },
            "meta": {
                "confidence": conf,
                "risk": _risk_label(conf, issues),
                "issues": issues,
                "mode": "FAZ-13 TEAM BASELINE",
            },
        }
