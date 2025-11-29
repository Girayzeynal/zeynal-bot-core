# faz13_engine/faz13_orchestrator.py

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ================================================================
# 🧮 YARDIMCI FONKSİYONLAR
# ================================================================
def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except Exception:
        return None


def _split_teams(tokens: List[str]) -> tuple[str, str]:
    """
    Takım isimlerini kabaca ikiye böler.
    BOS ORL 220.5 U 1.46 → BOS | ORL
    LOS ANGELES LAL BOS 220.5 → LOS ANGELES LAL | BOS
    """
    if not tokens:
        return "UNKNOWN", "UNKNOWN"

    if len(tokens) == 1:
        return tokens[0], "UNKNOWN"

    mid = len(tokens) // 2
    home = " ".join(tokens[:mid])
    away = " ".join(tokens[mid:])
    return home, away


# ================================================================
# 📝 MANUAL NORMALIZE
# ================================================================
def normalize_manual_text(
    text: str,
    default_league: str = "NBA",
) -> Dict[str, Any]:
    """
    Kullanıcıdan gelen metni normalize eder.
    Örnek:
        /mac BOS ORL 220.5 U 1.46
        BOS ORL 220.5 ALT 1.46
    """
    raw_text = (text or "").strip()

    # /mac prefix kırp
    if raw_text.startswith("/"):
        parts = raw_text.split(maxsplit=1)
        args = parts[1] if len(parts) > 1 else ""
    else:
        args = raw_text

    tokens = [t for t in args.replace("\n", " ").split(" ") if t.strip()]
    if not tokens:
        return {
            "source": "manual",
            "raw": raw_text,
            "league": default_league,
            "home": "UNKNOWN",
            "away": "UNKNOWN",
            "market": "FT TOTAL",
            "line": None,
            "direction": None,
            "odds": None,
        }

    # Sondaki sayıları line / odds gibi varsay
    floats_idx = [i for i, t in enumerate(tokens) if _safe_float(t) is not None]
    line: Optional[float] = None
    odds: Optional[float] = None
    direction: Optional[str] = None

    if floats_idx:
        if len(floats_idx) >= 2:
            line = _safe_float(tokens[floats_idx[-2]])
            odds = _safe_float(tokens[floats_idx[-1]])
        else:
            line = _safe_float(tokens[floats_idx[-1]])

        pos = floats_idx[-2] if len(floats_idx) >= 2 else floats_idx[-1]

        # Line etrafında yön (U/O/ALT/ÜST) ara
        if pos + 1 < len(tokens):
            d = tokens[pos + 1].upper()
            if d in ("U", "UNDER", "ALT"):
                direction = "U"
            elif d in ("O", "OVER", "UST", "ÜST"):
                direction = "O"
        if direction is None and pos - 1 >= 0:
            d = tokens[pos - 1].upper()
            if d in ("U", "UNDER", "ALT"):
                direction = "U"
            elif d in ("O", "OVER", "UST", "ÜST"):
                direction = "O"

        first_num_idx = floats_idx[0]
    else:
        first_num_idx = len(tokens)

    teams = tokens[:first_num_idx]
    home, away = _split_teams(teams)

    return {
        "source": "manual",
        "raw": raw_text,
        "league": default_league,
        "home": home,
        "away": away,
        "market": "FT TOTAL",
        "line": line,
        "direction": direction,
        "odds": odds,
    }


# ================================================================
# 📸 VISUAL NORMALIZE (OCR METNİ)
# ================================================================
def normalize_visual_meta(
    ocr_text: str,
    default_league: str = "NBA",
) -> Dict[str, Any]:
    """
    OCR'den gelen düz text'i normalize eder.
    Çok kaba ama dayanıklı bir parser.
    """
    text = (ocr_text or "").upper().replace("\n", " ")
    words = [w for w in text.split(" ") if w.strip()]

    if len(words) >= 2:
        home, away = words[0], words[1]
    else:
        home, away = "TEAM1", "TEAM2"

    # son 2–3 haneli sayı → line gibi düşün
    import re as _re

    nums = _re.findall(r"(\d{2,3}[.,]?\d*)", text)
    line = _safe_float(nums[-1]) if nums else None

    direction: Optional[str] = None
    if " ALT" in text or "UNDER" in text:
        direction = "U"
    elif " ÜST" in text or "UST" in text or "OVER" in text:
        direction = "O"

    return {
        "source": "visual",
        "raw": ocr_text,
        "league": default_league,
        "home": home,
        "away": away,
        "market": "FT TOTAL",
        "line": line,
        "direction": direction,
        "odds": None,
    }


