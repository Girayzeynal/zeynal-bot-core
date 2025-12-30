# faz22_engine/faz22_engine.py
from __future__ import annotations

import logging
from typing import List, Any

from faz13_engine import Faz13CoreOutput

log = logging.getLogger("zeynal-bot-core")


class Faz22Engine:
    """
    FAZ-22 (TEAM-BASELINE ONLY) — CALIBRATION / RISK / CONFIDENCE

    Bu final build:
    - league_profiles bağımlılığını KALDIRIR (lig baseline / lig profili yok)
    - Sadece TEAM baseline kalitesine göre confidence/risk üretir
    - Team baseline yoksa NO_PLAY üretir (confidence %10, risk NO_PLAY)
    - Market varsa band ile kıyaslar (edge dışındaysa küçük bonus, içindeyse küçük penalty)
    - Notes/meta'yı Telegram çıktısına uyumlu olacak şekilde günceller
    """

    def score_and_finalize(self, core: Faz13CoreOutput) -> Faz13CoreOutput:
        # -----------------------------
        # 0) Baseline kaynak / örneklem
        # -----------------------------
        h_src = (core.meta.get("home_baseline_src") or "none").strip()
        a_src = (core.meta.get("away_baseline_src") or "none").strip()
        h_n = int(core.meta.get("home_baseline_n", 0) or 0)
        a_n = int(core.meta.get("away_baseline_n", 0) or 0)

        # Kaynak kalitesi: lig profili yok → sadece kaynak tipine göre.
        # "statistics" en iyi; "local_match" iyi; "games_last5" örnekleme göre artar; "none" -> 0
        def q(src: str, n: int) -> float:
            src = (src or "none").strip()
            if src == "statistics":
                return 1.0
            if src == "local_match":
                return 0.90
            if src == "games_last5":
                # n=1..5 => 0.57..0.85 (tavan 0.85)
                return min(0.85, 0.50 + 0.07 * max(0, n))
            # none/unknown
            return 0.0

        hq = q(h_src, h_n)
        aq = q(a_src, a_n)
        baseline_quality = (hq + aq) / 2.0

        # -----------------------------
        # 1) NO_PLAY: takım verisi yok
        # -----------------------------
        issues: List[str] = []
        if baseline_quality == 0.0 or h_src == "none" or a_src == "none":
            issues.extend(["TEAM_BASELINE_MISSING", "NO_PLAY"])
            core.meta.update(
                {
                    "confidence": 10.0,
                    "risk": "NO_PLAY",
                    "issues": issues,
                    "baseline_quality": 0.0,
                    "mode": "FAZ-22 TEAM-ONLY V3 (NO_PLAY)",
                }
            )

            # Notes temizle ve net uyarı bas
            core.notes = [n for n in (core.notes or []) if "Güven:" not in n and "Hata Avcısı:" not in n]
            core.notes.append("⚠️ Güven: %10 | Risk: NO_PLAY")
            core.notes.append("🕵️ Hata Avcısı: TEAM_BASELINE_MISSING, NO_PLAY")
            return core

        # -----------------------------
        # 2) Bant genişliği → belirsizlik
        # -----------------------------
        lo, hi = core.total_band
        actual_width = max(0, int(hi) - int(lo))

        # Lig profili yok: beklenen bant genişliği için basit heuristik
        # Basketbol: ~10-14 puan band normal; Futbol: ~2 band normal
        league = (core.ctx.league or "").upper()
        if league in {"EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1", "CHAMPIONSLEAGUE"}:
            expected_width = 2  # goals
        else:
            expected_width = 12  # points

        # Bant genişliği büyüdükçe güven düşer
        base_conf = 75.0 - float(actual_width - expected_width) * 4.0
        base_conf = max(20.0, min(90.0, base_conf))

        # Baseline quality daha baskın (team-only mimari)
        conf = base_conf * (0.30 + 0.70 * baseline_quality)

        # -----------------------------
        # 3) Risk modifikatörleri
        # -----------------------------
        blow = (core.blowout_risk or "").upper()
        tempo = (core.tempo_flag or "").upper()

        if blow == "HIGH":
            conf -= 15.0
        elif blow == "MID":
            conf -= 7.0

        # tempo riskleri
        if tempo == "FAKE_TEMPO_RISK":
            conf -= 10.0
        elif tempo == "FAST":
            conf -= 3.0
        elif tempo == "SLOW":
            conf -= 3.0

        # -----------------------------
        # 4) Market entegrasyonu (lig profili yok)
        # -----------------------------
        m: Any = core.market or {}
        m_status = (m.get("status") or "").upper()

        if m_status == "OK":
            line = m.get("total")
            if isinstance(line, (int, float)):
                # Market çizgisi band dışındaysa: “uyumsuzluk” → value ihtimali → küçük bonus
                if float(line) < float(lo) or float(line) > float(hi):
                    conf += 4.0
                else:
                    # Market ile aynı bant: belirsizlik biraz artar
                    conf -= 3.0
            else:
                conf -= 6.0
        else:
            # market yoksa belirsizlik artar
            conf -= 12.0
            issues.append("MARKET_YOK")

        # -----------------------------
        # 5) Örneklem uyarıları
        # -----------------------------
        # games_last5 kullanılıyorsa n küçükse uyar
        if h_src == "games_last5" and h_n < 3:
            issues.append("YETERSIZ_ORNEKLEM")
        if a_src == "games_last5" and a_n < 3:
            if "YETERSIZ_ORNEKLEM" not in issues:
                issues.append("YETERSIZ_ORNEKLEM")

        # -----------------------------
        # 6) Final clamp + risk etiketi
        # -----------------------------
        # baseline_quality düşükse güveni tavana kilitle (team-only güvenlik)
        if baseline_quality < 0.30:
            conf = min(conf, 25.0)

        conf = max(5.0, min(98.0, conf))

        if conf < 25:
            risk = "EXTREME HIGH"
        elif conf < 40:
            risk = "HIGH"
        elif conf < 70:
            risk = "MID"
        else:
            risk = "LOW"

        if baseline_quality == 0:
            if "KRITIK_VERI_YOK" not in issues:
                issues.append("KRITIK_VERI_YOK")
        else:
            # team baseline var ama düşük kalite ise bilgi amaçlı
            if baseline_quality < 0.55:
                issues.append("LOW_BASELINE_QUALITY")

        if not issues:
            issues = ["OK"]

        # -----------------------------
        # 7) Core meta + notes güncelle
        # -----------------------------
        core.meta.update(
            {
                "confidence": round(conf, 1),
                "risk": risk,
                "issues": issues,
                "baseline_quality": round(baseline_quality, 2),
                "mode": "FAZ-22 TEAM-ONLY V3",
            }
        )

        # Notları temizle ve yeniden yaz
        core.notes = [n for n in (core.notes or []) if "Güven:" not in n and "Hata Avcısı:" not in n]
        core.notes.append(f"📊 Güven: %{round(conf)} | Risk: {risk}")
        if any(i != "OK" for i in issues):
            core.notes.append("🕵️ Hata Avcısı: " + ", ".join([i for i in issues if i != "OK"]))

        return core
