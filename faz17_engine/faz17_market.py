# faz17_engine/faz17_market.py

"""
FAZ-17 – MARKET RESISTANCE ENGINE

Amaç:
- Oran hareketlerinden "market resistance" sinyali üretmek.
- Sinyali FAZ-14 / FAZ-16 ile birlikte kullanıp
  nihai edge / stake ayarlamasında son filtre olması.

Girdi:
- odds_state: {
      "open": float,      # açılış oranı (ör: 1.70)
      "current": float,   # güncel oran (ör: 1.62)
      "implied_edge": float | None,  # daha önce hesaplanan edge
  }

Çıktı:
- {
    "market_shift": float,       # -0.3..+0.3 (negatif = oran düşmüş, favori güçlenmiş)
    "resistance": float,         # 0–1 (1 = market sinyali çok kuvvetli)
    "edge_adjust": float,        # -0.02..+0.02 (edge'e eklenebilir)
    "stance": "CONFIRM|CONTRA|NEUTRAL",
    "notes": str,
  }
"""

from __future__ import annotations

from typing import Dict, Any


def _sf(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def compute_market_resistance(odds_state: Dict[str, Any]) -> Dict[str, Any]:
    open_odds = _sf(odds_state.get("open", 0.0), 0.0)
    cur_odds = _sf(odds_state.get("current", 0.0), 0.0)
    implied_edge = _sf(odds_state.get("implied_edge", 0.0), 0.0)

    if open_odds <= 1.01 or cur_odds <= 1.01:
        return {
            "market_shift": 0.0,
            "resistance": 0.0,
            "edge_adjust": 0.0,
            "stance": "NEUTRAL",
            "notes": "insufficient_odds",
        }

    # Basit oran oranı
    ratio = cur_odds / open_odds  # <1: düşüş, >1: yükseliş
    market_shift = (1.0 - ratio) * 1.0  # -0.3..+0.3 bandına al
    market_shift = max(-0.3, min(0.3, market_shift))

    # Hareketin büyüklüğüne göre resistance
    magnitude = abs(market_shift)
    resistance = min(1.0, magnitude * 3.0)

    # Edge ayarı: market ile aynı yönde ise küçük boost,
    # ters yönde ise edge'i kes.
    edge_adjust = 0.0
    stance = "NEUTRAL"

    if implied_edge != 0.0:
        # Edge pozitif (biz fav görüyoruz)
        if implied_edge > 0:
            if market_shift > 0.02:  # oran düşmüş
                edge_adjust = min(0.02, implied_edge * 0.25)
                stance = "CONFIRM"
            elif market_shift < -0.02:  # oran yükselmiş
                edge_adjust = max(-0.02, -abs(implied_edge) * 0.35)
                stance = "CONTRA"
        # Edge negatif (fade etmeye çalışıyoruz) senaryosu için
        elif implied_edge < 0:
            if market_shift < -0.02:
                edge_adjust = min(0.02, abs(implied_edge) * 0.20)
                stance = "CONFIRM"
            elif market_shift > 0.02:
                edge_adjust = max(-0.02, -abs(implied_edge) * 0.30)
                stance = "CONTRA"

    notes = f"open={open_odds}, current={cur_odds}, ratio={ratio:.3f}"

    return {
        "market_shift": round(market_shift, 3),
        "resistance": round(resistance, 3),
        "edge_adjust": round(edge_adjust, 4),
        "stance": stance,
        "notes": notes,
    }
