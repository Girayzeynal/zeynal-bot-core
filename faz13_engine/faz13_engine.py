"""
Faz13Engine – Core pre-match analytics for basketball fixtures.

Lig profili entegrasyonu (league_profiles.py):
- Dar bant genişlikleri (total/team) lig bazlı
- pace_scale lig bazlı
- volatility (sigma) lig bazlı clamp
- Takım baseline kaynağı: statistics -> games(last5) -> league prior (son çare)
"""

from __future__ import annotations

import asyncio
import html
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from league_profiles import get_league_profile


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
        lines = []
        lines.append("<b>FAZ-13 Ön Analiz</b>")
        lines.append(
            f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}"
        )
        lines.append("")
        lines.append("<b>Dar Bant</b>")
        lines.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        lines.append(f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}")
        lines.append(f"• Alt/Üst yönü: {esc(self.ou_direction)}")

        lines.append("")
        lines.append("<b>Periyot Bantları</b>")
        for key in ["1Q", "2Q", "HT", "3Q", "4Q", "FT"]:
            if key in self.quarters:
                lo, hi = self.quarters[key]
                lines.append(f"• {key}: {lo}–{hi}")

        lines.append("")
        lines.append("<b>Risk Göstergeleri</b>")
        lines.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        lines.append(f"• Tempo flag: {esc(self.tempo_flag)}")

        if self.notes:
            lines.append("")
            lines.append("<b>Notlar</b>")
            for n in self.notes[:12]:
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
        lines.append("<i>Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.</i>")
        return "\n".join(lines)


