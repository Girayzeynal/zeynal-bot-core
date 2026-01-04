from __future__ import annotations

from typing import Any, Dict, List, Optional

from league_profiles import get_league_profile


class Faz22Engine:
    """
    FAZ-22 v4.1 — Meta Decision Engine (PRE + LIVE)

    PRODUCTION ENGINE (PATCHED):
    - PRE phase'te market yokken core compute çalışır
    - Early return (hesaplama boğucu) KALDIRILDI
    - FORCE MODE (debug / test) desteklenir
    - PRE SOFT UNLOCK aktiftir
    - FAZ-13 hesap / FAZ-22 karar ayrımı NET
    """

    # =================================================
    # SEGMENT TUNABLES
    # =================================================
    CONF_MIN_PCT = 60.0

    EDGE_MIN_MS = 6.0
    EDGE_MIN_1H = 4.0
    EDGE_MIN_Q = 3.0

    STD_RATIO_1H = 0.55
    STD_RATIO_2H = 0.60
    STD_RATIO_Q = 0.35

    STD_K_MS = 0.40
    STD_K_1H = 0.35
    STD_K_Q = 0.30

    # =================================================
    # META / DECISION TUNABLES
    # =================================================
    PRE_LOCK_CAP = 55.0

    LIVE_WEAK_BOOST = 4.0
    LIVE_STRONG_BOOST = 8.0

    PRE_SOFT_UNLOCK_ALPHA_NBA = 0.50
    PRE_SOFT_UNLOCK_ALPHA_DEFAULT = 0.40

    RISK_CAPS = {
        "HIGH": 68.0,
        "MEDIUM": 75.0,
        "LOW": 82.0,
    }

    # =================================================
    # UTILS
    # =================================================
    @staticmethod
    def _sf(v: Any) -> Optional[float]:
        try:
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    @staticmethod
    def _dir(edge: float) -> str:
        return "ÜST" if edge > 0 else "ALT"

    def _threshold(self, seg: str, std_seg: Optional[float]) -> float:
        if seg == "MS":
            base, k = self.EDGE_MIN_MS, self.STD_K_MS
        elif seg in ("1Y", "2Y"):
            base, k = self.EDGE_MIN_1H, self.STD_K_1H
        else:
            base, k = self.EDGE_MIN_Q, self.STD_K_Q

        if std_seg is None:
            return base
        return max(base, float(std_seg) * k)

    # =================================================
    # SEGMENT EVALUATION (CORE)
    # =================================================
    def _eval_segment(
        self,
        seg: str,
        expected: Optional[float],
        market: Optional[float],
        std_seg: Optional[float],
        conf_pct: float,
        out_notes: List[str],
    ) -> Optional[Dict[str, Any]]:
        if expected is None or market is None:
            return None

        if conf_pct < self.CONF_MIN_PCT:
            return None

        edge = expected - market
        thr = self._threshold(seg, std_seg)

        if abs(edge) < thr:
            return None

        out_notes.append(
            f"✅ {seg}: beklenen={expected:.1f} | market={market:.1f} | "
            f"edge={edge:+.1f} | eşik≥{thr:.1f}"
        )

        return {
            "segment": seg,
            "direction": self._dir(edge),
            "edge": round(edge, 2),
            "threshold": round(thr, 2),
            "expected": round(expected, 2),
            "market": round(market, 2),
        }

    # =================================================
    # FORCE MODE
    # =================================================
    @staticmethod
    def _get_force(core: Any) -> Optional[Dict[str, Any]]:
        try:
            f = getattr(core, "force", None)
            if isinstance(f, dict):
                return f
        except Exception:
            pass

        try:
            meta = getattr(core, "meta", {}) or {}
            f2 = meta.get("force")
            if isinstance(f2, dict):
                return f2
        except Exception:
            pass

        return None

    @staticmethod
    def _force_dir(d: str) -> str:
        d = (d or "").upper()
        if d in ("OVER", "UST", "ÜST"):
            return "ÜST"
        if d in ("UNDER", "ALT"):
            return "ALT"
        return "ÜST"

    # =================================================
    # PUBLIC API
    # =================================================
    def score_and_finalize(self, core):
        meta: Dict[str, Any] = getattr(core, "meta", {}) or {}
        notes: List[str] = []

        # -------------------------
        # LEAGUE PROFILE
        # -------------------------
        league = None
        try:
            league = getattr(getattr(core, "ctx", None), "league", None)
        except Exception:
            pass

        profile = get_league_profile(str(league or meta.get("league") or "EUROLEAGUE"))
        meta["league_profile"] = profile.name

        # -------------------------
        # INPUTS (FAZ-13 çıktıları)
        # -------------------------
        conf_pct = self._sf(meta.get("confidence_pct")) or 0.0
        sim_std = self._sf(meta.get("sim_std"))
        market_total = self._sf(meta.get("market_total"))
        edge_distance = self._sf(meta.get("edge_distance"))

        prematch_edge = meta.get("edge_flag", "NO_EDGE")
        live_edge = meta.get("live_edge_flag")
        risk = meta.get("risk", "HIGH")

        # -------------------------
        # FORCE
        # -------------------------
        force = self._get_force(core)
        force_enabled = isinstance(force, dict)

        # -------------------------
        # PHASE
        # -------------------------
        decision_phase = "LIVE" if live_edge else "PRE"

        # -------------------------
        # LOCK LOGIC (PATCHED)
        # -------------------------
        confidence_lock = prematch_edge in ("NO_EDGE", "WEAK_EDGE")

        if profile.market_required and market_total is None:
            confidence_lock = True
            meta["lock_reason"] = "MARKET_REQUIRED_BUT_MISSING"

        if live_edge in ("LIVE_WEAK_EDGE", "LIVE_EDGE"):
            confidence_lock = False
            meta["lock_reason"] = "LIVE_EDGE_UNLOCK"

        if force_enabled:
            confidence_lock = False
            meta["lock_reason"] = "FORCE_MODE_OVERRIDE"
            meta["force_enabled"] = True

        # -------------------------
        # PRE SOFT UNLOCK
        # -------------------------
        if decision_phase == "PRE" and confidence_lock:
            if edge_distance is not None and sim_std is not None:
                alpha = (
                    self.PRE_SOFT_UNLOCK_ALPHA_NBA
                    if profile.name == "NBA"
                    else self.PRE_SOFT_UNLOCK_ALPHA_DEFAULT
                )
                if edge_distance >= sim_std * alpha:
                    confidence_lock = False
                    meta["prematch_soft_unlock"] = True

        # -------------------------
        # CONFIDENCE CALC
        # -------------------------
        final_conf = conf_pct

        if force_enabled:
            f_conf = self._sf(force.get("confidence"))
            if f_conf is not None:
                final_conf = max(0.0, min(100.0, f_conf))
            else:
                final_conf = max(final_conf, 55.0)

            f_risk = force.get("risk")
            if isinstance(f_risk, str):
                risk = f_risk.upper()
                meta["risk"] = risk

        if confidence_lock and not force_enabled:
            final_conf = min(final_conf, self.PRE_LOCK_CAP)
        else:
            if live_edge == "LIVE_WEAK_EDGE":
                final_conf += self.LIVE_WEAK_BOOST
            elif live_edge == "LIVE_EDGE":
                final_conf += self.LIVE_STRONG_BOOST

        final_conf = min(final_conf, self.RISK_CAPS.get(risk, 70.0))

        if market_total is not None:
            final_conf *= float(profile.market_weight)
            meta["market_weight_applied"] = float(profile.market_weight)

        final_conf = round(final_conf, 1)

        # =================================================
        # MARKET YOK → FORCE VAR
        # =================================================
        if market_total is None and force_enabled:
            f_total = self._sf(force.get("total"))
            f_dir = self._force_dir(force.get("direction"))

            meta.update({
                "analysis_status": "FORCE_SIGNAL",
                "decision_phase": decision_phase,
                "confidence_lock": False,
                "final_confidence": final_conf,
                "strong_signals": [{
                    "segment": "MS",
                    "direction": f_dir,
                    "edge": None,
                    "threshold": None,
                    "expected": f_total,
                    "market": None,
                }],
            })

            notes.append(
                f"📌 FAZ-22 Karar | League={profile.name} | Phase={decision_phase} | "
                f"Conf={final_conf}% | Lock=False"
            )
            notes.append("")
            notes.append("🔥 FORCE MODE aktif: Market yokken karar üretildi.")
            notes.append("──────────────────")
            notes.append("ℹ️ Analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")

            core.meta = meta
            core.notes = notes
            return core

        # =================================================
        # MARKET YOK → NORMAL PRE (AMA HESAP VAR)
        # =================================================
        if market_total is None:
            meta.update({
                "analysis_status": "NO_STRONG_SIGNAL",
                "decision_phase": decision_phase,
                "confidence_lock": confidence_lock,
                "final_confidence": final_conf,
                "strong_signals": [],
            })
            core.meta = meta
            core.notes = ["⚠️ Market verisi yok → karar kilitli (hesaplandı)."]
            return core

        # =================================================
        # SEGMENT ANALYSIS
        # =================================================
        market_ms = market_total
        market_1h = self._sf(meta.get("market_1h")) or market_total / 2.0
        market_2h = self._sf(meta.get("market_2h")) or market_total / 2.0
        market_q = market_total / 4.0

        exp_ms = self._sf(meta.get("expected_total"))
        exp_1h = self._sf(meta.get("expected_1h"))
        exp_2h = self._sf(meta.get("expected_2h"))
        exp_q1 = self._sf(meta.get("expected_q1"))
        exp_q2 = self._sf(meta.get("expected_q2"))
        exp_q3 = self._sf(meta.get("expected_q3"))
        exp_q4 = self._sf(meta.get("expected_q4"))

        std_ms = sim_std
        std_1h = sim_std * self.STD_RATIO_1H if sim_std else None
        std_2h = sim_std * self.STD_RATIO_2H if sim_std else None
        std_q = sim_std * self.STD_RATIO_Q if sim_std else None

        strong: List[Dict[str, Any]] = []

        for seg, exp, mkt, std in [
            ("MS", exp_ms, market_ms, std_ms),
            ("1Y", exp_1h, market_1h, std_1h),
            ("2Y", exp_2h, market_2h, std_2h),
            ("Q1", exp_q1, market_q, std_q),
            ("Q2", exp_q2, market_q, std_q),
            ("Q3", exp_q3, market_q, std_q),
            ("Q4", exp_q4, market_q, std_q),
        ]:
            r = self._eval_segment(seg, exp, mkt, std, final_conf, notes)
            if r:
                strong.append(r)

        # =================================================
        # FINAL META + NOTES
        # =================================================
        meta.update({
            "decision_phase": decision_phase,
            "confidence_lock": confidence_lock,
            "final_confidence": final_conf,
            "analysis_status": "STRONG_SIGNAL" if strong else "NO_STRONG_SIGNAL",
            "strong_signals": strong,
        })

        notes.append(
            f"📌 FAZ-22 Karar | League={profile.name} | Phase={decision_phase} | "
            f"Conf={final_conf}% | Lock={confidence_lock}"
        )
        notes.append("")

        if strong:
            notes.append("✅ Güçlü sinyaller:")
            for s in strong:
                notes.append(f"• {s['segment']} {s['direction']} | edge={s['edge']:+.1f}")
        else:
            notes.append("📉 Güçlü ve güvenli bir sinyal oluşmadı.")
            notes.append("Maç izleme listesindedir.")

        notes.append("──────────────────")
        notes.append("ℹ️ Analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")

        core.meta = meta
        core.notes = notes
        return core 
