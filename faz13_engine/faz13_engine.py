# faz13_engine.py
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
        lines.append(f"Maç: {esc(self.ctx.home)} vs {esc(self.ctx.away)} | Lig: {esc(self.ctx.league)} | Tarih: {esc(self.ctx.date)}")
        lines.append("")
        lines.append("<b>Dar Bant</b>")
        lines.append(f"• Toplam: {self.total_band[0]}–{self.total_band[1]}")
        lines.append(f"• Ev: {self.home_band[0]}–{self.home_band[1]} | Dep: {self.away_band[0]}–{self.away_band[1]}")
        lines.append(f"• Alt/Üst yönü: {esc(self.ou_direction)}")
        lines.append("")
        lines.append("<b>Periyot Bantları</b>")
        for k in ["1Q", "2Q", "HT", "3Q", "4Q", "FT"]:
            if k in self.quarters:
                lo, hi = self.quarters[k]
                lines.append(f"• {k}: {lo}–{hi}")
        lines.append("")
        lines.append("<b>Risk Göstergeleri</b>")
        lines.append(f"• Blowout riski: {esc(self.blowout_risk)}")
        lines.append(f"• Tempo flag: {esc(self.tempo_flag)}")
        if self.notes:
            lines.append("")
            lines.append("<b>Notlar</b>")
            for n in self.notes:
                lines.append(f"• {esc(n)}")
        if self.market:
            lines.append("")
            lines.append("<b>Market Entegrasyonu</b>")
            for k, v in self.market.items():
                lines.append(f"• {esc(str(k))}: {esc(str(v))}")
        if self.meta:
            lines.append("")
            lines.append("<b>Meta Skor</b>")
            for k, v in self.meta.items():
                lines.append(f"• {esc(str(k))}: {esc(str(v))}")
        lines.append("")
        lines.append("<i>Bu çıktı analiz/simülasyon amaçlıdır. Bahis tavsiyesi değildir.</i>")
        return "\n".join(lines)

