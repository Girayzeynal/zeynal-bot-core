from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ================================================================
# Haber / barem cache konumu
# ================================================================

# İstersen fly.io volume içine maplersin:
#   fly volume: /data/faz13/news_cache.json
NEWS_CACHE_PATH = os.getenv(
    "FAZ13_NEWS_CACHE",
    "/data/faz13/news_cache.json"
)


# ================================================================
# Temel veri sınıfları
# ================================================================

@dataclass
class MatchMeta:
    """
    FAZ-13 / FAZ-23 için maç tanımı.

    book_main_total  : Kitapçının ana toplam baremi (ör: 165.5)
    book_alt_totals  : 164.5, 165.5, 166.5 ... gibi alt/üst serisi
                       (Nesine ekranındaki listeyi temsil eder)
    """
    league: str
    date: str
    home_team: str
    away_team: str
    book_main_total: Optional[float] = None
    book_alt_totals: Optional[List[float]] = None

    @property
    def match_key(self) -> str:
        return f"{self.league}|{self.date}|{self.home_team}-{self.away_team}"


@dataclass
class NewsSummary:
    """
    FAZ-13 / FAZ-23 God Layer'ın okuyacağı özet yapı.
    Gerçek haber entegrasyonu geldiğinde de bu şema bozulmayacak.
    """
    match_key: str
    league: str
    date: str
    home_team: str
    away_team: str

    injuries: Dict[str, Any]
    fatigue: Dict[str, Any]
    tempo: Dict[str, Any]
    total_view: Dict[str, Any]
    spread_view: Dict[str, Any]
    soft_score_range: Dict[str, Any]

    flags: List[str]
    confidence: float

    key_quotes: List[str]
    sources_used: List[str]


# ================================================================
# Cache yardımcıları
# ================================================================

