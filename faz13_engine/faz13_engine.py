from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore
from league_profiles import get_league_profile

# Optional aggregate import (if core/aggregate_engine.py exists)
try:
    from core.aggregate_engine import aggregate_baseline as _aggregate_baseline  # type: ignore
except Exception:
    _aggregate_baseline = None

# Optional ESPN provider (providers/espn_adapter.py)
try:
    from providers import ESPNAdapter  # type: ignore
except Exception:
    ESPNAdapter = None  # type: ignore

# Optional FAZ-17 market engine (if exists)
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
        """
        IMPORTANT FIX:
        - If meta values are lists (e.g. sources), render them as comma-joined text
          to avoid HTML escaped list output like [&#x27;ESPN&#x27;].
        """
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

        if self.quarters:
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
# AGGREGATE (SAFE)
# =====================================================

def _fallback_aggregate_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None

    total_conf = sum(float(r.get("confidence", 0.0)) for r in rows)
    if total_conf <= 0:
        return None

    pts_for = sum(float(r["pts_for"]) * float(r["confidence"]) for r in rows) / total_conf
    pts_against = sum(float(r["pts_against"]) * float(r["confidence"]) for r in rows) / total_conf

    sources = []
    for r in rows:
        s = r.get("source")
        if s:
            sources.append(str(s))

    out: Dict[str, Any] = {
        "pts_for": pts_for,
        "pts_against": pts_against,
        "confidence": total_conf / len(rows),  # 0..1
        "sources": sources,
    }

    # Optional extras (pace etc.)
    pace_vals = [float(r["pace"]) for r in rows if r.get("pace") is not None]
    if pace_vals:
        out["pace"] = sum(pace_vals) / len(pace_vals)

    return out


def aggregate_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if _aggregate_baseline:
        try:
            return _aggregate_baseline(rows)  # type: ignore
        except Exception:
            return _fallback_aggregate_baseline(rows)
    return _fallback_aggregate_baseline(rows)


# =====================================================
# PROVIDER: SportsDataIO (NBA)
# Secret: SPORTSDATA_API_KEY
# Endpoint: /v3/nba/scores/json/TeamSeasonStats/{season_year}
# Match via row["Key"] == "BKN"/"LAC"/"UTAH"/etc (SportsDataIO team key)
# =====================================================

class SportsDataIOAdapter:
    name = "SPORTSDATAIO"
    confidence = 0.85

    def __init__(self) -> None:
        self.key = os.getenv("SPORTSDATA_API_KEY", "").strip()

    async def _fetch_teamseasonstats(self, season_year: str) -> Optional[List[Dict[str, Any]]]:
        """Tek noktadan TeamSeasonStats çek (baseline + pace aynı endpoint)."""
        if not self.key:
            return None

        url = f"https://api.sportsdata.io/v3/nba/scores/json/TeamSeasonStats/{season_year}"
        headers = {"Ocp-Apim-Subscription-Key": self.key}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=20) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if isinstance(data, list):
            return data
        return None

    async def fetch_team_baseline(self, team_key: str, season_year: str) -> Optional[Dict[str, Any]]:
        if not self.key:
            return None

        key = (team_key or "").upper().strip()
        if not key:
            return None

        data = await self._fetch_teamseasonstats(season_year)
        if not data:
            return None

        row = next((x for x in data if str(x.get("Key", "")).upper() == key), None)
        if not row:
            return None

        pf = row.get("PointsPerGame")
        pa = row.get("OpponentPointsPerGame")
        if pf is None or pa is None:
            return None

        out: Dict[str, Any] = {
            "pts_for": float(pf),
            "pts_against": float(pa),
            "confidence": float(self.confidence),
            "source": self.name,
        }

        # BONUS: pace (possessions per game) — gerçek veri alanları varsa ekle
        poss = row.get("Possessions")
        games = row.get("Games")
        try:
            if poss is not None and games is not None and float(games) > 0:
                out["pace"] = float(poss) / float(games)
        except Exception:
            pass

        return out

    async def fetch_team_pace(self, team_key: str, season_year: str) -> Optional[Dict[str, Any]]:
        """
        Gerçek PACE/POSSESSIONS (SportsDataIO TeamSeasonStats):
        pace = Possessions / Games
        """
        if not self.key:
            return None

        key = (team_key or "").upper().strip()
        if not key:
            return None

        data = await self._fetch_teamseasonstats(season_year)
        if not data:
            return None

        row = next((x for x in data if str(x.get("Key", "")).upper() == key), None)
        if not row:
            return None

        poss = row.get("Possessions")
        games = row.get("Games")
        if poss is None or games is None:
            return None

        try:
            poss_f = float(poss)
            games_i = int(games)
        except Exception:
            return None

        if games_i <= 0:
            return None

        pace = poss_f / games_i
        return {
            "pace": float(pace),
            "possessions": float(poss_f),
            "games": int(games_i),
            "source": self.name,
            "fetched_at": int(time.time()),
        }


