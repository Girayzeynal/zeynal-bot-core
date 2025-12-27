# faz22_engine.py
from typing import List
from league_profiles import get_league_profile
from faz13_engine import Faz13CoreOutput

class Faz22Engine:
    def score_and_finalize(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        profile = get_league_profile(core.ctx.league)
        lo, hi = core.total_band
        actual_width = hi - lo
        expected_width = profile.band_hw_total * 2

        # Baseline quality
        def q(src: str, n: int) -> float:
            if src == "statistics":
                return 1.0
            if src == "games_last5":
                return min(1.0, 0.75 + 0.05 * n)
            return 0.50  # none or unknown

        hq = q(core.meta.get("home_baseline_src"), core.meta.get("home_baseline_n", 0))
        aq = q(core.meta.get("away_baseline_src"), core.meta.get("away_baseline_n", 0))
        baseline_quality = (hq + aq) / 2

        base_conf = 75 - (actual_width - expected_width) * 3
        base_conf = max(30.0, min(90.0, base_conf))
        conf = base_conf * (0.6 + 0.4 * baseline_quality)

        if core.blowout_risk == "HIGH":
            conf -= 10
        elif core.blowout_risk == "MID":
            conf -= 5

        if core.tempo_flag == "FAKE_TEMPO_RISK":
            conf -= 6
        elif core.tempo_flag == "FAST":
            conf -= 2
        elif core.tempo_flag == "SLOW":
            conf -= 3

        m = core.market or {}
        if m.get("status") == "OK":
            line = m.get("market_total")
            if isinstance(line, (int, float)):
                if line < lo or line > hi:
                    conf += profile.market_weight * 5
                else:
                    conf -= profile.market_weight * 5
        else:
            if profile.market_required:
                conf -= 8

        conf = max(25.0, min(95.0, conf))

        if conf < 45:
            risk = "HIGH"
        elif conf < 65:
            risk = "MID"
        else:
            risk = "LOW"

        issues: List[str] = []
        if core.meta.get("home_baseline_src") in {"none"} or core.meta.get("away_baseline_src") in {"none"}:
            issues.append("no_team_data")
        if core.meta.get("home_baseline_src") == "games_last5" and core.meta.get("home_baseline_n", 0) < 3:
            issues.append("home_small_sample")
        if core.meta.get("away_baseline_src") == "games_last5" and core.meta.get("away_baseline_n", 0) < 3:
            issues.append("away_small_sample")

        hb_lo, hb_hi = core.home_band
        ab_lo, ab_hi = core.away_band
        if hb_lo + ab_lo > hi + 4:
            issues.append("team_low_bands > total_hi")
        if hb_hi + ab_hi < lo - 4:
            issues.append("team_hi_bands < total_lo")
        if not issues:
            issues.append("OK")

        core.meta.update({
            "confidence": round(conf, 1),
            "risk": risk,
            "issues": issues,
            "baseline_quality": round(baseline_quality, 2),
            "mode": "FAZ-22 META CALIBRATED"
        })

        core.notes.append(f"Skor yönü: {core.ou_direction} | Güven: {round(conf)} | Risk: {risk}")
        if any(i != "OK" for i in issues):
            core.notes.append("Hata avcısı: " + " | ".join([i for i in issues if i != 'OK']))

        return core 
