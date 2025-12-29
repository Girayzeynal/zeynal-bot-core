from typing import List
import logging
from league_profiles import get_league_profile
from faz13_engine import Faz13CoreOutput

log = logging.getLogger("zeynal-bot-core")

class Faz22Engine:
    def score_and_finalize(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        profile = get_league_profile(core.ctx.league)
        
        # 1. Veri Kalitesi (Baseline Quality) - DAHA SERT CEZALAR
        def q(src: str, n: int) -> float:
            if src == "statistics": return 1.0
            if src == "local_match": return 0.90
            if src == "games_last5": return min(0.85, 0.50 + 0.07 * n)
            return 0.0  # Veri yoksa kalite SIFIRDIR

        h_src = core.meta.get("home_baseline_src")
        a_src = core.meta.get("away_baseline_src")
        h_n = core.meta.get("home_baseline_n", 0)
        a_n = core.meta.get("away_baseline_n", 0)

        hq = q(h_src, h_n)
        aq = q(a_src, a_n)
        baseline_quality = (hq + aq) / 2

        # 2. Bant Genişliği Analizi
        lo, hi = core.total_band
        actual_width = hi - lo
        expected_width = profile.band_hw_total * 2
        
        # Base confidence calculation
        base_conf = 75 - (actual_width - expected_width) * 4
        base_conf = max(20.0, min(90.0, base_conf))
        
        # Veri kalitesi çarpanını daha etkili hale getirdik
        conf = base_conf * (0.3 + 0.7 * baseline_quality)

        # 3. Risk Modifikatörleri
        if core.blowout_risk == "HIGH": conf -= 15
        elif core.blowout_risk == "MID": conf -= 7

        if core.tempo_flag == "FAKE_TEMPO_RISK": conf -= 10
        elif core.tempo_flag == "FAST": conf -= 3

        # 4. Market Entegrasyonu Etkisi
        m = core.market or {}
        if m.get("status") == "OK":
            line = m.get("total")
            # Eğer market çizgisi bizim bandımızın dışındaysa bu bir fırsattır (Edge)
            if isinstance(line, (int, float)):
                if line < lo or line > hi:
                    conf += (profile.market_weight * 8)
                else:
                    conf -= 5 # Market ile aynı fikirdeysek güven düşer (Value azalır)
        else:
            conf -= 12 # Market verisi yoksa belirsizlik artar

        # 5. Final Sınırlandırma
        # Eğer veri yoksa güven skorunu %25'in üzerine çıkartma
        if baseline_quality < 0.3:
            conf = min(conf, 25.0)

        conf = max(5.0, min(98.0, conf))

        # 6. Risk Seviyesi Belirleme
        if conf < 40: risk = "EXTREME HIGH"
        elif conf < 55: risk = "HIGH"
        elif conf < 75: risk = "MID"
        else: risk = "LOW"

        # 7. Issue (Hata) Avcısı
        issues = []
        if baseline_quality == 0: issues.append("KRITIK_VERI_YOK")
        if h_n < 3 or a_n < 3: issues.append("YETERSIZ_ORNEKLEM")
        if not m.get("status") == "OK": issues.append("MARKET_YOK")

        # Core objesini güncelle
        core.meta.update({
            "confidence": round(conf, 1),
            "risk": risk,
            "issues": issues if issues else ["OK"],
            "mode": "FAZ-22 CALIBRATED V2"
        })

        # Notları temizle ve yeniden yaz
        core.notes = [n for n in core.notes if "Güven:" not in n and "Hata avcısı:" not in n]
        core.notes.append(f"📊 Güven: %{round(conf)} | Risk: {risk}")
        if issues:
            core.notes.append(f"🕵️ Hata Avcısı: {', '.join(issues)}")

        return core
 
