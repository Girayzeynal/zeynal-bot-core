# ================================================================
# FAZ-13 GOD-LAYER
# Manual / Visual / Live fusion formatter
# ================================================================

import json
import logging
from typing import Any, Dict

log = logging.getLogger(__name__)


def _as_dict(obj: Any) -> Dict[str, Any]:
    """
    Gelen fusion objesini güvenli şekilde dict'e çevir.
    - dict ise direkt döner
    - string ise json.parse dene
    - olmazsa boş dict
    """
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except Exception:
            return {}
    return {}


def _fmt_float(x: Any, ndigits: int = 2) -> str:
    try:
        return f"{float(x):.{ndigits}f}"
    except Exception:
        return "-"


def _safe_get_any(d: Dict[str, Any], keys: list[str], default: Any = None) -> Any:
    """
    Birden fazla key adayından ilk bulunanı döndür.
    Örn: ["total", "barem", "total_line"]
    """
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


# ================================================================
# ANA GATEWAY
# ================================================================
def run_faz13_with_god_layer(input_kind: str, fusion: Any) -> str:
    """
    FAZ-13 GOD-LAYER
    =================
    Bu fonksiyon main.py tarafından çağrılır.

    input_kind:
      - "manual"
      - "visual"
      - "live"
      - vs.

    fusion:
      - normalize_manual_text / normalize_visual_meta / vs.'nin ürettiği
        dict benzeri yapı (veya string-json).

    Bu GOD-LAYER:
      - Çökmeyecek.
      - Elindeki fusion alanlarını okuyup insan-dostu formatta çıktı üretir.
      - Alanlar yoksa şikayet etmeyip sade bir özet yazar.
    """

    kind = (input_kind or "").upper()
    data = _as_dict(fusion)

    # ---------------------------------------------
    # Temel alanları tahmin etmeye çalış
    # ---------------------------------------------
    match_str = _safe_get_any(
        data,
        ["match", "match_name", "teams", "pair", "fixture"],
        default="Bilinmeyen Maç",
    )

    league = _safe_get_any(
        data,
        ["league", "lig", "competition"],
        default="-",
    )

    date = _safe_get_any(
        data,
        ["date", "tarih", "match_date"],
        default="-",
    )

    total_line = _safe_get_any(
        data,
        ["total", "barem", "total_line", "o_u_line"],
        default=None,
    )

    pick_side = _safe_get_any(
        data,
        ["pick", "side", "direction", "secim", "oy"],
        default=None,
    )

    odds = _safe_get_any(
        data,
        ["odds", "oran", "price"],
        default=None,
    )

    # Skor aralığı / hedef aralık
    low_bound = _safe_get_any(
        data,
        ["score_low", "range_low", "min_total", "target_min"],
        default=None,
    )
    high_bound = _safe_get_any(
        data,
        ["score_high", "range_high", "max_total", "target_max"],
        default=None,
    )

    # Confidence / risk / meta
    confidence = _safe_get_any(
        data,
        ["confidence", "conf", "risk_score"],
        default=None,
    )

    engine = _safe_get_any(
        data,
        ["engine", "model", "faz_engine"],
        default="FAZ-13",
    )

    # Debug reasons / açıklamalar
    reasons = _safe_get_any(
        data,
        ["reasons", "debug_reasons", "notes"],
        default=[],
    )
    if isinstance(reasons, str):
        reasons = [reasons]
    if not isinstance(reasons, list):
        reasons = []

    # Eğer FAZ-23 / news / provider füzyonu buraya da taşınmışsa,
    # bazı ekstra alanları da çekelim (sessizce, opsiyonel)
    news_consensus = _safe_get_any(
        data,
        ["news_total_consensus", "news_consensus"],
        default=None,
    )
    internal_score_vector = _safe_get_any(
        data,
        ["internal_score_vector", "score_vector"],
        default=None,
    )

    # ---------------------------------------------
    # ÇIKTIYI FORMATLA
    # ---------------------------------------------
    lines: list[str] = []

    lines.append(f"🧠 FAZ-13 GOD-LAYER [{kind}]")
    lines.append(f"⚙ Engine: {engine}")
    lines.append("")

    lines.append(f"🏀 Maç     : {match_str}")
    lines.append(f"🏆 Lig     : {league}")
    lines.append(f"📅 Tarih   : {date}")

    if total_line is not None or pick_side is not None or odds is not None:
        lines.append("")
        lines.append("🎯 Market / Seçim")
        if total_line is not None:
            lines.append(f"   • Toplam barem : {total_line}")
        if pick_side is not None:
            lines.append(f"   • Seçim        : {pick_side}")
        if odds is not None:
            lines.append(f"   • Oran         : {_fmt_float(odds)}")

    if low_bound is not None or high_bound is not None:
        lines.append("")
        lines.append("📊 Skor Aralığı Tahmini")
        lb = _fmt_float(low_bound) if low_bound is not None else "?"
        hb = _fmt_float(high_bound) if high_bound is not None else "?"
        lines.append(f"   • Hedef bant   : {lb}  —  {hb}")

    if confidence is not None:
        lines.append("")
        lines.append("🧪 Güven / Risk")
        lines.append(f"   • Confidence   : {_fmt_float(confidence, 3)}")

    if news_consensus is not None or internal_score_vector is not None:
        lines.append("")
        lines.append("🛰 İçsel Sinyaller")
        if news_consensus is not None:
            lines.append(f"   • News consensus : {news_consensus}")
        if internal_score_vector is not None:
            lines.append(f"   • Score vector   : {_fmt_float(internal_score_vector, 3)}")

    if reasons:
        lines.append("")
        lines.append("🔍 Gerekçeler / Notlar")
        for r in reasons:
            lines.append(f"   • {str(r)}")

    # Son olarak ham fusion'u debug bloğu olarak isteğe bağlı ekleyelim
    # (Telegram'da çok uzamasın diye condensed json)
    try:
        compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        compact = str(data)

    lines.append("")
    lines.append("🧾 RAW FUSION SNAPSHOT")
    if len(compact) > 1500:
        compact = compact[:1500] + "... (kısaltıldı)"
    lines.append(compact)

    return "\n".join(lines) 
