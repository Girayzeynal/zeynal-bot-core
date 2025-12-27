"""
Re-implemented FAZ-13 pre-match analysis engine.

This implementation defines the data structures and engine used by the Telegram
bot to perform a basic pre-match analysis.  It intentionally avoids any
undefined API calls (such as `self.api.get_prematch_data`) and instead uses
simple heuristics to compute neutral baselines when no real team data is
available.  The goal is to provide a working example of the FAZ-13 engine
that returns a consistent `Faz13CoreOutput` object for use downstream.

If you have access to a real data source, you can implement your own
`TeamStatsAdapter` to fetch recent team averages and plug it into
`Faz13Engine`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

######################################################################
# Data classes
######################################################################


@dataclass
class PrematchRequest:
    """Input payload for pre‑match analysis."""

    user_id: int
    league: str
    date: str
    home: str
    away: str


@dataclass
class FixtureContext:
    """Context information for a fixture under analysis."""

    league: str
    date: str
    home: str
    away: str


@dataclass
class TeamAverages:
    """Aggregate statistics for a single team (recent average performance)."""

    league: str
    team: str
    n_games: int
    pts_for: float
    pts_against: float
    pace: float
    stdev_total: float


@dataclass
class Faz13CoreOutput:
    """Output of the pre‑match analysis engine."""

    ctx: FixtureContext
    home_band: List[int]
    away_band: List[int]
    total_band: List[int]
    tempo_flag: str
    blowout_risk: str
    ou_direction: str
    meta: Dict[str, Any]
    notes: List[str]
    # Additional fields for downstream enrichment
    market: Dict[str, Any] = field(default_factory=dict)
    home_avg: TeamAverages | None = None
    away_avg: TeamAverages | None = None
    quarters: List[int] | None = None

    def render_html(self) -> str:
        """
        Render this analysis as an HTML fragment suitable for Telegram.  Newline
        characters are used to separate sections; list items are prefixed
        with hyphens.  Bold and italic tags are preserved.
        """
        html_lines: List[str] = []
        # Heading
        html_lines.append("FAZ-13 Ön Analiz\n")
        # Fixture summary
        html_lines.append(
            f"Maç: {self.ctx.home} vs {self.ctx.away} | Lig: {self.ctx.league} | Tarih: {self.ctx.date}\n"
        )
        # Bands (if available)
        if self.total_band and len(self.total_band) == 2:
            html_lines.append(
                f"Toplam (Tahmin): {self.total_band[0]}–{self.total_band[1]}\n"
            )
        if self.home_band and len(self.home_band) == 2:
            html_lines.append(
                f"{self.ctx.home} Bant: {self.home_band[0]}–{self.home_band[1]}\n"
            )
        if self.away_band and len(self.away_band) == 2:
            html_lines.append(
                f"{self.ctx.away} Bant: {self.away_band[0]}–{self.away_band[1]}\n"
            )
        # Signals
        html_lines.append(
            f"Tempo: {self.tempo_flag} | Blowout riski: {self.blowout_risk}\n"
        )
        html_lines.append(f"Alt/Üst yönü: {self.ou_direction}\n")
        # Meta information (confidence and risk)
        conf = self.meta.get("confidence")
        risk = self.meta.get("risk")
        if conf is not None or risk is not None:
            parts: List[str] = []
            if conf is not None:
                parts.append(f"Güven: {conf}")
            if risk is not None:
                parts.append(f"Risk: {risk}")
            html_lines.append("" + " | ".join(parts) + "\n")
        # Notes
        if self.notes:
            html_lines.append("\nNotlar:")
            for note in self.notes:
                html_lines.append(f"\n- {note}")

        # Per-quarter bands and halftime band
        qb = self.meta.get("quarter_bands")
        if qb:
            html_lines.append("\n\nPeriyot Bantları\n")
            # 1st quarter
            q1 = qb.get("1q") or [0, 0]
            html_lines.append(f"1Q: {q1[0]}–{q1[1]}\n")
            # 2nd quarter
            q2 = qb.get("2q") or [0, 0]
            html_lines.append(f"2Q: {q2[0]}–{q2[1]}\n")
            # Half-time
            ht = qb.get("ht") or [0, 0]
            html_lines.append(f"HT: {ht[0]}–{ht[1]}\n")
            # 3rd quarter
            q3 = qb.get("3q") or [0, 0]
            html_lines.append(f"3Q: {q3[0]}–{q3[1]}\n")
            # 4th quarter
            q4 = qb.get("4q") or [0, 0]
            html_lines.append(f"4Q: {q4[0]}–{q4[1]}\n")
            # Full-time
            ft = self.total_band or [0, 0]
            html_lines.append(f"FT: {ft[0]}–{ft[1]}\n")
        return "".join(html_lines)


######################################################################
# Faz13Engine Implementation
######################################################################


class Faz13Engine:
    """
    Pre‑match analysis engine.

    This class takes either a `TeamStatsAdapter` implementation or an API key and
    base URL for a sports data API.  If a string API key is provided, a dummy
    adapter is used that returns no recent stats, causing neutral baselines to
    be used.  Downstream engines (FAZ‑17, FAZ‑22, FAZ‑23) can enrich and score
    the output produced here.
    """

    def __init__(self, stats_adapter_or_key: Any, base_url: Optional[str] = None) -> None:
        # For simplicity we do not implement a real TeamStatsAdapter here.  If
        # `stats_adapter_or_key` is not a string, we assume it provides a
        # `fetch_team_recent_aggregate` method; otherwise we ignore it.  Real
        # implementations should replace this stub with actual data fetching.
        self.adapter = None
        if not isinstance(stats_adapter_or_key, str):
            self.adapter = stats_adapter_or_key
        # When using a string key, we could initialise a default adapter here,
        # but for this example we keep it None to always use neutral baselines.

    def pre_analyze(self, league: str, home: str, away: str) -> Dict[str, Any]:
        """
        Compute baseline and band data for a fixture.

        This stub implementation returns neutral baselines when no real team
        statistics are available.  If you implement `TeamStatsAdapter` and
        assign it to `self.adapter`, you can fetch real aggregates here and
        calculate meaningful bands.
        """
        notes: List[str] = []
        issues: List[str] = []
        baseline: Dict[str, Any] = {}
        bands: Dict[str, Any] = {}
        signals: Dict[str, Any] = {}
        meta: Dict[str, Any] = {}

        # Attempt to fetch aggregates for home and away teams if an adapter is provided.
        home_avg = None
        away_avg = None
        if self.adapter is not None:
            try:
                home_data = self.adapter.fetch_team_recent_aggregate(league, home, 5)
                away_data = self.adapter.fetch_team_recent_aggregate(league, away, 5)
                if home_data:
                    home_avg = TeamAverages(
                        league=league,
                        team=home,
                        n_games=home_data.get("n_games", 0),
                        pts_for=home_data.get("pts_for", 0.0),
                        pts_against=home_data.get("pts_against", 0.0),
                        pace=home_data.get("pace", 0.0),
                        stdev_total=home_data.get("stdev_total", 0.0),
                    )
                if away_data:
                    away_avg = TeamAverages(
                        league=league,
                        team=away,
                        n_games=away_data.get("n_games", 0),
                        pts_for=away_data.get("pts_for", 0.0),
                        pts_against=away_data.get("pts_against", 0.0),
                        pace=away_data.get("pace", 0.0),
                        stdev_total=away_data.get("stdev_total", 0.0),
                    )
            except Exception:
                # If fetching fails, note the issue and fall back to neutral baseline.
                issues.append("fetch_error")

        # If no team averages are available, use neutral baseline (0/0) and note the issue.
        if home_avg is None or away_avg is None:
            issues.append("no_team_data")
            notes.append(
                "UYARI: Team baseline alınamadı → neutral baseline (0/0) kullanıldı."
            )
            # Use simple neutral baseline: mu_total = 0, sigma_total = 9
            baseline = {"mu_total": 0.0, "sigma_total": 9.0, "pace": 1.0}
            bands = {"ft": [0, 0]}
            # Set neutral quarter and half-time bands as 0-0 as well
            bands.update({"1q": [0, 0], "2q": [0, 0], "3q": [0, 0], "4q": [0, 0], "ht": [0, 0]})
            signals = {"tempo_flag": "NORMAL", "blowout_risk": "LOW", "alt_ust": "NO_EDGE"}
            meta = {"confidence": 63.0, "risk": self._risk_label(63.0, issues)}
            # store quarter bands in meta for rendering
            meta["quarter_bands"] = {"1q": [0, 0], "2q": [0, 0], "3q": [0, 0], "4q": [0, 0], "ht": [0, 0]}
        else:
            # If real data exists, compute a simple baseline using team averages.
            # Here we calculate the expected total as the average of points for and against.
            mu_total = (home_avg.pts_for + home_avg.pts_against + away_avg.pts_for + away_avg.pts_against) / 2.0
            baseline = {"mu_total": mu_total, "sigma_total": 9.0, "pace": (home_avg.pace + away_avg.pace) / 2.0}
            # Bands: ±6 points around mu_total
            lo = int(round(mu_total - 6))
            hi = int(round(mu_total + 6))
            bands = {"ft": [lo, hi]}
            # Also compute per-quarter bands (approximate) and half-time band
            q_lo = int(round(mu_total / 4.0 - 2))
            q_hi = int(round(mu_total / 4.0 + 2))
            ht_lo = int(round(mu_total / 2.0 - 4))
            ht_hi = int(round(mu_total / 2.0 + 4))
            bands.update({"1q": [q_lo, q_hi], "2q": [q_lo, q_hi], "3q": [q_lo, q_hi], "4q": [q_lo, q_hi], "ht": [ht_lo, ht_hi]})
            # Simple tempo flag and blowout risk
            signals = {"tempo_flag": "NORMAL", "blowout_risk": "LOW", "alt_ust": "NO_EDGE"}
            meta = {"confidence": 70.0, "risk": self._risk_label(70.0, issues)}
            # store quarter bands in meta for rendering
            meta["quarter_bands"] = {"1q": [q_lo, q_hi], "2q": [q_lo, q_hi], "3q": [q_lo, q_hi], "4q": [q_lo, q_hi], "ht": [ht_lo, ht_hi]}
        return {
            "baseline": baseline,
            "bands": bands,
            "signals": signals,
            "meta": meta,
            "notes": notes,
        }

    def _risk_label(self, conf: float, issues: List[str]) -> str:
        """
        Determine a textual risk label based on confidence and known issues.
        """
        if "no_team_data" in issues:
            return "HIGH"
        if conf >= 75:
            return "LOW"
        if conf >= 60:
            return "MID"
        return "HIGH"

    async def run_prematch(self, request: PrematchRequest) -> Faz13CoreOutput:
        """
        Asynchronous wrapper around `pre_analyze` that returns a `Faz13CoreOutput`
        object.  This method does not perform any network I/O itself; it simply
        wraps the synchronous `pre_analyze` call to maintain compatibility with
        the asynchronous Telegram handler.
        """
        result = self.pre_analyze(request.league, request.home, request.away) or {}
        baseline: Dict[str, Any] = result.get("baseline", {}) or {}
        bands: Dict[str, Any] = result.get("bands", {}) or {}
        signals: Dict[str, Any] = result.get("signals", {}) or {}
        meta_info: Dict[str, Any] = result.get("meta", {}) or {}
        notes: List[str] = result.get("notes", []) or []

        # Determine total, home and away bands
        total_band: List[int] = bands.get("ft", [0, 0]) if isinstance(bands, dict) else [0, 0]
        mu_total: Optional[float] = baseline.get("mu_total")
        if isinstance(mu_total, (int, float)):
            home_band = [int(round(mu_total / 2.0 - 3)), int(round(mu_total / 2.0 + 3))]
            away_band = home_band.copy()
        else:
            lo, hi = total_band
            home_band = [int(round(lo / 2.0)), int(round(hi / 2.0))]
            away_band = home_band.copy()

        ctx = FixtureContext(
            league=request.league,
            date=request.date,
            home=request.home,
            away=request.away,
        )

        return Faz13CoreOutput(
            ctx=ctx,
            home_band=home_band,
            away_band=away_band,
            total_band=total_band,
            tempo_flag=signals.get("tempo_flag", "UNKNOWN"),
            blowout_risk=signals.get("blowout_risk", "UNKNOWN"),
            ou_direction=signals.get("alt_ust", "NO_EDGE"),
            meta=meta_info,
            notes=notes,
        ) 
