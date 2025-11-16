# ============================================================
#               FAZ-5 HEAVY ENGINE (STABİL ÇEKİRDEK)
# ============================================================

from __future__ import annotations
import random
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Literal


# ------------------------------------------------------------
# Mod tipleri
# ------------------------------------------------------------

HeavyMode = Literal["standard", "risk", "edge", "auto", "full"]


# ------------------------------------------------------------
# İç veri modeli
# ------------------------------------------------------------

@dataclass
class HeavyPick:
    id: str
    pick: str
    market: str
    league: str
    odds: float
    confidence: float
    edge: float
    recommended_stake: float
    note: str


# ------------------------------------------------------------
# Mode tabanlı parametre profilleri
# ------------------------------------------------------------

_MODE_CONFIG: Dict[str, Dict[str, Any]] = {
    "standard": {
        "base_conf": 0.63,
        "base_edge": 0.03,
        "max_stake": 2.0,
        "size": 4,
        "note": "Dengeli portföy (risk/getiri orta seviye)",
    },
    "risk": {
        "base_conf": 0.60,
        "base_edge": 0.05,
        "max_stake": 3.0,
        "size": 5,
        "note": "Yüksek risk / yüksek getirir odaklı portföy",
    },
    "edge": {
        "base_conf": 0.62,
        "base_edge": 0.06,
        "max_stake": 2.5,
        "size": 4,
        "note": "Edge odaklı value seçimler",
    },
    "auto": {
        "base_conf": 0.64,
        "base_edge": 0.03,
        "max_stake": 1.8,
        "size": 3,
        "note": "Otomatik dengeli ve kontrollü yapı",
    },
    "full": {
        "base_conf": 0.61,
        "base_edge": 0.035,
        "max_stake": 2.2,
        "size": 6,
        "note": "Geniş portföy – risk yayılımı yüksek",
    },
}


# ------------------------------------------------------------
# Clamp fonksiyonu
# ------------------------------------------------------------

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(val, hi))


# ------------------------------------------------------------
# Basit Kelly fraksiyon hesaplayıcı
# ------------------------------------------------------------

def _kelly_fraction(conf: float, odds: float) -> float:
    """
    conf: kazanma olasılığı (0-1)
    odds: decimal oran (ör: 1.70)
    """
    b = odds - 1.0
    p = conf
    q = 1.0 - p

    edge = b * p - q
    if edge <= 0:
        return 0.0

    frac = edge / b
    return _clamp(frac, 0.0, 1.0)


# ------------------------------------------------------------
# FAZ-5 geçici MOCK market havuzu (gerçek data gelene kadar)
# ------------------------------------------------------------

def _mock_market_pool() -> List[Dict[str, Any]]:
    teams = [
        ("Lakers", "Warriors"),
        ("Heat", "Knicks"),
        ("Celtics", "Nets"),
        ("Suns", "Clippers"),
    ]

    markets = [
        "ML",
        "HC -3.5",
        "HC +5.5",
        "TOTAL O 164.5",
        "TOTAL U 158.5",
    ]

    leagues = ["NBA", "EUROLEAGUE", "TURKEY BSL"]

    pool: List[Dict[str, Any]] = []
    gid = 1

    for home, away in teams:
        for m in markets:
            pool.append(
                {
                    "id": f"F5{gid:03d}",
                    "home": home,
                    "away": away,
                    "market": m,
                    "league": random.choice(leagues),
                    "odds": round(random.uniform(1.55, 2.20), 2),
                }
            )
            gid += 1

    return pool


# ------------------------------------------------------------
# Portföy üretici — seçilen moda göre
# ------------------------------------------------------------

def _build_portfolio_for_mode(mode: HeavyMode) -> List[HeavyPick]:
    cfg = _MODE_CONFIG[mode]

    base_conf = cfg["base_conf"]
    base_edge = cfg["base_edge"]
    max_stake = cfg["max_stake"]
    size = cfg["size"]

    pool = _mock_market_pool()
    random.shuffle(pool)

    portfolio: List[HeavyPick] = []

    for i, mk in enumerate(pool[:size], start=1):
        jitter = random.uniform(0.02, 0.04)

        conf = _clamp(base_conf + jitter, 0.52, 0.80)

        kelly_frac = _kelly_fraction(conf, mk["odds"])
        stake = round(_clamp(kelly_frac * max_stake, 0.25, max_stake), 2)

        implied_prob = 1.0 / mk["odds"]
        raw_edge = conf - implied_prob
        edge = round(raw_edge if raw_edge > 0 else base_edge, 3)

        pick_label = f"{mk['home']} vs {mk['away']} 🏀 {mk['market']}"

        portfolio.append(
            HeavyPick(
                id=mk["id"],
                pick=pick_label,
                market=mk["market"],
                league=mk["league"],
                odds=mk["odds"],
                confidence=round(conf, 3),
                edge=edge,
                recommended_stake=stake,
                note=cfg["note"],
            )
        )

    return portfolio


# ------------------------------------------------------------
# DIŞA AÇILAN ANA FONKSİYON
# ------------------------------------------------------------

def run_heavy_engine(mode: str = "standard") -> str:
    """
    FAZ-5 için tek giriş noktası.
    Telegram için hazır TEXT döner.
    """

    mode = (mode or "standard").lower().strip()

    if mode not in _MODE_CONFIG:
        return f"⚠️ Geçersiz FAZ-5 modu: {mode}"

    picks = _build_portfolio_for_mode(mode)
    cfg = _MODE_CONFIG[mode]

    header = [
        "🧠 *FAZ-5 Heavy Engine*",
        f"🎛 Mod: *{mode.upper()}*",
        f"ℹ️ Not: _{cfg['note']}_",
        "",
        "Seçilen maçlar:",
    ]

    lines: List[str] = []

    for p in picks:
        lines.append(
            "\n".join(
                [
                    f"📌 *{p.pick}*",
                    f"🏛 Lig: {p.league}",
                    f"📉 Oran: {p.odds}",
                    f"📈 Güven: *{int(p.confidence * 100)}%*",
                    f"💹 Edge: {p.edge}",
                    f"💰 Önerilen Stake: *{p.recommended_stake}u*",
                    f"📝 {p.note}",
                    "",
                ]
            )
        )

    text = "\n".join(header) + "\n\n" + "\n".join(lines)
    return text 
