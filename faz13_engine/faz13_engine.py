from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from league_profiles import get_league_profile

from core.aggregate_engine import aggregate_baseline
from faz17_engine.faz17_engine import Faz17Engine, MarketRequest
from providers.espn_adapter import ESPNAdapter
from providers.sportsdataio_adapter import SportsDataIOAdapter


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
# ENGINE
# =====================================================

class Faz13Engine:
    """
    FAZ-13 (PROD UYUMLU)
    - ESPN + SportsDataIO baseline
    - Market (FAZ-17) OPTIONAL (senin çıktın böyle)
    - DEGRADED_MODE sadece veri eksikse True
    - Team abbr resolver engine içinde (ESPNAdapter’da _espn_resolve_abbr olmasına gerek yok)
    """

    def __init__(
        self,
        api_sports_key: Optional[str] = None,
        api_sports_base: Optional[str] = None,
        baseline_store: Optional[Any] = None,
        min_baseline_games: int = 6,
    ) -> None:
        self.api_sports_key = api_sports_key
        self.api_sports_base = api_sports_base
        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games)

        self.espn = ESPNAdapter()
        self.sd = SportsDataIOAdapter()
        self.faz17 = Faz17Engine()

        # ESPN team directory cache (engine-level)
        self._teamdir_cache: Dict[str, Any] = {"ts": 0.0, "index": {}}
        self._teamdir_ttl = int(21600)  # 6 saat

    # -----------------------------
    # NBA season (API key) + display label
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
    def season_label(season_start: str) -> str:
        # 2025 -> 2025-2026 (senin istediğin)
        try:
            y = int(season_start)
            return f"{y}-{y+1}"
        except Exception:
            return season_start

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").strip().lower().replace("-", " ").replace("_", " ").split())

    async def _ensure_team_index(self) -> Dict[str, str]:
        now = time.time()
        if (now - float(self._teamdir_cache.get("ts", 0.0))) < self._teamdir_ttl:
            idx = self._teamdir_cache.get("index", {})
            if isinstance(idx, dict) and idx:
                return idx

        # ESPNAdapter zaten request_json yapıyor; onu kullanmadan direkt onun teams endpointini çağıran fonksiyon yok.
        # Bu yüzden ESPNAdapter'ın teams endpointini onun cache'li _request_json üzerinden kullanıyoruz.
        # (private method ama aynı process içinde en stabil çözüm)
        try:
            js = await self.espn._request_json("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams")  # type: ignore
        except Exception:
            js = None

        idx: Dict[str, str] = {}
        if js:
            teams = js.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
            for t in teams:
                team = (t or {}).get("team") or {}
                abbr = str(team.get("abbreviation", "") or "").lower().strip()
                if not abbr:
                    continue
                for raw in (
                    team.get("displayName"),
                    team.get("shortDisplayName"),
                    team.get("name"),
                    team.get("location"),
                    team.get("nickname"),
                    abbr,
                ):
                    k = self._norm(str(raw))
                    if k and k not in idx:
                        idx[k] = abbr

        self._teamdir_cache = {"ts": now, "index": idx}
        return idx

    async def _resolve_abbr(self, team_name: str) -> Optional[str]:
        k = self._norm(team_name)
        if not k:
            return None
        idx = await self._ensure_team_index()
        return idx.get(k)

    # -----------------------------
    # Confidence / risk helpers (prod style)
    # -----------------------------
    @staticmethod
    def _risk_label(confidence_pct: float) -> str:
        # eski çıktınla uyumlu: 60% => LOW değil, MEDIUM olmalı
        if confidence_pct >= 75:
            return "LOW"
        if confidence_pct >= 50:
            return "MEDIUM"
        return "HIGH"

    @staticmethod
    def _tempo_flag(pace_mean: Optional[float]) -> str:
        if pace_mean is None:
            return "UNKNOWN"
        if pace_mean >= 102:
            return "FAST"
        if pace_mean <= 97:
            return "SLOW"
        return "NORMAL"

    # -----------------------------
    # MAIN
    # -----------------------------
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        season = self.resolve_nba_season(req.date_str) if req.league.upper() == "NBA" else req.date_str[:4]
        season_str = self.season_label(season) if req.league.upper() == "NBA" else season

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        fetched_at = int(time.time())
        data_coverage = {
            "team_stats": False,
            "injuries": False,
            "roster": False,
            "pace": False,
            "market": False,
        }
        missing_fields: List[str] = []
        notes: List[str] = [f"Season: {season_str}", "TEAM-FIRST mode (MULTI-SOURCE)"]

        # -------------------------
        # MARKET (OPTIONAL - senin çıktın)
        # -------------------------
        market: Dict[str, Any] = {"status": "MARKET_OPTIONAL", "reason": None}
        market_total: Optional[float] = None
        t0 = time.time()
        try:
            m = await self.faz17.fetch_market_total(
                MarketRequest(league=req.league, date_str=req.date_str, home=req.home, away=req.away)
            )
            if isinstance(m, dict):
                market.update(m)
                if m.get("total") is not None:
                    market_total = float(m["total"])
                    data_coverage["market"] = True
            market["latency_ms"] = int((time.time() - t0) * 1000)
        except Exception as e:
            market["reason"] = f"FAZ17_EXCEPTION: {e}"

        # -------------------------
        # TEAM KEYS (ABBR)
        # -------------------------
        home_abbr = await self._resolve_abbr(req.home)
        away_abbr = await self._resolve_abbr(req.away)
        notes.append(f"ESPN abbr: home={home_abbr} away={away_abbr}")

        if not home_abbr:
            missing_fields.append("home_team_key")
        if not away_abbr:
            missing_fields.append("away_team_key")

        # -------------------------
        # BASELINES (ESPN + SDIO)
        # -------------------------
        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []

        if home_abbr:
            r = await self.espn.fetch_team_baseline(home_abbr)
            if r:
                home_rows.append(r)
        if away_abbr:
            r = await self.espn.fetch_team_baseline(away_abbr)
            if r:
                away_rows.append(r)

        if home_abbr:
            r = await self.sd.fetch_team_baseline(home_abbr.upper(), str(season))
            if r:
                home_rows.append(r)
        if away_abbr:
            r = await self.sd.fetch_team_baseline(away_abbr.upper(), str(season))
            if r:
                away_rows.append(r)

        home_base = aggregate_baseline(home_rows) if home_rows else None
        away_base = aggregate_baseline(away_rows) if away_rows else None

        if not home_base:
            missing_fields.append("home_team_stats")
        if not away_base:
            missing_fields.append("away_team_stats")

        if home_base and away_base:
            data_coverage["team_stats"] = True
            notes.append(f"Sources(home)={', '.join(home_base.get('sources', []))}")
            notes.append(f"Sources(away)={', '.join(away_base.get('sources', []))}")

        # -------------------------
        # PACE (SportsDataIO TeamSeasonStats -> Possessions/Games)
        # -------------------------
        pace_home = None
        pace_away = None
        try:
            if home_abbr:
                p = await self.sd.fetch_team_pace(home_abbr.upper(), str(season))  # type: ignore
                if p and p.get("pace") is not None:
                    pace_home = float(p["pace"])
            if away_abbr:
                p = await self.sd.fetch_team_pace(away_abbr.upper(), str(season))  # type: ignore
                if p and p.get("pace") is not None:
                    pace_away = float(p["pace"])
            if pace_home is not None and pace_away is not None:
                data_coverage["pace"] = True
                notes.append(f"Pace(home)={pace_home:.1f} | Pace(away)={pace_away:.1f}")
        except Exception:
            # pace yoksa sadece coverage false kalır
            pass

        # -------------------------
        # INJURIES (both providers)
        # -------------------------
        inj_sources_home: List[str] = []
        inj_sources_away: List[str] = []

        sd_inj_home = await self.sd.fetch_team_injuries(home_abbr.upper()) if home_abbr else None
        sd_inj_away = await self.sd.fetch_team_injuries(away_abbr.upper()) if away_abbr else None
        if sd_inj_home is not None:
            inj_sources_home.append("SPORTSDATAIO")
        if sd_inj_away is not None:
            inj_sources_away.append("SPORTSDATAIO")

        espn_inj_home = await self.espn.fetch_team_injuries(home_abbr) if home_abbr else None
        espn_inj_away = await self.espn.fetch_team_injuries(away_abbr) if away_abbr else None
        if espn_inj_home is not None:
            inj_sources_home.append("ESPN")
        if espn_inj_away is not None:
            inj_sources_away.append("ESPN")

        if inj_sources_home and inj_sources_away:
            data_coverage["injuries"] = True
        else:
            if not inj_sources_home:
                missing_fields.append("home_injury_data")
            if not inj_sources_away:
                missing_fields.append("away_injury_data")

        # roster proxy (injury_count) => roster coverage
        try:
            if home_abbr and away_abbr:
                rh = await self.espn.fetch_rotation_proxy(home_abbr)  # type: ignore
                ra = await self.espn.fetch_rotation_proxy(away_abbr)  # type: ignore
                if rh and ra:
                    data_coverage["roster"] = True
        except Exception:
            pass

        # -------------------------
        # DEGRADED MODE
        # -------------------------
        degraded_mode = False
        # senin çıktın: team_stats/pace/roster/market eksikse degraded
        for k in ("team_stats", "pace", "roster", "market"):
            if not data_coverage.get(k, False):
                degraded_mode = True
                break

        # Eğer baseline yoksa NO_PLAY (ama market olsa bile)
        if not home_base or not away_base:
            return Faz13CoreOutput(
                ctx=ctx,
                home_avg=TeamAverages(0, 0, 1, 9),
                away_avg=TeamAverages(0, 0, 1, 9),
                total_band=(0, 0),
                home_band=(0, 0),
                away_band=(0, 0),
                ou_direction="NO_PLAY",
                quarters={},
                blowout_risk="UNKNOWN",
                tempo_flag="UNKNOWN",
                notes=notes + ["NO_PLAY: BASELINE_MISSING"],
                market=market,
                meta={
                    "season": season,
                    "season_str": season_str,
                    "baseline_missing": True,
                    "degraded_mode": True,
                    "confidence": 10.0,
                    "fetched_at": fetched_at,
                    "data_coverage": data_coverage,
                    "missing_fields": missing_fields,
                    "sources_inj_home": inj_sources_home,
                    "sources_inj_away": inj_sources_away,
                },
            )

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

        conf_raw = min(float(home_base.get("confidence", 0.6)), float(away_base.get("confidence", 0.6)))
        confidence_pct = round(conf_raw * 100.0, 1)
        risk = self._risk_label(confidence_pct)

        # tempo
        pace_mean = (pace_home + pace_away) / 2.0 if (pace_home is not None and pace_away is not None) else None
        tempo_flag = self._tempo_flag(pace_mean)

        # Edge (aktif et ama market varsa)
        ou_direction = "NO_EDGE"
        edge_value = None
        if market_total is not None:
            edge_value = expected_total - market_total
            # daha basit eşik: band halfwidth’in %30’u
            thr = max(2.0, float(profile.band_hw_total) * 0.30)
            if edge_value >= thr:
                ou_direction = "ÜST"
            elif edge_value <= -thr:
                ou_direction = "ALT"
            else:
                ou_direction = "NO_EDGE"

        if degraded_mode:
            notes.append("⚠️ DEGRADED_MODE: Kaynak veriler eksik (team_stats/pace/roster/market). Analiz fallback ile üretildi.")

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(h_pf, h_pa, float(pace_home or 1.0), 10.0),
            away_avg=TeamAverages(a_pf, a_pa, float(pace_away or 1.0), 10.0),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction=ou_direction,
            quarters={},  # eski çıktın periyot basmıyordu; burada dokunmuyoruz
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            notes=notes,
            market=market,
            meta={
                "season": season,                 # API season key
                "season_str": season_str,         # 2025-2026
                "team_first": True,
                "baseline_missing": False,
                "confidence_pct": confidence_pct,
                "confidence_raw": round(conf_raw, 3),
                "risk": risk,
                "sources_home": ", ".join(home_base.get("sources", [])),
                "sources_away": ", ".join(away_base.get("sources", [])),
                "pace_home": pace_home,
                "pace_away": pace_away,
                "pace_mean": pace_mean,
                "market_total": market_total,
                "edge_value": edge_value,
                "degraded_mode": degraded_mode,
                "fetched_at": fetched_at,
                "data_coverage": data_coverage,
                "missing_fields": missing_fields,
                "sources_inj_home": inj_sources_home,
                "sources_inj_away": inj_sources_away,
            },
        )
