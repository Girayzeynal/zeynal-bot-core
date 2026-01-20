from __future__ import annotations

import asyncio
import html
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore
from league_profiles import get_league_profile

# Optional ESPN provider (repo varsa otomatik)
try:
    from providers.espn_adapter import ESPNAdapter  # type: ignore
except Exception:
    ESPNAdapter = None  # type: ignore


# =====================================================
# NBA TEAM CANONICAL (API-Sports search uyumu)
# =====================================================

NBA_TEAM_CANONICAL: Dict[str, str] = {
    "atlanta hawks": "Hawks",
    "boston celtics": "Celtics",
    "brooklyn nets": "Nets",
    "charlotte hornets": "Hornets",
    "chicago bulls": "Bulls",
    "cleveland cavaliers": "Cavaliers",
    "dallas mavericks": "Mavericks",
    "denver nuggets": "Nuggets",
    "detroit pistons": "Pistons",
    "golden state warriors": "Warriors",
    "houston rockets": "Rockets",
    "indiana pacers": "Pacers",
    "los angeles clippers": "Clippers",
    "los angeles lakers": "Lakers",
    "memphis grizzlies": "Grizzlies",
    "miami heat": "Heat",
    "milwaukee bucks": "Bucks",
    "minnesota timberwolves": "Timberwolves",
    "new orleans pelicans": "Pelicans",
    "new york knicks": "Knicks",
    "oklahoma city thunder": "Thunder",
    "orlando magic": "Magic",
    "philadelphia 76ers": "76ers",
    "phoenix suns": "Suns",
    "portland trail blazers": "Blazers",
    "sacramento kings": "Kings",
    "san antonio spurs": "Spurs",
    "toronto raptors": "Raptors",
    "utah jazz": "Jazz",
    "washington wizards": "Wizards",
}

# ESPN için (abbr)
NBA_TEAM_ABBR: Dict[str, str] = {
    "atlanta hawks": "ATL",
    "boston celtics": "BOS",
    "brooklyn nets": "BKN",
    "charlotte hornets": "CHA",
    "chicago bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",
    "denver nuggets": "DEN",
    "detroit pistons": "DET",
    "golden state warriors": "GSW",
    "houston rockets": "HOU",
    "indiana pacers": "IND",
    "los angeles clippers": "LAC",
    "los angeles lakers": "LAL",
    "memphis grizzlies": "MEM",
    "miami heat": "MIA",
    "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NOP",
    "new york knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX",
    "portland trail blazers": "POR",
    "sacramento kings": "SAC",
    "san antonio spurs": "SAS",
    "toronto raptors": "TOR",
    "utah jazz": "UTA",
    "washington wizards": "WAS",
}


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

        if self.quarters:
            out.append("")
            out.append("Periyot Bantları")
            for k in ("1Q", "2Q", "HT", "3Q", "4Q", "FT"):
                if k in self.quarters:
                    lo, hi = self.quarters[k]
                    out.append(f"• {k}: {lo}–{hi}")

        out.append("")
        out.append("Risk Göstergeleri")
        out.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        out.append(f"• Tempo flag: {esc(self.tempo_flag)}")

        if self.notes:
            out.append("")
            out.append("Notlar")
            for n in self.notes:
                out.append(f"• {esc(str(n))}")

        if self.meta:
            out.append("")
            out.append("Meta Skor")
            for k, v in self.meta.items():
                out.append(f"• {esc(str(k))}: {esc(str(v))}")

        out.append("")
        out.append("Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.")
        return "\n".join(out)


# =====================================================
# HELPERS
# =====================================================

class _TTLCache:
    def __init__(self, ttl_sec: float = 20.0) -> None:
        self.ttl = float(ttl_sec)
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        hit = self._data.get(key)
        if not hit:
            return None
        ts, val = hit
        if (time.time() - ts) > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)