def _load_cache() -> Dict[str, Any]:
    try:
        p = Path(NEWS_CACHE_PATH)
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        log.warning("FAZ-13 news cache okunamadı: %s", e)
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    """Şu an kullanılmıyor ama ileride manuel / admin komutu için hazır."""
    try:
        p = Path(NEWS_CACHE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("FAZ-13 news cache yazılamadı: %s", e)


# ================================================================
# Barem → yumuşak skor bandı
# ================================================================

def _barem_soft_range(
    book_main_total: Optional[float],
    book_alt_totals: Optional[List[float]],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Nesine ekranındaki alt/üst serisinden yumuşak skor bandı çıkarır.

    DÖNEN:
      (soft_low, soft_high, avg_line)

    Hiç barem yoksa hepsi None döner.
    """
    if not book_main_total and not book_alt_totals:
        return None, None, None

    vals: List[float] = []
    if isinstance(book_main_total, (int, float)):
        vals.append(float(book_main_total))

    if book_alt_totals:
        for v in book_alt_totals:
            try:
                vals.append(float(v))
            except Exception:
                continue

    if not vals:
        return None, None, None

    low = min(vals)
    high = max(vals)
    avg = sum(vals) / len(vals)

    return low, high, avg


# ================================================================
# Özellik kodlayıcı
# ================================================================

def encode_news_features(summary: NewsSummary) -> Dict[str, Any]:
    """
    NewsSummary → FAZ-13/FAZ-23 feature sözlüğü.

    Orchestrator şunları bekliyor:
      - news_total_avg_line
      - news_total_over_flag / news_total_under_flag
      - news_pace_high_flag / news_pace_low_flag
      - news_fatigue_diff
    """
    data = asdict(summary)

    total_view = data.get("total_view") or {}
    tempo = data.get("tempo") or {}
    fatigue = data.get("fatigue") or {}
    soft_range = data.get("soft_score_range") or {}

    consensus = str(total_view.get("consensus", "NEUTRAL")).upper()
    book_main = total_view.get("book_main_total")
    soft_low = soft_range.get("low")
    soft_high = soft_range.get("high")

    avg_line: float = 0.0
    if isinstance(book_main, (int, float)):
        avg_line = float(book_main)
    elif isinstance(soft_low, (int, float)) and isinstance(soft_high, (int, float)):
        avg_line = float((soft_low + soft_high) / 2.0)

    features: Dict[str, Any] = {
        "news_total_avg_line": float(avg_line) if avg_line else 0.0,
        "news_total_over_flag": consensus.startswith("OVER"),
        "news_total_under_flag": consensus.startswith("UNDER"),
        "news_pace_high_flag": str(tempo.get("pace_hint", "")).upper() == "HIGH",
        "news_pace_low_flag": str(tempo.get("pace_hint", "")).upper() == "LOW",
        "news_fatigue_diff": float(fatigue.get("diff", 0.0) or 0.0),
        # İleride FAZ-23 için ekstra sinyaller:
        "soft_low": soft_low,
        "soft_high": soft_high,
    }

    return features


# ================================================================
# Ana API
# ================================================================

def get_match_news(
    meta: MatchMeta,
    use_cache: bool = True,
) -> Tuple[NewsSummary, Dict[str, Any]]:
    """
    FAZ-13 / FAZ-23 için haber + barem özetini döndürür.

    ŞU ANDA:
      - Harici siteye istek ATMİYOR.
      - Eğer cache dosyasında kayıt yoksa
        'BASELINE_ONLY' modunda dummy özet üretir.
      - Yani artık 'NONEWSDATA' KULLANILMIYOR; yerine
        'SAFE_BASELINE' / 'BOOKTOTAL_ONLY' gibi flag'ler geliyor.

    İLERİDE:
      - Mackolik / Nesine / başka kaynaklardan scrape edip
        bu fonksiyonun içine entegre edebilirsin. Tek şart:
        NewsSummary şemasını bozmamak.
    """
    cache: Dict[str, Any] = {}
    record: Optional[Dict[str, Any]] = None

    if use_cache:
        cache = _load_cache()
        record = cache.get(meta.match_key)

    if record is not None:
        # Cache'ten yüklenen özet (manuel veya scraper ile doldurulmuş)
        try:
            summary = NewsSummary(
                match_key=meta.match_key,
                league=record.get("league", meta.league),
                date=record.get("date", meta.date),
                home_team=record.get("home_team", meta.home_team),
                away_team=record.get("away_team", meta.away_team),
                injuries=record.get("injuries", {}),
                fatigue=record.get("fatigue", {}),
                tempo=record.get("tempo", {"pace_hint": "MID"}),
                total_view=record.get("total_view", {"consensus": "NEUTRAL"}),
                spread_view=record.get("spread_view", {}),
                soft_score_range=record.get("soft_score_range", {}),
                flags=record.get("flags", ["CACHE_HIT"]),
                confidence=float(record.get("confidence", 0.6)),
                key_quotes=record.get("key_quotes", []),
                sources_used=record.get("sources_used", []),
            )
            features = encode_news_features(summary)
            return summary, features
        except Exception as e:
            log.warning(
                "FAZ-13 news cache kaydı bozuk (%s): %s",
                meta.match_key,
                e,
            )

    # ------------------------------------------------------------
    # BURASI: Haber yoksa çalışan SAFE BASELINE MODE
    # ------------------------------------------------------------
    soft_low, soft_high, avg_line = _barem_soft_range(
        meta.book_main_total,
        meta.book_alt_totals,
    )

    # Eğer sadece kitapçı baremi geldiyse:
    flags: List[str] = []
    if meta.book_main_total or meta.book_alt_totals:
        flags.append("BOOKTOTAL_ONLY")
    else:
        flags.append("SAFE_BASELINE")

    total_view: Dict[str, Any] = {
        "consensus": "NEUTRAL",
    }
    if meta.book_main_total is not None:
        total_view["book_main_total"] = float(meta.book_main_total)

    soft_score_range: Dict[str, Any] = {}
    if soft_low is not None and soft_high is not None:
        soft_score_range = {
            "low": float(soft_low),
            "high": float(soft_high),
        }

    summary = NewsSummary(
        match_key=meta.match_key,
        league=meta.league,
        date=meta.date,
        home_team=meta.home_team,
        away_team=meta.away_team,
        injuries={},
        fatigue={"diff": 0.0},
        tempo={"pace_hint": "MID"},
        total_view=total_view,
        spread_view={},
        soft_score_range=soft_score_range,
        flags=flags,
        confidence=0.3,  # baseline olduğu için düşük güven
        key_quotes=[],
        sources_used=[],
    )

    features = encode_news_features(summary)
    return summary, features
