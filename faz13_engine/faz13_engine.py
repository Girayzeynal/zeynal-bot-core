"""
Faz13Engine – Core pre‑match analytics for basketball fixtures.

This module queries the API‑Sports Basketball API to gather basic team
statistics, computes expected points for each team, and derives a
predicted total along with a confidence band.  It detects blowout
risks and tempo anomalies and prepares a structured output used by
subsequent engines.

This implementation is intentionally lightweight – it fetches team
statistics on demand, applies simple heuristics to compute pace and
volatility, and produces a band around the expected total.  A TTL
cache prevents excessive API calls on repeated analyses.

The prediction does not rely on league averages; instead it uses the
offensive output and defensive allowance of each team directly.  See
``run_prematch`` for the workflow.
"""

from __future__ import annotations

import asyncio
import html
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


@dataclass(frozen=True)
class PrematchRequest:
    """Specification for a pre‑match analysis.

    ``fixture_id`` is kept for API compatibility but unused when league/date
    information is provided.  ``league`` should be an identifier or name
    understood by API‑Sports.  ``date_str`` is YYYY‑MM‑DD.  ``home`` and
    ``away`` are team names.
    """

    fixture_id: int
    league: str
    date_str: str
    home: str
    away: str


@dataclass
class TeamAverages:
    points_for: float
    points_against: float
    pace_hint: float  # Derived measure of pace (approx 0.85–1.20)
    stdev_hint: float  # Derived volatility measure (approx 7–18)


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
    ou_direction: str  # "ALT", "UST" or "NO_EDGE"
    quarters: Dict[str, Tuple[int, int]]
    blowout_risk: str  # LOW, MID, HIGH
    tempo_flag: str  # NORMAL, FAST, SLOW, FAKE_TEMPO_RISK
    notes: List[str] = field(default_factory=list)
    market: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def render_html(self) -> str:
        """Render a human‑readable HTML summary of the prediction."""
        esc = html.escape
        lines = []
        lines.append("<b>FAZ‑13 Ön Analiz</b>")
        lines.append(
            f"<b>Maç:</b> {esc(self.ctx.home)} vs {esc(self.ctx.away)} | <b>Lig:</b> {esc(self.ctx.league)} | <b>Tarih:</b> {esc(self.ctx.date)}"
        )
        lines.append("")
        lines.append("<b>Dar Bant</b>")
        lines.append(
            f"• Toplam: <b>{self.total_band[0]}–{self.total_band[1]}</b>"
        )
        lines.append(
            f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}"
        )
        lines.append(f"• Alt/Üst yönü: <b>{esc(self.ou_direction)}</b>")
        lines.append("")
        lines.append("<b>Periyot Bantları</b>")
        for key in ["1Q", "2Q", "HT", "3Q", "4Q", "FT"]:
            if key in self.quarters:
                lo, hi = self.quarters[key]
                lines.append(f"• {key}: {lo}–{hi}")
        lines.append("")
        lines.append("<b>Risk Göstergeleri</b>")
        lines.append(f"• Blowout riski: <b>{esc(self.blowout_risk)}</b>")
        lines.append(f"• Tempo flag: <b>{esc(self.tempo_flag)}</b>")
        if self.notes:
            lines.append("")
            lines.append("<b>Notlar</b>")
            for n in self.notes[:10]:
                lines.append(f"• {esc(n)}")
        if self.market:
            lines.append("")
            lines.append("<b>Market Entegrasyonu</b>")
            for k, v in list(self.market.items())[:10]:
                lines.append(f"• {esc(str(k))}: {esc(str(v))}")
        if self.meta:
            lines.append("")
            lines.append("<b>Meta Skor</b>")
            for k, v in list(self.meta.items())[:10]:
                lines.append(f"• {esc(str(k))}: {esc(str(v))}")
        lines.append("")
        lines.append(
            "<i>Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.</i>"
        )
        return "\n".join(lines)


class _TTLCache:
    """Simple TTL cache for API responses."""

    def __init__(self, ttl_sec: float = 20.0) -> None:
        self.ttl = ttl_sec
        self._data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        hit = self._data.get(key)
        if not hit:
            return None
        ts, val = hit
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.time(), value)