def _league_avg_baseline(league: str) -> Dict[str, Any]:
    # “Asla 0–0 olmasın” son çare
    if (league or "").upper() == "NBA":
        return {"pts_for": 113.5, "pts_against": 113.5, "pace": 99.5, "stdev": 10.0}
    return {"pts_for": 80.0, "pts_against": 80.0, "pace": 95.0, "stdev": 9.0}


def _tempo_flag_from_pace(pace: float) -> str:
    if pace >= 102.0:
        return "FAST"
    if pace <= 97.0:
        return "SLOW"
    return "NORMAL"


def _quarters_band(total_mu: float, band_hw_total: int, tempo_flag: str) -> Dict[str, Tuple[int, int]]:
    # FT bantı total_band ile aynı, HT ise 1Q+2Q ağırlıklı
    w = [0.24, 0.26, 0.25, 0.25]
    if tempo_flag == "FAST":
        w = [0.245, 0.265, 0.245, 0.245]
    elif tempo_flag == "SLOW":
        w = [0.235, 0.255, 0.255, 0.255]

    q_hw = max(2, int(round(band_hw_total / 2.8)))
    q: Dict[str, Tuple[int, int]] = {}
    q1 = total_mu * w[0]
    q2 = total_mu * w[1]
    q3 = total_mu * w[2]
    q4 = total_mu * w[3]
    q["1Q"] = (int(q1 - q_hw), int(q1 + q_hw))
    q["2Q"] = (int(q2 - q_hw), int(q2 + q_hw))
    q["3Q"] = (int(q3 - q_hw), int(q3 + q_hw))
    q["4Q"] = (int(q4 - q_hw), int(q4 + q_hw))

    ht_mu = q1 + q2
    ht_hw = max(2, int(round(q_hw * 1.4)))
    q["HT"] = (int(ht_mu - ht_hw), int(ht_mu + ht_hw))

    ft_mu = total_mu
    ft_hw = int(band_hw_total)
    q["FT"] = (int(ft_mu - ft_hw), int(ft_mu + ft_hw))
    return q


# =====================================================
# ENGINE
# =====================================================