class _TTLCache:
    def __init__(self, ttl_sec: float = 30.0) -> None:
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
    def __init__(self, api_sports_key: str, api_sports_base: str):
        self.api_key = api_sports_key
        self.base = api_sports_base.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = _TTLCache(ttl_sec=25.0)

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
        key = f"{path}?{json.dumps(params, sort_keys=True)}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        s = await self._get_session()
        url = f"{self.base}{path}"
        headers = {"x-apisports-key": self.api_key}

        last_err: Optional[Exception] = None
        for attempt in range(4):
            try:
                async with s.get(url, params=params, headers=headers) as resp:
                    txt = await resp.text()
                    if resp.status >= 500:
                        raise RuntimeError(f"API-Sports {resp.status}: {txt[:200]}")
                    data = json.loads(txt) if txt else {}
                    self.cache.set(key, data)
                    return data
            except Exception as e:
                last_err = e
                await asyncio.sleep(0.35 * (2**attempt))
        raise RuntimeError(f"API-Sports request failed: {last_err!s}")

    # -----------------------------
    # TEAM BASELINE (priority order)
    # statistics -> games(last5) -> league prior (last resort)
    # Returns: (TeamAverages, source_label, sample_size)
    # -----------------------------
    async def _team_baseline(self, team_name: str, league: str, season: str) -> Tuple[TeamAverages, str, int]:
        profile = get_league_profile(league)

        # --- 1) Resolve team_id via /teams search
        team_id: Optional[int] = None
        try:
            teams_data = await self._api_get("/teams", {"search": team_name})
            t_resp = teams_data.get("response") or []
            if t_resp:
                # best exact-ish match
                for t in t_resp:
                    nm = (t.get("name") or "").strip().lower()
                    if nm == team_name.strip().lower():
                        team_id = int(t.get("id"))
                        break
                if team_id is None:
                    team_id = int(t_resp[0].get("id"))
        except Exception:
            team_id = None

        # --- 2) Try /statistics if possible (team baseline)
        # Not all subscriptions/tiers expose same structure; we guard hard.
        if team_id is not None:
            try:
                # Many API-Sports products use: /statistics?team=&league=&season=
                stats = await self._api_get("/statistics", {"team": team_id, "season": season, "league": league})
                r = stats.get("response") or {}

                # Defensive parsing (structure varies). Try common shapes:
                pts_for = _dig_float(r, ["points", "for", "average", "total"]) or _dig_float(r, ["points", "for", "average"])
                pts_against = _dig_float(r, ["points", "against", "average", "total"]) or _dig_float(r, ["points", "against", "average"])

                if pts_for is not None and pts_against is not None:
                    pace_hint = max(0.85, min(1.20, (pts_for + pts_against) / 180.0))
                    pace_hint = max(0.70, min(1.35, pace_hint * profile.pace_scale))

                    # stdev_hint: keep stable but league-clamped later
                    stdev_hint = max(profile.volatility_floor, min(profile.volatility_ceil, 9.0))
                    return TeamAverages(float(pts_for), float(pts_against), float(pace_hint), float(stdev_hint)), "statistics", 0
            except Exception:
                pass

        # --- 3) Fallback: /games last 5 (team baseline from recent games)
        if team_id is not None:
            try:
                games = await self._api_get("/games", {"team": team_id, "last": 5})
                resp = games.get("response") or []
                scored: List[float] = []
                allowed: List[float] = []
                for g in resp:
                    scores = g.get("scores", {})
                    if not isinstance(scores, dict):
                        continue
                    home = scores.get("home") or {}
                    away = scores.get("away") or {}
                    if not isinstance(home, dict) or not isinstance(away, dict):
                        continue
                    ht = home.get("total")
                    at = away.get("total")
                    if ht is None or at is None:
                        continue

                    teams = g.get("teams", {}) or {}
                    h_name = ((teams.get("home") or {}).get("name") or "").strip().lower()
                    a_name = ((teams.get("away") or {}).get("name") or "").strip().lower()

                    if h_name == team_name.strip().lower():
                        scored.append(float(ht))
                        allowed.append(float(at))
                    elif a_name == team_name.strip().lower():
                        scored.append(float(at))
                        allowed.append(float(ht))

                if scored and allowed:
                    pts_for = sum(scored) / len(scored)
                    pts_against = sum(allowed) / len(allowed)
                    pace_hint = max(0.85, min(1.20, (pts_for + pts_against) / 180.0))
                    pace_hint = max(0.70, min(1.35, pace_hint * profile.pace_scale))

                    # stdev hint from spread of points (simple proxy)
                    # if sample small, use mid
                    if len(scored) >= 4:
                        mean = pts_for
                        var = sum((x - mean) ** 2 for x in scored) / max(1, (len(scored) - 1))
                        stdev = var ** 0.5
                    else:
                        stdev = 9.0
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, stdev))
                    return TeamAverages(float(pts_for), float(pts_against), float(pace_hint), float(stdev)), "games_last5", len(scored)
            except Exception:
                pass

        # --- 4) LAST RESORT: league prior
        priors = {
            "NBA": (112.0, 112.0),
            "EUROLEAGUE": (80.0, 80.0),
            "TBL": (82.0, 82.0),
            "TBSL": (82.0, 82.0),
            "FIBA": (78.0, 78.0),
        }
        pf, pa = priors.get(league.upper(), (88.0, 88.0))
        pace_hint = max(0.70, min(1.35, 0.95 * profile.pace_scale))
        stdev_hint = max(profile.volatility_floor, min(profile.volatility_ceil, 9.0))
        return TeamAverages(float(pf), float(pa), float(pace_hint), float(stdev_hint)), "league_prior", 0

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        league = req.league or "GLOBAL"
        date = req.date_str
        home = req.home
        away = req.away
        season = req.date_str.split("-")[0]

        (home_avg, home_src, home_n), (away_avg, away_src, away_n) = await asyncio.gather(
            self._team_baseline(home, league, season),
            self._team_baseline(away, league, season),
        )

        # Expected points from team offense vs opponent defense
        home_mu = (home_avg.points_for + away_avg.points_against) / 2.0
        away_mu = (away_avg.points_for + home_avg.points_against) / 2.0
        total_mu = home_mu + away_mu

        # Volatility (sigma) league-clamped
        sigma = (home_avg.stdev_hint + away_avg.stdev_hint) / 2.0
        sigma = max(profile.volatility_floor, min(profile.volatility_ceil, sigma))

        # Pace
        pace = (home_avg.pace_hint + away_avg.pace_hint) / 2.0

        # Tempo flag thresholds (generic, but pace already league-scaled)
        tempo_flag = "NORMAL"
        if pace > 1.12 and sigma < 9.0:
            tempo_flag = "FAKE_TEMPO_RISK"
        elif pace > 1.05:
            tempo_flag = "FAST"
        elif pace < 0.95:
            tempo_flag = "SLOW"

        # Blowout risk
        gap = abs(home_mu - away_mu)
        if gap >= 12:
            blowout_risk = "HIGH"
        elif gap >= 7:
            blowout_risk = "MID"
        else:
            blowout_risk = "LOW"

        # ✅ Dar bantlar lig profilinden
        hw_total = int(profile.band_hw_total)
        hw_team = int(profile.band_hw_team)

        total_band = (int(round(total_mu - hw_total)), int(round(total_mu + hw_total)))
        home_band = (int(round(home_mu - hw_team)), int(round(home_mu + hw_team)))
        away_band = (int(round(away_mu - hw_team)), int(round(away_mu + hw_team)))

        # OU direction baseline (still simple; FAZ-17 will lock it if market exists)
        ou_direction = "NO_EDGE"
        if tempo_flag in {"SLOW", "FAKE_TEMPO_RISK"} and blowout_risk in {"MID", "HIGH"}:
            ou_direction = "ALT"
        elif tempo_flag == "FAST" and blowout_risk == "LOW":
            ou_direction = "UST"

        quarters = self._quarter_bands(total_mu, hw_total)

        notes: List[str] = []
        notes.append(f"Profile: {profile.name} | band_total_hw={profile.band_hw_total} band_team_hw={profile.band_hw_team}")
        notes.append(f"Baseline(home)={home_src} n={home_n} | Baseline(away)={away_src} n={away_n}")
        notes.append(f"μ(total)≈{total_mu:.1f}, σ≈{sigma:.1f}, pace≈{pace:.2f}")
        notes.append(f"gap≈{gap:.1f} → blowout={blowout_risk}")
        if home_src == "league_prior" or away_src == "league_prior":
            notes.append("UYARI: Team baseline alınamadı → league prior kullanıldı (API/parametre/erişim kontrol edin).")
        if ou_direction == "NO_EDGE":
            notes.append("Alt/Üst yönünde net edge yok: market çizgisi ile FAZ-17’de belirlenecek.")

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
        splits = {"1Q": 0.24, "2Q": 0.26, "3Q": 0.25, "4Q": 0.25}
        out: Dict[str, Tuple[int, int]] = {}
        for k, w in splits.items():
            mu = total_mu * w
            hw = max(2, int(round(hw_total * w)))
            out[k] = (int(round(mu - hw)), int(round(mu + hw)))
        out["HT"] = (out["1Q"][0] + out["2Q"][0], out["1Q"][1] + out["2Q"][1])
        out["FT"] = (int(round(total_mu - hw_total)), int(round(total_mu + hw_total)))
        return out


def _dig_float(obj: Any, path: List[str]) -> Optional[float]:
    cur = obj
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    try:
        if cur is None:
            return None
        return float(cur)
    except Exception:
        return None
