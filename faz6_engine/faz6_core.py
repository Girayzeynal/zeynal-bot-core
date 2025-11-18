"""
FAZ-6 Core Helpers
------------------
Bu dosya FAZ-6 için ortak çekirdek fonksiyonları tutar.

Amaç:
- Tüm modlar (test / risk / auto / balance / real / coupon)
  için ortak preset ve filtreleme mantığını tek yerde toplamak.
- Hiçbir network / I/O yapmaz. Sadece hesaplama yapar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


# ===========================
#  Preset Tanımı
# ===========================

@dataclass
class Faz6Preset:
    code: str               # örn: "test", "risk", "auto", "balance", "real", "coupon"
    title: str              # insan okunabilir isim
    min_confidence: float   # eşik: güven
    min_edge: float         # eşik: edge
    max_picks: Optional[int] = None   # maksimum seçim sayısı (None = sınırsız)


# Buradaki değerler güvenli, muhafazakâr default'lar.
# İleride FAZ-7 geçişinde sadece burayı değiştirerek
# tüm faz6_* dosyalarını güncellemek mümkün olacak.
PRESETS: Dict[str, Faz6Preset] = {
    "test": Faz6Preset(
        code="test",
        title="FAZ-6 TEST PRESET",
        min_confidence=0.55,
        min_edge=0.03,
        max_picks=5,
    ),
    "risk": Faz6Preset(
        code="risk",
        title="FAZ-6 RISK PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=7,
    ),
    "auto": Faz6Preset(
        code="auto",
        title="FAZ-6 AUTO PRESET",
        min_confidence=0.58,
        min_edge=0.04,
        max_picks=10,
    ),
    "balance": Faz6Preset(
        code="balance",
        title="FAZ-6 BALANCE PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=12,
    ),
    "real": Faz6Preset(
        code="real",
        title="FAZ-6 REAL PRESET",
        min_confidence=0.57,
        min_edge=0.035,
        max_picks=None,  # gerçek maç listesi serbest kalabilir
    ),
    "coupon": Faz6Preset(
        code="coupon",
        title="FAZ-6 COUPON PRESET",
        min_confidence=0.60,
        min_edge=0.04,
        max_picks=None,
    ),
}


def get_preset(code: str) -> Faz6Preset:
    """
    Verilen kod için preset döndürür.
    Bilinmeyen kod gelirse 'balance' preset'ini kullanır.
    """
    code = (code or "").lower().strip()
    if code in PRESETS:
        return PRESETS[code]
    return PRESETS["balance"]


# ===========================
#  Filtreleme ve Sıralama
# ===========================

def filter_and_rank_games(
    games: Iterable[Dict[str, Any]],
    preset: Faz6Preset,
) -> List[Dict[str, Any]]:
    """
    Ortak filtreleme mantığı:

    - game["confidence"]  >= preset.min_confidence
    - game["edge"]        >= preset.min_edge
    - confidence DESC + edge DESC sıralama
    - max_picks varsa, o kadar ile sınırla

    games içindeki elemanlar sözlük kabul edilir.
    Eksik alanlar varsa 0.0 gibi davranır; böylece
    hiçbir yerde KeyError patlamaz.
    """
    filtered: List[Dict[str, Any]] = []

    for game in games:
        try:
            conf = float(game.get("confidence", game.get("guven", 0.0)))
        except (TypeError, ValueError):
            conf = 0.0

        try:
            edge = float(game.get("edge", 0.0))
        except (TypeError, ValueError):
            edge = 0.0

        if conf < preset.min_confidence:
            continue
        if edge < preset.min_edge:
            continue

        filtered.append(game)

    # Güven → Edge sırasına göre tersten sırala
    filtered.sort(
        key=lambda g: (
            float(g.get("confidence", g.get("guven", 0.0))),
            float(g.get("edge", 0.0)),
        ),
        reverse=True,
    )

    if preset.max_picks is not None and len(filtered) > preset.max_picks:
        filtered = filtered[: preset.max_picks]

    return filtered


# ===========================
#  Format Yardımcıları
# ===========================

def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Her türlü tipi güvenle floata çevirir.
    Hata olursa default döner.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_pick_for_telegram(game: Dict[str, Any]) -> str:
    """
    Tek bir maçı Telegram mesajı satırı olarak formatlar.

    game sözlüğünde beklenen alanlar:
    - "label"      → 'NBA:LAC@PHX' gibi lig+maç kodu
    - "market_str" → 'LAC +7.5 (spread)' gibi market
    - "confidence" → 0.60
    - "edge"       → 0.04
    - "stake"      → 1.54

    Eksik alanlarda da çökmemesi için hepsi defansif yazılmıştır.
    """
    label = str(game.get("label") or game.get("match") or "UNKNOWN")
    market = str(game.get("market_str") or game.get("market") or "None")
    conf = safe_float(game.get("confidence", game.get("guven", 0.0)))
    edge = safe_float(game.get("edge", 0.0))
    stake = safe_float(game.get("stake", 0.0))

    lines = [
        f"📌 {label}",
        f"🎯 {market}",
        f"📈 Güven: {conf:.2f} | Edge: {edge:.3f}",
        f"💰 Stake: {stake:.3f}",
    ]
    return "\n".join(lines)

# ===========================
#  FAZ-6 TEST MODU
# ===========================

def run_faz6_test() -> dict:
    """
    FAZ-6 Test Engine
    Bu fonksiyon sadece test modunda çağrılır
    ve makinenin doğru çalıştığını doğrulamak için kullanılır.
    """
    print("FAZ-6 Test Engine Başlatıldı")

    return {
        "status": "ok",
        "engine": "faz6_core",
        "message": "FAZ-6 test başarıyla çalıştı."
    }
