from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from baseline.team_baseline_store import TeamBaselineStore, TeamBaselineBootstrapper
from league_profiles import get_league_profile


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
                out.append(f"• {esc(n)}")

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
# FAZ-13 ENGINE (TEAM-FIRST)
# =====================================================

class Faz13Engine:
    """
    Patch hedefleri:
      1) Teams Endpoint tek kaynak
      2) Canonical Team Map otomatik üret (cache)
      3) Telegram string -> team_id resolve
      4) FAZ-13 artık string değil team_id ile stats çeksin

    Ek kritik düzeltme:
      - NBA season resolver düzeltildi (Ocak 2026 -> season 2025 olmalı)
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

        self.baseline_store = baseline_store
        self.min_baseline_games = int(min_baseline_games)

        self.baseline_bootstrapper: Optional[TeamBaselineBootstrapper] = None
        if self.baseline_store is not None:
            self.baseline_bootstrapper = TeamBaselineBootstrapper(self.baseline_store, None)

        # ---- Canonical team map cache ----
        # key: f"{LEAGUE}:{SEASON}"
        # value: {"ts": float, "team_map": {team_id: {...}}, "alias_index": {alias: team_id}}
        self._teammap_cache: Dict[str, Dict[str, Any]] = {}
        self._teammap_ttl_sec = int(os.getenv("FAZ13_TEAMMAP_TTL_SEC", "21600"))  # default 6h

        # NBA league id (API-Sports Basketball)
        # Not: API tarafında değişebilirse env ile override edilebilir.
        self._nba_league_id = int(os.getenv("API_SPORTS_NBA_LEAGUE_ID", "12"))

    # -------------------------------------------------
    # NBA SEASON RESOLVER  (FIXED)
    # -------------------------------------------------
    @staticmethod
    def resolve_nba_season(date_str: str) -> str:
        """
        NBA sezonu Ekim'de başlar.
          - 2026-01-02 => 2025 season (2025-26)
          - 2026-11-02 => 2026 season (2026-27)
        """
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
    # Canonical Team Map (Teams endpoint = single source of truth)
    # -------------------------------------------------
    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").strip().lower().replace("-", " ").replace("_", " ").split())

    def _cache_key(self, league: str, season: str) -> str:
        return f"{league.upper()}:{season}"

    def _teammap_cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._teammap_cache.get(key)
        if not entry:
            return None
        ts = float(entry.get("ts", 0))
        if (time.time() - ts) > self._teammap_ttl_sec:
            self._teammap_cache.pop(key, None)
            return None
        return entry

    def _teammap_cache_set(self, key: str, team_map: Dict[int, Dict[str, Any]], alias_index: Dict[str, int]) -> None:
        self._teammap_cache[key] = {
            "ts": time.time(),
            "team_map": team_map,
            "alias_index": alias_index,
        }

    async def _fetch_teams_for_league(self, league: str, season: str) -> List[Dict[str, Any]]:
        """
        Teams endpoint tek kaynak.
        NBA için: /teams?league=<NBA_ID>&season=<season>
        Diğer ligler için: /teams?search=... fallback ile tek tek çözüyoruz.
        """
        if not self.api_key:
            return []

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}

        # NBA: lig id ile tüm takımları çek (canonical map üretmek için ideal)
        if league.upper() == "NBA":
            try:
                async with s.get(
                    f"{self.base}/teams",
                    params={"league": self._nba_league_id, "season": season},
                    headers=headers,
                    timeout=20,
                ) as r:
                    js = await r.json()
            except Exception:
                return []
            return js.get("response") or []

        # Non-NBA: burada tüm takımları çekmek için lig id gerekebilir.
        # Mevcut mimariyi bozmamak için "full map" yerine resolver sırasında search kullanacağız.
        return []

    async def _build_canonical_team_map(self, league: str, season: str) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, int]]:
        """
        Returns:
          team_map: {team_id: {"id": int, "name": str, "code": str, "aliases": set[str]}}
          alias_index: {alias_norm: team_id}
        """
        ck = self._cache_key(league, season)
        cached = self._teammap_cache_get(ck)
        if cached:
            return cached["team_map"], cached["alias_index"]

        team_map: Dict[int, Dict[str, Any]] = {}
        alias_index: Dict[str, int] = {}

        teams = await self._fetch_teams_for_league(league, season)

        for t in teams:
            # API-Sports response bazen {"id":..,"name":..} veya {"team":{...}} şeklinde gelebilir.
            obj = t.get("team") if isinstance(t, dict) and "team" in t else t
            if not isinstance(obj, dict):
                continue

            team_id = obj.get("id")
            if not team_id:
                continue

            name = obj.get("name") or ""
            code = obj.get("code") or ""
            city = obj.get("city") or ""
            nickname = obj.get("nickname") or ""

            aliases = set()

            # En sağlam alias'lar:
            aliases.add(self._norm(name))
            if code:
                aliases.add(self._norm(code))
            if city and nickname:
                aliases.add(self._norm(f"{city} {nickname}"))
            if city and name:
                aliases.add(self._norm(f"{city} {name}"))
            if nickname:
                aliases.add(self._norm(nickname))

            team_map[int(team_id)] = {
                "id": int(team_id),
                "name": name,
                "code": code,
                "aliases": aliases,
            }

        # alias index
        for tid, info in team_map.items():
            for a in info.get("aliases", set()):
                if a:
                    # çakışma olursa ilk gelen kazanır (NBA'de genelde çakışmaz)
                    alias_index.setdefault(a, tid)

        self._teammap_cache_set(ck, team_map, alias_index)
        return team_map, alias_index

    async def _resolve_team_id(self, team_name: str, league: str, season: str) -> Optional[int]:
        """
        Telegram string -> canonical team_id
        NBA: canonical map üzerinden
        Non-NBA: mevcut davranışı bozmamak adına /teams?search=... ile çöz (tek kaynak yine teams endpoint)
        """
        if not self.api_key:
            return None

        key = self._norm(team_name)

        if league.upper() == "NBA":
            _, alias_index = await self._build_canonical_team_map(league, season)
            tid = alias_index.get(key)
            if tid:
                return tid

            # NBA fallback: teams search (hala teams endpoint)
            s = await self._get_session()
            headers = {"x-apisports-key": self.api_key}
            try:
                async with s.get(
                    f"{self.base}/teams",
                    params={"search": team_name},
                    headers=headers,
                    timeout=15,
                ) as r:
                    js = await r.json()
            except Exception:
                return None
            resp = js.get("response") or []
            if not resp:
                return None

            obj = resp[0].get("team") if isinstance(resp[0], dict) and "team" in resp[0] else resp[0]
            if isinstance(obj, dict) and obj.get("id"):
                return int(obj["id"])
            return None

        # Non-NBA: mevcut sistem bozulmasın diye direkt search
        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}
        try:
            async with s.get(
                f"{self.base}/teams",
                params={"search": team_name},
                headers=headers,
                timeout=15,
            ) as r:
                js = await r.json()
        except Exception:
            return None

        resp = js.get("response") or []
        if not resp:
            return None

        obj = resp[0].get("team") if isinstance(resp[0], dict) and "team" in resp[0] else resp[0]
        if isinstance(obj, dict) and obj.get("id"):
            return int(obj["id"])
        return None

    # -------------------------------------------------
    # API-Sports TEAM BASELINE (TEAM_ID FIRST)
    # -------------------------------------------------
    async def _api_sports_team_baseline_by_id(
        self, team_id: int, league: str, season: str
    ) -> Optional[Tuple[float, float, float, float, int]]:
        """
        Artık baseline stats çekimi team_id ile yapılır.
        """
        if not self.api_key:
            return None

        s = await self._get_session()
        headers = {"x-apisports-key": self.api_key}

        try:
            async with s.get(
                f"{self.base}/statistics",
                params={"team": int(team_id), "season": season},
                headers=headers,
                timeout=15,
            ) as r:
                js = await r.json()
        except Exception:
            return None

        resp = js.get("response") or {}
        pf = resp.get("points", {}).get("for", {}).get("average", {}).get("total")
        pa = resp.get("points", {}).get("against", {}).get("average", {}).get("total")

        if pf is None or pa is None:
            return None

        profile = get_league_profile(league)
        pace = max(0.8, min(1.3, (float(pf) + float(pa)) / 180.0))
        stdev = max(profile.volatility_floor, min(profile.volatility_ceil, 10.0))

        # n = 5 (mevcut dosyada sabitlenmişti, bozmadım)
        return float(pf), float(pa), pace, stdev, 5

    async def _api_sports_team_baseline(
        self, team: str, league: str, season: str
    ) -> Optional[Tuple[float, float, float, float, int]]:
        """
        Backward-compatible wrapper:
          - önce team_id resolve
          - sonra stats team_id ile çek
        """
        team_id = await self._resolve_team_id(team, league, season)
        if not team_id:
            return None
        return await self._api_sports_team_baseline_by_id(team_id, league, season)

    # -------------------------------------------------
    # MAIN PREMATCH (TEAM-FIRST)
    # -------------------------------------------------
    async def run_prematch(self, req: PrematchRequest) -> Faz13CoreOutput:
        profile = get_league_profile(req.league)

        season = (
            self.resolve_nba_season(req.date_str)
            if req.league.upper() == "NBA"
            else req.date_str[:4]
        )

        # 1) Telegram string -> team_id
        home_id = await self._resolve_team_id(req.home, req.league, season)
        away_id = await self._resolve_team_id(req.away, req.league, season)

        # TEAM-FIRST: takım id çözülemezse NO_PLAY (daha doğru hata)
        if not home_id or not away_id:
            ctx = FixtureContext(req.league, req.date_str, req.home, req.away)
            notes = ["NO_PLAY: TEAM_ID_RESOLVE_FAILED"]
            if not home_id:
                notes.append(f"Resolve failed (home): {req.home}")
            if not away_id:
                notes.append(f"Resolve failed (away): {req.away}")
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
                notes=notes,
                market={},
                meta={
                    "season": season,
                    "team_first": True,
                    "baseline_missing": True,
                    "team_id_missing": True,
                    "home_id": home_id,
                    "away_id": away_id,
                },
            )

        # 2) Baseline artık team_id ile çekilir
        h = await self._api_sports_team_baseline_by_id(home_id, req.league, season)
        a = await self._api_sports_team_baseline_by_id(away_id, req.league, season)

        # TEAM-FIRST: takım verisi yoksa NO_PLAY
        if not h or not a:
            ctx = FixtureContext(req.league, req.date_str, req.home, req.away)
            notes = ["NO_PLAY: TEAM_BASELINE_MISSING"]
            if not h:
                notes.append(f"Missing baseline (home_id={home_id})")
            if not a:
                notes.append(f"Missing baseline (away_id={away_id})")
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
                notes=notes,
                market={},
                meta={
                    "season": season,
                    "team_first": True,
                    "baseline_missing": True,
                    "home_id": home_id,
                    "away_id": away_id,
                },
            )

        h_avg = TeamAverages(h[0], h[1], h[2], h[3])
        a_avg = TeamAverages(a[0], a[1], a[2], a[3])

        home_mu = (h_avg.points_for + a_avg.points_against) / 2
        away_mu = (a_avg.points_for + h_avg.points_against) / 2
        total_mu = home_mu + away_mu

        total_band = (
            int(total_mu - profile.band_hw_total),
            int(total_mu + profile.band_hw_total),
        )
        home_band = (
            int(home_mu - profile.band_hw_team),
            int(home_mu + profile.band_hw_team),
        )
        away_band = (
            int(away_mu - profile.band_hw_team),
            int(away_mu + profile.band_hw_team),
        )

        ctx = FixtureContext(req.league, req.date_str, req.home, req.away)

        return Faz13CoreOutput(
            ctx=ctx,
            home_avg=h_avg,
            away_avg=a_avg,
            total_band=total_band,
            home_band=home_band,
            away_band=away_band,
            ou_direction="NO_EDGE",
            quarters={},
            blowout_risk="LOW",
            tempo_flag="NORMAL",
            notes=[
                f"Season: {season}",
                "TEAM-FIRST mode (API-Sports)",
                f"Resolved IDs: home_id={home_id} away_id={away_id}",
            ],
            market={},
            meta={
                "season": season,
                "team_first": True,
                "baseline_quality": 1.0,
                "home_id": home_id,
                "away_id": away_id,
            },
            ) 
