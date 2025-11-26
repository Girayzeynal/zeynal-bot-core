# live_providers/provider_dummy.py
import time
from typing import Optional, Dict, Any


def fetch_live(query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Basit, her zaman sonuç üreten dummy provider.
    Amacı:
      - /live komutunun her zaman cevap vermesi
      - Ana mimariyi test etmek
    Gerçek canlı data sağlayıcıları eklendiğinde bile bu
    'fallback' olarak kalabilir.
    """
    league = (query.get("league") or "SIM").upper()
    home = (query.get("home") or "HOME").upper()
    away = (query.get("away") or "AWAY").upper()
    match_id = query.get("match_id") or "N/A"

    # Saat bazlı hafif değişen pseudo skor (tamamen kozmetik)
    now = int(time.time())
    home_score = 70 + (now % 15)
    away_score = 65 + (now % 10)
    period = f"Q{(now // 300) % 4 + 1}"  # 5 dakikada bir periyot değişiyormuş gibi
    clock = f"{(now // 60) % 10:02d}:{now % 60:02d}"

    win_side_label = "HOME" if home_score >= away_score else "AWAY"
    win_prob = 0.60 if win_side_label == "HOME" else 0.40
    pace = 98.5

    return {
        "league": league,
        "match_id": match_id,
        "home_name": home,
        "away_name": away,
        "home_score": home_score,
        "away_score": away_score,
        "period_label": period,
        "clock": clock,
        "status": "SIMULATED",
        "pace": pace,
        "win_side_label": win_side_label,
        "win_prob": win_prob,
        "provider": "DUMMY_SIM",
    }
