# faz13_engine/faz13_god_layer.py
"""
FAZ-13 GOD LAYER (FORMATTER ONLY)

- FINAL PIPELINE ile UYUMLU
- Karar üretmez
- Skor / band / confidence değiştirmez
- Sadece çıktıyı okunabilir hale getirir

Bu dosya main.py tarafından OPSİYONEL olarak kullanılabilir.
"""

from typing import Dict, Any


def format_faz_output(faz13: Dict[str, Any], faz22: Dict[str, Any]) -> str:
    home = faz13.get("home", "?")
    away = faz13.get("away", "?")
    league = faz13.get("league", "?")
    date_str = faz13.get("date", "?")

    base_pred = faz13.get("base_pred")
    band = faz13.get("band", [])
    play = faz13.get("play", {})
    play_flag = play.get("play", True)
    play_risk = play.get("risk", "MID")

    meta_pred = faz22.get("meta_pred")
    rlow = faz22.get("range_low")
    rhigh = faz22.get("range_high")
    conf = faz22.get("confidence")

    return (
        f"🏀 {home} - {away}\n"
        f"🏷️ {league} | 📅 {date_str}\n\n"
        f"🧠 Base Total: {base_pred}\n"
        f"🎯 Band: {band}\n"
        f"🚦 Oynanır mı?: {play_flag} | Risk: {play_risk}\n\n"
        f"🧬 META:\n"
        f" • Final: {meta_pred}\n"
        f" • Band: [{rlow}, {rhigh}]\n"
        f" • Confidence: {conf}\n"
    )


__all__ = ["format_faz_output"]
