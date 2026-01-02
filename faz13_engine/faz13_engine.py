from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore
from league_profiles import get_league_profile

try:
    from core.aggregate_engine import aggregate_baseline as _aggregate_baseline  # type: ignore
except Exception:
    _aggregate_baseline = None

try:
    from providers import ESPNAdapter  # type: ignore
except Exception:
    ESPNAdapter = None  # type: ignore

# Optional FAZ-17 market engine (if exists in your repo)
try:
    from faz17_engine.faz17_engine import Faz17Engine, MarketRequest  # type: ignore
except Exception:
    Faz17Engine = None  # type: ignore
    MarketRequest = None  # type: ignore


# =====================================================
# DATA MODELS
# =====================================================

@dataclass(frozen=True)
class PrematchRequest:
    fixture_id: int
    league: str
    date_str: str
    home: str
    away: str


@dataclass
class TeamAverages:
    points_for: float
    points_against: float
    pace_hint: float
    stdev_hint: float


@dataclass
class FixtureContext:
    league: str
    date: str
    home: str
    away: str


@dataclass
class Faz13CoreOutput:
    ctx: FixtureContext
    home_avg: TeamAverages
    away_avg: TeamAverages
    total_band: Tuple[int, int]
    home_band: Tuple[int, int]
    away_band: Tuple[int, int]
    ou_direction: str
    quarters: Dict[str, Tuple[int, int]]
    blowout_risk: str
    tempo_flag: str
    notes: List[str] = field(default_factory=list)
    market: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def render_html(self) -> str:
        esc = html.escape

        def _fmt(v: Any) -> str:
            if isinstance(v, (list, tuple, set)):
                return ", ".join(str(x) for x in v)
            return str(v)

        out: List[str] = []
        out.append("FAZ-13 Ön Analiz")
        out.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | "
            f"Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )

        out.append("")
        out.append("Dar Bant")
        out.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        out.append(
            f"• Ev: {self.home_band[0]}–{self.home_band[1]} | "
            f"Dep: {self.away_band[0]}–{self.away_band[1]}"
        )
        out.append(f"• Alt/Üst yönü: {esc(self.ou_direction)}")

        out.append("")
        out.append("Periyot Senaryosu (dar bant)")
        for k in ("1Q", "2Q", "3Q", "4Q"):
            if k in self.quarters:
                a, b = self.quarters[k]
                out.append(f"• {k}: {a}–{b}")

        out.append("")
        out.append("Risk Göstergeleri")
        out.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        out.append(f"• Tempo flag: {esc(self.tempo_flag)}")

        if self.notes:
            out.append("")
            out.append("Notlar")
            for n in self.notes:
                out.append(f"• {esc(str(n))}")

        if self.market:
            out.append("")
            out.append("Market Entegrasyonu")
            for k, v in self.market.items():
                out.append(f"• {esc(str(k))}: {esc(_fmt(v))}")

        if self.meta:
            out.append("")
            out.append("Meta Skor")
            for k, v in self.meta.items():
                out.append(f"• {esc(str(k))}: {esc(_fmt(v))}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


# =====================================================
# AGGREGATE
# =====================================================

def _fallback_aggregate_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None

    total_conf = sum(float(r.get("confidence", 0.0)) for r in rows)
    if total_conf <= 0:
        return None

    pts_for = sum(float(r["pts_for"]) * float(r["confidence"]) for r in rows) / total_conf
    pts_against = sum(float(r["pts_against"]) * float(r["confidence"]) for r in rows) / total_conf
    sources = [r.get("source") for r in rows if r.get("source")]

    pace_vals = [float(r["pace"]) for r in rows if r.get("pace") is not None]
    pace = sum(pace_vals) / len(pace_vals) if pace_vals else None

    return {
        "pts_for": pts_for,
        "pts_against": pts_against,
        "confidence": total_conf / len(rows),
        "sources": sources,
        "pace": pace,
    }


def aggregate_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if _aggregate_baseline:
        try:
            return _aggregate_baseline(rows)  # type: ignore
        except Exception:
            return _fallback_aggregate_baseline(rows)
    return _fallback_aggregate_baseline(rows)


# =====================================================
# ENGINE
# =====================================================

class Faz13Engine:
    def __init__(
        self,
        api_sports_key: str,
        api_sports_base: str,
        baseline_store: Optional[TeamBaselineStore] = None,
        min_baseline_games: int = 6,
    ) -> None:
        self.api_key = (api_sports_key or "").strip()
        self.base = (api_sports_base or "https://v1.basketball.api-sports.io").rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games)

        # Optional market engine
        self.faz17 = Faz17Engine() if Faz17Engine is not None else None

        self._espn_alias_cache: Dict[str, Any] = {"ts": 0.0, "index": {}}
        self._espn_alias_ttl_sec = int(os.getenv("FAZ13_ESPN_ALIAS_TTL_SEC", "21600"))

    # -----------------------------
    # Helpers
    # -----------------------------
    @staticmethod
    def resolve_nba_season(date_str: str) -> str:
        try:
            y = int(date_str[:4])
            m = int(date_str[5:7])
        except Exception:
            return date_str[:4]
        return str(y) if m >= 10 else str(y - 1)

    @staticmethod
    def format_nba_season_label(season_start_year: str) -> str:
        try:
            y = int(season_start_year)
            return f"{y}-{str((y + 1) % 100).zfill(2)}"
        except Exception:
            return season_start_year

    @staticmethod
    def tempo_flag_from_pace(pace: float) -> str:
        if pace >= 102:
            return "FAST"
        if pace <= 97:
            return "SLOW"
        return "NORMAL"

    @staticmethod
    def _tight_confidence(conf_raw: float) -> float:
        """
        Confidence eğrisi sıkılaştırma:
        0.50-0.75 bandını daha seçici yapar.
        """
        c = max(0.0, min(1.0, float(conf_raw)))
        # exponent >1 => orta bandı aşağı çeker (daha seçici)
        # 1.35 iyi bir başlangıç: agresif değil ama net.
        return c ** 1.35

    @staticmethod
    def _edge_threshold(conf_tight: float, band_hw_total: int) -> float:
        """
        Edge threshold: confidence yükseldikçe eşik biraz düşer,
        confidence düşünce eşik yükselir (NO_EDGE artar, yanlış edge azalır).
        """
        base = max(2.0, float(band_hw_total) * 0.30)
        # conf 0..1, high conf => factor 0.85, low conf => 1.25
        factor = 1.25 - 0.40 * max(0.0, min(1.0, conf_tight))
        return base * factor

    @staticmethod
    def _quarters_band(total_mu: float, band_hw_total: int, tempo_flag: str) -> Dict[str, Tuple[int, int]]:
        """
        Periyot bazlı skor bandı (deterministik split).
        Gerçek periyot verisi yoksa bile sabit dağılım + tempo ile makul projeksiyon.
        """
        # NBA tipik dağılım (toplamın yüzdesi)
        w = [0.24, 0.26, 0.25, 0.25]  # 1Q 2Q 3Q 4Q

        # tempo etkisi: FAST => 1Q/2Q biraz şişer, SLOW => biraz düşer
        if tempo_flag == "FAST":
            w = [0.245, 0.265, 0.245, 0.245]
        elif tempo_flag == "SLOW":
            w = [0.235, 0.255, 0.255, 0.255]

        q_hw = max(2, int(round(band_hw_total / 2.8)))  # quarter half-width
        qs = {}
        labels = ["1Q", "2Q", "3Q", "4Q"]
        for i, lab in enumerate(labels):
            mu = total_mu * w[i]
            qs[lab] = (int(mu - q_hw), int(mu + q_hw))
        return qs

    # -----------------------------
    # MAIN
    # -----------------------------
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        season = (
            self.resolve_nba_season(req.date_str)
            if req.league.upper() == "NBA"
            else req.date_str[:4]
        )
        season_str = (
            self.format_nba_season_label(season)
            if req.league.upper() == "NBA"
            else season
        )

        notes: List[str] = [f"Season: {season_str}", "TEAM-FIRST mode (MULTI-SOURCE)"]
        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        # -------------------------
        # BASELINE (ESPN)
        # -------------------------
        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []
        home_abbr: Optional[str] = None
        away_abbr: Optional[str] = None

        if req.league.upper() == "NBA" and ESPNAdapter:
            try:
                espn = ESPNAdapter()
                # Not: ESPNAdapter dosyanda _espn_resolve_abbr yok; bu engine tarafında çözmüyorsan
                # burada abbr doğrudan komutla gelmiyorsa, req.home/away zaten kısa ad ise çalışır.
                # Senin eski prod FAZ-13 sürümünde resolver ayrıydı.
                # Bu sürümde abbr yoksa baseline kaçabilir -> NO_PLAY.
                home_abbr = (req.home or "").strip().lower()
                away_abbr = (req.away or "").strip().lower()

                r = await espn.fetch_team_baseline(home_abbr)
                if r:
                    home_rows.append(r)
                r = await espn.fetch_team_baseline(away_abbr)
                if r:
                    away_rows.append(r)

                notes.append(f"ESPN team_key: home={home_abbr} away={away_abbr}")
            except Exception:
                notes.append("ESPN: fetch failed")

        home_base = aggregate_baseline(home_rows)
        away_base = aggregate_baseline(away_rows)

        if not home_base or not away_base:
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 1.0, 9),
                away_avg=TeamAverages(0, 0, 1.0, 9),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=notes + ["NO_PLAY: BASELINE_MISSING"],
                market={"status": "MISSING"},
                meta={
                    "season": season,
                    "season_str": season_str,
                    "baseline_missing": True,
                    "degraded_mode": True,
                },
            )

        # Pace fallback: pace yoksa default 100 (ama None değil)
        pace_home = float(home_base.get("pace") or 100.0)
        pace_away = float(away_base.get("pace") or 100.0)
        pace_mean = (pace_home + pace_away) / 2.0
        tempo_flag = self.tempo_flag_from_pace(pace_mean)

        # -------------------------
        # EXPECTED TOTAL
        # -------------------------
        h_pf = float(home_base["pts_for"])
        h_pa = float(home_base["pts_against"])
        a_pf = float(away_base["pts_for"])
        a_pa = float(away_base["pts_against"])

        home_mu = (h_pf + a_pa) / 2.0
        away_mu = (a_pf + h_pa) / 2.0
        expected_total = home_mu + away_mu

        total_band = (int(expected_total - profile.band_hw_total), int(expected_total + profile.band_hw_total))
        home_band = (int(home_mu - profile.band_hw_team), int(home_mu + profile.band_hw_team))
        away_band = (int(away_mu - profile.band_hw_team), int(away_mu + profile.band_hw_team))

        # -------------------------
        # CONFIDENCE (tight)
        # -------------------------
        conf_raw = min(float(home_base.get("confidence", 0.5)), float(away_base.get("confidence", 0.5)))
        conf_tight = self._tight_confidence(conf_raw)
        confidence_pct = round(conf_tight * 100.0, 1)

        # -------------------------
        # MARKET EDGE (FAZ-17)
        # -------------------------
        market: Dict[str, Any] = {}
        market_total: Optional[float] = None
        if self.faz17 is not None and MarketRequest is not None:
            try:
                m = await self.faz17.fetch_market_total(
                    MarketRequest(league=req.league, date_str=req.date_str, home=req.home, away=req.away)
                )
                if isinstance(m, dict):
                    market = m
                    if m.get("total") is not None:
                        market_total = float(m["total"])
                        notes.append(f"Market total={market_total:.1f}")
            except Exception:
                notes.append("FAZ-17: market fetch failed")

        ou_direction = "NO_EDGE"
        edge_value: Optional[float] = None
        edge_thr: Optional[float] = None

        if market_total is not None:
            edge_value = expected_total - market_total
            edge_thr = self._edge_threshold(conf_tight, profile.band_hw_total)
            if edge_value >= edge_thr:
                ou_direction = "ÜST"
            elif edge_value <= -edge_thr:
                ou_direction = "ALT"
            else:
                ou_direction = "NO_EDGE"
            notes.append(f"Edge={edge_value:+.1f} Thr={edge_thr:.1f}")

        # -------------------------
        # QUARTERS (tempo-aware)
        # -------------------------
        quarters = self._quarters_band(expected_total, profile.band_hw_total, tempo_flag)
        notes.append(f"Pace(mean)={pace_mean:.1f} Tempo={tempo_flag}")

        # Risk: daha sıkı confidence => daha az LOW
        if confidence_pct >= 82.0:
            risk = "LOW"
        elif confidence_pct >= 62.0:
            risk = "MEDIUM"
        else:
            risk = "HIGH"

        sources_home = home_base.get("sources", [])
        sources_away = away_base.get("sources", [])
        notes.append(f"Sources(home)={', '.join([str(x) for x in sources_home])}")
        notes.append(f"Sources(away)={', '.join([str(x) for x in sources_away])}")

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(h_pf, h_pa, pace_home, 10.0),
            away_avg=TeamAverages(a_pf, a_pa, pace_away, 10.0),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction=ou_direction,
            quarters=quarters,
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            notes=notes,
            market=market,
            meta={
                "season": season,               # API key
                "season_str": season_str,       # display
                "expected_total": round(expected_total, 3),
                "market_total": market_total,
                "edge_value": None if edge_value is None else round(edge_value, 3),
                "edge_threshold": edge_thr,
                "confidence_raw": round(conf_raw, 3),
                "confidence_tight": round(conf_tight, 3),
                "confidence_pct": confidence_pct,
                "risk": risk,
                "pace_home": round(pace_home, 3),
                "pace_away": round(pace_away, 3),
                "pace_mean": round(pace_mean, 3),
                "degraded_mode": False,
            },
        )