class Faz13Engine:
    """
    FAZ-13 FINAL BUILD
    - main.py uyumlu __init__(api_sports_key, api_sports_base, baseline_store, ...)
    - API-Sports + baseline_store + ESPN_LAST5 + league_avg fallback
    - ESPN çağrıları timeout'lu: handler kilitlenmez
    """

    def __init__(
        self,
        api_sports_key: str,
        api_sports_base: str,
        baseline_store: Optional[TeamBaselineStore] = None,
        min_baseline_games: int = 6,
        **kwargs: Any,
    ) -> None:
        self.api_key = (api_sports_key or "").strip()
        self.base = (api_sports_base or "https://v1.basketball.api-sports.io").rstrip("/")
        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games) if min_baseline_games else 6

        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = _TTLCache(ttl_sec=float(os.getenv("FAZ13_CACHE_TTL_SEC", "18")))

        self.espn = ESPNAdapter() if ESPNAdapter is not None else None
        self.espn_timeout_sec = float(os.getenv("FAZ13_ESPN_TIMEOUT_SEC", "2.0"))

        # opsiyonel; ileride kullanılır
        self.extra_args = kwargs

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
        return self.session

    async def aclose(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    # -------------------------
    # NBA season fix
    # -------------------------
    def _season_for_league(self, league: str, date_str: str) -> str:
        """
        NBA season:
        - Oct-Dec => season = year
        - Jan-Sep => season = year-1
        """
        try:
            y = int(str(date_str)[:4])
            m = int(str(date_str)[5:7])
        except Exception:
            return str(date_str)[:4]
        if (league or "").upper() == "NBA":
            return str(y if m >= 10 else (y - 1))
        return str(y)

    # -------------------------
    # API-Sports helpers
    # -------------------------
    async def _api_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        key = f"{path}:{str(sorted(params.items()))}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        if not self.api_key:
            raise RuntimeError("API_SPORTS_KEY_MISSING")

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}

        backoff = 0.4
        for _ in range(4):
            try:
                async with s.get(
                    f"{self.base}{path}",
                    params=params,
                    headers=headers,
                    timeout=15,
                ) as resp:
                    js = await resp.json()
                    if resp.status >= 500:
                        raise RuntimeError(f"API_SPORTS_{resp.status}")
                    self.cache.set(key, js)
                    return js
            except Exception:
                await asyncio.sleep(backoff)
                backoff *= 1.7

        raise RuntimeError("API_SPORTS_REQUEST_FAILED")

    async def _api_sports_team_baseline(
        self, league: str, team_name: str, season: str
    ) -> Optional[Dict[str, Any]]:
        """
        Dönen: {pts_for, pts_against, pace, stdev, source, n_games}
        """
        if not self.api_key:
            return None

        search_name = team_name
        if (league or "").upper() == "NBA":
            search_name = NBA_TEAM_CANONICAL.get(team_name.lower().strip(), team_name)

        try:
            teams = await self._api_get("/teams", {"search": search_name})
        except Exception:
            return None

        resp = teams.get("response") if isinstance(teams, dict) else None
        if not isinstance(resp, list) or not resp:
            return None

        team_id = resp[0].get("id")
        if not team_id:
            return None

        try:
            stats = await self._api_get("/statistics", {"team": team_id, "season": season})
        except Exception:
            return None

        sresp = stats.get("response") if isinstance(stats, dict) else None
        if not isinstance(sresp, dict):
            return None

        pf = (
            sresp.get("points", {})
            .get("for", {})
            .get("average", {})
            .get("total")
        )
        pa = (
            sresp.get("points", {})
            .get("against", {})
            .get("average", {})
            .get("total")
        )
        if pf is None or pa is None:
            return None

        profile = get_league_profile(league)
        total = float(pf) + float(pa)

        # pace_hint: kaba normalize (API-Sports possession vermez)
        pace = max(94.0, min(106.0, 99.5 + (total - 220.0) * 0.06))
        stdev = max(profile.volatility_floor, min(profile.volatility_ceil, 10.0))

        return {
            "pts_for": float(pf),
            "pts_against": float(pa),
            "pace": float(pace),
            "stdev": float(stdev),
            "source": "API_SPORTS_STATISTICS",
            "n_games": 12,
        }

    # -------------------------
    # ESPN baseline (non-blocking)
    # -------------------------
    async def _espn_last5_baseline(self, league: str, team_name: str) -> Optional[Dict[str, Any]]:
        if (league or "").upper() != "NBA":
            return None
        if self.espn is None:
            return None

        abbr = NBA_TEAM_ABBR.get(team_name.lower().strip())
        if not abbr:
            return None

        try:
            games = await asyncio.wait_for(
                self.espn.fetch_team_recent_games("NBA", abbr, 5),
                timeout=self.espn_timeout_sec,
            )
        except Exception:
            return None

        if not games:
            return None

        pf = sum(float(g.get("pts_for", 0.0)) for g in games) / len(games)
        pa = sum(float(g.get("pts_against", 0.0)) for g in games) / len(games)
        pace = sum(float(g.get("pace", 99.5)) for g in games) / len(games)
        return {
            "pts_for": float(pf),
            "pts_against": float(pa),
            "pace": float(pace),
            "stdev": 10.0,
            "source": "ESPN_LAST5",
            "n_games": int(len(games)),
        }

    # -------------------------
    # Baseline store fallback (SENİN İSTEDİĞİN BLOK)
    # -------------------------
    def _baseline_store_rows(self, league: str, home: str, away: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        home_rows: List[Dict[str, Any]] = []
        away_rows: List[Dict[str, Any]] = []
        if not self.baseline_store:
            return home_rows, away_rows

        try:
            h = self.baseline_store.get(league, home)
            a = self.baseline_store.get(league, away)

            if h:
                home_rows.append(
                    {
                        "pts_for": h.pts_for,
                        "pts_against": h.pts_against,
                        "confidence": 0.75,
                        "source": "BASELINE_STORE",
                        "pace": h.pace,
                        "stdev": h.stdev_total,
                        "n_games": h.n_games,
                    }
                )
            if a:
                away_rows.append(
                    {
                        "pts_for": a.pts_for,
                        "pts_against": a.pts_against,
                        "confidence": 0.75,
                        "source": "BASELINE_STORE",
                        "pace": a.pace,
                        "stdev": a.stdev_total,
                        "n_games": a.n_games,
                    }
                )
        except Exception:
            # sessiz geç
            pass

        return home_rows, away_rows

    # -------------------------
    # Weighted aggregate
    # -------------------------
    def _aggregate(self, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not rows:
            return None
        conf_sum = 0.0
        pf_sum = 0.0
        pa_sum = 0.0
        pace_vals: List[float] = []
        stdev_vals: List[float] = []
        sources: List[str] = []
        n_games: Optional[int] = None

        for r in rows:
            c = float(r.get("confidence", 0.0))
            if c <= 0:
                continue
            conf_sum += c
            pf_sum += float(r["pts_for"]) * c
            pa_sum += float(r["pts_against"]) * c

            if r.get("pace") is not None:
                pace_vals.append(float(r["pace"]))
            if r.get("stdev") is not None:
                stdev_vals.append(float(r["stdev"]))

            s = r.get("source")
            if s:
                sources.append(str(s))

            # n_games: maksimumu taşı
            ng = r.get("n_games")
            if isinstance(ng, int):
                n_games = ng if n_games is None else max(n_games, ng)

        if conf_sum <= 0:
            return None

        out: Dict[str, Any] = {
            "pts_for": pf_sum / conf_sum,
            "pts_against": pa_sum / conf_sum,
            "confidence": min(1.0, conf_sum / max(1, len(rows))),
            "sources": sources,
            "n_games": n_games,
        }
        if pace_vals:
            out["pace"] = sum(pace_vals) / len(pace_vals)
        if stdev_vals:
            out["stdev"] = sum(stdev_vals) / len(stdev_vals)
        return out

    # -------------------------
    # MAIN
    # -------------------------
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        season = self._season_for_league(req.league, req.date_str)

        notes: List[str] = [f"Season: {season}", "TEAM-FIRST mode (MULTI-SOURCE)"]

        # 1) baseline_store rows
        home_rows, away_rows = self._baseline_store_rows(req.league, req.home, req.away)

        # 2) ESPN last5 rows (non-blocking)
        espn_h = await self._espn_last5_baseline(req.league, req.home)
        if espn_h:
            home_rows.append(
                {
                    "pts_for": espn_h["pts_for"],
                    "pts_against": espn_h["pts_against"],
                    "confidence": 0.65,
                    "source": espn_h["source"],
                    "pace": espn_h["pace"],
                    "stdev": espn_h["stdev"],
                    "n_games": espn_h["n_games"],
                }
            )
        espn_a = await self._espn_last5_baseline(req.league, req.away)
        if espn_a:
            away_rows.append(
                {
                    "pts_for": espn_a["pts_for"],
                    "pts_against": espn_a["pts_against"],
                    "confidence": 0.65,
                    "source": espn_a["source"],
                    "pace": espn_a["pace"],
                    "stdev": espn_a["stdev"],
                    "n_games": espn_a["n_games"],
                }
            )

        # 3) API-Sports statistics (yüksek ağırlık)
        api_h = await self._api_sports_team_baseline(req.league, req.home, season)
        if api_h:
            home_rows.append(
                {
                    "pts_for": api_h["pts_for"],
                    "pts_against": api_h["pts_against"],
                    "confidence": 0.85,
                    "source": api_h["source"],
                    "pace": api_h["pace"],
                    "stdev": api_h["stdev"],
                    "n_games": api_h.get("n_games"),
                }
            )

        api_a = await self._api_sports_team_baseline(req.league, req.away, season)
        if api_a:
            away_rows.append(
                {
                    "pts_for": api_a["pts_for"],
                    "pts_against": api_a["pts_against"],
                    "confidence": 0.85,
                    "source": api_a["source"],
                    "pace": api_a["pace"],
                    "stdev": api_a["stdev"],
                    "n_games": api_a.get("n_games"),
                }
            )

        # 4) Aggregate
        home_base = self._aggregate(home_rows)
        away_base = self._aggregate(away_rows)

        # 5) Guaranteed fallback (asla 0–0 dönmesin)
        degraded_mode = False
        if not home_base:
            avg = _league_avg_baseline(req.league)
            home_base = {
                "pts_for": avg["pts_for"],
                "pts_against": avg["pts_against"],
                "pace": avg["pace"],
                "stdev": avg["stdev"],
                "confidence": 0.25,
                "sources": ["LEAGUE_AVG"],
                "n_games": None,
            }
            degraded_mode = True
            notes.append("Home baseline missing → LEAGUE_AVG applied")

        if not away_base:
            avg = _league_avg_baseline(req.league)
            away_base = {
                "pts_for": avg["pts_for"],
                "pts_against": avg["pts_against"],
                "pace": avg["pace"],
                "stdev": avg["stdev"],
                "confidence": 0.25,
                "sources": ["LEAGUE_AVG"],
                "n_games": None,
            }
            degraded_mode = True
            notes.append("Away baseline missing → LEAGUE_AVG applied")

        # 6) Final math
        h_pf = float(home_base["pts_for"])
        h_pa = float(home_base["pts_against"])
        a_pf = float(away_base["pts_for"])
        a_pa = float(away_base["pts_against"])

        home_mu = (h_pf + a_pa) / 2.0
        away_mu = (a_pf + h_pa) / 2.0
        total_mu = home_mu + away_mu

        total_band = (int(total_mu - profile.band_hw_total), int(total_mu + profile.band_hw_total))
        home_band = (int(home_mu - profile.band_hw_team), int(home_mu + profile.band_hw_team))
        away_band = (int(away_mu - profile.band_hw_team), int(away_mu + profile.band_hw_team))

        pace_home = float(home_base.get("pace") or 99.5)
        pace_away = float(away_base.get("pace") or 99.5)
        pace_mean = (pace_home + pace_away) / 2.0

        tempo_flag = _tempo_flag_from_pace(pace_mean)
        quarters = _quarters_band(total_mu, profile.band_hw_total, tempo_flag)

        src_h = home_base.get("sources") or []
        src_a = away_base.get("sources") or []
        notes.append(f"Sources(home)={', '.join(map(str, src_h))}")
        notes.append(f"Sources(away)={', '.join(map(str, src_a))}")

        # confidence: daha düşük olanı al (temkin)
        conf_raw = float(min(home_base.get("confidence", 0.5), away_base.get("confidence", 0.5)))
        confidence_pct = round(max(0.0, min(1.0, conf_raw)) * 100.0, 1)

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=TeamAverages(h_pf, h_pa, pace_home, float(home_base.get("stdev") or 10.0)),
            away_avg=TeamAverages(a_pf, a_pa, pace_away, float(away_base.get("stdev") or 10.0)),
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters=quarters,
            blowout_risk="LOW",
            tempo_flag=tempo_flag,
            notes=notes,
            market={},
            meta={
                "engine": "FAZ-13 FINAL MULTI-SOURCE",
                "season": season,
                "confidence_pct": confidence_pct,
                "home_baseline_src": (src_h[0] if src_h else "none"),
                "away_baseline_src": (src_a[0] if src_a else "none"),
                "home_baseline_n": home_base.get("n_games"),
                "away_baseline_n": away_base.get("n_games"),
                "pace_mean": round(pace_mean, 2),
                "expected_total": round(total_mu, 2),
                "degraded_mode": degraded_mode,
                "fetched_at": int(time.time()),
            },
        )