# =====================================================
# FAZ-13 ENGINE (REF-BASED FINAL BUILD)
# - Preserves legacy output format
# - Adds: season label (2025-26), market edge (optional), quarter bands, tighter confidence
# - Fixes: pace None by multi-fallback (SDIO pace -> baseline pace -> safe default)
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

        self._nba_league_id = int(os.getenv("API_SPORTS_NBA_LEAGUE_ID", "12"))
        self._espn_alias_cache: Dict[str, Any] = {"ts": 0.0, "index": {}}
        self._espn_alias_ttl_sec = int(os.getenv("FAZ13_ESPN_ALIAS_TTL_SEC", "21600"))

        self._faz17 = Faz17Engine() if Faz17Engine is not None else None

    # -----------------------------
    # NBA season resolver
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
    def _season_label(season_start: str) -> str:
        # "2025" -> "2025-26"
        try:
            y = int(season_start)
            return f"{y}-{str((y + 1) % 100).zfill(2)}"
        except Exception:
            return season_start

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    # -----------------------------
    # ESPN alias resolver
    # -----------------------------
    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").strip().lower().replace("-", " ").replace("_", " ").split())

    async def _espn_resolve_abbr(self, team_name: str) -> Optional[str]:
        k = self._norm(team_name)
        if not k:
            return None

        now = time.time()
        if (now - float(self._espn_alias_cache.get("ts", 0))) < self._espn_alias_ttl_sec:
            idx = self._espn_alias_cache.get("index", {})
            if isinstance(idx, dict) and k in idx:
                return idx.get(k)

        s = await self._get_session()
        try:
            async with s.get(
                "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",
                timeout=20,
            ) as r:
                js = await r.json()
        except Exception:
            return None

        alias_index: Dict[str, str] = {}
        teams = js.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])

        for t in teams:
            team = t.get("team", {})
            abbr = str(team.get("abbreviation", "")).lower()
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
                key = self._norm(str(raw))
                if key:
                    alias_index.setdefault(key, abbr)

        self._espn_alias_cache = {"ts": now, "index": alias_index}
        return alias_index.get(k)

    @staticmethod
    def _tempo_flag_from_pace(pace: float) -> str:
        if pace >= 102.0:
            return "FAST"
        if pace <= 97.0:
            return "SLOW"
        return "NORMAL"

    @staticmethod
    def _tight_confidence(conf_raw: float) -> float:
        # daha seçici: orta bandı aşağı çeker
        c = max(0.0, min(1.0, float(conf_raw)))
        return c ** 1.35

    @staticmethod
    def _edge_threshold(conf_tight: float, band_hw_total: int) -> float:
        base = max(2.0, float(band_hw_total) * 0.30)
        # düşük conf => daha yüksek eşik
        factor = 1.25 - 0.40 * max(0.0, min(1.0, conf_tight))
        return base * factor

    @staticmethod
    def _quarters_band(total_mu: float, band_hw_total: int, tempo_flag: str) -> Dict[str, Tuple[int, int]]:
        # deterministik split + tempo
        w = [0.24, 0.26, 0.25, 0.25]
        if tempo_flag == "FAST":
            w = [0.245, 0.265, 0.245, 0.245]
        elif tempo_flag == "SLOW":
            w = [0.235, 0.255, 0.255, 0.255]

        q_hw = max(2, int(round(band_hw_total / 2.8)))
        qs: Dict[str, Tuple[int, int]] = {}
        for lab, wi in zip(("1Q", "2Q", "3Q", "4Q"), w):
            mu = total_mu * wi
            qs[lab] = (int(mu - q_hw), int(mu + q_hw))
        return qs

    # -----------------------------
    # MAIN
    # -----------------------------
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        season = self.resolve_nba_season(req.date_str) if req.league.upper() == "NBA" else req.date_str[:4]
        season_label = self._season_label(season) if req.league.upper() == "NBA" else season

        notes: List[str] = [f"Season: {season_label}", "TEAM-FIRST mode (MULTI-SOURCE)"]

        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []

        home_abbr: Optional[str] = None
        away_abbr: Optional[str] = None

        # 1) ESPN baseline
        if req.league.upper() == "NBA" and ESPNAdapter is not None:
            try:
                espn = ESPNAdapter()
                home_abbr = await self._espn_resolve_abbr(req.home)
                away_abbr = await self._espn_resolve_abbr(req.away)

                if home_abbr:
                    r = await espn.fetch_team_baseline(home_abbr)  # type: ignore
                    if r:
                        home_rows.append(r)

                if away_abbr:
                    r = await espn.fetch_team_baseline(away_abbr)  # type: ignore
                    if r:
                        away_rows.append(r)

                notes.append(f"ESPN abbr: home={home_abbr} away={away_abbr}")
            except Exception:
                notes.append("ESPN: fetch failed")

        # 2) SportsDataIO baseline + pace
        pace_home: Optional[float] = None
        pace_away: Optional[float] = None

        if req.league.upper() == "NBA":
            sd = SportsDataIOAdapter()
            if home_abbr:
                r = await sd.fetch_team_baseline(home_abbr.upper(), str(season))
                if r:
                    home_rows.append(r)
                p = await sd.fetch_team_pace(home_abbr.upper(), str(season))
                if p and p.get("pace") is not None:
                    pace_home = float(p["pace"])
            if away_abbr:
                r = await sd.fetch_team_baseline(away_abbr.upper(), str(season))
                if r:
                    away_rows.append(r)
                p = await sd.fetch_team_pace(away_abbr.upper(), str(season))
                if p and p.get("pace") is not None:
                    pace_away = float(p["pace"])

        home_baseline = aggregate_baseline(home_rows) if home_rows else None
        away_baseline = aggregate_baseline(away_rows) if away_rows else None

        if not home_baseline or not away_baseline:
            ctx = FixtureContext(req.league, req.date_str, req.home, req.away)
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
                notes=notes + ["NO_PLAY: BASELINE_NOT_AVAILABLE"],
                market={},
                meta={
                    "season": season,
                    "season_str": season_label,
                    "team_first": True,
                    "baseline_missing": True,
                    "confidence_pct": 0.0,
                    "risk": "NO_PLAY",
                    "sources_home": [],
                    "sources_away": [],
                    "degraded_mode": True,
                },
            )

        # Fallback chain for pace (fixes pace None)
        if pace_home is None:
            try:
                v = home_baseline.get("pace")
                if v is not None:
                    pace_home = float(v)
            except Exception:
                pace_home = None
        if pace_away is None:
            try:
                v = away_baseline.get("pace")
                if v is not None:
                    pace_away = float(v)
            except Exception:
                pace_away = None

        pace_fallback_used = False
        if pace_home is None:
            pace_home = 100.0
            pace_fallback_used = True
        if pace_away is None:
            pace_away = 100.0
            pace_fallback_used = True

        if pace_fallback_used:
            notes.append("Pace missing from providers → fallback pace=100.0 applied")

        notes.append(f"Pace(home)={pace_home:.1f} | Pace(away)={pace_away:.1f}")

        # FAZ-13 math
        h_pf = float(home_baseline["pts_for"])
        h_pa = float(home_baseline["pts_against"])
        a_pf = float(away_baseline["pts_for"])
        a_pa = float(away_baseline["pts_against"])

        home_mu = (h_pf + a_pa) / 2.0
        away_mu = (a_pf + h_pa) / 2.0
        expected_total = home_mu + away_mu

        total_band = (int(expected_total - profile.band_hw_total), int(expected_total + profile.band_hw_total))
        home_band = (int(home_mu - profile.band_hw_team), int(home_mu + profile.band_hw_team))
        away_band = (int(away_mu - profile.band_hw_team), int(away_mu + profile.band_hw_team))

        # tighter confidence
        conf_raw = min(float(home_baseline.get("confidence", 0.5)), float(away_baseline.get("confidence", 0.5)))
        conf_tight = self._tight_confidence(conf_raw)
        confidence_pct = round(conf_tight * 100.0, 1)

        # risk (legacy semantics)
        if confidence_pct >= 82.0:
            risk = "LOW"
        elif confidence_pct >= 62.0:
            risk = "MEDIUM"
        else:
            risk = "HIGH"

        sources_home = home_baseline.get("sources", [])
        sources_away = away_baseline.get("sources", [])

        notes.append(f"Sources(home)={', '.join(sources_home)}")
        notes.append(f"Sources(away)={', '.join(sources_away)}")

        # tempo flag + quarters
        pace_mean = (pace_home + pace_away) / 2.0
        tempo_flag = self._tempo_flag_from_pace(pace_mean)
        quarters = self._quarters_band(expected_total, profile.band_hw_total, tempo_flag)

        # market edge (optional)
        market: Dict[str, Any] = {}
        market_total: Optional[float] = None
        edge_value: Optional[float] = None
        edge_thr: Optional[float] = None

        if self._faz17 is not None and MarketRequest is not None:
            try:
                m = await self._faz17.fetch_market_total(
                    MarketRequest(league=req.league, date_str=req.date_str, home=req.home, away=req.away)
                )
                if isinstance(m, dict):
                    market = m
                    if m.get("total") is not None:
                        market_total = float(m["total"])
            except Exception:
                market = {"status": "MARKET_OPTIONAL", "reason": "FAZ17_EXCEPTION"}

        ou_direction = "NO_EDGE"
        if market_total is not None:
            edge_value = expected_total - market_total
            edge_thr = self._edge_threshold(conf_tight, profile.band_hw_total)
            if edge_value >= edge_thr:
                ou_direction = "ÜST"
            elif edge_value <= -edge_thr:
                ou_direction = "ALT"
            else:
                ou_direction = "NO_EDGE"
            notes.append(f"Market total={market_total:.1f} | Edge={edge_value:+.1f} | Thr={edge_thr:.1f}")
        else:
            if not market:
                market = {"status": "MARKET_OPTIONAL"}

        # degraded mode signal (for your higher layer)
        data_coverage = {
            "team_stats": True,
            "pace": True,
            "market": market_total is not None,
        }
        degraded_mode = not (data_coverage["team_stats"] and data_coverage["pace"] and data_coverage["market"])

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(h_pf, h_pa, float(pace_home), 10.0),
            away_avg=TeamAverages(a_pf, a_pa, float(pace_away), 10.0),
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
                "season": season,
                "season_str": season_label,
                "team_first": True,
                "baseline_missing": False,
                "confidence_pct": confidence_pct,
                "confidence_raw": round(conf_raw, 3),
                "confidence_tight": round(conf_tight, 3),
                "risk": risk,
                "sources_home": sources_home,
                "sources_away": sources_away,
                "pace_home": pace_home,
                "pace_away": pace_away,
                "pace_mean": pace_mean,
                "tempo_flag": tempo_flag,
                "expected_total": round(expected_total, 3),
                "market_total": market_total,
                "edge_value": None if edge_value is None else round(edge_value, 3),
                "edge_threshold": edge_thr,
                "degraded_mode": degraded_mode,
                "data_coverage": data_coverage,
                "fetched_at": int(time.time()),
            },
        )
