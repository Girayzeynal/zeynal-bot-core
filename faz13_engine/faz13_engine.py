# faz13_engine.py
from __future__ import annotations

import asyncio
import html
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import os  # Added for local stats support

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
        """
        Initialize the FAZ-13 engine.

        In addition to the API‑Sports parameters, this initializer attempts to
        load a local team statistics dataset.  If the environment variable
        ``TEAM_STATS_FILE`` is set, it will be used as the path to a JSON
        file containing per‑team averages.  Otherwise ``team_stats.json`` in
        the current working directory is attempted.  When present, these
        statistics are used to compute baselines instead of making remote
        API calls.
        """
        self.api_key = api_sports_key
        self.base = api_sports_base.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = _TTLCache()
        # Load optional local stats file
        stats_env = os.environ.get("TEAM_STATS_FILE")
        if stats_env:
            stats_path = stats_env
        else:
            # start with CWD
            cwd_default = os.path.join(os.getcwd(), "team_stats.json")
            if os.path.exists(cwd_default):
                stats_path = cwd_default
            else:
                # attempt to locate relative to this module's directory
                repo_default = os.path.join(os.path.dirname(__file__), "..", "..", "team_stats.json")
                stats_path = os.path.normpath(repo_default)
        self._team_stats: Dict[str, Dict[str, Any]] = {}
        try:
            if os.path.exists(stats_path):
                with open(stats_path, "r", encoding="utf-8") as f:
                    self._team_stats = json.load(f)
        except Exception:
            self._team_stats = {}

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
        # Check local stats first
        local = self._team_stats.get(season)
        if local:
            # Case‑insensitive match against keys
            for nm, rec in local.items():
                if nm.lower().strip() == team.lower().strip():
                    try:
                        pf = float(rec.get("points_for", 0.0))
                        pa = float(rec.get("points_against", 0.0))
                    except Exception:
                        pf = pa = 0.0
                    # Pace from record or derived
                    pace = rec.get("pace")
                    if pace is None:
                        pace = max(0.70, min(1.35, (pf + pa) / 180.0))
                    stdev = 9.0
                    # Local stats may include stdev_hint
                    if isinstance(rec.get("stdev"), (int, float)):
                        stdev = float(rec["stdev"])
                    stdev = max(profile.volatility_floor, min(profile.volatility_ceil, stdev))
                    return TeamAverages(pf, pa, pace, stdev), "local", int(rec.get("games", 0))
        team_id = None

        # fall back to remote API (statistics / last 5 games) if local not found
        ...
        # (geri kalan kısımda herhangi bir değişiklik yok, sadece yukarıda yerel veriye öncelik veriliyor)

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

        # ... (diğer hesaplamalar ve not ekleme işlemleri aynı şekilde devam ediyor) 
