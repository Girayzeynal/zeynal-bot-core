# faz6_engine/faz6_engine_main.py
# ============================================================
#                    FAZ-6 ENGINE ÇEKİRDEĞİ
# ============================================================

from __future__ import annotations

import math
import random
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Literal, Optional

Faz6Mode = Literal["test", "auto", "risk", "edge", "real", "balance"]


# ------------------------------------------------------------
#  İç veri modeli (FAZ-6 tahmin objesi)
# ------------------------------------------------------------

@dataclass
class Faz6Prediction:
    id: str
    pick: str
    market: str
    confidence: float
    edge: float
    recommended_stake: float
    league: Optional[str] = None
    note: Optional[str] = None


# ------------------------------------------------------------
#  Mode bazlı parametre profilleri
# ------------------------------------------------------------

_MODE_CONFIG = {
    "test": {
        "base_conf": 0.60,
        "base_edge": 0.02,
        "max_stake": 1.0,
        "size": 3,
        "note": "TEST MODU - CANLI PARA KULLANMA"
    },
    "auto": {
        "base_conf": 0.64,
        "base_edge": 0.03,
        "max_stake": 2.0,
        "size": 4,
        "note": "Otomatik dengeli portföy"
    },
    "risk": {
        "base_conf": 0.58,
        "base_edge": 0.05,
        "max_stake": 3.0,
        "size": 5,
        "note": "Yüksek risk / yüksek getirili yapı"
    },
    "edge": {
        "base_conf": 0.62,
        "base_edge": 0.06,
        "max_stake": 2.5,
        "size": 4,
        "note": "Edge odaklı value seçimler"
    },
    "real": {
        "base_conf": 0.67,
        "base_edge": 0.025,
        "max_stake": 2.0,
        "size": 3,
        "note": "Gerçek para senaryosu için konservatif yapı"
    },
    "balance": {
        "base_conf": 0.65,
        "base_edge": 0.035,
        "max_stake": 2.2,
        "size": 4,
        "note": "Risk / getiri dengeli portföy"
    },
}


# ------------------------------------------------------------
#  Yardımcı fonksiyonlar
# ------------------------------------------------------------

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _kelly_fraction(conf: float, odds: float) -> float:
    """
    Basit Kelly fraksiyonu. conf: kazanma olasılığı (0-1),
    odds: decimal oran (örn 1.70).
    """
    b = odds - 1.0
    p = conf
    q = 1.0 - p
    edge = b * p - q
    if edge <= 0:
        return 0.0
    frac = edge / b
    return _clamp(frac, 0.0, 1.0)


def _mock_market_pool() -> List[Dict[str, Any]]:
    """
    Gerçek data entegrasyonu yapılana kadar FAZ-6 çekirdeğinin
    TELEGRAM tarafını, kupon üretimini ve formatlayıcılarını
    test etmek için sentetik bir market havuzu üretir.
    """
    teams = [
        ("Lakers", "Warriors"),
        ("Celtics", "Bucks"),
        ("Real Madrid", "Barcelona"),
        ("Fenerbahçe", "Efes"),
        ("CSKA", "Olympiacos"),
        ("Heat", "Knicks"),
    ]
    markets = ["ML", "HC -3.5", "HC +5.5", "TOTAL O 164.5", "TOTAL U 158.5"]
    leagues = ["NBA", "EUROLEAGUE", "TURKEY BSL"]

    pool = []
    gid = 1
    for home, away in teams:
        for m in markets:
            pool.append(
                {
                    "id": f"G{gid:03d}",
                    "home": home,
                    "away": away,
                    "market": m,
                    "league": random.choice(leagues),
                    "odds": round(random.uniform(1.55, 2.30), 2),
                }
            )
            gid += 1
    return pool


def _build_portfolio_for_mode(mode: Faz6Mode) -> List[Faz6Prediction]:
    cfg = _MODE_CONFIG[mode]
    base_conf = cfg["base_conf"]
    base_edge = cfg["base_edge"]
    max_stake = cfg["max_stake"]
    size = cfg["size"]

    pool = _mock_market_pool()
    random.shuffle(pool)

    portfolio: List[Faz6Prediction] = []
    for i, mk in enumerate(pool[:size], start=1):
        # Confidence & edge varyasyon
        jitter = random.uniform(-0.04, 0.04)
        conf = _clamp(base_conf + jitter, 0.52, 0.78)

        odds = mk["odds"]
        kelly_frac = _kelly_fraction(conf, odds)
        # FAZ-6 için kelly'nin konservatif bir skalası
        stake = round(_clamp(kelly_frac * max_stake, 0.25, max_stake), 2)

        # Edge kabaca: (conf - implied_prob)
        implied_prob = 1.0 / odds
        edge = conf - implied_prob
        edge = round(edge if edge > 0 else base_edge, 3)

        pick_label = f"{mk['home']} vs {mk['away']} - {mk['market']}"

        portfolio.append(
            Faz6Prediction(
                id=f"F6-{mode.upper()}-{i:02d}",
                pick=pick_label,
                market=mk["market"],
                confidence=round(conf, 3),
                edge=edge,
                recommended_stake=stake,
                league=mk["league"],
                note=_MODE_CONFIG[mode]["note"],
            )
        )

    return portfolio


# ------------------------------------------------------------
#  DIŞA AÇILAN ANA FONKSİYON
# ------------------------------------------------------------

def run_faz6_engine(mode: Faz6Mode = "auto") -> Dict[str, Any]:
    """
    FAZ-6 için tek giriş noktası.
    main.py ve faz6_coupon bu fonksiyona göre çalışır.

    DÖNÜŞ ŞEMASI (STANDART):
    {
        "status": "ok" | "error",
        "mode": "<test|auto|risk|edge|real|balance>",
        "result": {
            "predictions": [ {Faz6Prediction dict}, ... ],
            "meta": {...opsiyonel...}
        }
    }
    """

    if mode not in _MODE_CONFIG:
        return {
            "status": "error",
            "mode": mode,
            "result": {},
            "detail": f"Geçersiz FAZ-6 modu: {mode}",
        }

    portfolio = _build_portfolio_for_mode(mode)

    return {
        "status": "ok",
        "mode": mode,
        "result": {
            "predictions": [asdict(p) for p in portfolio],
            "meta": {
                "size": len(portfolio),
                "profile": _MODE_CONFIG[mode],
            },
        },
    }