# ================================================================
# 🌐 API / LIVE NORMALIZE
# ================================================================
def normalize_api_data(api_raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canlı / API veri sözlüğünü normalize eder.

    Beklenen alanlar esnek:
        league / lg
        home / home_team
        away / away_team
        market / mk / market_type
        line / total / over_under
        direction / pick / side  (O/U)
        odds / price / decimal_odds
    """
    data = dict(api_raw or {})

    league = (
        data.get("league")
        or data.get("lg")
        or data.get("competition")
        or "NBA"
    )
    league = str(league).upper()

    home = (
        data.get("home")
        or data.get("home_team")
        or data.get("team_home")
        or "HOME"
    )
    away = (
        data.get("away")
        or data.get("away_team")
        or data.get("team_away")
        or "AWAY"
    )

    market = (
        data.get("market")
        or data.get("market_type")
        or data.get("mk")
        or "FT TOTAL"
    )

    line = _safe_float(
        data.get("line")
        or data.get("total")
        or data.get("over_under")
        or data.get("points")
    )

    raw_dir = (
        data.get("direction")
        or data.get("pick")
        or data.get("side")
        or data.get("bet_on")
        or ""
    )
    d = str(raw_dir).upper()
    if d in ("U", "UNDER", "ALT"):
        direction = "U"
    elif d in ("O", "OVER", "UST", "ÜST"):
        direction = "O"
    else:
        direction = None

    odds = _safe_float(
        data.get("odds")
        or data.get("price")
        or data.get("decimal_odds")
        or data.get("odd")
    )

    # Model olasılıkları varsa içerde taşıyalım
    model_prob_over = data.get("model_prob_over")
    model_prob_under = data.get("model_prob_under")

    return {
        "source": "api",
        "raw": api_raw,
        "league": league,
        "home": home,
        "away": away,
        "market": market,
        "line": line,
        "direction": direction,
        "odds": odds,
        "model_prob_over": _safe_float(model_prob_over)
        if model_prob_over is not None
        else None,
        "model_prob_under": _safe_float(model_prob_under)
        if model_prob_under is not None
        else None,
    }


# ================================================================
# 🎛 FAZ-13 AUTO PIPELINE
# ================================================================
def run_faz13_auto_pipeline(source_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tek entrypoint: kaynağa göre ilgili normalize fonksiyonunu çağırır
    ve fusion çıktısını döner.
    """
    source_type = (source_type or "").lower()

    if source_type == "manual":
        fusion = normalize_manual_text(payload.get("text") or payload.get("raw") or "")
    elif source_type == "visual":
        fusion = normalize_visual_meta(payload.get("text") or payload.get("raw") or "")
    elif source_type in ("api", "live"):
        fusion = normalize_api_data(payload)
    else:
        # Bilinmeyen source: payload'ı fazla bozmadan dön
        fusion = dict(payload or {})
        fusion.setdefault("source", source_type or "unknown")

    return {
        "source": source_type,
        "fusion": fusion,
        "status": "OK",
    }


# ================================================================
# 🧾 FAZ-13 KUPON MOTORLARI (SKELETON v1)
# ================================================================
def _format_coupon_header(title: str) -> str:
    return f"🎟 <b>{title}</b>\n"


def _format_match_line(idx: int, m: Dict[str, Any]) -> str:
    """
    Tek satır kupon formatı:
    1) BOS–ORL | FT TOPLAM | ÜST 220.5 @1.72 | conf/edge
    """
    home = m.get("home", "HOME")
    away = m.get("away", "AWAY")
    market = m.get("market", "FT TOTAL")
    direction = m.get("direction_label", m.get("direction", "—"))
    line = m.get("line")
    odds = m.get("odds")
    conf = m.get("conf")
    edge = m.get("edge")
    bucket = m.get("bucket")

    if isinstance(line, (int, float)):
        line_str = f"{float(line):.1f}"
    else:
        line_str = "—"

    if isinstance(odds, (int, float)):
        odds_str = f"{float(odds):.2f}"
    else:
        odds_str = "—"

    extra = []
    if conf is not None:
        extra.append(f"conf={conf:.3f}")
    if edge is not None:
        extra.append(f"edge={edge:.3f}")
    if bucket:
        extra.append(f"bucket={bucket}")

    extra_str = " | ".join(extra) if extra else ""

    base = f"{idx}) {home}–{away} | {market} | {direction} {line_str} @ {odds_str}"
    if extra_str:
        base += f"  ({extra_str})"
    return base


def _build_coupon_body(ctx: Dict[str, Any], title: str) -> str:
    """
    ctx şu formatta olursa full çalışır:
        {
          "candidates": [
             {"home": ..., "away": ..., "market": ..., "direction": "ÜST",
              "line": 220.5, "odds": 1.72, "conf": 0.67, "edge": 0.035, "bucket": "MID"},
             ...
          ]
        }

    Eğer candidates yoksa bilgilendirici skeleton döner.
    """
    header = _format_coupon_header(title)
    cands = ctx.get("candidates") if isinstance(ctx, dict) else None

    if not cands:
        return (
            header
            + "\n"
            + "Şu an için kupon adayı listesi (ctx['candidates']) boş.\n"
            + "FAZ-13 çekirdeği çalışıyor, ama seçim yapması için aday maçları\n"
            + "faz17 / faz9 tarafında hazırlayıp buraya geçirmen gerekiyor."
        )

    lines: List[str] = [header, ""]
    for i, m in enumerate(cands, start=1):
        lines.append(_format_match_line(i, m))

    return "\n".join(lines)


def faz13_daily_coupon(ctx: Dict[str, Any]) -> str:
    """
    Günlük kupon – ctx içindeki 'candidates' listesini kullanır.
    """
    return _build_coupon_body(ctx or {}, "FAZ-13 DAILY COUPON")


def faz13_upcoming_coupon(ctx: Dict[str, Any]) -> str:
    """
    Yaklaşan maçlar kuponu.
    """
    return _build_coupon_body(ctx or {}, "FAZ-13 UPCOMING COUPON")


def faz13_league_coupon(ctx: Dict[str, Any]) -> str:
    """
    Lig bazlı kupon.
    """
    title = ctx.get("league_name") or "FAZ-13 LEAGUE COUPON"
    return _build_coupon_body(ctx or {}, title)


def faz13_live_coupon(ctx: Dict[str, Any]) -> str:
    """
    Canlı kupon – ileride live API ile birleşecek.
    """
    return _build_coupon_body(ctx or {}, "FAZ-13 LIVE COUPON")