class Faz13Engine:
    """Core pre‑match analytics using API‑Sports basketball data."""

    def __init__(self, api_sports_key: str, api_sports_base: str) -> None:
        self.api_key = api_sports_key
        self.base = api_sports_base.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = _TTLCache(ttl_sec=30.0)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        timeout = aiohttp.ClientTimeout(total=18, connect=8)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def aclose(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def _api_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a GET request to API‑Sports with basic caching and retry."""
        key = f"{path}?{json.dumps(params, sort_keys=True)}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        url = f"{self.base}{path}"
        headers = {"x-apisports-key": self.api_key}
        s = await self._get_session()
        last_err: Optional[Exception] = None
        for attempt in range(4):
            try:
                async with s.get(url, params=params, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status >= 500:
                        raise RuntimeError(
                            f"API‑Sports {resp.status}: {text[:200]}"
                        )
                    data = json.loads(text) if text else {}
                    self.cache.set(key, data)
                    return data
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.35 * (2 ** attempt))
        raise RuntimeError(f"API‑Sports request failed: {last_err!s}")

    async def _team_season_averages(
        self, team_name: str, league: str, season: str
    ) -> TeamAverages:
        """Compute simple offensive/defensive averages for a team.

        This method uses the API‑Sports ``games`` endpoint as a best‑effort
        fallback to compute average points scored and allowed across the
        last 5 games.  If the API call fails, a failsafe prior is used.
        """
        # Try to map team name via search endpoint
        try:
            teams_data = await self._api_get("/teams", {"search": team_name})
            t_resp = teams_data.get("response") or []
            team_id = None
            for t in t_resp:
                if (t.get("name") or "").lower().strip() == team_name.lower().strip():
                    team_id = t.get("id")
                    break
            if not team_id and t_resp:
                team_id = t_resp[0].get("id")
        except Exception:
            team_id = None

        # Compute averages via games endpoint if team id exists
        pts_for: Optional[float] = None
        pts_against: Optional[float] = None
        if team_id:
            try:
                # last=5 returns last 5 games
                games = await self._api_get(
                    "/games", {"team": team_id, "last": 5}
                )
                resp = games.get("response") or []
                scored: List[float] = []
                allowed: List[float] = []
                for g in resp:
                    scores = g.get("scores", {})
                    if not isinstance(scores, dict):
                        continue
                    home = (scores.get("home") or {}) if isinstance(scores.get("home"), dict) else {}
                    away = (scores.get("away") or {}) if isinstance(scores.get("away"), dict) else {}
                    home_total = home.get("total")
                    away_total = away.get("total")
                    teams = g.get("teams", {})
                    h_name = ((teams.get("home") or {}).get("name") or "").strip().lower()
                    a_name = ((teams.get("away") or {}).get("name") or "").strip().lower()
                    # Determine if this team is home or away in this game
                    if h_name == team_name.lower().strip():
                        if home_total is not None:
                            scored.append(float(home_total))
                        if away_total is not None:
                            allowed.append(float(away_total))
                    elif a_name == team_name.lower().strip():
                        if away_total is not None:
                            scored.append(float(away_total))
                        if home_total is not None:
                            allowed.append(float(home_total))
                if scored:
                    pts_for = sum(scored) / len(scored)
                if allowed:
                    pts_against = sum(allowed) / len(allowed)
            except Exception:
                pts_for = None
                pts_against = None

        # Fallback: generic prior if API fails
        if pts_for is None or pts_against is None:
            # Generic prior values by league
            priors = {
                "NBA": (112.0, 112.0),
                "EUROLEAGUE": (80.0, 80.0),
                "TBSL": (82.0, 82.0),
            }
            pf, pa = priors.get(league.upper(), (88.0, 88.0))
            pts_for = pf
            pts_against = pa

        # Pace hint: normalised around 1.0; more possessions imply higher pace
        pace_hint = max(0.85, min(1.20, (pts_for + pts_against) / 180.0))
        # Volatility hint: difference between offense and defense proxies variance
        stdev_hint = max(7.0, min(18.0, 9.0 + 12.0 * abs(pts_for - pts_against) / 40.0))
        return TeamAverages(
            points_for=float(pts_for),
            points_against=float(pts_against),
            pace_hint=float(pace_hint),
            stdev_hint=float(stdev_hint),
        )

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        """Compute a pre‑match prediction and diagnostics.

        The workflow:
        1. Fetch team averages (offense/defense) for both teams.
        2. Compute expected points using the harmonic mean of each team’s
           offensive output and opponent’s defensive allowance.
        3. Derive a total band (± hw_total) and individual team bands.
        4. Determine tempo and blowout flags.
        5. Generate quarter splits for additional granularity.
        """
        league = req.league or "GLOBAL"
        date = req.date_str
        home = req.home
        away = req.away
        # Determine season (use year of date)
        season = req.date_str.split("-")[0]
        # Fetch team averages concurrently
        home_avg, away_avg = await asyncio.gather(
            self._team_season_averages(home, league, season),
            self._team_season_averages(away, league, season),
        )
        # Expected points: average of offense and opponent defense
        home_mu = (home_avg.points_for + away_avg.points_against) / 2.0
        away_mu = (away_avg.points_for + home_avg.points_against) / 2.0
        total_mu = home_mu + away_mu
        # Pace and volatility
        sigma = (home_avg.stdev_hint + away_avg.stdev_hint) / 2.0
        pace = (home_avg.pace_hint + away_avg.pace_hint) / 2.0
        # Tempo flag
        tempo_flag = "NORMAL"
        if pace > 1.12 and sigma < 9.0:
            tempo_flag = "FAKE_TEMPO_RISK"
        elif pace > 1.08:
            tempo_flag = "FAST"
        elif pace < 0.93:
            tempo_flag = "SLOW"
        # Blowout risk based on mean gap
        gap = abs(home_mu - away_mu)
        if gap >= 12:
            blowout_risk = "HIGH"
        elif gap >= 7:
            blowout_risk = "MID"
        else:
            blowout_risk = "LOW"
        # Band widths: derive from volatility; clamp to reasonable bounds
        hw_total = int(max(6, min(10, round((sigma / 3.2) * 2.0))))
        total_band = (int(round(total_mu - hw_total)), int(round(total_mu + hw_total)))
        hw_team = int(max(4, min(8, round((sigma / 4.2)))))
        home_band = (
            int(round(home_mu - hw_team)),
            int(round(home_mu + hw_team)),
        )
        away_band = (
            int(round(away_mu - hw_team)),
            int(round(away_mu + hw_team)),
        )
        # OU direction baseline
        ou_direction = "NO_EDGE"
        if tempo_flag in {"SLOW", "FAKE_TEMPO_RISK"} and blowout_risk in {"MID", "HIGH"}:
            ou_direction = "ALT"
        elif tempo_flag == "FAST" and blowout_risk == "LOW":
            ou_direction = "UST"
        # Quarter splits: proportional to typical scoring distribution
        quarters = self._quarter_bands(total_mu, hw_total)
        notes: List[str] = []
        notes.append(f"μ(total)≈{total_mu:.1f}, σ≈{sigma:.1f}, pace≈{pace:.2f}")
        notes.append(f"gap≈{gap:.1f} → blowout={blowout_risk}")
        if ou_direction == "NO_EDGE":
            notes.append(
                "Alt/Üst yönünde net edge yok: market çizgisi ile FAZ‑17’de belirlenecek."
            )
        ctx = FixtureContext(league=league, date=date, home=home, away=away)
        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=home_avg,
            away_avg=away_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction=ou_direction,
            quarters=quarters,
            blowout_risk=blowout_risk,
            tempo_flag=tempo_flag,
            notes=notes,
        )

    @staticmethod
    def _quarter_bands(total_mu: float, hw_total: int) -> Dict[str, Tuple[int, int]]:
        """Compute bands for individual quarters and halves."""
        splits = {
            "1Q": 0.24,
            "2Q": 0.26,
            "3Q": 0.25,
            "4Q": 0.25,
        }
        out: Dict[str, Tuple[int, int]] = {}
        for k, w in splits.items():
            mu = total_mu * w
            hw = max(2, int(round(hw_total * w)))
            out[k] = (int(round(mu - hw)), int(round(mu + hw)))
        out["HT"] = (
            out["1Q"][0] + out["2Q"][0],
            out["1Q"][1] + out["2Q"][1],
        )
        out["FT"] = (
            int(round(total_mu - hw_total)),
            int(round(total_mu + hw_total)),
        )
        return out