class _TTLCache:
    def __init__(self, ttl_sec: float = 25.0) -> None:
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
        self.cache = _TTLCache()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session and not self.session.closed:
            return self.session
        self.session = aiohttp.ClientSession()
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
        headers = {"x-apisports-key": self.api_key}
        for attempt in range(4):
            try:
                async with s.get(f"{self.base}{path}", params=params, headers=headers) as resp:
                    data = await resp.json()
                    if resp.status >= 500:
                        raise RuntimeError(f"API-Sports error {resp.status}")
                    self.cache.set(key, data)
                    return data
            except Exception:
                await asyncio.sleep(0.3 * (2**attempt))
        raise RuntimeError("API-Sports request failed")

    async def _team_baseline(self, team: str, league: str, season: str) -> Tuple[TeamAverages, str, int]:
        profile = get_league_profile(league)
        team_id = None

        # find team_id
        try:
            res = await self._api_get("/teams", {"search": team})
            t_resp = res.get("response") or []
            if t_resp:
                for t in t_resp:
                    nm = (t.get("name") or "").strip().lower()
                    if nm == team.lower().strip():
                        team_id = int(t.get("id"))
                        break
                if team_id is None:
                    team_id = int(t_resp[0]["id"])
        except Exception:
            team_id = None

        # statistics
        if team_id is not None:
            try:
                stats = await self._api_get("/statistics", {"team": team_id, "league": league, "season": season})
                r = stats.get("response") or {}
                pf = self._dig(r, ["points", "for", "average", "total"])
                pa = self._dig(r, ["points", "against", "average", "total"])
                if pf is not None and pa is not None:
                    pace = max(0.85, min(1.20, (pf + pa) / 180.0))
                    pace = max(0.70, min(1.35, pace * profile.pace_scale))
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, 9.0))
                    return TeamAverages(pf, pa, pace, stdev), "statistics", 0
            except Exception:
                pass

        # games last5
        if team_id is not None:
            try:
                games = await self._api_get("/games", {"team": team_id, "last": 5})
                resp = games.get("response") or []
                scored, allowed = [], []
                for g in resp:
                    s = g.get("scores") or {}
                    h = s.get("home") or {}
                    a = s.get("away") or {}
                    ht = h.get("total")
                    at = a.get("total")
                    if ht is None or at is None:
                        continue
                    teams = g.get("teams") or {}
                    hn = (teams.get("home") or {}).get("name", "").strip().lower()
                    an = (teams.get("away") or {}).get("name", "").strip().lower()
                    if hn == team.lower().strip():
                        scored.append(float(ht))
                        allowed.append(float(at))
                    elif an == team.lower().strip():
                        scored.append(float(at))
                        allowed.append(float(ht))
                if scored and allowed:
                    pf = sum(scored) / len(scored)
                    pa = sum(allowed) / len(allowed)
                    pace = max(0.85, min(1.20, (pf + pa) / 180.0))
                    pace = max(0.70, min(1.35, pace * profile.pace_scale))
                    stdev = 9.0
                    if len(scored) >= 4:
                        mean = pf
                        var = sum((x - mean) ** 2 for x in scored) / (len(scored) - 1)
                        stdev = var ** 0.5
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, stdev))
                    return TeamAverages(pf, pa, pace, stdev), "games_last5", len(scored)
            except Exception:
                pass

        # no baseline found -> neutral baseline
        return TeamAverages(0.0, 0.0, 1.0, 9.0), "none", 0

    @staticmethod
    def _dig(obj: Any, path: List[str]) -> Optional[float]:
        cur = obj
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        try:
            return float(cur)
        except Exception:
            return None

    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)
        season = req.date_str.split("-")[0]

        (h_avg, h_src, h_n), (a_avg, a_src, a_n) = await asyncio.gather(
            self._team_baseline(req.home, req.league, season),
            self._team_baseline(req.away, req.league, season)
        )

        home_mu = (h_avg.points_for + a_avg.points_against) / 2
        away_mu = (a_avg.points_for + h_avg.points_against) / 2
        total_mu = home_mu + away_mu

        sigma = (h_avg.stdev_hint + a_avg.stdev_hint) / 2
        sigma = max(profile.volatility_floor, min(profile.volatility_ceil, sigma))
        pace = (h_avg.pace_hint + a_avg.pace_hint) / 2

        tempo_flag = "NORMAL"
        if pace > 1.12 and sigma < 9.0:
            tempo_flag = "FAKE_TEMPO_RISK"
        elif pace > 1.05:
            tempo_flag = "FAST"
        elif pace < 0.95:
            tempo_flag = "SLOW"

        gap = abs(home_mu - away_mu)
        blowout = "HIGH" if gap >= 12 else "MID" if gap >= 7 else "LOW"

        hw_total = profile.band_hw_total
        hw_team = profile.band_hw_team
        total_band = (int(round(total_mu - hw_total)), int(round(total_mu + hw_total)))
        home_band = (int(round(home_mu - hw_team)), int(round(home_mu + hw_team)))
        away_band = (int(round(away_mu - hw_team)), int(round(away_mu + hw_team)))

        ou_dir = "NO_EDGE"
        if tempo_flag in {"SLOW", "FAKE_TEMPO_RISK"} and blowout in {"MID", "HIGH"}:
            ou_dir = "ALT"
        elif tempo_flag == "FAST" and blowout == "LOW":
            ou_dir = "UST"

        quarters = self._quarter_bands(total_mu, hw_total)

        notes = [
            f"Profile: {profile.name}",
            f"Baseline(home)={h_src} n={h_n} | Baseline(away)={a_src} n={a_n}",
            f"μ(total)≈{total_mu:.1f}, σ≈{sigma:.1f}, pace≈{pace:.2f}",
            f"gap≈{gap:.1f} → blowout={blowout}"
        ]
        if h_src == "none" or a_src == "none":
            notes.append("UYARI: Team baseline alınamadı → neutral baseline (0/0) kullanıldı.")
        if ou_dir == "NO_EDGE":
            notes.append("Alt/Üst yönünde net edge yok: market çizgisi ile FAZ-17'de belirlenecek.")

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)
        meta = {
            "league_profile": profile.name,
            "home_baseline_src": h_src,
            "home_baseline_n": h_n,
            "away_baseline_src": a_src,
            "away_baseline_n": a_n,
        }

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=h_avg,
            away_avg=a_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction=ou_dir,
            quarters=quarters,
            blowout_risk=blowout,
            tempo_flag=tempo_flag,
            notes=notes,
            market={},
            meta=meta
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
