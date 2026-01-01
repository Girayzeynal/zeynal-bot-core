from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore
from league_profiles import get_league_profile

# Optional aggregate import
try:
    from core.aggregate_engine import aggregate_baseline as _aggregate_baseline  # type: ignore
except Exception:
    _aggregate_baseline = None

# Optional ESPN provider
try:
    from providers import ESPNAdapter  # type: ignore
except Exception:
    ESPNAdapter = None  # type: ignore


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
                out.append(f"• {esc(str(k))}: {esc(str(v))}")

        if self.meta:
            out.append("")
            out.append("Meta Skor")
            for k, v in self.meta.items():
                out.append(f"• {esc(str(k))}: {esc(str(v))}")

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

    return {
        "pts_for": pts_for,
        "pts_against": pts_against,
        "confidence": total_conf / len(rows),
        "sources": [str(r.get("source")) for r in rows if r.get("source")],
    }


def aggregate_baseline(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if _aggregate_baseline:
        try:
            return _aggregate_baseline(rows)  # type: ignore
        except Exception:
            return _fallback_aggregate_baseline(rows)
    return _fallback_aggregate_baseline(rows)


# =====================================================
# PROVIDER: SportsDataIO (NBA)
# =====================================================

class SportsDataIOAdapter:
    name = "SPORTSDATAIO"
    confidence = 0.85

    def __init__(self) -> None:
        self.key = os.getenv("SPORTSDATA_API_KEY", "").strip()

    async def fetch_team_baseline(self, team_abbr: str, season_year: str) -> Optional[Dict[str, Any]]:
        if not self.key:
            return None

        abbr = (team_abbr or "").upper().strip()
        if not abbr:
            return None

        url = f"https://api.sportsdata.io/v3/nba/scores/json/TeamSeasonStats/{season_year}"
        headers = {"Ocp-Apim-Subscription-Key": self.key}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=20) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        row = next((x for x in data if str(x.get("Key", "")).upper() == abbr), None)
        if not row:
            return None

        pf = row.get("PointsPerGame")
        pa = row.get("OpponentPointsPerGame")
        if pf is None or pa is None:
            return None

        return {
            "pts_for": float(pf),
            "pts_against": float(pa),
            "confidence": float(self.confidence),
            "source": self.name,
        }


# =====================================================
# FAZ-13 ENGINE (CLEAN / STABLE)
# =====================================================

class Faz13Engine:
    """
    FINAL, STABLE FAZ-13
    - NO TeamBaselineBootstrapper
    - ESPN + SportsDataIO
    - Correct confidence & risk
    """

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

        # baseline_store is OPTIONAL, kept only for legacy compatibility
        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games)

        # CACHES
        self._teammap_cache: Dict[str, Dict[str, Any]] = {}
        self._teammap_ttl_sec = int(os.getenv("FAZ13_TEAMMAP_TTL_SEC", "21600"))
        self._nba_league_id = int(os.getenv("API_SPORTS_NBA_LEAGUE_ID", "12"))

        self._espn_alias_cache: Dict[str, Any] = {"ts": 0.0, "index": {}}
        self._espn_alias_ttl_sec = int(os.getenv("FAZ13_ESPN_ALIAS_TTL_SEC", "21600"))

    # -------------------------------------------------
    # NBA SEASON
    # -------------------------------------------------
    @staticmethod
    def resolve_nba_season(date_str: str) -> str:
        try:
            y = int(date_str[:4])
            m = int(date_str[5:7])
        except Exception:
            return date_str[:4]
        return str(y) if m >= 10 else str(y - 1)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    # -------------------------------------------------
    # ESPN ABBR RESOLVER
    # -------------------------------------------------
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
        async with s.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",
            timeout=20,
        ) as r:
            js = await r.json()

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

    # -------------------------------------------------
    # MAIN PREMATCH
    # -------------------------------------------------
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        season = self.resolve_nba_season(req.date_str) if req.league.upper() == "NBA" else req.date_str[:4]

        notes: List[str] = [f"Season: {season}", "TEAM-FIRST mode (MULTI-SOURCE)"]

        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []

        home_abbr = None
        away_abbr = None

        # ESPN
        if req.league.upper() == "NBA" and ESPNAdapter is not None:
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

        # SportsDataIO
        if req.league.upper() == "NBA":
            sd = SportsDataIOAdapter()
            if home_abbr:
                r = await sd.fetch_team_baseline(home_abbr.upper(), str(season))
                if r:
                    home_rows.append(r)
            if away_abbr:
                r = await sd.fetch_team_baseline(away_abbr.upper(), str(season))
                if r:
                    away_rows.append(r)

        home_baseline = aggregate_baseline(home_rows)
        away_baseline = aggregate_baseline(away_rows)

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
                meta={"risk": "NO_PLAY", "confidence_pct": 0.0},
            )

        h_pf = float(home_baseline["pts_for"])
        h_pa = float(home_baseline["pts_against"])
        a_pf = float(away_baseline["pts_for"])
        a_pa = float(away_baseline["pts_against"])

        home_mu = (h_pf + a_pa) / 2
        away_mu = (a_pf + h_pa) / 2
        total_mu = home_mu + away_mu

        total_band = (int(total_mu - profile.band_hw_total), int(total_mu + profile.band_hw_total))
        home_band = (int(home_mu - profile.band_hw_team), int(home_mu + profile.band_hw_team))
        away_band = (int(away_mu - profile.band_hw_team), int(away_mu + profile.band_hw_team))

        conf_raw = min(float(home_baseline["confidence"]), float(away_baseline["confidence"]))
        confidence_pct = round(conf_raw * 100.0, 1)

        if confidence_pct >= 75:
            risk = "LOW"
        elif confidence_pct >= 50:
            risk = "MEDIUM"
        else:
            risk = "HIGH"

        notes.append(f"Sources(home)={', '.join(home_baseline.get('sources', []))}")
        notes.append(f"Sources(away)={', '.join(away_baseline.get('sources', []))}")

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(h_pf, h_pa, 1.0, 10.0),
            away_avg=TeamAverages(a_pf, a_pa, 1.0, 10.0),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters={},
            blowout_risk="LOW",
            tempo_flag="NORMAL",
            notes=notes,
            market={},
            meta={
                "season": season,
                "team_first": True,
                "baseline_missing": False,
                "confidence_pct": confidence_pct,
                "risk": risk,
                "sources_home": home_baseline.get("sources", []),
                "sources_away": away_baseline.get("sources", []),
            },
    )
