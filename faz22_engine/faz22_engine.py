from __future__ import annotations

from typing import Any, Dict, List, Optional

from league_profiles import get_league_profile


class Faz22Engine:
    """
    FAZ-22 v4.1 — Meta Decision Engine (PRE + LIVE)

    - Segment-aware strong signal detection (ESKİ MOTOR KORUNDU)
    - Confidence Lock sistemi
    - Prematch NO_EDGE → kilitli (ama SOFT UNLOCK ile açılabilir)
    - Live EDGE → kilit açılır
    - LeagueProfile.market_weight uygulanır (gerçekçi confidence)

    PATCH (FORCE MODE):
    - Eğer core.force varsa, market olmasa bile karar üretir.
    - FORCE varsa LOCK kapatılır, final_confidence FORCE'tan alınır.
    """

    # -------------------------
    # Tunables (segment motoru)
    # -------------------------
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

    # -------------------------
    # Meta / Decision tunables
    # -------------------------
    PRE_LOCK_CAP = 55.0
    LIVE_WEAK_BOOST = 4.0
    LIVE_STRONG_BOOST = 8.0

    # PATCH: PRE soft unlock alpha
    PRE_SOFT_UNLOCK_ALPHA_NBA = 0.50
    PRE_SOFT_UNLOCK_ALPHA_DEFAULT = 0.40

    RISK_CAPS = {
        "HIGH": 68.0,
        "MEDIUM": 75.0,
        "LOW": 82.0,
    }

    # -------------------------
    # Utils
    # -------------------------
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

    @staticmethod
    def _fmt1(x: Optional[float]) -> str:
        return "?" if x is None else f"{x:.1f}"

    def _threshold(self, seg: str, std_seg: Optional[float]) -> float:
        if seg == "MS":
            base = self.EDGE_MIN_MS
            k = self.STD_K_MS
        elif seg in ("1Y", "2Y"):
            base = self.EDGE_MIN_1H
            k = self.STD_K_1H
        else:
            base = self.EDGE_MIN_Q
            k = self.STD_K_Q

        if std_seg is None:
            return base
        return max(base, float(std_seg) * k)

    # -------------------------
    # Segment evaluation (ESKİ)
    # -------------------------
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

        edge = expected - market
        thr = self._threshold(seg, std_seg)

        if conf_pct < self.CONF_MIN_PCT:
            return None
        if abs(edge) < thr:
            return None

        out_notes.append(
            f"✅ {seg}: beklenen={expected:.1f} | market={market:.1f} | edge={edge:+.1f} | eşik≥{thr:.1f}"
        )

        return {
            "segment": seg,
            "direction": self._dir(edge),
            "edge": round(edge, 2),
            "threshold": round(thr, 2),
            "expected": round(expected, 2),
            "market": round(market, 2),
        }

    # -------------------------
    # FORCE MODE HELPERS (NEW)
    # -------------------------
    @staticmethod
    def _get_force(core: Any) -> Optional[Dict[str, Any]]:
        """
        FORCE payload can live in:
          - core.force (preferred)
          - core.meta["force"] (fallback)
        """
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
    def _force_direction_label(direction: str) -> str:
        d = (direction or "").upper().strip()
        if d in ("OVER", "UST", "ÜST"):
            return "ÜST"
        if d in ("UNDER", "ALT"):
            return "ALT"
        # FORCE placeholder -> still ok
        return "ÜST"

    # -------------------------
    # PUBLIC API
    # -------------------------
    def score_and_finalize(self, core):
        meta: Dict[str, Any] = getattr(core, "meta", {}) or {}
        base_notes: List[str] = getattr(core, "notes", []) or []

        # =========================
        # LEAGUE PROFILE
        # =========================
        league_name = None
        try:
            league_name = getattr(getattr(core, "ctx", None), "league", None)
        except Exception:
            league_name = None

        profile = get_league_profile(str(league_name or meta.get("league") or "EUROLEAGUE"))
        meta["league_profile"] = profile.name

        # =========================
        # INPUTS
        # =========================
        conf_pct = self._sf(meta.get("confidence_pct")) or 0.0
        sim_std = self._sf(meta.get("sim_std"))
        market_total = self._sf(meta.get("market_total"))
        edge_distance = self._sf(meta.get("edge_distance"))

        prematch_edge = meta.get("edge_flag", "NO_EDGE")
        live_edge = meta.get("live_edge_flag")
        risk = meta.get("risk", "HIGH")

        # =========================
        # FORCE DETECTION (NEW)
        # =========================
        force = self._get_force(core)
        force_enabled = isinstance(force, dict)

        # =========================
        # DECISION PHASE + LOCK
        # =========================
        decision_phase = "LIVE" if live_edge else "PRE"

        # PATCH: market_required hard lock
        if profile.market_required and market_total is None:
            confidence_lock = True
            meta["lock_reason"] = "MARKET_REQUIRED_BUT_MISSING"
        else:
            confidence_lock = prematch_edge in ("NO_EDGE", "WEAK_EDGE")

        # PATCH: Live edge unlock
        if live_edge in ("LIVE_WEAK_EDGE", "LIVE_EDGE"):
            confidence_lock = False
            meta["lock_reason"] = "LIVE_EDGE_UNLOCK"

        # =========================
        # PATCH: FORCE OVERRIDE (NEW)
        # =========================
        if force_enabled:
            # FORCE varsa lock yok; market_required olsa bile karar ver
            confidence_lock = False
            meta["force_enabled"] = True
            meta["lock_reason"] = "FORCE_MODE_OVERRIDE"

        # =========================
        # PATCH: PRE SOFT UNLOCK
        # =========================
        prematch_soft_unlock = False
        if decision_phase == "PRE" and confidence_lock:
            if edge_distance is not None and sim_std is not None:
                alpha = (
                    self.PRE_SOFT_UNLOCK_ALPHA_NBA
                    if profile.name == "NBA"
                    else self.PRE_SOFT_UNLOCK_ALPHA_DEFAULT
                )
                if edge_distance >= sim_std * alpha:
                    confidence_lock = False
                    prematch_soft_unlock = True
                    meta["prematch_soft_unlock"] = True
                    meta["soft_unlock_reason"] = f"EDGE_DISTANCE_GE_STD_X_{alpha:.2f}"

        # =========================
        # CONFIDENCE UPDATE
        # =========================
        final_conf = conf_pct

        # FORCE varsa confidence'ı oradan al (zorunlu karar)
        if force_enabled:
            try:
                f_conf = self._sf(force.get("confidence"))
                if f_conf is not None:
                    # confidence 0..100 beklenir; değilse clamp
                    final_conf = max(0.0, min(100.0, float(f_conf)))
                else:
                    final_conf = max(final_conf, 55.0)
            except Exception:
                final_conf = max(final_conf, 55.0)

            # Risk’i de force’dan alabiliriz
            try:
                f_risk = force.get("risk")
                if isinstance(f_risk, str) and f_risk:
                    risk = f_risk.upper()
                    meta["risk"] = risk
            except Exception:
                pass

        if confidence_lock and not force_enabled:
            final_conf = min(final_conf, self.PRE_LOCK_CAP)
        else:
            if live_edge == "LIVE_WEAK_EDGE":
                final_conf += self.LIVE_WEAK_BOOST
            elif live_edge == "LIVE_EDGE":
                final_conf += self.LIVE_STRONG_BOOST

            if prematch_soft_unlock:
                final_conf += 3.0

        # Risk cap (force dahil)
        final_conf = min(final_conf, self.RISK_CAPS.get(risk, 70.0))

        # PATCH: League market weight (market varsa uygula)
        if market_total is not None:
            final_conf = final_conf * float(profile.market_weight)
            meta["market_weight_applied"] = float(profile.market_weight)

        final_conf = round(final_conf, 1)

        # =========================
        # FORCE MODE PATH when market missing (NEW)
        # =========================
        if market_total is None and force_enabled:
            # Force direction: market yoksa force total tek başına yön taşır (render_html market varsa düzeltir)
            f_total = self._sf(force.get("total"))
            f_dir = self._force_direction_label(str(force.get("direction", "OVER")))

            meta.update({
                "analysis_status": "FORCE_SIGNAL",
                "uncertainty_level": "ORTA",
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
            core.meta = meta

            summary: List[str] = []
            summary.append(
                f"📌 FAZ-22 Karar | League={profile.name} | Phase={decision_phase} | Conf={final_conf}% | Lock=False"
            )
            summary.append("")
            summary.append("🔥 FORCE MODE aktif: Market yokken bile karar üretildi.")
            if f_total is not None:
                summary.append(f"• MS {f_dir} | Total≈{f_total:.0f}")
            summary.append("──────────────────")
            summary.append("ℹ️ Analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")

            core.notes = summary
            return core

        # =========================
        # SEGMENT ANALYSIS (ESKİ MOTOR) — market yoksa eski davranış
        # =========================
        if market_total is None:
            meta.update({
                "analysis_status": "NO_STRONG_SIGNAL",
                "uncertainty_level": "YÜKSEK",
                "decision_phase": decision_phase,
                "confidence_lock": confidence_lock,
                "final_confidence": final_conf,
                "strong_signals": [],
            })
            core.meta = meta
            core.notes = ["⚠️ Market verisi yok → karar üretilemedi."]
            return core

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
        notes: List[str] = []

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

        # =========================
        # FINAL META
        # =========================
        meta.update({
            "decision_phase": decision_phase,
            "confidence_lock": confidence_lock,
            "final_confidence": final_conf,
            "analysis_status": "STRONG_SIGNAL" if strong else "NO_STRONG_SIGNAL",
            "uncertainty_level": "DÜŞÜK" if strong else "YÜKSEK",
            "strong_signals": strong,
        })

        summary: List[str] = []
        summary.append(
            f"📌 FAZ-22 Karar | League={profile.name} | Phase={decision_phase} | Conf={final_conf}% | Lock={confidence_lock}"
        )
        summary.append("")

        if force_enabled:
            summary.append("🔥 FORCE MODE aktif (karar kaçışı yok).")

        if not strong:
            summary.append("📉 Güçlü ve güvenli bir sinyal oluşmadı.")
            summary.append("Maç izleme listesindedir.")
        else:
            summary.append("✅ Güçlü sinyaller:")
            for s in strong:
                summary.append(f"• {s['segment']} {s['direction']} | edge={s['edge']:+.1f}")

        summary.append("──────────────────")
        summary.append("ℹ️ Analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")

        core.notes = summary
        core.meta = meta
        return core
