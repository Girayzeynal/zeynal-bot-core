# faz13_engine/faz13_god_layer.py

from __future__ import annotations

from typing import Any, Dict, Optional


# ================================================================
# 🧮 YARDIMCI
# ================================================================
def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return None


# İleride faz17 ile daha derin entegrasyon istersek burada deneyebiliriz.
try:  # faz17_market_adjust'i bulabilirsek kullanırız, bulamazsak sorun olmaz.
    from faz17_engine.faz17_market_adjust import faz17_market_adjust as _faz17_market_adjust
except Exception:  # pragma: no cover - opsiyonel
    try:
        from faz17_engine.faz17_market import faz17_market_adjust as _faz17_market_adjust  # type: ignore
    except Exception:
        _faz17_market_adjust = None  # type: ignore


# ================================================================
# 👁‍🗨 GOD-LAYER CORE
# ================================================================
def run_faz13_with_god_layer(source_type: str, fusion_input: Dict[str, Any]) -> str:
    """
    GOD-LAYER:
    - normalize_* çıktısını alır (fusion_input)
    - conf / edge / bucket hesaplar
    - market adjust varsa onu da katar
    - Telegram'a gidecek metni üretir
    """
    meta = dict(fusion_input or {})
    meta.setdefault("league", "NBA")
    meta.setdefault("market", "FT TOTAL")

    league = str(meta.get("league", "NBA")).upper()
    direction = meta.get("direction")
    line = meta.get("line")
    odds = meta.get("odds")

    # ============================================================
    # 1) Baz conf / edge
    # ============================================================
    conf = 0.60
    edge = 0.03

    if direction and line is not None:
        conf += 0.03
        edge += 0.005

    if isinstance(odds, (int, float, str)):
        o = _safe_float(odds) or 1.80
        if o < 1.40:
            conf += 0.02
            edge -= 0.004
        elif o < 1.60:
            conf += 0.01
            edge -= 0.002
        elif o > 1.90:
            conf -= 0.02
            edge += 0.004

    if league in ("EUROLEAGUE", "EL"):
        edge += 0.002
    elif league in ("BSL", "TBL"):
        edge += 0.001

    # ============================================================
    # 2) Opsiyonel FAZ-17 MARKET ADJUST
    #    Eğer fusion_input içinde model_prob_over/under varsa ve
    #    faz17_market_adjust fonksiyonunu bulduysak kullanırız.
    # ============================================================
    model_prob_over = meta.get("model_prob_over")
    model_prob_under = meta.get("model_prob_under")

    if (
        _faz17_market_adjust is not None
        and isinstance(model_prob_over, (int, float))
        and isinstance(model_prob_under, (int, float))
        and isinstance(odds, (int, float))
        and isinstance(line, (int, float))
    ):
        try:
            # Over/Under olasılıklarını market ile harmanla
            market_info = _faz17_market_adjust(
                float(model_prob_over),
                float(model_prob_under),
                float(odds),   # over odds varsayımı
                float(odds),   # under odds varsayımı (yoksa aynı)
            )
            edge_over = market_info.get("edge_over")
            edge_under = market_info.get("edge_under")

            # Seçim yönüne göre edge'i al
            if isinstance(direction, str) and direction.upper().startswith("O"):
                if isinstance(edge_over, (int, float)):
                    edge = float(edge_over)
            elif isinstance(direction, str) and direction.upper().startswith("U"):
                if isinstance(edge_under, (int, float)):
                    edge = float(edge_under)

            # conf'u da hafifçe market edge'e göre ayarla
            if isinstance(edge, (int, float)):
                if edge > 0.05:
                    conf += 0.03
                elif edge < 0.02:
                    conf -= 0.02
        except Exception:
            # Market adjust opsiyonel; patlarsa görmezden gel.
            pass

    # ============================================================
    # 3) Conf / Edge clamp + bucket
    # ============================================================
    conf = max(0.50, min(0.80, conf))
    edge = max(0.01, min(0.06, edge))

    score = 0.6 * (conf / 0.63) + 0.4 * (edge / 0.035)
    if score < 0.95:
        bucket = "LOW"
    elif score < 1.10:
        bucket = "MID"
    else:
        bucket = "HIGH"

    profile = "SAFE" if bucket == "LOW" else ("BAL" if bucket == "MID" else "AGG")

    # ============================================================
    # 4) Label / format
    # ============================================================
    dir_label = "—"
    if isinstance(direction, str):
        d = direction.upper()
        if d == "U":
            dir_label = "ALT"
        elif d == "O":
            dir_label = "ÜST"

    if isinstance(line, (int, float)):
        line_part = f"{float(line):.1f}"
    else:
        line_part = "—"

    if isinstance(odds, (int, float)):
        odds_part = f"{float(odds):.2f}"
    else:
        odds_part = "—"

    header_map = {
        "manual": "📝 <b>FAZ-13 MANUAL</b>",
        "visual": "📸 <b>FAZ-13 VISUAL</b>",
        "live": "📡 <b>FAZ-13 LIVE</b>",
        "api": "🌐 <b>FAZ-13 API</b>",
    }
    header = header_map.get(source_type, "🤖 <b>FAZ-13</b>")

    body = (
        f"{header}\n\n"
        f"Lig   : <b>{league}</b>\n"
        f"Maç   : <b>{meta.get('home','HOME')} vs {meta.get('away','AWAY')}</b>\n"
        f"Pazar : <b>{meta.get('market','FT TOTAL')}</b>\n"
        f"Seçim : <b>{dir_label} {line_part}</b> @ <b>{odds_part}</b>\n\n"
        f"Güven : <b>{conf:.3f}</b>\n"
        f"Edge  : <b>{edge:.3f}</b>\n"
        f"Risk  : <b>{profile}</b> | Bucket: <b>{bucket}</b>\n"
    )

    return body
